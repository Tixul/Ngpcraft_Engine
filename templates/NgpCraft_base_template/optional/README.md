# Modules optionnels NGPC

Modules **à la carte** — ne font pas partie du template de base.
Copie uniquement ce dont tu as besoin dans `src/` pour ne pas alourdir la RAM, la compilation ni le dossier projet.

---

## Comment utiliser un module

1. **Copier** le sous-dossier dans `src/` de ton projet
   ```
   optional/ngpc_aabb/  →  src/ngpc_aabb/
   ```

2. **Ajouter** les `.rel` au makefile (pas pour les header-only) :
   ```makefile
   OBJS += src/ngpc_aabb/ngpc_aabb.rel
   OBJS += src/ngpc_tilecol/ngpc_tilecol.rel
   OBJS += src/ngpc_camera/ngpc_camera.rel
   # ngpc_fixed : rien à ajouter (header-only)
   ```

3. **Inclure** dans ton code :
   ```c
   #include "ngpc_fixed/ngpc_fixed.h"   /* header-only, toujours dispo */
   #include "ngpc_aabb/ngpc_aabb.h"
   #include "ngpc_tilecol/ngpc_tilecol.h"
   #include "ngpc_camera/ngpc_camera.h"
   ```

**Dépendances inter-modules :**
- `ngpc_aabb` inclut `ngpc_fixed` (pour le swept test)
- `ngpc_tilecol` inclut `ngpc_aabb` (pour les flags COL_*)
- `ngpc_camera` inclut `ngpc_gfx` (déjà dans le template de base)

Les modules s'appuient sur `ngpc_hw.h` (types u8/s16/etc.) accessible via `-Isrc/core` (déjà dans le makefile du template).

---

## Modules disponibles

### `ngpc_fixed` — Math fixe-point 8.4
**Type :** header-only · **RAM :** 0 octet · **Makefile :** rien à ajouter

Math entière subpixel pour positions et vélocités. Indispensable dès qu'on a de la physique ou du mouvement lisse.

| Élément | Description |
|---|---|
| `fx16` | Type fixe-point s16 (4 bits fractionnels, précision 1/16 px) |
| `FxVec2` | Paire `{ fx16 x, y }` pour position/vélocité 2D |
| `INT_TO_FX(x)` | Entier → fx16 |
| `FX_TO_INT(x)` | fx16 → entier (tronqué) |
| `FX_ROUND(x)` | fx16 → entier (arrondi) |
| `FX_LIT(f)` | Constante flottante compile-time (ex: `FX_LIT(0.25)`) |
| `FX_ADD/SUB/MUL/DIV` | Arithmétique fixe-point |
| `FX_SCALE(i, f)` | Entier × facteur fx16 → entier |
| `FX_LERP(a, b, t)` | Interpolation linéaire |
| `FX_CLAMP/MIN/MAX` | Utilitaires |
| `FX_SIGN(a)` | Signe en fx16 (-FX_ONE, 0, +FX_ONE) |

```c
/* Exemple physique platformer */
#define GRAVITY        FX_LIT(0.25)
#define MAX_FALL       INT_TO_FX(4)
#define JUMP_VEL       FX_LIT(-3.5)

FxVec2 pos = { INT_TO_FX(80), INT_TO_FX(60) };
FxVec2 vel = FXVEC2_ZERO;

/* Chaque frame : */
vel.y = FX_MIN(FX_ADD(vel.y, GRAVITY), MAX_FALL);
pos   = FXVEC2_ADD(pos, vel);
sprite_x = FX_TO_INT(pos.x);
sprite_y = FX_TO_INT(pos.y);
```

---

### `ngpc_aabb` — Collision rectangles
**Type :** .h + .c · **RAM :** 0 octet · **Dépend de :** ngpc_fixed

Collision rectangles axis-aligned. Fonctions pures, zéro état global.

| Fonction | Description |
|---|---|
| `ngpc_rect_overlap(a, b)` | 1 si les deux rects se chevauchent |
| `ngpc_rect_contains(r, px, py)` | 1 si le point est dans le rect |
| `ngpc_rect_test(a, b, *out)` | Overlap + côtés touchés + push MTV |
| `ngpc_rect_test_many(moving, list, n, *rx, *ry, *sides)` | Un mobile vs N statiques |
| `ngpc_swept_aabb(a, vx, vy, b, *out)` | Swept test pour projectiles rapides |
| `ngpc_rect_push_x/y(a, b)` | Pénétration sur un axe uniquement |
| `ngpc_rect_intersect(a, b, *out)` | Rectangle d'intersection |
| `ngpc_rect_offset(r, dx, dy)` | Déplacement du rect |

**Flags COL_\* :** `COL_LEFT`, `COL_RIGHT`, `COL_TOP`, `COL_BOTTOM`, `COL_ANY`

```c
/* Exemple joueur vs liste de plateformes */
NgpcCollResult cr;
if (ngpc_rect_test(&player_rect, &platform_rect, &cr)) {
    player.x += cr.push_x;
    player.y += cr.push_y;
    if (cr.hit & COL_BOTTOM) on_ground = 1;
    if (cr.hit & COL_TOP)    vel_y = 0;
}

/* Exemple balle rapide (swept) */
NgpcSweptResult sr;
ngpc_swept_aabb(&bullet_rect, bullet_vx, bullet_vy, &enemy_rect, &sr);
if (sr.hit) {
    /* sr.t  = moment exact [0..FX_ONE] */
    /* sr.nx / sr.ny = normale de collision */
    enemy_hp--;
}
```

### `ngpc_abl` — Liste AABB avec bitmasks (DAS-5)
**Type :** .h + .c · **RAM :** 324 octets · **Makefile :** `OBJS += src/ngpc_aabb/ngpc_abl.rel` · **Dépend de :** ngpc_aabb

Gère jusqu'à 32 objets nommés par ID (0..31), teste toutes les paires en O(n²) et stocke les résultats comme bitmasks `u32`. Évite les boucles manuelles quand plusieurs catégories d'objets doivent se tester mutuellement.

| Fonction | Description |
|---|---|
| `ngpc_abl_clear()` | Réinitialise tous les slots |
| `ngpc_abl_set(id, x, y, w, h)` | Enregistre / met à jour le rect de l'objet `id` |
| `ngpc_abl_remove(id)` | Retire l'objet de la liste |
| `ngpc_abl_test_all()` | Teste toutes les paires actives — appeler une fois par frame |
| `ngpc_abl_hit(id_a, id_b)` | 1 si `id_a` et `id_b` sont en collision |
| `ngpc_abl_hit_mask(id)` | Bitmask de tous les objets en collision avec `id` |

```c
/* IDs et masques de groupe */
#define ID_PLAYER    0
#define ID_E0        1
#define ID_E1        2
#define ID_E2        3
#define MASK_ENEMIES 0x0Eu  /* bits 1-3 */

/* Chaque frame, avant de tester */
ngpc_abl_set(ID_PLAYER, player.x, player.y, 8, 12);
ngpc_abl_set(ID_E0, e[0].x, e[0].y, 8, 8);
ngpc_abl_set(ID_E1, e[1].x, e[1].y, 8, 8);
ngpc_abl_test_all();

/* Lire les résultats */
if (ngpc_abl_hit_mask(ID_PLAYER) & MASK_ENEMIES) player_hit();
if (ngpc_abl_hit(ID_E0, ID_PLAYER)) enemy_hit(0);
```

> **Note :** Pour les jeux avec ≤ 5 ennemis et 1 joueur, les appels directs à `ngpc_rect_test` restent plus légers. `ngpc_abl` devient utile à partir de ~8 objets ou dès que la logique de groupe se complexifie.

---

### `ngpc_tilecol` — Collision tilemap
**Type :** .h + .c · **RAM :** 0 octet (+ la map de collision du jeu) · **Dépend de :** ngpc_aabb

Collision contre une map typée. **Contient `ngpc_tilecol_move()`, la fonction centrale de tout jeu d'action.**

**Types de tiles :**

| Constante | Valeur | Comportement |
|---|---|---|
| `TILE_PASS` | 0 | Passable, aucune collision |
| `TILE_SOLID` | 1 | Solide sur tous les côtés |
| `TILE_ONE_WAY` | 2 | Plateforme traversable — solide seulement par le haut |
| `TILE_DAMAGE` | 3 | Passable, signalé dans `result.in_damage` |
| `TILE_LADDER` | 4 | Zone d'échelle, signalé dans `result.in_ladder` |
| 5-15 | — | Libres pour usage projet |

**Coût RAM de la map :** `map_w × map_h` octets
- Écran plein : 20×19 = **380 octets**
- Map maximale : 32×32 = **1024 octets** (attention au budget 12 KB)

| Fonction | Description |
|---|---|
| `ngpc_tilecol_move(col, *rx, *ry, w, h, dx, dy, *res)` | **Déplace + résout** la collision, remplit NgpcMoveResult |
| `ngpc_tilecol_on_ground(col, rx, ry, w, h)` | 1 si posé sur un sol (solid ou one-way) |
| `ngpc_tilecol_on_ceiling(col, rx, ry, w, h)` | 1 si tête dans un plafond |
| `ngpc_tilecol_on_wall_left/right(...)` | 1 si contre un mur |
| `ngpc_tilecol_ground_dist(col, rx, ry, w, h, max)` | Distance jusqu'au sol |
| `ngpc_tilecol_rect_solid(col, wx, wy, w, h)` | Test brut zone vs tiles solides |
| `ngpc_tilecol_type_at(col, wx, wy)` | Type du tile à une position pixel |

**`NgpcMoveResult` après `ngpc_tilecol_move()` :**
```c
res.sides     /* COL_* : quels côtés ont heurté */
res.tile_x    /* type du tile bloquant en X */
res.tile_y    /* type du tile bloquant en Y */
res.in_ladder /* 1 si dans une zone TILE_LADDER */
res.in_damage /* 1 si dans une zone TILE_DAMAGE */
```

> **Contrainte :** `|dx|` et `|dy|` ≤ 8 pixels/frame pour éviter le tunnel-through.
> À 60fps, 8px/frame = 480px/s. Largement suffisant pour un jeu NGPC.

```c
/* Exemple platformer complet */
static const u8 s_map[MAP_W * MAP_H] = {
    1,1,1,1,1,1,1,1,
    1,0,0,0,0,0,0,1,
    1,0,0,2,2,0,0,1,   /* 2 = one-way platform */
    1,0,0,0,0,0,0,1,
    1,1,1,1,1,1,1,1,
};
NgpcTileCol col = { s_map, MAP_W, MAP_H };

/* Chaque frame : */
vel.y = FX_MIN(FX_ADD(vel.y, GRAVITY), MAX_FALL);
s16 dx = FX_TO_INT(vel.x);
s16 dy = FX_TO_INT(vel.y);

NgpcMoveResult res;
ngpc_tilecol_move(&col, &px, &py, PW, PH, dx, dy, &res);

if (res.sides & COL_BOTTOM) { on_ground = 1; vel.y = 0; }
if (res.sides & COL_TOP)    { vel.y = 0; }
if (res.sides & (COL_LEFT | COL_RIGHT)) { vel.x = 0; }
if (res.in_damage) { player_hurt(); }
if (res.in_ladder) { can_climb = 1; }
```

---

### `ngpc_camera` — Caméra
**Type :** .h + .c · **RAM :** ~10 octets par caméra · **Dépend de :** ngpc_gfx (template de base)

| Fonction | Description |
|---|---|
| `ngpc_cam_init(cam, level_w, level_h, flags)` | Initialise (CAM_FLAG_CLAMP pour bornes de niveau) |
| `ngpc_cam_follow(cam, tx, ty)` | Centre instantanément sur la cible |
| `ngpc_cam_follow_smooth(cam, tx, ty, speed)` | Suivi progressif (speed 1=lent .. 8=rapide) |
| `ngpc_cam_apply(cam, plane)` | Applique le scroll sur GFX_SCR1 / GFX_SCR2 |
| `ngpc_cam_world_to_screen(cam, wx, wy, *sx, *sy)` | Coords monde → coords écran (pour placer sprites) |
| `ngpc_cam_on_screen(cam, wx, wy, margin)` | 1 si visible (+ marge) — culling basique |

```c
NgpcCamera cam;
ngpc_cam_init(&cam, LEVEL_W * 8, LEVEL_H * 8, CAM_FLAG_CLAMP);

/* Chaque frame : */
ngpc_cam_follow_smooth(&cam, player_x, player_y, 4);
ngpc_cam_apply(&cam, GFX_SCR1);

/* Placer le sprite du joueur en coords écran : */
s16 sx, sy;
ngpc_cam_world_to_screen(&cam, player_x, player_y, &sx, &sy);
ngpc_sprite_move(0, sx, sy);
```

---

## `ngpc_timer` — Timers de jeu
**Type :** .h + .c · **RAM :** 3 octets/timer · **Makefile :** `OBJS += src/ngpc_timer/ngpc_timer.rel`

Countdown, cooldown, tick périodique. One-shot ou répétitif. Appeler `ngpc_timer_update()` une fois par frame.

| Fonction / Macro | Description |
|---|---|
| `ngpc_timer_start(t, frames)` | Démarre un timer one-shot de N frames |
| `ngpc_timer_start_repeat(t, period)` | Démarre un timer répétitif (relance auto) |
| `ngpc_timer_stop(t)` | Stoppe sans réinitialiser |
| `ngpc_timer_restart(t)` | Repart depuis 0 avec la durée mémorisée |
| `ngpc_timer_update(t)` | Met à jour — retourne 1 si expiré ce frame |
| `ngpc_timer_active(t)` | 1 si le timer compte |
| `ngpc_timer_done(t)` | 1 si one-shot expiré (vrai 1 seul frame) |
| `ngpc_timer_remaining(t)` | Frames restantes |

```c
/* Cooldown d'attaque */
NgpcTimer atk_cd;
ngpc_timer_start(&atk_cd, 20);          /* 20 frames de cooldown */

/* Chaque frame : */
ngpc_timer_update(&atk_cd);
if (!ngpc_timer_active(&atk_cd)) { /* peut attaquer */ }

/* Timer répétitif (spawn ennemi toutes les 3 secondes = 180 frames) */
NgpcTimer spawn_t;
ngpc_timer_start_repeat(&spawn_t, 180);
if (ngpc_timer_update(&spawn_t)) { spawn_enemy(); }
```

---

## `ngpc_anim` — Animation de sprites
**Type :** .h + .c · **RAM :** 4 octets/NgpcAnim · **Makefile :** `OBJS += src/ngpc_anim/ngpc_anim.rel`

Séquence de frames avec vitesse configurable. Modes : LOOP, PINGPONG, ONESHOT.
`NgpcAnimDef` est const (en ROM), `NgpcAnim` est l'état courant (en RAM).

| Élément | Description |
|---|---|
| `NgpcAnimDef` | Définition const (frames[], count, speed, flags) |
| `NgpcAnim` | État courant : frame, tick, done |
| `ANIM_DEF(frm, cnt, spd, flg)` | Macro de déclaration en ROM |
| `ANIM_LOOP` / `ANIM_PINGPONG` / `ANIM_ONESHOT` | Modes de lecture |
| `ngpc_anim_play(a, def)` | Lance une animation (no-op si déjà en cours) |
| `ngpc_anim_restart(a)` | Force le redémarrage depuis frame 0 |
| `ngpc_anim_update(a)` | Avance l'anim — retourne 1 si frame changée |
| `ngpc_anim_tile(a)` | Index tile courant (à ajouter à TILE_BASE) |
| `ngpc_anim_done(a)` | 1 si ONESHOT terminé |

```c
static const u8 run_f[] = { 2, 3, 4, 5 };
static const u8 idle_f[] = { 0, 1 };
static const NgpcAnimDef anim_run  = ANIM_DEF(run_f,  4, 4, ANIM_LOOP);
static const NgpcAnimDef anim_idle = ANIM_DEF(idle_f, 2, 8, ANIM_LOOP);

NgpcAnim anim;
ngpc_anim_play(&anim, &anim_idle);

/* Chaque frame : */
ngpc_anim_update(&anim);
ngpc_sprite_set(0, px, py, TILE_BASE + ngpc_anim_tile(&anim), pal, 0);

/* Changer d'animation selon l'état : */
if (moving) ngpc_anim_play(&anim, &anim_run);
else        ngpc_anim_play(&anim, &anim_idle);
```

---

## `ngpc_fsm` — Machine d'états
**Type :** header-only · **RAM :** 3 octets/NgpcFsm · **Makefile :** rien

Suivi des transitions d'état. `ngpc_fsm_entered()` est vrai exactement 1 frame après chaque transition — idéal pour les initialisations d'état.

| Macro | Description |
|---|---|
| `ngpc_fsm_init(f, initial)` | Initialise dans l'état `initial` |
| `ngpc_fsm_goto(f, state)` | Transition vers un nouvel état |
| `ngpc_fsm_entered(f)` | 1 le premier frame d'un état (init) |
| `ngpc_fsm_changed(f)` | 1 si l'état a changé ce frame |
| `ngpc_fsm_tick(f)` | À appeler en FIN de frame (efface les flags) |

```c
#define ST_IDLE 0
#define ST_RUN  1
#define ST_HIT  2

NgpcFsm fsm;
ngpc_fsm_init(&fsm, ST_IDLE);

/* Chaque frame : */
switch (fsm.cur) {
    case ST_IDLE:
        if (ngpc_fsm_entered(&fsm)) { ngpc_anim_play(&anim, &anim_idle); }
        if (ngpc_pad_pressed & PAD_RIGHT) ngpc_fsm_goto(&fsm, ST_RUN);
        break;
    case ST_RUN:
        if (ngpc_fsm_entered(&fsm)) { ngpc_anim_play(&anim, &anim_run); }
        if (!(ngpc_pad_held & PAD_RIGHT)) ngpc_fsm_goto(&fsm, ST_IDLE);
        break;
}
ngpc_fsm_tick(&fsm);   /* toujours en dernier */
```

---

## `ngpc_pool` — Pool d'objets
**Type :** .h + .c · **RAM :** 3 octets/pool + taille des objets · **Makefile :** `OBJS += src/ngpc_pool/ngpc_pool.rel`

Allocation/libération O(1) sans malloc. Bitmask u16 → max 16 slots. Utiliser `NGPC_POOL_DECL` pour créer un pool typé.

| Élément | Description |
|---|---|
| `NgpcPoolHdr` | En-tête : mask, count, capacity |
| `NGPC_POOL_DECL(Name, Type, N)` | Déclare un pool typé de N objets de type Type |
| `NGPC_POOL_INIT(pool_ptr, N)` | Initialise avant utilisation |
| `ngpc_pool_alloc(hdr)` | Alloue un slot — retourne index ou `POOL_NONE` |
| `ngpc_pool_free(hdr, idx)` | Libère le slot idx |
| `ngpc_pool_clear(hdr)` | Vide tout le pool |
| `ngpc_pool_active(hdr, idx)` | 1 si le slot est occupé |
| `ngpc_pool_count(hdr)` | Nombre de slots occupés |
| `POOL_EACH(hdr, i)` | Itère sur les slots actifs uniquement |
| `POOL_NONE` | Index invalide (0xFF) |

```c
typedef struct { s16 x, y; s8 vx, vy; } Bullet;
NGPC_POOL_DECL(BulletPool, Bullet, 8);
static BulletPool bullets;
NGPC_POOL_INIT(&bullets, 8);

/* Spawn : */
u8 idx = ngpc_pool_alloc(&bullets.hdr);
if (idx != POOL_NONE) {
    bullets.items[idx].x = player_x;
    bullets.items[idx].vx = 3;
}

/* Update all active : */
POOL_EACH(&bullets.hdr, i) {
    bullets.items[i].x += bullets.items[i].vx;
    if (out_of_bounds) ngpc_pool_free(&bullets.hdr, i);
}
```

---

## `ngpc_menu` — Menu de sélection
**Type :** .h + .c · **RAM :** 6 octets · **Makefile :** `OBJS += src/ngpc_menu/ngpc_menu.rel`

Navigation D-pad + validation PAD_A. Affichage sur tilemap.
**Dépend de :** `ngpc_input.h` (core) et `ngpc_text.h` (gfx).

| Fonction | Description |
|---|---|
| `ngpc_menu_init(m, items, count, wrap)` | Initialise avec un tableau de chaînes |
| `ngpc_menu_update(m)` | Lit l'input — retourne index si A pressé, `MENU_NONE` sinon |
| `ngpc_menu_draw(m, plane, tx, ty, ch)` | Dessine le menu (cursor_char = '>' par ex.) |
| `ngpc_menu_erase(m, plane, tx, ty, w)` | Efface la zone du menu |
| `m->changed` | 1 si le curseur a bougé ce frame (pour redraw conditionnel) |
| `MENU_NONE` | Valeur retournée si aucune sélection (0xFF) |

```c
static const char *labels[] = { "JOUER", "OPTIONS", "QUITTER" };
static NgpcMenu menu;
ngpc_menu_init(&menu, labels, 3, 1);    /* wrap=1 */
ngpc_menu_draw(&menu, PLANE_SCR1, 7, 6, '>');

/* Chaque frame : */
u8 sel = ngpc_menu_update(&menu);
if (menu.changed) ngpc_menu_draw(&menu, PLANE_SCR1, 7, 6, '>');
if (sel != MENU_NONE) {
    switch (sel) {
        case 0: start_game(); break;
        case 1: open_options(); break;
        case 2: ngpc_shutdown(); break;
    }
}
```

---

## `ngpc_motion` — Buffer d'inputs et détection de patterns
**Type :** .h + .c · **RAM :** 34 octets · **Makefile :** `OBJS += src/ngpc_motion/ngpc_motion.rel`

Buffer circulaire 32 frames + détection de séquences directionnelles fighting-game style (quarter-circle, double-tap, charge…).
Enregistre chaque frame : direction D-pad (nibble haut) + boutons pressés en rising-edge (nibble bas).
La détection est flexible : les frames neutres entre deux steps sont ignorés.

| Élément | Description |
|---|---|
| `NgpcMotionBuf` | Buffer 34 octets RAM par entité (frames + head + count) |
| `NgpcMotionPattern` | Pattern en ROM : `steps[]` + `count` + `window` (frames) |
| `ngpc_motion_init(buf)` | Initialise le buffer |
| `ngpc_motion_push(buf, held, pressed)` | Enregistre le frame courant (appeler 1× par frame) |
| `ngpc_motion_test(buf, pat)` | Retourne 1 si le pattern est détecté |
| `ngpc_motion_scan(buf, pats, count)` | Teste un tableau de patterns, retourne l'index du premier trouvé ou `0xFF` |
| `ngpc_motion_clear(buf)` | Vide le buffer (évite re-trigger après déclenchement) |
| `MDIR_N/U/D/L/R/UR/UL/DR/DL` | Directions (nibble haut) |
| `MDIR_ANY` | Wildcard direction (accepte tout) |
| `MBTN_A/B/OPT` | Boutons (nibble bas, combinables avec `\|`) |
| `NGPC_MOTION_FINAL_WINDOW` | Fenêtre (frames) pour matcher le dernier step (défaut : 4) |

```c
/* Définir les patterns en ROM */
static const u8 _qcf_steps[]   = { MDIR_D, MDIR_DR, MDIR_R | MBTN_A };
static const u8 _dp_steps[]    = { MDIR_R, MDIR_D, MDIR_DR | MBTN_A };
static const u8 _dtap_steps[]  = { MDIR_R, MDIR_N, MDIR_R };

static const NgpcMotionPattern QCF_A  = { _qcf_steps,  3, 20 };
static const NgpcMotionPattern DP_A   = { _dp_steps,   3, 20 };
static const NgpcMotionPattern DTAP_R = { _dtap_steps, 3, 15 };

static NgpcMotionBuf motion_buf;
ngpc_motion_init(&motion_buf);

/* Chaque frame (avant la logique jeu) : */
ngpc_motion_push(&motion_buf, ngpc_pad_held, ngpc_pad_pressed);

if (ngpc_motion_test(&motion_buf, &QCF_A)) {
    ngpc_motion_clear(&motion_buf);
    fire_fireball();
}
if (ngpc_motion_test(&motion_buf, &DP_A)) {
    ngpc_motion_clear(&motion_buf);
    fire_uppercut();
}
```

---

## `ngpc_easing` — Fonctions de lissage
**Type :** header-only · **RAM :** 0 octet · **Makefile :** rien · **Dépend de :** ngpc_fixed

Easing en fixe-point 8.4. Toutes les fonctions prennent `t ∈ [0..FX_ONE]` et retournent `[0..FX_ONE]`.

| Macro | Description |
|---|---|
| `EASE_LINEAR(t)` | Identité |
| `EASE_IN_QUAD(t)` / `EASE_OUT_QUAD(t)` / `EASE_INOUT_QUAD(t)` | Quadratique |
| `EASE_IN_CUBIC(t)` / `EASE_OUT_CUBIC(t)` / `EASE_INOUT_CUBIC(t)` | Cubique |
| `EASE_SMOOTH(t)` | Hermite 3t²-2t³ (dérivée nulle aux extrêmes) |
| `EASE_LERP(a, b, tick, total, fn)` | Interpolation lissée d'un compteur de frames |

```c
/* Déplacer la caméra avec ease-out en 30 frames */
fx16 x = EASE_LERP(INT_TO_FX(0), INT_TO_FX(100), frame, 30, EASE_OUT_QUAD);
```

---

## `ngpc_platform` — Physique platformer
**Type :** .h + .c · **RAM :** 11 octets · **Makefile :** `OBJS += src/ngpc_platform/ngpc_platform.rel` · **Dépend de :** ngpc_fixed

Gravité, saut variable, coyote time (6 frames), jump buffer (8 frames). La collision reste dans le code jeu.

| Élément | Description |
|---|---|
| `ngpc_platform_init(p, x, y)` | Initialise au repos |
| `ngpc_platform_update(p)` | Gravité + intégration pos (avant collision) |
| `ngpc_platform_land(p)` | Appeler quand le sol est détecté — exécute saut bufferisé si présent |
| `ngpc_platform_press_jump(p)` | Pression saut : immédiat ou stocké en buffer |
| `ngpc_platform_release_jump(p)` | Relâchement : variable jump height |
| `ngpc_platform_on_ground(p)` | 1 si posé |
| `ngpc_platform_px/py(p)` | Position pixel |

Constantes `#define`-surchargeables : `PLAT_GRAVITY` `PLAT_MAX_FALL` `PLAT_JUMP_VEL` `PLAT_COYOTE_FRAMES` `PLAT_JUMP_BUF_FRAMES`

```c
NgpcPlatform p;
ngpc_platform_init(&p, INT_TO_FX(80), INT_TO_FX(60));
/* Chaque frame : */
ngpc_platform_update(&p);
resolve_collisions(&p);    /* code jeu : ajuste p.pos.y + appelle ngpc_platform_land() */
if (ngpc_pad_pressed & PAD_A)  ngpc_platform_press_jump(&p);
if (ngpc_pad_released & PAD_A) ngpc_platform_release_jump(&p);
```

---

## `ngpc_actor` — Mouvement top-down
**Type :** .h + .c · **RAM :** 17 octets · **Makefile :** `OBJS += src/ngpc_actor/ngpc_actor.rel` · **Dépend de :** ngpc_fixed

Déplacement 4/8 directions, accélération, vitesse max, friction. Normalisation des diagonales.

| Élément | Description |
|---|---|
| `ngpc_actor_init(a, x, y, speed, accel, friction)` | Initialise |
| `ngpc_actor_move(a, dx, dy)` | Direction ce frame (dx,dy ∈ {-1,0,+1}) — appeler AVANT update |
| `ngpc_actor_update(a)` | Friction si immobile, intègre pos |
| `ngpc_actor_stop(a)` | Stoppe instantanément |
| `a->dir_x` / `a->dir_y` | Dernière direction (pour flip sprite ou animation) |
| `ACTOR_4DIR_H/V(dx,dy)` | Helpers priorité horizontal en mode 4 directions |

```c
NgpcActor hero;
ngpc_actor_init(&hero, INT_TO_FX(80), INT_TO_FX(76),
                ACTOR_DEFAULT_SPEED, ACTOR_DEFAULT_ACCEL, ACTOR_DEFAULT_FRICTION);
/* Chaque frame : */
s8 dx = (ngpc_pad_held & PAD_RIGHT) ? 1 : (ngpc_pad_held & PAD_LEFT) ? -1 : 0;
s8 dy = (ngpc_pad_held & PAD_DOWN)  ? 1 : (ngpc_pad_held & PAD_UP)   ? -1 : 0;
ngpc_actor_move(&hero, dx, dy);
ngpc_actor_update(&hero);
ngpc_sprite_set(0, ngpc_actor_px(&hero), ngpc_actor_py(&hero),
                tile, pal, hero.dir_x < 0 ? SPR_HFLIP : 0);
```

---

## `ngpc_particle` — Pool de particules
**Type :** .h + .c · **RAM :** `PARTICLE_POOL_SIZE × 12` octets (défaut : 192) · **Makefile :** `OBJS += src/ngpc_particle/ngpc_particle.rel` · **Dépend de :** ngpc_fixed

Pool statique avec durée de vie, vélocité et gravité optionnelle. Le rendu est à la charge du jeu.

| Élément | Description |
|---|---|
| `ngpc_particle_emit(pool, x, y, vx, vy, life, tile, pal, flags)` | Émet une particule |
| `ngpc_particle_burst(pool, x, y, count, speed, ...)` | Explose en étoile (8 directions, boucle si count>8) |
| `ngpc_particle_update(pool)` | Physique + décrément life (appeler une fois par frame) |
| `PART_GRAVITY` | Flag : appliquer PARTICLE_GRAVITY à vel.y |
| `ngpc_particle_px/py(p)` | Position pixel entière |

```c
static NgpcParticlePool fx;
ngpc_particle_pool_init(&fx);
/* À l'impact : */
ngpc_particle_burst(&fx, pos_x, pos_y, 8, INT_TO_FX(1), 20, SPARK_TILE, 2, PART_GRAVITY);
/* Chaque frame : */
ngpc_particle_update(&fx);
for (i = 0; i < PARTICLE_POOL_SIZE; i++) {
    NgpcParticle *p = &fx.slots[i];
    if (!p->life) { ngpc_sprite_hide(SPR_FX + i); continue; }
    ngpc_sprite_set(SPR_FX + i, ngpc_particle_px(p), ngpc_particle_py(p),
                    p->tile, p->pal, SPR_FRONT);
}
```

---

## `ngpc_tween` — Interpolation dans le temps
**Type :** .h + .c · **RAM :** 10 octets · **Makefile :** `OBJS += src/ngpc_tween/ngpc_tween.rel` · **Dépend de :** ngpc_easing (→ ngpc_fixed)

Tweene une valeur `fx16` de `from` à `to` en N frames avec easing. Modes : one-shot, loop, pingpong.

| Élément | Description |
|---|---|
| `ngpc_tween_start(tw, from, to, duration, ease, flags)` | Lance le tween |
| `ngpc_tween_update(tw)` | Avance d'un frame — retourne 1 si en cours, 0 si terminé |
| `ngpc_tween_restart(tw)` | Repart depuis from sans changer les paramètres |
| `tw->value` | Valeur interpolée courante (à lire après update) |
| `ngpc_tween_is_done(tw)` | 1 si one-shot terminé |
| `TWEEN_LOOP` / `TWEEN_PINGPONG` | Flags de mode (passer dans flags) |
| `TWEEN_EASE_OUT_QUAD` … `TWEEN_EASE_SMOOTH` | Fonctions d'easing disponibles |

```c
/* Fondu de luminosité 0→8 en 30 frames */
NgpcTween fade;
ngpc_tween_start(&fade, INT_TO_FX(0), INT_TO_FX(8), 30, TWEEN_EASE_OUT_QUAD, 0);
/* Chaque frame : */
ngpc_tween_update(&fade);
ngpc_palfx_set_brightness(0, FX_TO_INT(fade.value));

/* Pulsation infinie avec PINGPONG + EASE_SMOOTH */
NgpcTween pulse;
ngpc_tween_start(&pulse, INT_TO_FX(0), INT_TO_FX(7), 45, TWEEN_EASE_SMOOTH, TWEEN_PINGPONG);
```

---

## `ngpc_bullet` — Pool de projectiles
**Type :** .h + .c · **RAM :** `BULLET_POOL_SIZE × 12` octets (défaut : 192) · **Makefile :** `OBJS += src/ngpc_bullet/ngpc_bullet.rel` · **Dépend de :** ngpc_pool, ngpc_fixed, ngpc_aabb

Pool de projectiles avec déplacement, expiration automatique (TTL + hors écran) et collision rect.

| Élément | Description |
|---|---|
| `NGPC_BULLET_POOL_INIT(pool)` | Initialise le pool |
| `ngpc_bullet_spawn(pool, x, y, vx, vy, w, h, tile, pal, life, flags)` | Spawne un bullet (retourne l'index ou POOL_NONE) |
| `ngpc_bullet_update(pool)` | Déplace + expire bullets (OOB ou TTL) — une fois par frame |
| `ngpc_bullet_hits(pool, idx, target_rect)` | Test de collision bullet vs rect |
| `ngpc_bullet_kill(pool, idx)` | Libère un bullet après collision |
| `ngpc_bullet_px/py(b)` | Position pixel pour ngpc_sprite_set |
| `BULLET_PLAYER` / `BULLET_ENEMY` | Flags pour discriminer les factions |

`life = 0` → le bullet ne s'expire que hors écran.

```c
static NgpcBulletPool bullets;
NGPC_BULLET_POOL_INIT(&bullets);

/* Tir : */
ngpc_bullet_spawn(&bullets, hero.pos.x, hero.pos.y,
                  4, 0, 4, 4, BULLET_TILE, 1, 60, BULLET_PLAYER);

/* Chaque frame : */
ngpc_bullet_update(&bullets);
POOL_EACH(&bullets.hdr, i) {
    NgpcBullet *b = &bullets.items[i];
    /* Rendu : */
    ngpc_sprite_set(SPR_BULLET + i, ngpc_bullet_px(b), ngpc_bullet_py(b),
                    b->tile, b->pal, SPR_FRONT);
    /* Collision ennemi : */
    NgpcRect er = { ex, ey, 16, 16 };
    if ((b->flags & BULLET_PLAYER) && ngpc_bullet_hits(&bullets, i, &er)) {
        enemy_hurt();
        ngpc_bullet_kill(&bullets, i);
    }
}
```

---

---

## `ngpc_kinematic` — Corps physique générique
**Type :** .h + .c · **RAM :** 11 octets · **Makefile :** `OBJS += src/ngpc_kinematic/ngpc_kinematic.rel` · **Dépend de :** ngpc_fixed, ngpc_tilecol

Corps générique avec vélocité fx16, friction multiplicative et rebond. Intègre `ngpc_tilecol_move()` — pour rochers, barils, balles, ennemis à physique simple.

| Élément | Description |
|---|---|
| `ngpc_kinematic_init(k, x, y, friction, bounce)` | Initialise |
| `ngpc_kinematic_apply_gravity(k, gravity, max_fall)` | Ajoute la gravité à vel.y |
| `ngpc_kinematic_move(k, col, w, h)` | Friction → intégration → collision → rebond |
| `ngpc_kinematic_impulse(k, ix, iy)` | Impulsion instantanée |
| `KIN_FRICTION_NONE/LOW/MEDIUM/HIGH` | Presets ×1.0 / ×0.94 / ×0.875 / ×0.75 |
| `KIN_BOUNCE_NONE/SOFT/ELASTIC/PERFECT` | Presets 0 / ×0.5 / ×0.81 / ×1.0 |

```c
NgpcKinematic rock;
ngpc_kinematic_init(&rock, INT_TO_FX(80), INT_TO_FX(10),
                    KIN_FRICTION_MEDIUM, KIN_BOUNCE_ELASTIC);
/* Chaque frame : */
ngpc_kinematic_apply_gravity(&rock, KIN_GRAVITY, KIN_MAX_FALL);
ngpc_kinematic_move(&rock, &col, 8, 8);
ngpc_sprite_set(SPR_ROCK, ngpc_kinematic_px(&rock), ngpc_kinematic_py(&rock),
                ROCK_TILE, 0, 0);
```

---

## `ngpc_hud` — Éléments HUD
**Type :** .h + .c · **RAM :** 9 octets/barre · **Makefile :** `OBJS += src/ngpc_hud/ngpc_hud.rel` · **Dépend de :** ngpc_gfx, ngpc_text, ngpc_sprite (core)

Barre de valeur (HP/énergie), score et compteur de vies précâblés.

| Élément | Description |
|---|---|
| `ngpc_hud_bar_init(bar, plane, tx, ty, len, max, tf, th, te, pal)` | Initialise une barre |
| `ngpc_hud_bar_set(bar, value)` | Change valeur + redessine |
| `ngpc_hud_score_draw(plane, pal, tx, ty, score, digits, zero_pad)` | Affiche un score |
| `ngpc_hud_lives_draw(spr_base, x, y, lives, max, tile, pal, spacing)` | Icônes vies |

`tile_half = 0` → précision simple (1 unité/tile). Sinon double précision (2 unités/tile).

```c
static NgpcHudBar hp;
ngpc_hud_bar_init(&hp, GFX_SCR1, 1, 0, 4, 8,
                  TILE_HP_FULL, TILE_HP_HALF, TILE_HP_EMPTY, 0);
ngpc_hud_bar_set(&hp, player_hp);
ngpc_hud_score_draw(GFX_SCR1, 0, 13, 0, score, 6, 0);
ngpc_hud_lives_draw(SPR_LIVES, 2, 1, lives, 4, LIFE_TILE, 0, 10);
```

---

## `ngpc_dialog` — Boîte de dialogue
**Type :** .h + .c · **RAM :** 14 octets · **Makefile :** `OBJS += src/ngpc_dialog/ngpc_dialog.rel` · **Dépend de :** ngpc_gfx, ngpc_text, ngpc_input (core)

Texte lettre par lettre, indicateur `▶` clignotant, jusqu'à 2 choix D-pad.

| Élément | Description |
|---|---|
| `ngpc_dialog_open(d, plane, bx, by, bw, bh, pal)` | Ouvre et dessine le cadre |
| `ngpc_dialog_set_text(d, text)` | Texte courant (supporte `\n`) |
| `ngpc_dialog_set_choices(d, choices, count)` | Ajoute des choix (max 2) |
| `ngpc_dialog_update(d)` | `DIALOG_RUNNING / DONE / CHOICE_0 / CHOICE_1` |
| `ngpc_dialog_is_open(d)` | 1 si en cours (bloquer gameplay) |
| `DIALOG_TEXT_SPEED` | Frames/lettre (défaut 2, surchargeable) |

```c
static NgpcDialog dlg;
ngpc_dialog_open(&dlg, GFX_SCR1, 0, 16, 20, 3, 0);
ngpc_dialog_set_text(&dlg, "Bonjour !\nAppuie sur A pour continuer.");
/* Chaque frame (si dialogue actif) : */
u8 r = ngpc_dialog_update(&dlg);
if (r == DIALOG_DONE) game_resume();
```

---

## `ngpc_entity` — Système d'entités
**Type :** .h + .c · **RAM :** `ENTITY_COUNT × (8 + ENTITY_DATA_SIZE)` octets · **Makefile :** `OBJS += src/ngpc_entity/ngpc_entity.rel` · **Dépend de :** rien

Tableau statique avec flag active/inactive. Dispatch par `switch(type)` dans `entity_update()` / `entity_draw()` fournies par le jeu — pas de pointeurs de fonction.

| Élément | Description |
|---|---|
| `ENTITY_COUNT` | Taille du pool (défaut 8) |
| `ENTITY_DATA_SIZE` | Octets de données jeu par entité (défaut 8) |
| `ngpc_entity_spawn(type, x, y)` | Alloue un slot (retourne pointeur ou NULL) |
| `ngpc_entity_kill(e)` | Macro — désactive |
| `ngpc_entity_update_all()` | Appelle `entity_update(e)` sur chaque active |
| `ngpc_entity_draw_all()` | Appelle `entity_draw(e)` sur chaque active |
| `ngpc_entity_find(type)` | Premier slot actif de ce type |

Le jeu **doit** implémenter `void entity_update(NgpcEntity *e)` et `void entity_draw(const NgpcEntity *e)`.

```c
void entity_update(NgpcEntity *e) {
    switch (e->type) {
        case ENT_SLIME: slime_update(e); break;
        case ENT_COIN:  if (--e->timer == 0) ngpc_entity_kill(e); break;
    }
}
/* Init niveau : */
ngpc_entity_init_all();
NgpcEntity *s = ngpc_entity_spawn(ENT_SLIME, 64, 40);
s->data[0] = 3;  /* HP */
/* Chaque frame : */
ngpc_entity_update_all();
ngpc_entity_draw_all();
```

---

## `ngpc_room` — Transitions entre rooms
**Type :** .h + .c · **RAM :** 4 octets · **Makefile :** `OBJS += src/ngpc_room/ngpc_room.rel` · **Dépend de :** rien

Timer qui séquence fade-out → chargement → fade-in. Gère uniquement le timing ; l'effet visuel est à la charge du jeu (ngpc_palfx recommandé).

| Élément | Description |
|---|---|
| `ngpc_room_init(r, phase_frames)` | Initialise (ex: 30 frames/phase) |
| `ngpc_room_go(r, next_room)` | Démarre la transition |
| `ngpc_room_loaded(r)` | Signale que le chargement est terminé → fade-in |
| `ngpc_room_update(r)` | `ROOM_IDLE / FADE_OUT / LOAD / FADE_IN / DONE` |
| `ngpc_room_in_transition(r)` | 1 si en cours |
| `ngpc_room_progress(r)` | Progression [0..255] de la phase courante |

```c
static NgpcRoom room;
ngpc_room_init(&room, 30);
/* Déclencher : */
ngpc_palfx_fade_to_black(GFX_SCR1, 0, 2);
ngpc_room_go(&room, ROOM_CAVE);
/* Chaque frame : */
u8 r = ngpc_room_update(&room);
if (r == ROOM_LOAD) {
    load_level(room.next_room);
    ngpc_gfx_set_palette(GFX_SCR1, 0, 0, 0, 0, 0);
    ngpc_palfx_fade(GFX_SCR1, 0, level_pal, 2);
    ngpc_room_loaded(&room);
}
if (r == ROOM_DONE) gameplay_active = 1;
```

---

## `ngpc_grid` — Logique grille puzzle
**Type :** header-only · **RAM :** 0 (+ buffer jeu) · **Makefile :** rien · **Dépend de :** rien

Grille `u8[]` fournie par le jeu. Accès, conversion coords pixel↔tile, utilitaires match-3/Sokoban.

| Élément | Description |
|---|---|
| `ngpc_grid_init(g, cells, w, h)` | Associe un buffer |
| `ngpc_grid_get/set(g, tx, ty)` | Lecture/écriture |
| `ngpc_grid_at(g, tx, ty)` | Pointeur cellule (NULL si hors bornes) |
| `ngpc_grid_swap(g, ax, ay, bx, by)` | Échange deux cellules |
| `ngpc_grid_to_screen(g, tx, ty, ox, oy, cw, ch, *sx, *sy)` | Tile → pixel |
| `ngpc_grid_from_screen(g, px, py, ox, oy, cw, ch, *tx, *ty)` | Pixel → tile |
| `ngpc_grid_count_h/v(g, tx, ty, value)` | Cellules consécutives H/V |
| `ngpc_grid_find(g, value, *tx, *ty)` | Première cellule d'une valeur |

```c
static u8 cells[8 * 8];
static NgpcGrid grid;
ngpc_grid_init(&grid, cells, 8, 8);
ngpc_grid_fill(&grid, CELL_EMPTY);
/* Match-3 : */
if (ngpc_grid_count_h(&grid, x, y, CELL_RED) >= 3) clear_h(&grid, x, y);
/* Sokoban : */
u8 *dst = ngpc_grid_at(&grid, px + dx, py + dy);
if (dst && *dst == CELL_EMPTY) { *dst = CELL_PLAYER; ngpc_grid_set(&grid, px, py, CELL_EMPTY); }
```

---

## `ngpc_path` — Pathfinding BFS
**Type :** .h + .c · **RAM :** 320 octets statiques internes · **Makefile :** `OBJS += src/ngpc_path/ngpc_path.rel` · **Dépend de :** rien

BFS flood-fill inverse (depuis la cible) sur grille max 16×16. Retourne le premier pas ou la distance totale. Map compatible `NgpcTileCol` (0 = passable).

| Élément | Description |
|---|---|
| `ngpc_path_step(map, w, h, sx, sy, tx, ty, *dx, *dy)` | Premier pas vers la cible (retourne 1 si chemin trouvé) |
| `ngpc_path_dist(map, w, h, sx, sy, tx, ty)` | Distance (PATH_NO_PATH = 0xFF si inaccessible) |

```c
/* Ennemi suit le joueur : */
s8 dx, dy;
if (ngpc_path_step(col.map, MAP_W, MAP_H,
                   enemy_tx, enemy_ty, player_tx, player_ty, &dx, &dy)) {
    enemy_tx += dx; enemy_ty += dy;
}
/* IA conditionnelle : */
u8 d = ngpc_path_dist(col.map, MAP_W, MAP_H, etx, ety, ptx, pty);
if (d <= 2) attack(); else if (d != PATH_NO_PATH) chase(); else wander();
```

---

## `ngpc_soam` — Shadow OAM double-buffer
**Type :** .h + .c · **RAM :** 320 octets (shadow_oam[256] + shadow_col[64]) · **Makefile :** `OBJS += src/ngpc_soam/ngpc_soam.rel`

Mise à jour des sprites **sans déchirure** : on construit l'état complet en RAM pendant la logique jeu, puis on pousse en une seule rafale vers le hardware dans le VBlank.

**Différence avec `ngpc_sprmux` :**
- `ngpc_sprmux` = multiplexage HBlank réel, supporte >64 sprites simultanés
- `ngpc_soam` = double-buffer propre, max 64 sprites, zéro overhead ISR

| Fonction | Description |
|---|---|
| `ngpc_soam_begin()` | Début de frame : remet à zéro le compteur de slots |
| `ngpc_soam_put(slot, x, y, tile, flags, pal)` | Écrit un sprite dans le shadow OAM |
| `ngpc_soam_hide(slot)` | Cache un slot sans avancer le compteur |
| `ngpc_soam_flush()` | Pousse le shadow vers hardware — **appeler dans le VBlank** |
| `ngpc_soam_hide_all()` | Cache les 64 slots hardware immédiatement |
| `ngpc_soam_used()` | Retourne le high-water-mark (nb slots écrits ce frame) |

**`flags`** : `SPR_FRONT` / `SPR_MIDDLE` / `SPR_BEHIND` / `SPR_HIDE` + `SPR_HFLIP` / `SPR_VFLIP`

> **Tail-clear automatique :** si tu utilises 5 slots un frame et 3 le suivant, `flush()` cache automatiquement les slots 3 et 4. Pas besoin de les cacher manuellement.

```c
/* Chaque frame — logique jeu : */
ngpc_soam_begin();
for (i = 0; i < enemy_count; i++) {
    ngpc_soam_put(i, enemy[i].x, enemy[i].y,
                  TILE_BASE + enemy[i].tile, SPR_FRONT, enemy[i].pal);
}

/* Dans le VBlank handler : */
ngpc_soam_flush();
```

**Remplacement drop-in de `ngpc_sprite_set()` pour 64 sprites max :**
```c
/* Avant (writes HW direct, risque de tearing) : */
ngpc_sprite_set(0, px, py, TILE_BASE, 0, SPR_FRONT);

/* Après (buffered, tear-free) : */
ngpc_soam_begin();
ngpc_soam_put(0, px, py, TILE_BASE, SPR_FRONT, 0);
/* dans VBlank : ngpc_soam_flush(); */
```

---

## `ngpc_raster_chain` — Raster splits CPU (sans MicroDMA)
**Type :** .h + .c · **RAM :** ~20 octets (pointeurs + index) · **Makefile :** `OBJS += src/ngpc_raster_chain/ngpc_raster_chain.rel`

Effets de split-screen par palier : on tire la logique de Sonic NGPC §2.2-2.3 — Timer0 avec reprogrammation dynamique de `TREG0`. Chaque split ne coûte qu'un IRQ timer sur la ligne exacte, pas une ISR HBlank complète.

**Avantages vs `ngpc_dma_raster` (MicroDMA) :**
- Le VBlank s'exécute toujours normalement → watchdog toujours nourri → aucun risque de coupure
- Fonctionne sans MicroDMA validé
- Moins de RAM : pas de table de 152 entrées

**Limitation :** max `RCHAIN_MAX_SPLITS` (8) splits par frame, précision ±1 scanline.

> **Conflit ressource :** partage Timer0 avec `ngpc_raster`, `ngpc_dma_raster`, `ngpc_sprmux`. N'utiliser qu'**un seul** à la fois.

| Élément | Description |
|---|---|
| `RChainSplit` | `{ u8 line, scr1x, scr1y, scr2x, scr2y }` — un point de rupture |
| `ngpc_rchain_init()` | Initialise (Timer0 non démarré) |
| `ngpc_rchain_arm(splits, count)` | Arme pour la frame suivante — **appeler dans VBlank** |
| `ngpc_rchain_disarm()` | Stoppe Timer0, retour au scroll uniforme |
| `RCHAIN_MAX_SPLITS` | Nombre max de splits (défaut : 8) |

```c
/* Parallax 3 zones : HUD fixe en bas, plan lointain 2×, plan proche 1× */
static const RChainSplit splits[] = {
    /*  line  scr1x scr1y  scr2x scr2y */
    {    0,   0,    0,     0,    0    },  /* ligne 0  : baseline */
    {   80,   cam_x/2, 0, cam_x, 0   },  /* ligne 80 : parallax */
    {  128,   0,    0,     0,    0    },  /* ligne 128: HUD fixe */
};

/* Dans VBlank : */
ngpc_rchain_arm(splits, 3);
```

```c
/* Shmup : vagues ennemies sur fond différent selon la zone */
static RChainSplit raster[2];

void vblank_handler(void)
{
    raster[0].line  = 0;
    raster[0].scr1x = bg_x;    /* background rapide */
    raster[1].line  = 100;
    raster[1].scr1x = bg_x/3;  /* lente au bas (espace lointain) */
    ngpc_rchain_arm(raster, 2);
}
```

---

## `ngpc_winani` — Animation fenêtre (transition scène)
**Type :** .h + .c · **RAM :** 4 octets · **Makefile :** `OBJS += src/ngpc_winani/ngpc_winani.rel`

Ouverture/fermeture centrée de la fenêtre K2GE (`HW_WIN_X/Y/W/H`), pattern Pocket Tennis §4 : expansion du centre vers les bords, ou contraction vers le centre.

> **Ambiguïté hardware :** Pocket Tennis utilise 160/152 pour plein écran, Sonic utilise 159/151. Ce module utilise les valeurs Pocket Tennis. Si décalage 1px sur ton hardware, `#define WINANI_SIZE_MINUS1`.

| Fonction | Description |
|---|---|
| `ngpc_win_init()` | Initialise en plein écran (sans animation) |
| `ngpc_win_set_full()` | Plein écran instantané (pas d'animation) |
| `ngpc_win_set_closed()` | Fermeture instantanée (rien de visible) |
| `ngpc_win_open(speed)` | Démarre l'ouverture — speed = pixels/frame par côté (1–40) |
| `ngpc_win_close(speed)` | Démarre la fermeture — même convention |
| `ngpc_win_update()` | Met à jour et écrit les registres — **appeler dans VBlank** — retourne 1 quand terminé |
| `ngpc_win_busy()` | 1 si animation en cours |

```c
/* Scénario typique : fermer → charger → ouvrir */

/* À la fin de la scène courante : */
ngpc_win_close(4);      /* 4px/côté/frame = ~20 frames pour fermer */

/* Dans VBlank : */
if (ngpc_win_update()) {
    /* Animation terminée */
    if (win_closing) {
        load_next_scene();
        ngpc_win_open(4);
        win_closing = 0;
    }
}
```

```c
/* Intro jeu : fenêtre fermée, puis ouverture lente au démarrage */
void scene_intro_init(void)
{
    ngpc_win_set_closed();    /* rien visible au départ */
    ngpc_win_open(2);         /* ouverture douce, 2px/côté */
}

/* Dans VBlank de la scène intro : */
ngpc_win_update();
```

---

## `ngpc_tileblitter` — Blitter tilemap W×H
**Type :** .h + .c · **RAM :** 0 octet · **Makefile :** `OBJS += src/ngpc_tileblitter/ngpc_tileblitter.rel`

Copie un rectangle W×H de tilewords depuis la ROM vers n'importe quelle position (x,y) d'un scroll plane — avec wrap-safe automatique. Supporte le miroir horizontal.

**Différence avec `NGP_TILEMAP_BLIT_SCR1` (macro) :** la macro blitte un écran plein (20×19) depuis (0,0). `ngpc_tblit()` blitte **n'importe quelle région** vers **n'importe quelle position** — idéal pour les mises à jour partielles (HUD, salle scrollante, bloc de tuiles animé).

| Fonction | Description |
|---|---|
| `ngpc_tblit(plane, x, y, w, h, src)` | Blitte W×H tilewords en (x,y) |
| `ngpc_tblit_hflip(plane, x, y, w, h, src)` | Idem, miroir horizontal |

- `src` doit être déclaré `NGP_FAR` si les données sont en ROM (ce qui est presque toujours le cas)
- `src` est en ordre ligne par ligne (row-major), left-to-right
- Pour `hflip` : `src` reste en ordre normal, le miroir est appliqué pendant le blit

**Format tileword (u16) — identique au format K2GE :**
```
bit 15 = H.flip  |  bit 14 = V.flip  |  bits 12:9 = palette  |  bit 8 = tile index bit 8  |  bits 7:0 = tile index
```

```c
/* Dessiner un bloc de décor 4×3 à la position (10, 5) */
extern const u16 NGP_FAR rock_block_tiles[12];  /* 4*3 = 12 tilewords en ROM */

ngpc_tblit(GFX_SCR1, 10, 5, 4, 3, rock_block_tiles);

/* Version miroir (porte du côté droit par ex.) */
ngpc_tblit_hflip(GFX_SCR1, 16, 5, 4, 3, rock_block_tiles);
```

```c
/* HUD : redessiner seulement la zone de score (5 tiles de large, 1 de haut) */
extern const u16 NGP_FAR hud_score_tiles[5];

ngpc_tblit(GFX_SCR1, 0, 0, 5, 1, hud_score_tiles);
```

```c
/* Tile animé : alterner deux frames d'animation sur un bloc 2×2 */
static u8 anim_tick = 0;
static const u16 NGP_FAR anim_frame_a[4] = { ... };
static const u16 NGP_FAR anim_frame_b[4] = { ... };

anim_tick++;
ngpc_tblit(GFX_SCR1, door_x, door_y, 2, 2,
           (anim_tick & 0x10) ? anim_frame_b : anim_frame_a);
```

> **Note sur les assets :** `ngpc_tilemap.py` génère `map_tiles[]` qui contient les indices dans le set. Pour créer un array `NGP_FAR` utilisable par `ngpc_tblit`, il faut soit utiliser les tilewords complets depuis `map_tiles[]`, soit construire manuellement les u16 avec `tile | (pal << 9)`.

---

## `ngpc_mapstream` — Streaming tilemap (cartes > 32×32)
**Type :** .h + .c · **RAM :** 11 octets/NgpcMapStream · **Makefile :** `OBJS += src/ngpc_mapstream/ngpc_mapstream.rel`

Streaming de tilemap pour les cartes dont les dimensions dépassent la VRAM hardware (32×32 tiles = 256×256 px).
Écrit les nouvelles colonnes / lignes dans la VRAM toroïdale au fur et à mesure du déplacement de la caméra.

**Principe :** la VRAM wrap toroïdalement ; le tile monde (wx, wy) est stocké en VRAM à (wx%32, wy%32).
Quand la caméra avance d'une case, la colonne/ligne qui entre dans le viewport est écrite dans le slot VRAM libéré.

**Limite index :** carte jusqu'à 256×256 tiles (index u16 max 65535). Au-delà, contacter le support.

**Budget VBlank :** 1 colonne ≈ 21 writes = 42 octets VRAM. Confortable jusqu'à 10 tiles/frame de scroll.

**Statut hardware :** valide sur hardware reel dans `platformmer_test_2` pour le streaming d'une grande map.

| Fonction | Description |
|---|---|
| `ngpc_mapstream_init(ms, plane, map_tiles, w, h, cam_px, cam_py)` | Init + blit initial viewport (appel hors VBlank) |
| `ngpc_mapstream_update(ms, cam_px, cam_py)` | Streame les colonnes/lignes nouvelles (appel après vsync) |

- `map_tiles` : array ROM row-major `map_w × map_h` de tilewords u16 (indices **absolus** — tile base déjà inclus)
- Appeler `ngpc_mapstream_init()` à nouveau si la caméra teleporte de plus de `NGPC_MAPSTREAM_MAX_DELTA` tiles

```c
/* Scene init : */
NgpcMapStream g_ms;
ngpc_mapstream_init(&g_ms, GFX_SCR1,
                    g_level1_bg_map, 128u, 32u,
                    cam_px, cam_py);

/* Main loop, APRÈS ngpc_vsync() et avant draw : */
ngpc_mapstream_update(&g_ms, cam_px, cam_py);
/* Puis appliquer le scroll hardware normalement : */
ngpc_cam_apply(&cam, GFX_SCR1);
```

**Combo recommandé :** `ngpc_mapstream` + `ngpc_camera` + `ngpc_tilecol` pour un platformer avec grand niveau.

---

---

## `ngpc_rng` — PRNG déterministe (xorshift32)
**Type :** .h + .c · **RAM :** 4 octets/instance · **Makefile :** `OBJS += src/ngpc_rng/ngpc_rng.rel`

PRNG avec état explicite par instance. Contrairement à `ngpc_random()` (état global, non reproductible), `NgpcRng` permet de générer le même donjon depuis le même seed, et d'avoir plusieurs générateurs indépendants simultanés.

| Élément | Description |
|---|---|
| `NgpcRng` | Struct d'état (4 octets : `u32 state`) |
| `ngpc_rng_init(rng, seed)` | Seed fixe → séquence reproductible |
| `ngpc_rng_init_vbl(rng)` | Seed depuis le timer hardware → aléatoire |
| `ngpc_rng_next(rng)` | u16 dans [0..65535] |
| `ngpc_rng_u8(rng)` | u8 dans [0..255] |
| `ngpc_rng_range(rng, min, max)` | u8 dans [min..max] inclus |
| `ngpc_rng_chance(rng, pct)` | 1 avec pct% de probabilité |
| `ngpc_rng_signed(rng, range)` | s8 dans [-range..+range] |
| `ngpc_rng_shuffle(rng, arr, n)` | Fisher-Yates sur tableau u8[] |
| `ngpc_rng_pick_mask(rng, mask)` | Index d'un bit actif aléatoire dans un masque u16 |

```c
NgpcRng rng;
ngpc_rng_init(&rng, 0x4A2B);      /* reproductible */
u8 roll   = ngpc_rng_range(&rng, 1, 6);
u8 crit   = ngpc_rng_chance(&rng, 25);
s8 jitter = ngpc_rng_signed(&rng, 3);
```

---

## `ngpc_procgen` — Générateur de donjons procéduraux (Dicing Knight style) ✅ Validé
**Type :** .h + .c · **RAM :** 136 octets (ProcgenMap + ProcgenContent×16) · **Makefile :** `OBJS += src/ngpc_rng/ngpc_rng.rel src/ngpc_procgen/ngpc_procgen.rel` · **Dépend de :** ngpc_rng

Génère une carte de rooms reliées par des portes sur une grille 4×4 (configurable).
Chaque room = un écran NGPC complet (20×19 tiles). DFS + injection de boucles optionnelle + contenu procédural.
**Voir [ngpc_procgen/README.md](ngpc_procgen/README.md) pour la documentation complète.**

> **Patron alternatif — shooter / shmup :** Pour un niveau infini procédural dans un genre sans rooms (shoot'em up, runner…), il n'est pas nécessaire d'utiliser le module complet. Un **director de spawn** piloté par `ngpc_qrandom()` (disponible dans le core, `ngpc_math.c`) suffit : timer de vague, table de difficulté par tier, RNG pour type/count/position. Voir `Shmup_StarGunner/src/game/shmup.c` → `shmup_inf_update()` pour un exemple complet validé en production (2026-03-15).

| Élément | Description |
|---|---|
| `ProcgenMap` | Carte du donjon (cells[], start_idx, exit_idx, room_count, seed…) |
| `ProcgenCell` | 4 octets : template_id, exits, room_type, flags |
| `ProcgenContent` | 4 octets : enemies (bitmask), items (bitmask), count, special |
| `NgpcRoomTemplate` | 2 octets : exits_mask, variant (ROM-safe, sans pointeurs) |
| `ngpc_procgen_generate_ex(map, tpl, n, seed, loop_pct)` | **Recommandé** — DFS + boucles (`loop_pct=20`) + templates |
| `ngpc_procgen_generate(map, tpl, n, seed)` | Compatibilité — sans boucles (= `_ex` avec `loop_pct=0`) |
| `ngpc_procgen_gen_content(map, content[], max_en, item_pct)` | Contenu procédural par room (ennemis, items, boss…) |
| `ngpc_procgen_load_room(map, idx, tpl, fn, entry_dir, ud)` | Charge une room + callback de rendu |
| `ngpc_procgen_neighbor(map, idx, dir)` | Index du voisin ou `PROCGEN_IDX_NONE` (0xFF) |
| `ngpc_procgen_spawn_pos(entry_dir, *x, *y)` | Position de spawn selon la direction d'entrée |
| `ngpc_procgen_room_seed(map, idx)` | Seed 16-bit reproductible par room (pour entités) |
| `g_procgen_rooms[48]` | Pool 48 templates (3 variantes × 16 configs) via `ngpc_procgen_rooms.h` |
| `ngpc_procgen_fill_room(cell, tpl, wall, floor, deco, pal)` | Rendu room prototype (plain/pilliers/divisé) |
| `ngpc_procgen_fill_simple(cell, wall, floor, pal)` | Rendu minimal sans variante (rétrocompatibilité) |

**`loop_pct` :** 0 = labyrinthe parfait · **20 = recommandé** · 35 = très ouvert

**Types de rooms :** `PROCGEN_ROOM_START/NORMAL/EXIT/SHOP/SECRET`
**Flags runtime :** `PROCGEN_FLAG_VISITED/CLEARED/LOCKED`

```c
ProcgenMap donjon;
ProcgenContent content[PROCGEN_MAX_ROOMS];

/* Génération avec 20% de boucles */
ngpc_procgen_generate_ex(&donjon, g_procgen_rooms, PROCGEN_ROOMS_COUNT,
                         seed, 20u);

/* Contenu procédural : 3 ennemis max, 40% chance d'item */
ngpc_procgen_gen_content(&donjon, content, 3u, 40u);

/* Callback de rendu — appelé à chaque changement de room */
void room_cb(const ProcgenCell *cell, const NgpcRoomTemplate NGP_FAR *tpl,
             u8 entry_dir, void *ud)
{
    u8 idx = donjon.current_idx;
    ngpc_procgen_fill_room(cell, tpl, TILE_WALL, TILE_FLOOR, TILE_PILLAR, 0u);
    if (!(cell->flags & PROCGEN_FLAG_VISITED))
        spawn_enemies(content[idx].count, content[idx].enemies);
    (void)entry_dir; (void)ud;
}

/* Charger la room de départ : */
ngpc_procgen_load_room(&donjon, donjon.start_idx, g_procgen_rooms,
                       room_cb, 0xFFu, NULL);

/* Transition vers l'Est : */
u8 next = ngpc_procgen_neighbor(&donjon, donjon.current_idx, PROCGEN_DIR_E);
if (next != PROCGEN_IDX_NONE)
    ngpc_procgen_load_room(&donjon, next, g_procgen_rooms, room_cb,
                           PROCGEN_DIR_E, NULL);
```

---

## `ngpc_cavegen` — Générateur de caves procédurales (Cave Noir style) ✅ Validé
**Type :** .h + .c · **RAM :** 1412 octets (NgpcCaveMap 1032 + viewport 380) · **Makefile :** `OBJS += src/ngpc_rng/ngpc_rng.rel src/ngpc_cavegen/ngpc_cavegen.rel` · **Dépend de :** ngpc_rng

Cave **32×32 tiles** générée par automate cellulaire. Scrolling 20×19 (un écran NGPC).
Toute la map est calculée en début de partie, le joueur s'y déplace librement.
**Voir [ngpc_cavegen/README.md](ngpc_cavegen/README.md) pour la documentation complète.**

**Algorithme en 4 passes :**
1. Remplissage aléatoire (`wall_pct`% de murs)
2. Lissage × 5 — règle Moore 5/4 (in-place)
3. Flood-fill — suppression des îlots isolés
4. Placement — entrée (gauche), sortie (droite), ennemis/coffres par sections 8×8

| Élément | Description |
|---|---|
| `NgpcCaveMap` | 1032 octets : `map[32×32]` + positions entrée/sortie + compteurs |
| `CAVE_WALL/FLOOR/ENTRY/EXIT/CHEST/ENEMY` | Types de tiles (0..5) |
| `CAVEGEN_W / CAVEGEN_H` | 32 tiles (= limite tilemap hardware NGPC) |
| `ngpc_cavegen_generate(out, seed, wall_pct, max_en, max_ch)` | Génère la cave complète |
| `ngpc_cavegen_viewport(m, cam_x, cam_y, out[380])` | Extrait une fenêtre 20×19 |
| `ngpc_cavegen_cam_center(px, py, *cam_x, *cam_y)` | Caméra centrée + clampée |

**`wall_pct` :** 40 = très ouverte · **47 = recommandé** · 52 = étroite / couloirs

```c
/* Correspondance CAVE_* → tile NGPC */
static const u16 s_tiles[6] = {
    TILE_WALL, TILE_FLOOR, TILE_FLOOR, TILE_EXIT, TILE_CHEST, TILE_ENEMY
};

NgpcCaveMap cave;
u8 view[20 * 19];
u8 cam_x, cam_y;

/* Init : */
ngpc_cavegen_generate(&cave, seed, 47u, 8u, 3u);
cam_x = cave.entry_x; cam_y = cave.entry_y;
ngpc_cavegen_viewport(&cave, cam_x, cam_y, view);

/* Update (chaque frame) : */
void cave_update(void) {
    u8 new_px = px, new_py = py;
    /* déplacer new_px/new_py selon pad... */
    u8 tile = cave.map[(u16)new_py * CAVEGEN_W + new_px];
    if (tile == CAVE_WALL) { new_px = px; new_py = py; } /* collision */
    if (tile == CAVE_EXIT) { /* niveau suivant */ }
    px = new_px; py = new_py;
    /* Scrolling : re-extraire seulement si la cam a bougé */
    u8 new_cx, new_cy;
    ngpc_cavegen_cam_center(px, py, &new_cx, &new_cy);
    if (new_cx != cam_x || new_cy != cam_y) {
        cam_x = new_cx; cam_y = new_cy;
        ngpc_cavegen_viewport(&cave, cam_x, cam_y, view);
        /* → réécrire view[i] en VRAM */
    }
}
```

---

---

## `ngpc_seq` — Séquenceur PSG minimal
**Type :** .h + .c · **RAM :** 12 octets (4 slots NgpcSeqState) · **Makefile :** `OBJS += src/ngpc_seq/ngpc_seq.rel` · **Dépend de :** `sounds.h` (core)

Joue des tables de notes sur les 4 canaux T6W28 PSG **sans tracker ni Sound Creator**.
Utile pour les jingles de menu, fanfares, sons de gameplay simples, ou projets NGPCraft
qui n'utilisent pas le driver Sound Creator complet.

**Format de séquence :**
```c
typedef struct { u8 note; u8 attn; u8 dur; } NgpcSeqNote;
/* note : 0=silence, 1..50=hauteur (index NOTE_TABLE), canal 3 : 1..7=rate bruit */
/* attn : 0=fort, 15=muet                                                         */
/* dur  : frames VBL ; 0=fin, 0xFF=boucle depuis le début                         */
#define NGPC_SEQ_END  { 0u, 15u, 0u   }
#define NGPC_SEQ_LOOP { 0u, 15u, 0xFFu }
```

| Fonction | Description |
|---|---|
| `ngpc_seq_play(ch, seq)` | Démarre la séquence sur le canal ch (0-2=tone, 3=bruit), joue la 1re note immédiatement |
| `ngpc_seq_update()` | À appeler **une fois par VBL** (après `Sound_Update()`), avance les compteurs |
| `ngpc_seq_stop(ch)` | Coupe le canal et silence |
| `ngpc_seq_stop_all()` | Coupe les 4 canaux |
| `ngpc_seq_is_done(ch)` | 1 quand la séquence non-bouclée est terminée |

```c
/* Définir la séquence (tableaux en ROM) */
static const NgpcSeqNote s_jingle[] = {
    { 30, 0,  8 },   /* note 30 (do aigu), fort, 8 frames */
    { 34, 0,  8 },   /* note 34 (mi) */
    { 37, 0, 16 },   /* note 37 (sol), tenu 16 frames */
    {  0, 15, 4 },   /* silence 4 frames */
    { 37, 0, 24 },   /* sol final */
    NGPC_SEQ_END
};

static const NgpcSeqNote s_bass_loop[] = {
    { 10, 3, 12 },
    { 14, 3, 12 },
    NGPC_SEQ_LOOP    /* revient à la note 10 indéfiniment */
};

/* Démarrage */
ngpc_seq_play(0, s_jingle);    /* mélodie sur canal 0 */
ngpc_seq_play(1, s_bass_loop); /* basse sur canal 1 */

/* Dans la boucle principale, après Sound_Update() : */
ngpc_seq_update();

/* Arrêt propre */
if (ngpc_seq_is_done(0)) ngpc_seq_stop(1);
```

> **Intégration :** `ngpc_seq` appelle `Sfx_PlayToneCh` / `Sfx_PlayNoise` de `sounds.c`
> et utilise `NOTE_TABLE` (50 fréquences, défini dans tes données sonores).
> `Sound_Update()` doit être appelé chaque VBL pour pousser les commandes vers le Z80.
> Pour les jeux utilisant Sound Creator BGM, `ngpc_seq` joue sur les canaux SFX
> (les mêmes que `Sfx_PlayToneCh`) — il peut coexister si les canaux ne se chevauchent pas.

---

---

### `ngpc_transition` — Transitions d'écran
**Type :** .h + .c · **RAM :** 6 octets · **Dépend de :** ngpc_room · ngpc_palfx (core)

Enchaîne un fondu-sortie, un instant de chargement et un fondu-entrée.
Trois types : `TRANS_FADE` (noir), `TRANS_FLASH` (éclair blanc), `TRANS_INSTANT` (sans effet).

| Fonction | Description |
|---|---|
| `ngpc_transition_init(tr, phase_frames)` | Initialise, `phase_frames` = durée de chaque phase (16–30 recommandé) |
| `ngpc_transition_start(tr, type)` | Déclenche OUT + effet palfx |
| `ngpc_transition_update(tr)` | Avance l'état, retourne `TRANS_IDLE/OUT/LOAD/IN/DONE` |
| `ngpc_transition_loaded(tr)` | Signale fin du chargement → passe en phase IN |
| `ngpc_transition_active(tr)` | Macro : 1 si OUT/LOAD/IN (bloquer gameplay) |
| `ngpc_transition_progress(tr)` | Macro : progression [0..255] de la phase courante |

```c
static NgpcTransition tr;
ngpc_transition_init(&tr, 20);     /* 20 frames par phase */

/* Déclencher : */
ngpc_transition_start(&tr, TRANS_FADE);

/* Chaque frame : */
u8 r = ngpc_transition_update(&tr);
if (r == TRANS_LOAD) {
    load_scene(next_scene_id);     /* charger tuiles + palettes */
    ngpc_transition_loaded(&tr);
    /* Pour TRANS_FADE : déclencher le fade-in ici */
    ngpc_palfx_fade(GFX_SCR1, 0xFF, scene_palette, 5u);
}
if (ngpc_transition_active(&tr)) skip_input();
```

> **Note :** `ngpc_transition.c` inclut `../fx/ngpc_palfx.h` — le module doit être dans `src/ngpc_transition/`.
> Copier aussi `ngpc_room/` dans `src/`.

---

### `ngpc_wave` — Vagues d'ennemis scriptées
**Type :** .h + .c · **RAM :** 7 octets par `NgpcWaveSeq` · **ROM :** 6 octets par `NgpcWaveEntry`

Rejoue un tableau ROM d'événements de spawn trié par délai croissant.
Compatible avec les timers frame ou les compteurs de scroll (shmup, tower defense).

| Élément | Description |
|---|---|
| `NgpcWaveEntry {type, x, y, data, delay}` | Entrée ROM : type ennemi, position, délai en frames |
| `WAVE_END` | Sentinelle de fin de tableau (delay == 0xFFFF) |
| `WAVE_COUNT(arr)` | Macro : nombre d'entrées sans le sentinel |
| `ngpc_wave_start(seq, entries, count)` | Initialise et démarre la séquence |
| `ngpc_wave_update(seq)` | Avance timer + retourne `NgpcWaveEntry*` si spawn dû, sinon NULL |
| `ngpc_wave_tick(seq)` | Avance le timer uniquement |
| `ngpc_wave_poll(seq)` | Interroge sans avancer (pour spawns simultanés) |
| `ngpc_wave_stop(seq)` | Stoppe proprement |
| `WAVE_FLAG_ACTIVE/DONE` | Flags d'état |

```c
static const NgpcWaveEntry s_wave1[] = {
    { 1, 148, 40, 0, 0   },   /* ennemi type 1, x=148, y=40, frame 0  */
    { 1, 148, 80, 0, 54  },   /* ennemi type 1, frame 54               */
    { 2, 148, 60, 1, 108 },   /* ennemi type 2, frame 108              */
    WAVE_SENTINEL
};

static NgpcWaveSeq s_seq;
/* WAVE_COUNT inclut le sentinel → -1 pour n'avoir que les vraies entrées */
ngpc_wave_start(&s_seq, s_wave1, WAVE_COUNT(s_wave1) - 1);

/* Chaque frame de jeu : */
{
    const NgpcWaveEntry *e = ngpc_wave_update(&s_seq);
    /* Boucle pour les spawns simultanés (même delay) */
    while (e) {
        spawn_enemy(e->type, e->x, e->y, e->data);
        e = ngpc_wave_poll(&s_seq);   /* poll sans avancer le timer */
    }
}
if (ngpc_wave_done(&s_seq)) start_next_wave();
```

---

### `ngpc_inventory` — Inventaire d'items
**Type :** .h + .c · **RAM :** `INV_SLOTS × 2 + INV_EQUIP_SLOTS` (36 oct. par défaut) · **Dépend de :** rien

Tableau fixe d'items `{id, count}` + slots d'équipement. Zéro allocation dynamique.

| Fonction | Description |
|---|---|
| `ngpc_inv_init(inv)` | Vide l'inventaire et les slots d'équipement |
| `ngpc_inv_add(inv, id, count)` | Ajoute des items (empile si déjà présent), retourne 1/0 |
| `ngpc_inv_remove(inv, id, count)` | Retire des items, retourne 1 si OK, 0 si quantité insuffisante |
| `ngpc_inv_has(inv, id)` | Quantité totale de l'item (0 si absent) |
| `ngpc_inv_find(inv, id)` | Index du slot, ou `INV_NONE` (0xFF) |
| `ngpc_inv_used(inv)` | Nombre de slots occupés |
| `ngpc_inv_equip(inv, slot, id)` | Équipe l'item dans un slot (0=arme, 1=armure, 2-3=acc.) |
| `ngpc_inv_equipped(inv, slot)` | Macro : ID équipé dans le slot |
| `ngpc_inv_is_equipped(inv, id)` | 1 si l'item est équipé dans n'importe quel slot |

```c
/* Définir les items du jeu (0 est réservé = vide) */
#define ITEM_SWORD    1
#define ITEM_POTION   2
#define ITEM_KEY      3

static NgpcInventory inv;
ngpc_inv_init(&inv);

ngpc_inv_add(&inv, ITEM_POTION, 5);    /* ramasse 5 potions */
ngpc_inv_add(&inv, ITEM_SWORD,  1);

if (ngpc_inv_has(&inv, ITEM_POTION)) {
    ngpc_inv_remove(&inv, ITEM_POTION, 1);
    player_hp = (u8)(player_hp + 30);
}

ngpc_inv_equip(&inv, INV_SLOT_WEAPON, ITEM_SWORD);
u8 weapon = ngpc_inv_equipped(&inv, INV_SLOT_WEAPON);  /* → ITEM_SWORD */
```

> **Taille configurable :** `#define INV_SLOTS 8` et/ou `#define INV_EQUIP_SLOTS 2`
> avant d'inclure le header pour réduire la RAM.

---

### `ngpc_score` — Score courant + table des meilleurs scores
**Type :** .h + .c · **RAM :** 4 octets (`NgpcScore`) + 11 octets (`NgpcScoreTable`, top 5)

Score u32 (deux u16 pour éviter les ops 32-bit sur TLCS-900) + table de high scores triée décroissante.

| Élément | Description |
|---|---|
| `NgpcScore {lo, hi}` | Score courant jusqu'à ~4 milliards |
| `ngpc_score_reset(s)` | Remet à 0 |
| `ngpc_score_add(s, pts)` | Ajoute des points (u16), clampé à max |
| `ngpc_score_add_mul(s, pts, mul)` | Ajoute `pts × mul` |
| `ngpc_score_get_hi(s)` | Retourne la partie haute u16 (clampé à 65535 si débordement) |
| `ngpc_score_get_parts(s, hi_part, lo_part)` | Décompose pour affichage 8 chiffres |
| `NgpcScoreTable` | Top `SCORE_TABLE_SIZE` scores triés décroissant |
| `ngpc_score_table_insert(t, score)` | Insère si classé, retourne le rang (1-based, 0=non classé) |
| `ngpc_score_table_is_high(t, score)` | 1 si le score entrerait dans la table |
| `ngpc_score_table_get(t, rank)` | Score au rang donné (1-based) |
| `ngpc_score_table_sort(t)` | Retrie (utile après chargement flash) |
| `ngpc_score_table_clear(t)` | Efface tous les scores |

```c
static NgpcScore     score;
static NgpcScoreTable hi;

ngpc_score_reset(&score);
ngpc_score_table_init(&hi);

/* En jeu : */
ngpc_score_add(&score, 100);              /* +100 pts */
ngpc_score_add_mul(&score, 50, 3);        /* +150 pts (combo ×3) */

/* Fin de partie : */
u8 rank = ngpc_score_table_insert(&hi, ngpc_score_get_hi(&score));
if (rank > 0) show_highscore_screen(rank);

/* Affichage 8 chiffres sur HUD : */
u16 hi_part, lo_part;
ngpc_score_get_parts(&score, &hi_part, &lo_part);
/* hi_part = chiffres 5-8, lo_part = chiffres 1-4 (0..9999 chacun) */

/* Persister vers flash : */
memcpy(flash_buf, hi.table, sizeof(hi.table));
/* Au démarrage, après chargement flash : */
memcpy(hi.table, flash_buf, sizeof(hi.table));
ngpc_score_table_sort(&hi);
```

> **Taille configurable :** `#define SCORE_TABLE_SIZE 10` pour un top 10 (20 octets RAM).
> Compatible avec le système flash du template (`NGPC_FLASH_SAVE_GUIDE.md`).

---

### `ngpc_vehicle` — Physique véhicule top-down (8 directions)
**Type :** .h + .c · **RAM :** 8 octets (`NgpcVehicle`) + 4 octets opt. (`NgpcDriftState`) · **Dépend de :** `ngpc_fixed`, `ngpc_tilecol`

Modèle physique simplifié style Micro Machines : vitesse scalaire (avant/arrière), direction discrète 8 crans (0=E, 1=NE, …, 7=SE), friction différenciée par surface, rebond sur murs.

#### Physique de base

| Élément | Description |
|---|---|
| `NgpcVehicle {pos, speed, dir, flags}` | 8 octets — position fx16, vitesse fx16, direction 0-7, flags d'état |
| `ngpc_vehicle_init(v, px, py, dir)` | Initialise à la position pixel, vitesse = 0 |
| `ngpc_vehicle_steer(v, delta)` | Tourne de ±1 cran (modulo 8) |
| `ngpc_vehicle_accel(v, amount, max_speed)` | Accélère de `amount` fx16, clampé à `[-max_speed, max_speed]` |
| `ngpc_vehicle_brake(v, amount)` | Décélère vers 0 de `amount` fx16 |
| `ngpc_vehicle_update(v, col, rw, rh)` | Met à jour la physique : surface, friction, déplacement, collisions |
| `VEH_FLAG_WALL_HIT` | Rebond sur mur ce frame |
| `VEH_FLAG_OFFTRACK` | Tile VOID — hors-piste |
| `VEH_FLAG_BOOSTING` | Sur boost strip ce frame |
| `VEH_TILE_BOOST / GRAVEL / VOID` | Types de tiles spéciaux (IDs 5-7) |
| `VEH_SPEED_MAX` | 4 px/frame (fx16) |
| `VEH_FRICTION_TRACK / GRAVEL` | 15/16 (piste) ou 12/16 (gravier) |
| `VEH_BOUNCE_FACTOR` | 0.5 — demi-vitesse après rebond |

#### Extension drift (opt-in, 4 octets)

| Élément | Description |
|---|---|
| `NgpcDriftState {vel_lat}` | Vitesse latérale courante en fx16 |
| `ngpc_vehicle_drift_reset(d)` | Remet `vel_lat` à zéro |
| `ngpc_vehicle_steer_drift(v, d, delta)` | Virage avec transfert vitesse → latéral |
| `ngpc_vehicle_update_drift_auto(v, d, col, rw, rh, is_turning)` | Update complet avec grip auto (recommandé) |
| `ngpc_vehicle_update_drift(v, d, col, rw, rh, grip)` | Update avec grip manuel |
| `VEH_GRIP_HIGH / LOW / ICE` | 13/16 · 8/16 · 4/16 — adhérence par surface |
| `VEH_FLAG_DRIFTING` | Vitesse latérale > `VEH_DRIFT_THRESH` (2 px/frame) |

> **Budget CPU :** quand `is_turning == 0` et `vel_lat == {0,0}`, `update_drift_auto()` appelle directement `ngpc_vehicle_update()` — coût identique au cas sans drift (3 comparaisons d'overhead).

#### IA waypoints

| Élément | Description |
|---|---|
| `NgpcWaypoint {x, y}` | Centre pixel d'un waypoint (exporté par l'éditeur) |
| `ngpc_vehicle_ai_steer(v, wps, count, wp_idx, precision, accel, max_speed)` | Pilote automatique : oriente + accélère, freine en virage serré, avance `wp_idx` si dans le rayon. Retourne 1 si waypoint avancé |
| `ngpc_vehicle_lap_progress(laps, gate, gate_count)` | Score de progression = `laps × gate_count + gate` — comparer pour le classement |
| `VEH_AI_PRECISION` | Rayon de capture waypoint par défaut (16 px, Manhattan) |
| `VEH_ACCEL_DEFAULT` | 0.25 px/frame |
| `VEH_BRAKE_FORCE` | 0.5 px/frame |

```c
/* Physique de base */
static NgpcVehicle car;
ngpc_vehicle_init(&car, 80, 60, 0);  /* position (80,60), cap Est */

/* Game loop */
if (btn & BTN_RIGHT) ngpc_vehicle_steer(&car, +1);
if (btn & BTN_LEFT)  ngpc_vehicle_steer(&car, -1);
if (btn & BTN_A)     ngpc_vehicle_accel(&car, VEH_ACCEL_DEFAULT, VEH_SPEED_MAX);
if (btn & BTN_B)     ngpc_vehicle_brake(&car, VEH_BRAKE_FORCE);
ngpc_vehicle_update(&car, &col, 8, 8);
if (car.flags & VEH_FLAG_OFFTRACK) respawn(&car);

/* Drift (ajouter NgpcDriftState à côté du véhicule) */
static NgpcDriftState drift;
u8 turning = (btn & (BTN_LEFT | BTN_RIGHT)) != 0;
if (turning) ngpc_vehicle_steer_drift(&car, &drift, delta);
ngpc_vehicle_update_drift_auto(&car, &drift, &col, 8, 8, turning);
if (car.flags & VEH_FLAG_DRIFTING) play_sfx(SFX_SCREECH);

/* IA (tableau de waypoints exporté par l'éditeur) */
extern const NgpcWaypoint g_race_waypoints[];
#define RACE_WP_COUNT 8
static u8 ai_wp = 0;
ngpc_vehicle_ai_steer(&ai_car, g_race_waypoints, RACE_WP_COUNT,
                       &ai_wp, VEH_AI_PRECISION, VEH_ACCEL_DEFAULT, VEH_SPEED_MAX);

/* Classement (comparer les scores de progression) */
u16 score_p = ngpc_vehicle_lap_progress(p_laps, p_gate, RACE_LAP_GATE_COUNT);
u16 score_a = ngpc_vehicle_lap_progress(a_laps, a_gate, RACE_LAP_GATE_COUNT);
u8 player_leads = (score_p > score_a);
```

---

### `ngpc_pushblock` — Blocs poussables tile-based (Sokoban)
**Type :** .h + .c · **RAM :** 6 octets par bloc (`NgpcPushBlock`) · **Dépend de :** `ngpc_tilecol`

Mécanique Sokoban : le joueur pousse des blocs d'une case à la fois. Gère les collisions bloc-mur, bloc-bloc et la détection de zones cibles.

| Élément | Description |
|---|---|
| `NgpcPushBlock {tx, ty, active, _pad}` | 6 octets — position en coordonnées tile |
| `ngpc_pushblock_init(b, tx, ty)` | Initialise à la position tile |
| `ngpc_pushblock_try_push(b, others, n, ptx, pty, dx, dy, col, void_type)` | Tente de pousser le bloc. Retourne `PUSH_NONE / PUSH_MOVED / PUSH_VOID` |
| `ngpc_pushblock_on_region(b, rx, ry, rw, rh)` | 1 si le bloc est dans la région tile (pour déclencheur victoire) |
| `ngpc_pushblock_tile_type(b, col)` | Type de tile sous le bloc (via `ngpc_tilecol`) |
| `ngpc_pushblock_pixel(b, tile_size, px, py)` | Coordonnées pixel du coin haut-gauche |
| `PUSH_NONE / PUSH_MOVED / PUSH_VOID` | Résultat de `try_push` |

```c
/* Initialisation depuis l'export éditeur */
extern const NgpcPbTile g_puzzle01_push_block_tiles[];
#define PUZZLE01_PUSH_BLOCK_COUNT 3

static NgpcPushBlock blocks[PUZZLE01_PUSH_BLOCK_COUNT];
for (u8 i = 0; i < PUZZLE01_PUSH_BLOCK_COUNT; i++)
    ngpc_pushblock_init(&blocks[i], g_puzzle01_push_block_tiles[i].tx,
                                    g_puzzle01_push_block_tiles[i].ty);

/* Game loop — bouton A = pousser dans la direction du joueur */
if (btn_pressed & BTN_A) {
    s8 dx = player_dir_x;  /* -1, 0, +1 */
    s8 dy = player_dir_y;
    for (u8 i = 0; i < PUZZLE01_PUSH_BLOCK_COUNT; i++) {
        u8 r = ngpc_pushblock_try_push(&blocks[i], blocks, PUZZLE01_PUSH_BLOCK_COUNT,
                                        player_tx, player_ty, dx, dy, &col, 0);
        if (r == PUSH_VOID) { blocks[i].active = 0; }   /* bloc tombé dans le vide */
    }
}

/* Vérifier victoire : tous les blocs sur leur case cible */
u8 solved = 1;
for (u8 i = 0; i < PUZZLE01_PUSH_BLOCK_COUNT; i++) {
    /* Région cible exportée par l'éditeur (rx,ry = coin, rw=rh=1) */
    if (!ngpc_pushblock_on_region(&blocks[i], target_rx[i], target_ry[i], 1, 1))
        solved = 0;
}
if (solved) fsm_set_state(STATE_WIN);

/* Rendu */
for (u8 i = 0; i < PUZZLE01_PUSH_BLOCK_COUNT; i++) {
    if (!blocks[i].active) continue;
    s16 px, py;
    ngpc_pushblock_pixel(&blocks[i], 8, &px, &py);
    ngpc_sprite_draw(SPR_BLOCK, px - cam_x, py - cam_y);
}
```

> **Mouvement joueur :** `try_push` est appelé avec les coordonnées tile du joueur et sa direction. Si la case adjacente dans la direction `(dx,dy)` correspond au bloc, il est poussé.
> **Tip :** utiliser `ngpc_pushblock_tile_type()` pour détecter les pressure plates (type custom) sans modifier la logique core.

---

> Les modules suivants sont **déjà dans le core** et n'ont pas besoin d'un module optionnel :
> `ngpc_input` · `ngpc_text` · `ngpc_sprite` · `ngpc_math` (rand, sin, cos) · `ngpc_palfx` (fade, flash) · `ngpc_flash` (save 256 B)

---

## Modules par genre

| Genre | Modules recommandés |
|---|---|
| **Platformer** | `ngpc_platform` ✓, `ngpc_tilecol` ✓, `ngpc_anim` ✓, `ngpc_timer` ✓, `ngpc_pool` ✓, `ngpc_bullet` ✓, `ngpc_kinematic` ✓, `ngpc_room` ✓, `ngpc_transition` ✓, `ngpc_score` ✓, `ngpc_winani` ✓, `ngpc_mapstream` ✓ (grands niveaux), `ngpc_seq` ✓ (jingles/fanfares) |
| **Shooter** | `ngpc_bullet` ✓, `ngpc_pool` ✓, `ngpc_particle` ✓, `ngpc_anim` ✓, `ngpc_timer` ✓, `ngpc_aabb` ✓, `ngpc_wave` ✓, `ngpc_score` ✓, `ngpc_hud` ✓, `ngpc_soam` ✓, `ngpc_transition` ✓, `ngpc_raster_chain` ✓, `ngpc_seq` ✓ (SFX séquencés) |
| **RPG / Aventure** | `ngpc_actor` ✓, `ngpc_menu` ✓, `ngpc_fsm` ✓, `ngpc_camera` ✓, `ngpc_anim` ✓, `ngpc_tween` ✓, `ngpc_dialog` ✓, `ngpc_room` ✓, `ngpc_transition` ✓, `ngpc_inventory` ✓, `ngpc_entity` ✓, `ngpc_path` ✓, `ngpc_winani` ✓, `ngpc_tileblitter` ✓, `ngpc_mapstream` ✓ (monde ouvert), `ngpc_seq` ✓ (jingles de scène) |
| **Puzzle** | `ngpc_menu` ✓, `ngpc_timer` ✓, `ngpc_tween` ✓, `ngpc_easing` ✓, `ngpc_fsm` ✓, `ngpc_grid` ✓, `ngpc_pushblock` ✓ (blocs poussables), `ngpc_score` ✓, `ngpc_transition` ✓, `ngpc_seq` ✓ (jingle victoire) |
| **Course (top-down)** | `ngpc_vehicle` ✓, `ngpc_tilecol` ✓, `ngpc_fixed` ✓, `ngpc_camera` ✓, `ngpc_anim` ✓, `ngpc_timer` ✓, `ngpc_hud` ✓, `ngpc_score` ✓, `ngpc_soam` ✓, `ngpc_transition` ✓, `ngpc_seq` ✓ (musique/SFX) |
| **Action top-down** | `ngpc_actor` ✓, `ngpc_bullet` ✓, `ngpc_fsm` ✓, `ngpc_aabb` ✓, `ngpc_anim` ✓, `ngpc_particle` ✓, `ngpc_entity` ✓, `ngpc_path` ✓, `ngpc_wave` ✓, `ngpc_score` ✓, `ngpc_inventory` ✓, `ngpc_hud` ✓, `ngpc_soam` ✓, `ngpc_seq` ✓ (SFX séquencés) |
| **Fighting / Beat'em up** | `ngpc_motion` ✓ (quarter-circle, DP, double-tap), `ngpc_anim` ✓, `ngpc_aabb` ✓, `ngpc_fsm` ✓, `ngpc_pool` ✓, `ngpc_timer` ✓, `ngpc_hud` ✓, `ngpc_soam` ✓, `ngpc_score` ✓, `ngpc_transition` ✓, `ngpc_seq` ✓ (SFX coups) |
| **Roguelite / Donjon** | `ngpc_procgen` ✓, `ngpc_cavegen` ✓, `ngpc_rng` ✓, `ngpc_room` ✓, `ngpc_transition` ✓, `ngpc_pool` ✓, `ngpc_aabb` ✓, `ngpc_entity` ✓, `ngpc_fsm` ✓, `ngpc_anim` ✓, `ngpc_inventory` ✓, `ngpc_score` ✓, `ngpc_soam` ✓, `ngpc_hud` ✓, `ngpc_seq` ✓ (fanfares niveau) |
