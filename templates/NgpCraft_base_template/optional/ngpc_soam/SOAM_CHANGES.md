# ngpc_soam - changes (2026-02-25)

This folder contains the optional module `ngpc_soam` (Shadow OAM double-buffer).

Goal of the change: keep the existing tested behavior (`ngpc_soam_flush()`), and add an
additional flush path that is closer to what big NGPC games do (Metal Slug 1st Mission):
copy only what is needed + tail-clear the leftovers.

Note: keep this file ASCII-only.

---

## What was added

### 1) New API: `ngpc_soam_flush_partial()`

Files:
- `ngpc_soam.h` (declaration + brief doc)
- `ngpc_soam.c` (implementation)

Behavior (intended for the common case "slots 0..used-1 are used"):
- Copy only the prefix `[0..used-1]` to hardware OAM (`0x8800`), instead of always copying all 64.
- Tail-clear leftover sprites from previous frame by clearing only the HW *attr* byte (stride 4)
  for slots `[used..used_prev-1]` (attr=0 => hidden).
- Update HW palette indices (`0x8C00`) for `[0..used-1]` and clear the tail `[used..used_prev-1]`
  to `0` so no stale palette id lingers.

Constraints:
- Same assumption as the original tail-clear strategy: you should fill sprites densely starting at
  slot 0 for best results (0,1,2,...).
- MUST be called during VBlank (or just after) for tear-free updates.

When to use:
- Use `ngpc_soam_flush_partial()` if you usually submit far less than 64 sprites (ex: 8..24).
- Keep `ngpc_soam_flush()` as the default safe option (constant cost, always 64 slots copied).

Example (VBlank):
```c
static void __interrupt isr_vblank(void)
{
    HW_WATCHDOG = WATCHDOG_CLEAR;
    ngpc_soam_flush_partial(); /* or ngpc_soam_flush(); */
    ngpc_vramq_flush();
    g_vb_counter++;
}
```

---

## Change 2 (2026-02-26) -- ASM split (flush hot path)

### Why

`ngpc_soam_flush()` and `ngpc_soam_flush_partial()` run 60x/second in ISR (VBlank).
The C implementation uses byte-by-byte loops: 256 + 64 iterations per frame.
TLCS-900H LDIRW copies 2 bytes per clock cycle using hardware block transfer,
making the flush path significantly faster on the VBlank hot path.
All other functions (begin, put, hide, hide_all, used) have no long loops -- C is sufficient.

Reference disassembly pattern (Sonic SS1 section 1.1):
  0x0003C017: XDE=0x8800, XHL=shadow_oam, BC=0x80, LDIRW  (256 bytes)
  0x0003C02D: XDE=0x8C00, XHL=shadow_col, BC=0x20, LDIRW  ( 64 bytes)

### New file layout

| File                   | Role                                               |
|------------------------|----------------------------------------------------|
| `ngpc_soam.c`          | REFERENCE ONLY -- not compiled. Original C impl.   |
| `ngpc_soam_c.c`        | Compiled C: begin/put/hide/hide_all/used + vars     |
| `ngpc_soam_flush.asm`  | Compiled ASM: flush() and flush_partial() via LDIRW |
| `ngpc_soam.h`          | Public API (unchanged)                             |

Variables in `ngpc_soam_c.c` are declared WITHOUT `static` so the ASM file can
access them via `extern` directives:
  extern  _s_oam, _s_col, _s_used, _s_used_prev

### Makefile integration (two .rel files instead of one)

Old:
  OBJS += $(OBJ_DIR)/src/ngpc_soam/ngpc_soam.rel

New:
  OBJS += $(OBJ_DIR)/src/ngpc_soam/ngpc_soam_c.rel
  OBJS += $(OBJ_DIR)/src/ngpc_soam/ngpc_soam_flush.rel

The asm rule is usually automatic if the makefile already handles .asm -> .rel.
Check that the rule uses: asm900 -o $@ $< $(ASMFLAGS)

### asm900 / TLCS-900H gotchas found during this port

1. INC requires explicit count: `INC 1, r` (NOT `INC r`)
2. `LD (HL), n` does NOT exist -- no store-indirect-immediate instruction
3. `LD (XHL), c` -- 'c' is ambiguous with Carry condition code -- use register E
4. `(XHL+d)` form required for indirect stores (NOT `(HL)`)
5. Upper 16 bits of XHL must be 0 before (XHL+d) addressing; `LD XHL, 0` once
   before a loop is enough (16-bit HL ops do NOT touch upper XHL)
6. LDIRW BC=0 copies 65536 words -- guard partial flush with `or a,a / jr z, skip`
7. Warning 501 on `ld hl, extern_symbol` is informational -- linker resolves it

See also: `Doc de dev/Final/ASM.md` for full reference.

---

## Backups

Because this workspace is not a git repo, the original version is preserved as explicit backup
files in this directory:
- `ngpc_soam.c.bak_pre_flush_partial_20260225`
- `ngpc_soam.h.bak_pre_flush_partial_20260225`

These backups are the exact pre-change content (no `ngpc_soam_flush_partial()` API).

