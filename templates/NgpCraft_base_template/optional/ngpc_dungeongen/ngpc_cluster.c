/*
 * ngpc_cluster.c -- Navigation par clusters de salles (implementation)
 *
 * Voir ngpc_cluster.h pour la documentation API.
 */

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
 * ngpc_cluster_gen
 *
 * Genere un arbre de 2..NGPC_CLUSTER_MAX noeuds depuis cluster_seed.
 *
 * Algorithme :
 *   1. Tirer n_rooms dans [2, NGPC_CLUSTER_MAX] depuis la seed.
 *   2. Construire l'arbre : on distribue les noeuds 1..n-1 en tant qu'enfants
 *      des noeuds 0..n-2, au plus 3 enfants par noeud, en respectant la limite.
 *   3. Les feuilles (n_children == 0) recoivent room_type = DGEN_ROOM_LEAF.
 *   4. Les noeuds intermediaires = DGEN_ROOM_NODE.
 *   5. Le noeud 0 = DGEN_ROOM_ENTRY.
 *   6. L'escalier est place dans la feuille la plus profonde (max depth).
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
        cl->room_type[i]  = DGEN_ROOM_LEAF;
        cl->parent_idx[i] = 0xFFu;
        cl->n_children[i] = 0u;
        cl->children[i][0] = 0xFFu;
        cl->children[i][1] = 0xFFu;
        cl->children[i][2] = 0xFFu;
    }
    cl->room_type[0] = DGEN_ROOM_ENTRY;

    /* 3. Attacher chaque noeud i>=1 a un parent parmi 0..i-1
       Le parent choisi est le dernier noeud ayant encore de la place (<3 enfants).
       Si aucun n'a de place, on force le dernier disponible (ne doit pas arriver
       avec n<=4 et max 3 enfants par noeud). */
    for (i = 1u; i < n; i++) {
        /* Chercher un parent ayant de la place, de preference le noeud le plus
           recent qui n'est pas encore plein. */
        parent = 0u;
        {
            u8 j;
            for (j = 0u; j < i; j++) {
                if (cl->n_children[j] < 3u) {
                    parent = j;
                }
            }
        }
        cl->parent_idx[i]                           = parent;
        cl->children[parent][cl->n_children[parent]] = i;
        cl->n_children[parent] = (u8)(cl->n_children[parent] + 1u);
        /* Les noeuds qui ont des enfants ne sont pas des feuilles */
        if (cl->room_type[parent] != (u8)DGEN_ROOM_ENTRY) {
            cl->room_type[parent] = DGEN_ROOM_NODE;
        }
    }

    /* 4. Trouver la feuille la plus profonde pour l'escalier */
    /* Calculer depth de chaque noeud */
    tmp_depth[0] = 0u;
    for (i = 1u; i < n; i++) {
        parent     = cl->parent_idx[i];
        cur_depth  = (parent < 4u) ? (u8)(tmp_depth[parent] + 1u) : 0u;
        tmp_depth[i] = cur_depth;
    }
    best_depth = 0u;
    stair_room = (u8)(n - 1u);   /* fallback : derniere room */
    for (i = 0u; i < n; i++) {
        if (cl->room_type[i] == (u8)DGEN_ROOM_LEAF) {
            depth = tmp_depth[i];
            if (depth >= best_depth) {
                best_depth = depth;
                stair_room = i;
            }
        }
    }
    cl->stair_room = stair_room;
}

/* =========================================================================
 * ngpc_cluster_enter
 * ========================================================================= */
void ngpc_cluster_enter(NgpcCluster *cl, u8 room_idx, u16 base_seed)
{
    u8 rtype;
    u8 avec_esc;
    u16 rseed;

    cl->current_room = room_idx;
    cl->took_stair   = 0u;

    rtype    = cl->room_type[room_idx];
    avec_esc = (room_idx == cl->stair_room) ? 1u : 0u;
    rseed    = _room_seed(base_seed, room_idx);

    /* Style : nombre d'exits muraux = n_children + (1 si back, sauf Entry) */
    /* On derive le style automatiquement (0xFF) et laisse dungeongen choisir. */
    /* Le game code peut forcer un style particulier si besoin. */
    ngpc_dungeongen_enter((u16)rseed, 0xFFu);
    ngpc_dungeongen_set_room_type(rtype, avec_esc);
}

/* =========================================================================
 * ngpc_cluster_go_forward
 * ========================================================================= */
void ngpc_cluster_go_forward(NgpcCluster *cl, u8 exit_child_idx, u16 base_seed)
{
    u8 cur;
    u8 child;

    cur = cl->current_room;
    if (exit_child_idx >= cl->n_children[cur]) { return; }

    child = cl->children[cur][exit_child_idx];
    if (child == 0xFFu || child >= cl->n_rooms)  { return; }

    /* Verifier escalier AVANT de changer de room */
    if (cur == cl->stair_room && ngpc_dgroom.has_stair) {
        cl->took_stair = 1u;
        return;   /* le game code doit generer un nouveau cluster */
    }

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
