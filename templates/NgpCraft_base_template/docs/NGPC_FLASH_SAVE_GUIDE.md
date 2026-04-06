# NGPC Flash Save — Complete Guide

**Template 2026 — validated on real hardware (2026-03-18)**

---

## 1. Quick start

```c
// ── build flags ────────────────────────────────────────────────────
// -DNGP_ENABLE_FLASH_SAVE=1   (disabled by default in the distributed template)

// ── no system.lib required ─────────────────────────────────────────
// Flash save is self-contained: ngpc_flash_asm.asm embeds standalone AMD stubs.
// Enable with: make NGP_ENABLE_FLASH_SAVE=1

// ── define your save struct ────────────────────────────────────────
typedef struct {
    u8  magic[4];      /* MUST be { 0xCA, 0xFE, 0x20, 0x26 } */
    u8  level;
    u16 score;
    u8  lives;
    /* ... up to SAVE_SIZE-4 bytes of payload */
} MySave;

// ── at startup ─────────────────────────────────────────────────────
ngpc_flash_init();
if (ngpc_flash_exists()) {
    MySave s;
    ngpc_flash_load(&s);
    g_level = s.level;
    g_score = s.score;
} else {
    /* no save found: use defaults */
}

// ── when saving ────────────────────────────────────────────────────
MySave s;
s.magic[0] = 0xCA;  s.magic[1] = 0xFE;
s.magic[2] = 0x20;  s.magic[3] = 0x26;
s.level = g_level;
s.score = g_score;
ngpc_flash_save(&s);       /* safe to call multiple times per session */
```

---

## 2. Hardware context

### Memory map

| Address (CPU) | Region | Note |
|---|---|---|
| `0x200000` | Cart ROM base (CS0) | 16Mbit = 2 MB |
| `0x3F8000` | Block 32 (F16_B32, 8 KB) | Save-capable |
| `0x3FA000` | **Block 33 (F16_B33, 8 KB)** | **Used by this driver** |
| `0x3FC000` | Block 34 (F16_B34, 16 KB) | Reserved for BIOS — DO NOT USE |

### Block sizes (16Mbit cart)

| Blocks | Size each | Erase time | Safe? |
|---|---|---|---|
| 0–30 | 64 KB | 50–200 ms | ❌ Watchdog fires (~100 ms limit) |
| 31 | 32 KB | ~20 ms | Untested |
| **32, 33** | **8 KB** | **~5–15 ms** | **✓ Safe** |
| 34 | 16 KB | — | Reserved — never use |

**Block 33 was chosen** because it is 8 KB (fast erase, safe under watchdog) and SNK games use it as the save area for 16Mbit carts.

### Why the BIOS makes flash write hard

During any flash operation, the BIOS executes **DI** (disable interrupts). This prevents the VBL ISR from clearing the watchdog. Erase of a 64 KB block takes 50–200 ms; the watchdog fires at ~100 ms → console reset. 8 KB blocks erase in ~5–15 ms and are safe.

---

## 3. BIOS bugs and how they are worked around

### Bug 1 — VECT_FLASHERS broken for blocks 32/33/34

`SysCall.txt p.299`:
> *System call "VECT_FLASHERS" cannot operate on blocks 32, 33, 34 (F16_B32, F16_B33, F16_B34). When these areas need to be operated on, please use the system library routine "CLR_FLASH_RAM".*

**Workaround (original):** use `CLR_FLASH_RAM` from `system.lib` (bank-3 registers).

**Workaround (standalone — used by this template):** `ngpc_flash_asm.asm` embeds
the AMD sector-erase sequence executed from RAM at `0x6E00` — no `system.lib` required.

### Bug 2 — CLR_FLASH_RAM silently fails on its 2nd call in the same session

`CLR_FLASH_RAM` erases block 33 successfully on the **first** call after power-on. On any subsequent call within the same session it exits silently without erasing. No source is available for `system.lib`; root cause unknown.

Diagnostic codes used during research:
```
BERA:00CA  → chip read 0xCA before erase  = data present, chip in Read Array mode ✓
FERA:00CA  → chip still 0xCA after erase  = erase silently failed
FERA:FF    → chip reads 0xFF after erase  = erase OK ✓
FVFY:0000  → flash matches data exactly   = write OK ✓
FVFY:0002  → 2 bytes wrong after write    = erase failed, NOR AND of old+new data
```

**Workaround:** the append-only slot design (see §4) ensures `CLR_FLASH_RAM` is called at most once per session.

### Bug 3 — Direct cart ROM writes are no-ops from user code

Attempting to send Sharp flash commands manually (e.g. `ldb (xde),0x20` with `xde=0x3FA000`) has no effect. The cart bus `/WE` line is only asserted by the BIOS and `system.lib`; user code read/write cycles to ROM space are decoded as read-only by the address decoder.

**Evidence (confirmed across 3 hardware attempts):**
```asm
ld   xde,0x3fa000
ldb  (xde),0x50      ; Clear SR command — silently ignored
ldb  (xde),0x20      ; Block Erase Setup — silently ignored
ldb  (xde),0xd0      ; Block Erase Confirm — silently ignored
; Poll:
bit  7,(xde)         ; reads 0xCA (real flash data, chip in Read Array mode)
                     ; 0xCA = 0b11001010 → bit 7 = 1 → poll exits immediately
                     ; Chip was never put in erase mode.
```

**Consequence:** `ldb (xde),imm8` from ROM-resident code still fails (executing from
the chip being programmed is impossible). The fix is a three-step workaround:

```
(0x6E) = 0x14    ; assert /WE on cart bus — user code CAN write this register
(0x6F) = 0xB1    ; watchdog extended mode
copy stub → 0x6E00 + call 0x6E00   ; execute AMD sequence from RAM, not from flash
```

This is exactly what `ngpc_flash_asm.asm` does.

### Bug 4 — asm900 Error-230 with `ld xde3,(xsp+N)`

Stack-relative addressing `(xsp+disp)` is not encodable with bank-3 extended registers as destination. The assembler reports:

```
ASM900-Error-230 : Operand type mismatch
```

**Workaround:** two-step load through the primary bank — the same pattern already used for `XHL3`:

```asm
; Passing a pointer (1st param):
ld   xhl,(xsp+4)     ; stack-rel → primary XHL  ✓
ld   xhl3,xhl        ; primary   → bank-3        ✓

; Passing a u32 offset (2nd param):
ld   xde,(xsp+8)     ; stack-rel → primary XDE  ✓
ld   xde3,xde        ; primary   → bank-3        ✓
```

---

## 4. Append-only slot design

### Rationale

Because `CLR_FLASH_RAM` fails on its 2nd call per session, the driver must avoid calling erase more than once per session. The append-only design achieves this by never erasing mid-session: each save writes to the next empty slot, and erase only occurs when the entire block is full.

### Layout

```
Block 33 — 8 KB (0x1FA000..0x1FBFFF)
SAVE_SIZE = 256 bytes → NUM_SLOTS = 32

Offset    Slot   Status after boot
────────  ─────  ──────────────────────────────────────────────────
0x1FA000  0      0xCA 0xFE 0x20 0x26 ... (written, valid)
0x1FA100  1      0xCA 0xFE 0x20 0x26 ... (written, valid — newest)
0x1FA200  2      0xFF 0xFF 0xFF 0xFF ... (empty — next write goes here)
0x1FA300  3      0xFF ...
...
0x1FBF00  31     0xFF ...
```

### Write algorithm

```
find_next_slot():
    for i in 0..31:
        if SAVE_ADDR[i * 256] == 0xFF:
            return i
    return 32  (full)

ngpc_flash_save(data):
    slot = find_next_slot()
    if slot == 32:               // block full
        ngpc_flash_erase_asm()   // standalone AMD erase — 1st call of session, always OK
        slot = 0
    offset = 0x1FA000 + slot * 256
    ngpc_flash_write_asm(data, offset)
```

### Read algorithm

```
find_last_slot():
    for i in 31..0:              // scan newest first
        if SAVE_ADDR[i*256 + 0..3] == {0xCA,0xFE,0x20,0x26}:
            return i
    return 0xFF                  // no valid save

ngpc_flash_load(data):
    slot = find_last_slot()
    if slot == 0xFF: return
    copy 256 bytes from SAVE_ADDR[slot * 256] to data
```

### Why erase is called at most once per session

- At power-on, the block either has empty slots (≥ 1 byte == 0xFF at the right position) or all 32 slots are full.
- **Case A — slots available:** saves go to slot 0, 1, 2, … until all 32 are used. Erase is triggered only when slot 32 is needed. In a typical session a game saves at most a handful of times → the block will never fill.
- **Case B — block full at boot:** first save triggers erase (1st erase call → success), then writes to slot 0. Subsequent saves write to slot 1, 2, …, no more erases.
- In neither case is the erase function called twice in the same session.

---

## 5. system.lib symbols (reference — no longer a dependency)

> **The template does NOT require `system.lib`.** `ngpc_flash_asm.asm` embeds
> standalone AMD stubs (erase + write) extracted by disassembly of the
> hardware-validated StarGunner ROM. `system.lib` remains supported via
> `SYSTEM_LIB=<path>` if you prefer the original BIOS path.

For reference, the relevant symbols and their register interface:

**TULINK is case-sensitive. All symbols must be UPPER-CASE.**

| Symbol | Function | Parameters |
|---|---|---|
| `CLR_FLASH_RAM` | Erase blocks 32/33/34 | `RA3`=cart(0), `RB3`=block(0x21) |
| `WRITE_FLASH_RAM` | Write flash | `RA3`=cart, `RBC3`=count×256, `XHL3`=src, `XDE3`=offset |
| `FLASH_M_READ` | Read chip capacity (debug only) | `RA3`=cart → returns capacity in `RA3` |

`FLASH_M_READ` is documented as **debug-only** (`SysLib.txt`): *"This subroutine should be used during debug. When creating master program, the code calling this subroutine should be invalid."*

Declare in ASM with `extern large SYMBOL_NAME` and call with `calr SYMBOL_NAME`.

---

## 6. NGP_FAR requirement

The save area is at `0x200000 + 0x1FA000 = 0x3FA000`. This is beyond the 16-bit near address range (`0x0000..0xFFFF`).

`cc900` uses **near (16-bit) pointers by default**. Without `NGP_FAR` (`__far`), the compiler silently truncates `0x3FA000` to `0xA000`, which is ROM code space. Reads return random ROM bytes instead of flash data.

```c
/* CORRECT — all internal flash pointers use NGP_FAR */
#define SAVE_ADDR  ((volatile u8 NGP_FAR *)(CART_ROM_BASE + SAVE_OFFSET))
```

User-facing API functions (`ngpc_flash_save`, `ngpc_flash_load`) take plain `void *` pointers to **RAM** buffers. You do not need `NGP_FAR` in your own code.

---

## 7. Configuring SAVE_SIZE

`SAVE_SIZE` is defined in `ngpc_flash.h`. It must be a **multiple of 256** (BIOS write granularity).

| SAVE_SIZE | Payload bytes | NUM_SLOTS | `BC` in ASM |
|---|---|---|---|
| 256 (default) | 252 | 32 | `1` |
| 512 | 508 | 16 | `2` |
| 1024 | 1020 | 8 | `4` |

If you change `SAVE_SIZE`, you **must also update `ld bc,N`** in `ngpc_flash_asm.asm`
(in `_ngpc_flash_write_asm`, line `ld bc,0x0001`):

```asm
ld   bc,N       ; N = SAVE_SIZE / 256
```

---

## 8. Files involved

| File | Role |
|---|---|
| `src/core/ngpc_flash.h` | Public API and full documentation |
| `src/core/ngpc_flash.c` | C implementation: slot scan, erase/write dispatch |
| `src/core/ngpc_flash_asm.asm` | Standalone AMD erase/write stubs (no `system.lib` required) |
| `system.lib` | Toshiba library — **optional**, only for `SYSTEM_LIB=<path>` compatibility path |
| `SysCall.txt` (Toshiba SDK) | VECT_FLASHERS bug (p.299), VECT_FLASHWRITE params |
| `SysLib.txt` (Toshiba SDK) | CLR_FLASH_RAM, WRITE_FLASH_RAM, FLASH_M_READ specs |
| `FlashMem.txt` (Toshiba SDK) | Block layout for 4/8/16 Mbit carts |

---

## 9. Diagnostic log codes (debug builds)

Enable with `NGP_ENABLE_DEBUG=1` and `NGP_ENABLE_FLASH_SAVE=1`.

| Code | Meaning |
|---|---|
| `FERA:FF` | Block erased successfully (0xFF = blank) |
| `FERA:CA` | Erase failed (0xCA = data still present) |
| `FVFY:0000` | Flash matches data exactly — write OK |
| `FVFY:NNNN` | N bytes differ — write or erase failed |

---

## 10. Known-bad patterns (do not use)

```c
// ❌ VECT_FLASHERS for block 33 — broken in BIOS (SysCall.txt p.299)
__ASM("ld  ra3,0");
__ASM("ld  rb3,0x21");       // block 33
__ASM("ld  rw3,8");          // VECT_FLASHERS = 8
__ASM("swi 1");              // silently does nothing for this block

// ❌ Direct cart ROM writes — no-ops (cart /WE not asserted by user code)
ld   xde,0x3fa000
ldb  (xde),0x20              // Block Erase Setup — never reaches chip
ldb  (xde),0xd0              // Confirm — never reaches chip

// ❌ ld xde3,(xsp+N) — asm900 Error-230
ld   xde3,(xsp+8)            // stack-rel to bank-3 = invalid encoding
                             // use two-step: ld xde,(xsp+8) / ld xde3,xde

// ❌ FLASH_M_READ in production builds — debug-only per SysLib.txt
calr FLASH_M_READ            // remove before shipping
```

---

## 11. Research log

Summary of key findings:

| Essai | Approach | Result | Root cause |
|---|---|---|---|
| 1–5 | VECT_FLASHERS / block 30/33 | Crash or no effect | Bug in BIOS for blk 33; watchdog for 64 KB |
| 6 | CLR_FLASH_RAM + swi 1 write | **1st save works ✓** | Valid path |
| 7–13 | Various resets before 2nd CLR call | FERA:00CA always | CLR_FLASH_RAM session bug, chip state irrelevant |
| 14 | Split erase/write for logging | Cleaner diagnostics | — |
| 15 | Manual Sharp erase, bank-3 regs | FERA:00CA | `ldb (xde3),imm8` invalid encoding (Error-230 path) |
| 16 | Manual Sharp erase, primary XDE | FERA:00CA | Writes silently ignored — user code can't drive /WE |
| **17** | **Append-only slots** | **✓ SOLVED** | Avoids 2nd CLR_FLASH_RAM call entirely |
| **18** | **Standalone AMD stubs (no system.lib)** | **✓ SOLVED** | Register 0x6E=0x14 enables /WE; stubs copied to RAM 0x6E00 and called from there |
