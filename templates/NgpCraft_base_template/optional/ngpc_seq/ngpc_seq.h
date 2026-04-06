#ifndef NGPC_SEQ_H
#define NGPC_SEQ_H

/*
 * ngpc_seq -- Minimal PSG sequencer for Neo Geo Pocket Color
 * ===========================================================
 * Plays note tables on the 4 T6W28 PSG channels without Sound Creator
 * (no tracker data required).
 * Useful for: menu jingles, victory fanfares, simple gameplay tones,
 * NGPCraft projects (no custom Z80 driver).
 *
 * Dependency: sounds.h / sounds.c (Z80 SFX driver -- included in the
 * template) to access Sfx_PlayToneCh / Sfx_PlayNoise.
 * Sound_Update() must be called every VBL.
 *
 * --------------------------------------------------------------------------
 * Installation:
 *   Copy ngpc_seq/ into src/
 *   Add  OBJS += src/ngpc_seq/ngpc_seq.rel  to the Makefile
 *   #include "ngpc_seq/ngpc_seq.h"
 * --------------------------------------------------------------------------
 *
 * Sequence format:
 *   Array of NgpcSeqNote terminated by NGPC_SEQ_END or NGPC_SEQ_LOOP.
 *   { note, attn, dur }
 *     note : 0 = silence, 1..50 = pitch (index into NOTE_TABLE)
 *            channel 3 (noise): 1..7 = noise rate, 0 = silence
 *     attn : volume, 0 = loudest, 15 = silent (T6W28 attenuation)
 *     dur  : duration in VBL frames (1..254)
 *            0    -> end of sequence (non-looping)
 *            0xFF -> loop from the beginning
 *
 * Example:
 *   static const NgpcSeqNote s_jingle[] = {
 *       { 30, 0,  8 },   // C (8 frames)
 *       { 34, 0,  8 },   // E
 *       { 37, 0, 16 },   // G (held)
 *       NGPC_SEQ_END
 *   };
 *   ngpc_seq_play(0, s_jingle);   // channel 0
 *
 * In the main loop:
 *   Sound_Update();          // Z80 SFX driver
 *   ngpc_seq_update();       // advance sequences
 */

#include "ngpc_hw.h"  /* u8, s16 */

/* ── Note structure ──────────────────────────────────────────────────── */

typedef struct {
    u8 note;  /* 0=silence, 1..50=pitch (1..7 for noise channel) */
    u8 attn;  /* 0=loudest, 15=silent */
    u8 dur;   /* VBL frames; 0=end, 0xFF=loop */
} NgpcSeqNote;

/* Convenience sentinels to place at end of array */
#define NGPC_SEQ_END  { 0u, 15u, 0u   }
#define NGPC_SEQ_LOOP { 0u, 15u, 0xFFu }

/* ── API ──────────────────────────────────────────────────────────────────
 *
 * ngpc_seq_play(ch, seq)
 *   Start sequence seq on channel ch (0-2 = tone, 3 = noise).
 *   Plays the first note immediately.
 *
 * ngpc_seq_update()
 *   Call ONCE per VBL, after Sound_Update().
 *   Advances counters and triggers note changes.
 *
 * ngpc_seq_stop(ch)
 *   Silence the channel and stop the sequence.
 *
 * ngpc_seq_stop_all()
 *   Silence all 4 channels.
 *
 * ngpc_seq_is_done(ch)
 *   Returns 1 when the sequence has ended (dur=0 reached).
 *   Always 0 for looping sequences.
 */

void ngpc_seq_play(u8 ch, const NgpcSeqNote *seq);
void ngpc_seq_update(void);
void ngpc_seq_stop(u8 ch);
void ngpc_seq_stop_all(void);
u8   ngpc_seq_is_done(u8 ch);

#endif /* NGPC_SEQ_H */
