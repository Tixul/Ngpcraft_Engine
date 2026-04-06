/* ngpng_hud.h -- HUD rendering (text, sprite digits, palette, state).
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#ifndef NGPNG_HUD_H
#define NGPNG_HUD_H

#include "ngpc_hw.h"        /* u8, s8, s16, u16                  (found via -Isrc/core)  */
#include "ngpc_gfx.h"       /* ngpc_gfx_set_palette, RGB          (found via -Isrc/gfx)   */
#include "ngpc_text.h"      /* ngpc_text_print                    (found via -Isrc/gfx)   */
#include "ngpc_sprite.h"    /* ngpc_sprite_hide                   (found via -Isrc/gfx)   */
#include "scenes_autogen.h" /* NgpSceneDef, NgpngHudItem          (found via -IGraphX)    */
#include "ngpng_engine.h"   /* NGPNG_HUD_FIXED_SCR1/SCR2, GFX_*  (found via -Isrc/ngpng) */

/* ---- HUD constant definitions (with #ifndef guards for Makefile overrides) ---- */
#ifndef NGPNG_HUD_KIND_ICON
#define NGPNG_HUD_KIND_ICON  0
#define NGPNG_HUD_KIND_VALUE 1
#endif

#ifndef NGPNG_HUD_FLAG_ZERO_PAD
#define NGPNG_HUD_FLAG_ZERO_PAD 1
#endif

#ifndef NGPNG_HUD_STYLE_TEXT
#define NGPNG_HUD_STYLE_TEXT 0
#define NGPNG_HUD_STYLE_BAND 1
#endif

#ifndef NGPNG_HUD_METRIC_HP
#define NGPNG_HUD_METRIC_HP        0
#define NGPNG_HUD_METRIC_SCORE     1
#define NGPNG_HUD_METRIC_COLLECT   2
#define NGPNG_HUD_METRIC_TIMER     3
#define NGPNG_HUD_METRIC_LIVES     4
#define NGPNG_HUD_METRIC_CONTINUES 5
#endif

/* ---- HUD API (compiled only when NGPNG_HAS_PLAYER) ---- */
#if NGPNG_HAS_PLAYER

void ngpng_hud_apply_palettes(const NgpSceneDef *sc);
void ngpng_hud_reset(const NgpSceneDef *sc);
void ngpng_hud_sync(const NgpSceneDef *sc,
    u8 hud_flags, u8 hud_pos, u8 hud_font_mode,
    u16 score, u8 hp, u8 lives, u8 continues_left,
    u16 collectibles, u16 timer_sec,
    u8 game_over, u8 stage_clear);
u8 ngpng_continue_restore_lives(const NgpSceneDef *sc);

#endif /* NGPNG_HAS_PLAYER */

#endif /* NGPNG_HUD_H */
