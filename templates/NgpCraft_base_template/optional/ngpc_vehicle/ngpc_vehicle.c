#include "ngpc_vehicle.h"

/*
 * Table des 8 directions (0=E, sens anti-horaire de 45° en 45°).
 * Valeurs en fx16 (FX_ONE = 16 = 1.0).
 * Diagonales : 11/16 ≈ 0.6875 ≈ 1/√2 (approximation entière conservatrice).
 *
 *   0=E   1=NE   2=N   3=NW   4=W   5=SW   6=S   7=SE
 */
static const FxVec2 s_dirs[8] = {
    { (fx16) 16, (fx16)  0 },   /* 0: E  */
    { (fx16) 11, (fx16)-11 },   /* 1: NE */
    { (fx16)  0, (fx16)-16 },   /* 2: N  */
    { (fx16)-11, (fx16)-11 },   /* 3: NW */
    { (fx16)-16, (fx16)  0 },   /* 4: W  */
    { (fx16)-11, (fx16) 11 },   /* 5: SW */
    { (fx16)  0, (fx16) 16 },   /* 6: S  */
    { (fx16) 11, (fx16) 11 },   /* 7: SE */
};

/* ── Helpers IA (static) ─────────────────────────────────────────────── */

/* Convertit un vecteur (dx,dy) en direction 0-7 (même convention que s_dirs).
 * Seuil 2:1 pour distinguer directionnel cardinal vs diagonal. */
static u8 s_vec_to_dir(s16 dx, s16 dy)
{
    s16 ax = (s16)(dx < 0 ? (s16)-dx : dx);
    s16 ay = (s16)(dy < 0 ? (s16)-dy : dy);
    if (ax > (s16)(ay + ay)) return (dx > 0) ? 0u : 4u;    /* E / W  */
    if (ay > (s16)(ax + ax)) return (dy < 0) ? 2u : 6u;    /* N / S  */
    if (dx > 0 && dy < 0)    return 1u;   /* NE */
    if (dx < 0 && dy < 0)    return 3u;   /* NW */
    if (dx < 0 && dy > 0)    return 5u;   /* SW */
    return 7u;                             /* SE */
}

/* Tourne le véhicule d'un cran vers target_dir (chemin le plus court). */
static void s_steer_toward(NgpcVehicle *v, u8 target_dir)
{
    u8 delta = (u8)((target_dir - v->dir) & 7u);
    if (delta == 0u) return;
    v->dir = (delta <= 4u) ? (u8)((v->dir + 1u) & 7u)
                           : (u8)((v->dir + 7u) & 7u);
}

/* ── Implémentation ──────────────────────────────────────────────────── */

void ngpc_vehicle_init(NgpcVehicle *v, s16 px, s16 py, u8 dir)
{
    v->pos.x = INT_TO_FX(px);
    v->pos.y = INT_TO_FX(py);
    v->speed = 0;
    v->dir   = dir & 7;
    v->flags = 0;
}

void ngpc_vehicle_steer(NgpcVehicle *v, s8 delta)
{
    v->dir = (u8)((v->dir + (u8)(delta & 7)) & 7);
}

void ngpc_vehicle_accel(NgpcVehicle *v, fx16 amount, fx16 max_speed)
{
    v->speed = FX_ADD(v->speed, amount);
    if (v->speed > max_speed)         v->speed = max_speed;
    if (v->speed < FX_NEG(max_speed)) v->speed = FX_NEG(max_speed);
}

void ngpc_vehicle_brake(NgpcVehicle *v, fx16 amount)
{
    if (v->speed > amount)
        v->speed = FX_SUB(v->speed, amount);
    else if (v->speed < FX_NEG(amount))
        v->speed = FX_ADD(v->speed, amount);
    else
        v->speed = 0;
}

void ngpc_vehicle_update(NgpcVehicle *v, const NgpcTileCol *col,
                         u8 rw, u8 rh)
{
    FxVec2 d;
    s16    opx, opy, npx, npy, dx, dy, cx, cy;
    u8     surface;
    fx16   friction;
    NgpcMoveResult res;

    /* ── 1. Position pixel avant mouvement ── */
    opx = (s16)FX_TO_INT(v->pos.x);
    opy = (s16)FX_TO_INT(v->pos.y);

    /* ── 2. Surface sous le centre du véhicule ── */
    cx = (s16)(opx + (s16)(rw >> 1));
    cy = (s16)(opy + (s16)(rh >> 1));
    surface = (col != (NgpcTileCol *)0)
              ? ngpc_tilecol_type_at(col, cx, cy)
              : (u8)TILE_PASS;

    /* ── 3. Reset flags surface ── */
    v->flags &= (u8)~(VEH_FLAG_OFFTRACK | VEH_FLAG_BOOSTING);

    /* Hors-piste : arrêt immédiat, on ne déplace pas */
    if (surface == (u8)VEH_TILE_VOID) {
        v->speed = 0;
        v->flags |= VEH_FLAG_OFFTRACK;
        return;
    }

    /* Boost strip */
    if (surface == (u8)VEH_TILE_BOOST) {
        v->speed = FX_ADD(v->speed, (fx16)VEH_BOOST_DELTA);
        v->flags |= VEH_FLAG_BOOSTING;
    }

    /* ── 4. Friction selon surface ── */
    friction = (surface == (u8)VEH_TILE_GRAVEL)
               ? (fx16)VEH_FRICTION_GRAVEL
               : (fx16)VEH_FRICTION_TRACK;
    v->speed = FX_MUL(v->speed, friction);

    /* Snap à zéro si sous le seuil sub-pixel (évite oscillation infinie) */
    if (v->speed > (fx16)-2 && v->speed < (fx16)2) v->speed = 0;

    /* ── 5. Déplacement sub-pixel dans la direction courante ── */
    d = s_dirs[v->dir & 7];
    v->pos.x = FX_ADD(v->pos.x, FX_MUL(d.x, v->speed));
    v->pos.y = FX_ADD(v->pos.y, FX_MUL(d.y, v->speed));

    /* ── 6. Résolution de collision (via tilecol sur pixels entiers) ── */
    npx = (s16)FX_TO_INT(v->pos.x);
    npy = (s16)FX_TO_INT(v->pos.y);
    dx  = (s16)(npx - opx);
    dy  = (s16)(npy - opy);

    v->flags &= (u8)~VEH_FLAG_WALL_HIT;

    if (col != (NgpcTileCol *)0 && (dx || dy)) {
        ngpc_tilecol_move(col, &opx, &opy, rw, rh, dx, dy, &res);

        /* Reconstruire pos : position entière corrigée + fraction conservée */
        {
            fx16 fx = (fx16)((u16)(v->pos.x) & 0x0F);
            fx16 fy = (fx16)((u16)(v->pos.y) & 0x0F);
            v->pos.x = (fx16)(((s16)opx << FX_SHIFT) | (s16)fx);
            v->pos.y = (fx16)(((s16)opy << FX_SHIFT) | (s16)fy);
        }

        /* Rebond si collision mur */
        if (res.sides) {
            v->speed  = FX_MUL(FX_NEG(v->speed), (fx16)VEH_BOUNCE_FACTOR);
            v->flags |= VEH_FLAG_WALL_HIT;
        }
    }
}

u8 ngpc_vehicle_ai_steer(NgpcVehicle *v,
                          const NgpcWaypoint *wps, u8 wp_count,
                          u8 *wp_idx, u8 precision,
                          fx16 accel, fx16 max_speed)
{
    NgpcWaypoint wp;
    s16 px, py, dx, dy, ax, ay;
    u8  tdir, turn, advanced;

    if (!wp_count || !wps) return 0;

    advanced = 0;
    wp  = wps[*wp_idx % wp_count];
    px  = (s16)FX_TO_INT(v->pos.x);
    py  = (s16)FX_TO_INT(v->pos.y);
    dx  = (s16)(wp.x - px);
    dy  = (s16)(wp.y - py);
    ax  = (s16)(dx < 0 ? (s16)-dx : dx);
    ay  = (s16)(dy < 0 ? (s16)-dy : dy);

    /* Waypoint atteint : distance de Manhattan ≤ precision */
    if ((s16)(ax + ay) <= (s16)precision) {
        *wp_idx  = (u8)((*wp_idx + 1u) % wp_count);
        advanced = 1;
        wp  = wps[*wp_idx];
        dx  = (s16)(wp.x - px);
        dy  = (s16)(wp.y - py);
    }

    /* Direction optimale vers le waypoint */
    tdir = s_vec_to_dir(dx, dy);

    /* Amplitude du virage avant de tourner (0..4, 0=ligne droite) */
    turn = (u8)((tdir - v->dir) & 7u);
    if (turn > 4u) turn = (u8)(8u - turn);

    /* Tourner d'un cran vers la cible */
    s_steer_toward(v, tdir);

    /* Freinage en virage serré, accélération sinon */
    if (turn >= 2u)
        ngpc_vehicle_brake(v, accel);
    else
        ngpc_vehicle_accel(v, accel, max_speed);

    return advanced;
}

u16 ngpc_vehicle_lap_progress(u8 laps, u8 gate, u8 gate_count)
{
    return (u16)((u16)laps * gate_count + gate);
}

/* ── Drift ────────────────────────────────────────────────────────────── */

void ngpc_vehicle_drift_reset(NgpcDriftState *d)
{
    d->vel_lat.x = 0;
    d->vel_lat.y = 0;
}

void ngpc_vehicle_steer_drift(NgpcVehicle *v, NgpcDriftState *d, s8 delta)
{
    FxVec2 right;
    fx16   transfer;
    u8     steps;

    if (!delta) return;

    /* Vecteur perpendiculaire CW au cap courant : s_dirs[(dir+6) & 7]
     * Vérifié : E(0)→S(6), N(2)→E(0), W(4)→N(2), etc. */
    right = s_dirs[(v->dir + 6u) & 7u];

    /* Amplitude du transfert selon le nombre de crans de virage */
    steps = (u8)(delta < 0 ? (s8)-delta : delta);
    if (steps > 4u) steps = (u8)(8u - steps);      /* normalise à [0..4] */
    transfer = (steps >= 2u) ? v->speed
                             : FX_MUL(v->speed, (fx16)11); /* sin(45°) ≈ 11/16 */

    /* Direction du transfert : CW (delta>0) → rightward, CCW → leftward */
    if (delta > 0) {
        d->vel_lat.x = FX_ADD(d->vel_lat.x, FX_MUL(right.x, transfer));
        d->vel_lat.y = FX_ADD(d->vel_lat.y, FX_MUL(right.y, transfer));
    } else {
        d->vel_lat.x = FX_SUB(d->vel_lat.x, FX_MUL(right.x, transfer));
        d->vel_lat.y = FX_SUB(d->vel_lat.y, FX_MUL(right.y, transfer));
    }

    /* Tourner effectivement */
    ngpc_vehicle_steer(v, delta);
}

void ngpc_vehicle_update_drift(NgpcVehicle *v, NgpcDriftState *d,
                                const NgpcTileCol *col, u8 rw, u8 rh,
                                fx16 grip)
{
    FxVec2 fw;
    s16    opx, opy, npx, npy, dx, dy, cx, cy;
    s16    lx, ly;
    u8     surface;
    fx16   friction;
    NgpcMoveResult res;

    /* ── 1. Position pixel avant mouvement ── */
    opx = (s16)FX_TO_INT(v->pos.x);
    opy = (s16)FX_TO_INT(v->pos.y);

    /* ── 2. Surface sous le centre ── */
    cx = (s16)(opx + (s16)(rw >> 1));
    cy = (s16)(opy + (s16)(rh >> 1));
    surface = (col != (NgpcTileCol *)0)
              ? ngpc_tilecol_type_at(col, cx, cy)
              : (u8)TILE_PASS;

    /* ── 3. Reset flags surface ── */
    v->flags &= (u8)~(VEH_FLAG_OFFTRACK | VEH_FLAG_BOOSTING | VEH_FLAG_DRIFTING);

    /* Hors-piste : arrêt complet */
    if (surface == (u8)VEH_TILE_VOID) {
        v->speed      = 0;
        d->vel_lat.x  = 0;
        d->vel_lat.y  = 0;
        v->flags |= VEH_FLAG_OFFTRACK;
        return;
    }

    /* Boost strip */
    if (surface == (u8)VEH_TILE_BOOST) {
        v->speed = FX_ADD(v->speed, (fx16)VEH_BOOST_DELTA);
        v->flags |= VEH_FLAG_BOOSTING;
    }

    /* ── 4. Friction avant selon surface ── */
    friction = (surface == (u8)VEH_TILE_GRAVEL)
               ? (fx16)VEH_FRICTION_GRAVEL
               : (fx16)VEH_FRICTION_TRACK;
    v->speed = FX_MUL(v->speed, friction);

    /* ── 5. Friction latérale (grip) ── */
    d->vel_lat.x = FX_MUL(d->vel_lat.x, grip);
    d->vel_lat.y = FX_MUL(d->vel_lat.y, grip);

    /* Snap à zéro si sous le seuil sub-pixel */
    if (v->speed > (fx16)-2 && v->speed < (fx16)2) v->speed = 0;
    lx = (s16)(d->vel_lat.x < 0 ? (fx16)-d->vel_lat.x : d->vel_lat.x);
    ly = (s16)(d->vel_lat.y < 0 ? (fx16)-d->vel_lat.y : d->vel_lat.y);
    if (lx < 2 && ly < 2) { d->vel_lat.x = 0; d->vel_lat.y = 0; }

    /* ── 6. Déplacement = avant * speed + vel_lat ── */
    fw = s_dirs[v->dir & 7u];
    v->pos.x = FX_ADD(v->pos.x, FX_ADD(FX_MUL(fw.x, v->speed), d->vel_lat.x));
    v->pos.y = FX_ADD(v->pos.y, FX_ADD(FX_MUL(fw.y, v->speed), d->vel_lat.y));

    /* ── 7. Résolution de collision ── */
    npx = (s16)FX_TO_INT(v->pos.x);
    npy = (s16)FX_TO_INT(v->pos.y);
    dx  = (s16)(npx - opx);
    dy  = (s16)(npy - opy);

    v->flags &= (u8)~VEH_FLAG_WALL_HIT;

    if (col != (NgpcTileCol *)0 && (dx || dy)) {
        ngpc_tilecol_move(col, &opx, &opy, rw, rh, dx, dy, &res);

        /* Reconstruire pos : entier corrigé + fraction conservée */
        {
            fx16 fx = (fx16)((u16)(v->pos.x) & 0x0F);
            fx16 fy = (fx16)((u16)(v->pos.y) & 0x0F);
            v->pos.x = (fx16)(((s16)opx << FX_SHIFT) | (s16)fx);
            v->pos.y = (fx16)(((s16)opy << FX_SHIFT) | (s16)fy);
        }

        /* Rebond : inverser speed + amortir vel_lat */
        if (res.sides) {
            v->speed     = FX_MUL(FX_NEG(v->speed), (fx16)VEH_BOUNCE_FACTOR);
            d->vel_lat.x = FX_MUL(d->vel_lat.x,     (fx16)VEH_BOUNCE_FACTOR);
            d->vel_lat.y = FX_MUL(d->vel_lat.y,     (fx16)VEH_BOUNCE_FACTOR);
            v->flags    |= VEH_FLAG_WALL_HIT;
        }
    }

    /* ── 8. Flag DRIFTING (distance Manhattan de vel_lat) ── */
    lx = (s16)(d->vel_lat.x < 0 ? (fx16)-d->vel_lat.x : d->vel_lat.x);
    ly = (s16)(d->vel_lat.y < 0 ? (fx16)-d->vel_lat.y : d->vel_lat.y);
    if ((s16)(lx + ly) > (s16)VEH_DRIFT_THRESH)
        v->flags |= VEH_FLAG_DRIFTING;
}

void ngpc_vehicle_update_drift_auto(NgpcVehicle *v, NgpcDriftState *d,
                                     const NgpcTileCol *col, u8 rw, u8 rh,
                                     u8 is_turning)
{
    fx16 grip;

    /* Early-exit : vel_lat nulle + pas de virage → coût identique à update() */
    if (!is_turning && !d->vel_lat.x && !d->vel_lat.y) {
        ngpc_vehicle_update(v, col, rw, rh);
        return;
    }

    grip = (is_turning && v->speed > (fx16)VEH_DRIFT_THRESH)
           ? (fx16)VEH_GRIP_LOW
           : (fx16)VEH_GRIP_HIGH;

    ngpc_vehicle_update_drift(v, d, col, rw, rh, grip);
}
