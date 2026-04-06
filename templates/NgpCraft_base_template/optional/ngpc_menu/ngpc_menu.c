#include "ngpc_menu.h"
#include "ngpc_input.h"   /* ngpc_pad_pressed, PAD_UP, PAD_DOWN, PAD_A */
#include "ngpc_text.h"    /* ngpc_text_print */

/* Chaîne d'espaces pour effacer une ligne (20 = largeur écran en tiles) */
static const char _blanks[] = "                    ";

void ngpc_menu_init(NgpcMenu *m, const char **items, u8 count, u8 wrap) {
    m->items   = items;
    m->count   = (count > MENU_MAX_ITEMS) ? MENU_MAX_ITEMS : count;
    m->cursor  = 0;
    m->wrap    = wrap;
    m->changed = 0;
}

u8 ngpc_menu_update(NgpcMenu *m) {
    m->changed = 0;

    if (ngpc_pad_pressed & PAD_UP) {
        if (m->cursor > 0) {
            m->cursor--;
            m->changed = 1;
        } else if (m->wrap && m->count > 0) {
            m->cursor = m->count - 1;
            m->changed = 1;
        }
    }

    if (ngpc_pad_pressed & PAD_DOWN) {
        if (m->count > 0 && m->cursor < m->count - 1) {
            m->cursor++;
            m->changed = 1;
        } else if (m->wrap) {
            m->cursor = 0;
            m->changed = 1;
        }
    }

    if (ngpc_pad_pressed & PAD_A) {
        return m->cursor;
    }

    return MENU_NONE;
}

void ngpc_menu_draw(const NgpcMenu *m, u8 plane, u8 tx, u8 ty, char cur_ch) {
    u8 i;
    char prefix[2];
    prefix[1] = '\0';

    for (i = 0; i < m->count; i++) {
        prefix[0] = (i == m->cursor) ? cur_ch : ' ';
        ngpc_text_print(plane, tx,     ty + i, prefix);
        ngpc_text_print(plane, tx + 1, ty + i, m->items[i]);
    }
}

void ngpc_menu_erase(const NgpcMenu *m, u8 plane, u8 tx, u8 ty, u8 width) {
    u8 i;
    /* Utilise les 'width' premiers espaces de _blanks (max 20) */
    if (width > 20) width = 20;
    for (i = 0; i < m->count; i++) {
        ngpc_text_print(plane, tx, ty + i, _blanks + (20 - width));
    }
}
