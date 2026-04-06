/*
 * ngpc_hw.h - Neo Geo Pocket Color hardware register definitions
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from scratch using the public NGPC hardware specification
 * (ngpcspec.txt by NeeGee, 2000). All values are hardware facts.
 *
 * TLCS-900/H main CPU, Z80 sound CPU, K2GE graphics engine, T6W28 PSG.
 */

#ifndef NGPC_HW_H
#define NGPC_HW_H

#include "ngpc_types.h"

/* ======================================================================
 * CPU CONTROL & TIMERS (Internal I/O)
 * Source: ngpcspec.txt "Internal I/O" + TLCS-900/H datasheet
 * ====================================================================== */

#define HW_TRUN         (*(volatile u8  *)0x0020)   /* Timer run control      */
#define HW_TREG0        (*(volatile u8  *)0x0022)   /* 8-bit timer register 0 */
#define HW_TREG1        (*(volatile u8  *)0x0023)   /* 8-bit timer register 1 */
#define HW_T01MOD       (*(volatile u8  *)0x0024)   /* Timer 0/1 mode control */
#define HW_TFFCR        (*(volatile u8  *)0x0025)   /* Timer flip-flop control */
#define HW_TREG2        (*(volatile u8  *)0x0026)   /* PWM0 timer register    */
#define HW_TREG3        (*(volatile u8  *)0x0027)   /* PWM1 timer register    */
#define HW_T23MOD       (*(volatile u8  *)0x0028)   /* Timer 2/3 mode control */
#define HW_TRDC         (*(volatile u8  *)0x0029)   /* Timer double buffer control */

/* DOC-TIM — Timer allocation table (NgpCraft_base_template)
 *
 *  Timer | Owner           | Notes
 *  ------+-----------------+-------------------------------------------
 *    0   | HBlank / raster | Used by ngpc_raster_chain for scanline DMA.
 *          (1 owner max)     Free if raster FX not active.
 *    1   | FREE            | Available for game code (e.g. ngpc_timer).
 *    2   | FREE            | Available for game code.
 *    3   | Z80 sound CPU   | RESERVED — drives Z80 IM1 interrupt at
 *          DO NOT TOUCH      ~7.8 kHz for T6W28 driver. Writing HW_T23MOD
 *                            bits[7:4] or HW_TRUN bit3 will break audio. */

/* Micro DMA request/start vector registers (TLCS-900/H I/O). */
#define HW_DMA0V        (*(volatile u8  *)0x007C)   /* DMA0 start vector      */
#define HW_DMA1V        (*(volatile u8  *)0x007D)   /* DMA1 start vector      */
#define HW_DMA2V        (*(volatile u8  *)0x007E)   /* DMA2 start vector      */
#define HW_DMA3V        (*(volatile u8  *)0x007F)   /* DMA3 start vector      */

/* DMA-SAFE-1 — Stop all micro-DMA channels before VBlank work.
 *
 * Pattern confirmed on hardware (Ganbare Neo Poke-kun analysis):
 * if a raster/HBlank DMA is still pending when VBlank ISR fires, it can
 * interleave with the ISR's VRAM writes and corrupt tile data.
 *
 * Usage — call at the TOP of any code that touches VRAM during VBlank,
 * before ngpc_vramq_flush() or any direct VRAM write, then re-arm:
 *
 *   HW_DMA_STOP_ALL;          // disable all DMA channels
 *   ... VRAM writes ...
 *   HW_DMA0V = MY_DMA0_VEC;   // re-arm whichever channels were active
 *
 * Note: HW_DMAn == 0 disarms that channel (no transfer triggered). */
#define HW_DMA_STOP_ALL  do { \
    HW_DMA0V = 0; HW_DMA1V = 0; HW_DMA2V = 0; HW_DMA3V = 0; \
} while (0)

/* MicroDMA end-of-transfer interrupts (INTTCn) enable/level registers.
 * Source: TLCS-900/H IO900H.H (INTETC01=0x79, INTETC23=0x7A). */
#define HW_INTETC01     (*(volatile u8  *)0x0079)   /* INTTC0/1 enable+level  */
#define HW_INTETC23     (*(volatile u8  *)0x007A)   /* INTTC2/3 enable+level  */

/* Watchdog: must write 0x4E at least every ~100ms or CPU resets.
 * Source: ngpcspec.txt "Watch Dog Timer"
 *
 * VBlank fires every ~16.7ms so kicking in isr_vblank() covers all normal
 * game loops automatically. The only risk is a long INIT loop that runs
 * before the first VBlank (tile upload, map clear, decompression…).
 *
 * Pattern for long init loops (kick every ~64 iterations to stay well
 * under the 100ms budget at 6.144 MHz):
 *
 *   u16 _wdog = 0;
 *   while (...) {
 *       ... work ...
 *       if ((++_wdog & 63u) == 0u) HW_WATCHDOG = WATCHDOG_CLEAR;
 *   }
 *
 * Reference: Metal Slug 1st Mission (disassembly §4.2 / §17.3). */
#define HW_WATCHDOG     (*(volatile u8  *)0x006F)
#define WATCHDOG_CLEAR  0x4E

/* ======================================================================
 * SOUND CPU (Z80) CONTROL
 * Source: ngpcspec.txt "SOUND CONTROL CPU"
 * Z80 runs at 3.072 MHz, has 4KB RAM accessible from main CPU.
 * ====================================================================== */

#define HW_SOUNDCPU_CTRL (*(volatile u16 *)0x00B8)  /* Z80 control register   */
#define Z80_STOP         0xAAAA                      /* Write to halt Z80      */
#define Z80_START        0x5555                      /* Write to start Z80     */

#define HW_Z80_NMI      (*(volatile u8  *)0x00BA)   /* Trigger Z80 NMI        */
#define HW_Z80_COMM     (*(volatile u8  *)0x00BC)   /* CPU <-> Z80 comm byte  */

/* Z80 shared RAM: 4KB at 0x7000-0x7FFF (main CPU view)
 * Z80 sees the same memory at 0x0000-0x0FFF.
 * Z80 sound chip ports: 0x4000 (right), 0x4001 (left) */
#define HW_Z80_RAM      ((volatile u8  *)0x7000)

/* ======================================================================
 * SYSTEM INFORMATION (RAM area, set by BIOS)
 * Source: ngpcspec.txt "System Information"
 * ====================================================================== */

#define HW_BAT_VOLT_RAW (*(volatile u16 *)0x6F80)   /* Battery voltage raw (likely 10-bit ADC, low bits used) */
#define HW_BAT_VOLT     ((u16)(HW_BAT_VOLT_RAW & 0x03FFu)) /* 0..1023 (masked) */
#define HW_JOYPAD       (*(volatile u8  *)0x6F82)   /* Joypad input state     */
#define HW_USR_BOOT     (*(volatile u8  *)0x6F84)   /* Boot status (0=power,1=resume,2=alarm) */
#define HW_USR_SHUTDOWN  (*(volatile u8  *)0x6F85)   /* Shutdown request flag  */
#define HW_USR_ANSWER   (*(volatile u8  *)0x6F86)   /* User response flags    */
#define HW_LANGUAGE     (*(volatile u8  *)0x6F87)   /* System language        */
#define LANG_ENGLISH    0u                           /* HW_LANGUAGE == 0 */
#define LANG_JAPANESE   1u                           /* HW_LANGUAGE == 1 */
#define HW_OS_VERSION   (*(volatile u8  *)0x6F91)   /* 0=monochrome, !=0=color */

/* Joypad bit masks
 * Source: ngpcspec.txt "Sys Lever" register at 0x6F82 */
#define PAD_UP          0x01
#define PAD_DOWN        0x02
#define PAD_LEFT        0x04
#define PAD_RIGHT       0x08
#define PAD_A           0x10
#define PAD_B           0x20
#define PAD_OPTION      0x40
#define PAD_POWER       0x80

/* ======================================================================
 * INTERRUPT VECTORS (stored in RAM, set by user program)
 * Source: ngpcspec.txt "User Program Interrupt Vectors"
 * Each vector is a 32-bit pointer to an interrupt handler.
 * VBL interrupt (0x6FCC) is MANDATORY and must not be disabled.
 * ====================================================================== */

#define HW_INT_SWI3     (*(IntHandler **)0x6FB8)    /* Software interrupt 3   */
#define HW_INT_SWI4     (*(IntHandler **)0x6FBC)    /* Software interrupt 4   */
#define HW_INT_SWI5     (*(IntHandler **)0x6FC0)    /* Software interrupt 5   */
#define HW_INT_SWI6     (*(IntHandler **)0x6FC4)    /* Software interrupt 6   */
#define HW_INT_RTC      (*(IntHandler **)0x6FC8)    /* RTC alarm interrupt    */
#define HW_INT_VBL      (*(IntHandler **)0x6FCC)    /* Vertical blank (60 Hz) */
#define HW_INT_Z80      (*(IntHandler **)0x6FD0)    /* Z80 interrupt request  */
#define HW_INT_TIM0     (*(IntHandler **)0x6FD4)    /* Timer 0 (H-blank)      */
#define HW_INT_TIM1     (*(IntHandler **)0x6FD8)    /* Timer 1                */
#define HW_INT_TIM2     (*(IntHandler **)0x6FDC)    /* Timer 2                */
#define HW_INT_TIM3     (*(IntHandler **)0x6FE0)    /* Timer 3 (sound clock)  */
#define HW_INT_SER_TX   (*(IntHandler **)0x6FE4)    /* Serial TX (reserved)   */
#define HW_INT_SER_RX   (*(IntHandler **)0x6FE8)    /* Serial RX (reserved)   */
#define HW_INT_DMA0     (*(IntHandler **)0x6FF0)    /* Micro DMA 0 complete   */
#define HW_INT_DMA1     (*(IntHandler **)0x6FF4)    /* Micro DMA 1 complete   */
#define HW_INT_DMA2     (*(IntHandler **)0x6FF8)    /* Micro DMA 2 complete   */
#define HW_INT_DMA3     (*(IntHandler **)0x6FFC)    /* Micro DMA 3 complete   */

/* Enable interrupts (TLCS-900/H instruction) */
#define INTERRUPTS_ON   __asm("ei")

/* ======================================================================
 * VIDEO REGISTERS (K2GE Graphics Engine)
 * Source: ngpcspec.txt "Window Registers", "2D Status/Control", etc.
 * ====================================================================== */

/* Display control */
#define HW_DISP_CTL     (*(volatile u8  *)0x8000)   /* Display enable         */

/* Window (viewport) definition
 * Constraint: WBA.H + WSI.H <= 160, WBA.V + WSI.V <= 152 */
#define HW_WIN_X        (*(volatile u8  *)0x8002)   /* Window origin X        */
#define HW_WIN_Y        (*(volatile u8  *)0x8003)   /* Window origin Y        */
#define HW_WIN_W        (*(volatile u8  *)0x8004)   /* Window width           */
#define HW_WIN_H        (*(volatile u8  *)0x8005)   /* Window height          */

/* Frame rate register - DO NOT MODIFY (0xC6 at reset) */
#define HW_FRAME_RATE   (*(volatile u8  *)0x8006)

/* Raster position (read-only, valid during vblank) */
#define HW_RAS_H        (*(volatile u8  *)0x8008)   /* Horizontal raster pos  */
#define HW_RAS_V        (*(volatile u8  *)0x8009)   /* Vertical raster line   */

/* 2D status register
 * Bit 7: Character Over (cleared at end of VBL)
 * Bit 6: Blanking (0=displaying, 1=vblank active) */
#define HW_STATUS       (*(volatile u8  *)0x8010)
#define STATUS_CHAR_OVR 0x80
#define STATUS_VBLANK   0x40

/* 2D control register
 * Bit 7: NEG (0=normal, 1=inverted display)
 * Bit 2-0: OOWC (outside-of-window color palette select) */
#define HW_LCD_CTL      (*(volatile u8  *)0x8012)

/* Sprite position offset (added to all sprite positions) */
#define HW_SPR_OFS_X    (*(volatile u8  *)0x8020)   /* Sprite offset X        */
#define HW_SPR_OFS_Y    (*(volatile u8  *)0x8021)   /* Sprite offset Y        */

/* Scroll plane priority
 * Bit 7: 0=plane1 in front, 1=plane2 in front */
#define HW_SCR_PRIO     (*(volatile u8  *)0x8030)

/* Scroll plane offsets */
#define HW_SCR1_OFS_X   (*(volatile u8  *)0x8032)   /* Scroll plane 1 X       */
#define HW_SCR1_OFS_Y   (*(volatile u8  *)0x8033)   /* Scroll plane 1 Y       */
#define HW_SCR2_OFS_X   (*(volatile u8  *)0x8034)   /* Scroll plane 2 X       */
#define HW_SCR2_OFS_Y   (*(volatile u8  *)0x8035)   /* Scroll plane 2 Y       */

/* Background color register
 * Bit 7-6: BGON (10=valid, other=black)
 * Bit 2-0: BGC (background palette select, 0-7) */
#define HW_BG_CTL       (*(volatile u8  *)0x8118)

/* Mode selection - DO NOT MODIFY
 * Bit 7: 0=K2GE color, 1=K1GE mono compat */
#define HW_GE_MODE      (*(volatile u8  *)0x87E2)

/* ======================================================================
 * PALETTE RAM (16-bit access ONLY)
 * Source: ngpcspec.txt "Colour Palette RAM"
 * Format per entry: 0x0BGR (4 bits each, 4096 colors)
 * 16 palettes x 4 colors = 64 entries per plane
 * ====================================================================== */

#define HW_PAL_SPR      ((volatile u16 *)0x8200)    /* Sprite palettes 0-63   */
#define HW_PAL_SCR1     ((volatile u16 *)0x8280)    /* Scroll 1 palettes 0-63 */
#define HW_PAL_SCR2     ((volatile u16 *)0x8300)    /* Scroll 2 palettes 0-63 */
#define HW_PAL_BG       ((volatile u16 *)0x83E0)    /* Background palette     */
#define HW_PAL_WIN      ((volatile u16 *)0x83F0)    /* Window palette         */

/* 12-bit RGB color macro (4 bits per channel, 0-15) */
#define RGB(r, g, b)    ((u16)((r) & 0xF) | (((g) & 0xF) << 4) | (((b) & 0xF) << 8))

/* ======================================================================
 * SPRITE VRAM
 * Source: ngpcspec.txt "Sprite VRAM Format"
 * 64 sprites, 4 bytes each at 0x8800 + palette byte at 0x8C00.
 *
 * Per sprite (4 bytes):
 *   [0] = tile number (low 8 bits of 9-bit index)
 *   [1] = flags:
 *         bit 7: H flip, bit 6: V flip
 *         bit 4-3: priority (00=hide, 01=behind, 10=mid, 11=front)
 *         bit 2: H chain, bit 1: V chain
 *         bit 0: tile number bit 8
 *   [2] = X position (pixels)
 *   [3] = Y position (pixels)
 * Palette byte at 0x8C00+n: bits 3-0 = palette 0-15
 * ====================================================================== */

#define HW_SPR_DATA     ((volatile u8  *)0x8800)    /* Sprite attribs, 64x4B  */
#define HW_SPR_PAL      ((volatile u8  *)0x8C00)    /* Sprite palette indices  */

#define SPR_MAX         64

/* Sprite flag bits (byte 1) */
#define SPR_HFLIP       0x80
#define SPR_VFLIP       0x40
#define SPR_HVFLIP      0xC0
#define SPR_HIDE        (0 << 3)
#define SPR_BEHIND      (1 << 3)
#define SPR_MIDDLE      (2 << 3)
#define SPR_FRONT       (3 << 3)
#define SPR_HCHAIN      0x04
#define SPR_VCHAIN      0x02

/* ======================================================================
 * SCROLL PLANE VRAM (tile maps)
 * Source: ngpcspec.txt "Data Format for Scroll Plane VRAM"
 * 32x32 tiles per plane, 2 bytes per entry (16-bit access).
 *
 * Per entry (u16):
 *   low byte  = tile number (low 8 bits of 9-bit index)
 *   high byte = bit 7: H flip, bit 6: V flip
 *               bit 4-1: palette (0-15)
 *               bit 0: tile number bit 8
 * ====================================================================== */

#define HW_SCR1_MAP     ((volatile u16 *)0x9000)    /* Scroll plane 1: 32x32  */
#define HW_SCR2_MAP     ((volatile u16 *)0x9800)    /* Scroll plane 2: 32x32  */

#define SCR_MAP_W       32
#define SCR_MAP_H       32

/* Build a scroll map entry from tile index (0-511), palette (0-15), flips */
#define SCR_ENTRY(tile, pal, hflip, vflip) \
    ((u16)((tile) & 0xFF) | \
     (((u16)(hflip) & 1) << 15) | \
     (((u16)(vflip) & 1) << 14) | \
     (((u16)(pal) & 0xF) << 9) | \
     (((u16)(((tile) >> 8) & 1)) << 8))

/* Simplified: tile + palette, no flip */
#define SCR_TILE(tile, pal) SCR_ENTRY((tile), (pal), 0, 0)

/* ======================================================================
 * CHARACTER (TILE) RAM
 * Source: ngpcspec.txt "Data Format for Sprite/Scroll Characters"
 * 512 tiles, 8x8 pixels, 2 bits per pixel = 16 bytes per tile.
 * Stored as 8 rows of 2 bytes (u16) each.
 * ====================================================================== */

#define HW_TILE_DATA    ((volatile u16 *)0xA000)    /* 512 tiles, 8 words each */
#define TILE_MAX        512
#define TILE_WORDS      8       /* 8 x u16 = 16 bytes per tile */

/* ======================================================================
 * SCREEN CONSTANTS
 * Source: ngpcspec.txt "GRAPHICS" specs
 * ====================================================================== */

#define SCREEN_W        160     /* Visible width in pixels  */
#define SCREEN_H        152     /* Visible height in pixels */
#define SCREEN_TW       20      /* Visible width in tiles   */
#define SCREEN_TH       19      /* Visible height in tiles  */

/* Stringify helpers for inline assembly constants. */
#define NGPC_STR_HELPER(x) #x
#define NGPC_STR(x) NGPC_STR_HELPER(x)

/* ======================================================================
 * BIOS SYSTEM CALL VECTOR NUMBERS
 * Source: ngpcspec.txt "NEOGEO POCKET SYSTEM CALL (BIOS CALL)"
 * Called via SWI instruction with vector number in register.
 * ====================================================================== */

#define BIOS_SHUTDOWN       0   /* Power off                              */
#define BIOS_CLOCKGEARSET   1   /* CPU clock divider (0=6MHz .. 4=384KHz) */
#define BIOS_RTCGET         2   /* Read real-time clock                   */
#define BIOS_INTLVSET       4   /* Interrupt level setting                */
#define BIOS_SYSFONTSET     5   /* Load system font into tile RAM         */
#define BIOS_FLASHWRITE     6   /* Write flash memory                     */
#define BIOS_FLASHALLERS    7   /* Erase all flash blocks                 */
#define BIOS_FLASHERS       8   /* Erase specified flash blocks           */
#define BIOS_ALARMSET       9   /* Set alarm during operation             */
#define BIOS_ALARMDOWNSET  11   /* Set power-on alarm                     */
#define BIOS_FLASHPROTECT  13   /* Protect flash blocks                   */
#define BIOS_GEMODESET     14   /* Switch K1GE/K2GE display mode          */

/* ======================================================================
 * CARTRIDGE ROM
 * Source: ngpcspec.txt "Cart ROM Header Info"
 * ROM starts at 0x200000, max 2MB. Last 16KB reserved for system.
 * ====================================================================== */

#define CART_ROM_BASE   0x200000
#define CART_ROM_SIZE   0x200000    /* 2 MB max */

/* Boot status values (HW_USR_BOOT) */
#define BOOT_POWER      0   /* Normal power-on   */
#define BOOT_RESUME     1   /* Resume from sleep */
#define BOOT_ALARM      2   /* RTC alarm wake    */

/* ======================================================================
 * MEMORY MAP SUMMARY (for reference)
 *
 * 0x000000 - 0x0000FF  Internal I/O registers
 * 0x004000 - 0x006BFF  Main RAM (12 KB, 0x4000-0x5FFF battery-backed)
 * 0x007000 - 0x007FFF  Z80 RAM (4 KB, shared with sound CPU)
 * 0x008000 - 0x0087FF  Video registers
 * 0x008800 - 0x008BFF  Sprite VRAM (256+32 bytes)
 * 0x008C00 - 0x008C3F  Sprite palette indices
 * 0x009000 - 0x0097FF  Scroll plane 1 VRAM (2 KB)
 * 0x009800 - 0x009FFF  Scroll plane 2 VRAM (2 KB)
 * 0x00A000 - 0x00BFFF  Character/tile RAM (8 KB)
 * 0x200000 - 0x3FFFFF  Cartridge ROM (2 MB flash)
 * 0xFF0000 - 0xFFFFFF  Internal ROM (64 KB, system firmware)
 * ====================================================================== */

#endif /* NGPC_HW_H */

