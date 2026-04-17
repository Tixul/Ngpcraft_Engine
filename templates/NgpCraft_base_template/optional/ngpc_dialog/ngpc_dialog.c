/*
 * ngpc_dialog.c - Dialogue box on SCR2 with custom font
 *
 * Architecture validated by Evolution (Europe) + Nige-Ron-Pa (Japan/En) RE.
 *
 * Key invariants:
 *   - Always renders on GFX_SCR2.
 *   - SCR2 scroll is forced to (0,0) while box is open.
 *   - Game sprites use SPR_MIDDLE -> automatically behind SCR2.
 *   - Portrait sprite uses SPR_FRONT -> always above SCR2.
 *   - Word-wrap is applied automatically.
 */

#include "ngpc_dialog.h"
#include "ngpc_font.h"
#include "../../src/gfx/ngpc_gfx.h"
#include "../../src/core/ngpc_input.h"
#include "../ngpc_soam/ngpc_soam.h"

/* Box frame glyphs drawn using the custom font. */
#define _FRAME_H    '-'
#define _FRAME_V    '|'
#define _FRAME_TL   '+'
#define _FRAME_TR   '+'
#define _FRAME_BL   '+'
#define _FRAME_BR   '+'
#define _SPACE      ' '

/* ------------------------------------------------------------------ */
/* Internal helpers                                                     */
/* ------------------------------------------------------------------ */

static void _put_char(u8 x, u8 y, char c, u8 pal)
{
    ngpc_gfx_put_tile(GFX_SCR2, x, y, ngpc_font_char_to_tile(c), pal);
}

/* Scan forward from text[idx] to find the length of the current word
 * (stops at space, newline, or end of string). */
static u8 _word_len(const char *text, u8 idx)
{
    u8 len = 0u;
    while (text[(u8)(idx + len)] != '\0' &&
           text[(u8)(idx + len)] != ' '  &&
           text[(u8)(idx + len)] != '\n')
        len++;
    return len;
}

static void _put_str(u8 x, u8 y, const char *s, u8 pal)
{
    while (*s && x < 32u) {
        _put_char(x, y, *s, pal);
        x++;
        s++;
    }
}

static void _fill_row(u8 x, u8 y, char c, u8 count, u8 pal)
{
    u8 i;
    for (i = 0u; i < count; i++)
        _put_char((u8)(x + i), y, c, pal);
}

static void _clear_tile(u8 x, u8 y)
{
    /* Write tile 0 (transparent) with palette 0 to erase. */
    ngpc_gfx_put_tile(GFX_SCR2, x, y, 0u, 0u);
}

static void _clear_rect(u8 bx, u8 by, u8 bw, u8 bh)
{
    u8 x, y;
    for (y = by; y < (u8)(by + bh); y++)
        for (x = bx; x < (u8)(bx + bw); x++)
            _clear_tile(x, y);
}

/* ------------------------------------------------------------------ */
/* Layout helpers                                                       */
/* ------------------------------------------------------------------ */

/* Returns how many tile columns the portrait occupies (0 or 4). */
static u8 _portrait_cols(const NgpcDialog *d)
{
    return (d->portrait_tile != 0u && d->bw > 6u && d->bh > 4u) ? 4u : 0u;
}

/* Returns 1 if a speaker name is present and non-empty. */
static u8 _has_speaker(const NgpcDialog *d)
{
    return (d->speaker && d->speaker[0] != '\0' && d->speaker[0] != DIALOG_SPEAKER_END_CHAR) ? 1u : 0u;
}

/*
 * Computes the text area inside the box:
 *   text_x, text_y : top-left tile of text area
 *   max_col        : last tile column (inclusive) for text
 *   max_row        : last tile row (inclusive) for text
 */
static void _text_area(const NgpcDialog *d,
                       u8 *tx, u8 *ty, u8 *max_col, u8 *max_row)
{
    u8 pcols     = _portrait_cols(d);
    u8 spk_rows  = _has_speaker(d) ? 1u : 0u;
    u8 inner_x   = (u8)(d->bx + 1u);
    u8 inner_y   = (u8)(d->by + 1u);
    u8 inner_w   = (d->bw > 2u) ? (u8)(d->bw - 2u) : 1u;
    u8 inner_h   = (d->bh > 2u) ? (u8)(d->bh - 2u) : 1u;
    u8 choice_h  = (d->n_choices > 0u) ? d->n_choices : 0u;
    u8 text_h;

    *tx = (u8)(inner_x + pcols);
    *ty = (u8)(inner_y + spk_rows);

    text_h = (inner_h > spk_rows) ? (u8)(inner_h - spk_rows) : 1u;
    if (choice_h < text_h) text_h = (u8)(text_h - choice_h);
    else text_h = 1u;

    *max_col = (u8)(*tx + (inner_w > pcols ? inner_w - pcols : 1u) - 1u);
    *max_row = (u8)(*ty + text_h - 1u);
}

/* ------------------------------------------------------------------ */
/* Frame and clear                                                      */
/* ------------------------------------------------------------------ */

static void _draw_frame(const NgpcDialog *d)
{
    u8 x, y;
    u8 bx  = d->bx;
    u8 by  = d->by;
    u8 bw  = d->bw;
    u8 bh  = d->bh;
    u8 iw  = (bw > 2u) ? (u8)(bw - 2u) : 0u;
    u8 ih  = (bh > 2u) ? (u8)(bh - 2u) : 0u;

    if (d->frame_tile_base != 0u) {
        /* Sprite-based frame: 4 tiles (TL corner, H-border, fill, V-border).
         * tile+0 = TL corner  (H-flip=TR, V-flip=BL, H+V-flip=BR)
         * tile+1 = H-border   (V-flip = bottom edge)
         * tile+2 = fill       (interior, all opaque color 1)
         * tile+3 = V-border   (H-flip = left edge) */
        u16 fb = d->frame_tile_base;
        u8  fp = d->frame_pal;

        /* Corners */
        ngpc_gfx_put_tile_ex(GFX_SCR2, bx,                  by,                  fb,          fp, 0, 0);
        ngpc_gfx_put_tile_ex(GFX_SCR2, (u8)(bx + bw - 1u),  by,                  fb,          fp, 1, 0);
        ngpc_gfx_put_tile_ex(GFX_SCR2, bx,                  (u8)(by + bh - 1u),  fb,          fp, 0, 1);
        ngpc_gfx_put_tile_ex(GFX_SCR2, (u8)(bx + bw - 1u),  (u8)(by + bh - 1u), fb,          fp, 1, 1);

        /* Top / bottom H-borders */
        for (x = 1u; x < (u8)(bw - 1u); x++) {
            ngpc_gfx_put_tile_ex(GFX_SCR2, (u8)(bx + x), by,                 (u16)(fb + 1u), fp, 0, 0);
            ngpc_gfx_put_tile_ex(GFX_SCR2, (u8)(bx + x), (u8)(by + bh - 1u),(u16)(fb + 1u), fp, 0, 1);
        }

        /* Middle rows: left V-border, fill interior, right V-border */
        for (y = 1u; y <= ih; y++) {
            ngpc_gfx_put_tile_ex(GFX_SCR2, bx,                 (u8)(by + y), (u16)(fb + 3u), fp, 1, 0);
            for (x = 1u; x < (u8)(bw - 1u); x++)
                ngpc_gfx_put_tile(GFX_SCR2, (u8)(bx + x), (u8)(by + y), (u16)(fb + 2u), fp);
            ngpc_gfx_put_tile_ex(GFX_SCR2, (u8)(bx + bw - 1u),(u8)(by + y), (u16)(fb + 3u), fp, 0, 0);
        }
    } else {
        /* ASCII character fallback */
        u8 pal = d->pal;
        _put_char(bx, by, _FRAME_TL, pal);
        _fill_row((u8)(bx + 1u), by, _FRAME_H, iw, pal);
        _put_char((u8)(bx + bw - 1u), by, _FRAME_TR, pal);

        for (y = 1u; y <= ih; y++) {
            _put_char(bx, (u8)(by + y), _FRAME_V, pal);
            _fill_row((u8)(bx + 1u), (u8)(by + y), _SPACE, iw, pal);
            _put_char((u8)(bx + bw - 1u), (u8)(by + y), _FRAME_V, pal);
        }

        _put_char(bx, (u8)(by + bh - 1u), _FRAME_BL, pal);
        _fill_row((u8)(bx + 1u), (u8)(by + bh - 1u), _FRAME_H, iw, pal);
        _put_char((u8)(bx + bw - 1u), (u8)(by + bh - 1u), _FRAME_BR, pal);
    }
}

static void _clear_inner(const NgpcDialog *d)
{
    u8 iw = (d->bw > 2u) ? (u8)(d->bw - 2u) : 0u;
    u8 ih = (d->bh > 2u) ? (u8)(d->bh - 2u) : 0u;
    u8 x, y;

#ifdef NO_SYSFONT
    /* Custom font two-plane mode: SCR2 interior transparent, SCR1 holds the fill. */
    for (y = 0u; y < ih; y++)
        for (x = 0u; x < iw; x++)
            _clear_tile((u8)(d->bx + 1u + x), (u8)(d->by + 1u + y));
#else
    if (d->frame_tile_base != 0u) {
        /* Refill with opaque fill tile (frame_tile_base+2). */
        for (y = 0u; y < ih; y++)
            for (x = 0u; x < iw; x++)
                ngpc_gfx_put_tile(GFX_SCR2, (u8)(d->bx + 1u + x), (u8)(d->by + 1u + y),
                                  (u16)(d->frame_tile_base + 2u), d->frame_pal);
    } else {
        for (y = 0u; y < ih; y++)
            _fill_row((u8)(d->bx + 1u), (u8)(d->by + 1u + y), _SPACE, iw, d->pal);
    }
#endif
}

/* ------------------------------------------------------------------ */
/* Speaker name                                                         */
/* ------------------------------------------------------------------ */

static void _draw_speaker(const NgpcDialog *d)
{
    u8 tx, ty, mc, mr;
    u8 x;
    const char *p;
    u8 pal = d->pal;

    if (!_has_speaker(d)) return;

    _text_area(d, &tx, &ty, &mc, &mr);
    /* Speaker row is one above text area, one inside the frame. */
    ty = (u8)(d->by + 1u);
    x  = tx;
    p  = d->speaker;

    while (*p != '\0' && *p != DIALOG_SPEAKER_END_CHAR && x <= mc) {
        _put_char(x, ty, *p, pal);
        x++;
        p++;
    }
}

/* ------------------------------------------------------------------ */
/* Portrait sprite                                                      */
/* ------------------------------------------------------------------ */

static void _draw_portrait(const NgpcDialog *d)
{
    u8 px, py;
    if (d->portrait_tile == 0u) return;

    /* Position: 4px inside the box from top-left corner. */
    px = (u8)(d->bx * 8u + 4u);
    py = (u8)(d->by * 8u + 4u);

    /* Write portrait sprite in reserved OAM slot using SPR_FRONT so it
     * appears above SCR2 (the dialogue box plane). */
    ngpc_soam_put(DIALOG_PORTRAIT_SLOT, px, py, d->portrait_tile,
                  SPR_FRONT, d->pal);
}

static void _hide_portrait(void)
{
    ngpc_soam_hide(DIALOG_PORTRAIT_SLOT);
}

/* ------------------------------------------------------------------ */
/* Typewriter / page                                                    */
/* ------------------------------------------------------------------ */

static void _draw_arrow(const NgpcDialog *d, u8 visible)
{
    u8 tx, ty, mc, mr;
    char c = visible ? '>' : ' ';
    _text_area(d, &tx, &ty, &mc, &mr);
    _put_char((u8)(d->bx + d->bw - 2u), (u8)(d->by + d->bh - 2u), c, d->pal);
}

static void _draw_choices(const NgpcDialog *d)
{
    u8 tx, ty, mc, mr;
    u8 i;
    _text_area(d, &tx, &ty, &mc, &mr);
    ty = (u8)(mr + 1u);

    for (i = 0u; i < d->n_choices; i++) {
        char sel = (i == d->cursor) ? '>' : ' ';
        _put_char(tx, (u8)(ty + i), sel, d->pal);
        _put_str((u8)(tx + 1u), (u8)(ty + i), d->choices[i], d->pal);
    }
}

/*
 * Scan forward from start_idx, skipping leading whitespace.
 */
static u8 _skip_ws(const char *text, u8 idx)
{
    while (text[idx] == ' ' || text[idx] == '\n' || text[idx] == '\r')
        idx++;
    return idx;
}

/*
 * Scan forward from start_idx to find where the current page ends.
 * A page ends when the cursor would exceed max_row.
 */
static u8 _page_end(const NgpcDialog *d, u8 start_idx)
{
    u8 tx, ty, mc, mr;
    u8 row, col;
    u8 i;
    u8 prev_space;
    u8 wl, line_w;
    const char *text;

    if (!d->text) return start_idx;

    _text_area(d, &tx, &ty, &mc, &mr);
    text       = d->text;
    row        = ty;
    col        = tx;
    prev_space = 1u; /* treat page start as "after a space" */

    for (i = start_idx; text[i] != '\0'; i++) {
        if (text[i] == '\n') {
            row++; col = tx; prev_space = 1u;
            if (row > mr) return i;
        } else if (text[i] == ' ') {
            prev_space = 1u;
            col++;
            if (col > mc) { row++; col = tx; if (row > mr) return i; }
        } else {
            /* Word-wrap: at word start, check if the whole word fits. */
            if (prev_space && col > tx) {
                wl     = _word_len(text, i);
                line_w = (u8)(mc - tx + 1u);
                if (wl <= line_w && (u8)(col + wl) > (u8)(mc + 1u)) {
                    row++; col = tx;
                    if (row > mr) return i;
                }
            }
            prev_space = 0u;
            col++;
            if (col > mc) { row++; col = tx; if (row > mr) return i; }
        }
    }
    return i;
}

static u8 _page_has_more(const NgpcDialog *d)
{
    u8 next;
    if (!d->text) return 0u;
    next = _skip_ws(d->text, d->page_end);
    return (u8)(d->text[next] != '\0');
}

/*
 * Redraw all revealed characters of the current page.
 */
static void _redraw_text(const NgpcDialog *d)
{
    u8 tx, ty, mc, mr;
    u8 row, col;
    u8 i;
    u8 prev_space;
    u8 wl, line_w;
    const char *text;

    if (!d->text) return;

    _text_area(d, &tx, &ty, &mc, &mr);
    _draw_speaker(d);

    text       = d->text;
    row        = ty;
    col        = tx;
    prev_space = 1u;

    for (i = d->page_start; i < d->char_idx && text[i] != '\0'; i++) {
        if (text[i] == '\n') {
            row++; col = tx; prev_space = 1u;
        } else if (text[i] == ' ') {
            prev_space = 1u;
            col++;
            if (col > mc) { row++; col = tx; }
        } else {
            if (prev_space && col > tx) {
                wl     = _word_len(text, i);
                line_w = (u8)(mc - tx + 1u);
                if (wl <= line_w && (u8)(col + wl) > (u8)(mc + 1u)) {
                    row++; col = tx;
                }
            }
            prev_space = 0u;
            if (row <= mr && col <= mc)
                _put_char(col, row, text[i], d->pal);
            col++;
            if (col > mc) { row++; col = tx; }
        }
    }
}

/*
 * Reveal one character at char_idx.
 */
static void _reveal_char(const NgpcDialog *d)
{
    u8 tx, ty, mc, mr;
    u8 row, col;
    u8 i;
    u8 prev_space;
    u8 wl, line_w;
    const char *text;

    if (!d->text || d->char_idx >= d->page_end) return;

    _text_area(d, &tx, &ty, &mc, &mr);
    text       = d->text;
    row        = ty;
    col        = tx;
    prev_space = 1u;

    /* Walk from page_start to char_idx to find cursor position (same
     * word-wrap logic as _page_end and _redraw_text). */
    for (i = d->page_start; i < d->char_idx && text[i] != '\0'; i++) {
        if (text[i] == '\n') {
            row++; col = tx; prev_space = 1u;
        } else if (text[i] == ' ') {
            prev_space = 1u;
            col++;
            if (col > mc) { row++; col = tx; }
        } else {
            if (prev_space && col > tx) {
                wl     = _word_len(text, i);
                line_w = (u8)(mc - tx + 1u);
                if (wl <= line_w && (u8)(col + wl) > (u8)(mc + 1u)) {
                    row++; col = tx;
                }
            }
            prev_space = 0u;
            col++;
            if (col > mc) { row++; col = tx; }
        }
    }

    /* Apply word-wrap for the character about to be revealed. */
    if (text[d->char_idx] != '\n' && text[d->char_idx] != ' ') {
        if (prev_space && col > tx) {
            wl     = _word_len(text, d->char_idx);
            line_w = (u8)(mc - tx + 1u);
            if (wl <= line_w && (u8)(col + wl) > (u8)(mc + 1u)) {
                row++; col = tx;
            }
        }
    }

    if (text[d->char_idx] != '\n' && row <= mr && col <= mc)
        _put_char(col, row, text[d->char_idx], d->pal);
}

static void _set_page(NgpcDialog *d, u8 start_idx)
{
    d->page_start = _skip_ws(d->text ? d->text : "", start_idx);
    d->page_end   = _page_end(d, d->page_start);
    d->char_idx   = d->page_start;
    d->tick       = 0u;
    d->blink      = 0u;
    d->flags     &= (u8)~_DLG_TEXT_DONE;
    _clear_inner(d);
    _redraw_text(d);
}

/* ------------------------------------------------------------------ */
/* Public API                                                           */
/* ------------------------------------------------------------------ */

void ngpc_dialog_open(NgpcDialog *d,
                      u8 bx, u8 by, u8 bw, u8 bh,
                      u8 pal, u16 portrait_tile,
                      u16 frame_tile_base, u8 frame_pal)
{
    /* Save and reset SCR2 scroll so box tile coords == screen coords. */
    d->saved_scr2_x = HW_SCR2_OFS_X;
    d->saved_scr2_y = HW_SCR2_OFS_Y;
    HW_SCR2_OFS_X   = 0u;
    HW_SCR2_OFS_Y   = 0u;

    d->text            = 0;
    d->speaker         = 0;
    d->choices         = 0;
    d->bx              = bx;
    d->by              = by;
    d->bw              = bw;
    d->bh              = bh;
    d->pal             = pal;
    d->char_idx        = 0u;
    d->page_start      = 0u;
    d->page_end        = 0u;
    d->tick            = 0u;
    d->blink           = 0u;
    d->cursor          = 0u;
    d->n_choices       = 0u;
    d->portrait_tile   = portrait_tile;
    d->frame_tile_base = frame_tile_base;
    d->frame_pal       = frame_pal;
    d->flags           = _DLG_OPEN;

    ngpc_font_load();
#ifndef NO_SYSFONT
    ngpc_font_apply_palette(GFX_SCR2, pal);
#endif
    _draw_frame(d);

    if (portrait_tile != 0u) {
        d->flags |= _DLG_HAS_PORTRAIT;
        _draw_portrait(d);
    }
}

void ngpc_dialog_close(NgpcDialog *d)
{
    /* Clear the full box area on SCR2. */
    _clear_rect(d->bx, d->by, d->bw, d->bh);

    /* Restore SCR2 scroll. */
    HW_SCR2_OFS_X = d->saved_scr2_x;
    HW_SCR2_OFS_Y = d->saved_scr2_y;

    /* Hide portrait if any. */
    if (d->flags & _DLG_HAS_PORTRAIT)
        _hide_portrait();

    d->text    = 0;
    d->speaker = 0;
    d->flags   = 0u;
}

void ngpc_dialog_set_text(NgpcDialog *d, const char *text)
{
    const char *body = text;
    d->speaker = 0;

    /* Parse encoded speaker: "\001Name\002Body" */
    if (text && text[0] == DIALOG_SPEAKER_BEGIN_CHAR) {
        const char *sep = text + 1;
        while (*sep != '\0' && *sep != DIALOG_SPEAKER_END_CHAR) sep++;
        if (*sep == DIALOG_SPEAKER_END_CHAR) {
            d->speaker = text + 1;
            body       = sep + 1;
        }
    }

    d->text      = body;
    d->n_choices = 0u;
    d->flags    &= (u8)~(_DLG_TEXT_DONE | _DLG_HAS_CHOICES);
    _set_page(d, 0u);
}

void ngpc_dialog_set_choices(NgpcDialog *d, const char **choices, u8 count)
{
    if (count > DIALOG_MAX_CHOICES) count = DIALOG_MAX_CHOICES;
    d->choices   = choices;
    d->n_choices = count;
    d->cursor    = 0u;
    if (count > 0u) d->flags |= _DLG_HAS_CHOICES;
    if (d->text) {
        d->page_end = _page_end(d, d->page_start);
        _clear_inner(d);
        _redraw_text(d);
        if ((d->flags & _DLG_TEXT_DONE) && !_page_has_more(d) && count > 0u)
            _draw_choices(d);
    }
}

u8 ngpc_dialog_update(NgpcDialog *d)
{
    u8 more;

    if (!(d->flags & _DLG_OPEN)) return DIALOG_DONE;

    /* --- Typewriter phase --- */
    if (!(d->flags & _DLG_TEXT_DONE)) {
        if (!d->text || d->char_idx >= d->page_end) {
            d->flags |= _DLG_TEXT_DONE;
            if ((d->flags & _DLG_HAS_CHOICES) && !_page_has_more(d))
                _draw_choices(d);
        } else {
            /* A skips to page end. */
            if (ngpc_pad_pressed & PAD_A) {
                d->char_idx = d->page_end;
                d->flags   |= _DLG_TEXT_DONE;
                _clear_inner(d);
                _redraw_text(d);
                if ((d->flags & _DLG_HAS_CHOICES) && !_page_has_more(d))
                    _draw_choices(d);
                return DIALOG_RUNNING;
            }
            /* Advance typewriter. */
            d->tick++;
            if (d->tick >= DIALOG_TEXT_SPEED) {
                d->tick = 0u;
                /* Skip over newlines immediately (they don't render). */
                while (d->char_idx < d->page_end &&
                       d->text[d->char_idx] == '\n')
                    d->char_idx++;
                if (d->char_idx < d->page_end) {
                    _reveal_char(d);
                    d->char_idx++;
                }
                if (d->char_idx >= d->page_end) {
                    d->flags |= _DLG_TEXT_DONE;
                    if ((d->flags & _DLG_HAS_CHOICES) && !_page_has_more(d))
                        _draw_choices(d);
                }
            }
        }
        return DIALOG_RUNNING;
    }

    /* --- Page-more phase --- */
    more = _page_has_more(d);
    if (more) {
        d->blink++;
        if (d->blink >= DIALOG_BLINK_PERIOD) d->blink = 0u;
        _draw_arrow(d, (u8)(d->blink < (DIALOG_BLINK_PERIOD / 2u)));

        if (ngpc_pad_pressed & PAD_A)
            _set_page(d, d->page_end);

        return DIALOG_RUNNING;
    }

    /* --- Choice phase --- */
    if (d->flags & _DLG_HAS_CHOICES) {
        u8 changed = 0u;
        if ((ngpc_pad_pressed & PAD_UP) && d->cursor > 0u)
            { d->cursor--; changed = 1u; }
        if ((ngpc_pad_pressed & PAD_DOWN) && d->cursor < (u8)(d->n_choices - 1u))
            { d->cursor++; changed = 1u; }
        if (changed) _draw_choices(d);

        if (ngpc_pad_pressed & PAD_A) {
            u8 sel = d->cursor;
            ngpc_dialog_close(d);
            return (u8)(DIALOG_CHOICE_0 + sel);
        }
        return DIALOG_RUNNING;
    }

    /* --- Wait-for-dismiss phase (arrow blink) --- */
    d->blink++;
    if (d->blink >= DIALOG_BLINK_PERIOD) d->blink = 0u;
    _draw_arrow(d, (u8)(d->blink < (DIALOG_BLINK_PERIOD / 2u)));

    if (ngpc_pad_pressed & PAD_A) {
        ngpc_dialog_close(d);
        return DIALOG_DONE;
    }
    return DIALOG_RUNNING;
}
