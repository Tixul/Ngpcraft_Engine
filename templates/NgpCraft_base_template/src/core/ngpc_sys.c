/*
 * ngpc_sys.c - System initialization, VBI handler, shutdown
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 */

#include "ngpc_hw.h"
#include "ngpc_sys.h"
#if NGP_ENABLE_DEBUG
#include "ngpc_log.h"
#endif
#include "ngpc_vramq.h"

/* ---- State ---- */

volatile u8 g_vb_counter = 0;
static u8 s_is_color = 0;
static u8 s_language = 0;

/* Linker symbols from ngpc.lcf (runtime init tables). */
extern const u8 _DataROM_START;
extern const u8 _DataROM_END;
extern u8 _DataRAM_START;
extern u8 _Bss_START;
extern u8 _Bss_END;

/* ---- C runtime bootstrap (replacement for system.lib init) ---- */

static void runtime_bootstrap(void)
{
    const u8 *src = &_DataROM_START;
    const u8 *src_end = &_DataROM_END;
    u8 *dst = &_DataRAM_START;
    u8 *bss = &_Bss_START;
    u8 *bss_end = &_Bss_END;

    /* Copy initialized data from ROM image to RAM runtime addresses. */
    while (src < src_end) {
        *dst++ = *src++;
    }

    /* Zero all BSS/data-area storage. */
    while (bss < bss_end) {
        *bss++ = 0;
    }
}

/* ---- Dummy interrupt handler (does nothing) ---- */

static void __interrupt isr_dummy(void) { }

/* ---- VBlank interrupt handler (mandatory, 60 Hz) ---- */
/*
 * From ngpcspec.txt:
 * - Watchdog must be cleared every ~100ms (VBL fires every ~16.7ms, so every frame is fine)
 * - USR_SHUTDOWN must be checked and shutdown called if set
 * - VBL interrupt (level 4) must never be disabled
 */

static void __interrupt isr_vblank(void)
{
    HW_WATCHDOG = WATCHDOG_CLEAR;
    /* Shutdown handling is performed in ngpc_vsync() (main context). */

    /* Execute queued VRAM writes during VBlank. */
    ngpc_vramq_flush();

    g_vb_counter++;
}

/* ---- Public API ---- */

void ngpc_init(void)
{
    /* Power-off bug patch for prototype firmware (no-op on retail hardware).
     * Must run before anything else, interrupts still disabled at this point. */
    ngpc_sys_patch();

    /* Initialize C globals in RAM (no external system.lib startup). */
    runtime_bootstrap();

    /* Detect mono vs color hardware.
     * ngpcspec.txt: "OS_Version" at 0x6F91, 0 = monochrome, != 0 = color. */
    s_is_color = (HW_OS_VERSION != 0) ? 1 : 0;

    /* Cache system language from BIOS register (0x6F87).
     * LANG_ENGLISH=0, LANG_JAPANESE=1. Set by BIOS at boot, read-only. */
    s_language = HW_LANGUAGE;

    /* Clear bit 5 of USR_ANSWER (reserved, must be 0 per spec checklist). */
    HW_USR_ANSWER &= ~(1 << 5);
    /* Compatibility with classic NGPC init code:
     * many templates set USR_ANSWER bit 6 early. */
    HW_USR_ANSWER |= 0x40;

#if NGP_ENABLE_DEBUG
    /* Reset debug log ring buffer. */
    ngpc_log_init();
#endif

    /* Reset queued VRAM update system. */
    ngpc_vramq_init();

    /* Install interrupt vectors.
     * ngpcspec.txt: vectors at 0x6FB8-0x6FFC, 32-bit pointers.
     * VBL at 0x6FCC is mandatory. All others set to dummy. */
    HW_INT_SWI3   = isr_dummy;
    HW_INT_SWI4   = isr_dummy;
    HW_INT_SWI5   = isr_dummy;
    HW_INT_SWI6   = isr_dummy;
    HW_INT_RTC    = isr_dummy;
    HW_INT_VBL    = isr_vblank;
    HW_INT_Z80    = isr_dummy;
    HW_INT_TIM0   = isr_dummy;
    HW_INT_TIM1   = isr_dummy;
    HW_INT_TIM2   = isr_dummy;
    HW_INT_TIM3   = isr_dummy;
    HW_INT_SER_TX = isr_dummy;
    HW_INT_SER_RX = isr_dummy;
    HW_INT_DMA0   = isr_dummy;
    HW_INT_DMA1   = isr_dummy;
    HW_INT_DMA2   = isr_dummy;
    HW_INT_DMA3   = isr_dummy;

    /* Set viewport to full screen (160x152).
     * ngpcspec.txt: window is minimized at startup, user must set it.
     * Constraint: origin + size <= 160 (H) / 152 (V). */
    HW_WIN_X = 0;
    HW_WIN_Y = 0;
    HW_WIN_W = SCREEN_W;
    HW_WIN_H = SCREEN_H;

    /* Force a known video state.
     * Some emulators/BIOS paths may leave non-zero scroll/priority state. */
    HW_SCR1_OFS_X = 0;
    HW_SCR1_OFS_Y = 0;
    HW_SCR2_OFS_X = 0;
    HW_SCR2_OFS_Y = 0;
    /* Do not clobber unknown bits in this register; only force plane priority.
     * Many classic NGPC codebases only touch bit 7. */
    HW_SCR_PRIO &= (u8)~0x80;   /* bit7=0 => SCR1 in front, SCR2 behind */
    HW_SPR_OFS_X = 0;
    HW_SPR_OFS_Y = 0;
    HW_LCD_CTL &= (u8)~0x80; /* ensure LCD is not inverted */

    /* Clear tile 0 pixel data so ngpc_gfx_clear() gives truly transparent tiles.
     * The BIOS boot screen may leave visible pixels in tile 0; scroll maps
     * cleared with ngpc_gfx_clear() point to tile 0, palette 0, and any
     * non-zero pixel data would show through as visual artifacts. */
    {
        u8 w;
        for (w = 0; w < TILE_WORDS; w++)
            HW_TILE_DATA[w] = 0;
    }

    /* Enable interrupts.
     * ngpcspec.txt: "software starts up with interrupts prohibited (DI)." */
    INTERRUPTS_ON;
}

u8 ngpc_is_color(void)
{
    return s_is_color;
}

u8 ngpc_get_language(void)
{
    return s_language;
}

void ngpc_shutdown(void)
{
    /* BIOS system call: VECT_SHUTDOWN.
     * ngpcspec.txt: use system call for shutdown.
     * rw3 = vector number, ra3 = function code 3. */
    __asm("ldb ra3, 3");
    __asm("ldb rw3, " NGPC_STR(BIOS_SHUTDOWN));
    __asm("swi 1");
}

void ngpc_load_sysfont(void)
{
    /* BIOS system call: VECT_SYSFONTSET.
     * Loads built-in font characters into tile RAM. */
    __asm("ldb ra3, 3");
    __asm("ldb rw3, " NGPC_STR(BIOS_SYSFONTSET));
    __asm("swi 1");
}

void ngpc_memcpy(u8 *dst, const u8 *src, u16 len)
{
    while (len--)
        *dst++ = *src++;
}

void ngpc_memset(u8 *dst, u8 val, u16 len)
{
    while (len--)
        *dst++ = val;
}

