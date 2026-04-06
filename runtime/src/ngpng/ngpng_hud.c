/* ngpng_hud.c -- HUD rendering (text, sprite digits, palette, state).
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 *
 * Sizing constants (NGPNG_AUTORUN_HUD_*) and NGPNG_HAS_PLAYER are injected
 * via Makefile CDEFS on export.  The #ifndef fallbacks below match the
 * default layout (HUD text palette 14, band palette 13, HUD sprite base 56).
 */
#include "ngpng_hud.h"

/* ---- Sizing fallbacks (real values come from Makefile CDEFS) ---- */
#ifndef NGPNG_AUTORUN_HUD_TEXT_PAL
#define NGPNG_AUTORUN_HUD_TEXT_PAL 14
#endif
#ifndef NGPNG_AUTORUN_HUD_BAND_PAL
#define NGPNG_AUTORUN_HUD_BAND_PAL 13
#endif
#ifndef NGPNG_AUTORUN_HUD_SPR_BASE
#define NGPNG_AUTORUN_HUD_SPR_BASE 56u
#endif

/* ==========================================================================
 * HUD (compiled only when NGPNG_HAS_PLAYER)
 * ========================================================================== */
#if NGPNG_HAS_PLAYER

/* ---- File-scope state ---- */
static char  s_hud_line0[32];
static char  s_hud_line1[32];
static char  s_hud_state_line[20];
static u8    s_hud_visible          = 0u;
static u16   s_hud_last_score       = 0xFFFFu;
static u8    s_hud_last_hp          = 0xFFu;
static u8    s_hud_last_lives       = 0xFFu;
static u16   s_hud_last_collectibles = 0xFFFFu;
static u16   s_hud_last_timer_sec   = 0xFFFFu;
static u8    s_hud_last_game_over   = 0xFFu;
static u8    s_hud_last_stage_clear = 0xFFu;

/* ---- Internal helpers ---- */

static void ngpng_hud_append(char *dst, u8 *pos, const char *src)
{
    u8 p;
    if (!dst || !pos || !src) return;
    p = *pos;
    while (*src && p < 20u) dst[p++] = *src++;
    dst[p] = 0;
    *pos = p;
}

static u16 ngpng_hud_color_rgb(u8 preset)
{
    switch (preset) {
        case 6u: return RGB(0,0,0);
        case 1u: return RGB(8,15,8);
        case 2u: return RGB(15,12,4);
        case 3u: return RGB(8,15,15);
        case 4u: return RGB(15,8,8);
        case 5u: return RGB(8,10,15);
        default: return RGB(15,15,15);
    }
}

static u16 ngpng_hud_color_rgb_dark(u8 preset)
{
    switch (preset) {
        case 6u: return RGB(0,0,0);
        case 1u: return RGB(3,8,3);
        case 2u: return RGB(8,5,1);
        case 3u: return RGB(2,7,7);
        case 4u: return RGB(8,3,3);
        case 5u: return RGB(2,3,7);
        default: return RGB(6,6,6);
    }
}

static u16 ngpng_hud_color_rgb_mid(u8 preset)
{
    switch (preset) {
        case 6u: return RGB(0,0,0);
        case 1u: return RGB(5,11,5);
        case 2u: return RGB(11,8,2);
        case 3u: return RGB(4,10,10);
        case 4u: return RGB(11,5,5);
        case 5u: return RGB(4,6,11);
        default: return RGB(10,10,10);
    }
}

static u16 ngpng_hud_band_rgb(u8 preset)
{
    switch (preset) {
        case 6u: return RGB(0,0,0);
        case 1u: return RGB(0,3,0);
        case 2u: return RGB(4,2,0);
        case 3u: return RGB(0,3,3);
        case 4u: return RGB(3,0,0);
        case 5u: return RGB(0,1,4);
        default: return RGB(15,15,15);
    }
}

static u16 ngpng_hud_metric_value(u8 metric, u16 score, u8 hp, u8 lives,
    u8 continues_left, u16 collectibles, u16 timer_sec)
{
    switch (metric) {
        case NGPNG_HUD_METRIC_HP:        return (u16)hp;
        case NGPNG_HUD_METRIC_SCORE:     return score;
        case NGPNG_HUD_METRIC_COLLECT:   return collectibles;
        case NGPNG_HUD_METRIC_TIMER:     return timer_sec;  /* OPT-E: pre-divided by caller */
        case NGPNG_HUD_METRIC_LIVES:     return (u16)lives;
        case NGPNG_HUD_METRIC_CONTINUES: return (u16)continues_left;
        default:                         return 0u;
    }
}

static void ngpng_hud_format_value(char *dst, u16 value, u8 digits, u8 zero_pad)
{
    u8 i;
    if (digits == 0u) digits = 1u;
    if (digits > 6u)  digits = 6u;
    for (i = 0u; i < digits; ++i) {
        dst[(u8)(digits - 1u - i)] = (char)('0' + (value % 10u));
        value = (u16)(value / 10u);
    }
    dst[digits] = 0;
    if (!zero_pad) {
        for (i = 0u; i + 1u < digits; ++i) {
            if (dst[i] != '0') break;
            dst[i] = ' ';
        }
    }
}

static u8 ngpng_hud_value_font_ready(const NgpSceneDef *sc, const char *buf, u8 digits)
{
    u8 i;
    if (!sc || !sc->hud_digit_types || !sc->draw_entity_anim) return 0u;
    for (i = 0u; i < digits; ++i) {
        char ch = buf[i];
        if (ch == ' ') continue;
        if (ch < '0' || ch > '9') return 0u;
        if (sc->hud_digit_types[(u8)(ch - '0')] == 255u) return 0u;
    }
    return 1u;
}

static void ngpng_hud_draw_value(const NgpSceneDef *sc, u8 hud_plane, u8 *spr_io,
    const NgpngHudItem *it, u16 value)
{
    char buf[7];
    u8 digits;
    u8 i;
    if (!it) return;
    digits = it->digits;
    if (digits == 0u) digits = 1u;
    if (digits > 6u)  digits = 6u;
    ngpng_hud_format_value(buf, value, digits,
        (u8)((it->flags & NGPNG_HUD_FLAG_ZERO_PAD) ? 1u : 0u));
    if (ngpng_hud_value_font_ready(sc, buf, digits)) {
        u8 spr = *spr_io;
        for (i = 0u; i < digits; ++i) {
            u8 next;
            char ch = buf[i];
            if (ch == ' ') continue;
            if (spr >= 64u) break;
            next = sc->draw_entity_anim(spr,
                sc->hud_digit_types[(u8)(ch - '0')], 0u,
                (s16)(((u16)it->x + i) * 8u), (s16)((u16)it->y * 8u));
            if (next <= spr || next > 64u) break;
            spr = next;
        }
        *spr_io = spr;
    } else {
        ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, it->x, it->y, "      ");
        ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, it->x, it->y, buf);
    }
}

/* ---- Public API ---- */

void ngpng_hud_apply_palettes(const NgpSceneDef *sc)
{
    u8  text_color = sc ? sc->hud_text_color : 0u;
    u8  band_color = sc ? sc->hud_band_color : 5u;
    u8  band_en    = (sc && sc->hud_style == NGPNG_HUD_STYLE_BAND) ? 1u : 0u;
    u16 bg   = band_en ? ngpng_hud_band_rgb(band_color) : RGB(0,0,0);
    u16 fg   = ngpng_hud_color_rgb(text_color);
    u16 mid  = ngpng_hud_color_rgb_mid(text_color);
    u16 dark = ngpng_hud_color_rgb_dark(text_color);
    ngpc_gfx_set_palette(GFX_SCR1, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, bg, fg, mid, dark);
    ngpc_gfx_set_palette(GFX_SCR2, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, bg, fg, mid, dark);
    ngpc_gfx_set_palette(GFX_SCR1, (u8)NGPNG_AUTORUN_HUD_BAND_PAL,
        ngpng_hud_band_rgb(band_color), ngpng_hud_band_rgb(band_color),
        ngpng_hud_band_rgb(band_color), ngpng_hud_band_rgb(band_color));
    ngpc_gfx_set_palette(GFX_SCR2, (u8)NGPNG_AUTORUN_HUD_BAND_PAL,
        ngpng_hud_band_rgb(band_color), ngpng_hud_band_rgb(band_color),
        ngpng_hud_band_rgb(band_color), ngpng_hud_band_rgb(band_color));
}

void ngpng_hud_reset(const NgpSceneDef *sc)
{
    u8 hud_plane;
    s_hud_visible           = 0u;
    s_hud_last_score        = 0xFFFFu;
    s_hud_last_hp           = 0xFFu;
    s_hud_last_lives        = 0xFFu;
    s_hud_last_collectibles = 0xFFFFu;
    s_hud_last_timer_sec    = 0xFFFFu;
    s_hud_last_game_over    = 0xFFu;
    s_hud_last_stage_clear  = 0xFFu;
    hud_plane = (sc && sc->hud_fixed_plane == NGPNG_HUD_FIXED_SCR2) ? GFX_SCR2 : GFX_SCR1;
    ngpng_hud_apply_palettes(sc);
    ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0,  0, "                    ");
    ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0,  1, "                    ");
    ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0,  2, "                    ");
    ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, 16, "                    ");
    ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, 17, "                    ");
    ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, 18, "                    ");
}

u8 ngpng_continue_restore_lives(const NgpSceneDef *sc)
{
    if (!sc) return 0u;
    if (sc->continue_restore_lives > 0u) return sc->continue_restore_lives;
    return sc->start_lives;
}

void ngpng_hud_sync(const NgpSceneDef *sc,
    u8 hud_flags, u8 hud_pos, u8 hud_font_mode,
    u16 score, u8 hp, u8 lives, u8 continues_left,
    u16 collectibles, u16 timer_sec,
    u8 game_over, u8 stage_clear)
{
    char num[6];
    /* OPT-E: timer_sec is pre-computed by the caller (timer/60 counter),
     * avoiding a software division on the T900 every frame. */
    u8  hud_plane = (sc && sc->hud_fixed_plane == NGPNG_HUD_FIXED_SCR2) ? GFX_SCR2 : GFX_SCR1;
    u8  pos0 = 0u;
    u8  pos1 = 0u;
    u8  row0 = (hud_pos == 1u) ? 16u : 0u;
    u8  row1 = (u8)(row0 + 1u);
    u8  row2 = (u8)(row0 + 2u);
    u8  hud_spr;
    u8  dirty;
    /* Hide HUD sprite slots (fast via shadow OAM — no direct VRAM write). */
    for (hud_spr = (u8)NGPNG_AUTORUN_HUD_SPR_BASE; hud_spr < 64u; ++hud_spr)
        ngpc_sprite_hide(hud_spr);
    /* Dirty check: skip all VRAM tilemap writes when nothing changed. */
    dirty = (u8)(!s_hud_visible
        || score        != s_hud_last_score
        || hp           != s_hud_last_hp
        || lives        != s_hud_last_lives
        || collectibles != s_hud_last_collectibles
        || timer_sec     != s_hud_last_timer_sec
        || game_over    != s_hud_last_game_over
        || stage_clear  != s_hud_last_stage_clear);
    /* Text mode: tilemap writes only when dirty. Sprite mode: always redraw. */
    if (!dirty && hud_font_mode == 0u) return;
    if (!s_hud_visible) s_hud_visible = 1u;
    /* ngpng_hud_apply_palettes is called once in ngpng_hud_reset — NOT every frame. */
    s_hud_line0[0] = 0;
    s_hud_line1[0] = 0;
    if (hud_font_mode == 0u && (hud_flags & 2u)) {
        ngpng_hud_format_value(num, (u16)hp, sc ? sc->hud_digits_hp : 2u, 0u);
        s_hud_line0[pos0++] = 'H'; s_hud_line0[pos0++] = 'P'; s_hud_line0[pos0++] = ':';
        ngpng_hud_append(s_hud_line0, &pos0, num);
    }
    if (hud_font_mode == 0u && (hud_flags & 1u)) {
        ngpng_hud_format_value(num, score, sc ? sc->hud_digits_score : 5u, 0u);
        if (pos0) s_hud_line0[pos0++] = ' ';
        s_hud_line0[pos0++] = 'S'; s_hud_line0[pos0++] = ':';
        ngpng_hud_append(s_hud_line0, &pos0, num);
    }
    if (hud_font_mode == 0u && (hud_flags & 16u)) {
        ngpng_hud_format_value(num, (u16)lives, sc ? sc->hud_digits_lives : 2u, 0u);
        if (pos0) s_hud_line0[pos0++] = ' ';
        s_hud_line0[pos0++] = 'L'; s_hud_line0[pos0++] = ':';
        ngpng_hud_append(s_hud_line0, &pos0, num);
    }
    s_hud_line0[pos0] = 0;
    if (hud_font_mode == 0u && (hud_flags & 4u)) {
        ngpng_hud_format_value(num, collectibles, sc ? sc->hud_digits_collect : 3u, 0u);
        s_hud_line1[pos1++] = 'C'; s_hud_line1[pos1++] = ':';
        ngpng_hud_append(s_hud_line1, &pos1, num);
    }
    if (hud_font_mode == 0u && (hud_flags & 8u)) {
        ngpng_hud_format_value(num, timer_sec, sc ? sc->hud_digits_timer : 3u, 0u);
        if (pos1) s_hud_line1[pos1++] = ' ';
        s_hud_line1[pos1++] = 'T'; s_hud_line1[pos1++] = ':';
        ngpng_hud_append(s_hud_line1, &pos1, num);
    }
    s_hud_line1[pos1] = 0;
    if (game_over) {
        s_hud_state_line[0]  = 'G'; s_hud_state_line[1]  = 'A'; s_hud_state_line[2]  = 'M'; s_hud_state_line[3]  = 'E';
        s_hud_state_line[4]  = ' '; s_hud_state_line[5]  = 'O'; s_hud_state_line[6]  = 'V'; s_hud_state_line[7]  = 'E'; s_hud_state_line[8]  = 'R';
        s_hud_state_line[9]  = ' '; s_hud_state_line[10] = 'B'; s_hud_state_line[11] = '=';
        if (continues_left > 0u) {
            s_hud_state_line[12] = 'C'; s_hud_state_line[13] = 'O'; s_hud_state_line[14] = 'N'; s_hud_state_line[15] = 'T';
            s_hud_state_line[16] = (char)('0' + ((continues_left / 10u) % 10u));
            s_hud_state_line[17] = (char)('0' + (continues_left % 10u));
            s_hud_state_line[18] = ' '; s_hud_state_line[19] = 0;
        } else {
            s_hud_state_line[12] = 'R'; s_hud_state_line[13] = 'E'; s_hud_state_line[14] = 'T';
            s_hud_state_line[15] = 'R'; s_hud_state_line[16] = 'Y';
            s_hud_state_line[17] = ' '; s_hud_state_line[18] = ' '; s_hud_state_line[19] = 0;
        }
        ngpc_gfx_fill_rect(hud_plane, 0u, row2, 20u, 1u, ' ', (u8)NGPNG_AUTORUN_HUD_TEXT_PAL);
        ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, row2, s_hud_state_line);
    } else if (stage_clear) {
        ngpc_gfx_fill_rect(hud_plane, 0u, row2, 20u, 1u, ' ', (u8)NGPNG_AUTORUN_HUD_TEXT_PAL);
        ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, row2, "STAGE CLEAR B=RETRY ");
    } else {
        ngpc_gfx_fill_rect(hud_plane, 0u, row2, 20u, 1u, ' ', (u8)NGPNG_AUTORUN_HUD_TEXT_PAL);
    }
    if (sc && sc->hud_style == NGPNG_HUD_STYLE_BAND) {
        u8 rows = sc->hud_band_rows;
        u8 i;
        if (rows == 0u) rows = 1u;
        if (rows > 3u)  rows = 3u;
        for (i = 0u; i < rows; ++i)
            ngpc_gfx_fill_rect(hud_plane, 0u, (u8)(row0 + i), 20u, 1u, ' ', (u8)NGPNG_AUTORUN_HUD_TEXT_PAL);
    } else {
        ngpc_gfx_fill_rect(hud_plane, 0u, row0, 20u, 1u, ' ', (u8)NGPNG_AUTORUN_HUD_TEXT_PAL);
        ngpc_gfx_fill_rect(hud_plane, 0u, row1, 20u, 1u, ' ', (u8)NGPNG_AUTORUN_HUD_TEXT_PAL);
    }
    if (hud_font_mode == 0u) {
        ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, row0, s_hud_line0);
        ngpc_text_print(hud_plane, (u8)NGPNG_AUTORUN_HUD_TEXT_PAL, 0, row1, s_hud_line1);
    } else if (sc && sc->hud_items && sc->hud_item_count > 0u) {
        u8 i;
        u8 spr = (u8)NGPNG_AUTORUN_HUD_SPR_BASE;
        for (i = 0u; i < sc->hud_item_count; ++i) {
            const NgpngHudItem *it = &sc->hud_items[i];
            if (it->kind == NGPNG_HUD_KIND_ICON) {
                if (!sc->draw_entity_anim || it->type == 255u || spr >= 64u) continue;
                spr = sc->draw_entity_anim(spr, it->type, 0u,
                    (s16)((u16)it->x * 8u), (s16)((u16)it->y * 8u));
                if (spr == 0u || spr > 64u) break;
            } else if (it->kind == NGPNG_HUD_KIND_VALUE) {
                ngpng_hud_draw_value(sc, hud_plane, &spr, it,
                    ngpng_hud_metric_value(it->metric, score, hp, lives,
                        continues_left, collectibles, timer_sec));
            }
        }
    }
    s_hud_last_score        = score;
    s_hud_last_hp           = hp;
    s_hud_last_lives        = lives;
    s_hud_last_collectibles = collectibles;
    s_hud_last_timer_sec    = timer_sec;
    s_hud_last_game_over    = game_over;
    s_hud_last_stage_clear  = stage_clear;
}

#endif /* NGPNG_HAS_PLAYER */
