/*
 * object_pool_example.c - Fixed-size object pool pattern (no malloc)
 *
 * This file is documentation-by-example and is not compiled by default.
 * Copy/adapt it to your game module.
 */

#include "../src/ngpc_types.h"

typedef struct Bullet {
    s16 x;
    s16 y;
    s8 vx;
    s8 vy;
} Bullet;

#define MAX_BULLETS 16

static Bullet s_bullets[MAX_BULLETS];
static u16 s_active_mask = 0;

void bullet_pool_reset(void)
{
    u8 i;
    s_active_mask = 0;
    for (i = 0; i < MAX_BULLETS; ++i) {
        s_bullets[i].x = 0;
        s_bullets[i].y = 0;
        s_bullets[i].vx = 0;
        s_bullets[i].vy = 0;
    }
}

u8 bullet_pool_alloc(void)
{
    u8 i;
    u16 bit;

    bit = 1;
    for (i = 0; i < MAX_BULLETS; ++i) {
        if ((s_active_mask & bit) == 0) {
            s_active_mask |= bit;
            return i;
        }
        bit <<= 1;
    }
    return 0xFF; /* no free slot */
}

void bullet_pool_free(u8 idx)
{
    if (idx >= MAX_BULLETS) {
        return;
    }
    s_active_mask &= (u16)~((u16)1 << idx);
}

void bullet_spawn(s16 x, s16 y, s8 vx, s8 vy)
{
    u8 idx;

    idx = bullet_pool_alloc();
    if (idx == 0xFF) {
        return;
    }

    s_bullets[idx].x = x;
    s_bullets[idx].y = y;
    s_bullets[idx].vx = vx;
    s_bullets[idx].vy = vy;
}

void bullet_update_all(void)
{
    u8 i;
    u16 bit;

    bit = 1;
    for (i = 0; i < MAX_BULLETS; ++i) {
        if ((s_active_mask & bit) != 0) {
            s_bullets[i].x += s_bullets[i].vx;
            s_bullets[i].y += s_bullets[i].vy;

            if (s_bullets[i].x < -8 || s_bullets[i].x > 167 ||
                s_bullets[i].y < -8 || s_bullets[i].y > 159) {
                bullet_pool_free(i);
            }
        }
        bit <<= 1;
    }
}
