#include "ngpc_abl.h"

/* ── État interne ───────────────────────────────────────────────── */

static NgpcRect s_abl_rects[NGPC_ABL_MAX];  /* rectangles par ID */
static u32      s_abl_masks[NGPC_ABL_MAX];  /* bitmask collisions par ID */
static u32      s_abl_active;               /* bitmask des IDs actifs */

/* ── API ────────────────────────────────────────────────────────── */

void ngpc_abl_clear(void)
{
    u8 i;
    s_abl_active = 0u;
    for (i = 0u; i < (u8)NGPC_ABL_MAX; ++i) s_abl_masks[i] = 0u;
}

void ngpc_abl_set(u8 id, s16 x, s16 y, u8 w, u8 h)
{
    if (id >= (u8)NGPC_ABL_MAX) return;
    s_abl_rects[id].x = x;
    s_abl_rects[id].y = y;
    s_abl_rects[id].w = w;
    s_abl_rects[id].h = h;
    s_abl_active |= (1ul << id);
}

void ngpc_abl_remove(u8 id)
{
    if (id >= (u8)NGPC_ABL_MAX) return;
    s_abl_active   &= ~(1ul << id);
    s_abl_masks[id]  = 0u;
}

void ngpc_abl_test_all(void)
{
    u8 i, j;
    /* Effacer les masques */
    for (i = 0u; i < (u8)NGPC_ABL_MAX; ++i) s_abl_masks[i] = 0u;
    /* Test O(n²) symétrique : chaque paire (i,j) testée une seule fois */
    for (i = 0u; i < (u8)(NGPC_ABL_MAX - 1u); ++i) {
        if (!(s_abl_active & (1ul << i))) continue;
        for (j = (u8)(i + 1u); j < (u8)NGPC_ABL_MAX; ++j) {
            if (!(s_abl_active & (1ul << j))) continue;
            if (ngpc_rect_overlap(&s_abl_rects[i], &s_abl_rects[j])) {
                s_abl_masks[i] |= (1ul << j);
                s_abl_masks[j] |= (1ul << i);
            }
        }
    }
}

u8 ngpc_abl_hit(u8 id_a, u8 id_b)
{
    if (id_a >= (u8)NGPC_ABL_MAX || id_b >= (u8)NGPC_ABL_MAX) return 0u;
    return (u8)((s_abl_masks[id_a] >> id_b) & 1u);
}

u32 ngpc_abl_hit_mask(u8 id)
{
    if (id >= (u8)NGPC_ABL_MAX) return 0u;
    return s_abl_masks[id];
}
