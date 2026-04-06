#include "ngpc_seq.h"
#include "sounds.h"   /* Sfx_PlayToneCh, Sfx_PlayNoise, NOTE_TABLE, NOTE_MAX_INDEX */

/* ── État interne : 1 slot par canal ───────────────────────────────────── */

typedef struct {
    const NgpcSeqNote *table;  /* NULL = inactif */
    u8  pos;                   /* index courant dans la table */
    u8  timer;                 /* frames restantes sur la note courante */
    u8  done;                  /* 1 = séquence terminée (dur=0 atteint) */
} NgpcSeqState;

static NgpcSeqState s_ch[4];

/* ── Helpers internes ──────────────────────────────────────────────────── */

/* Convertit un index de note (1..50) en diviseur 10-bit T6W28.
 * Utilise NOTE_TABLE (2 octets par note : nibble bas + octet haut).
 * note=0 → silence (divider=1, attn forcé à 15). */
static u16 seq_note_to_div(u8 note)
{
    u8 idx;
    if (!NOTE_TABLE || note == 0 || note > NOTE_MAX_INDEX) return 1u;
    idx = (u8)(note - 1u);
    return (u16)(((u16)(NOTE_TABLE[idx * 2u + 1u] & 0x3Fu) << 4) |
                  (u16) (NOTE_TABLE[idx * 2u + 0u] & 0x0Fu));
}

/* Émet la note courante sur le canal hardware. */
static void seq_emit(u8 ch, u8 note, u8 attn)
{
    if (ch < 3u) {
        u16 div = seq_note_to_div(note);
        u8  vol = (note == 0u) ? 15u : attn;  /* silence = attn max */
        Sfx_PlayToneCh(ch, div, vol, 0u);
    } else {
        /* Canal bruit : note 1..7 = rate (bit rate T6W28), 0 = silence */
        u8 rate = (note == 0u || note > 7u) ? 3u : note;
        u8 vol  = (note == 0u) ? 15u : attn;
        Sfx_PlayNoise(rate, vol, 0u);
    }
}

/* ── API publique ──────────────────────────────────────────────────────── */

void ngpc_seq_play(u8 ch, const NgpcSeqNote *seq)
{
    NgpcSeqState *st;
    if (ch > 3u || !seq) return;
    st = &s_ch[ch];
    st->table = seq;
    st->pos   = 0u;
    st->done  = 0u;
    st->timer = seq[0].dur;
    if (st->timer == 0u) {
        /* Première note dur=0 : séquence vide, on arrête immédiatement. */
        st->done  = 1u;
        st->table = 0;
        return;
    }
    seq_emit(ch, seq[0].note, seq[0].attn);
}

void ngpc_seq_update(void)
{
    u8 ch;
    for (ch = 0u; ch < 4u; ++ch) {
        NgpcSeqState *st = &s_ch[ch];
        NgpcSeqNote cur;
        if (!st->table || st->done) continue;
        if (st->timer > 1u) { --st->timer; continue; }
        /* Avancer à la note suivante. */
        ++st->pos;
        cur = st->table[st->pos];
        if (cur.dur == 0xFFu) {
            /* Boucle : retour au début. */
            st->pos  = 0u;
            cur      = st->table[0];
        }
        if (cur.dur == 0u) {
            /* Fin de séquence. */
            seq_emit(ch, 0u, 15u);  /* silence */
            st->done  = 1u;
            st->table = 0;
            continue;
        }
        st->timer = cur.dur;
        seq_emit(ch, cur.note, cur.attn);
    }
}

void ngpc_seq_stop(u8 ch)
{
    if (ch > 3u) return;
    s_ch[ch].table = 0;
    s_ch[ch].done  = 0u;
    seq_emit(ch, 0u, 15u);
}

void ngpc_seq_stop_all(void)
{
    u8 ch;
    for (ch = 0u; ch < 4u; ++ch) ngpc_seq_stop(ch);
}

u8 ngpc_seq_is_done(u8 ch)
{
    if (ch > 3u) return 1u;
    return s_ch[ch].done;
}
