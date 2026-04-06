#ifndef NGPC_VEHICLE_H
#define NGPC_VEHICLE_H

/*
 * ngpc_vehicle -- Physique véhicule top-down (8 directions)
 * =========================================================
 * Modèle simplifié adapté aux jeux de course NGPC style Micro Machines :
 *   - Vitesse scalaire (avant/arrière) + direction discrète (0-7, pas de 45°)
 *   - Friction différenciée par surface (piste / gravier / boost)
 *   - Rebond automatique sur les murs (via ngpc_tilecol)
 *   - Détection de zones spéciales : boost, gravier, hors-piste (void)
 *
 * Directions (sens anti-horaire, 0=Est) :
 *   0=E  1=NE  2=N  3=NW  4=W  5=SW  6=S  7=SE
 *
 * Types de tiles reconnus (libres 5-7 dans ngpc_tilecol) :
 *   TILE_PASS    = 0  (piste normale)
 *   TILE_SOLID   = 1  (mur — géré par ngpc_tilecol_move)
 *   VEH_TILE_BOOST  = 5  (boost strip — +vitesse chaque frame)
 *   VEH_TILE_GRAVEL = 6  (gravier — friction forte)
 *   VEH_TILE_VOID   = 7  (hors-piste — arrêt immédiat)
 *
 * Dépendances :
 *   ngpc_fixed/ngpc_fixed.h
 *   ngpc_tilecol/ngpc_tilecol.h
 *
 * Usage :
 *   Copier ngpc_vehicle/ dans src/
 *   OBJS += src/ngpc_vehicle/ngpc_vehicle.rel
 *   #include "ngpc_vehicle/ngpc_vehicle.h"
 */

#include "ngpc_hw.h"
#include "../ngpc_fixed/ngpc_fixed.h"
#include "../ngpc_tilecol/ngpc_tilecol.h"

/* ── Types de tiles spéciaux (5-7 libres dans ngpc_tilecol) ─────────── */

#define VEH_TILE_BOOST      5   /* boost strip : +vitesse chaque frame  */
#define VEH_TILE_GRAVEL     6   /* gravier     : friction élevée         */
#define VEH_TILE_VOID       7   /* hors-piste  : arrêt immédiat         */

/* ── Constantes physique par défaut ─────────────────────────────────── */

/* Vitesse maximale par défaut (px/frame en fx16).
 * Remplacer par la valeur souhaitée dans ngpc_vehicle_accel(). */
#define VEH_SPEED_MAX       INT_TO_FX(4)        /* 4 px/frame            */
#define VEH_SPEED_REVERSE   FX_LIT(-1.5f)       /* vitesse maxi arrière  */

/* Accélération boost strip appliquée chaque frame par dessus la vitesse */
#define VEH_BOOST_DELTA     FX_LIT(0.125f)      /* +0.125 px/frame       */

/* Friction multiplicative (appliquée à la vitesse chaque frame) :
 *   FX_LIT(0.9375) = 15/16  → légère perte de vitesse (piste)
 *   FX_LIT(0.75)   = 12/16  → freinage marqué (gravier) */
#define VEH_FRICTION_TRACK  ((fx16)(FX_ONE - 1))   /* 15/16 — piste     */
#define VEH_FRICTION_GRAVEL ((fx16)(FX_ONE - 4))   /* 12/16 — gravier   */

/* Facteur de rebond sur mur (appliqué à la vitesse inversée).
 *   FX_HALF = 0.5 → demi-vitesse après rebond. */
#define VEH_BOUNCE_FACTOR   FX_HALF

/* ── Constantes dérive (drift) ───────────────────────────────────────── */

/* Adhérence latérale (grip) — appliquée à vel_lat chaque frame.
 * Valeur haute = adhérence forte (peu de dérive).
 * Valeur basse = dérive longue (glace / gravier mouillé). */
#define VEH_GRIP_HIGH    ((fx16)(FX_ONE - 3))   /* 13/16 — adhérence normale   */
#define VEH_GRIP_LOW     ((fx16)(FX_ONE - 8))   /* 8/16  — dérapage marqué     */
#define VEH_GRIP_ICE     ((fx16)(FX_ONE - 12))  /* 4/16  — glace / vent glacé  */

/* Seuil de vitesse latérale (fx16) au-dessus duquel VEH_FLAG_DRIFTING est levé.
 * INT_TO_FX(2) = 2 px/frame de vitesse latérale. */
#define VEH_DRIFT_THRESH INT_TO_FX(2)

/* ── Constantes IA ──────────────────────────────────────────────────── */

#define VEH_ACCEL_DEFAULT   FX_LIT(0.25f)   /* accélération standard / frame  */
#define VEH_BRAKE_FORCE     FX_LIT(0.5f)    /* force de freinage / frame      */
#define VEH_AI_PRECISION    16              /* rayon waypoint défaut (pixels) */

/* ── Flags d'état (NgpcVehicle.flags) ───────────────────────────────── */

#define VEH_FLAG_WALL_HIT   0x01    /* collision mur ce frame            */
#define VEH_FLAG_OFFTRACK   0x02    /* tile VOID — véhicule hors-piste   */
#define VEH_FLAG_BOOSTING   0x04    /* tile BOOST actif ce frame         */
#define VEH_FLAG_DRIFTING   0x08    /* vitesse latérale > VEH_DRIFT_THRESH */

/* ── Structure NgpcVehicle (8 octets) ───────────────────────────────── */

typedef struct {
    FxVec2 pos;     /* position monde en fx16 (4 octets)                 */
    fx16   speed;   /* vitesse scalaire en fx16, >0=avant, <0=arrière    */
    u8     dir;     /* direction 0-7 : 0=E 1=NE 2=N 3=NW 4=W 5=SW 6=S 7=SE */
    u8     flags;   /* VEH_FLAG_* combinés                               */
} NgpcVehicle;      /* 8 octets                                          */

/* ── API ─────────────────────────────────────────────────────────────── */

/*
 * ngpc_vehicle_init -- Initialise le véhicule à la position pixel (px,py),
 *                      direction dir (0-7), vitesse nulle.
 */
void ngpc_vehicle_init(NgpcVehicle *v, s16 px, s16 py, u8 dir);

/*
 * ngpc_vehicle_steer -- Tourne le véhicule de delta directions (±1).
 *   delta = +1 → rotation CW (vers la droite en vue top-down)
 *   delta = -1 → rotation CCW (vers la gauche)
 *   Enroule modulo 8.
 */
void ngpc_vehicle_steer(NgpcVehicle *v, s8 delta);

/*
 * ngpc_vehicle_accel -- Accélère de `amount` fx16, clampe à [-max_speed, max_speed].
 *   Exemple : ngpc_vehicle_accel(&car, FX_LIT(0.25f), VEH_SPEED_MAX);
 */
void ngpc_vehicle_accel(NgpcVehicle *v, fx16 amount, fx16 max_speed);

/*
 * ngpc_vehicle_brake -- Décélère vers zéro de `amount` fx16.
 *   Utilisé pour le freinage volontaire ou le frein à main.
 *   Exemple : ngpc_vehicle_brake(&car, FX_LIT(0.5f));
 */
void ngpc_vehicle_brake(NgpcVehicle *v, fx16 amount);

/*
 * ngpc_vehicle_update -- Met à jour la physique chaque frame.
 *   1. Détecte la surface sous le véhicule (boost / gravier / void).
 *   2. Applique friction selon surface.
 *   3. Déplace le véhicule dans sa direction.
 *   4. Résout les collisions avec les murs (TILE_SOLID).
 *   5. Met à jour NgpcVehicle.flags.
 *
 *   col : tilemap de collision (peut être NULL = pas de murs).
 *   rw  : largeur hitbox en pixels.
 *   rh  : hauteur hitbox en pixels.
 *
 *   Après l'appel :
 *     v->flags & VEH_FLAG_WALL_HIT  → rebond ce frame
 *     v->flags & VEH_FLAG_OFFTRACK  → sur tile VOID (stopper / respawn)
 *     v->flags & VEH_FLAG_BOOSTING  → sur boost strip
 */
void ngpc_vehicle_update(NgpcVehicle *v, const NgpcTileCol *col,
                         u8 rw, u8 rh);

/* ── Drift ────────────────────────────────────────────────────────────── */

/*
 * NgpcDriftState -- Extension drift pour NgpcVehicle (4 octets).
 * Stocker aux côtés du NgpcVehicle. Initialiser à zéro ou via
 * ngpc_vehicle_drift_reset().
 *
 * Le drift sépare le cap (NgpcVehicle.dir) du vecteur de déplacement réel :
 *   mouvement_réel = avant * speed + vel_lat
 *
 * vel_lat est la composante *perpendiculaire* au cap.
 * Elle est alimentée par les virages et s'atténue via le paramètre `grip`.
 */
typedef struct {
    FxVec2 vel_lat;   /* vitesse latérale courante en fx16 (4 octets) */
} NgpcDriftState;

/*
 * ngpc_vehicle_drift_reset -- Remet vel_lat à zéro (respawn / reset).
 */
void ngpc_vehicle_drift_reset(NgpcDriftState *d);

/*
 * ngpc_vehicle_steer_drift -- Remplacement drift-aware de ngpc_vehicle_steer().
 *   Lors d'un virage, transfère une fraction de la vitesse avant en vitesse
 *   latérale :
 *     1 cran  (45°) : transfert ≈ sin(45°) × speed  (11/16 en fx16)
 *     2 crans (90°) : transfert = speed (transfert total)
 *   La direction est mise à jour comme ngpc_vehicle_steer() (delta = ±1).
 *
 *   Utiliser cette fonction à la place de ngpc_vehicle_steer() dès que
 *   NgpcDriftState est actif.
 */
void ngpc_vehicle_steer_drift(NgpcVehicle *v, NgpcDriftState *d, s8 delta);

/*
 * ngpc_vehicle_update_drift -- Version complète (grip manuel).
 *   Utiliser quand on veut contrôler le grip soi-même (ex. : glace forcée,
 *   surface dynamique). Pour le cas courant, préférer update_drift_auto().
 *
 *   grip : VEH_GRIP_HIGH (normal), VEH_GRIP_LOW (dérapage), VEH_GRIP_ICE.
 */
void ngpc_vehicle_update_drift(NgpcVehicle *v, NgpcDriftState *d,
                                const NgpcTileCol *col, u8 rw, u8 rh,
                                fx16 grip);

/*
 * ngpc_vehicle_update_drift_auto -- Wrapper simplifié (usage recommandé).
 *   Détermine le grip automatiquement selon l'état de virage :
 *     is_turning = 1 ET speed > VEH_DRIFT_THRESH  →  VEH_GRIP_LOW  (dérapage)
 *     sinon                                         →  VEH_GRIP_HIGH (récupération)
 *
 *   Early-exit si vel_lat == 0 et is_turning == 0 : coût identique à update()
 *   normal dans ce cas.
 *
 *   Exemple dans le game loop :
 *     u8 turning = (btn & (BTN_LEFT | BTN_RIGHT)) != 0;
 *     if (turning) ngpc_vehicle_steer_drift(&car, &drift, delta);
 *     ngpc_vehicle_update_drift_auto(&car, &drift, &col, 8, 8, turning);
 *     if (car.flags & VEH_FLAG_DRIFTING) sfx_drift_smoke();
 */
void ngpc_vehicle_update_drift_auto(NgpcVehicle *v, NgpcDriftState *d,
                                     const NgpcTileCol *col, u8 rw, u8 rh,
                                     u8 is_turning);

/* ── Waypoint ─────────────────────────────────────────────────────────── */

/*
 * NgpcWaypoint -- Point de passage IA en coordonnées pixel.
 * Exporté par l'éditeur de scène dans g_{sym}_waypoints[] (sorted by wp_index).
 */
typedef struct {
    s16 x, y;   /* centre pixel du waypoint (tile_x*8 + tile_w*4, idem Y) */
} NgpcWaypoint;

/* ── API IA ──────────────────────────────────────────────────────────── */

/*
 * ngpc_vehicle_ai_steer -- Pilote automatique waypoint-following.
 *   Oriente et accélère le véhicule vers le waypoint courant (wp_idx).
 *   Freine automatiquement en virage serré (delta direction ≥ 2 crans).
 *   Avance wp_idx (circulaire) quand la distance de Manhattan au waypoint
 *   est ≤ precision (pixels).
 *
 *   Paramètres :
 *     wps       : tableau NgpcWaypoint (centres pixel, ordre de circuit)
 *     wp_count  : nombre de waypoints dans le tableau
 *     wp_idx    : [in/out] indice courant (0..wp_count-1), modifié si atteint
 *     precision : rayon de capture en pixels (Manhattan), ex. VEH_AI_PRECISION
 *     accel     : montant d'accélération / décélération par frame
 *     max_speed : vitesse maximale
 *
 *   Retourne 1 si le waypoint vient d'être avancé ce frame, 0 sinon.
 *   Utiliser le retour pour compter les tours : quand wp_idx repasse à 0,
 *   incrémenter le compteur de tours du coureur.
 */
u8 ngpc_vehicle_ai_steer(NgpcVehicle *v,
                          const NgpcWaypoint *wps, u8 wp_count,
                          u8 *wp_idx, u8 precision,
                          fx16 accel, fx16 max_speed);

/*
 * ngpc_vehicle_lap_progress -- Score de progression dans le circuit.
 *   Score = laps * gate_count + current_gate.
 *   Comparer deux scores pour déterminer le classement :
 *     if (ngpc_vehicle_lap_progress(a_laps, a_gate, N) >
 *         ngpc_vehicle_lap_progress(b_laps, b_gate, N)) => A devance B
 *
 *   gate_count = {SYM}_LAP_GATE_COUNT exporté par l'éditeur.
 */
u16 ngpc_vehicle_lap_progress(u8 laps, u8 gate, u8 gate_count);

#endif /* NGPC_VEHICLE_H */
