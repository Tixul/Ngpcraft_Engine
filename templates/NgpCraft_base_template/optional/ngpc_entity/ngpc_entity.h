#ifndef NGPC_ENTITY_H
#define NGPC_ENTITY_H

/*
 * ngpc_entity -- Tableau fixe d'entités avec dispatch par type
 * =============================================================
 * Tableau statique de NgpcEntity avec flag active/inactive.
 * Le jeu dispatche update/draw via un switch(type) — pas de pointeurs
 * de fonction pour éviter la surcharge ROM sur cc900.
 *
 * Taille par entité : 8 octets + ENTITY_DATA_SIZE octets de données jeu.
 * Taille par défaut : 8 + 8 = 16 octets, ENTITY_COUNT = 8 entités = 128 octets.
 *
 * Dépend de : ngpc_hw.h uniquement
 *
 * Usage :
 *   Copier ngpc_entity/ dans src/
 *   OBJS += src/ngpc_entity/ngpc_entity.rel
 *   #include "ngpc_entity/ngpc_entity.h"
 *
 * Exemple — ennemis et collectibles dans un jeu action :
 *
 *   // Définir les types d'entités du jeu
 *   #define ENT_SLIME    1
 *   #define ENT_COIN     2
 *
 *   // Utiliser la liste globale
 *   ngpc_entity_init_all();    // au chargement du niveau
 *
 *   // Spawner un slime
 *   NgpcEntity *e = ngpc_entity_spawn(ENT_SLIME, 64, 40);
 *   e->data[0] = 3;  // HP = 3
 *
 *   // Chaque frame :
 *   ngpc_entity_update_all();   // appelle entity_update() sur chaque active
 *   ngpc_entity_draw_all();     // appelle entity_draw() sur chaque active
 *
 *   // Implémenter dans le jeu (game.c) :
 *   void entity_update(NgpcEntity *e) {
 *       switch (e->type) {
 *           case ENT_SLIME: slime_update(e); break;
 *           case ENT_COIN:  coin_update(e);  break;
 *       }
 *   }
 *   void entity_draw(const NgpcEntity *e) {
 *       switch (e->type) {
 *           case ENT_SLIME: slime_draw(e); break;
 *           case ENT_COIN:  coin_draw(e);  break;
 *       }
 *   }
 */

#include "ngpc_hw.h"

/* ── Taille du pool et des données extra ─────────────────── */
#ifndef ENTITY_COUNT
#define ENTITY_COUNT      8   /* entités max simultanées */
#endif

#ifndef ENTITY_DATA_SIZE
#define ENTITY_DATA_SIZE  8   /* octets de données jeu par entité */
#endif

/* ── Struct entité (8 + ENTITY_DATA_SIZE octets) ────────── */
typedef struct {
    s16 x, y;                    /* position pixel                 */
    u8  type;                    /* type d'entité (défini par jeu) */
    u8  active;                  /* 1 si en jeu, 0 si libre        */
    u8  timer;                   /* timer généraliste (usage libre) */
    u8  flags;                   /* flags généraux (usage libre)   */
    u8  data[ENTITY_DATA_SIZE];  /* données jeu (HP, état, etc.)   */
} NgpcEntity;

/* ── Tableau global ──────────────────────────────────────── */
extern NgpcEntity ngpc_entities[ENTITY_COUNT];

/* ── Fonctions à implémenter dans le jeu ─────────────────── */
/*
 * Le jeu DOIT fournir ces deux fonctions dans son propre code.
 * Elles sont appelées par ngpc_entity_update_all / ngpc_entity_draw_all.
 * Prototypes déclarés ici pour la vérification de type.
 */
void entity_update(NgpcEntity *e);
void entity_draw(const NgpcEntity *e);

/* ── API ─────────────────────────────────────────────────── */

/* Initialise toutes les entités (active = 0). */
void ngpc_entity_init_all(void);

/*
 * Alloue un slot libre et initialise type, x, y, active=1.
 * Retourne un pointeur vers l'entité, ou NULL si le tableau est plein.
 * Les champs timer, flags et data sont remis à 0.
 */
NgpcEntity *ngpc_entity_spawn(u8 type, s16 x, s16 y);

/* Désactive une entité (la libère pour réutilisation). */
#define ngpc_entity_kill(e)  ((e)->active = 0)

/*
 * Appelle entity_update(e) pour chaque entité active.
 * Sûr : la fonction peut désactiver des entités pendant l'itération.
 */
void ngpc_entity_update_all(void);

/*
 * Appelle entity_draw(e) pour chaque entité active.
 */
void ngpc_entity_draw_all(void);

/*
 * Cherche la première entité active d'un type donné.
 * Retourne NULL si aucune.
 */
NgpcEntity *ngpc_entity_find(u8 type);

/* Nombre d'entités actives. */
u8 ngpc_entity_count_active(void);

/* Désactive toutes les entités d'un type. */
void ngpc_entity_kill_all(u8 type);

#endif /* NGPC_ENTITY_H */
