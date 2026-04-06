#ifndef NGPC_SCORE_H
#define NGPC_SCORE_H

/*
 * ngpc_score -- Current score + RAM high score table
 * ===================================================
 * Current score: u32 with add/reset/get.
 * High score table: SCORE_TABLE_SIZE entries (u16), sorted descending.
 *
 * To persist high scores across sessions, save score_table.table[]
 * to flash (see NGPC_FLASH_SAVE_GUIDE.md).
 *
 * Depends on: ngpc_hw.h only
 *
 * RAM:
 *   NgpcScore      : 4 bytes (u32)
 *   NgpcScoreTable : SCORE_TABLE_SIZE x 2 + 1 = 11 bytes (default)
 *
 * Usage:
 *   Copy ngpc_score/ into src/
 *   OBJS += src/ngpc_score/ngpc_score.rel
 *   #include "ngpc_score/ngpc_score.h"
 *
 * Example:
 *   static NgpcScore     score;
 *   static NgpcScoreTable hi;
 *
 *   ngpc_score_reset(&score);
 *   ngpc_score_table_init(&hi);
 *
 *   // In-game:
 *   ngpc_score_add(&score, 100);           // +100
 *   ngpc_score_add_mul(&score, 10, 3);     // +(10 x 3)
 *
 *   // End of game:
 *   u8 rank = ngpc_score_table_insert(&hi, ngpc_score_get_hi(&score));
 *   if (rank > 0) show_highscore_screen(rank);
 *
 *   // Load/save:
 *   memcpy(hi.table, flash_data, sizeof(hi.table));
 *   ngpc_score_table_sort(&hi);    // after loading from flash
 */

#include "ngpc_hw.h"

/* ── Table size ──────────────────────────────────────────────────────── */
#ifndef SCORE_TABLE_SIZE
#define SCORE_TABLE_SIZE  5   /* top 5 entries */
#endif

/* Sentinel value for an empty entry */
#define SCORE_EMPTY  0u

/* ── Current score ───────────────────────────────────────────────────── */
/*
 * u32 to avoid overflow at 65535.
 * ngpc_score_get_hi() returns a u16 for the table (clamped to 65535).
 */
typedef struct {
    u16 lo;   /* bits 0-15  */
    u16 hi;   /* bits 16-31 */
} NgpcScore;

/* Reset the score to 0. */
void ngpc_score_reset(NgpcScore *s);

/*
 * Add `pts` to the score.
 * Clamped to 0xFFFFFFFF.
 */
void ngpc_score_add(NgpcScore *s, u16 pts);

/*
 * Add pts x multiplier.
 * multiplier == 0: no-op. Clamped to 0xFFFFFFFF.
 */
void ngpc_score_add_mul(NgpcScore *s, u16 pts, u8 multiplier);

/*
 * Return the high part (u16) for display / table.
 * If score > 65535, returns 65535.
 */
u16 ngpc_score_get_hi(const NgpcScore *s);

/*
 * Return the u32 value as two u16 parts (8-digit display).
 *   hi_part: digits 5-8 (0..9999)
 *   lo_part: digits 1-4 (0..9999)
 */
void ngpc_score_get_parts(const NgpcScore *s, u16 *hi_part, u16 *lo_part);

/* ── High score table ────────────────────────────────────────────────── */
typedef struct {
    u16 table[SCORE_TABLE_SIZE];  /* scores sorted descending */
    u8  count;                    /* valid entries            */
} NgpcScoreTable;

/* Initialize the table (all zeros). */
void ngpc_score_table_init(NgpcScoreTable *t);

/*
 * Insert `score` into the table if high enough.
 * Returns the rank (1 = first, 0 = not ranked).
 * Sorts automatically.
 */
u8 ngpc_score_table_insert(NgpcScoreTable *t, u16 score);

/*
 * Return 1 if `score` would enter the table.
 * Useful for showing "NEW RECORD!" before the game ends.
 */
u8 ngpc_score_table_is_high(const NgpcScoreTable *t, u16 score);

/*
 * Return the score at position `rank` (1-based).
 * Returns 0 if rank is invalid or entry is empty.
 */
u16 ngpc_score_table_get(const NgpcScoreTable *t, u8 rank);

/*
 * Re-sort the table descending (useful after raw flash load).
 */
void ngpc_score_table_sort(NgpcScoreTable *t);

/* Clear all scores. */
void ngpc_score_table_clear(NgpcScoreTable *t);

#endif /* NGPC_SCORE_H */
