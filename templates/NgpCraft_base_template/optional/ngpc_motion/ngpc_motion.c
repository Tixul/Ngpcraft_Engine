#include "ngpc_motion.h"

/* ── Constantes internes ─────────────────────────────────────────────── */

#define _BUF_MASK   (NGPC_MOTION_BUF_SIZE - 1u)  /* wrap circulaire rapide */

/* Bits D-pad dans ngpc_pad_held (ngpc_input.h) */
#define _PAD_UP    0x01
#define _PAD_DOWN  0x02
#define _PAD_LEFT  0x04
#define _PAD_RIGHT 0x08
/* Bits boutons dans ngpc_pad_pressed */
#define _PAD_A     0x10
#define _PAD_B     0x20
#define _PAD_OPT   0x40

/* ── Helpers privés ──────────────────────────────────────────────────── */

/* Encode la direction D-pad en nibble haut.
 * Diagonales testées en premier pour ne pas masquer avec un cardinal. */
static u8 _dir_from_pad(u8 pad) {
    u8 up    = (pad & _PAD_UP)    ? 1u : 0u;
    u8 down  = (pad & _PAD_DOWN)  ? 1u : 0u;
    u8 left  = (pad & _PAD_LEFT)  ? 1u : 0u;
    u8 right = (pad & _PAD_RIGHT) ? 1u : 0u;

    if (up   && right) return MDIR_UR;
    if (up   && left)  return MDIR_UL;
    if (down && right) return MDIR_DR;
    if (down && left)  return MDIR_DL;
    if (up)            return MDIR_U;
    if (down)          return MDIR_D;
    if (left)          return MDIR_L;
    if (right)         return MDIR_R;
    return MDIR_N;
}

/* Encode les boutons pressés (rising edge) en nibble bas.
 * Seul le front montant (pad_pressed) est enregistré — évite les re-triggers. */
static u8 _btn_from_pressed(u8 pressed) {
    u8 b = 0u;
    if (pressed & _PAD_A)   b |= MBTN_A;
    if (pressed & _PAD_B)   b |= MBTN_B;
    if (pressed & _PAD_OPT) b |= MBTN_OPT;
    return b;
}

/* Teste si un frame du buffer correspond à un step du pattern.
 *   frame : octet lu dans le buffer (dir|btn)
 *   step  : octet lu depuis la ROM pattern (dir|btn)
 * La direction MDIR_ANY matche toute valeur de nibble haut. */
static u8 _step_match(u8 frame, u8 step) {
    u8 step_dir = step & MDIR_MASK;
    u8 step_btn = step & MBTN_MASK;
    u8 frm_dir  = frame & MDIR_MASK;
    u8 frm_btn  = frame & MBTN_MASK;

    /* Direction */
    if (step_dir != MDIR_ANY && step_dir != frm_dir) return 0u;
    /* Boutons : tous les bits requis par le step doivent être présents */
    if ((frm_btn & step_btn) != step_btn) return 0u;
    return 1u;
}

/* ── API publique ────────────────────────────────────────────────────── */

void ngpc_motion_init(NgpcMotionBuf *buf) {
    u8 i;
    for (i = 0u; i < NGPC_MOTION_BUF_SIZE; i++) {
        buf->frames[i] = 0u;
    }
    buf->head  = 0u;
    buf->count = 0u;
}

void ngpc_motion_push(NgpcMotionBuf *buf, u8 pad_held, u8 pad_pressed) {
    u8 dir = _dir_from_pad(pad_held);
    u8 btn = _btn_from_pressed(pad_pressed);

    buf->head = (u8)((buf->head + 1u) & _BUF_MASK);
    buf->frames[buf->head] = (u8)(dir | btn);

    if (buf->count < NGPC_MOTION_BUF_SIZE) {
        buf->count++;
    }
}

u8 ngpc_motion_test(const NgpcMotionBuf *buf,
                    const NgpcMotionPattern NGP_FAR *pat) {
    u8 window;
    u8 step_idx;    /* index courant dans pat->steps (part de count-1 = dernier step) */
    u8 buf_pos;     /* position courante dans le buffer (remonte depuis head) */
    u8 age;         /* nombre de frames depuis head */
    u8 frame;
    u8 step;
    u8 found;

    if (!pat || pat->count == 0u) return 0u;
    if (buf->count == 0u) return 0u;

    window = (pat->window > 0u) ? pat->window : NGPC_MOTION_BUF_SIZE;

    /* ── Étape 1 : trouver le DERNIER step dans la FINAL_WINDOW ─────── */
    step_idx = pat->count - 1u;   /* index du dernier step dans le tableau */
    step = pat->steps[step_idx];

    found = 0u;
    buf_pos = buf->head;
    for (age = 0u; age < NGPC_MOTION_FINAL_WINDOW; age++) {
        if (age >= buf->count) break;
        frame = buf->frames[buf_pos];
        if (_step_match(frame, step)) {
            found = 1u;
            break;
        }
        buf_pos = (u8)((buf_pos - 1u) & _BUF_MASK);
    }
    if (!found) return 0u;
    if (step_idx == 0u) return 1u;   /* pattern à 1 step — terminé */

    /* buf_pos pointe sur le frame qui a matché le dernier step.
     * Remonter d'une position de plus pour chercher les steps précédents. */
    buf_pos = (u8)((buf_pos - 1u) & _BUF_MASK);
    age++;

    /* ── Étape 2 : trouver les steps précédents en remontant ──────────
     * Les frames neutres (MDIR_N, MBTN_NONE) sont ignorés (skippés).
     * On reste dans la fenêtre totale "window". */
    step_idx--;

    while (age < window) {
        if (age >= buf->count) break;

        frame = buf->frames[buf_pos];
        step  = pat->steps[step_idx];

        if (_step_match(frame, step)) {
            if (step_idx == 0u) {
                return 1u;   /* tous les steps trouvés */
            }
            step_idx--;
        }
        /* Frames neutres : on avance sans décrémenter step_idx */

        buf_pos = (u8)((buf_pos - 1u) & _BUF_MASK);
        age++;
    }

    return 0u;
}

u8 ngpc_motion_scan(const NgpcMotionBuf *buf,
                    const NgpcMotionPattern NGP_FAR *pats, u8 count) {
    u8 i;
    for (i = 0u; i < count; i++) {
        if (ngpc_motion_test(buf, &pats[i])) {
            return i;
        }
    }
    return 0xFFu;
}

void ngpc_motion_clear(NgpcMotionBuf *buf) {
    ngpc_motion_init(buf);
}
