#ifndef NGPC_HUD_H
#define NGPC_HUD_H

/*
 * ngpc_hud -- Éléments HUD précâblés
 * ====================================
 * Barre de valeur (HP/énergie), score, compteur de vies.
 * Rendu sur tilemap via ngpc_gfx_put_tile() et ngpc_text_print_dec().
 *
 * Dépend de : ngpc_gfx.h, ngpc_text.h (template de base)
 *
 * Usage :
 *   Copier ngpc_hud/ dans src/
 *   OBJS += src/ngpc_hud/ngpc_hud.rel
 *   #include "ngpc_hud/ngpc_hud.h"
 *
 * Barre HP — 3 tiles : TILE_FULL, TILE_HALF, TILE_EMPTY
 * --------------------------------------------------------
 * La barre s'affiche sur HUD_BAR_LEN tiles. Chaque tile peut valoir
 * 2 unités (full = 2, half = 1, empty = 0), ce qui donne une précision
 * ×2 par rapport à la largeur visuelle.
 *
 * Exemple — barre HP 8 points sur 4 tiles :
 *   #define TILE_HP_FULL  256   /* tile chargé en RAM */
 *   #define TILE_HP_HALF  257
 *   #define TILE_HP_EMPTY 258
 *
 *   static NgpcHudBar hp_bar;
 *   ngpc_hud_bar_init(&hp_bar, GFX_SCR1, 1, 0, 4,
 *                     8, TILE_HP_FULL, TILE_HP_HALF, TILE_HP_EMPTY, 0);
 *   ngpc_hud_bar_draw(&hp_bar);
 *
 *   // Quand HP change :
 *   ngpc_hud_bar_set(&hp_bar, player_hp);   // redessine automatiquement
 *
 * Score
 * -----
 *   ngpc_hud_score_draw(GFX_SCR1, 0, 12, 1, score, 6);  // "  1234" sur 6 chars
 *
 * Vies — icônes sprites
 * ----------------------
 *   ngpc_hud_lives_draw(SPR_LIVES, 2, 1, lives, LIFE_TILE, 0, 12);
 *   // 3 vies → 3 sprites espacés de 12 px depuis (2, 1)
 */

#include "ngpc_hw.h"

/* ── Barre de valeur ─────────────────────────────────────── */

/*
 * Structure de barre HUD (9 octets).
 * len tiles × 2 unités max = max_val max possible = len * 2.
 * Si tile_half == 0, la barre est binaire (full/empty uniquement).
 */
typedef struct {
    u8  plane;       /* GFX_SCR1 ou GFX_SCR2           */
    u8  tx, ty;      /* position tile (coin gauche)     */
    u8  len;         /* largeur en tiles (max 20)       */
    u8  cur;         /* valeur courante                 */
    u8  max_val;     /* valeur max (= len × 2 avec half, = len sans) */
    u16 tile_full;   /* tile "plein" (index tile RAM)   */
    u16 tile_half;   /* tile "demi" (0 si non utilisé)  */
    u16 tile_empty;  /* tile "vide"                     */
    u8  pal;         /* palette (0-15)                  */
} NgpcHudBar;

/*
 * Initialise une barre HUD.
 *   tile_half : 0 = précision simple (1 unité/tile), >0 = précision double (2 unités/tile).
 */
void ngpc_hud_bar_init(NgpcHudBar *bar,
                       u8 plane, u8 tx, u8 ty, u8 len,
                       u8 max_val,
                       u16 tile_full, u16 tile_half, u16 tile_empty,
                       u8 pal);

/* Dessine la barre à son état courant. */
void ngpc_hud_bar_draw(const NgpcHudBar *bar);

/*
 * Change la valeur courante et redessine.
 * value est clampé dans [0..max_val].
 */
void ngpc_hud_bar_set(NgpcHudBar *bar, u8 value);

/* ── Score ───────────────────────────────────────────────── */

/*
 * Affiche un score (u16) sur la tilemap.
 *   plane, pal     : plane et palette
 *   tx, ty         : position tile
 *   score          : valeur 0-65535
 *   digits         : nombre de caractères (ex: 6 → " 1234" zéro-paddé à gauche)
 *   zero_pad       : 1 = zéros à gauche ("001234"), 0 = espaces ("  1234")
 */
void ngpc_hud_score_draw(u8 plane, u8 pal, u8 tx, u8 ty,
                         u16 score, u8 digits, u8 zero_pad);

/* ── Vies (icônes sprites) ───────────────────────────────── */

/*
 * Affiche 'lives' icônes sprites consécutifs.
 *   spr_base : index du premier sprite alloué aux vies
 *   x, y     : position pixel du premier icône
 *   lives    : nombre d'icônes visibles
 *   max_lives: nombre total de slots sprites (les surplus sont cachés)
 *   tile     : tile de l'icône
 *   pal      : palette
 *   spacing  : espacement horizontal entre icônes (pixels)
 */
void ngpc_hud_lives_draw(u8 spr_base, u8 x, u8 y,
                         u8 lives, u8 max_lives,
                         u16 tile, u8 pal, u8 spacing);

#endif /* NGPC_HUD_H */
