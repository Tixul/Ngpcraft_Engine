; ngpc_soam_flush.asm - Shadow OAM flush routines (TLCS-900/H ASM)
;
; Part of NgpCraft_base_template (MIT License)
;
; Why ASM: the C version uses byte-by-byte loops (256 + 64 iterations).
; LDIRW copies 2 bytes per clock cycle using hardware block transfer,
; cutting the flush time on the hot VBlank path.
;
; Sonic disassembly pattern (SS1 section 1.1):
;   0x0003C017: XDE=0x8800, XHL=shadow_oam, BC=0x80, LDIRW  (256 bytes)
;   0x0003C02D: XDE=0x8C00, XHL=shadow_col, BC=0x20, LDIRW  ( 64 bytes)
;
; asm900 / TLCS-900H notes:
;   INC requires explicit count: INC 1, r  (not just INC r).
;   LD (rr), n (immediate) does not exist -- store via register.
;   LD (rr), c is ambiguous: C = condition code Carry, not register C.
;   Use register E (never a condition code) as zero constant for stores.
;   Addressing: LD (XHL+d), r  -- use d=+1 or d=+0 form explicitly.
;   Upper 16 bits of XHL must be 0 before (XHL+d) addressing.
;   16-bit ops (ADD HL,HL / ADD HL,DE / LD H,n / LD L,n) do NOT
;   modify XHL upper bits, so LD XHL,0 once before a loop is enough.
;
; LDIRW guard: BC=0 at entry copies 65536 words.
;   flush_full: BC constants 0x80/0x20 -- never 0, always safe.
;   flush_partial: BC = runtime value -- guarded by jr z.
;
; Variables defined in ngpc_soam_c.c (non-static globals).

        module  ngpc_soam_flush

        public  _ngpc_soam_flush
        public  _ngpc_soam_flush_partial

        extern  _s_oam, _s_col, _s_used, _s_used_prev

SPR_MAX         equ     64
HW_SPR_DATA     equ     0x8800
HW_SPR_PAL      equ     0x8C00

SOAM_FLUSH      section code large

; ================================================================
; void ngpc_soam_flush(void)
;
; Full flush: always pushes all 64 sprite slots to hardware.
;   1. Tail-clear shadow for slots s_used..s_used_prev-1
;   2. LDIRW 256 bytes s_oam -> 0x8800 (BC=0x80 = 128 words)
;   3. LDIRW  64 bytes s_col -> 0x8C00 (BC=0x20 =  32 words)
; ================================================================
_ngpc_soam_flush:
        ld      a, (_s_used)
        ld      b, (_s_used_prev)
        cp      a, b
        jr      nc, soam_full_push  ; s_used >= s_used_prev: nothing to clear

        ; XHL = 0: upper 16 bits must be 0 for (XHL+d) addressing.
        ; 16-bit HL ops do not modify upper XHL -- zero once before loop.
        ld      xhl, 0

soam_full_tail:
        ; s_oam[A*4+1] = 0  (attr byte -> PR.C=0 = hidden)
        ; XHL = &s_oam[A*4], then (XHL+1) = &s_oam[A*4+1]
        ld      l, a
        ld      h, 0
        add     hl, hl              ; HL = A*2
        add     hl, hl              ; HL = A*4
        ld      de, _s_oam
        add     hl, de              ; HL = &s_oam[A*4]
        ld      e, 0                ; E = 0 (after DE use; E is not a condition code)
        ld      (xhl+1), e          ; write 0 to s_oam[A*4+1]
        inc     1, a
        cp      a, b
        jr      c, soam_full_tail

soam_full_push:
        ; --- LDIRW: 256 bytes s_oam -> HW_SPR_DATA ---
        ; XHL = source (near address, upper bits 0)
        ; XDE = dest   (near address, upper bits 0)
        ld      xhl, 0
        ld      hl, _s_oam
        ld      xde, 0
        ld      de, HW_SPR_DATA
        ld      bc, 0x0080          ; 128 words = 256 bytes
        ldirw

        ; --- LDIRW: 64 bytes s_col -> HW_SPR_PAL ---
        ld      xhl, 0
        ld      hl, _s_col
        ld      xde, 0
        ld      de, HW_SPR_PAL
        ld      bc, 0x0020          ; 32 words = 64 bytes
        ldirw

        ret

; ================================================================
; void ngpc_soam_flush_partial(void)
;
; Optimized for dense usage (filled slots 0..s_used-1):
;   1. LDIRW s_used*4 bytes s_oam prefix -> 0x8800 (s_used*2 words)
;   2. LDIR  s_used   bytes s_col prefix -> 0x8C00 (byte copy)
;   3. Tail-clear HW attr + palette for slots s_used..s_used_prev-1
;
; If s_used == 0: LDIRW/LDIR skipped (BC=0 would copy 65536 words).
; ================================================================
_ngpc_soam_flush_partial:
        ld      a, (_s_used)
        or      a, a
        jr      z, soam_partial_tail_check

        ; --- LDIRW: s_used*4 bytes of OAM prefix ---
        ; BC = s_used*2 words (s_used <= 64, so *2 <= 128, fits in C)
        add     a, a                ; A = s_used * 2 (word count)
        ld      b, 0
        ld      c, a                ; BC = s_used * 2
        ld      xhl, 0
        ld      hl, _s_oam
        ld      xde, 0
        ld      de, HW_SPR_DATA
        ldirw                       ; LDIRW does not modify A

        ; --- LDIR: s_used bytes of palette prefix ---
        ld      a, (_s_used)
        ld      b, 0
        ld      c, a                ; BC = s_used
        ld      xhl, 0
        ld      hl, _s_col
        ld      xde, 0
        ld      de, HW_SPR_PAL
        ldir

soam_partial_tail_check:
        ld      a, (_s_used)
        ld      b, (_s_used_prev)
        cp      a, b
        jr      nc, soam_partial_done

        ; XHL = 0 before loop (upper bits must be 0 for (XHL+d) addressing)
        ld      xhl, 0

soam_partial_tail:
        ; hw_oam[A*4+1] = 0
        ld      l, a
        ld      h, 0
        add     hl, hl              ; HL = A*2
        add     hl, hl              ; HL = A*4
        ld      de, HW_SPR_DATA
        add     hl, de              ; XHL = &hw_oam[A*4]
        ld      e, 0                ; E = 0 (after DE use)
        ld      (xhl+1), e          ; hw_oam[A*4+1] = 0

        ; hw_col[A] = 0
        ld      l, a
        ld      h, 0
        ld      de, HW_SPR_PAL
        add     hl, de              ; XHL = &hw_col[A]
        ld      e, 0
        ld      (xhl+0), e          ; hw_col[A] = 0

        inc     1, a
        cp      a, b
        jr      c, soam_partial_tail

soam_partial_done:
        ret

        end
