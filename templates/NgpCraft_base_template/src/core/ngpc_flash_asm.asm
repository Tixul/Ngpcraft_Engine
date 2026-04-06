$MAXIMUM

;
; ngpc_flash_asm.asm - Standalone flash save (no system.lib)
;
; Part of NgpCraft_base_template (MIT License)
;
; This file replaces the system.lib-dependent version.
; It embeds the flash programming stubs extracted from StarGunner (hardware-validated)
; and implements the full call mechanism found by disassembly of WRITE_FLASH_RAM /
; CLR_FLASH_RAM (system.lib internals):
;
;   1. ld (0x6E),0x14      — enable /WE on cartridge bus (CRITICAL: never set manually)
;   2. ld (0x6F),0xB1      — watchdog extended mode for long BIOS-equivalent operation
;   3. Copy stub bytes to RAM 0x6E00 (mandatory: cannot execute from the flash chip itself)
;   4. Set XIX=0x200000, XDE=abs_dest, XHL=src, BC=pages   (or XDE=block, XIY/A=0 for erase)
;   5. call 0x6E00         — execute AMD sequence from RAM
;   6. ld (0x6F),0x4E / ld (0x6E),0xF0  — restore watchdog + bus
;
; Flash target: block 33 (F16_B33, 8KB, absolute 0x3FA000).
;
; Default SAVE_SIZE = 256 bytes -> BC = 1.
; If you change SAVE_SIZE to 512: set  ld bc,0x0002  below and update SAVE_SIZE in
; ngpc_flash.h  (NUM_SLOTS = 8192 / SAVE_SIZE must remain >= 1).
;
; Stub byte sources (from StarGunner/bin/main.ngp, hardware-validated):
;   Write stub : 115 bytes at ROM file offset 0x13517  (ROM addr 0x213517)
;   Erase stub :  98 bytes at ROM file offset 0x13733  (ROM addr 0x213733)
;
; Stub register interface (current bank, bank-0):
;   Write: XIX=0x200000  XHL=src_ptr  XDE=abs_flash_dest  BC=0x0001 (1x256=256B)
;   Erase: XIX=0x200000  XIY=0        A=0                 XDE=0x3FA000 (block 33)
;
; cc900 ABI (CALL pushes 4-byte XPC as return address):
;   (xsp+0)..(xsp+3) = return address
;   (xsp+4)..(xsp+7) = 1st parameter  (pushed as 4-byte XWA via lda/push)
;   (xsp+8)..(xsp+11)= 2nd parameter  (same)
;

        module  ngpc_flash_asm

        public  _ngpc_flash_erase_asm
        public  _ngpc_flash_write_asm

FLASH_RAM       equ     0x6E00          ; RAM address for stub execution
FLASH_BUS_CTRL  equ     0x6E            ; I/O: flash /WE enable (0x14=on, 0xF0=off)
FLASH_WD        equ     0x6F            ; I/O: watchdog  (0xB1=extended, 0x4E=normal)
CART_BASE       equ     0x200000        ; CS0 base address
FLASH_BLK33     equ     0x3FA000        ; Block 33 absolute address (0x200000+0x1FA000)

FLASH   section code large


; ===========================================================================
; _ngpc_flash_erase_asm
; Erases block 33 (F16_B33, 8KB) using the extracted AMD erase stub.
; Called only when all append-only slots are full (~once per 16 saves).
; No parameters.  C prototype: void ngpc_flash_erase_asm(void);
; ===========================================================================
_ngpc_flash_erase_asm:

        ld      (FLASH_BUS_CTRL),0x14   ; enable /WE on cart bus
        ld      (FLASH_WD),0xB1         ; watchdog: extended mode

        ; Copy erase stub (98 bytes) from ROM to RAM at FLASH_RAM
        push    xbc                     ; preserve XBC across copy
        ld      xde,FLASH_RAM           ; destination: RAM
        ld      xhl,_erase_stub         ; source: stub bytes in ROM
        ld      bc,0x62                 ; BC = 98 bytes
        db      0x83,0x11               ; ldir (xde+),(xhl+) -- copy BC bytes
        pop     xbc                     ; restore XBC

        ; Set up registers for stub call
        ld      xix,CART_BASE           ; XIX = 0x200000 (AMD unlock base)
        ld      xiy,0x0                 ; XIY = 0 (erase stub uses as delay counter)
        ld      a,0x0                   ; A = 0 (erase stub state init)
        ld      xde,FLASH_BLK33         ; XDE = 0x3FA000 (block 33 to erase)

        call    FLASH_RAM               ; execute stub from RAM

        ld      (FLASH_WD),0x4E         ; restore watchdog
        ld      (FLASH_BUS_CTRL),0xF0   ; disable /WE
        ret


; ===========================================================================
; _ngpc_flash_write_asm
; Writes SAVE_SIZE bytes (default 256, BC=0x0001) from data to the flash slot at the given absolute offset.
; Parameters:
;   (xsp+4)  = data:   source address (const void *)
;   (xsp+8)  = offset: flash dest relative to cart base (u32, e.g. 0x1FA000 + slot*256)
; C prototype: void ngpc_flash_write_asm(const void *data, u32 offset);
; ===========================================================================
_ngpc_flash_write_asm:

        ld      (FLASH_BUS_CTRL),0x14   ; enable /WE on cart bus
        ld      (FLASH_WD),0xB1         ; watchdog: extended mode

        ; Load parameters from C stack (before any pushes change offsets)
        ld      xhl,(xsp+4)             ; 1st param: source pointer
        ld      xde,(xsp+8)             ; 2nd param: flash offset (relative, e.g. 0x1FA000+slot*512)
        ld      xix,CART_BASE           ; XIX = 0x200000 (also needed for AMD sequences)
        add     xde,xix                 ; XDE = offset + 0x200000 = absolute flash dest (0x3FA000+...)

        ; Preserve abs_dest/src across LDIR copy
        push    xde                     ; save flash abs dest
        push    xhl                     ; save src pointer

        ; Copy write stub (115 bytes) from ROM to RAM at FLASH_RAM
        ld      xde,FLASH_RAM           ; destination: RAM
        ld      xhl,_write_stub         ; source: stub bytes in ROM
        ld      bc,0x73                 ; BC = 115 bytes
        db      0x83,0x11               ; ldir (xde+),(xhl+) -- copy BC bytes

        ; Restore src/dest pointers
        pop     xhl                     ; source data pointer
        pop     xde                     ; flash absolute destination

        ; Set up remaining registers for stub call (XIX already set above)
        ld      bc,0x0001               ; BC = 1 page x 256 = 256 bytes  (change to 0x0002 if SAVE_SIZE=512)

        call    FLASH_RAM               ; execute stub from RAM

        ld      (FLASH_WD),0x4E         ; restore watchdog
        ld      (FLASH_BUS_CTRL),0xF0   ; disable /WE
        ret


; ===========================================================================
; Flash stub byte tables
; Extracted from StarGunner/bin/main.ngp (hardware-validated on real flash cart).
; These are position-independent stubs — they use XIX for AMD bus cycles.
;
; Write stub  (115 bytes, file offset 0x13517):
;   AMD unlock → reset → unlock again → byte-program sequence → poll DQ7/DQ5 loop
;   Register interface: XIX=cart_base XHL=src XDE=dest BC=pages(1 for default 256B)
;
; Erase stub  (98 bytes, file offset 0x13733):
;   AMD unlock → reset → unlock → erase setup (0x80) → unlock → sector erase (0x30)
;   Poll DQ7 loop → final reset/unlock → ret
;   Register interface: XIX=cart_base XDE=block_addr XIY=0 A=0
; ===========================================================================

_write_stub:
        db      0xF3,0xF1,0x55,0x55,0x00,0xAA, 0xF3,0xF1,0xAA,0x2A,0x00,0x55
        db      0xF3,0xF1,0x55,0x55,0x00,0xF0, 0xD7,0xE6,0xA8,0xE9,0xEC,0x08
        db      0x21,0x00,0xC5,0xEC,0x20,0xED, 0xA8,0x1E,0x24,0x00,0xEA,0x61
        db      0xC9,0xCF,0xFF,0x66,0x0A,0xE9, 0x69,0xE9,0xCF,0x00,0x00,0x00
        db      0x00,0x6E,0xE7,0xF3,0xF1,0x55, 0x55,0x00,0xAA,0xF3,0xF1,0xAA
        db      0x2A,0x00,0x55,0xF3,0xF1,0x55, 0x55,0x00,0xF0,0x0E,0xF3,0xF1
        db      0x55,0x55,0x00,0xAA,0xF3,0xF1, 0xAA,0x2A,0x00,0x55,0xF3,0xF1
        db      0x55,0x55,0x00,0xA0,0xB2,0x40, 0x82,0xF0,0x66,0x14,0xED,0x61
        db      0xED,0xCF,0xFF,0xFF,0x03,0x00, 0x66,0x08,0xB2,0xCD,0x66,0xEE
        db      0x82,0xF0,0x66,0x02,0x21,0xFF, 0x0E

_erase_stub:
        db      0xF3,0xF1,0x55,0x55,0x00,0xAA, 0xF3,0xF1,0xAA,0x2A,0x00,0x55
        db      0xF3,0xF1,0x55,0x55,0x00,0xF0, 0x00,0x00,0xF3,0xF1,0x55,0x55
        db      0x00,0xAA,0xF3,0xF1,0xAA,0x2A, 0x00,0x55,0xF3,0xF1,0x55,0x55
        db      0x00,0x80,0xF3,0xF1,0x55,0x55, 0x00,0xAA,0xF3,0xF1,0xAA,0x2A
        db      0x00,0x55,0xB2,0x00,0x30,0x82, 0x3F,0xFF,0x66,0x15,0xED,0x61
        db      0xED,0xCF,0xFF,0xFF,0x1F,0x00, 0x66,0x09,0xB2,0xCD,0x66,0xED
        db      0x82,0x3F,0xFF,0x66,0x02,0x21, 0xFF,0xF3,0xF1,0x55,0x55,0x00
        db      0xAA,0xF3,0xF1,0xAA,0x2A,0x00, 0x55,0xF3,0xF1,0x55,0x55,0x00
        db      0xF0,0x0E

        end
