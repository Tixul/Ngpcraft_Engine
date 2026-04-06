#include "ngpc_room.h"

void ngpc_room_init(NgpcRoom *r, u8 phase_frames)
{
    r->state     = ROOM_IDLE;
    r->next_room = 0;
    r->timer     = 0;
    r->duration  = phase_frames ? phase_frames : 1;
}

void ngpc_room_go(NgpcRoom *r, u8 next_room)
{
    if (r->state != ROOM_IDLE) return;
    r->next_room = next_room;
    r->timer     = r->duration;
    r->state     = ROOM_FADE_OUT;
}

void ngpc_room_loaded(NgpcRoom *r)
{
    if (r->state != ROOM_LOAD) return;
    r->timer = r->duration;
    r->state = ROOM_FADE_IN;
}

u8 ngpc_room_update(NgpcRoom *r)
{
    switch (r->state) {
        case ROOM_IDLE:
            return ROOM_IDLE;

        case ROOM_FADE_OUT:
            if (r->timer > 0) r->timer--;
            if (r->timer == 0) {
                r->state = ROOM_LOAD;
                return ROOM_LOAD;
            }
            return ROOM_FADE_OUT;

        case ROOM_LOAD:
            /* Attendre ngpc_room_loaded() */
            return ROOM_LOAD;

        case ROOM_FADE_IN:
            if (r->timer > 0) r->timer--;
            if (r->timer == 0) {
                r->state = ROOM_DONE;
            }
            return ROOM_FADE_IN;

        case ROOM_DONE:
            r->state = ROOM_IDLE;
            return ROOM_DONE;

        default:
            return ROOM_IDLE;
    }
}

u8 ngpc_room_progress(const NgpcRoom *r)
{
    u8 elapsed;
    if (r->duration == 0) return 255;
    elapsed = (u8)(r->duration - r->timer);
    /* Retourne [0..255] proportionnel à elapsed / duration */
    return (u8)(((u16)elapsed * 255u) / (u16)r->duration);
}
