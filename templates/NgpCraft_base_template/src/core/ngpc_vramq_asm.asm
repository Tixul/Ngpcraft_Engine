; ngpc_vramq_asm.asm - VRAM queue ASM helpers (TLCS-900/H)
;
; Part of NgpCraft_base_template (MIT License)
;
; Provides ngpc_memcpy_w() -- word-level block copy via LDIRW.
; Used by ngpc_vramq.c CMD_COPY path instead of a byte-by-byte C loop.
; dst is a near VRAM address (0x8000-0xBFFF). src can be near RAM or far ROM.
;
; void ngpc_memcpy_w(u32 dst_addr, u32 src_addr, u32 words)
;
; cc900 calling convention -- args passed as u32 (4 bytes each, unambiguous):
;   (xsp+0)  return address (far)   4 bytes
;   (xsp+4)  dst_addr (u32)         4 bytes  <- near VRAM address (high 16 = 0)
;   (xsp+8)  src_addr (u32)         4 bytes  <- RAM/ROM address (near or far)
;   (xsp+12) words (u32)            4 bytes  <- word count (high 16 = 0)
;
; Using u32 args avoids ambiguity: cc900 may pad u16 args to 4 bytes on stack.
; u32 args are always exactly 4 bytes, matching LD XRR, (xsp+N) reads.
;
; LDIRW guard: BC=0 at entry copies 65536 words -- skip if words==0.
; OR A, C is safe here (ALU instruction; C is not ambiguous as condition code
; in this context -- ambiguity only occurs in LD (mem), c indirect store form).

$MAXIMUM

        module  ngpc_vramq_asm

        public  _ngpc_memcpy_w

VRAMQ_ASM       section code large

; ================================================================
; void ngpc_memcpy_w(u32 dst_addr, u32 src_addr, u32 words)
;
; Block-copies 'words' 16-bit words from src_addr to dst_addr via LDIRW.
; Equivalent to: while (words--) *(u16*)dst++ = *(u16*)src++;
; but uses LDIRW hardware block transfer.
;
; Call site (ngpc_vramq.c) passes near u16 addresses widened to u32:
;   ngpc_memcpy_w((u32)dst_u16, (u32)src_u16, (u32)word_count)
; So upper 16 bits of XDE/XHL are guaranteed 0. LDIRW needs upper=0. OK
; ================================================================
_ngpc_memcpy_w:
        ; Load XDE = dst_addr (full 32-bit; upper 16 = 0 since near address)
        ld      xde, (xsp+4)

        ; Load XHL = src_addr (full 32-bit; may be near or far)
        ld      xhl, (xsp+8)

        ; Load BC = words (low 16 of u32; high 16 is 0 since words <= 65535)
        ld      bc, (xsp+12)

        ; BC=0 guard: if words==0, skip (LDIRW BC=0 copies 65536 words!)
        ; OR A, C: ALU instruction -- C is register, not condition code here.
        ld      a, b
        or      a, c
        jr      z, memcpy_w_done

        ldirw                       ; block copy: BC words from XHL -> XDE

memcpy_w_done:
        ret

        end

