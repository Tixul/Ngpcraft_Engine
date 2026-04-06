/*
 * ngpc_timing.c - VSync synchronization and CPU speed
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 */

#include "ngpc_hw.h"
#include "ngpc_sys.h"
#include "ngpc_timing.h"
#if NGP_ENABLE_DEBUG && !NGP_PROFILE_RELEASE
#include "ngpc_vramq.h"
#include "ngpc_assert.h"
#endif

/* ---- Public API ---- */

void ngpc_vsync(void)
{
    static u8 s_power_hold = 0;

    /* Wait until g_vb_counter changes (incremented by VBI at 60 Hz).
     * This busy-waits but lets the CPU execute other code in the
     * interrupt handler between checks. */
    u8 prev = g_vb_counter;
    while (g_vb_counter == prev)
        ;

#if NGP_ENABLE_DEBUG && !NGP_PROFILE_RELEASE
    /* DBG-1: catch VRAMQ overflow — too many commands queued in one frame.
     * The assert fires once and halts (with file/line on screen) so you can
     * identify the offending frame. Raise VRAMQ_MAX_CMDS or reduce writes. */
    NGPC_ASSERT(ngpc_vramq_dropped() == 0);
    ngpc_vramq_clear_dropped();
#endif

    /* POWER button: BIOS requests shutdown by setting HW_USR_SHUTDOWN.
     * Calling the BIOS shutdown vector from a normal (non-ISR) context is
     * more robust on real hardware than doing it inside the VBlank ISR. */
    if (HW_USR_SHUTDOWN)
        ngpc_shutdown();

    /* Fallback: some setups expose POWER as a joypad bit (PAD_POWER) without
     * reliably latching HW_USR_SHUTDOWN. Support a "hold POWER" gesture. */
    if (HW_JOYPAD & PAD_POWER) {
        if (s_power_hold < 255) s_power_hold++;
        if (s_power_hold >= 30) {
            ngpc_shutdown();
        }
    } else {
        s_power_hold = 0;
    }
}

u8 ngpc_in_vblank(void)
{
    /* ngpcspec.txt: 0x8010 bit 6 = BLNK (0=displaying, 1=vblank). */
    return (HW_STATUS & STATUS_VBLANK) ? 1 : 0;
}

void ngpc_sleep(u8 frames)
{
    u8 i;

    /* Reduce CPU speed during sleep to save battery. */
    ngpc_cpu_speed(4);

    for (i = 0; i < frames; i++)
        ngpc_vsync();

    /* Restore full speed. */
    ngpc_cpu_speed(0);
}

void ngpc_cpu_speed(u8 divider)
{
    /* BIOS system call: VECT_CLOCKGEARSET.
     * ngpcspec.txt: CPU clock divider 0=6MHz, 1=3MHz, 2=1.5MHz, 3=768KHz, 4=384KHz.
     * Pass divider in RB3 and joypad-speedup flag in RC3. */
    (void)divider;
    __asm("ld rw3, " NGPC_STR(BIOS_CLOCKGEARSET));
    __asm("ld xde, (xsp+4)");    /* get divider argument */
    __asm("ld b, e");            /* RB3 = divider */
    __asm("ld c, 0");            /* RC3 = no auto speed-up on joypad */
    __asm("ldf 3");
    __asm("add w, w");
    __asm("add w, w");
    __asm("ld xix, 0xfffe00");
    __asm("ld xix, (xix+w)");
    __asm("call xix");
}
