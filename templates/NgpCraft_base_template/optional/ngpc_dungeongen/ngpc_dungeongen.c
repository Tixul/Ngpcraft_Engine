/*
 * ngpc_dungeongen.c -- Generateur de donjon scrollable (implementation)
 *
 * Voir ngpc_dungeongen.h pour la documentation API.
 *
 * Ordre de compilation (cc900 single-pass) :
 *   1. RNG xorshift16
 *   2. Hash deterministes (style, largeur, hauteur)
 *   3. Helpers dessin (put_mt, put_wall_h/v, _place_elem)
 *   4. draw_interior (early return si eau)
 *   5. _on_exit (rejection spawn)
 *   6. spawn_entities / sprites_sync (interne)
 *   7. _plan_water
 *   8. draw_population
 *   9. Predicats portes + ground, draw_room
 *  10. API publique (ngpc_dungeongen_*)
 */

#include "dungeongen_config.h"
#include "ngpc_dungeongen/ngpc_dungeongen.h"

/* Assets graphiques generes par les scripts export_*.py */
#include "tiles_procgen.h"    /* TILE_GROUND_1, PAL_TERRAIN, PAL_EAU, etc. */
#include "sprites_lab.h"      /* SPR_ENE1_TILE, PAL_SPR_ENE1, etc.         */

/* HAL graphique + sprites */
#include "ngpc_gfx.h"
#include "ngpc_sprite.h"
#include "ngpc_rtc.h"

/* =========================================================================
 * Alias locaux (isoler les defines DUNGEONGEN_* des noms courts internes)
 * ========================================================================= */
#define _GPC_1  DUNGEONGEN_GROUND_PCT_1
#define _GPC_2  DUNGEONGEN_GROUND_PCT_2
#define _GPC_3  DUNGEONGEN_GROUND_PCT_3

#define _EAU_FREQ      DUNGEONGEN_EAU_FREQ
#define _VIDE_FREQ     DUNGEONGEN_VIDE_FREQ
#define _TNO_FREQ      DUNGEONGEN_TONNEAU_FREQ
#define _TNO_MAX       DUNGEONGEN_TONNEAU_MAX
/* _ESC_FREQ supprime : l'escalier est place par ngpc_dungeongen_set_room_type()
 * via ngpc_cluster. DUNGEONGEN_ESCALIER_FREQ n'est plus utilise dans ce module. */
#define _VIDE_MARGIN   DUNGEONGEN_VIDE_MARGIN
#define _ENE_MIN       DUNGEONGEN_ENEMY_MIN
#define _ENE_MAX       DUNGEONGEN_ENEMY_MAX
#define _ENE_DENS      DUNGEONGEN_ENEMY_DENSITY
#define _ENE2_PCT      DUNGEONGEN_ENE2_PCT
#define _ITEM_FREQ     DUNGEONGEN_ITEM_FREQ

#define _MW_MIN  DUNGEONGEN_ROOM_MW_MIN
#define _MW_MAX  DUNGEONGEN_ROOM_MW_MAX
#define _MH_MIN  DUNGEONGEN_ROOM_MH_MIN
#define _MH_MAX  DUNGEONGEN_ROOM_MH_MAX
#define _N_STY   DUNGEONGEN_N_STYLES

/* Taille d'une cellule logique (tiles et pixels) */
#define _CW       DUNGEONGEN_CELL_W_TILES
#define _CH       DUNGEONGEN_CELL_H_TILES
#define _CELL_PX  ((u8)((u8)_CW * 8u))   /* pixels par cellule en X */
#define _CELL_PY  ((u8)((u8)_CH * 8u))   /* pixels par cellule en Y */

/* Bitmasks sorties (internes) */
#define _EXIT_N  DGN_EXIT_N
#define _EXIT_S  DGN_EXIT_S
#define _EXIT_E  DGN_EXIT_E
#define _EXIT_W  DGN_EXIT_W

/* Couche BG utilisee */
#define _PLANE   GFX_SCR1

/* Nombre de slots sprite reserves par ennemi (= max tile_count du pool, ou 4 legacy) */
#ifdef DUNGEONGEN_ENE_POOL_SIZE
#  define _ENE_SLOTS_PER  ((u8)DUNGEONGEN_ENE_SLOTS_PER)
#else
#  define _ENE_SLOTS_PER  4u
#endif

/* Slot sprites item = apres les slots ennemis */
#define _SPR_ITEM_SLOT  ((u8)((u8)_ENE_MAX * _ENE_SLOTS_PER))

/* =========================================================================
 * RNG xorshift16 (u16 pur, safe cc900 / TLCS-900)
 * Parametres (7,9,8) -- periode 2^16-1.
 * s_global_seed XOR'd dans rng_seed_room pour decoreller les sessions.
 * ========================================================================= */
static u16 s_rng;
static u16 s_global_seed;

static void _rng_seed(u16 seed)
{
    s_rng = seed ? seed : 1u;
}

static u8 _rng_u8(void)
{
    s_rng ^= (u16)(s_rng << 7u);
    s_rng ^= (u16)(s_rng >> 9u);
    s_rng ^= (u16)(s_rng << 8u);
    return (u8)(s_rng >> 8u);
}

static void _rng_seed_room(u16 room_idx, u8 style_idx)
{
    u16 s = (u16)((room_idx  + 1u) * 157u)
          ^ (u16)((u16)(style_idx + 1u) * 233u)
          ^ s_global_seed;
    _rng_seed(s ? s : 1u);
}

/* =========================================================================
 * Hash deterministes par room_idx (decorelles par multiplicateur different)
 * ========================================================================= */
static u8 _style_for(u16 room_idx)
{
    u16 s = (u16)((room_idx + 1u) * 157u) ^ s_global_seed;
    s ^= (u16)(s << 7u);
    s ^= (u16)(s >> 9u);
    s ^= (u16)(s << 8u);
    return (u8)((u8)(s >> 8u) % (u8)_N_STY);
}

static u8 _room_w_for(u16 room_idx)
{
    u8  range = (u8)(_MW_MAX - _MW_MIN + 1u);
    u16 s = (u16)((room_idx + 1u) * 211u) ^ s_global_seed;
    s ^= (u16)(s << 5u);
    s ^= (u16)(s >> 11u);
    s ^= (u16)(s << 3u);
    return (u8)(_MW_MIN + (u8)((u8)(s >> 8u) % range));
}

static u8 _room_h_for(u16 room_idx)
{
    u8  range = (u8)(_MH_MAX - _MH_MIN + 1u);
    u16 s = (u16)((room_idx + 1u) * 173u) ^ s_global_seed;
    s ^= (u16)(s << 9u);
    s ^= (u16)(s >> 5u);
    s ^= (u16)(s << 7u);
    return (u8)(_MH_MIN + (u8)((u8)(s >> 8u) % range));
}

/* =========================================================================
 * State interne
 * ========================================================================= */
static u8  s_style_idx;
static u16 s_room_idx;
static u8  s_room_w;
static u8  s_room_h;
static u8  s_door_col_lo;
static u8  s_door_col_hi;
static u8  s_door_row_lo;
static u8  s_door_row_hi;

/* Parametres eau (calcules par _plan_water avant draw_interior) */
static u8  s_has_water;
static u8  s_water_orient;   /* 0=bande H, 1=bande V */
static u8  s_water_band;     /* rangee (H) ou colonne (V) */
static u8  s_bridge_px;
static u8  s_bridge_py;

/* Entites : positions monde en pixels (metatile * 16) */
#if DUNGEONGEN_ENEMY_MAX > 0
static u8  s_enemy_wx[DUNGEONGEN_ENEMY_MAX];
static u8  s_enemy_wy[DUNGEONGEN_ENEMY_MAX];
static u8  s_enemy_type[DUNGEONGEN_ENEMY_MAX];  /* 0=ENE1 16x16, 1=ENE2 8x8 */
#endif
static u8  s_enemy_count;
static u8  s_item_wx;
static u8  s_item_wy;
static u8  s_item_active;
static u8  s_item_type;   /* index pool item (0 si pool non defini) */
static u8  s_is_safe_room;

/* Navigation cluster */
static u8  s_has_stair;
static u8  s_stair_mx;
static u8  s_stair_my;

/* Tonneaux : positions enregistrees pour collision */
static u8  s_tonneau_count;
static u8  s_tonneau_x[2];
static u8  s_tonneau_y[2];

/* Fosse (vide) : position du bloc 2x2 */
static u8  s_has_vide;
static u8  s_vide_x;
static u8  s_vide_y;

/* Tier de difficulte courant (0 = defaut) */
#if DUNGEONGEN_TIER_COLS > 0
static const u8 s_tier_ene_max[DUNGEONGEN_TIER_COLS]   = DUNGEONGEN_TIER_ENE_MAX;
static const u8 s_tier_item_freq[DUNGEONGEN_TIER_COLS] = DUNGEONGEN_TIER_ITEM_FREQ;
static const u8 s_tier_eau_freq[DUNGEONGEN_TIER_COLS]  = DUNGEONGEN_TIER_EAU_FREQ;
static const u8 s_tier_vide_freq[DUNGEONGEN_TIER_COLS] = DUNGEONGEN_TIER_VIDE_FREQ;
static u8 s_tier;
#endif

/* Murs interieurs enregistres pour rejection de spawn */
#define _MAX_INT_WALLS  4u
static u8  s_int_wall_count;
static u8  s_int_wall_x[_MAX_INT_WALLS];
static u8  s_int_wall_y[_MAX_INT_WALLS];
static u8  s_int_wall_w[_MAX_INT_WALLS];
static u8  s_int_wall_h[_MAX_INT_WALLS];

/* =========================================================================
 * State public
 * ========================================================================= */
NgpcDungeonRoom ngpc_dgroom;

/* =========================================================================
 * Table des styles (exits + sol). Ordonnee par nb de sorties croissant.
 * ========================================================================= */
typedef struct { u8 exits; u8 ground; } _RoomStyle;

static const _RoomStyle s_styles[] = {
    /* --- Styles originaux [0-6] --- */
    { 0u,                                            0u }, /* [0]  fermee          */
    { _EXIT_N,                                       0u }, /* [1]  dead end N      */
    { _EXIT_N | _EXIT_S,                             0u }, /* [2]  corridor V      */
    { _EXIT_E | _EXIT_W,                             0u }, /* [3]  corridor H      */
    { _EXIT_N | _EXIT_E,                             0u }, /* [4]  coin NE         */
    { _EXIT_N | _EXIT_S | _EXIT_E,                   0u }, /* [5]  T-shape N/S/E   */
    { _EXIT_N | _EXIT_S | _EXIT_E | _EXIT_W,         0u }, /* [6]  toutes sorties  */
    /* --- Styles cluster [7-12] : entrees non-Nord (S/E/W comme back-exit) --- */
    { _EXIT_S,                                       0u }, /* [7]  dead end S      */
    { _EXIT_E,                                       0u }, /* [8]  dead end E      */
    { _EXIT_W,                                       0u }, /* [9]  dead end W      */
    { _EXIT_S | _EXIT_E,                             0u }, /* [10] coin SE         */
    { _EXIT_S | _EXIT_W,                             0u }, /* [11] coin SW         */
    { _EXIT_S | _EXIT_E | _EXIT_W,                   0u }, /* [12] T-shape S/E/W   */
};

/* =========================================================================
 * Helper : dessin d'une cellule logique (CELL_W_TILES x CELL_H_TILES tiles).
 * Les tiles du set doivent etre ordonnes ligne par ligne (row-major).
 * Exemple 2x2 : tile+0=TL, tile+1=TR, tile+2=BL, tile+3=BR.
 * Exemple 1x1 : tile+0 seulement.
 *
 * _put_cell_ex : version avec flip hardware (DGN_FLIP_NONE/H/V/HV).
 *   En mode compact, les tuiles directionnelles derivees (N/W/NE/SW/SE...)
 *   reutilisent la meme donnee binaire que leur source avec un flip hardware.
 *   En mode full (TILE_X_FLIP = DGN_FLIP_NONE pour tout), comportement identique
 *   a l'ancienne _put_cell.
 * ========================================================================= */
static void _put_cell_ex(u8 mx, u8 my, u16 tile, u8 pal, u8 flip)
{
    u8 gx = (u8)((u8)_CW * mx);
    u8 gy = (u8)((u8)_CH * my);
    u8 tx, ty;
    u8 hf = (u8)(flip & 1u);
    u8 vf = (u8)((flip >> 1u) & 1u);
    for (ty = 0u; ty < (u8)_CH; ty++) {
        u8 src_ty = vf ? (u8)((u8)_CH - 1u - ty) : ty;
        for (tx = 0u; tx < (u8)_CW; tx++) {
            u8 src_tx = hf ? (u8)((u8)_CW - 1u - tx) : tx;
            ngpc_gfx_put_tile_ex(_PLANE, (u8)(gx + tx), (u8)(gy + ty),
                (u16)(tile + (u16)((u8)((u8)_CW * src_ty) + src_tx)),
                pal, hf, vf);
        }
    }
}
#define _put_cell(mx,my,t,p)  _put_cell_ex((mx),(my),(t),(p),DGN_FLIP_NONE)

/* =========================================================================
 * Helpers : formes de murs interieurs
 * ========================================================================= */
static void _put_wall_h(u8 mx, u8 my, u8 w)
{
    u8 x;
    _put_cell_ex(mx, my, TILE_WALL_INT_NW, PAL_WALL_INT, TILE_WALL_INT_NW_FLIP);
    for (x = 1u; x < (u8)(w - 1u); x++)
        _put_cell_ex((u8)(mx + x), my, TILE_WALL_INT_N, PAL_WALL_INT, TILE_WALL_INT_N_FLIP);
    _put_cell_ex((u8)(mx + w - 1u), my, TILE_WALL_INT_NE, PAL_WALL_INT, TILE_WALL_INT_NE_FLIP);
    _put_cell_ex(mx, (u8)(my + 1u), TILE_WALL_INT_SW, PAL_WALL_INT, TILE_WALL_INT_SW_FLIP);
    for (x = 1u; x < (u8)(w - 1u); x++)
        _put_cell_ex((u8)(mx + x), (u8)(my + 1u), TILE_WALL_INT_S, PAL_WALL_INT, TILE_WALL_INT_S_FLIP);
    _put_cell_ex((u8)(mx + w - 1u), (u8)(my + 1u), TILE_WALL_INT_SE, PAL_WALL_INT, TILE_WALL_INT_SE_FLIP);
}

static void _put_wall_v(u8 mx, u8 my, u8 h)
{
    u8 y;
    _put_cell_ex(mx, my, TILE_WALL_INT_NW, PAL_WALL_INT, TILE_WALL_INT_NW_FLIP);
    _put_cell_ex((u8)(mx + 1u), my, TILE_WALL_INT_NE, PAL_WALL_INT, TILE_WALL_INT_NE_FLIP);
    for (y = 1u; y < (u8)(h - 1u); y++) {
        _put_cell_ex(mx, (u8)(my + y), TILE_WALL_INT_W, PAL_WALL_INT, TILE_WALL_INT_W_FLIP);
        _put_cell_ex((u8)(mx + 1u), (u8)(my + y), TILE_WALL_INT_E, PAL_WALL_INT, TILE_WALL_INT_E_FLIP);
    }
    _put_cell_ex(mx, (u8)(my + h - 1u), TILE_WALL_INT_SW, PAL_WALL_INT, TILE_WALL_INT_SW_FLIP);
    _put_cell_ex((u8)(mx + 1u), (u8)(my + h - 1u), TILE_WALL_INT_SE, PAL_WALL_INT, TILE_WALL_INT_SE_FLIP);
}

static void _record_wall(u8 px, u8 py, u8 w, u8 h)
{
    if (s_int_wall_count < (u8)_MAX_INT_WALLS) {
        s_int_wall_x[s_int_wall_count] = px;
        s_int_wall_y[s_int_wall_count] = py;
        s_int_wall_w[s_int_wall_count] = w;
        s_int_wall_h[s_int_wall_count] = h;
        s_int_wall_count = (u8)(s_int_wall_count + 1u);
    }
}

static void _place_elem(u8 shape, u8 px, u8 py, u8 xlim, u8 ylim)
{
    if (shape == 1u && px > xlim) { px = xlim; }
    if (shape == 2u && py > ylim) { py = ylim; }
    if      (shape == 0u) { _put_wall_h(px, py, 2u); _record_wall(px, py, 2u, 2u); }
    else if (shape == 1u) { _put_wall_h(px, py, 3u); _record_wall(px, py, 3u, 2u); }
    else                  { _put_wall_v(px, py, 3u); _record_wall(px, py, 2u, 3u); }
}

/* =========================================================================
 * Murs interieurs (early return si eau presente)
 * ========================================================================= */
static void _draw_interior(void)
{
    u8 r, ox, oy, mxl, mxh, myl, myh;
    u8 n_elem, max_elem, shape, pat, px, py;
    u8 xlim, ylim, step, thr;

    s_int_wall_count = 0u;
    if (s_has_water) { return; }

    r    = _rng_u8();
    step = (u8)((u8)(s_room_w - _MW_MIN) * 24u);
    thr  = (u8)(179u - step);
    if (r < thr) return;

    mxl = (u8)(s_room_w >> 2u);
    mxh = (u8)(s_room_w - mxl - 2u);
    myl = (u8)(s_room_h >> 2u);
    myh = (u8)(s_room_h - myl - 2u);

    ox  = _rng_u8() & 0x01u;
    oy  = _rng_u8() & 0x01u;
    mxl = (u8)(mxl + ox);
    mxh = (u8)(mxh + ox);
    myl = (u8)(myl + oy);
    myh = (u8)(myh + oy);

    xlim = (u8)(s_room_w - 4u);
    ylim = (u8)(s_room_h - 4u);

    if (s_room_w >= 16u) {
        _place_elem(_rng_u8() % 3u, mxl, myl, xlim, ylim);
        _place_elem(_rng_u8() % 3u, mxh, myl, xlim, ylim);
        _place_elem(_rng_u8() % 3u, mxl, myh, xlim, ylim);
        _place_elem(_rng_u8() % 3u, mxh, myh, xlim, ylim);
        return;
    }

    if      (s_room_w <= 11u) { max_elem = 1u; }
    else if (s_room_w <= 13u) { max_elem = 2u; }
    else                      { max_elem = 3u; }

    n_elem = (u8)(_rng_u8() % max_elem + 1u);

    pat   = _rng_u8() & 0x03u;
    shape = _rng_u8() % 3u;
    if      (pat == 0u) { px = mxl; py = myl; }
    else if (pat == 1u) { px = mxh; py = myh; }
    else if (pat == 2u) { px = mxh; py = myl; }
    else                { px = mxl; py = myh; }
    _place_elem(shape, px, py, xlim, ylim);

    if (n_elem < 2u) { return; }

    shape = _rng_u8() % 3u;
    if      (pat == 0u) { px = mxh; py = myh; }
    else if (pat == 1u) { px = mxl; py = myl; }
    else if (pat == 2u) { px = mxl; py = myh; }
    else                { px = mxh; py = myl; }
    _place_elem(shape, px, py, xlim, ylim);

    if (n_elem < 3u) { return; }

    shape = _rng_u8() % 3u;
    if (_rng_u8() & 0x01u) { px = mxl; py = myl; }
    else                   { px = mxh; py = myl; }
    _place_elem(shape, px, py, xlim, ylim);
}

/* =========================================================================
 * Helper : le metatile (px,py) obstrue-t-il une sortie ?
 * ========================================================================= */
static u8 _on_exit(u8 px, u8 py, u8 exits)
{
    if (exits & _EXIT_N) {
        if (py == 1u) {
            if (px == s_door_col_lo) { return 1u; }
            if (px == s_door_col_hi) { return 1u; }
        }
    }
    if (exits & _EXIT_S) {
        if (py == (u8)(s_room_h - 2u)) {
            if (px == s_door_col_lo) { return 1u; }
            if (px == s_door_col_hi) { return 1u; }
        }
    }
    if (exits & _EXIT_W) {
        if (px == 1u) {
            if (py == s_door_row_lo) { return 1u; }
            if (py == s_door_row_hi) { return 1u; }
        }
    }
    if (exits & _EXIT_E) {
        if (px == (u8)(s_room_w - 2u)) {
            if (py == s_door_row_lo) { return 1u; }
            if (py == s_door_row_hi) { return 1u; }
        }
    }
    return 0u;
}

/* =========================================================================
 * Spawn des entites (interne)
 * ========================================================================= */
static void _spawn_entities(void)
{
    u8 n, cap, px, py, tries, ok, type, wi, spawn_item;
    u8 iw, ih, exits;
#if DUNGEONGEN_ENEMY_RAMP_ROOMS > 0
    u16 ramp;
    u8  ramp_bonus;
#endif

    ngpc_sprite_hide_all();

    iw    = (u8)(s_room_w - 2u);
    ih    = (u8)(s_room_h - 2u);
    exits = s_styles[s_style_idx].exits;

    s_enemy_count  = 0u;
    s_item_active  = 0u;
    s_is_safe_room = 0u;

    /* ---- Salle safe : pas d'ennemis, item garanti ---- */
#if DUNGEONGEN_SAFE_ROOM_EVERY > 0
    if (s_room_idx > 0u && (s_room_idx % (u16)DUNGEONGEN_SAFE_ROOM_EVERY) == 0u) {
        s_is_safe_room = 1u;
    }
#endif

#if DUNGEONGEN_ENEMY_MAX > 0
    if (s_is_safe_room == 0u) {
#if DUNGEONGEN_TIER_COLS > 0
        cap = s_tier_ene_max[s_tier];
        if (cap < (u8)_ENE_MIN) { cap = (u8)_ENE_MIN; }
        if (cap > (u8)_ENE_MAX) { cap = (u8)_ENE_MAX; }
#else
        cap = (u8)((u8)(iw * ih) / (u8)_ENE_DENS);
        if (cap < (u8)_ENE_MIN) { cap = (u8)_ENE_MIN; }
        if (cap > (u8)_ENE_MAX) { cap = (u8)_ENE_MAX; }
#endif

        /* ---- Rampe de difficulte par room_idx (bonus sur cap tier ou density) ---- */
#if DUNGEONGEN_ENEMY_RAMP_ROOMS > 0
        ramp = (u16)(s_room_idx / (u16)DUNGEONGEN_ENEMY_RAMP_ROOMS);
        ramp_bonus = (ramp > 7u) ? 7u : (u8)ramp;
        cap = (u8)(cap + ramp_bonus);
        if (cap > (u8)_ENE_MAX) { cap = (u8)_ENE_MAX; }
#endif

        if (cap > (u8)_ENE_MIN) {
            n = (u8)((u8)_ENE_MIN
                + _rng_u8() % (u8)((u8)(cap - (u8)_ENE_MIN) + 1u));
        } else {
            n = cap;
        }

        while (s_enemy_count < n) {
            ok = 0u;
            for (tries = 0u; tries < 8u; tries++) {
                if (ok) { break; }
                px = (u8)(1u + _rng_u8() % iw);
                py = (u8)(1u + _rng_u8() % ih);
                if (_on_exit(px, py, exits) == 0u) {
                    ok = 1u;
                    if (s_has_water) {
                        if (s_water_orient == 0u && py == s_water_band) { ok = 0u; }
                        if (s_water_orient != 0u && px == s_water_band) { ok = 0u; }
                    }
                    /* Rejection murs interieurs */
                    if (ok) {
                        for (wi = 0u; wi < s_int_wall_count; wi++) {
                            if (px >= s_int_wall_x[wi] &&
                                px < (u8)(s_int_wall_x[wi] + s_int_wall_w[wi]) &&
                                py >= s_int_wall_y[wi] &&
                                py < (u8)(s_int_wall_y[wi] + s_int_wall_h[wi])) {
                                ok = 0u;
                                break;
                            }
                        }
                    }
                }
            }
            if (ok == 0u) { break; }
#ifdef DUNGEONGEN_ENE_POOL_SIZE
            type = _pick_weighted_pool(s_ene_w, (u8)DUNGEONGEN_ENE_POOL_SIZE);
#else
            type = (_rng_u8() % 100u < (u8)_ENE2_PCT) ? 1u : 0u;
#endif
            s_enemy_wx[s_enemy_count] = (u8)((u8)(px * (u8)_CW) * 8u);
            s_enemy_wy[s_enemy_count] = (u8)((u8)(py * (u8)_CH) * 8u);
            s_enemy_type[s_enemy_count] = type;
            s_enemy_count = (u8)(s_enemy_count + 1u);
        }
    }
#endif

#if DUNGEONGEN_ITEM_FREQ > 0
    spawn_item = s_is_safe_room;
    if (spawn_item == 0u) {
#if DUNGEONGEN_TIER_COLS > 0
        if (_rng_u8() % 100u < s_tier_item_freq[s_tier]) { spawn_item = 1u; }
#else
        if (_rng_u8() % 100u < (u8)_ITEM_FREQ) { spawn_item = 1u; }
#endif
    }
    if (spawn_item) {
        ok = 0u;
        for (tries = 0u; tries < 8u; tries++) {
            if (ok) { break; }
            px = (u8)(1u + _rng_u8() % iw);
            py = (u8)(1u + _rng_u8() % ih);
            if (_on_exit(px, py, exits) == 0u) {
                ok = 1u;
                if (s_has_water) {
                    if (s_water_orient == 0u && py == s_water_band) { ok = 0u; }
                    if (s_water_orient != 0u && px == s_water_band) { ok = 0u; }
                }
                if (ok) {
                    for (wi = 0u; wi < s_int_wall_count; wi++) {
                        if (px >= s_int_wall_x[wi] &&
                            px < (u8)(s_int_wall_x[wi] + s_int_wall_w[wi]) &&
                            py >= s_int_wall_y[wi] &&
                            py < (u8)(s_int_wall_y[wi] + s_int_wall_h[wi])) {
                            ok = 0u;
                            break;
                        }
                    }
                }
            }
        }
        if (ok) {
            s_item_wx     = (u8)((u8)(px * (u8)_CW) * 8u);
            s_item_wy     = (u8)((u8)(py * (u8)_CH) * 8u);
            s_item_active = 1u;
#ifdef DUNGEONGEN_ITEM_POOL_SIZE
            s_item_type   = _pick_weighted_pool(s_item_w, (u8)DUNGEONGEN_ITEM_POOL_SIZE);
#else
            s_item_type   = 0u;
#endif
        }
    }
#endif
}

/* =========================================================================
 * Helper : cache N slots sprite consecutifs depuis base
 * ========================================================================= */
static void _spr_hide_n(u8 base, u8 n)
{
    u8 j;
    for (j = 0u; j < n; j++) {
        ngpc_sprite_hide((u8)(base + j));
    }
}

/* =========================================================================
 * Sync sprites -> ecran depuis positions monde + camera (interne)
 * ========================================================================= */
static void _sprites_sync(u8 cx, u8 cy)
{
    u8 i, sbase, isbase, sx, sy, vis;

    isbase = _SPR_ITEM_SLOT;

#if DUNGEONGEN_ENEMY_MAX > 0
    i = 0u;
    while (i < s_enemy_count) {
        sbase = (u8)(i * _ENE_SLOTS_PER);
        vis   = 0u;
        if (s_enemy_wx[i] >= cx) {
            if ((u8)(s_enemy_wx[i] - cx) < 160u) {
                if (s_enemy_wy[i] >= cy) {
                    if ((u8)(s_enemy_wy[i] - cy) < 152u) {
                        vis = 1u;
                    }
                }
            }
        }
        if (vis) {
            sx = (u8)(s_enemy_wx[i] - cx);
            sy = (u8)(s_enemy_wy[i] - cy);
#ifdef DUNGEONGEN_ENE_POOL_SIZE
            /* Pool mode : s_ene_tiles[], s_ene_pals[], s_ene_sz[] depuis sprites_lab.h */
            {
                u8 pi;
                u8 sz;
                pi = s_enemy_type[i];
                sz = s_ene_sz[pi];
                if (sz >= 16u) {
                    /* 32x32 : grille 4x4 de tiles 8x8 = 16 slots */
                    ngpc_sprite_set(sbase,           sx,           sy,
                        s_ene_tiles[pi],                           s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+1u),  (u8)(sx+8u),  sy,
                        (u16)(s_ene_tiles[pi]+1u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+2u),  (u8)(sx+16u), sy,
                        (u16)(s_ene_tiles[pi]+2u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+3u),  (u8)(sx+24u), sy,
                        (u16)(s_ene_tiles[pi]+3u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+4u),  sx,           (u8)(sy+8u),
                        (u16)(s_ene_tiles[pi]+4u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+5u),  (u8)(sx+8u),  (u8)(sy+8u),
                        (u16)(s_ene_tiles[pi]+5u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+6u),  (u8)(sx+16u), (u8)(sy+8u),
                        (u16)(s_ene_tiles[pi]+6u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+7u),  (u8)(sx+24u), (u8)(sy+8u),
                        (u16)(s_ene_tiles[pi]+7u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+8u),  sx,           (u8)(sy+16u),
                        (u16)(s_ene_tiles[pi]+8u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+9u),  (u8)(sx+8u),  (u8)(sy+16u),
                        (u16)(s_ene_tiles[pi]+9u),                 s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+10u), (u8)(sx+16u), (u8)(sy+16u),
                        (u16)(s_ene_tiles[pi]+10u),                s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+11u), (u8)(sx+24u), (u8)(sy+16u),
                        (u16)(s_ene_tiles[pi]+11u),                s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+12u), sx,           (u8)(sy+24u),
                        (u16)(s_ene_tiles[pi]+12u),                s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+13u), (u8)(sx+8u),  (u8)(sy+24u),
                        (u16)(s_ene_tiles[pi]+13u),                s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+14u), (u8)(sx+16u), (u8)(sy+24u),
                        (u16)(s_ene_tiles[pi]+14u),                s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+15u), (u8)(sx+24u), (u8)(sy+24u),
                        (u16)(s_ene_tiles[pi]+15u),                s_ene_pals[pi], (u8)SPR_FRONT);
                    _spr_hide_n((u8)(sbase+16u), (u8)(_ENE_SLOTS_PER - 16u));
                } else if (sz >= 4u) {
                    /* 16x16 : grille 2x2 = 4 slots */
                    ngpc_sprite_set(sbase,           sx,          sy,
                        s_ene_tiles[pi],              s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+1u),  (u8)(sx+8u), sy,
                        (u16)(s_ene_tiles[pi]+1u),    s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+2u),  sx,          (u8)(sy+8u),
                        (u16)(s_ene_tiles[pi]+2u),    s_ene_pals[pi], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(sbase+3u),  (u8)(sx+8u), (u8)(sy+8u),
                        (u16)(s_ene_tiles[pi]+3u),    s_ene_pals[pi], (u8)SPR_FRONT);
                    _spr_hide_n((u8)(sbase+4u), (u8)(_ENE_SLOTS_PER - 4u));
                } else {
                    /* 8x8 : 1 slot */
                    ngpc_sprite_set(sbase, sx, sy,
                        s_ene_tiles[pi], s_ene_pals[pi], (u8)SPR_FRONT);
                    _spr_hide_n((u8)(sbase+1u), (u8)(_ENE_SLOTS_PER - 1u));
                }
            }
#else
            /* Legacy mode : ENE1 (16x16) / ENE2 (8x8) depuis sprites_lab.h statique */
            if (s_enemy_type[i] == 0u) {
                ngpc_sprite_set(sbase,           sx,          sy,
                    SPR_ENE1_TILE,           PAL_SPR_ENE1, (u8)SPR_FRONT);
                ngpc_sprite_set((u8)(sbase+1u),  (u8)(sx+8u), sy,
                    (u16)(SPR_ENE1_TILE+1u), PAL_SPR_ENE1, (u8)SPR_FRONT);
                ngpc_sprite_set((u8)(sbase+2u),  sx,          (u8)(sy+8u),
                    (u16)(SPR_ENE1_TILE+2u), PAL_SPR_ENE1, (u8)SPR_FRONT);
                ngpc_sprite_set((u8)(sbase+3u),  (u8)(sx+8u), (u8)(sy+8u),
                    (u16)(SPR_ENE1_TILE+3u), PAL_SPR_ENE1, (u8)SPR_FRONT);
            } else {
                ngpc_sprite_set(sbase, sx, sy,
                    SPR_ENE2_TILE, PAL_SPR_ENE2, (u8)SPR_FRONT);
                ngpc_sprite_hide((u8)(sbase+1u));
                ngpc_sprite_hide((u8)(sbase+2u));
                ngpc_sprite_hide((u8)(sbase+3u));
            }
#endif
        } else {
            _spr_hide_n(sbase, _ENE_SLOTS_PER);
        }
        i = (u8)(i + 1u);
    }
    while (i < (u8)_ENE_MAX) {
        sbase = (u8)(i * _ENE_SLOTS_PER);
        _spr_hide_n(sbase, _ENE_SLOTS_PER);
        i = (u8)(i + 1u);
    }
#endif

#if DUNGEONGEN_ITEM_FREQ > 0
    if (s_item_active) {
        vis = 0u;
        if (s_item_wx >= cx) {
            if ((u8)(s_item_wx - cx) < 160u) {
                if (s_item_wy >= cy) {
                    if ((u8)(s_item_wy - cy) < 152u) {
                        vis = 1u;
                    }
                }
            }
        }
        if (vis) {
            sx = (u8)(s_item_wx - cx);
            sy = (u8)(s_item_wy - cy);
#ifdef DUNGEONGEN_ITEM_POOL_SIZE
            /* Pool mode : s_item_tiles[], s_item_pals[], s_item_sz[] depuis sprites_lab.h */
            {
                u8 isz;
                isz = s_item_sz[s_item_type];
                if (isz >= 4u) {
                    /* 16x16 : grille 2x2 */
                    ngpc_sprite_set(isbase,           sx,          sy,
                        s_item_tiles[s_item_type],              s_item_pals[s_item_type], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(isbase+1u),  (u8)(sx+8u), sy,
                        (u16)(s_item_tiles[s_item_type]+1u),    s_item_pals[s_item_type], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(isbase+2u),  sx,          (u8)(sy+8u),
                        (u16)(s_item_tiles[s_item_type]+2u),    s_item_pals[s_item_type], (u8)SPR_FRONT);
                    ngpc_sprite_set((u8)(isbase+3u),  (u8)(sx+8u), (u8)(sy+8u),
                        (u16)(s_item_tiles[s_item_type]+3u),    s_item_pals[s_item_type], (u8)SPR_FRONT);
                } else {
                    /* 8x8 : 1 slot */
                    ngpc_sprite_set(isbase, sx, sy,
                        s_item_tiles[s_item_type], s_item_pals[s_item_type], (u8)SPR_FRONT);
                    ngpc_sprite_hide((u8)(isbase+1u));
                    ngpc_sprite_hide((u8)(isbase+2u));
                    ngpc_sprite_hide((u8)(isbase+3u));
                }
            }
#else
            /* Legacy mode : item unique depuis sprites_lab.h statique */
            ngpc_sprite_set(isbase,           sx,          sy,
                SPR_ITEM_TILE,           PAL_SPR_ITEM, (u8)SPR_FRONT);
            ngpc_sprite_set((u8)(isbase+1u),  (u8)(sx+8u), sy,
                (u16)(SPR_ITEM_TILE+1u), PAL_SPR_ITEM, (u8)SPR_FRONT);
            ngpc_sprite_set((u8)(isbase+2u),  sx,          (u8)(sy+8u),
                (u16)(SPR_ITEM_TILE+2u), PAL_SPR_ITEM, (u8)SPR_FRONT);
            ngpc_sprite_set((u8)(isbase+3u),  (u8)(sx+8u), (u8)(sy+8u),
                (u16)(SPR_ITEM_TILE+3u), PAL_SPR_ITEM, (u8)SPR_FRONT);
#endif
        } else {
            ngpc_sprite_hide(isbase);
            ngpc_sprite_hide((u8)(isbase+1u));
            ngpc_sprite_hide((u8)(isbase+2u));
            ngpc_sprite_hide((u8)(isbase+3u));
        }
    } else {
        ngpc_sprite_hide(isbase);
        ngpc_sprite_hide((u8)(isbase+1u));
        ngpc_sprite_hide((u8)(isbase+2u));
        ngpc_sprite_hide((u8)(isbase+3u));
    }
#endif
}

/* =========================================================================
 * Plan bande d'eau (calcule avant draw_interior)
 * ========================================================================= */
static void _plan_water(void)
{
    u8 exits, n_exits, iw, ih;

    s_has_water    = 0u;
    s_water_orient = 0u;
    s_water_band   = 0u;
    s_bridge_px    = (u8)(s_room_w >> 1u);
    s_bridge_py    = (u8)(s_room_h >> 1u);

#if DUNGEONGEN_EAU_FREQ > 0
    exits   = s_styles[s_style_idx].exits;
    n_exits = 0u;
    if (exits & _EXIT_N) { n_exits = (u8)(n_exits + 1u); }
    if (exits & _EXIT_S) { n_exits = (u8)(n_exits + 1u); }
    if (exits & _EXIT_E) { n_exits = (u8)(n_exits + 1u); }
    if (exits & _EXIT_W) { n_exits = (u8)(n_exits + 1u); }
    iw = (u8)(s_room_w - 2u);
    ih = (u8)(s_room_h - 2u);

#if DUNGEONGEN_TIER_COLS > 0
    if (n_exits <= 2u && _rng_u8() % 100u < s_tier_eau_freq[s_tier]) {
#else
    if (n_exits <= 2u && _rng_u8() % 100u < (u8)_EAU_FREQ) {
#endif
        s_water_orient = _rng_u8() & 0x01u;
        if (s_water_orient == 0u) {
            s_water_band = (_rng_u8() & 0x01u)
                ? (u8)(s_room_h / 3u) : (u8)((s_room_h * 2u) / 3u);
            s_bridge_py  = s_water_band;
            if (exits & (u8)(_EXIT_N | _EXIT_S)) {
                s_bridge_px = s_door_col_lo;
            } else {
                s_bridge_px = (u8)(1u + _rng_u8() % iw);
            }
        } else {
            s_water_band = (_rng_u8() & 0x01u)
                ? (u8)(s_room_w / 3u) : (u8)((s_room_w * 2u) / 3u);
            s_bridge_px  = s_water_band;
            if (exits & (u8)(_EXIT_E | _EXIT_W)) {
                s_bridge_py = s_door_row_lo;
            } else {
                s_bridge_py = (u8)(1u + _rng_u8() % ih);
            }
        }
        s_has_water = 1u;
    }
#endif
}

/* =========================================================================
 * Population visuelle (eau, vide, tonneau, escalier)
 * ========================================================================= */
static void _draw_population(void)
{
    u8 r, px, py;
    u8 iw, ih;
    u8 wall;
    u8 exits;
    u8 tries, ok, in_dc, in_dr;

    iw    = (u8)(s_room_w - 2u);
    ih    = (u8)(s_room_h - 2u);
    exits = s_styles[s_style_idx].exits;

#if DUNGEONGEN_EAU_FREQ > 0
    if (s_has_water) {
        if (s_water_orient == 0u) {
            for (px = 1u; px < (u8)(s_room_w - 1u); px++)
                _put_cell(px, s_water_band, TILE_EAU_H, PAL_EAU);
            if (exits & (u8)(_EXIT_N | _EXIT_S)) {
                _put_cell(s_door_col_lo, s_water_band, TILE_PONT_H, PAL_BRIDGE);
                _put_cell(s_door_col_hi, s_water_band, TILE_PONT_H, PAL_BRIDGE);
            } else {
                _put_cell(s_bridge_px, s_water_band, TILE_PONT_H, PAL_BRIDGE);
            }
        } else {
            for (py = 1u; py < (u8)(s_room_h - 1u); py++)
                _put_cell(s_water_band, py, TILE_EAU_V, PAL_EAU);
            if (exits & (u8)(_EXIT_E | _EXIT_W)) {
                _put_cell(s_water_band, s_door_row_lo, TILE_PONT_V, PAL_BRIDGE);
                _put_cell(s_water_band, s_door_row_hi, TILE_PONT_V, PAL_BRIDGE);
            } else {
                _put_cell(s_water_band, s_bridge_py, TILE_PONT_V, PAL_BRIDGE);
            }
        }
    }
#endif

#if DUNGEONGEN_VIDE_FREQ > 0
    if (iw >= 3u && ih >= 3u) {
#if DUNGEONGEN_TIER_COLS > 0
        if (_rng_u8() % 100u < s_tier_vide_freq[s_tier]) {
#else
        if (_rng_u8() % 100u < (u8)_VIDE_FREQ) {
#endif
            ok = 0u;
            for (tries = 0u; tries < 6u && ok == 0u; tries++) {
                px = (u8)(1u + _rng_u8() % (u8)(iw - 1u));
                py = (u8)(1u + _rng_u8() % (u8)(ih - 1u));
                in_dc = 0u;
                if (px <= s_door_col_hi && (u8)(px+1u) >= s_door_col_lo) in_dc = 1u;
                in_dr = 0u;
                if (py <= s_door_row_hi && (u8)(py+1u) >= s_door_row_lo) in_dr = 1u;
                ok = 1u;
                if (in_dc) {
                    if ((exits & _EXIT_N) && py < (u8)(1u + _VIDE_MARGIN)) { ok = 0u; }
                    if ((exits & _EXIT_S) && (u8)(py+1u) > (u8)(s_room_h - 2u - _VIDE_MARGIN)) { ok = 0u; }
                }
                if (in_dr) {
                    if ((exits & _EXIT_W) && px < (u8)(1u + _VIDE_MARGIN)) { ok = 0u; }
                    if ((exits & _EXIT_E) && (u8)(px+1u) > (u8)(s_room_w - 2u - _VIDE_MARGIN)) { ok = 0u; }
                }
                /* Exclude void from center 4x4 zone where player spawns */
                { u8 cx = (u8)(s_room_w / 2u); u8 cy = (u8)(s_room_h / 2u);
                  if (ok && (u8)(px+1u) >= (u8)(cx-1u) && px < (u8)(cx+1u)
                         && (u8)(py+1u) >= (u8)(cy-1u) && py < (u8)(cy+1u)) { ok = 0u; } }
            }
            if (ok) {
                _put_cell(px,            py,            TILE_VIDE_BORD, PAL_DECO);
                _put_cell((u8)(px+1u),   py,            TILE_VIDE_BORD, PAL_DECO);
                _put_cell(px,            (u8)(py+1u),   TILE_VIDE,      PAL_DECO);
                _put_cell((u8)(px+1u),   (u8)(py+1u),   TILE_VIDE,      PAL_DECO);
                s_has_vide = 1u;
                s_vide_x   = px;
                s_vide_y   = py;
            }
        }
    }
#endif

#if DUNGEONGEN_TONNEAU_FREQ > 0
    r = _rng_u8();
    if (r % 100u < (u8)_TNO_FREQ) {
        ok = 0u;
        for (tries = 0u; tries < 4u; tries++) {
            if (ok) { break; }
            wall = _rng_u8() & 0x03u;
            if      (wall == 0u) { px = (u8)(1u + _rng_u8() % iw); py = 1u; }
            else if (wall == 1u) { px = (u8)(1u + _rng_u8() % iw); py = (u8)(s_room_h - 2u); }
            else if (wall == 2u) { px = 1u; py = (u8)(1u + _rng_u8() % ih); }
            else                 { px = (u8)(s_room_w - 2u); py = (u8)(1u + _rng_u8() % ih); }
            if (_on_exit(px, py, exits) == 0u) { ok = 1u; }
        }
        if (ok) {
            _put_cell(px, py, TILE_TONNEAU, PAL_DECO);
            if (s_tonneau_count < 2u) { s_tonneau_x[s_tonneau_count] = px; s_tonneau_y[s_tonneau_count] = py; s_tonneau_count = (u8)(s_tonneau_count + 1u); }
        }
#if DUNGEONGEN_TONNEAU_MAX >= 2
        if (r >= 200u) {
            ok = 0u;
            for (tries = 0u; tries < 4u; tries++) {
                if (ok) { break; }
                wall = _rng_u8() & 0x03u;
                if      (wall == 0u) { px = (u8)(1u + _rng_u8() % iw); py = 1u; }
                else if (wall == 1u) { px = (u8)(1u + _rng_u8() % iw); py = (u8)(s_room_h - 2u); }
                else if (wall == 2u) { px = 1u; py = (u8)(1u + _rng_u8() % ih); }
                else                 { px = (u8)(s_room_w - 2u); py = (u8)(1u + _rng_u8() % ih); }
                if (_on_exit(px, py, exits) == 0u) { ok = 1u; }
            }
            if (ok) {
                _put_cell(px, py, TILE_TONNEAU, PAL_DECO);
                if (s_tonneau_count < 2u) { s_tonneau_x[s_tonneau_count] = px; s_tonneau_y[s_tonneau_count] = py; s_tonneau_count = (u8)(s_tonneau_count + 1u); }
            }
        }
#endif
    }
#endif

    /* Escalier : place par ngpc_dungeongen_set_room_type() (modele cluster).
     * Ne pas placer ici : position deterministe par le module cluster. */
}

/* =========================================================================
 * Predicats portes (inline)
 * ========================================================================= */
static u8 _dn(u8 mx, u8 exits) { return (exits & _EXIT_N) && mx >= s_door_col_lo && mx <= s_door_col_hi; }
static u8 _ds(u8 mx, u8 exits) { return (exits & _EXIT_S) && mx >= s_door_col_lo && mx <= s_door_col_hi; }
static u8 _dw(u8 my, u8 exits) { return (exits & _EXIT_W) && my >= s_door_row_lo && my <= s_door_row_hi; }
static u8 _de(u8 my, u8 exits) { return (exits & _EXIT_E) && my >= s_door_row_lo && my <= s_door_row_hi; }

/* =========================================================================
 * Selection de sol ponderee
 * ========================================================================= */
static u16 _ground_tile(void)
{
    u8 r = _rng_u8() % 100u;
    if (r < (u8)_GPC_1)                        return TILE_GROUND_1;
    if (r < (u8)((u8)_GPC_1 + (u8)_GPC_2))    return TILE_GROUND_2;
    return TILE_GROUND_3;
}

/* =========================================================================
 * Dessin complet d'une salle
 * ========================================================================= */
static void _draw_room(void)
{
    u8 mx, my;
    u8 exits = s_styles[s_style_idx].exits;

    /* Sol : seed par room_idx uniquement (stable meme si style change) */
    _rng_seed_room(s_room_idx, 0u);
    for (my = 1u; my < (u8)(s_room_h - 1u); my++)
        for (mx = 1u; mx < (u8)(s_room_w - 1u); mx++)
            _put_cell(mx, my, _ground_tile(), PAL_GROUND);

    /* Coins */
    _put_cell_ex(0u,                  0u,                  TILE_WALL_EXT_NW, PAL_WALL_EXT, TILE_WALL_EXT_NW_FLIP);
    _put_cell_ex((u8)(s_room_w - 1u), 0u,                  TILE_WALL_EXT_NE, PAL_WALL_EXT, TILE_WALL_EXT_NE_FLIP);
    _put_cell_ex(0u,                  (u8)(s_room_h - 1u), TILE_WALL_EXT_SW, PAL_WALL_EXT, TILE_WALL_EXT_SW_FLIP);
    _put_cell_ex((u8)(s_room_w - 1u), (u8)(s_room_h - 1u), TILE_WALL_EXT_SE, PAL_WALL_EXT, TILE_WALL_EXT_SE_FLIP);

    /* Murs perimetre avec ouvertures de sorties */
    for (mx = 1u; mx < (u8)(s_room_w - 1u); mx++)
        _put_cell_ex(mx, 0u,
            _dn(mx, exits) ? TILE_DOOR_N            : TILE_WALL_EXT_N,
            _dn(mx, exits) ? (u8)PAL_GROUND          : (u8)PAL_WALL_EXT,
            _dn(mx, exits) ? (u8)TILE_DOOR_N_FLIP    : (u8)TILE_WALL_EXT_N_FLIP);
    for (mx = 1u; mx < (u8)(s_room_w - 1u); mx++)
        _put_cell_ex(mx, (u8)(s_room_h - 1u),
            _ds(mx, exits) ? TILE_DOOR_S            : TILE_WALL_EXT_S,
            _ds(mx, exits) ? (u8)PAL_GROUND          : (u8)PAL_WALL_EXT,
            _ds(mx, exits) ? (u8)TILE_DOOR_S_FLIP    : (u8)TILE_WALL_EXT_S_FLIP);
    for (my = 1u; my < (u8)(s_room_h - 1u); my++)
        _put_cell_ex(0u, my,
            _dw(my, exits) ? TILE_DOOR_W            : TILE_WALL_EXT_W,
            _dw(my, exits) ? (u8)PAL_GROUND          : (u8)PAL_WALL_EXT,
            _dw(my, exits) ? (u8)TILE_DOOR_W_FLIP    : (u8)TILE_WALL_EXT_W_FLIP);
    for (my = 1u; my < (u8)(s_room_h - 1u); my++)
        _put_cell_ex((u8)(s_room_w - 1u), my,
            _de(my, exits) ? TILE_DOOR_E            : TILE_WALL_EXT_E,
            _de(my, exits) ? (u8)PAL_GROUND          : (u8)PAL_WALL_EXT,
            _de(my, exits) ? (u8)TILE_DOOR_E_FLIP    : (u8)TILE_WALL_EXT_E_FLIP);

    /* Population */
    _rng_seed_room(s_room_idx, s_style_idx);
    _plan_water();
    _draw_interior();
    _draw_population();
}

/* =========================================================================
 * Selection ponderee dans un pool (u8 safe, pas de float)
 * w[n] : tableaux de poids (somme > 0).
 * Retourne l'index selectionne (0..n-1).
 * ========================================================================= */
static u8 _pick_weighted_pool(const u8 *w, u8 n)
{
    u8 i;
    u8 total;
    u8 acc;
    u8 r;

    total = 0u;
    for (i = 0u; i < n; i++) { total = (u8)(total + w[i]); }
    if (total == 0u) { return 0u; }

    r   = _rng_u8() % total;
    acc = 0u;
    for (i = 0u; i < (u8)(n - 1u); i++) {
        acc = (u8)(acc + w[i]);
        if (r < acc) { return i; }
    }
    return (u8)(n - 1u);
}

/* =========================================================================
 * API PUBLIQUE
 * ========================================================================= */

void ngpc_dungeongen_set_rtc_seed(void)
{
    NgpcTime t;
    ngpc_rtc_get(&t);
    s_global_seed = (u16)((u16)t.second
                  ^ ((u16)t.minute  << 4u)
                  ^ ((u16)t.hour    << 8u)
                  ^ ((u16)t.day     << 1u));
}

void ngpc_dungeongen_set_seed(u16 seed)
{
    s_global_seed = seed ? seed : 1u;
}

u8 ngpc_dungeongen_style_for_exits(u8 exits_mask)
{
    u8 i;
    u8 n = (u8)(sizeof(s_styles) / sizeof(s_styles[0]));
    for (i = 0u; i < n; i++) {
        if (s_styles[i].exits == exits_mask) { return i; }
    }
    return 0u; /* fallback : salle fermee */
}

void ngpc_dungeongen_init(void)
{
    ngpc_gfx_load_tiles_at(TILES_PROCGEN, TILES_PROCGEN_COUNT, TILE_BASE);
    ngpc_gfx_load_tiles_at(SPRITES_LAB,  SPRITES_LAB_COUNT,  SPR_TILE_BASE);

    /* Palettes BG — une par groupe de tiles (peut partager un meme slot si couleurs compatibles) */
    ngpc_gfx_set_palette(GFX_SCR1, PAL_GROUND,
        PAL_GROUND_C0,   PAL_GROUND_C1,   PAL_GROUND_C2,   PAL_GROUND_C3);
    ngpc_gfx_set_palette(GFX_SCR1, PAL_WALL_EXT,
        PAL_WALL_EXT_C0, PAL_WALL_EXT_C1, PAL_WALL_EXT_C2, PAL_WALL_EXT_C3);
    ngpc_gfx_set_palette(GFX_SCR1, PAL_WALL_INT,
        PAL_WALL_INT_C0, PAL_WALL_INT_C1, PAL_WALL_INT_C2, PAL_WALL_INT_C3);
    ngpc_gfx_set_palette(GFX_SCR1, PAL_EAU,
        PAL_EAU_C0,      PAL_EAU_C1,      PAL_EAU_C2,      PAL_EAU_C3);
    ngpc_gfx_set_palette(GFX_SCR1, PAL_BRIDGE,
        PAL_BRIDGE_C0,   PAL_BRIDGE_C1,   PAL_BRIDGE_C2,   PAL_BRIDGE_C3);
    ngpc_gfx_set_palette(GFX_SCR1, PAL_DECO,
        PAL_DECO_C0,     PAL_DECO_C1,     PAL_DECO_C2,     PAL_DECO_C3);

    ngpc_gfx_set_palette(GFX_SPR, PAL_SPR_ENE1,
        PAL_SPR_ENE1_C0, PAL_SPR_ENE1_C1, PAL_SPR_ENE1_C2, PAL_SPR_ENE1_C3);
    ngpc_gfx_set_palette(GFX_SPR, PAL_SPR_ENE2,
        PAL_SPR_ENE2_C0, PAL_SPR_ENE2_C1, PAL_SPR_ENE2_C2, PAL_SPR_ENE2_C3);
    ngpc_gfx_set_palette(GFX_SPR, PAL_SPR_ITEM,
        PAL_SPR_ITEM_C0, PAL_SPR_ITEM_C1, PAL_SPR_ITEM_C2, PAL_SPR_ITEM_C3);
}

u8 ngpc_dungeongen_n_styles(void)
{
    return (u8)_N_STY;
}

void ngpc_dungeongen_enter(u16 room_idx, u8 style_idx)
{
    u16 tmp;
#if DUNGEONGEN_MIN_EXITS > 0
    u8 exits_count;
    u8 tries_style;
#endif

    s_room_idx  = room_idx;
    s_room_w    = _room_w_for(room_idx);
    s_room_h    = _room_h_for(room_idx);

    if (style_idx == 0xFFu) {
        s_style_idx = _style_for(room_idx);
    } else {
        s_style_idx = (u8)(style_idx % (u8)_N_STY);
    }

#if DUNGEONGEN_MIN_EXITS > 0
    for (tries_style = 0u; tries_style < (u8)_N_STY; tries_style++) {
        exits_count = 0u;
        if (s_styles[s_style_idx].exits & _EXIT_N) { exits_count = (u8)(exits_count + 1u); }
        if (s_styles[s_style_idx].exits & _EXIT_S) { exits_count = (u8)(exits_count + 1u); }
        if (s_styles[s_style_idx].exits & _EXIT_E) { exits_count = (u8)(exits_count + 1u); }
        if (s_styles[s_style_idx].exits & _EXIT_W) { exits_count = (u8)(exits_count + 1u); }
        if (exits_count >= (u8)DUNGEONGEN_MIN_EXITS) { break; }
        s_style_idx = (u8)((u8)(s_style_idx + 1u) % (u8)_N_STY);
    }
#endif

    s_door_col_lo = (u8)(s_room_w / 2u - 1u);
    s_door_col_hi = (u8)(s_room_w / 2u);
    s_door_row_lo = (u8)(s_room_h / 2u - 1u);
    s_door_row_hi = (u8)(s_room_h / 2u);
    s_has_vide    = 0u;
    s_vide_x      = 0u;
    s_vide_y      = 0u;

    tmp = (u16)((u16)s_room_w * (u16)_CW);
    ngpc_dgroom.scroll_max_x = (tmp > 20u) ? (s16)((tmp - 20u) * 8u) : 0;
    tmp = (u16)((u16)s_room_h * (u16)_CH);
    ngpc_dgroom.scroll_max_y = (tmp > 19u) ? (s16)((tmp - 19u) * 8u) : 0;

    ngpc_dgroom.room_w      = s_room_w;
    ngpc_dgroom.room_h      = s_room_h;
    ngpc_dgroom.exits       = s_styles[s_style_idx].exits;
    ngpc_dgroom.style_idx   = s_style_idx;
    ngpc_dgroom.door_col_lo = s_door_col_lo;
    ngpc_dgroom.door_col_hi = s_door_col_hi;
    ngpc_dgroom.door_row_lo = s_door_row_lo;
    ngpc_dgroom.door_row_hi = s_door_row_hi;

    /* Navigation cluster : reset, defini apres par ngpc_dungeongen_set_room_type() */
    s_has_stair     = 0u;
    s_stair_mx      = 0u;
    s_stair_my      = 0u;
    s_tonneau_count = 0u;
    ngpc_dgroom.room_type = DGEN_ROOM_ENTRY;
    ngpc_dgroom.has_stair = 0u;
    ngpc_dgroom.stair_mx  = 0u;
    ngpc_dgroom.stair_my  = 0u;

    ngpc_gfx_clear(_PLANE);
    _draw_room();
    ngpc_dgroom.has_water = s_has_water;
}

void ngpc_dungeongen_spawn(void)
{
    _spawn_entities();
    ngpc_dgroom.enemy_count  = s_enemy_count;
    ngpc_dgroom.item_active  = s_item_active;
    ngpc_dgroom.is_safe_room = s_is_safe_room;
}

void ngpc_dungeongen_sync_sprites(u8 cam_x, u8 cam_y)
{
    _sprites_sync(cam_x, cam_y);
}

u8 ngpc_dungeongen_enemy_count(void)
{
    return s_enemy_count;
}

u8 ngpc_dungeongen_enemy_world_x(u8 idx)
{
    if (idx >= s_enemy_count) { return 0u; }
    return s_enemy_wx[idx];
}

u8 ngpc_dungeongen_enemy_world_y(u8 idx)
{
    if (idx >= s_enemy_count) { return 0u; }
    return s_enemy_wy[idx];
}

u8 ngpc_dungeongen_enemy_type_index(u8 idx)
{
    if (idx >= s_enemy_count) { return 0u; }
    return s_enemy_type[idx];
}

u16 ngpc_dungeongen_room_seed(u16 room_idx)
{
    u16 s = (u16)((u16)((room_idx + 1u) * 191u) ^ s_global_seed);
    if (s == 0u) { s = 0xA5C3u; }
    s ^= (u16)(s << 7u);
    s ^= (u16)(s >> 9u);
    s ^= (u16)(s << 8u);
    return s;
}

static u8 _world_to_mx(s16 wx)
{
    if (wx < 0) { return 0xFFu; }
    return (u8)((u16)(wx / (s16)_CELL_PX));
}

static u8 _world_to_my(s16 wy)
{
    if (wy < 0) { return 0xFFu; }
    return (u8)((u16)(wy / (s16)_CELL_PY));
}

u8 ngpc_dungeongen_collision_at(u8 mx, u8 my)
{
    u8 exits;
    u8 wi;
    u8 ti;

    /* Hors de la salle = solide */
    if (mx >= s_room_w || my >= s_room_h) { return DGNCOL_SOLID; }

    exits = s_styles[s_style_idx].exits;

    /* Bords exterieurs = mur, SAUF les ouvertures actives du cote concerne. */
    if (mx == 0u) {
        if (_dw(my, exits)) { return DGNCOL_PASS; }
        return DGNCOL_SOLID;
    }
    if (mx == (u8)(s_room_w - 1u)) {
        if (_de(my, exits)) { return DGNCOL_PASS; }
        return DGNCOL_SOLID;
    }
    if (my == 0u) {
        if (_dn(mx, exits)) { return DGNCOL_PASS; }
        return DGNCOL_SOLID;
    }
    if (my == (u8)(s_room_h - 1u)) {
        if (_ds(mx, exits)) { return DGNCOL_PASS; }
        return DGNCOL_SOLID;
    }

    /* Bande d'eau */
    if (s_has_water) {
        if (s_water_orient == 0u && my == s_water_band) {
            /* Case pont = passable */
            if (mx == s_bridge_px) { return DGNCOL_PASS; }
            if ((exits & (u8)(_EXIT_N | _EXIT_S)) &&
                (mx == s_door_col_lo || mx == s_door_col_hi)) { return DGNCOL_PASS; }
            return (u8)DUNGEONGEN_WATER_COL;
        }
        if (s_water_orient != 0u && mx == s_water_band) {
            if (my == s_bridge_py) { return DGNCOL_PASS; }
            if ((exits & (u8)(_EXIT_E | _EXIT_W)) &&
                (my == s_door_row_lo || my == s_door_row_hi)) { return DGNCOL_PASS; }
            return (u8)DUNGEONGEN_WATER_COL;
        }
    }

    /* Fosse (vide) : bloc 2x2 stocke dans s_vide_x/y */
    if (s_has_vide
     && mx >= s_vide_x && mx < (u8)(s_vide_x + 2u)
     && my >= s_vide_y && my < (u8)(s_vide_y + 2u))
    { return DGNCOL_VOID; }

    /* Murs interieurs enregistres = solide */
    for (wi = 0u; wi < s_int_wall_count; wi++) {
        if (mx >= s_int_wall_x[wi]
         && mx < (u8)(s_int_wall_x[wi] + s_int_wall_w[wi])
         && my >= s_int_wall_y[wi]
         && my < (u8)(s_int_wall_y[wi] + s_int_wall_h[wi]))
        { return DGNCOL_SOLID; }
    }

    /* Escalier = trigger (game code decide quoi faire) */
    if (s_has_stair && mx == s_stair_mx && my == s_stair_my) {
        return DGNCOL_TRIGGER;
    }

    /* Tonneaux = solide */
    for (ti = 0u; ti < s_tonneau_count; ti++) {
        if (mx == s_tonneau_x[ti] && my == s_tonneau_y[ti]) { return DGNCOL_SOLID; }
    }

    return DGNCOL_PASS;
}

u8 ngpc_dungeongen_world_rect_hits_solid(s16 wx0, s16 wy0, s16 wx1, s16 wy1)
{
    s16 rpw;
    s16 rph;
    u8 mx;
    u8 my;

    rpw = (s16)((s16)s_room_w * (s16)_CELL_PX);
    rph = (s16)((s16)s_room_h * (s16)_CELL_PY);

    if (wx1 < wx0 || wy1 < wy0) { return 0u; }

    /* Coins hors salle = zone de sortie, pas de collision.
     * Seuls les coins a l'interieur de la salle [0..rpw[ x [0..rph[ sont testes.
     * Cela permet au joueur de franchir les ouvertures N/S/E/W sans etre bloque. */
    if (wx0 >= 0 && wy0 >= 0 && wx0 < rpw && wy0 < rph) {
        mx = _world_to_mx(wx0); my = _world_to_my(wy0);
        if (ngpc_dungeongen_collision_at(mx, my) == DGNCOL_SOLID) { return 1u; }
    }
    if (wx1 >= 0 && wy0 >= 0 && wx1 < rpw && wy0 < rph) {
        mx = _world_to_mx(wx1); my = _world_to_my(wy0);
        if (ngpc_dungeongen_collision_at(mx, my) == DGNCOL_SOLID) { return 1u; }
    }
    if (wx0 >= 0 && wy1 >= 0 && wx0 < rpw && wy1 < rph) {
        mx = _world_to_mx(wx0); my = _world_to_my(wy1);
        if (ngpc_dungeongen_collision_at(mx, my) == DGNCOL_SOLID) { return 1u; }
    }
    if (wx1 >= 0 && wy1 >= 0 && wx1 < rpw && wy1 < rph) {
        mx = _world_to_mx(wx1); my = _world_to_my(wy1);
        if (ngpc_dungeongen_collision_at(mx, my) == DGNCOL_SOLID) { return 1u; }
    }
    return 0u;
}

void ngpc_dungeongen_set_room_type(u8 room_type, u8 avec_escalier)
{
    u8 mx;
    u8 my;
    u8 tries;
    u8 ok;
    u8 exits;
    u8 wi;

    ngpc_dgroom.room_type = room_type;
    s_has_stair = 0u;
    ngpc_dgroom.has_stair = 0u;
    ngpc_dgroom.stair_mx  = 0u;
    ngpc_dgroom.stair_my  = 0u;

    if (room_type != (u8)DGEN_ROOM_LEAF) { return; }
    if (avec_escalier == 0u)             { return; }

    /* Placer l'escalier : trouver une case de sol libre */
    exits  = s_styles[s_style_idx].exits;
    tries  = 0u;
    ok     = 0u;
    mx     = 0u;
    my     = 0u;

    while (tries < 32u) {
        mx = (u8)(1u + _rng_u8() % (u8)(s_room_w - 2u));
        my = (u8)(1u + _rng_u8() % (u8)(s_room_h - 2u));
        ok = 1u;

        /* Pas dans une ouverture murale */
        if (_dn(mx, exits) && my == 0u)                  { ok = 0u; }
        if (_ds(mx, exits) && my == (u8)(s_room_h - 1u)) { ok = 0u; }

        /* Pas sur la bande d'eau */
        if (s_has_water) {
            if (s_water_orient == 0u && my == s_water_band) { ok = 0u; }
            if (s_water_orient != 0u && mx == s_water_band) { ok = 0u; }
        }

        /* Pas sur un mur interieur */
        wi = 0u;
        while (wi < s_int_wall_count && ok) {
            if (mx >= s_int_wall_x[wi]
             && mx < (u8)(s_int_wall_x[wi] + s_int_wall_w[wi])
             && my >= s_int_wall_y[wi]
             && my < (u8)(s_int_wall_y[wi] + s_int_wall_h[wi]))
            { ok = 0u; }
            wi = (u8)(wi + 1u);
        }

        if (ok) { break; }
        tries = (u8)(tries + 1u);
    }

    if (ok) {
        s_has_stair       = 1u;
        s_stair_mx        = mx;
        s_stair_my        = my;
        ngpc_dgroom.has_stair = 1u;
        ngpc_dgroom.stair_mx  = mx;
        ngpc_dgroom.stair_my  = my;
        _put_cell(mx, my, TILE_EXIT_STAIR, PAL_DECO);
    }
}

#if DUNGEONGEN_TIER_COLS > 0
void ngpc_dungeongen_set_tier(u8 tier)
{
    s_tier = (tier < (u8)DUNGEONGEN_TIER_COLS)
           ? tier
           : (u8)((u8)DUNGEONGEN_TIER_COLS - 1u);
}

u8 ngpc_dungeongen_get_tier(void)
{
    return s_tier;
}
#endif /* DUNGEONGEN_TIER_COLS > 0 */
