#ifndef NGPC_MENU_H
#define NGPC_MENU_H

/*
 * ngpc_menu -- Menu de sélection au D-pad
 * ========================================
 * Navigation haut/bas avec PAD_UP/PAD_DOWN. Validation avec PAD_A.
 * Affichage sur tilemap via ngpc_text_print().
 *
 * Dépendances (includes automatiques) :
 *   ngpc_input.h  (ngpc_pad_pressed, PAD_*)
 *   ngpc_text.h   (ngpc_text_print)
 *
 * Le build doit inclure src/core/ et src/gfx/ dans les chemins.
 *
 * Usage:
 *   Copier ngpc_menu/ dans src/
 *   OBJS += src/ngpc_menu/ngpc_menu.rel
 *   #include "ngpc_menu/ngpc_menu.h"
 *
 * Exemple :
 *   static const char *items[] = { "JOUER", "OPTIONS", "QUITTER" };
 *   static NgpcMenu menu;
 *   ngpc_menu_init(&menu, items, 3, 1);     // wrap=1
 *   ngpc_menu_draw(&menu, PLANE_SCR1, 8, 6, '>');
 *
 *   // Chaque frame :
 *   u8 sel = ngpc_menu_update(&menu);
 *   if (menu.changed) ngpc_menu_draw(&menu, PLANE_SCR1, 8, 6, '>');
 *   if (sel != MENU_NONE) { ... action[sel] ... }
 */

#include "ngpc_hw.h"  /* u8 */

#define MENU_MAX_ITEMS   8
#define MENU_NONE        0xFF   /* retourné si A n'est pas pressé */

/* ── Type ───────────────────────────────────────────────── */
typedef struct {
    const char **items;   /* tableau de chaînes (en ROM) */
    u8 count;             /* nombre d'items (max MENU_MAX_ITEMS) */
    u8 cursor;            /* item sélectionné (0..count-1) */
    u8 wrap;              /* 1 = le curseur boucle en haut/bas */
    u8 changed;           /* 1 si le curseur a bougé ce frame (pour redraw conditionnel) */
} NgpcMenu;

/* ── API ────────────────────────────────────────────────── */

/* Initialise le menu.
 *   items : tableau de pointeurs vers chaînes constantes
 *   count : nombre d'items (max MENU_MAX_ITEMS)
 *   wrap  : 1 = boucle aux bords */
void ngpc_menu_init(NgpcMenu *m, const char **items, u8 count, u8 wrap);

/* Met à jour le menu (lit ngpc_pad_pressed).
 * Retourne l'index sélectionné si PAD_A pressé, MENU_NONE sinon.
 * Met m->changed à 1 si le curseur a bougé. */
u8 ngpc_menu_update(NgpcMenu *m);

/* Dessine le menu sur la tilemap.
 *   plane  : PLANE_SCR1 ou PLANE_SCR2
 *   tx, ty : position en tuiles du premier item
 *   cur_ch : caractère affiché devant l'item actif (ex: '>', '*') */
void ngpc_menu_draw(const NgpcMenu *m, u8 plane, u8 tx, u8 ty, char cur_ch);

/* Efface la zone du menu (remplace par des espaces).
 *   width : nombre de tuiles à effacer par ligne (titre le plus long + 2) */
void ngpc_menu_erase(const NgpcMenu *m, u8 plane, u8 tx, u8 ty, u8 width);

#endif /* NGPC_MENU_H */
