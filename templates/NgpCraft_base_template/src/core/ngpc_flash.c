/*
 * ngpc_flash.c - Cartridge flash save system (append-only slot design)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * ═══════════════════════════════════════════════════════════════════
 * WHY THIS DESIGN — COMPLETE HARDWARE RESEARCH SUMMARY
 * ═══════════════════════════════════════════════════════════════════
 *
 * Target block: F16_B33 (block 33, 8 KB, offset 0x1FA000).
 *   CPU absolute read address: CART_ROM_BASE (0x200000) + 0x1FA000
 *                            = 0x3FA000
 *
 * ── BIOS bugs (confirmed on hardware) ──────────────────────────────
 *
 *  1. VECT_FLASHERS is broken for blocks 32/33/34 (SNK bug, SysCall.txt
 *     p.299). CLR_FLASH_RAM (system.lib) is the documented workaround.
 *
 *  2. Block erase with 64 KB blocks (e.g. block 30) triggers the
 *     watchdog: the BIOS does DI during all flash ops, preventing the
 *     VBL ISR from clearing the watchdog. Erase of 64 KB takes 50-200 ms;
 *     the watchdog fires in ~100 ms → console reset. 8 KB blocks erase
 *     in ~5-15 ms and are safe.
 *
 *  3. CLR_FLASH_RAM silently fails on its 2nd call within the same
 *     power-on session. Root cause unknown (no source available).
 *     BERA:00CA (chip is in Read Array mode before the call) confirms
 *     the chip state is not the issue — CLR_FLASH_RAM exits early for
 *     an unknown internal reason.
 *
 *  4. Direct writes to 0x3FA000 from user code (ldb (xde),imm8 etc.)
 *     are no-ops. The cart bus /WE line is only asserted by the BIOS /
 *     system.lib; user code cannot generate write cycles to ROM space.
 *     Evidence: after sending 0x20/0xD0 manually, `bit 7,(xde)` reads
 *     0xCA (actual flash data, bit 7 = 1) and exits immediately — the
 *     chip was never put into erase mode.
 *
 * ── Why append-only slots solve everything ─────────────────────────
 *
 * The double-erase bug (point 3) only matters if CLR_FLASH_RAM is
 * called twice in one session. The append-only design ensures it is
 * called at most once per session: erase only happens when all 32
 * slots are full, which requires 32 separate save operations without
 * a power cycle — impossible under normal gameplay.
 *
 *  • First CLR_FLASH_RAM call of any session → always succeeds. ✓
 *  • All subsequent saves within the same session write to new empty
 *    slots → zero erases, zero problems. ✓
 *
 * ── ASM constraint: ld xde3,(xsp+N) is invalid ────────────────────
 *
 * TLCS-900/H / asm900 does not support stack-relative addressing
 * (xsp+disp) with bank-3 extended registers as destination (Error-230).
 * The correct pattern (used in ngpc_flash_asm.asm) is:
 *     ld  xde,(xsp+8)    ; stack-rel → primary XDE  (valid)
 *     ld  xde3,xde       ; primary  → bank-3         (valid, mirrors ld xhl3,xhl)
 *
 * ── NGP_FAR requirement ────────────────────────────────────────────
 *
 * CART_ROM_BASE + 0x1FA000 = 0x3FA000, beyond 16-bit range.
 * Without NGP_FAR (__far), cc900 truncates to 0xA000, causing reads
 * to return ROM code bytes instead of flash data.
 *
 * ═══════════════════════════════════════════════════════════════════
 * SLOT LAYOUT (block 33, 8 KB)
 * ═══════════════════════════════════════════════════════════════════
 *
 *  SAVE_SIZE = 256 bytes  →  NUM_SLOTS = 8192 / 256 = 32
 *
 *  slot 0  : 0x1FA000..0x1FA0FF   first byte 0xFF = empty, 0xCA = used
 *  slot 1  : 0x1FA100..0x1FA1FF
 *  ...
 *  slot 31 : 0x1FBF00..0x1FBFFF
 *
 *  Write : scan 0→31 for first byte == 0xFF → write there, no erase.
 *  Read  : scan 31→0 for last slot with valid magic → that is current save.
 *  Erase : only when all slots used; CLR_FLASH_RAM (1st call, always OK).
 */

#include "ngpc_hw.h"
#include "ngpc_sys.h"
#include "ngpc_flash.h"
#if NGP_ENABLE_DEBUG
#include "ngpc_log.h"
#endif


/* ── Address constants ──────────────────────────────────────────────
 *
 * NGP_FAR (__far) is REQUIRED for SAVE_ADDR: the address 0x3FA000 is
 * outside the 16-bit near range.  cc900 silently truncates near pointers
 * to 16 bits, turning 0x3FA000 into 0xA000 (a ROM code address).
 */
#define SAVE_OFFSET   0x1FA000UL
#define SAVE_ADDR     ((volatile u8 NGP_FAR *)(CART_ROM_BASE + SAVE_OFFSET))

/* ── Slot constants ─────────────────────────────────────────────────
 *
 * SLOT_SIZE == SAVE_SIZE: BIOS VECT_FLASHWRITE transfers in multiples
 * of 256 bytes (rbc3=1 → 256 bytes).  SAVE_SIZE must be a multiple of
 * 256; the default is 256 (rbc3=1 in ngpc_flash_asm.asm).
 */
#define SLOT_SIZE     SAVE_SIZE                   /* bytes per slot   */
#define NUM_SLOTS     (8192UL / (u32)SLOT_SIZE)   /* 32 slots at 256  */

/* ── Magic bytes ────────────────────────────────────────────────────
 *
 * The first 4 bytes of every valid save slot must equal these values.
 * ngpc_flash_exists() and ngpc_flash_load() scan for this pattern.
 */
#define SAVE_MAGIC_0  0xCA
#define SAVE_MAGIC_1  0xFE
#define SAVE_MAGIC_2  0x20
#define SAVE_MAGIC_3  0x26

/* ════════════════════════════════════════════════════════════════════
 * Disabled stub — when NGP_ENABLE_FLASH_SAVE=0
 * ════════════════════════════════════════════════════════════════════ */
#if !NGP_ENABLE_FLASH_SAVE

void ngpc_flash_init(void)                        { }
void ngpc_flash_save(const void *data)            { (void)data; }
void ngpc_flash_load(void *data)                  { (void)data; }
u8   ngpc_flash_exists(void)                      { return 0u; }
u16  ngpc_flash_verify(const void *data)          { (void)data; return 0u; }

#else /* NGP_ENABLE_FLASH_SAVE */

/* ── ASM stubs (ngpc_flash_asm.asm) ────────────────────────────────
 *
 * _ngpc_flash_erase_asm  : erases block 33 via CLR_FLASH_RAM.
 *                          No parameters.
 *
 * _ngpc_flash_write_asm  : writes SAVE_SIZE bytes to flash.
 *   param 1 (xsp+4)  : const void *data  — source buffer
 *   param 2 (xsp+8)  : u32 offset        — flash offset (e.g. 0x1FA200)
 *
 * Note: ld xde3,(xsp+8) is NOT valid (Error-230). The ASM loads into
 * primary XDE then copies with ld xde3,xde — same as ld xhl3,xhl.
 */
extern void ngpc_flash_erase_asm(void);
extern void ngpc_flash_write_asm(const void *data, u32 offset);

/* Index of the slot used by the last ngpc_flash_save() call.
 * Used by ngpc_flash_verify() to inspect the correct slot.
 * 0xFF = ngpc_flash_save() not called yet this session. */
static u8 s_last_slot = 0xFF;

/* ── Internal helpers ───────────────────────────────────────────────*/

/* Return the index (0..NUM_SLOTS-1) of the next empty slot,
 * or NUM_SLOTS if the block is completely full.
 * An empty slot has its first byte erased to 0xFF. */
static u8 flash_find_next_slot(void)
{
    u8 i;
    for (i = 0u; i < (u8)NUM_SLOTS; i++) {
        if (SAVE_ADDR[(u32)i * SLOT_SIZE] == 0xFF)
            return i;
    }
    return (u8)NUM_SLOTS;   /* full */
}

/* Return the index of the LAST slot that begins with the 4 magic bytes,
 * or 0xFF if no valid slot is found. Scanning from high to low means
 * the most recently written slot is found first. */
static u8 flash_find_last_slot(void)
{
    u8 i = (u8)NUM_SLOTS;
    while (i-- > 0u) {
        u32 base = (u32)i * SLOT_SIZE;
        if (SAVE_ADDR[base + 0u] == SAVE_MAGIC_0 &&
            SAVE_ADDR[base + 1u] == SAVE_MAGIC_1 &&
            SAVE_ADDR[base + 2u] == SAVE_MAGIC_2 &&
            SAVE_ADDR[base + 3u] == SAVE_MAGIC_3) {
            return i;
        }
    }
    return 0xFF;    /* no valid slot */
}

/* ── Public API ─────────────────────────────────────────────────────*/

void ngpc_flash_init(void)
{
    /* Flash is memory-mapped and directly readable without setup.
     * s_last_slot is already 0xFF (static initialisation). */
}

/* Write SAVE_SIZE bytes to the next available slot.
 *
 * Normal case: slot with first byte == 0xFF found → write there, done.
 *
 * Block-full case: all 32 slots are written.
 *   → ngpc_flash_erase_asm() calls CLR_FLASH_RAM (system.lib).
 *   → This is guaranteed to be the FIRST CLR_FLASH_RAM call of the
 *     session (no prior erase happened; 32 saves without power cycle
 *     is not reachable in normal gameplay).
 *   → After erase, write to slot 0.
 */
void ngpc_flash_save(const void *data)
{
    u8  slot;
    u32 offset;

    slot = flash_find_next_slot();

    if (slot >= (u8)NUM_SLOTS) {
        /* Block full: erase (CLR_FLASH_RAM, first call of session). */
        ngpc_flash_erase_asm();
#if NGP_ENABLE_DEBUG
        /* FERA: 0xFF = erase OK, 0xCA = erase failed */
        NGPC_LOG_HEX("FERA", SAVE_ADDR[0]);
#endif
        slot = 0u;
    }

    offset      = SAVE_OFFSET + (u32)slot * SLOT_SIZE;
    s_last_slot = slot;
    ngpc_flash_write_asm(data, offset);
}

/* Read SAVE_SIZE bytes from the last valid slot.
 * Does nothing if no valid slot is found (call ngpc_flash_exists() first). */
void ngpc_flash_load(void *data)
{
    u8  slot = flash_find_last_slot();
    u32 base;
    u8 *dst = (u8 *)data;
    u16 i;

    if (slot == 0xFF) return;   /* no valid save */

    base = (u32)slot * SLOT_SIZE;
    for (i = 0u; i < SAVE_SIZE; i++)
        dst[i] = SAVE_ADDR[base + i];
}

/* Return 1 if at least one valid slot exists, 0 otherwise. */
u8 ngpc_flash_exists(void)
{
    return flash_find_last_slot() != 0xFF;
}

/* Verify the slot written by the last ngpc_flash_save() call.
 * Returns 0 if flash matches data exactly, >0 = error byte count,
 * 0xFFFF if ngpc_flash_save() has not been called this session. */
u16 ngpc_flash_verify(const void *data)
{
    const u8 *expected = (const u8 *)data;
    u32 base;
    u16 i, errors = 0u;

    if (s_last_slot == 0xFF) return 0xFFFFu;

    base = (u32)s_last_slot * SLOT_SIZE;
    for (i = 0u; i < SAVE_SIZE; i++) {
        if (SAVE_ADDR[base + i] != expected[i])
            errors++;
    }
    return errors;
}

#endif /* NGP_ENABLE_FLASH_SAVE */
