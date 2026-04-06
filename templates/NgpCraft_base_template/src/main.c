/*
 * main.c - NgpCraft_base_template
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Intro screen (skippable with A) then black screen + BGM loop.
 *
 * Sound data : sound/sound_data.c  (pulls in "sound_sample.c")
 * Instruments: src/audio/sounds.c includes "sound_sample_instruments.c"
 *              (see docs/SOUND_DRIVER_REF.md — Tracker Export Integration)
 * Intro image : GraphX/intro_ngpc_craft_png.c/.h
 *
 * ---- HOW TO REPLACE THIS DEMO WITH YOUR OWN GAME ----
 *
 * 1. BGM: replace "sound_sample.c" in sound/ with your export.
 *         Replace "sound_sample_instruments.c" with the companion file from
 *         the same hybrid export.
 *
 * 2. Intro: swap intro_ngpc_craft_png with your own image (same pipeline:
 *           ngpc_tilemap.py PNG -> .c/.h, then NGP_TILEMAP_BLIT_SCR1).
 *           Or remove STATE_INTRO entirely and start at your title screen.
 *
 * 3. Game entry: replace STATE_BLACK and black_init/black_update with
 *                your own state machine (title, game, pause, etc.).
 *
 * 4. Cleanup: remove #include "sounds.h", sound_data.h, intro_ngpc_craft_png.h
 *             and the corresponding state functions once you no longer need them.
 * ------------------------------------------------------
 */

#include "ngpc_hw.h"
#include "carthdr.h"
#include "ngpc_sys.h"
#include "ngpc_gfx.h"
#include "ngpc_sprite.h"
#include "ngpc_text.h"
#include "ngpc_input.h"
#include "ngpc_timing.h"
#include "ngpc_tilemap_blit.h"
#include "sounds.h"

#include "../sound/sound_data.h"
#include "../GraphX/intro_ngpc_craft_png.h"

/* ---- Game states ---- */

typedef enum {
    STATE_INTRO,
    STATE_BLACK
} GameState;

static GameState s_state = STATE_INTRO;

/* ---- State: Intro ---- */

#define INTRO_TILE_BASE 128u

static void intro_init(void)
{
    ngpc_gfx_scroll(GFX_SCR1, 0, 0);
    ngpc_gfx_scroll(GFX_SCR2, 0, 0);
    ngpc_gfx_clear(GFX_SCR1);
    ngpc_gfx_clear(GFX_SCR2);
    ngpc_sprite_hide_all();
    ngpc_gfx_set_bg_color(RGB(0, 0, 0));
    NGP_TILEMAP_BLIT_SCR1(intro_ngpc_craft_png, INTRO_TILE_BASE);
}

static void intro_update(void)
{
    if (ngpc_pad_pressed & PAD_A) {
        s_state = STATE_BLACK;
    }
}

/* ---- State: Black screen + BGM ---- */

static void black_init(void)
{
    ngpc_gfx_set_viewport(0, 0, SCREEN_W, SCREEN_H);
    HW_SCR_PRIO = 0x00;
    ngpc_load_sysfont();

    ngpc_gfx_scroll(GFX_SCR1, 0, 0);
    ngpc_gfx_scroll(GFX_SCR2, 0, 0);
    ngpc_gfx_clear(GFX_SCR1);
    ngpc_gfx_clear(GFX_SCR2);
    ngpc_sprite_hide_all();
    ngpc_gfx_set_bg_color(RGB(0, 0, 0));

    ngpc_gfx_set_palette(GFX_SCR1, 0,
        RGB(0, 0, 0),
        RGB(15, 15, 15),
        RGB(8, 8, 8),
        RGB(4, 4, 4)
    );
    ngpc_gfx_fill(GFX_SCR1, ' ', 0);
    ngpc_text_print(GFX_SCR1, 0, 4, 9, "Hello World");

    Bgm_SetNoteTable(NOTE_TABLE);
    Bgm_StartLoop4Ex(
        BGM_CH0, BGM_CH0_LOOP,
        BGM_CH1, BGM_CH1_LOOP,
        BGM_CH2, BGM_CH2_LOOP,
        BGM_CHN, BGM_CHN_LOOP
    );
}

/* ---- Main entry point ---- */

void main(void)
{
    GameState prev_state;

    ngpc_init();
    ngpc_load_sysfont();
    Sounds_Init();

    prev_state = STATE_BLACK; /* force init on first frame */

    while (1) {
        ngpc_vsync();
        ngpc_input_update();
        Sounds_Update();

        if (s_state != prev_state) {
            prev_state = s_state;
            switch (s_state) {
            case STATE_INTRO: intro_init(); break;
            case STATE_BLACK: black_init(); break;
            }
        }

        switch (s_state) {
        case STATE_INTRO: intro_update(); break;
        case STATE_BLACK: break;
        }
    }
}
