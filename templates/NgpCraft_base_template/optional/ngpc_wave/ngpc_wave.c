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

    /* Poll d'abord avec le timer courant : supporte delay=0 qui doit fire
     * dès la première frame (timer=0). Puis incrémente une fois par appel
     * d'update (= une fois par frame). Le poll dans la boucle d'appel
     * (ngpc_wave_poll) lit ce timer sans le ré-incrémenter, donc tous les
     * entries simultanés à un même delay firent dans la même frame.
     *
     * Ancien gating "if (next>0 || timer>0) inc" était cassé : timer et
     * next restaient bloqués à 0, donc timer ne montait jamais et aucune
     * wave de delay>0 ne firait jamais. */
    e = _wave_poll_internal(seq);
    if (seq->timer < 0xFFFFu) seq->timer++;
    return e;
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
