        module  ngpc_dma_prog

        public  _dma0_program_asm, _dma1_program_asm, _dma2_program_asm, _dma3_program_asm
        public  _dma0_program_u16_asm, _dma1_program_u16_asm
        public  _dma2_program_u16_asm, _dma3_program_u16_asm
        public  _dma0_program_u32_asm, _dma1_program_u32_asm
        public  _dma2_program_u32_asm, _dma3_program_u32_asm

DMA_PROG section code large

; C prototypes:
;   void dmaN_program_asm(const u8  __far *src, volatile u8 __far *dst, u16 count);
;   void dmaN_program_u16_asm(const u16 __far *src, volatile u8 __far *dst, u16 count);
;   void dmaN_program_u32_asm(const u32 __far *src, volatile u8 __far *dst, u16 count);
;
; Notes:
; - `count` is written to DMACn directly (i.e. number of DMA "steps"/transfers,
;   not necessarily a byte count when using word/dword modes).
;
; Stack layout on entry (TLCS-900/H cc900):
;   (xsp+0)  return address (far) 4 bytes
;   (xsp+4)  src (far pointer)   4 bytes
;   (xsp+8)  dst (far pointer)   4 bytes
;   (xsp+12) count (u16)         2 bytes
;
; DMA modes (see SDK `HDMA.H`; values here are the real hex values).
DMA_MODE_SINC1  equ 8   ; 0x08: byte,  src++
DMA_MODE_SINC2  equ 9   ; 0x09: word,  src++
DMA_MODE_SINC4  equ 10  ; 0x0A: dword, src++

_dma0_program_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas0,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad0,xwa
        ld      wa,(xsp+12)
        ldcw    dmac0,wa
        ld      a,DMA_MODE_SINC1
        ldcb    dmam0,a
        ret

_dma0_program_u16_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas0,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad0,xwa
        ld      wa,(xsp+12)
        ldcw    dmac0,wa
        ld      a,DMA_MODE_SINC2
        ldcb    dmam0,a
        ret

_dma0_program_u32_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas0,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad0,xwa
        ld      wa,(xsp+12)
        ldcw    dmac0,wa
        ld      a,DMA_MODE_SINC4
        ldcb    dmam0,a
        ret

_dma1_program_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas1,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad1,xwa
        ld      wa,(xsp+12)
        ldcw    dmac1,wa
        ld      a,DMA_MODE_SINC1
        ldcb    dmam1,a
        ret

_dma1_program_u16_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas1,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad1,xwa
        ld      wa,(xsp+12)
        ldcw    dmac1,wa
        ld      a,DMA_MODE_SINC2
        ldcb    dmam1,a
        ret

_dma1_program_u32_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas1,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad1,xwa
        ld      wa,(xsp+12)
        ldcw    dmac1,wa
        ld      a,DMA_MODE_SINC4
        ldcb    dmam1,a
        ret

_dma2_program_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas2,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad2,xwa
        ld      wa,(xsp+12)
        ldcw    dmac2,wa
        ld      a,DMA_MODE_SINC1
        ldcb    dmam2,a
        ret

_dma2_program_u16_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas2,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad2,xwa
        ld      wa,(xsp+12)
        ldcw    dmac2,wa
        ld      a,DMA_MODE_SINC2
        ldcb    dmam2,a
        ret

_dma2_program_u32_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas2,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad2,xwa
        ld      wa,(xsp+12)
        ldcw    dmac2,wa
        ld      a,DMA_MODE_SINC4
        ldcb    dmam2,a
        ret

_dma3_program_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas3,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad3,xwa
        ld      wa,(xsp+12)
        ldcw    dmac3,wa
        ld      a,DMA_MODE_SINC1
        ldcb    dmam3,a
        ret

_dma3_program_u16_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas3,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad3,xwa
        ld      wa,(xsp+12)
        ldcw    dmac3,wa
        ld      a,DMA_MODE_SINC2
        ldcb    dmam3,a
        ret

_dma3_program_u32_asm:
        ld      xwa,(xsp+4)
        ldcl    dmas3,xwa
        ld      xwa,(xsp+8)
        ldcl    dmad3,xwa
        ld      wa,(xsp+12)
        ldcw    dmac3,wa
        ld      a,DMA_MODE_SINC4
        ldcb    dmam3,a
        ret

        end
