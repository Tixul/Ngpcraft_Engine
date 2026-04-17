/*
 * ngpc_cluster.c -- Navigation par clusters de salles (implementation)
 *
 * Voir ngpc_cluster.h pour la documentation API.
 */

#include "dungeongen_config.h"
#include "ngpc_dungeongen/ngpc_cluster.h"

/* =========================================================================
 * RNG local (xorshift16 pur, decorelle du RNG interne dungeongen)
 * Multiplicateur 163u : decorrelation garantie avec les seeds dungeongen.
 * ========================================================================= */
static u16 s_cl_rng;

static void _cl_rng_seed(u16 seed)
{
    s_cl_rng = seed ? seed : 0xBEEFu;
}

static u8 _cl_rng_u8(void)
{
    s_cl_rng ^= (u16)(s_cl_rng << 7u);
    s_cl_rng ^= (u16)(s_cl_rng >> 9u);
    s_cl_rng ^= (u16)(s_cl_rng << 8u);
    return (u8)(s_cl_rng & 0xFFu);
}

/* =========================================================================
 * Seed derivee par room (decorrelation intra-cluster)
 * ========================================================================= */
static u16 _room_seed(u16 base, u8 room_idx)
{
    u16 s;
    s = (u16)((u16)((u16)room_idx * 0x4E6Du) ^ base);
    if (s == 0u) { s = 0x1A3Cu; }
    s ^= (u16)(s << 7u);
    s ^= (u16)(s >> 9u);
    s ^= (u16)(s << 8u);
    return s;
}

/* =========================================================================
 * Helper : direction opposee
 * ========================================================================= */
static u8 _opp(u8 dir)
{
    if (dir == (u8)DGN_EXIT_N) { return (u8)DGN_EXIT_S; }
    if (dir == (u8)DGN_EXIT_S) { return (u8)DGN_EXIT_N; }
    if (dir == (u8)DGN_EXIT_E) { return (u8)DGN_EXIT_W; }
    if (dir == (u8)DGN_EXIT_W) { return (u8)DGN_EXIT_E; }
    return 0xFFu;
}

/* Ordre de priorite pour les sorties forward : S d'abord, puis E, W, N.
 * Garantit que l'Entry (sans back-exit Nord) pointe vers le bas/droite/gauche. */
static const u8 _fwd_order[4] = {
    DGN_EXIT_S, DGN_EXIT_E, DGN_EXIT_W, DGN_EXIT_N
};

/* =========================================================================
 * ngpc_cluster_gen
 *
 * Genere un arbre de 2..NGPC_CLUSTER_MAX noeuds depuis cluster_seed.
 *
 * Algorithme :
 *   1. Tirer n_rooms dans [2, NGPC_CLUSTER_MAX] depuis la seed.
 *   2. Construire l'arbre : distribue les noeuds 1..n-1 en enfants de 0..n-2.
 *   3. Feuilles (n_children==0) → DGEN_ROOM_LEAF ; intermediaires → NODE.
 *   4. Noeud 0 = DGEN_ROOM_ENTRY.
 *   5. L'escalier est place dans la feuille la plus profonde.
 *   6. entry_dir[] et fwd_dirs[] sont initialises a 0xFF (remplis par cluster_enter).
 * ========================================================================= */
void ngpc_cluster_gen(NgpcCluster *cl, u16 cluster_seed)
{
    u8 i;
    u8 n;
    u8 parent;
    u8 depth;
    u8 best_depth;
    u8 stair_room;
    u8 tmp_depth[4];
    u8 cur_depth;

    _cl_rng_seed(cluster_seed);
    cl->cluster_seed = cluster_seed;
    cl->took_stair   = 0u;
    cl->current_room = 0u;

    /* 1. Nombre de rooms : 2..NGPC_CLUSTER_MAX */
    n = (u8)(2u + _cl_rng_u8() % (u8)((u8)NGPC_CLUSTER_MAX - 1u));
    if (n < 2u) { n = 2u; }
    cl->n_rooms = n;

    /* 2. Initialiser tous les noeuds */
    for (i = 0u; i < 4u; i++) {
        cl->room_type[i]   = DGEN_ROOM_LEAF;
        cl->parent_idx[i]  = 0xFFu;
        cl->n_children[i]  = 0u;
        cl->children[i][0] = 0xFFu;
        cl->children[i][1] = 0xFFu;
        cl->children[i][2] = 0xFFu;
        cl->entry_dir[i]   = 0xFFu;  /* inconnu jusqu'a la premiere entree */
        cl->fwd_dirs[i][0] = 0xFFu;
        cl->fwd_dirs[i][1] = 0xFFu;
        cl->fwd_dirs[i][2] = 0xFFu;
    }
    cl->room_type[0] = DGEN_ROOM_ENTRY;

    /* 3. Attacher chaque noeud i>=1 au dernier parent ayant de la place */
    for (i = 1u; i < n; i++) {
        parent = 0u;
        {
            u8 j;
            for (j = 0u; j < i; j++) {
                if (cl->n_children[j] < 3u) { parent = j; }
            }
        }
        cl->parent_idx[i]                            = parent;
        cl->children[parent][cl->n_children[parent]] = i;
        cl->n_children[parent] = (u8)(cl->n_children[parent] + 1u);
        if (cl->room_type[parent] != (u8)DGEN_ROOM_ENTRY) {
            cl->room_type[parent] = DGEN_ROOM_NODE;
        }
    }

    /* 4. Feuille la plus profonde → escalier */
    tmp_depth[0] = 0u;
    for (i = 1u; i < n; i++) {
        parent    = cl->parent_idx[i];
        cur_depth = (parent < 4u) ? (u8)(tmp_depth[parent] + 1u) : 0u;
        tmp_depth[i] = cur_depth;
    }
    best_depth = 0u;
    stair_room = (u8)(n - 1u);
    for (i = 0u; i < n; i++) {
        if (cl->room_type[i] == (u8)DGEN_ROOM_LEAF) {
            depth = tmp_depth[i];
            if (depth >= best_depth) { best_depth = depth; stair_room = i; }
        }
    }
    cl->stair_room = stair_room;
}

/* =========================================================================
 * ngpc_cluster_enter
 *
 * Entre dans room_idx :
 *   - Calcule le bitmask exits depuis entry_dir[room_idx] et n_children.
 *   - Convention : back-exit = opp(entry_dir), forward-exits = S→E→W→N
 *     (en excluant le back-exit).
 *   - Selectionne le style via ngpc_dungeongen_style_for_exits().
 *   - Enregistre fwd_dirs[room_idx][k] = direction du k-eme enfant.
 * ========================================================================= */
void ngpc_cluster_enter(NgpcCluster *cl, u8 room_idx, u16 base_seed)
{
    u8 rtype, avec_esc, style;
    u16 rseed;
    u8 back_dir, exits_mask;
    u8 n_fwd, fi, k;
    u8 d;

    cl->current_room = room_idx;
    cl->took_stair   = 0u;

    rtype    = cl->room_type[room_idx];
    avec_esc = (room_idx == cl->stair_room) ? 1u : 0u;
    rseed    = _room_seed(base_seed, room_idx);

    /* Back-exit : direction opposee a celle prise depuis le parent */
    back_dir = (cl->entry_dir[room_idx] != 0xFFu)
             ? _opp(cl->entry_dir[room_idx])
             : 0xFFu;
    exits_mask = (back_dir != 0xFFu) ? back_dir : 0u;

    /* Forward-exits : n_children premiers dans _fwd_order en excluant back_dir */
    n_fwd = cl->n_children[room_idx];
    k     = 0u;
    for (fi = 0u; fi < 4u && k < n_fwd; fi++) {
        d = _fwd_order[fi];
        if (d != back_dir) {
            cl->fwd_dirs[room_idx][k] = d;
            exits_mask |= d;
            k = (u8)(k + 1u);
        }
    }
    /* Slots non utilises */
    for (; k < 3u; k++) { cl->fwd_dirs[room_idx][k] = 0xFFu; }

    style = ngpc_dungeongen_style_for_exits(exits_mask);
    ngpc_dungeongen_enter((u16)rseed, style);
    ngpc_dungeongen_set_room_type(rtype, avec_esc);
}

/* =========================================================================
 * ngpc_cluster_go_forward_dir
 *
 * Avance vers l'enfant associe a la direction dir_bit (DGN_EXIT_N/S/E/W).
 * - Si room courante = stair_room avec escalier : pose took_stair=1 et retourne.
 * - Sinon : trouve l'enfant dont fwd_dirs[cur][k] == dir_bit, enregistre
 *   entry_dir[child] = dir_bit, entre dans la room.
 * ========================================================================= */
void ngpc_cluster_go_forward_dir(NgpcCluster *cl, u8 dir_bit, u16 base_seed)
{
    u8 cur, child, k;

    cur = cl->current_room;

    /* Escalier : toute tentative de sortie forward depuis la stair_room */
    if (cur == cl->stair_room && ngpc_dgroom.has_stair) {
        cl->took_stair = 1u;
        return;
    }

    /* Trouver l'enfant correspondant a cette direction */
    child = 0xFFu;
    for (k = 0u; k < cl->n_children[cur]; k++) {
        if (cl->fwd_dirs[cur][k] == dir_bit) {
            child = cl->children[cur][k];
            break;
        }
    }
    if (child == 0xFFu || child >= cl->n_rooms) { return; }

    cl->entry_dir[child] = dir_bit;
    ngpc_cluster_enter(cl, child, base_seed);
}

/* =========================================================================
 * ngpc_cluster_go_back
 * ========================================================================= */
void ngpc_cluster_go_back(NgpcCluster *cl, u16 base_seed)
{
    u8 cur;
    u8 par;

    cur = cl->current_room;
    par = cl->parent_idx[cur];
    if (par == 0xFFu || par >= cl->n_rooms) { return; }  /* Entry : pas de parent */

    ngpc_cluster_enter(cl, par, base_seed);
}

/* =========================================================================
 * Predicats
 * ========================================================================= */
u8 ngpc_cluster_took_stair(NgpcCluster *cl)
{
    u8 v;
    v = cl->took_stair;
    cl->took_stair = 0u;
    return v;
}

u8 ngpc_cluster_has_stair(const NgpcCluster *cl)
{
    return (cl->current_room == cl->stair_room && ngpc_dgroom.has_stair) ? 1u : 0u;
}

u8 ngpc_cluster_forward_count(const NgpcCluster *cl)
{
    return cl->n_children[cl->current_room];
}

u8 ngpc_cluster_has_back(const NgpcCluster *cl)
{
    return (cl->parent_idx[cl->current_room] != 0xFFu) ? 1u : 0u;
}

u8 ngpc_cluster_back_dir(const NgpcCluster *cl)
{
    u8 ed = cl->entry_dir[cl->current_room];
    return (ed != 0xFFu) ? _opp(ed) : 0xFFu;
}

u8 ngpc_cluster_fwd_dir(const NgpcCluster *cl, u8 child_idx)
{
    u8 cur = cl->current_room;
    if (child_idx >= cl->n_children[cur]) { return 0xFFu; }
    return cl->fwd_dirs[cur][child_idx];
}

u8 ngpc_cluster_exits_mask(const NgpcCluster *cl)
{
    u8 mask;
    u8 d;
    u8 k;
    u8 cur;
    cur  = cl->current_room;
    mask = 0u;
    d = ngpc_cluster_back_dir(cl);
    if (d != 0xFFu) { mask = (u8)(mask | d); }
    for (k = 0u; k < cl->n_children[cur]; k++) {
        d = cl->fwd_dirs[cur][k];
        if (d != 0xFFu) { mask = (u8)(mask | d); }
    }
    return mask;
}
