# NgpCraft_base_template - Makefile
# MIT License
#
# Targets: make / make clean / make move_files
# Toolchain: Toshiba cc900 (TLCS-900/H C compiler)
#
# Build outputs:
# - Objects (.rel): build/obj/
# - Link intermediates: project root (tulink/tuconv always write to cwd)
#   move_files cleans them up to build/tmp/
# - Final ROMs: bin/

NAME = main
OBJ_DIR = build/obj
TMP_DIR = build/tmp
OUTPUT_DIR = bin

# Path to Toshiba toolchain (cc900, asm900, tulink, tuconv, s242ngp).
# Windows: set via system environment variables (THOME already defined by installer).
# Linux:   set here or override with: make THOME=/path/to/toshiba
#   Example: THOME = /home/user/toshiba
THOME ?=
export THOME

# Auto-detect Python: prefer 'py -3' (Windows Launcher), fall back to 'python3', then 'python'
# If auto-detection fails, override here: PYTHON := py -3
ifeq ($(OS),Windows_NT)
    PYTHON := $(shell (where py >nul 2>nul && echo py -3) || (where python3 >nul 2>nul && echo python3) || echo python)
else
    PYTHON := $(shell command -v python3 2>/dev/null && echo python3 || echo python)
endif
CC900_CPU ?= -Nb2

# ---- Feature flags (sync with src/core/ngpc_config.h defaults) ----
NGP_ENABLE_SOUND ?= 1
NGP_ENABLE_FLASH_SAVE ?= 0
NGP_ENABLE_DEBUG ?= 1
NGP_ENABLE_DMA ?= 0
NGP_ENABLE_SPRMUX ?= 0
NGP_ENABLE_PROFILER ?= 0
NGP_PROFILE_RELEASE ?= 0
NGP_DMA_ALLOW_VBLANK_TRIGGER ?= 0
NGP_DMA_INSTALL_DONE_ISR ?= 0
NGP_DMA_INSTALL_REARM_ISR ?= 0

CDEFS = \
	-DNGP_ENABLE_SOUND=$(NGP_ENABLE_SOUND) \
	-DNGP_ENABLE_FLASH_SAVE=$(NGP_ENABLE_FLASH_SAVE) \
	-DNGP_ENABLE_DEBUG=$(NGP_ENABLE_DEBUG) \
	-DNGP_ENABLE_DMA=$(NGP_ENABLE_DMA) \
	-DNGP_ENABLE_SPRMUX=$(NGP_ENABLE_SPRMUX) \
	-DNGP_ENABLE_PROFILER=$(NGP_ENABLE_PROFILER) \
	-DNGP_PROFILE_RELEASE=$(NGP_PROFILE_RELEASE) \
	-DNGP_DMA_ALLOW_VBLANK_TRIGGER=$(NGP_DMA_ALLOW_VBLANK_TRIGGER) \
	-DNGP_DMA_INSTALL_DONE_ISR=$(NGP_DMA_INSTALL_DONE_ISR) \
	-DNGP_DMA_INSTALL_REARM_ISR=$(NGP_DMA_INSTALL_REARM_ISR) \
	-DNGP_FAR=__far \
	-DNGP_NEAR=__near

# ---- Code modules ----
OBJS = \
    $(OBJ_DIR)/src/main.rel \
    $(OBJ_DIR)/src/core/ngpc_sys.rel \
    $(OBJ_DIR)/src/core/ngpc_vramq.rel \
    $(OBJ_DIR)/src/core/ngpc_vramq_asm.rel \
    $(OBJ_DIR)/src/core/ngpc_log.rel \
    $(OBJ_DIR)/src/core/ngpc_assert.rel \
    $(OBJ_DIR)/src/gfx/ngpc_gfx.rel \
    $(OBJ_DIR)/src/gfx/ngpc_sprite.rel \
    $(OBJ_DIR)/src/gfx/ngpc_text.rel \
    $(OBJ_DIR)/src/core/ngpc_input.rel \
    $(OBJ_DIR)/src/core/ngpc_timing.rel \
    $(OBJ_DIR)/src/core/ngpc_math.rel \
    $(OBJ_DIR)/src/core/ngpc_flash.rel \
    $(OBJ_DIR)/src/gfx/ngpc_bitmap.rel \
    $(OBJ_DIR)/src/core/ngpc_rtc.rel \
    $(OBJ_DIR)/src/gfx/ngpc_metasprite.rel \
    $(OBJ_DIR)/src/fx/ngpc_palfx.rel \
    $(OBJ_DIR)/src/fx/ngpc_raster.rel \
    $(OBJ_DIR)/src/fx/ngpc_lz.rel \
    $(OBJ_DIR)/src/fx/ngpc_lut.rel \
    $(OBJ_DIR)/src/core/ngpc_runtime.rel \
    $(OBJ_DIR)/src/core/ngpc_runtime_alias.rel \
    $(OBJ_DIR)/src/core/ngpc_syspatch.rel

ifneq ($(strip $(NGP_ENABLE_FLASH_SAVE)),0)
OBJS += $(OBJ_DIR)/src/core/ngpc_flash_asm.rel
endif

ifneq ($(strip $(NGP_ENABLE_PROFILER)),0)
OBJS += $(OBJ_DIR)/src/fx/ngpc_debug.rel
endif

ifneq ($(strip $(NGP_ENABLE_SPRMUX)),0)
OBJS += $(OBJ_DIR)/src/fx/ngpc_sprmux.rel
endif

ifneq ($(strip $(NGP_ENABLE_DMA)),0)
OBJS += $(OBJ_DIR)/src/fx/ngpc_dma.rel
OBJS += $(OBJ_DIR)/src/fx/ngpc_dma_prog.rel
OBJS += $(OBJ_DIR)/src/fx/ngpc_dma_raster.rel
endif

# ---- Sound driver/data ----
ifneq ($(strip $(NGP_ENABLE_SOUND)),0)
OBJS += $(OBJ_DIR)/src/audio/sounds.rel
OBJS += $(OBJ_DIR)/sound/sound_data.rel
endif

# ---- Graphics data (tiles, sprites, palettes) ----
OBJS += $(OBJ_DIR)/GraphX/gfx_data.rel
OBJS += $(OBJ_DIR)/GraphX/intro_ngpc_craft_png.rel

TARGET_ABS = $(NAME).abs
TARGET_S24 = $(NAME).s24
TARGET_NGP = $(NAME).ngp

# system.lib — required for CLR_FLASH_RAM (block 33 erase, BIOS bug workaround).
# SysLib.txt: VECT_FLASHERS cannot erase F16_B32/B33/B34 on 16Mbit carts.
# Override path if your system.lib is elsewhere:
#   make SYSTEM_LIB=C:/path/to/system.lib
SYSTEM_LIB ?=
# Default clean build: keep this empty.
# Only pass SYSTEM_LIB if you explicitly need Toshiba flash helper symbols.

ifneq ($(strip $(SYSTEM_LIB)),)
LINK_LIBS = "$(SYSTEM_LIB)"
else
LINK_LIBS =
endif

# ---- Rules ----

.PHONY: all clean move_files

all: $(TARGET_NGP)

$(OBJ_DIR)/%.rel: %.c
	$(PYTHON) tools/build_utils.py compile $< $@ $(CC900_CPU) $(CDEFS)

$(OBJ_DIR)/%.rel: %.asm
	$(PYTHON) tools/build_utils.py asm $< $@

# ---- Generated scene header dependencies ----
# cc900 does not emit .d dependency files, so make cannot auto-detect header
# changes.  List GraphX/gen/*.h explicitly: when any generated scene header
# changes, the files that include them are rebuilt.
_GEN_HEADERS := $(wildcard GraphX/gen/*.h)
ifneq ($(_GEN_HEADERS),)
$(OBJ_DIR)/src/main.rel: $(_GEN_HEADERS)
$(OBJ_DIR)/src/ngpng_autorun_main.rel: $(_GEN_HEADERS)
endif

$(TARGET_NGP): makefile ngpc.lcf $(OBJS)
	$(PYTHON) tools/build_utils.py link $(TARGET_ABS) ngpc.lcf $(OBJS) $(LINK_LIBS)
	$(PYTHON) tools/build_utils.py s242ngp $(TARGET_S24)
	$(PYTHON) tools/build_utils.py copy $(TARGET_NGP) $(OUTPUT_DIR)/$(NAME).ngc

clean:
	$(PYTHON) tools/build_utils.py clean

move_files:
	$(PYTHON) tools/build_utils.py move $(NAME) $(TMP_DIR)
