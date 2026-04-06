/*
 * ngpc_flash.h - Cartridge flash save system
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * ═══════════════════════════════════════════════════════════════════
 * HARDWARE CONTEXT
 * ═══════════════════════════════════════════════════════════════════
 *
 * Target : block 33 (F16_B33), offset 0x1FA000, 8 KB
 *          Absolute CPU address: 0x200000 + 0x1FA000 = 0x3FA000
 *
 * BIOS bugs confirmed on 16Mbit carts (SysCall.txt p.299):
 *   - VECT_FLASHERS cannot erase blocks 32, 33, 34.
 *   - Workaround: use CLR_FLASH_RAM (system.lib) for those blocks.
 *   - CLR_FLASH_RAM itself silently fails on its 2nd call within the
 *     same power-on session (hardware bug; no source available).
 *   - Direct writes to 0x3FA000 from user code are no-ops: the cart
 *     bus /WE line is only asserted by the BIOS / system.lib.
 *
 * ═══════════════════════════════════════════════════════════════════
 * APPEND-ONLY SLOT DESIGN  (avoids all double-erase problems)
 * ═══════════════════════════════════════════════════════════════════
 *
 * Block 33 (8 KB) is treated as an array of 32 slots × 256 bytes.
 *
 *   slot 0  : 0x1FA000..0x1FA0FF   (256 bytes)
 *   slot 1  : 0x1FA100..0x1FA1FF
 *   ...
 *   slot 31 : 0x1FB F00..0x1FBfFF
 *
 * Write  : finds the next empty slot (first byte == 0xFF) and writes
 *          there — NO erase required.
 * Read   : scans slots 31→0, returns the last slot with a valid magic.
 * Erase  : triggered only when ALL 32 slots are used (extremely rare
 *          mid-session); uses CLR_FLASH_RAM (first and only call of
 *          the session → always succeeds).
 *
 * ═══════════════════════════════════════════════════════════════════
 * USAGE
 * ═══════════════════════════════════════════════════════════════════
 *
 * 1. Define NGP_ENABLE_FLASH_SAVE=1 in your build flags (or makefile).
 *
 * 2. Link system.lib (contains CLR_FLASH_RAM and WRITE_FLASH_RAM).
 *
 * 3. Your save struct MUST start with the 4 magic bytes:
 *
 *       typedef struct {
 *           u8  magic[4];    // must be { 0xCA, 0xFE, 0x20, 0x26 }
 *           u8  level;
 *           u16 score;
 *           // ... up to 252 more bytes (total must fit in SAVE_SIZE)
 *       } MySaveData;
 *
 * 4. Typical save / load pattern:
 *
 *       // ── at startup ───────────────────────────────────────────
 *       ngpc_flash_init();
 *       if (ngpc_flash_exists()) {
 *           MySaveData save;
 *           ngpc_flash_load(&save);
 *           player_level = save.level;
 *           player_score = save.score;
 *       }
 *
 *       // ── when saving ──────────────────────────────────────────
 *       MySaveData save;
 *       save.magic[0] = 0xCA;  save.magic[1] = 0xFE;
 *       save.magic[2] = 0x20;  save.magic[3] = 0x26;
 *       save.level = player_level;
 *       save.score = player_score;
 *       ngpc_flash_save(&save);   // can be called multiple times
 *                                 // per session safely
 *
 * ═══════════════════════════════════════════════════════════════════
 * NGP_FAR REQUIREMENT
 * ═══════════════════════════════════════════════════════════════════
 *
 * Flash is at 0x3FA000 — outside the 16-bit near address range.
 * All internal flash pointers use NGP_FAR (__far). You do NOT need
 * NGP_FAR in your own code; the API copies to/from your normal buffers.
 *
 * ═══════════════════════════════════════════════════════════════════
 */

#ifndef NGPC_FLASH_H
#define NGPC_FLASH_H

#include "ngpc_types.h"

/* ── Configuration ─────────────────────────────────────────────────
 *
 * SAVE_SIZE : size of your save data, in bytes.
 *   - Minimum 4 (magic) + your data.
 *   - Must be a multiple of 256 (BIOS write granularity).
 *   - Must satisfy: NUM_SLOTS = 8192 / SAVE_SIZE >= 1.
 *   - Default 256 → 32 slots. Increase if you need more than 252
 *     bytes of payload (e.g. 512 → 16 slots, 508 bytes payload).
 *
 * SLOT_SIZE is always equal to SAVE_SIZE.
 * NUM_SLOTS = 8192 / SAVE_SIZE (computed internally in .c).
 */
#define SAVE_SIZE   256     /* bytes per slot; must be multiple of 256 */

/* ── API ────────────────────────────────────────────────────────────
 *
 * All functions are no-ops when NGP_ENABLE_FLASH_SAVE=0.
 */

/* Call once at startup before any other flash function. */
void ngpc_flash_init(void);

/* Write SAVE_SIZE bytes to the next available flash slot.
 *
 * data : pointer to your save struct (first 4 bytes must be the magic).
 *
 * The function writes to the next empty slot without erasing first.
 * If all slots are full it erases the block (CLR_FLASH_RAM, one call)
 * then writes to slot 0. Erase is safe: it can happen at most once
 * per session, so CLR_FLASH_RAM is never called twice.
 */
void ngpc_flash_save(const void *data);

/* Read SAVE_SIZE bytes from the last valid slot into buffer.
 * Does nothing if ngpc_flash_exists() returns 0.
 * data : receive buffer, must be >= SAVE_SIZE bytes. */
void ngpc_flash_load(void *data);

/* Return 1 if at least one slot with a valid magic exists, 0 otherwise.
 * Call at startup to decide whether to load or initialise defaults. */
u8 ngpc_flash_exists(void);

/* Debug: read back the slot written by the last ngpc_flash_save() call
 * and count bytes that differ from data.
 * Returns 0  = flash matches exactly (write successful).
 * Returns >0 = that many bytes are wrong (write failed or incomplete).
 * Returns 0xFFFF if ngpc_flash_save() has not been called yet.
 * Only meaningful with NGP_ENABLE_FLASH_SAVE=1 and NGP_ENABLE_DEBUG=1. */
u16 ngpc_flash_verify(const void *data);

#endif /* NGPC_FLASH_H */
