#include "ngpc_wave.h"

void ngpc_wave_start(NgpcWaveSeq *seq,
                     const NgpcWaveEntry *entries, u8 count)
{
    seq->entries = entries;
    seq->count   = count;
    seq->timer   = 0;
    seq->next    = 0;
    seq->flags   = (count > 0) ? WAVE_FLAG_ACTIVE : WAVE_FLAG_DONE;
}

void ngpc_wave_stop(NgpcWaveSeq *seq)
{
    seq->flags = 0;
    seq->timer = 0;
    seq->next  = 0;
}

/* Retourne un pointeur si un spawn est dû au timer courant. */
static const NgpcWaveEntry *_wave_poll_internal(NgpcWaveSeq *seq)
{
    const NgpcWaveEntry *e;

    if (!(seq->flags & WAVE_FLAG_ACTIVE)) return 0;
    if (seq->next >= seq->count) {
        seq->flags = (u8)((seq->flags & ~WAVE_FLAG_ACTIVE) | WAVE_FLAG_DONE);
        return 0;
    }

    e = &seq->entries[seq->next];

    /* Vérification sentinel */
    if (e->delay == WAVE_END) {
        seq->flags = (u8)((seq->flags & ~WAVE_FLAG_ACTIVE) | WAVE_FLAG_DONE);
        return 0;
    }

    if (seq->timer >= e->delay) {
        seq->next++;
        return e;
    }
    return 0;
}

const NgpcWaveEntry *ngpc_wave_update(NgpcWaveSeq *seq)
{
    const NgpcWaveEntry *e;

    if (!(seq->flags & WAVE_FLAG_ACTIVE)) return 0;

    /* Avancer le timer UNE fois par frame (premier appel de la boucle)
     * On distingue : si next == 0 ET timer == 0, c'est le premier frame,
     * on ne fait pas d'incrément avant le premier poll. */
    if (seq->next > 0 || seq->timer > 0) {
        if (seq->timer < 0xFFFFu) seq->timer++;
    }

    e = _wave_poll_internal(seq);
    if (e) return e;

    /* Premier frame (timer=0, next=0) : vérifier quand même */
    if (seq->timer == 0 && seq->next == 0)
        return _wave_poll_internal(seq);

    return 0;
}

void ngpc_wave_tick(NgpcWaveSeq *seq)
{
    if (!(seq->flags & WAVE_FLAG_ACTIVE)) return;
    if (seq->timer < 0xFFFFu) seq->timer++;
}

const NgpcWaveEntry *ngpc_wave_poll(NgpcWaveSeq *seq)
{
    return _wave_poll_internal(seq);
}
