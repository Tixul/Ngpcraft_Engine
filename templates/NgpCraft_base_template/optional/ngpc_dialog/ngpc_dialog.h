/*
 * ngpc_dialog -- Tilemap dialogue box
 * ===================================
 * Renders a dialogue box on SCR2 with custom font, typewriter effect,
 * optional portrait sprite, optional speaker name, and up to 2 choices.
 *
 * Architecture (validated by Evolution + Nige-Ron-Pa RE):
 *   - Always uses GFX_SCR2 (not SCR1) so box position is camera-independent.
 *   - Saves/restores SCR2 scroll registers at open/close.
 *   - Game sprites must use SPR_MIDDLE so they pass behind SCR2 automatically.
 *   - Portrait sprite uses SPR_FRONT to appear above the box.
 *   - Text uses custom font (ngpc_font.h), not BIOS sysfont.
 *   - Word-wrap is automatic: no explicit '\n' needed (caller may still use it).
 *
 * Speaker string format:
 *   "\001SpeakerName\002Body text"
 *   Helper macros: DIALOG_SPEAKER_BEGIN_STR + name + DIALOG_SPEAKER_END_STR + body
 */

#ifndef NGPC_DIALOG_H
#define NGPC_DIALOG_H

#include "../../src/core/ngpc_types.h"
#include "../../src/core/ngpc_hw.h"
#include "ngpc_dialog/ngpc_font.h"

/* Return values from ngpc_dialog_update(). */
#define DIALOG_RUNNING   0
#define DIALOG_DONE      1
#define DIALOG_CHOICE_0  2
#define DIALOG_CHOICE_1  3

/* Tunable: frames between each character reveal (typewriter speed). */
#ifndef DIALOG_TEXT_SPEED
#define DIALOG_TEXT_SPEED   2
#endif

/* Tunable: frames per blink half-period for the continue arrow. */
#ifndef DIALOG_BLINK_PERIOD
#define DIALOG_BLINK_PERIOD 30
#endif

/* Tunable: max visible text rows inside the box (excluding speaker row). */
#ifndef DIALOG_MAX_LINES
#define DIALOG_MAX_LINES    3
#endif

/* Tunable: maximum number of choices. */
#ifndef DIALOG_MAX_CHOICES
#define DIALOG_MAX_CHOICES  2
#endif

/* OAM slot reserved for the portrait sprite (0-63). */
#ifndef DIALOG_PORTRAIT_SLOT
#define DIALOG_PORTRAIT_SLOT 63u
#endif

/* Speaker string encoding: "\001Name\002Body" */
#define DIALOG_SPEAKER_BEGIN_CHAR '\001'
#define DIALOG_SPEAKER_END_CHAR   '\002'
#define DIALOG_SPEAKER_BEGIN_STR  "\001"
#define DIALOG_SPEAKER_END_STR    "\002"

/* Internal flags. */
#define _DLG_HAS_CHOICES  0x01u
#define _DLG_TEXT_DONE    0x02u
#define _DLG_OPEN         0x04u
#define _DLG_HAS_PORTRAIT 0x08u

typedef struct {
    const char  *text;          /* Points into body text (after speaker end marker). */
    const char  *speaker;       /* Points into speaker name (or NULL). */
    const char **choices;       /* Array of choice strings (or NULL). */

    u8  bx, by;                 /* Box origin in tile coordinates (screen-space, SCR2). */
    u8  bw, bh;                 /* Box width/height in tiles. */
    u8  pal;                    /* Palette index for text. */

    u8  char_idx;               /* Typewriter: index of next char to reveal. */
    u8  page_start;             /* First char index of current page. */
    u8  page_end;               /* First char index past current page. */
    u8  tick;                   /* Typewriter tick counter. */
    u8  blink;                  /* Blink counter for continue arrow. */
    u8  cursor;                 /* Choice cursor position. */
    u8  n_choices;              /* Number of active choices. */

    u16 portrait_tile;          /* Tile index for portrait sprite (0 = none). */
    u16 frame_tile_base;        /* Tile base for sprite-based frame (0 = char fallback). */
    u8  frame_pal;              /* SCR2 palette slot for the frame tiles. */

    u8  saved_scr2_x;           /* SCR2 scroll saved at open, restored at close. */
    u8  saved_scr2_y;

    u8  flags;                  /* Internal flags (_DLG_*). */
} NgpcDialog;

/*
 * Open the dialogue box.
 *   bx, by           : top-left tile position on screen (SCR2 coordinates).
 *   bw, bh           : box dimensions in tiles.
 *   pal              : palette index for text (0-15).
 *   portrait_tile    : tile index for portrait sprite, 0 = no portrait.
 *   frame_tile_base  : base tile index of the 4-tile sprite frame set
 *                      (TL corner, H-border, fill, V-border). Pass 0 for
 *                      the ASCII character fallback.
 *   frame_pal        : SCR2 palette slot for frame tiles (ignored when 0).
 *
 * Saves SCR2 scroll and resets it to (0,0).
 * Draws the box frame on SCR2.
 */
void ngpc_dialog_open(NgpcDialog *d,
                      u8 bx, u8 by, u8 bw, u8 bh,
                      u8 pal, u16 portrait_tile,
                      u16 frame_tile_base, u8 frame_pal);

/*
 * Close the box.
 * Clears the box area on SCR2, restores SCR2 scroll,
 * hides portrait sprite if any.
 */
void ngpc_dialog_close(NgpcDialog *d);

/*
 * Set the text to display.
 *
 * Plain text:   "Hello world"
 * With speaker: "\001Alice\002Hello world"
 *
 * Word-wrap is applied automatically. Use '\n' for explicit breaks.
 */
void ngpc_dialog_set_text(NgpcDialog *d, const char *text);

/* Set choices shown after text is fully revealed. */
void ngpc_dialog_set_choices(NgpcDialog *d, const char **choices, u8 count);

/*
 * Update the box once per frame.
 * Call this every frame while the box is open.
 * Returns DIALOG_RUNNING, DIALOG_DONE, DIALOG_CHOICE_0, or DIALOG_CHOICE_1.
 */
u8 ngpc_dialog_update(NgpcDialog *d);

/* Returns 1 if the box is currently open. */
#define ngpc_dialog_is_open(d)  ((d)->flags & _DLG_OPEN)

#endif /* NGPC_DIALOG_H */
