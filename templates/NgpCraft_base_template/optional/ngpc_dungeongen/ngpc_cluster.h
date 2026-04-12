/*
 * ngpc_cluster.h -- Navigation par clusters de salles (modele arbre 2-4 noeuds)
 * =============================================================================
 *
 * CONCEPT
 * -------
 * Le donjon est divise en "clusters" de DUNGEONGEN_CLUSTER_SIZE_MAX salles max.
 * Chaque cluster est un arbre local :
 *
 *   [Entry] -+- [Node ou Leaf]
 *             +- [Leaf]
 *             +- [Leaf + escalier] --> cluster suivant (one-way)
 *
 * - Dans un cluster : backtrack libre (enfant -> parent toujours possible).
 * - Entre clusters  : one-way via escalier, pas de retour.
 *
 * MEMOIRE
 * -------
 *   NgpcCluster : 9 bytes fixes (2+1+4+1+1), independant de la taille du donjon.
 *   Aucune allocation dynamique, aucun graphe en RAM.
 *
 * USAGE
 * -----
 *   NgpcCluster cl;
 *   ngpc_cluster_gen(&cl, cluster_seed);    // genere la structure
 *   ngpc_cluster_enter(&cl, 0u);            // entre dans la room 0 (Entry)
 *   // dans la boucle jeu :
 *   ngpc_cluster_go_forward(&cl, exit_idx); // avance vers une sortie
 *   ngpc_cluster_go_back(&cl);              // revient au parent
 *   // test transition floor :
 *   if (ngpc_cluster_took_stair(&cl)) { ... }  // generer cluster suivant
 *
 * DEPENDANCES
 * -----------
 *   ngpc_dungeongen.h / ngpc_dungeongen.c
 */

#ifndef NGPC_CLUSTER_H
#define NGPC_CLUSTER_H

#include "ngpc_hw.h"
#include "ngpc_dungeongen/ngpc_dungeongen.h"

/* =========================================================================
 * Configuration
 * ========================================================================= */

/* Taille max du cluster (2..4). Synchronise avec DUNGEONGEN_CLUSTER_SIZE_MAX. */
#define NGPC_CLUSTER_MAX  DUNGEONGEN_CLUSTER_SIZE_MAX

/* =========================================================================
 * Structure de cluster
 * ========================================================================= */

/*
 * Decrit un cluster complet (genere une seule fois par ngpc_cluster_gen).
 * Lire uniquement, ne pas modifier directement.
 */
typedef struct {
    u16 cluster_seed;                    /* seed de ce cluster */
    u8  n_rooms;                         /* 2..NGPC_CLUSTER_MAX */
    u8  room_type[4];                    /* DGEN_ROOM_ENTRY/NODE/LEAF par room */
    u8  parent_idx[4];                   /* index parent (0xFF = Entry) */
    u8  n_children[4];                   /* nombre d'enfants (0..3) */
    u8  children[4][3];                  /* indices enfants (valides si < n_children[i]) */
    u8  stair_room;                      /* index de la leaf avec l'escalier */
    u8  current_room;                    /* room courante dans le cluster */
    u8  took_stair;                      /* 1 si le joueur vient de prendre l'escalier */
} NgpcCluster;

/* =========================================================================
 * API
 * ========================================================================= */

/*
 * Genere la structure d'arbre d'un cluster depuis sa seed.
 * Appeler une fois par cluster (transition d'escalier ou debut de jeu).
 * cluster_seed : u16 quelconque (derive depuis un seed de session ou index floor).
 */
void ngpc_cluster_gen(NgpcCluster *cl, u16 cluster_seed);

/*
 * Entre dans une room du cluster : appelle ngpc_dungeongen_enter() avec le bon
 * style, puis ngpc_dungeongen_set_room_type() selon room_type[room_idx].
 * L'escalier est place si room_idx == cl->stair_room.
 *
 * room_idx    : index dans le cluster (0 = Entry).
 * base_seed   : seed de base pour les rooms (typiquement cluster_seed).
 *               Chaque room i utilise base_seed XOR (i * 0x4E6Du) pour garantir
 *               des seeds differentes dans le meme cluster.
 */
void ngpc_cluster_enter(NgpcCluster *cl, u8 room_idx, u16 base_seed);

/*
 * Avance vers le N-ieme enfant de la room courante (exit_child_idx = 0..n_children-1).
 * Met a jour cl->current_room et rappelle ngpc_cluster_enter pour la nouvelle room.
 * Ne fait rien si exit_child_idx >= n_children[current].
 * base_seed : meme valeur que lors de l'appel initial a ngpc_cluster_enter.
 */
void ngpc_cluster_go_forward(NgpcCluster *cl, u8 exit_child_idx, u16 base_seed);

/*
 * Revient vers le parent de la room courante.
 * Met a jour cl->current_room et rappelle ngpc_cluster_enter pour la room parent.
 * Ne fait rien si la room courante est l'Entry (pas de parent).
 * base_seed : meme valeur que lors de l'appel initial.
 */
void ngpc_cluster_go_back(NgpcCluster *cl, u16 base_seed);

/*
 * Retourne 1 si le joueur vient de prendre l'escalier (transition cluster).
 * Remet automatiquement took_stair a 0 apres lecture.
 * Le code appelant doit alors generer un nouveau cluster (ngpc_cluster_gen)
 * avec une nouvelle seed.
 */
u8 ngpc_cluster_took_stair(NgpcCluster *cl);

/*
 * Retourne 1 si la room courante a un escalier.
 * Equivalent a (cl->current_room == cl->stair_room && ngpc_dgroom.has_stair).
 */
u8 ngpc_cluster_has_stair(const NgpcCluster *cl);

/*
 * Retourne le nombre d'exits "forward" disponibles depuis la room courante.
 * = n_children[current_room].
 * Utile pour masquer les sorties inexistantes cote game code.
 */
u8 ngpc_cluster_forward_count(const NgpcCluster *cl);

/*
 * Retourne 1 si la room courante a un exit "back" (retour parent).
 * = (current_room != Entry).
 */
u8 ngpc_cluster_has_back(const NgpcCluster *cl);

#endif /* NGPC_CLUSTER_H */
