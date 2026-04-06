#include "ngpc_score.h"

/* ── Score courant ───────────────────────────────────────── */

void ngpc_score_reset(NgpcScore *s)
{
    s->lo = 0;
    s->hi = 0;
}

void ngpc_score_add(NgpcScore *s, u16 pts)
{
    u16 new_lo;
    if (s->hi == 0xFFFFu && s->lo == 0xFFFFu) return;  /* clamp max */

    new_lo = (u16)(s->lo + pts);
    if (new_lo < s->lo) {
        /* débordement u16 */
        if (s->hi < 0xFFFFu) {
            s->hi++;
        } else {
            s->lo = 0xFFFFu;  /* clamp */
            return;
        }
    }
    s->lo = new_lo;
}

void ngpc_score_add_mul(NgpcScore *s, u16 pts, u8 multiplier)
{
    u8 i;
    if (multiplier == 0) return;
    for (i = 0; i < multiplier; i++) ngpc_score_add(s, pts);
}

u16 ngpc_score_get_hi(const NgpcScore *s)
{
    if (s->hi > 0) return 0xFFFFu;
    return s->lo;
}

void ngpc_score_get_parts(const NgpcScore *s, u16 *hi_part, u16 *lo_part)
{
    /* Décompose en deux tranches de 4 chiffres décimaux (0..9999 chacune)
     * pour l'affichage 8 chiffres sans division 32-bit.
     * Approximation : on divise s->lo par 10000 avec une soustraction itérative.
     * Pour un score max de 65535 × 65536 ≈ 4 milliards, on retourne
     * hi_part = s->hi (0..65535 en ×10000) et lo_part = s->lo % 10000. */
    u16 lo = s->lo;
    /* lo % 10000 par soustraction */
    while (lo >= 10000u) lo = (u16)(lo - 10000u);
    *lo_part = lo;
    *hi_part = s->hi;
}

/* ── Table des meilleurs scores ──────────────────────────── */

void ngpc_score_table_init(NgpcScoreTable *t)
{
    u8 i;
    for (i = 0; i < SCORE_TABLE_SIZE; i++) t->table[i] = 0;
    t->count = 0;
}

static void _sort(NgpcScoreTable *t)
{
    /* Tri à bulles sur SCORE_TABLE_SIZE entrées — petit tableau, OK */
    u8 i, j;
    u16 tmp;
    for (i = 0; i < SCORE_TABLE_SIZE - 1; i++) {
        for (j = 0; j < SCORE_TABLE_SIZE - 1 - i; j++) {
            if (t->table[j] < t->table[j + 1]) {
                tmp             = t->table[j];
                t->table[j]     = t->table[j + 1];
                t->table[j + 1] = tmp;
            }
        }
    }
}

u8 ngpc_score_table_insert(NgpcScoreTable *t, u16 score)
{
    u8 i, rank;

    if (score == 0) return 0;

    /* Chercher si le score entre (meilleur que le dernier ou table non pleine) */
    if (t->count < SCORE_TABLE_SIZE) {
        t->table[t->count++] = score;
    } else if (score > t->table[SCORE_TABLE_SIZE - 1]) {
        t->table[SCORE_TABLE_SIZE - 1] = score;
    } else {
        return 0;  /* pas classé */
    }

    _sort(t);

    /* Trouver le rang (1-based) */
    rank = 0;
    for (i = 0; i < SCORE_TABLE_SIZE; i++) {
        if (t->table[i] == score) {
            rank = (u8)(i + 1);
            break;
        }
    }
    return rank;
}

u8 ngpc_score_table_is_high(const NgpcScoreTable *t, u16 score)
{
    if (score == 0) return 0;
    if (t->count < SCORE_TABLE_SIZE) return 1;
    return (u8)(score > t->table[SCORE_TABLE_SIZE - 1]);
}

u16 ngpc_score_table_get(const NgpcScoreTable *t, u8 rank)
{
    if (rank == 0 || rank > SCORE_TABLE_SIZE) return 0;
    return t->table[rank - 1];
}

void ngpc_score_table_sort(NgpcScoreTable *t)
{
    u8 i;
    /* Recompter les entrées non nulles */
    t->count = 0;
    for (i = 0; i < SCORE_TABLE_SIZE; i++) {
        if (t->table[i] != 0) t->count++;
    }
    _sort(t);
}

void ngpc_score_table_clear(NgpcScoreTable *t)
{
    ngpc_score_table_init(t);
}
