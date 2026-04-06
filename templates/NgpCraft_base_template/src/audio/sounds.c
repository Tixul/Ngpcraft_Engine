#include "ngpc_types.h"
#include "ngpc_hw.h"
#include "ngpc_sys.h"
#include "sounds.h"

/* Alias: the driver uses SOUNDCPU_CTRL, our template uses HW_SOUNDCPU_CTRL */
#define SOUNDCPU_CTRL  HW_SOUNDCPU_CTRL

/*
 * Minimal Z80 SFX driver (polling, multi-command buffer).
 * Shared RAM (Z80: 0x0003..0x0012, CPU: 0x7003..0x7012):
 *   0x7003 = count (CPU writes N, Z80 clears to 0 when done)
 *   0x7004 = buffer[0] (byte1)
 *   0x7005 = buffer[1] (byte2)
 *   0x7006 = buffer[2] (byte3)
 *   ... up to 5 commands (15 bytes total)
 */
static const u8 s_z80drv[] = {
    0xC3, 0x13, 0x00,           /* jp 0x0013              */
    0x00,                       /* count                  */
    0x00, 0x00, 0x00,           /* buf[0..2]              */
    0x00, 0x00, 0x00,           /* buf[3..5]              */
    0x00, 0x00, 0x00,           /* buf[6..8]              */
    0x00, 0x00, 0x00,           /* buf[9..11]             */
    0x00, 0x00, 0x00,           /* buf[12..14]            */
    /* 0x0013: */
    0xF3,                       /* di                     */
    0x31, 0x00, 0x10,           /* ld sp, 0x1000          */
    /* loop (0x0017): */
    0x3A, 0x03, 0x00,           /* ld a, (0x0003)         */
    0xB7,                       /* or a                   */
    0x28, 0xFA,                 /* jr z, loop (-6)        */
    0x47,                       /* ld b, a                */
    0x21, 0x04, 0x00,           /* ld hl, 0x0004          */
    /* cmd_loop (0x0021): */
    0x7E,                       /* ld a, (hl)             */
    0x32, 0x01, 0x40,           /* ld (0x4001), a         */
    0x32, 0x00, 0x40,           /* ld (0x4000), a         */
    0x23,                       /* inc hl                 */
    0x7E,                       /* ld a, (hl)             */
    0x32, 0x01, 0x40,           /* ld (0x4001), a         */
    0x32, 0x00, 0x40,           /* ld (0x4000), a         */
    0x23,                       /* inc hl                 */
    0x7E,                       /* ld a, (hl)             */
    0x32, 0x01, 0x40,           /* ld (0x4001), a         */
    0x32, 0x00, 0x40,           /* ld (0x4000), a         */
    0x23,                       /* inc hl                 */
    0x10, 0xE6,                 /* djnz cmd_loop (-26)    */
    0xAF,                       /* xor a                  */
    0x32, 0x03, 0x00,           /* ld (0x0003), a         */
    0x18, 0xD6                  /* jr loop (-42)          */
};

/* Shared RAM (main CPU side) */
#define SND_COUNT   (*(volatile u8 *)0x7003)
#define SND_BUF     ((volatile u8 *)0x7004)
#define SND_BUF_MAX 5

/*
 * T6W28 register format:
 *   Byte 1: 1 RRR DDDD  (R=reg, D=low 4 bits of tone divider)
 *   Byte 2: 0 0 DDDDDD  (D=high 6 bits of tone divider)
 *   Attn:   1 RRR VVVV  (V=attenuation 0=max, 0xF=silent)
 *
 * Tone1 freq: reg=000, attn: reg=001
 * F = 3072000 / (32 * n)
 */

typedef struct {
    u8 valid;
    u8 b1;
    u8 b2;
    u8 b3;
} PsgCmd;

typedef struct {
    u8 attn;
    u8 env_on;
    u8 env_step;
    u8 env_speed;
    u8 env_curve_id;
    u8 pitch_curve_id;
    u8 vib_on;
    u8 vib_depth;
    u8 vib_speed;
    u8 vib_delay;
    u8 sweep_on;
    u16 sweep_end;
    s16 sweep_step;
    u8 sweep_speed;
    u8 mode;
    u8 noise_config; /* 0-7 (rate=bits0-1, type=bit2) */
    u8 macro_id;
    u8 adsr_on;       /* 0=legacy env, 1=ADSR active */
    u8 adsr_attack;   /* frames per step 15â†’attn (0=instant) */
    u8 adsr_decay;    /* frames per step attnâ†’sustain (0=instant) */
    u8 adsr_sustain;  /* sustain attn level 0-15 */
    u8 adsr_release;  /* frames per step cur->15 (0=instant) */
    u8 adsr_sustain_rate; /* frames per step sustain->silent (0=hold) */
    u8 lfo_on;
    u8 lfo_wave;      /* 0=tri,1=square,2=saw,3=sweep up,4=sweep down */
    u8 lfo_rate;      /* frames per modulation step (0=off) */
    u8 lfo_depth;     /* divider delta amount */
    u8 lfo_hold;      /* hold frames before modulation starts */
    u8 lfo2_on;
    u8 lfo2_wave;
    u8 lfo2_hold;
    u8 lfo2_rate;
    u8 lfo2_depth;
    u8 lfo_algo;      /* SNK-style algorithm 0..7 */
} BgmInstrument;

#define BGM_INST(attn, env_on, env_step, env_speed, env_curve_id, pitch_curve_id, \
                 vib_on, vib_depth, vib_speed, vib_delay, sweep_on, sweep_end, \
                 sweep_step, sweep_speed, mode, noise_config, macro_id) \
    { attn, env_on, env_step, env_speed, env_curve_id, pitch_curve_id, \
      vib_on, vib_depth, vib_speed, vib_delay, sweep_on, sweep_end, \
      sweep_step, sweep_speed, mode, noise_config, macro_id, \
      0, 0, 0, 0, 0, 0, \
      0, 0, 1, 0, 0, \
      0, 0, 0, 1, 0, 1 }

#define BGM_INST_ADSR(attn, env_on, env_step, env_speed, env_curve_id, pitch_curve_id, \
                      vib_on, vib_depth, vib_speed, vib_delay, sweep_on, sweep_end, \
                      sweep_step, sweep_speed, mode, noise_config, macro_id, \
                      adsr_on, adsr_attack, adsr_decay, adsr_sustain, adsr_release) \
    { attn, env_on, env_step, env_speed, env_curve_id, pitch_curve_id, \
      vib_on, vib_depth, vib_speed, vib_delay, sweep_on, sweep_end, \
      sweep_step, sweep_speed, mode, noise_config, macro_id, \
      adsr_on, adsr_attack, adsr_decay, adsr_sustain, adsr_release, 0, \
      0, 0, 1, 0, 0, \
      0, 0, 0, 1, 0, 1 }

/* Instrument presets come from the companion hybrid export in sound/. */
#include "../../sound/sound_sample_instruments.c"

static const u8 s_bgm_instrument_count = (u8)(sizeof(s_bgm_instruments) / sizeof(s_bgm_instruments[0]));

#ifndef SOUNDS_ENABLE_MACROS
#define SOUNDS_ENABLE_MACROS 1
#endif

#ifndef SOUNDS_ENABLE_ENV_CURVES
#define SOUNDS_ENABLE_ENV_CURVES 1
#endif

#ifndef SOUNDS_ENABLE_PITCH_CURVES
#define SOUNDS_ENABLE_PITCH_CURVES 1
#endif

#ifndef SOUNDS_ENABLE_EXAMPLE_PRESETS
#define SOUNDS_ENABLE_EXAMPLE_PRESETS 1
#endif

#if SOUNDS_ENABLE_MACROS
typedef struct {
    u8 frames;
    s8 attn_delta;
    s16 pitch_delta;
} BgmMacroStep;

typedef struct {
    const BgmMacroStep *steps;
    u8 count;
} BgmMacro;

/* Optional instrument macro steps (per-note).
 * frames=0 terminates. Keep empty to disable macros. */
static const BgmMacroStep s_bgm_macro0[] = { {0, 0, 0} };
#if SOUNDS_ENABLE_EXAMPLE_PRESETS
static const BgmMacroStep s_bgm_macro1[] = {
    {2, -4, 0},
    {4, 0, 0},
    {6, 4, 0},
    {0, 0, 0}
};
#else
static const BgmMacroStep s_bgm_macro1[] = { {0, 0, 0} };
#endif
/* Stubs for NGPC Sound Creator hybrid export compatibility (macro_id 2..3).
 * These must always be present; replace with actual steps if needed. */
static const BgmMacroStep s_bgm_macro2[] = { {0, 0, 0} };
static const BgmMacroStep s_bgm_macro3[] = { {0, 0, 0} };

static const BgmMacro s_bgm_macros[] = {
    { s_bgm_macro0, 0 },
#if SOUNDS_ENABLE_EXAMPLE_PRESETS
    { s_bgm_macro1, 4 },
#else
    { s_bgm_macro1, 0 },
#endif
    { s_bgm_macro2, 0 },
    { s_bgm_macro3, 0 },
};

static const u8 s_bgm_macro_count = (u8)(sizeof(s_bgm_macros) / sizeof(s_bgm_macros[0]));
#else
static const u8 s_bgm_macro_count = 0;
#endif

#if SOUNDS_ENABLE_ENV_CURVES
typedef struct {
    const s8 *steps;
    u8 count;
} BgmEnvCurve;

/* Optional envelope curves (deltas from base attenuation).
 * Keep empty to disable curve envelopes. */
static const s8 s_bgm_env_curve0[] = { 0 };
#if SOUNDS_ENABLE_EXAMPLE_PRESETS
static const s8 s_bgm_env_curve1[] = { 0, 1, 2, 3, 4, 6, 8, 10 };
#else
static const s8 s_bgm_env_curve1[] = { 0 };
#endif
/* Stub for NGPC Sound Creator hybrid export compatibility (env_curve_id 2). */
static const s8 s_bgm_env_curve2[] = { 0, 2, 4, 6, 8, 10, 12, 14 };

static const BgmEnvCurve s_bgm_env_curves[] = {
    { s_bgm_env_curve0, 0 },
#if SOUNDS_ENABLE_EXAMPLE_PRESETS
    { s_bgm_env_curve1, 8 },
#else
    { s_bgm_env_curve1, 0 },
#endif
    { s_bgm_env_curve2, 8 },
};

static const u8 s_bgm_env_curve_count = (u8)(sizeof(s_bgm_env_curves) / sizeof(s_bgm_env_curves[0]));
#else
static const u8 s_bgm_env_curve_count = 0;
#endif

#if SOUNDS_ENABLE_PITCH_CURVES
typedef struct {
    const s16 *steps;
    u8 count;
} BgmPitchCurve;

/* Optional pitch curves (divider deltas).
 * Keep empty to disable pitch curves. */
static const s16 s_bgm_pitch_curve0[] = { 0 };
static const s16 s_bgm_pitch_curve1[] = { 0, -2, -4, -6, -8 };
static const s16 s_bgm_pitch_curve2[] = { 0, 2, 4, 6, 8 };
static const s16 s_bgm_pitch_curve3[] = { 0, 2, 0, -2, 0 };
static const s16 s_bgm_pitch_curve4[] = { 0, -4, -8, -12, -8, -4, 0 };
/* Aliases for NGPC Sound Creator hybrid export compatibility (pitch_curve_id 5..7). */
static const s16 s_bgm_pitch_curve5[] = { 0, -2, -4, -6, -8 };          /* alias curve1 */
static const s16 s_bgm_pitch_curve6[] = { 0, 2, 4, 6, 8 };              /* alias curve2 */
static const s16 s_bgm_pitch_curve7[] = { 0, -4, -8, -12, -8, -4, 0 }; /* alias curve4 */

static const BgmPitchCurve s_bgm_pitch_curves[] = {
    { s_bgm_pitch_curve0, 0 },
    { s_bgm_pitch_curve1, 5 },
    { s_bgm_pitch_curve2, 5 },
    { s_bgm_pitch_curve3, 5 },
    { s_bgm_pitch_curve4, 7 },
    { s_bgm_pitch_curve5, 5 },
    { s_bgm_pitch_curve6, 5 },
    { s_bgm_pitch_curve7, 7 },
};

static const u8 s_bgm_pitch_curve_count = (u8)(sizeof(s_bgm_pitch_curves) / sizeof(s_bgm_pitch_curves[0]));
#else
static const u8 s_bgm_pitch_curve_count = 0;
#endif

/* Duration timer (frames) */
static u8 s_sfxTimer[4];
static u8 s_bgm_ch_used_by_sfx[4];
static u8 s_bgm_restore_ch[4];
static const u8 *s_bgm_note_table = NOTE_TABLE;
static u8 s_freq_base[4] = {0x80, 0xA0, 0xC0, 0xE0};
static u8 s_attn_base[4] = {0x90, 0xB0, 0xD0, 0xF0};
static PsgCmd s_sfx_cmd[4];
static PsgCmd s_psg_shadow[4];
static PsgCmd s_psg_pending[4];
static u8 s_psg_pending_mask;
static u8 s_psg_commit_mask;
static u8 s_sfx_end_pending[4];
static u16 s_sfx_tone_div_base[3];
static u16 s_sfx_tone_div_cur[3];
static u8 s_sfx_tone_attn_base[3];
static u8 s_sfx_tone_attn_cur[3];
static u16 s_sfx_tone_sw_end[3];
static s16 s_sfx_tone_sw_step[3];
static s8 s_sfx_tone_sw_dir[3];
static u8 s_sfx_tone_sw_speed[3];
static u8 s_sfx_tone_sw_counter[3];
static u8 s_sfx_tone_sw_on[3];
static u8 s_sfx_tone_sw_ping[3];
static u8 s_sfx_tone_env_on[3];
static u8 s_sfx_tone_env_step[3];
static u8 s_sfx_tone_env_spd[3];
static u8 s_sfx_tone_env_counter[3];
static u8 s_sfx_noise_val;
static u8 s_sfx_noise_attn_base;
static u8 s_sfx_noise_attn_cur;
static u8 s_sfx_noise_env_on;
static u8 s_sfx_noise_env_step;
static u8 s_sfx_noise_env_spd;
static u8 s_sfx_noise_env_counter;
static u8 s_sfx_noise_burst;
static u8 s_sfx_noise_burst_dur;
static u8 s_sfx_noise_burst_counter;
static u8 s_sfx_noise_burst_off;

static u8 s_buf_count;
static u8 s_sfx_active_mask;
static u16 s_sound_drops;
static u8 s_sound_fault;
static u8 s_sound_last_sfx;
static u8 BufferPushIfSpace(u8 b1, u8 b2, u8 b3);

static const PsgCmd *LastQueuedOrCommitted(u8 ch)
{
    u8 bit = (u8)(1u << ch);
    if ((s_psg_pending_mask & bit) && s_psg_pending[ch].valid) {
        return &s_psg_pending[ch];
    }
    if (s_psg_shadow[ch].valid) {
        return &s_psg_shadow[ch];
    }
    return 0;
}

static void CommitPendingShadows(void)
{
    u8 ch;
    if (!s_psg_commit_mask) {
        return;
    }
    for (ch = 0; ch < 4; ch++) {
        u8 bit = (u8)(1u << ch);
        if ((s_psg_commit_mask & bit) && s_psg_pending[ch].valid) {
            s_psg_shadow[ch] = s_psg_pending[ch];
            s_psg_shadow[ch].valid = 1;
            s_psg_pending_mask &= (u8)~bit;
        }
    }
    s_psg_commit_mask = 0;
}

static void BufferReplayPending(void)
{
    /* Requeue unsent channel commands first so drops are retried automatically. */
    static const u8 kOrder[4] = {3, 0, 1, 2};
    u8 i;
    for (i = 0; i < 4; i++) {
        u8 ch = kOrder[i];
        u8 bit = (u8)(1u << ch);
        if ((s_psg_pending_mask & bit) && !(s_psg_commit_mask & bit) && s_psg_pending[ch].valid) {
            if (BufferPushIfSpace(s_psg_pending[ch].b1, s_psg_pending[ch].b2, s_psg_pending[ch].b3)) {
                s_psg_commit_mask |= bit;
            }
        }
    }
}

static u8 WaitBufferFree(void)
{
    /* Non-blocking: if Z80 is busy, drop this packet. */
    if (SND_COUNT) {
        s_sound_fault = 1;
        s_sound_drops++;
        return 0;
    }
    return 1;
}

static u8 WaitBufferFreeSpin(u16 spin)
{
    while (SND_COUNT && spin-- > 0) {
        /* spin */
    }
    if (SND_COUNT) {
        s_sound_fault = 1;
        s_sound_drops++;
        return 0;
    }
    return 1;
}

static void BufferBegin(void)
{
    s_buf_count = 0;
    s_psg_commit_mask = 0;
}

static void BufferPush(u8 b1, u8 b2, u8 b3)
{
    if (s_buf_count < SND_BUF_MAX) {
        u8 idx = (u8)(s_buf_count * 3);
        SND_BUF[idx + 0] = b1;
        SND_BUF[idx + 1] = b2;
        SND_BUF[idx + 2] = b3;
        s_buf_count++;
    }
}

static u8 BufferPushIfSpace(u8 b1, u8 b2, u8 b3)
{
    if (s_buf_count < SND_BUF_MAX) {
        u8 idx = (u8)(s_buf_count * 3);
        SND_BUF[idx + 0] = b1;
        SND_BUF[idx + 1] = b2;
        SND_BUF[idx + 2] = b3;
        s_buf_count++;
        return 1;
    }
    s_sound_fault = 1;
    s_sound_drops++;
    return 0;
}

static int BufferPushIfChanged(u8 ch, const PsgCmd *cmd)
{
    const PsgCmd *last;
    u8 bit;
    if (!cmd || !cmd->valid) {
        return 0;
    }
    last = LastQueuedOrCommitted(ch);
    if (last &&
        last->b1 == cmd->b1 &&
        last->b2 == cmd->b2 &&
        last->b3 == cmd->b3) {
        return 0;
    }
    if (!BufferPushIfSpace(cmd->b1, cmd->b2, cmd->b3)) {
        return -1;
    }
    s_psg_pending[ch] = *cmd;
    s_psg_pending[ch].valid = 1;
    bit = (u8)(1u << ch);
    s_psg_pending_mask |= bit;
    s_psg_commit_mask |= bit;
    return 1;
}

static int BufferPushBytesIfChanged(u8 ch, u8 b1, u8 b2, u8 b3)
{
    PsgCmd cmd;
    cmd.valid = 1;
    cmd.b1 = b1;
    cmd.b2 = b2;
    cmd.b3 = b3;
    return BufferPushIfChanged(ch, &cmd);
}

static void BufferCommit(void)
{
    if (s_buf_count == 0) {
        return;
    }
    if (!WaitBufferFree()) {
        s_buf_count = 0;
        s_psg_commit_mask = 0;
        return;
    }
    SND_COUNT = s_buf_count;
    s_buf_count = 0;
    CommitPendingShadows();
}

static void BufferCommitBlocking(u16 spin)
{
    if (s_buf_count == 0) {
        return;
    }
    if (!WaitBufferFreeSpin(spin)) {
        s_buf_count = 0;
        s_psg_commit_mask = 0;
        return;
    }
    SND_COUNT = s_buf_count;
    s_buf_count = 0;
    CommitPendingShadows();
}

void Sfx_BufferBegin(void)
{
    BufferBegin();
}

void Sfx_BufferPush(u8 b1, u8 b2, u8 b3)
{
    BufferPush(b1, b2, b3);
}

void Sfx_BufferCommit(void)
{
    BufferCommit();
}

void Sfx_SendBytes(u8 b1, u8 b2, u8 b3)
{
    BufferBegin();
    BufferPush(b1, b2, b3);
    BufferCommit();
}

/* Direct PSG helpers (unused in clean build, kept as reference):
 * - PlayTone / PlayToneCh: write one tone command immediately.
 * - PlayNoise: write one noise command immediately.
 * If you need them, reintroduce as static helpers. */

static void MakeToneCmd(u8 ch, u16 n, u8 attn, PsgCmd *cmd)
{
    u8 freq_base = s_freq_base[ch];
    u8 attn_base = s_attn_base[ch];
    cmd->valid = 1;
    cmd->b1 = (u8)(freq_base | (n & 0x0F));
    cmd->b2 = (u8)((n >> 4) & 0x3F);
    cmd->b3 = (u8)(attn_base | (attn & 0x0F));
}

static void MakeNoiseCmd(u8 noise_val, u8 attn, PsgCmd *cmd)
{
    const PsgCmd *last;
    u8 val = (u8)(noise_val & 0x07);
    u8 ctrl = (u8)(0xE0 | val);
    u8 ctrl_changed = 1;
    cmd->valid = 1;
    cmd->b1 = ctrl;
    last = LastQueuedOrCommitted(3);
    if (last && (last->b1 == ctrl || last->b2 == ctrl)) {
        ctrl_changed = 0;
    }
    cmd->b2 = ctrl_changed ? ctrl : (u8)(0xF0 | (attn & 0x0F));
    cmd->b3 = (u8)(0xF0 | (attn & 0x0F));
}

static void MakeNoiseCmdFromNote(u8 note_idx, u8 attn, PsgCmd *cmd)
{
    /* Noise stream note byte is 1..8, register payload is low 3 bits (0..7). */
    u8 val = (u8)((note_idx - 1) & 0x07);
    MakeNoiseCmd(val, attn, cmd);
}

static void MakeSilenceCmd(u8 attn_base, PsgCmd *cmd)
{
    cmd->valid = 1;
    cmd->b1 = (u8)(attn_base | 0x0F);
    cmd->b2 = (u8)(attn_base | 0x0F);
    cmd->b3 = (u8)(attn_base | 0x0F);
}

static void SilenceVoice(u8 attn_base)
{
    BufferBegin();
    /* Keep all 3 bytes as latch writes to avoid ambiguous data-byte side effects. */
    BufferPush((u8)(attn_base | 0x0F), (u8)(attn_base | 0x0F), (u8)(attn_base | 0x0F));
    BufferCommit();
}

static void Psg_ResetBases(void)
{
    /* Reset PSG base registers to a known state (hardware quirk workaround). */
    BufferBegin();
    BufferPush(0x80, 0x00, 0x9F);
    BufferPush(0xA0, 0x00, 0xBF);
    BufferPush(0xC0, 0x00, 0xDF);
    BufferPush(0xE0, 0xE0, 0xFF);
    BufferCommitBlocking(4000);
}

typedef struct {
    const u8 *ptr;
    const u8 *start;
    u32 next_frame;
    u32 gate_off_frame;
    u8 attn;
    u8 enabled;
    u8 freq_base;
    u8 attn_base;
    u8 shadow_b1;
    u8 shadow_b2;
    u8 shadow_b3;
    u8 note_active;
    u8 note_idx;
    u8 attn_cur;
    u8 gate_active;
    u8 env_on;
    u8 env_step;
    u8 env_speed;
    u8 env_counter;
    u8 env_curve_id;
    u8 env_index;
    u8 pitch_curve_id;
    u8 pitch_index;
    u8 pitch_counter;
    s16 pitch_offset;
    u8 vib_on;
    u8 vib_depth;
    u8 vib_speed;
    u8 vib_delay;
    u8 vib_delay_counter;
    u8 vib_counter;
    s8 vib_dir;
    u8 lfo_on;
    u8 lfo_wave;
    u8 lfo_hold;
    u8 lfo_rate;
    u8 lfo_depth;
    u8 lfo_hold_counter;
    u8 lfo_counter;
    s8 lfo_sign;
    s16 lfo_delta;
    u8 lfo2_on;
    u8 lfo2_wave;
    u8 lfo2_hold;
    u8 lfo2_rate;
    u8 lfo2_depth;
    u8 lfo2_hold_counter;
    u8 lfo2_counter;
    s8 lfo2_sign;
    s16 lfo2_delta;
    u8 lfo_algo;
    s16 lfo_pitch_delta;
    s8 lfo_attn_delta;
    u8 sweep_on;
    u16 sweep_end;
    s16 sweep_step;
    u8 sweep_speed;
    u8 sweep_counter;
    u16 base_div;
    u16 tone_div;
    u8 inst_id;
    u8 macro_id;
    u8 macro_step;
    u8 macro_counter;
    u8 macro_active;
    s16 macro_pitch;
#if BGM_DEBUG
    u32 dbg_events;
    u8 dbg_last_note;
    u8 dbg_last_cmd;
#endif
    u8 mode;
    /* ADSR state */
    u8 adsr_on;
    u8 adsr_attack;
    u8 adsr_decay;
    u8 adsr_sustain;
    u8 adsr_sustain_rate;
    u8 adsr_release;
    u8 adsr_phase;   /* 0=off, 1=ATK, 2=DEC, 3=SUS, 4=REL */
    u8 adsr_counter;
    u8 expression;   /* additional attn offset per-voice (0-15, 0=no reduction) */
    s16 pitch_bend;  /* additional divider offset (signed, 0=no bend) */
    const u8 *loop;
} BgmVoice;

static BgmVoice s_bgm_v0;
static BgmVoice s_bgm_v1;
static BgmVoice s_bgm_v2;
static BgmVoice s_bgm_vn;
static u8 s_bgm_loop;
static u8 s_bgm_speed;
static u8 s_bgm_gate_percent;
static u8 s_bgm_fade_speed;    /* 0 = no fade; >0 = frames between fade steps */
static u8 s_bgm_fade_counter;
static u8 s_bgm_fade_attn;     /* additional global attn offset (0-15) */
static u8 s_bgm_last_vbl;
static u32 s_bgm_song_frame;
static BgmDebug s_bgm_dbg;

static void BgmVoice_ApplyInstrument(BgmVoice *v, u8 inst_id)
{
    const BgmInstrument *inst;
    if (inst_id >= s_bgm_instrument_count) {
        inst_id = 0;
    }
    inst = &s_bgm_instruments[inst_id];
    v->inst_id = inst_id;
    v->attn = inst->attn;
    v->attn_cur = v->attn;
    v->env_on = inst->env_on;
    v->env_step = inst->env_step ? inst->env_step : 1;
    v->env_speed = inst->env_speed ? inst->env_speed : 1;
    v->env_counter = v->env_speed;
#if SOUNDS_ENABLE_ENV_CURVES
    v->env_curve_id = inst->env_curve_id;
    v->env_index = 0;
#else
    v->env_curve_id = 0;
    v->env_index = 0;
#endif
#if SOUNDS_ENABLE_PITCH_CURVES
    v->pitch_curve_id = inst->pitch_curve_id;
    v->pitch_index = 0;
    v->pitch_counter = v->env_speed;
    v->pitch_offset = 0;
#else
    v->pitch_curve_id = 0;
    v->pitch_index = 0;
    v->pitch_counter = 0;
    v->pitch_offset = 0;
#endif
    v->vib_on = inst->vib_on;
    v->vib_depth = inst->vib_depth;
    v->vib_speed = inst->vib_speed ? inst->vib_speed : 1;
    v->vib_delay = inst->vib_delay;
    v->vib_delay_counter = v->vib_delay;
    v->vib_counter = v->vib_speed;
    v->vib_dir = 1;
    v->lfo_on = inst->lfo_on ? 1 : 0;
    v->lfo_wave = inst->lfo_wave > 4 ? 4 : inst->lfo_wave;
    v->lfo_hold = inst->lfo_hold;
    v->lfo_rate = inst->lfo_rate;
    v->lfo_depth = inst->lfo_depth;
    v->lfo_hold_counter = v->lfo_hold;
    v->lfo_counter = v->lfo_rate;
    v->lfo_sign = 1;
    v->lfo_delta = 0;
    v->lfo2_on = inst->lfo2_on ? 1 : 0;
    v->lfo2_wave = inst->lfo2_wave > 4 ? 4 : inst->lfo2_wave;
    v->lfo2_hold = inst->lfo2_hold;
    v->lfo2_rate = inst->lfo2_rate;
    v->lfo2_depth = inst->lfo2_depth;
    v->lfo2_hold_counter = v->lfo2_hold;
    v->lfo2_counter = v->lfo2_rate;
    v->lfo2_sign = 1;
    v->lfo2_delta = 0;
    v->lfo_algo = inst->lfo_algo > 7 ? 7 : inst->lfo_algo;
    v->lfo_pitch_delta = 0;
    v->lfo_attn_delta = 0;
    if (v->lfo_depth == 0 || v->lfo_rate == 0) v->lfo_on = 0;
    if (v->lfo2_depth == 0 || v->lfo2_rate == 0) v->lfo2_on = 0;
    v->sweep_on = inst->sweep_on;
    v->sweep_end = inst->sweep_end ? inst->sweep_end : 1;
    v->sweep_step = inst->sweep_step;
    v->sweep_speed = inst->sweep_speed ? inst->sweep_speed : 1;
    v->sweep_counter = v->sweep_speed;
    /* Only the noise voice may use noise mode. */
    v->mode = (v->freq_base == 0xE0) ? 1 : 0;
#if SOUNDS_ENABLE_MACROS
    v->macro_id = inst->macro_id;
#else
    v->macro_id = 0;
#endif
    v->adsr_on = inst->adsr_on;
    v->adsr_attack = inst->adsr_attack;
    v->adsr_decay = inst->adsr_decay;
    v->adsr_sustain = inst->adsr_sustain;
    v->adsr_sustain_rate = inst->adsr_sustain_rate;
    v->adsr_release = inst->adsr_release;
    v->adsr_phase = 0;
    v->adsr_counter = 0;
}

static void BgmVoice_MacroReset(BgmVoice *v)
{
#if SOUNDS_ENABLE_MACROS
    v->macro_step = 0;
    v->macro_counter = 0;
    v->macro_pitch = 0;
    v->macro_active = (v->macro_id < s_bgm_macro_count) &&
        (s_bgm_macros[v->macro_id].count > 0);
    if (v->macro_active) {
        const BgmMacro *m = &s_bgm_macros[v->macro_id];
        const BgmMacroStep *s = &m->steps[0];
        if (s->frames == 0) {
            v->macro_active = 0;
            return;
        }
        v->macro_counter = s->frames;
        v->macro_pitch = s->pitch_delta;
        /* Keep ADSR as the sole attenuation owner when ADSR is active. */
        if (!v->adsr_on) {
            s16 attn = (s16)v->attn + (s16)s->attn_delta;
            if (attn < 0) attn = 0;
            if (attn > 15) attn = 15;
            v->attn_cur = (u8)attn;
        }
    }
#else
    v->macro_step = 0;
    v->macro_counter = 0;
    v->macro_pitch = 0;
    v->macro_active = 0;
#endif
}

static u8 BgmVoice_MacroTick(BgmVoice *v)
{
#if SOUNDS_ENABLE_MACROS
    u8 dirty = 0;
    if (!v->macro_active) {
        return 0;
    }
    if (v->macro_counter == 0) {
        const BgmMacro *m = &s_bgm_macros[v->macro_id];
        v->macro_step++;
        if (v->macro_step >= m->count) {
            v->macro_active = 0;
            return dirty;
        }
        {
            const BgmMacroStep *s = &m->steps[v->macro_step];
            if (s->frames == 0) {
                v->macro_active = 0;
                return dirty;
            }
            v->macro_counter = s->frames;
            v->macro_pitch = s->pitch_delta;
            /* Keep ADSR as the sole attenuation owner when ADSR is active. */
            if (!v->adsr_on) {
                s16 attn = (s16)v->attn + (s16)s->attn_delta;
                if (attn < 0) attn = 0;
                if (attn > 15) attn = 15;
                if (v->attn_cur != (u8)attn) {
                    v->attn_cur = (u8)attn;
                    dirty = 1;
                }
            }
        }
    }
    if (v->macro_counter > 0) {
        v->macro_counter--;
    }
    return dirty;
#else
    (void)v;
    return 0;
#endif
}

static void BgmVoice_ResetFx(BgmVoice *v)
{
    v->note_active = 0;
    v->note_idx = 0;
    v->gate_active = 0;
    v->gate_off_frame = 0;
    BgmVoice_ApplyInstrument(v, v->inst_id);
    v->macro_active = 0;
    v->macro_counter = 0;
    v->macro_step = 0;
    v->macro_pitch = 0;
    v->base_div = 1;
    v->tone_div = 1;
    v->pitch_index = 0;
    v->pitch_counter = v->env_speed;
    v->pitch_offset = 0;
    v->expression = 0;
    v->pitch_bend = 0;
    v->shadow_b1 = (u8)(v->attn_base | 0x0F);
    v->shadow_b2 = (u8)(v->attn_base | 0x0F);
    v->shadow_b3 = (u8)(v->attn_base | 0x0F);
}

static void BgmVoice_Reset(BgmVoice *v)
{
    v->ptr = 0;
    v->start = 0;
    v->next_frame = 0;
    v->gate_off_frame = 0;
    v->inst_id = (v->freq_base == 0xE0 && s_bgm_instrument_count > 1) ? 1 : 0;
    BgmVoice_ResetFx(v);
    v->enabled = 0;
    v->shadow_b1 = (u8)(v->attn_base | 0x0F);
    v->shadow_b2 = (u8)(v->attn_base | 0x0F);
    v->shadow_b3 = (u8)(v->attn_base | 0x0F);
#if BGM_DEBUG
    v->dbg_events = 0;
    v->dbg_last_note = 0;
    v->dbg_last_cmd = 0;
#endif
    v->loop = 0;
}

static void BgmVoice_StartEx(BgmVoice *v, const u8 *stream, u16 loop_offset)
{
    v->start = stream;
    v->ptr = stream;
    v->loop = (stream && loop_offset) ? (stream + loop_offset) : stream;
    v->next_frame = s_bgm_song_frame;
    v->enabled = (stream != 0);
    v->inst_id = (v->freq_base == 0xE0 && s_bgm_instrument_count > 1) ? 1 : 0;
    BgmVoice_ResetFx(v);
#if BGM_DEBUG
    v->dbg_events = 0;
    v->dbg_last_note = 0;
    v->dbg_last_cmd = 0;
#endif
}

static void BgmVoice_Stop(BgmVoice *v)
{
    v->enabled = 0;
    v->next_frame = s_bgm_song_frame;
    v->gate_active = 0;
    v->gate_off_frame = 0;
}

static void Bgm_ClearRestoreFlags(void)
{
    s_bgm_restore_ch[0] = 0;
    s_bgm_restore_ch[1] = 0;
    s_bgm_restore_ch[2] = 0;
    s_bgm_restore_ch[3] = 0;
}

static void Bgm_ClearSfxFlags(void)
{
    s_bgm_ch_used_by_sfx[0] = 0;
    s_bgm_ch_used_by_sfx[1] = 0;
    s_bgm_ch_used_by_sfx[2] = 0;
    s_bgm_ch_used_by_sfx[3] = 0;
}

static void BgmVoice_CommandSilence(BgmVoice *v, PsgCmd *cmd)
{
    v->note_active = 0;
    v->note_idx = 0;
    v->gate_active = 0;
    v->gate_off_frame = 0;
    v->shadow_b1 = (u8)(v->attn_base | 0x0F);
    v->shadow_b2 = (u8)(v->attn_base | 0x0F);
    v->shadow_b3 = (u8)(v->attn_base | 0x0F);
    cmd->valid = 1;
    cmd->b1 = v->shadow_b1;
    cmd->b2 = v->shadow_b2;
    cmd->b3 = v->shadow_b3;
}

static u16 BgmNoteToDiv(u8 note_idx)
{
    u8 idx;
    u8 lo;
    u8 hi;
    const u8 *table = s_bgm_note_table ? s_bgm_note_table : NOTE_TABLE;

    if (!table) {
        return 1;
    }
    if (note_idx == 0) {
        note_idx = 1;
    } else if (note_idx > NOTE_MAX_INDEX + 1) {
        note_idx = NOTE_MAX_INDEX + 1;
    }
    idx = (u8)(note_idx - 1);
    lo = table[idx * 2 + 0] & 0x0F;
    hi = table[idx * 2 + 1] & 0x3F;
    return (u16)(((u16)hi << 4) | (u16)lo);
}

static void BgmVoice_SetNote(BgmVoice *v, u8 note_idx)
{
    v->note_active = 1;
    v->note_idx = note_idx;
    if (v->adsr_on) {
        /* ADSR: start at silent (15), attack ramps down to target */
        v->attn_cur = 15;
        v->adsr_phase = 1; /* ATK */
        v->adsr_counter = v->adsr_attack;
    } else {
        v->attn_cur = v->attn;
    }
    v->env_counter = v->env_speed;
    v->env_index = 0;
    v->pitch_index = 0;
    v->pitch_counter = v->env_speed;
    v->pitch_offset = 0;
    v->vib_delay_counter = v->vib_delay;
    v->vib_counter = v->vib_speed;
    v->vib_dir = 1;
    v->lfo_counter = v->lfo_rate;
    v->lfo_sign = 1;
    v->lfo_delta = 0;
    v->sweep_counter = v->sweep_speed;
    BgmVoice_MacroReset(v);
    if (v->mode == 0) {
        v->base_div = BgmNoteToDiv(note_idx);
        v->tone_div = v->base_div;
    } else {
        v->base_div = 1;
        v->tone_div = 1;
    }
}

static void BgmVoice_CommandFromState(BgmVoice *v, PsgCmd *cmd)
{
    if (!v->note_active) {
        cmd->valid = 0;
        return;
    }
    {
        /* Apply expression + global fade offset */
        u8 final_attn = v->attn_cur;
        if (v->lfo_attn_delta != 0) {
            s16 la = (s16)final_attn + (s16)v->lfo_attn_delta;
            if (la < 0) la = 0;
            if (la > 15) la = 15;
            final_attn = (u8)la;
        }
        if (v->expression > 0) {
            u8 ea = (u8)(final_attn + v->expression);
            if (ea > 15) ea = 15;
            final_attn = ea;
        }
        if (s_bgm_fade_attn > 0) {
            u8 fa = (u8)(final_attn + s_bgm_fade_attn);
            if (fa > 15) fa = 15;
            final_attn = fa;
        }
        if (v->mode == 1) {
            PsgCmd ncmd;
            MakeNoiseCmdFromNote(v->note_idx, final_attn, &ncmd);
            v->shadow_b1 = ncmd.b1;
            v->shadow_b2 = ncmd.b2;
            v->shadow_b3 = ncmd.b3;
        } else {
            s16 vib_delta = 0;
            u16 div = v->tone_div;
            {
                s16 delta = 0;
                if (v->macro_pitch != 0) {
                    delta = (s16)(delta + v->macro_pitch);
                }
#if SOUNDS_ENABLE_PITCH_CURVES
                if (v->pitch_offset != 0) {
                    delta = (s16)(delta + v->pitch_offset);
                }
#endif
                if (v->pitch_bend != 0) {
                    delta = (s16)(delta + v->pitch_bend);
                }
                if (v->lfo_pitch_delta != 0) {
                    delta = (s16)(delta + v->lfo_pitch_delta);
                }
                if (delta != 0) {
                    s16 md = (s16)div + delta;
                    if (md < 1) md = 1;
                    if (md > 1023) md = 1023;
                    div = (u16)md;
                }
            }
            if (v->vib_on && v->vib_depth > 0 && v->vib_delay_counter == 0) {
                vib_delta = (s16)v->vib_depth * (s16)v->vib_dir;
            }
            if (vib_delta != 0) {
                s16 vd = (s16)div + vib_delta;
                if (vd < 1) vd = 1;
                if (vd > 1023) vd = 1023;
                div = (u16)vd;
            }
            v->shadow_b1 = (u8)(v->freq_base | (div & 0x0F));
            v->shadow_b2 = (u8)((div >> 4) & 0x3F);
            v->shadow_b3 = (u8)(v->attn_base | (final_attn & 0x0F));
        }
    }
    cmd->valid = 1;
    cmd->b1 = v->shadow_b1;
    cmd->b2 = v->shadow_b2;
    cmd->b3 = v->shadow_b3;
}

static u16 BgmMulDiv100(u16 value, u8 percent)
{
    u16 q = (u16)(value / 100u);
    u16 r = (u16)(value % 100u);
    u16 acc = (u16)(q * percent);
    acc = (u16)(acc + (u16)((r * percent) / 100u));
    return acc;
}

static s16 BgmClampS16(s16 value, s16 lo, s16 hi)
{
    if (value < lo) return lo;
    if (value > hi) return hi;
    return value;
}

static s16 BgmLfoStepWave(u8 wave, s16 cur, s8 *sign, s16 depth)
{
    s16 next;
    if (depth <= 0) {
        return 0;
    }
    switch (wave) {
    case 0: /* triangle */
        next = (s16)(cur + *sign);
        if (next >= depth) {
            next = depth;
            *sign = -1;
        } else if (next <= -depth) {
            next = (s16)-depth;
            *sign = 1;
        }
        return next;
    case 1: /* square */
        *sign = (*sign < 0) ? 1 : -1;
        return (s16)(depth * (s16)(*sign));
    case 2: /* saw */
        next = (s16)(cur + 1);
        if (next > depth) {
            next = (s16)-depth;
        }
        return next;
    case 3: /* sweep up */
        if (cur < depth) return (s16)(cur + 1);
        return depth;
    case 4: /* sweep down */
        if (cur > -depth) return (s16)(cur - 1);
        return (s16)-depth;
    default:
        return cur;
    }
}

static u8 BgmLfoTick(u8 on, u8 wave, u8 rate, u8 depth,
                     u8 *hold_counter, u8 *counter, s8 *sign, s16 *delta)
{
    s16 next;
    if (!on || depth == 0 || rate == 0) {
        if (*delta != 0) {
            *delta = 0;
            return 1;
        }
        return 0;
    }
    if (*hold_counter > 0) {
        (*hold_counter)--;
        if (*delta != 0) {
            *delta = 0;
            return 1;
        }
        return 0;
    }
    if (*counter == 0) {
        *counter = rate;
        next = BgmLfoStepWave((u8)(wave > 4 ? 4 : wave), *delta, sign, (s16)depth);
        if (next != *delta) {
            *delta = next;
            return 1;
        }
    } else {
        (*counter)--;
    }
    return 0;
}

static s8 BgmLfoToAttnDelta(s16 mod)
{
    s16 d = (s16)(mod / 16);
    if (d < -15) d = -15;
    if (d > 15) d = 15;
    return (s8)(-d);
}

static void BgmLfoResolve(BgmVoice *v)
{
    s16 l1 = v->lfo_delta;
    s16 l2 = v->lfo2_delta;
    s16 mix = (s16)(l1 + l2);
    mix = BgmClampS16(mix, -255, 255);

    switch (v->lfo_algo & 0x07) {
    default:
    case 0: /* none */
        v->lfo_pitch_delta = 0;
        v->lfo_attn_delta = 0;
        break;
    case 1: /* LFO1=tremolo, LFO2=vibrato */
        v->lfo_pitch_delta = l2;
        v->lfo_attn_delta = BgmLfoToAttnDelta(l1);
        break;
    case 2: /* FM blend on both */
        v->lfo_pitch_delta = mix;
        v->lfo_attn_delta = BgmLfoToAttnDelta(mix);
        break;
    case 3: /* AM blend + vibrato on LFO2 */
        v->lfo_pitch_delta = l2;
        v->lfo_attn_delta = BgmLfoToAttnDelta(mix);
        break;
    case 4: /* FM blend + tremolo on LFO1 */
        v->lfo_pitch_delta = mix;
        v->lfo_attn_delta = BgmLfoToAttnDelta(l1);
        break;
    case 5: /* AM blend only */
        v->lfo_pitch_delta = 0;
        v->lfo_attn_delta = BgmLfoToAttnDelta(mix);
        break;
    case 6: /* FM blend only */
        v->lfo_pitch_delta = mix;
        v->lfo_attn_delta = 0;
        break;
    case 7: /* AM-shaped vibrato */
        v->lfo_pitch_delta = (s16)(mix / 2);
        v->lfo_attn_delta = 0;
        break;
    }
}

static u8 BgmVoice_UpdateFx(BgmVoice *v)
{
    u8 dirty = 0;
    if (!v->note_active) {
        return 0;
    }

    if (BgmVoice_MacroTick(v)) {
        dirty = 1;
    }
#if SOUNDS_ENABLE_PITCH_CURVES
    if (v->pitch_curve_id < s_bgm_pitch_curve_count &&
        s_bgm_pitch_curves[v->pitch_curve_id].count > 0) {
        if (v->pitch_counter == 0) {
            const BgmPitchCurve *c = &s_bgm_pitch_curves[v->pitch_curve_id];
            u8 idx = v->pitch_index;
            if (idx >= c->count) {
                idx = (u8)(c->count - 1);
            } else {
                v->pitch_index++;
            }
            v->pitch_offset = c->steps[idx];
            v->pitch_counter = v->env_speed;
            dirty = 1;
        } else {
            v->pitch_counter--;
        }
    }
#endif

    /* --- ADSR state machine (replaces legacy env when active) --- */
    if (v->adsr_on && v->adsr_phase > 0) {
        switch (v->adsr_phase) {
        case 1: /* ATK: ramp 15 â†’ attn (louder) */
            if (v->adsr_attack == 0) {
                v->attn_cur = v->attn;
                v->adsr_phase = 2;
                v->adsr_counter = v->adsr_decay;
                dirty = 1;
            } else if (v->adsr_counter == 0) {
                if (v->attn_cur > v->attn) {
                    v->attn_cur--;
                    dirty = 1;
                }
                if (v->attn_cur <= v->attn) {
                    v->attn_cur = v->attn;
                    v->adsr_phase = 2;
                    v->adsr_counter = v->adsr_decay;
                } else {
                    v->adsr_counter = v->adsr_attack;
                }
            } else {
                v->adsr_counter--;
            }
            break;
        case 2: /* DEC: ramp attn â†’ sustain (quieter) */
        {
            u8 sus_target = v->adsr_sustain;
            if (sus_target < v->attn) sus_target = v->attn;
            if (v->adsr_decay == 0 || sus_target <= v->attn) {
                v->attn_cur = sus_target;
                v->adsr_phase = 3;
                v->adsr_counter = v->adsr_sustain_rate;
                dirty = 1;
            } else if (v->adsr_counter == 0) {
                if (v->attn_cur < sus_target) {
                    v->attn_cur++;
                    dirty = 1;
                }
                if (v->attn_cur >= sus_target) {
                    v->attn_cur = sus_target;
                    v->adsr_phase = 3;
                    v->adsr_counter = v->adsr_sustain_rate;
                } else {
                    v->adsr_counter = v->adsr_decay;
                }
            } else {
                v->adsr_counter--;
            }
            break;
        }
        case 3: /* SUS: optional sustain-rate fade while key is held */
            if (v->adsr_sustain_rate > 0) {
                if (v->adsr_counter == 0) {
                    if (v->attn_cur < 15) {
                        v->attn_cur++;
                        dirty = 1;
                    }
                    if (v->attn_cur >= 15) {
                        v->note_active = 0;
                        v->adsr_phase = 0;
                    } else {
                        v->adsr_counter = v->adsr_sustain_rate;
                    }
                } else {
                    v->adsr_counter--;
                }
            }
            break;
        case 4: /* REL: ramp cur â†’ 15 (silent) */
            if (v->adsr_release == 0) {
                v->attn_cur = 15;
                v->adsr_phase = 0;
                v->note_active = 0;
                dirty = 1;
            } else if (v->adsr_counter == 0) {
                if (v->attn_cur < 15) {
                    v->attn_cur++;
                    dirty = 1;
                }
                if (v->attn_cur >= 15) {
                    v->adsr_phase = 0;
                    v->note_active = 0;
                } else {
                    v->adsr_counter = v->adsr_release;
                }
            } else {
                v->adsr_counter--;
            }
            break;
        }
        /* When ADSR is active, skip only legacy env processing. */
        goto skip_legacy_env;
    }

    if (!v->env_on &&
        !(v->mode == 0 &&
          (v->sweep_on || v->vib_on ||
           (v->lfo_on && v->lfo_depth > 0) ||
           (v->lfo2_on && v->lfo2_depth > 0))) &&
        !dirty) {
        return 0;
    }
    if (v->env_on) {
        if (v->env_counter == 0) {
#if SOUNDS_ENABLE_ENV_CURVES
            if (v->env_curve_id < s_bgm_env_curve_count &&
                s_bgm_env_curves[v->env_curve_id].count > 0) {
                const BgmEnvCurve *c = &s_bgm_env_curves[v->env_curve_id];
                u8 idx = v->env_index;
                if (idx >= c->count) {
                    idx = (u8)(c->count - 1);
                } else {
                    v->env_index++;
                }
                {
                    s16 attn = (s16)v->attn + (s16)c->steps[idx];
                    if (attn < 0) attn = 0;
                    if (attn > 15) attn = 15;
                    if (v->attn_cur != (u8)attn) {
                        v->attn_cur = (u8)attn;
                        dirty = 1;
                    }
                }
            } else if (v->attn_cur < 15) {
                u8 next_attn = (u8)(v->attn_cur + v->env_step);
                if (next_attn > 15) next_attn = 15;
                v->attn_cur = next_attn;
                dirty = 1;
            }
#else
            if (v->attn_cur < 15) {
                u8 next_attn = (u8)(v->attn_cur + v->env_step);
                if (next_attn > 15) next_attn = 15;
                v->attn_cur = next_attn;
                dirty = 1;
            }
#endif
            v->env_counter = v->env_speed;
        } else {
            v->env_counter--;
        }
    }
skip_legacy_env:
    if (v->mode == 0 && v->sweep_on && v->sweep_step != 0) {
        if (v->sweep_counter == 0) {
            s32 nd = (s32)v->tone_div + (s32)v->sweep_step;
            if (nd < 1) nd = 1;
            if (nd > 1023) nd = 1023;
            v->tone_div = (u16)nd;
            v->sweep_counter = v->sweep_speed;
            dirty = 1;
            if (v->sweep_step > 0) {
                if (v->tone_div >= v->sweep_end) v->sweep_on = 0;
            } else {
                if (v->tone_div <= v->sweep_end) v->sweep_on = 0;
            }
        } else {
            v->sweep_counter--;
        }
    }
    if (v->mode == 0 && v->vib_on && v->vib_depth > 0) {
        if (v->vib_delay_counter > 0) {
            v->vib_delay_counter--;
            if (v->vib_delay_counter == 0) {
                v->vib_counter = v->vib_speed;
                v->vib_dir = 1;
                dirty = 1;
            }
        } else {
            if (v->vib_counter == 0) {
                v->vib_dir = (v->vib_dir < 0) ? 1 : -1;
                v->vib_counter = v->vib_speed;
                dirty = 1;
            } else {
                v->vib_counter--;
            }
        }
    }
    if (v->mode == 0) {
        u8 lfo_dirty = 0;
        s16 prev_pitch = v->lfo_pitch_delta;
        s8 prev_attn = v->lfo_attn_delta;

        if (BgmLfoTick(v->lfo_on, v->lfo_wave, v->lfo_rate, v->lfo_depth,
                       &v->lfo_hold_counter, &v->lfo_counter, &v->lfo_sign, &v->lfo_delta)) {
            lfo_dirty = 1;
        }
        if (BgmLfoTick(v->lfo2_on, v->lfo2_wave, v->lfo2_rate, v->lfo2_depth,
                       &v->lfo2_hold_counter, &v->lfo2_counter, &v->lfo2_sign, &v->lfo2_delta)) {
            lfo_dirty = 1;
        }
        BgmLfoResolve(v);
        if (v->lfo_pitch_delta != prev_pitch || v->lfo_attn_delta != prev_attn) {
            lfo_dirty = 1;
        }
        if (lfo_dirty) {
            dirty = 1;
        }
    } else if (v->lfo_pitch_delta != 0 || v->lfo_attn_delta != 0) {
        v->lfo_pitch_delta = 0;
        v->lfo_attn_delta = 0;
        dirty = 1;
    }
    return dirty;
}

static void BgmVoice_Step(BgmVoice *v, PsgCmd *cmd)
{
    u16 scaled;
    u32 song_frame = s_bgm_song_frame;
    cmd->valid = 0;
    if (!v->enabled || !v->ptr) {
        return;
    }
    if (v->gate_active && v->note_active && song_frame >= v->gate_off_frame) {
        BgmVoice_CommandSilence(v, cmd);
        return;
    }
    if (song_frame < v->next_frame) {
        if (BgmVoice_UpdateFx(v)) {
            BgmVoice_CommandFromState(v, cmd);
        }
        return;
    }

    while (v->enabled && song_frame >= v->next_frame) {
        u8 note = *v->ptr++;
        if (note == 0x00) {
            if (s_bgm_loop && (v->loop || v->start)) {
                v->ptr = v->loop ? v->loop : v->start;
                if (v->ptr && *v->ptr != 0x00) {
                    continue;
                }
                BgmVoice_CommandSilence(v, cmd);
                v->next_frame = song_frame + 1;
#if BGM_DEBUG
                v->dbg_events++;
                v->dbg_last_note = 0;
                v->dbg_last_cmd = 3;
#endif
                return;
            }
            BgmVoice_CommandSilence(v, cmd);
            BgmVoice_Stop(v);
#if BGM_DEBUG
            v->dbg_events++;
            v->dbg_last_note = 0;
            v->dbg_last_cmd = 3;
#endif
            return;
        }

        if (note == 0xFF) {
            scaled = (u16)(*v->ptr++) * (u16)s_bgm_speed;
            if (scaled == 0) {
                scaled = 1;
            }
            v->next_frame += scaled;
            if (v->adsr_on && v->adsr_release > 0 && v->note_active) {
                /* Start ADSR release phase instead of immediate silence */
                v->adsr_phase = 4; /* REL */
                v->adsr_counter = v->adsr_release;
                BgmVoice_CommandFromState(v, cmd);
            } else {
                BgmVoice_CommandSilence(v, cmd);
            }
#if BGM_DEBUG
            v->dbg_events++;
            v->dbg_last_note = 0xFF;
            v->dbg_last_cmd = 2;
#endif
            return;
        }

        if (note >= BGM_OP_SET_ATTN) {
            switch (note) {
            case BGM_OP_SET_ATTN: {
                u8 attn = *v->ptr++;
                if (attn > 15) attn = 15;
                v->attn = attn;
                break;
            }
            case BGM_OP_SET_ENV: {
                u8 step = *v->ptr++;
                u8 speed = *v->ptr++;
                if (step > 4) step = 4;
                if (speed < 1) speed = 1;
                if (speed > 10) speed = 10;
                v->env_on = (step > 0) ? 1 : 0;
                v->env_step = step ? step : 1;
                v->env_speed = speed;
                v->env_counter = v->env_speed;
                v->env_index = 0;
#if SOUNDS_ENABLE_PITCH_CURVES
                v->pitch_index = 0;
                v->pitch_counter = v->env_speed;
                v->pitch_offset = 0;
#endif
                break;
            }
            case BGM_OP_SET_VIB: {
                u8 depth = *v->ptr++;
                u8 speed = *v->ptr++;
                u8 delay = *v->ptr++;
                if (speed < 1) speed = 1;
                if (speed > 30) speed = 30;
                v->vib_on = (depth > 0) ? 1 : 0;
                v->vib_depth = depth;
                v->vib_speed = speed;
                v->vib_delay = delay;
                v->vib_delay_counter = v->vib_delay;
                v->vib_counter = v->vib_speed;
                v->vib_dir = 1;
                break;
            }
            case BGM_OP_SET_SWEEP: {
                u16 end = (u16)v->ptr[0] | ((u16)v->ptr[1] << 8);
                s8 step = (s8)v->ptr[2];
                u8 speed = v->ptr[3];
                v->ptr += 4;
                if (speed < 1) speed = 1;
                if (speed > 30) speed = 30;
                if (end < 1) end = 1;
                if (end > 1023) end = 1023;
                v->sweep_on = (step != 0) ? 1 : 0;
                v->sweep_end = end;
                v->sweep_step = (s16)step;
                v->sweep_speed = speed;
                v->sweep_counter = v->sweep_speed;
                break;
            }
            case BGM_OP_SET_INST:
            {
                u8 inst_id = *v->ptr++;
                BgmVoice_ApplyInstrument(v, inst_id);
                break;
            }
            case BGM_OP_SET_PAN:
            {
                /* Reserved for stereo pan (Phase 3). Current driver is mono-safe:
                 * consume payload and keep neutral rendering. */
                (void)(*v->ptr++);
                break;
            }
            case BGM_OP_HOST_CMD:
            {
                u8 type = *v->ptr++;
                u8 data = *v->ptr++;
                if (type == 0) {
                    /* Fade out */
                    s_bgm_fade_speed = data;
                    s_bgm_fade_counter = data;
                } else if (type == 1) {
                    /* Tempo change */
                    if (data < 1) data = 1;
                    s_bgm_speed = data;
                }
                break;
            }
            case BGM_OP_SET_EXPR:
            {
                u8 expr = *v->ptr++;
                if (expr > 15) expr = 15;
                v->expression = expr;
                break;
            }
            case BGM_OP_PITCH_BEND:
            {
                u8 lo = *v->ptr++;
                u8 hi = *v->ptr++;
                v->pitch_bend = (s16)((u16)lo | ((u16)hi << 8));
                break;
            }
            case BGM_OP_SET_ADSR:
            {
                u8 a = *v->ptr++;
                u8 d = *v->ptr++;
                u8 s = *v->ptr++;
                u8 r = *v->ptr++;
                v->adsr_on = 1;
                v->adsr_attack = a;
                v->adsr_decay = d;
                v->adsr_sustain = s > 15 ? 15 : s;
                v->adsr_sustain_rate = 0;
                v->adsr_release = r;
                v->adsr_phase = 0;
                v->adsr_counter = 0;
                break;
            }
            case BGM_OP_SET_LFO:
            {
                u8 wave = *v->ptr++;
                u8 rate = *v->ptr++;
                u8 depth = *v->ptr++;
                v->lfo_on = (depth > 0 && rate > 0) ? 1 : 0;
                v->lfo_wave = wave > 4 ? 4 : wave;
                v->lfo_hold = 0;
                v->lfo_rate = rate;
                v->lfo_depth = depth;
                v->lfo_hold_counter = 0;
                v->lfo_counter = rate;
                v->lfo_sign = 1;
                v->lfo_delta = 0;
                v->lfo2_on = 0;
                v->lfo2_delta = 0;
                v->lfo_pitch_delta = 0;
                v->lfo_attn_delta = 0;
                v->lfo_algo = 1;
                break;
            }
            case BGM_OP_EXT:
            {
                u8 sub = *v->ptr++;
                if (sub == BGM_EXT_SET_ADSR5) {
                    u8 a = *v->ptr++;
                    u8 d = *v->ptr++;
                    u8 sl = *v->ptr++;
                    u8 sr = *v->ptr++;
                    u8 rr = *v->ptr++;
                    v->adsr_on = 1;
                    v->adsr_attack = a;
                    v->adsr_decay = d;
                    v->adsr_sustain = sl > 15 ? 15 : sl;
                    v->adsr_sustain_rate = sr;
                    v->adsr_release = rr;
                    v->adsr_phase = 0;
                    v->adsr_counter = 0;
                } else if (sub == BGM_EXT_SET_MOD2) {
                    v->lfo_algo = (u8)(*v->ptr++ & 0x07);
                    v->lfo_on = *v->ptr++ ? 1 : 0;
                    v->lfo_wave = (u8)(*v->ptr++ & 0x07);
                    if (v->lfo_wave > 4) v->lfo_wave = 4;
                    v->lfo_hold = *v->ptr++;
                    v->lfo_rate = *v->ptr++;
                    v->lfo_depth = *v->ptr++;
                    v->lfo2_on = *v->ptr++ ? 1 : 0;
                    v->lfo2_wave = (u8)(*v->ptr++ & 0x07);
                    if (v->lfo2_wave > 4) v->lfo2_wave = 4;
                    v->lfo2_hold = *v->ptr++;
                    v->lfo2_rate = *v->ptr++;
                    v->lfo2_depth = *v->ptr++;
                    v->lfo_hold_counter = v->lfo_hold;
                    v->lfo_counter = v->lfo_rate;
                    v->lfo_sign = 1;
                    v->lfo_delta = 0;
                    v->lfo2_hold_counter = v->lfo2_hold;
                    v->lfo2_counter = v->lfo2_rate;
                    v->lfo2_sign = 1;
                    v->lfo2_delta = 0;
                    v->lfo_pitch_delta = 0;
                    v->lfo_attn_delta = 0;
                    if (v->lfo_depth == 0 || v->lfo_rate == 0) v->lfo_on = 0;
                    if (v->lfo2_depth == 0 || v->lfo2_rate == 0) v->lfo2_on = 0;
                } else {
                    /* Unknown ext subcommand: consume one byte guard to avoid lock. */
                    v->ptr++;
                }
                break;
            }
            case BGM_OP_SET_ENV_CURVE:
            {
                u8 curve_id = *v->ptr++;
#if SOUNDS_ENABLE_ENV_CURVES
                v->env_curve_id = curve_id;
                v->env_index = 0;
#else
                (void)curve_id;
#endif
                break;
            }
            case BGM_OP_SET_PITCH_CURVE:
            {
                u8 curve_id = *v->ptr++;
#if SOUNDS_ENABLE_PITCH_CURVES
                v->pitch_curve_id = curve_id;
                v->pitch_index = 0;
                v->pitch_counter = v->env_speed;
                v->pitch_offset = 0;
#else
                (void)curve_id;
#endif
                break;
            }
            case BGM_OP_SET_MACRO:
            {
                u8 mid = *v->ptr++;
#if SOUNDS_ENABLE_MACROS
                v->macro_id = mid;
#else
                (void)mid;
#endif
                break;
            }
            default:
                v->ptr++;
                break;
            }
            continue;
        }

        scaled = (u16)(*v->ptr++) * (u16)s_bgm_speed;
        if (scaled == 0) {
            scaled = 1;
        }
        v->next_frame += scaled;

        if (note > NOTE_MAX_INDEX + 1) {
            BgmVoice_CommandSilence(v, cmd);
#if BGM_DEBUG
            v->dbg_events++;
            v->dbg_last_note = note;
            v->dbg_last_cmd = 2;
#endif
            return;
        }
        BgmVoice_SetNote(v, note);
        if (s_bgm_gate_percent < 100) {
            u16 gate_frames = BgmMulDiv100(scaled, s_bgm_gate_percent);
            if (gate_frames < 1) gate_frames = 1;
            if (gate_frames >= scaled) {
                v->gate_active = 0;
            } else {
                v->gate_active = 1;
                v->gate_off_frame = song_frame + (u32)gate_frames;
            }
        } else {
            v->gate_active = 0;
        }
        BgmVoice_CommandFromState(v, cmd);
#if BGM_DEBUG
        v->dbg_events++;
        v->dbg_last_note = note;
        v->dbg_last_cmd = 1;
#endif
        return;
    }
}

void Sounds_ResetState(void)
{
    u16 i;

    SND_COUNT = 0;
    s_sound_drops = 0;
    s_sound_fault = 0;
    s_sound_last_sfx = 0xFF;
    s_freq_base[0] = 0x80;
    s_freq_base[1] = 0xA0;
    s_freq_base[2] = 0xC0;
    s_freq_base[3] = 0xE0;
    s_attn_base[0] = 0x90;
    s_attn_base[1] = 0xB0;
    s_attn_base[2] = 0xD0;
    s_attn_base[3] = 0xF0;
    s_sfxTimer[0] = 0;
    s_sfxTimer[1] = 0;
    s_sfxTimer[2] = 0;
    s_sfxTimer[3] = 0;
    s_sfx_cmd[0].valid = 0;
    s_sfx_cmd[1].valid = 0;
    s_sfx_cmd[2].valid = 0;
    s_sfx_cmd[3].valid = 0;
    for (i = 0; i < 4; i++) {
        s_psg_shadow[i].valid = 0;
        s_psg_shadow[i].b1 = (u8)(s_attn_base[i] | 0x0F);
        s_psg_shadow[i].b2 = (u8)(s_attn_base[i] | 0x0F);
        s_psg_shadow[i].b3 = (u8)(s_attn_base[i] | 0x0F);
        s_psg_pending[i].valid = 0;
        s_psg_pending[i].b1 = s_psg_shadow[i].b1;
        s_psg_pending[i].b2 = s_psg_shadow[i].b2;
        s_psg_pending[i].b3 = s_psg_shadow[i].b3;
    }
    s_psg_pending_mask = 0;
    s_psg_commit_mask = 0;
    s_sfx_end_pending[0] = 0;
    s_sfx_end_pending[1] = 0;
    s_sfx_end_pending[2] = 0;
    s_sfx_end_pending[3] = 0;
    for (i = 0; i < 3; i++) {
        s_sfx_tone_div_base[i] = 1;
        s_sfx_tone_div_cur[i] = 1;
        s_sfx_tone_attn_base[i] = 15;
        s_sfx_tone_attn_cur[i] = 15;
        s_sfx_tone_sw_end[i] = 1;
        s_sfx_tone_sw_step[i] = 0;
        s_sfx_tone_sw_dir[i] = 1;
        s_sfx_tone_sw_speed[i] = 1;
        s_sfx_tone_sw_counter[i] = 0;
        s_sfx_tone_sw_on[i] = 0;
        s_sfx_tone_sw_ping[i] = 0;
        s_sfx_tone_env_on[i] = 0;
        s_sfx_tone_env_step[i] = 1;
        s_sfx_tone_env_spd[i] = 1;
        s_sfx_tone_env_counter[i] = 0;
    }
    s_sfx_noise_val = 0;
    s_sfx_noise_attn_base = 15;
    s_sfx_noise_attn_cur = 15;
    s_sfx_noise_env_on = 0;
    s_sfx_noise_env_step = 1;
    s_sfx_noise_env_spd = 1;
    s_sfx_noise_env_counter = 0;
    s_sfx_noise_burst = 0;
    s_sfx_noise_burst_dur = 0;
    s_sfx_noise_burst_counter = 0;
    s_sfx_noise_burst_off = 0;
    s_sfx_active_mask = 0;
    s_bgm_note_table = NOTE_TABLE;
    s_bgm_v0.freq_base = 0x80;
    s_bgm_v0.attn_base = 0x90;
    BgmVoice_Reset(&s_bgm_v0);
    s_bgm_v1.freq_base = 0xA0;
    s_bgm_v1.attn_base = 0xB0;
    BgmVoice_Reset(&s_bgm_v1);
    s_bgm_v2.freq_base = 0xC0;
    s_bgm_v2.attn_base = 0xD0;
    BgmVoice_Reset(&s_bgm_v2);
    s_bgm_vn.freq_base = 0xE0;
    s_bgm_vn.attn_base = 0xF0;
    BgmVoice_Reset(&s_bgm_vn);
    s_bgm_vn.inst_id = 1;
    BgmVoice_ApplyInstrument(&s_bgm_vn, s_bgm_vn.inst_id);
    s_bgm_loop = 0;
    s_bgm_speed = 1;
    s_bgm_gate_percent = 100;
    s_bgm_fade_speed = 0;
    s_bgm_fade_counter = 0;
    s_bgm_fade_attn = 0;
    s_bgm_last_vbl = g_vb_counter;
    s_bgm_song_frame = 0;
    s_bgm_ch_used_by_sfx[0] = 0;
    s_bgm_ch_used_by_sfx[1] = 0;
    s_bgm_ch_used_by_sfx[2] = 0;
    s_bgm_ch_used_by_sfx[3] = 0;
    s_bgm_restore_ch[0] = 0;
    s_bgm_restore_ch[1] = 0;
    s_bgm_restore_ch[2] = 0;
    s_bgm_restore_ch[3] = 0;
    Bgm_DebugReset();
    Psg_ResetBases();
}

u8 Sounds_DebugFault(void)
{
    return s_sound_fault;
}

u16 Sounds_DebugDrops(void)
{
    return s_sound_drops;
}

u8 Sounds_DebugLastSfx(void)
{
    return s_sound_last_sfx;
}

void Sounds_Init(void)
{
    u8 *ram;
    u16 i;

    SOUNDCPU_CTRL = 0xAAAA;

    ram = (u8 *)0x7000;
    for (i = 0; i < sizeof(s_z80drv); i++) {
        ram[i] = s_z80drv[i];
    }

    SOUNDCPU_CTRL = 0x5555;
    Sounds_ResetState();
}

void Sounds_Update(void)
{
    Sfx_Update();
    Bgm_Update();
}

void Sfx_Update(void)
{
    u8 ch;
    if (s_sfx_active_mask == 0) {
        return;
    }
    for (ch = 0; ch < 3; ch++) {
        if (s_sfxTimer[ch] > 0) {
            u8 dirty = 0;
            if (s_sfx_tone_sw_on[ch]) {
                if (s_sfx_tone_sw_counter[ch] == 0) {
                    s32 v = (s32)s_sfx_tone_div_cur[ch] +
                            (s32)(s_sfx_tone_sw_step[ch] * s_sfx_tone_sw_dir[ch]);
                    if (s_sfx_tone_sw_ping[ch]) {
                        s32 minv = (s32)((s_sfx_tone_div_base[ch] < s_sfx_tone_sw_end[ch])
                            ? s_sfx_tone_div_base[ch] : s_sfx_tone_sw_end[ch]);
                        s32 maxv = (s32)((s_sfx_tone_div_base[ch] < s_sfx_tone_sw_end[ch])
                            ? s_sfx_tone_sw_end[ch] : s_sfx_tone_div_base[ch]);
                        if (v <= minv) {
                            v = minv;
                            s_sfx_tone_sw_dir[ch] = 1;
                        } else if (v >= maxv) {
                            v = maxv;
                            s_sfx_tone_sw_dir[ch] = -1;
                        }
                    } else {
                        if (s_sfx_tone_sw_dir[ch] < 0 && v <= (s32)s_sfx_tone_sw_end[ch]) {
                            v = s_sfx_tone_sw_end[ch];
                            s_sfx_tone_sw_on[ch] = 0;
                        } else if (s_sfx_tone_sw_dir[ch] > 0 && v >= (s32)s_sfx_tone_sw_end[ch]) {
                            v = s_sfx_tone_sw_end[ch];
                            s_sfx_tone_sw_on[ch] = 0;
                        }
                    }
                    if (v < 1) v = 1;
                    if (v > 1023) v = 1023;
                    s_sfx_tone_div_cur[ch] = (u16)v;
                    s_sfx_tone_sw_counter[ch] = s_sfx_tone_sw_speed[ch];
                    dirty = 1;
                } else {
                    s_sfx_tone_sw_counter[ch]--;
                }
            }
            if (s_sfx_tone_env_on[ch]) {
                if (s_sfx_tone_env_counter[ch] == 0) {
                    if (s_sfx_tone_attn_cur[ch] < 15) {
                        u8 next_attn = (u8)(s_sfx_tone_attn_cur[ch] + s_sfx_tone_env_step[ch]);
                        if (next_attn > 15) next_attn = 15;
                        s_sfx_tone_attn_cur[ch] = next_attn;
                        dirty = 1;
                    }
                    s_sfx_tone_env_counter[ch] = s_sfx_tone_env_spd[ch];
                } else {
                    s_sfx_tone_env_counter[ch]--;
                }
            }
            if (dirty) {
                MakeToneCmd(ch, s_sfx_tone_div_cur[ch], s_sfx_tone_attn_cur[ch], &s_sfx_cmd[ch]);
            }
            s_sfxTimer[ch]--;
            if (s_sfxTimer[ch] == 0) {
                MakeSilenceCmd(s_attn_base[ch], &s_sfx_cmd[ch]);
                s_sfx_end_pending[ch] = 1;
                s_bgm_restore_ch[ch] = 1;
                s_sfx_tone_sw_on[ch] = 0;
                s_sfx_tone_env_on[ch] = 0;
                s_sfx_active_mask &= (u8)~(1u << ch);
            }
        }
    }
    if (s_sfxTimer[3] > 0) {
        u8 dirty = 0;
        if (s_sfx_noise_env_on) {
            if (s_sfx_noise_env_counter == 0) {
                if (s_sfx_noise_attn_cur < 15) {
                    u8 next_attn = (u8)(s_sfx_noise_attn_cur + s_sfx_noise_env_step);
                    if (next_attn > 15) next_attn = 15;
                    s_sfx_noise_attn_cur = next_attn;
                    dirty = 1;
                }
                s_sfx_noise_env_counter = s_sfx_noise_env_spd;
            } else {
                s_sfx_noise_env_counter--;
            }
        }
        if (s_sfx_noise_burst) {
            if (s_sfx_noise_burst_counter == 0) {
                s_sfx_noise_burst_off = (u8)(!s_sfx_noise_burst_off);
                s_sfx_noise_burst_counter = s_sfx_noise_burst_off ? 1 : s_sfx_noise_burst_dur;
                dirty = 1;
            } else {
                s_sfx_noise_burst_counter--;
            }
        }
        if (dirty) {
            if (s_sfx_noise_burst && s_sfx_noise_burst_off) {
                MakeSilenceCmd(s_attn_base[3], &s_sfx_cmd[3]);
            } else {
                MakeNoiseCmd(s_sfx_noise_val, s_sfx_noise_attn_cur, &s_sfx_cmd[3]);
            }
        }
        s_sfxTimer[3]--;
        if (s_sfxTimer[3] == 0) {
            MakeSilenceCmd(s_attn_base[3], &s_sfx_cmd[3]);
            s_sfx_end_pending[3] = 1;
            s_bgm_restore_ch[3] = 1;
            s_sfx_noise_env_on = 0;
            s_sfx_noise_burst = 0;
            s_sfx_noise_burst_off = 0;
            s_sfx_active_mask &= (u8)~(1u << 3);
        }
    }
}

/* Sfx_Play is intentionally a no-op in the clean driver.
 * Define SFX_PLAY_EXTERNAL to provide your own mapping, or use
 * Sfx_PlayPresetTable for data-driven presets. */
#ifndef SFX_PLAY_EXTERNAL
void Sfx_Play(u8 id)
{
    s_sound_last_sfx = id;
    (void)id;
}
#endif

void Sfx_PlayPreset(const SfxPreset *preset)
{
    if (!preset) {
        return;
    }
    if (preset->kind == SFX_PRESET_TONE) {
        const SfxTonePreset *t = &preset->u.tone;
        Sfx_PlayToneEx(t->ch, t->divider, t->attn, t->frames,
                       t->sw_end, t->sw_step, t->sw_speed, t->sw_ping, t->sw_on,
                       t->env_on, t->env_step, t->env_spd);
    } else if (preset->kind == SFX_PRESET_NOISE) {
        const SfxNoisePreset *n = &preset->u.noise;
        Sfx_PlayNoiseEx(n->rate, n->type, n->attn, n->frames,
                        n->burst, n->burst_dur, n->env_on, n->env_step, n->env_spd);
    }
}

void Sfx_PlayPresetTable(const SfxPreset *table, u8 count, u8 id)
{
    if (!table || count == 0 || id >= count) {
        return;
    }
    s_sound_last_sfx = id;
    Sfx_PlayPreset(&table[id]);
}

void Sfx_PlayToneCh(u8 ch, u16 divider, u8 attn, u8 frames)
{
    if (ch > 2) {
        return;
    }
    if (divider < 1) divider = 1;
    if (divider > 1023) divider = 1023;
    if (attn > 15) attn = 15;
    s_sfx_tone_div_base[ch] = divider;
    s_sfx_tone_div_cur[ch] = divider;
    s_sfx_tone_attn_base[ch] = attn;
    s_sfx_tone_attn_cur[ch] = attn;
    s_sfx_tone_sw_on[ch] = 0;
    s_sfx_tone_env_on[ch] = 0;
    s_sfx_tone_sw_counter[ch] = 0;
    s_sfx_tone_env_counter[ch] = 0;
    MakeToneCmd(ch, divider, attn, &s_sfx_cmd[ch]);
    s_sfxTimer[ch] = frames;
    if (frames > 0) {
        s_sfx_active_mask |= (u8)(1u << ch);
        s_sfx_end_pending[ch] = 0;
        s_bgm_ch_used_by_sfx[ch] = 1;
        s_bgm_restore_ch[ch] = 0;
    } else {
        /* One-shot write this frame, then release channel next frame. */
        s_sfx_active_mask &= (u8)~(1u << ch);
        s_sfx_end_pending[ch] = 1;
        s_bgm_ch_used_by_sfx[ch] = 1;
        s_bgm_restore_ch[ch] = 1;
    }
}

void Sfx_PlayToneEx(u8 ch, u16 divider, u8 attn, u8 frames,
                    u16 sw_end, s16 sw_step, u8 sw_speed, u8 sw_ping, u8 sw_on,
                    u8 env_on, u8 env_step, u8 env_spd)
{
    if (ch > 2) {
        return;
    }
    if (divider < 1) divider = 1;
    if (divider > 1023) divider = 1023;
    if (attn > 15) attn = 15;
    if (sw_end < 1) sw_end = 1;
    if (sw_end > 1023) sw_end = 1023;
    if (sw_on && sw_step == 0) sw_step = 1;
    if (sw_speed < 1) sw_speed = 1;
    if (sw_speed > 30) sw_speed = 30;
    if (env_step < 1) env_step = 1;
    if (env_step > 4) env_step = 4;
    if (env_spd < 1) env_spd = 1;
    if (env_spd > 10) env_spd = 10;

    s_sfx_tone_div_base[ch] = divider;
    s_sfx_tone_div_cur[ch] = divider;
    s_sfx_tone_attn_base[ch] = attn;
    s_sfx_tone_attn_cur[ch] = attn;
    s_sfx_tone_sw_end[ch] = sw_end;
    if (sw_step < 0) {
        s_sfx_tone_sw_step[ch] = (s16)(-sw_step);
        s_sfx_tone_sw_dir[ch] = -1;
    } else {
        s_sfx_tone_sw_step[ch] = sw_step;
        s_sfx_tone_sw_dir[ch] = 1;
    }
    s_sfx_tone_sw_speed[ch] = sw_speed;
    s_sfx_tone_sw_counter[ch] = 0;
    s_sfx_tone_sw_on[ch] = sw_on ? 1 : 0;
    s_sfx_tone_sw_ping[ch] = sw_ping ? 1 : 0;
    s_sfx_tone_env_on[ch] = env_on ? 1 : 0;
    s_sfx_tone_env_step[ch] = env_step;
    s_sfx_tone_env_spd[ch] = env_spd;
    s_sfx_tone_env_counter[ch] = 0;

    MakeToneCmd(ch, divider, attn, &s_sfx_cmd[ch]);
    s_sfxTimer[ch] = frames;
    if (frames > 0) {
        s_sfx_active_mask |= (u8)(1u << ch);
        s_sfx_end_pending[ch] = 0;
        s_bgm_ch_used_by_sfx[ch] = 1;
        s_bgm_restore_ch[ch] = 0;
    } else {
        /* One-shot write this frame, then release channel next frame. */
        s_sfx_active_mask &= (u8)~(1u << ch);
        s_sfx_end_pending[ch] = 1;
        s_bgm_ch_used_by_sfx[ch] = 1;
        s_bgm_restore_ch[ch] = 1;
    }
}

void Sfx_PlayNoise(u8 noise_val, u8 attn, u8 frames)
{
    if (attn > 15) attn = 15;
    s_sfx_noise_val = (u8)(noise_val & 0x07);
    s_sfx_noise_attn_base = attn;
    s_sfx_noise_attn_cur = attn;
    s_sfx_noise_env_on = 0;
    s_sfx_noise_env_counter = 0;
    s_sfx_noise_burst = 0;
    s_sfx_noise_burst_dur = 0;
    s_sfx_noise_burst_counter = 0;
    s_sfx_noise_burst_off = 0;
    MakeNoiseCmd(s_sfx_noise_val, attn, &s_sfx_cmd[3]);
    s_sfxTimer[3] = frames;
    if (frames > 0) {
        s_sfx_active_mask |= (u8)(1u << 3);
        s_sfx_end_pending[3] = 0;
        s_bgm_ch_used_by_sfx[3] = 1;
        s_bgm_restore_ch[3] = 0;
    } else {
        /* One-shot write this frame, then release channel next frame. */
        s_sfx_active_mask &= (u8)~(1u << 3);
        s_sfx_end_pending[3] = 1;
        s_bgm_ch_used_by_sfx[3] = 1;
        s_bgm_restore_ch[3] = 1;
    }
}

void Sfx_PlayNoiseEx(u8 rate, u8 type, u8 attn, u8 frames,
                     u8 burst, u8 burst_dur,
                     u8 env_on, u8 env_step, u8 env_spd)
{
    u8 noise_val;
    if (rate > 3) rate = 3;
    if (type > 1) type = 1;
    if (attn > 15) attn = 15;
    if (burst_dur < 1) burst_dur = 1;
    if (burst_dur > 30) burst_dur = 30;
    if (env_step < 1) env_step = 1;
    if (env_step > 4) env_step = 4;
    if (env_spd < 1) env_spd = 1;
    if (env_spd > 10) env_spd = 10;

    noise_val = (u8)(((type & 0x01) << 2) | (rate & 0x03));
    s_sfx_noise_val = noise_val;
    s_sfx_noise_attn_base = attn;
    s_sfx_noise_attn_cur = attn;
    s_sfx_noise_env_on = env_on ? 1 : 0;
    s_sfx_noise_env_step = env_step;
    s_sfx_noise_env_spd = env_spd;
    s_sfx_noise_env_counter = 0;
    s_sfx_noise_burst = burst ? 1 : 0;
    s_sfx_noise_burst_dur = burst_dur;
    s_sfx_noise_burst_counter = burst_dur;
    s_sfx_noise_burst_off = 0;

    MakeNoiseCmd(noise_val, attn, &s_sfx_cmd[3]);
    if (frames == 0 && s_sfx_noise_burst) {
        frames = s_sfx_noise_burst_dur;
    }
    s_sfxTimer[3] = frames;
    if (s_sfxTimer[3] > 0) {
        s_sfx_active_mask |= (u8)(1u << 3);
        s_sfx_end_pending[3] = 0;
        s_bgm_ch_used_by_sfx[3] = 1;
        s_bgm_restore_ch[3] = 0;
    } else {
        /* One-shot write this frame, then release channel next frame. */
        s_sfx_active_mask &= (u8)~(1u << 3);
        s_sfx_end_pending[3] = 1;
        s_bgm_ch_used_by_sfx[3] = 1;
        s_bgm_restore_ch[3] = 1;
    }
}

void Sfx_Stop(void)
{
    u8 i;
    for (i = 0; i < 4; i++) {
        s_sfxTimer[i] = 0;
        MakeSilenceCmd(s_attn_base[i], &s_sfx_cmd[i]);
        s_sfx_end_pending[i] = 1;
        s_bgm_restore_ch[i] = 1;
        s_bgm_ch_used_by_sfx[i] = 0;
        if (i < 3) {
            s_sfx_tone_sw_on[i] = 0;
            s_sfx_tone_env_on[i] = 0;
        }
    }
    s_sfx_noise_env_on = 0;
    s_sfx_noise_burst = 0;
    s_sfx_noise_burst_off = 0;
    s_sfx_noise_burst_counter = 0;
    s_sfx_active_mask = 0;
}

static void Bgm_ResetFadeState(void)
{
    s_bgm_fade_speed = 0;
    s_bgm_fade_counter = 0;
    s_bgm_fade_attn = 0;
}

void Bgm_Start(const u8 *stream)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream, 0);
    BgmVoice_Stop(&s_bgm_v1);
    BgmVoice_Stop(&s_bgm_v2);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = 0;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_SetNoteTable(const u8 *note_table)
{
    if (note_table) {
        s_bgm_note_table = note_table;
    } else {
        s_bgm_note_table = NOTE_TABLE;
    }
}

void Bgm_StartLoop(const u8 *stream)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream, 0);
    BgmVoice_Stop(&s_bgm_v1);
    BgmVoice_Stop(&s_bgm_v2);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartLoop2(const u8 *stream0, const u8 *stream1)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream0, 0);
    BgmVoice_StartEx(&s_bgm_v1, stream1, 0);
    BgmVoice_Stop(&s_bgm_v2);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartLoop3(const u8 *stream0, const u8 *stream1, const u8 *stream2)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream0, 0);
    BgmVoice_StartEx(&s_bgm_v1, stream1, 0);
    BgmVoice_StartEx(&s_bgm_v2, stream2, 0);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartLoop4(const u8 *stream0, const u8 *stream1, const u8 *stream2, const u8 *streamN)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream0, 0);
    BgmVoice_StartEx(&s_bgm_v1, stream1, 0);
    BgmVoice_StartEx(&s_bgm_v2, stream2, 0);
    BgmVoice_StartEx(&s_bgm_vn, streamN, 0);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartEx(const u8 *stream, u16 loop_offset)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream, loop_offset);
    BgmVoice_Stop(&s_bgm_v1);
    BgmVoice_Stop(&s_bgm_v2);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = (loop_offset != 0);
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartLoop2Ex(const u8 *stream0, u16 loop0, const u8 *stream1, u16 loop1)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream0, loop0);
    BgmVoice_StartEx(&s_bgm_v1, stream1, loop1);
    BgmVoice_Stop(&s_bgm_v2);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartLoop3Ex(const u8 *stream0, u16 loop0, const u8 *stream1, u16 loop1, const u8 *stream2, u16 loop2)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream0, loop0);
    BgmVoice_StartEx(&s_bgm_v1, stream1, loop1);
    BgmVoice_StartEx(&s_bgm_v2, stream2, loop2);
    BgmVoice_Stop(&s_bgm_vn);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_StartLoop4Ex(const u8 *stream0, u16 loop0, const u8 *stream1, u16 loop1, const u8 *stream2, u16 loop2, const u8 *streamN, u16 loopN)
{
    Bgm_ResetFadeState();
    s_bgm_song_frame = 0;
    BgmVoice_StartEx(&s_bgm_v0, stream0, loop0);
    BgmVoice_StartEx(&s_bgm_v1, stream1, loop1);
    BgmVoice_StartEx(&s_bgm_v2, stream2, loop2);
    BgmVoice_StartEx(&s_bgm_vn, streamN, loopN);
    s_bgm_loop = 1;
    Bgm_ClearRestoreFlags();
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_Stop(void)
{
    Bgm_ResetFadeState();
    BgmVoice_Reset(&s_bgm_v0);
    BgmVoice_Reset(&s_bgm_v1);
    BgmVoice_Reset(&s_bgm_v2);
    BgmVoice_Reset(&s_bgm_vn);
    s_bgm_loop = 0;
    s_bgm_song_frame = 0;
    Bgm_ClearSfxFlags();
    Bgm_ClearRestoreFlags();
    SilenceVoice(0x90);
    SilenceVoice(0xB0);
    SilenceVoice(0xD0);
    SilenceVoice(0xF0);
    s_bgm_last_vbl = g_vb_counter;
}

void Bgm_SetSpeed(u8 mul)
{
    if (mul == 0) {
        mul = 1;
    }
    s_bgm_speed = mul;
}

void Bgm_SetGate(u8 percent)
{
    if (percent == 0) {
        percent = 1;
    }
    if (percent > 100) {
        percent = 100;
    }
    s_bgm_gate_percent = percent;
}

void Bgm_FadeOut(u8 speed)
{
    if (speed == 0) {
        Bgm_ResetFadeState();
        return;
    }
    s_bgm_fade_speed = speed;
    s_bgm_fade_counter = speed;
    /* Don't reset s_bgm_fade_attn to allow chaining fades */
}

void Bgm_SetTempo(u8 speed)
{
    if (speed < 1) speed = 1;
    s_bgm_speed = speed;
}

void Bgm_DebugReset(void)
{
    s_bgm_dbg.song_frame = 0;
    s_bgm_dbg.v0_next_frame = 0;
    s_bgm_dbg.v1_next_frame = 0;
    s_bgm_dbg.v2_next_frame = 0;
    s_bgm_dbg.vn_next_frame = 0;
    s_bgm_dbg.v0_ptr = 0;
    s_bgm_dbg.v1_ptr = 0;
    s_bgm_dbg.v2_ptr = 0;
    s_bgm_dbg.vn_ptr = 0;
    s_bgm_dbg.v0_events = 0;
    s_bgm_dbg.v1_events = 0;
    s_bgm_dbg.v2_events = 0;
    s_bgm_dbg.vn_events = 0;
    s_bgm_dbg.v0_last_note = 0;
    s_bgm_dbg.v1_last_note = 0;
    s_bgm_dbg.v2_last_note = 0;
    s_bgm_dbg.vn_last_note = 0;
    s_bgm_dbg.v0_last_cmd = 0;
    s_bgm_dbg.v1_last_cmd = 0;
    s_bgm_dbg.v2_last_cmd = 0;
    s_bgm_dbg.vn_last_cmd = 0;
    s_bgm_dbg.v0_enabled = 0;
    s_bgm_dbg.v1_enabled = 0;
    s_bgm_dbg.v2_enabled = 0;
    s_bgm_dbg.vn_enabled = 0;
    s_bgm_dbg.ch1_muted_by_sfx = 0;
    s_bgm_dbg.restore_ch1 = 0;
#if BGM_DEBUG
    s_bgm_v0.dbg_events = 0;
    s_bgm_v0.dbg_last_note = 0;
    s_bgm_v0.dbg_last_cmd = 0;
    s_bgm_v1.dbg_events = 0;
    s_bgm_v1.dbg_last_note = 0;
    s_bgm_v1.dbg_last_cmd = 0;
    s_bgm_v2.dbg_events = 0;
    s_bgm_v2.dbg_last_note = 0;
    s_bgm_v2.dbg_last_cmd = 0;
    s_bgm_vn.dbg_events = 0;
    s_bgm_vn.dbg_last_note = 0;
    s_bgm_vn.dbg_last_cmd = 0;
#endif
}

void Bgm_DebugSnapshot(BgmDebug *out)
{
    if (!out) {
        return;
    }
    out->song_frame = s_bgm_song_frame;
    out->v0_next_frame = s_bgm_v0.next_frame;
    out->v1_next_frame = s_bgm_v1.next_frame;
    out->v2_next_frame = s_bgm_v2.next_frame;
    out->vn_next_frame = s_bgm_vn.next_frame;
    if (s_bgm_v0.start && s_bgm_v0.ptr >= s_bgm_v0.start) {
        out->v0_ptr = (u32)(s_bgm_v0.ptr - s_bgm_v0.start);
    } else {
        out->v0_ptr = 0;
    }
    if (s_bgm_v1.start && s_bgm_v1.ptr >= s_bgm_v1.start) {
        out->v1_ptr = (u32)(s_bgm_v1.ptr - s_bgm_v1.start);
    } else {
        out->v1_ptr = 0;
    }
    if (s_bgm_v2.start && s_bgm_v2.ptr >= s_bgm_v2.start) {
        out->v2_ptr = (u32)(s_bgm_v2.ptr - s_bgm_v2.start);
    } else {
        out->v2_ptr = 0;
    }
    if (s_bgm_vn.start && s_bgm_vn.ptr >= s_bgm_vn.start) {
        out->vn_ptr = (u32)(s_bgm_vn.ptr - s_bgm_vn.start);
    } else {
        out->vn_ptr = 0;
    }
#if BGM_DEBUG
    out->v0_events = s_bgm_v0.dbg_events;
    out->v1_events = s_bgm_v1.dbg_events;
    out->v0_last_note = s_bgm_v0.dbg_last_note;
    out->v1_last_note = s_bgm_v1.dbg_last_note;
    out->v0_last_cmd = s_bgm_v0.dbg_last_cmd;
    out->v1_last_cmd = s_bgm_v1.dbg_last_cmd;
    out->v2_events = s_bgm_v2.dbg_events;
    out->vn_events = s_bgm_vn.dbg_events;
    out->v2_last_note = s_bgm_v2.dbg_last_note;
    out->vn_last_note = s_bgm_vn.dbg_last_note;
    out->v2_last_cmd = s_bgm_v2.dbg_last_cmd;
    out->vn_last_cmd = s_bgm_vn.dbg_last_cmd;
#else
    out->v0_events = 0;
    out->v1_events = 0;
    out->v0_last_note = 0;
    out->v1_last_note = 0;
    out->v0_last_cmd = 0;
    out->v1_last_cmd = 0;
    out->v2_events = 0;
    out->vn_events = 0;
    out->v2_last_note = 0;
    out->vn_last_note = 0;
    out->v2_last_cmd = 0;
    out->vn_last_cmd = 0;
#endif
    out->v0_enabled = s_bgm_v0.enabled;
    out->v1_enabled = s_bgm_v1.enabled;
    out->v2_enabled = s_bgm_v2.enabled;
    out->vn_enabled = s_bgm_vn.enabled;
    out->ch1_muted_by_sfx = s_bgm_ch_used_by_sfx[0];
    out->restore_ch1 = s_bgm_restore_ch[0];
}

void Bgm_Update(void)
{
    u8 elapsed;
    PsgCmd cmd0;
    PsgCmd cmd1;
    PsgCmd cmd2;
    PsgCmd cmdn;
    if (!s_bgm_v0.enabled && !s_bgm_v1.enabled && !s_bgm_v2.enabled && !s_bgm_vn.enabled &&
        s_sfx_active_mask == 0 &&
        !s_sfx_cmd[0].valid && !s_sfx_cmd[1].valid && !s_sfx_cmd[2].valid && !s_sfx_cmd[3].valid &&
        !s_sfx_end_pending[0] && !s_sfx_end_pending[1] && !s_sfx_end_pending[2] && !s_sfx_end_pending[3] &&
        !s_bgm_restore_ch[0] && !s_bgm_restore_ch[1] && !s_bgm_restore_ch[2] && !s_bgm_restore_ch[3]) {
        return;
    }
    elapsed = (u8)(g_vb_counter - s_bgm_last_vbl);
    if (elapsed == 0) {
        return;
    }
#if SOUNDS_MAX_CATCHUP > 0
    if (elapsed > (u8)SOUNDS_MAX_CATCHUP) {
        elapsed = (u8)SOUNDS_MAX_CATCHUP;
    }
#endif
    s_bgm_last_vbl = g_vb_counter;
    while (elapsed > 0) {
        s_bgm_song_frame++;
        /* --- Fade processing --- */
        if (s_bgm_fade_speed > 0) {
            if (s_bgm_fade_counter == 0) {
                if (s_bgm_fade_attn < 15) {
                    s_bgm_fade_attn++;
                }
                if (s_bgm_fade_attn >= 15) {
                    /* Fade complete â€” stop BGM */
                    Bgm_Stop();
                    return;
                }
                s_bgm_fade_counter = s_bgm_fade_speed;
            } else {
                s_bgm_fade_counter--;
            }
        }
        if (s_bgm_v0.enabled) {
            BgmVoice_Step(&s_bgm_v0, &cmd0);
        } else {
            cmd0.valid = 0;
        }
        if (s_bgm_v1.enabled) {
            BgmVoice_Step(&s_bgm_v1, &cmd1);
        } else {
            cmd1.valid = 0;
        }
        if (s_bgm_v2.enabled) {
            BgmVoice_Step(&s_bgm_v2, &cmd2);
        } else {
            cmd2.valid = 0;
        }
        if (s_bgm_vn.enabled) {
            BgmVoice_Step(&s_bgm_vn, &cmdn);
        } else {
            cmdn.valid = 0;
        }
        BufferBegin();
        BufferReplayPending();
        /* SFX first (one frame packet) */
        if (s_sfx_cmd[0].valid) {
            BufferPushIfChanged(0, &s_sfx_cmd[0]);
        }
        if (s_sfx_cmd[1].valid) {
            BufferPushIfChanged(1, &s_sfx_cmd[1]);
        }
        if (s_sfx_cmd[2].valid) {
            BufferPushIfChanged(2, &s_sfx_cmd[2]);
        }
        if (s_sfx_cmd[3].valid) {
            BufferPushIfChanged(3, &s_sfx_cmd[3]);
        }
        /* Prioritize noise channel when buffer is under pressure. */
        if (cmdn.valid) {
            if (!s_bgm_ch_used_by_sfx[3]) {
                int pushed = BufferPushIfChanged(3, &cmdn);
                if (pushed < 0) {
                    s_bgm_restore_ch[3] = 1;
                }
            } else {
                s_bgm_restore_ch[3] = 1;
            }
        }
        if (s_bgm_restore_ch[3] && !s_bgm_ch_used_by_sfx[3] && !cmdn.valid && s_bgm_vn.enabled) {
            int pushed = BufferPushBytesIfChanged(3, s_bgm_vn.shadow_b1, s_bgm_vn.shadow_b2, s_bgm_vn.shadow_b3);
            if (pushed == 0) {
                s_bgm_restore_ch[3] = 0;
            }
        }
        if (cmd0.valid) {
            if (!s_bgm_ch_used_by_sfx[0]) {
                int pushed = BufferPushIfChanged(0, &cmd0);
                if (pushed < 0) {
                    s_bgm_restore_ch[0] = 1;
                }
            } else {
                s_bgm_restore_ch[0] = 1;
            }
        }
        if (s_bgm_restore_ch[0] && !s_bgm_ch_used_by_sfx[0] && !cmd0.valid && s_bgm_v0.enabled) {
            int pushed = BufferPushBytesIfChanged(0, s_bgm_v0.shadow_b1, s_bgm_v0.shadow_b2, s_bgm_v0.shadow_b3);
            if (pushed == 0) {
                s_bgm_restore_ch[0] = 0;
            }
        }
        if (cmd1.valid) {
            if (!s_bgm_ch_used_by_sfx[1]) {
                int pushed = BufferPushIfChanged(1, &cmd1);
                if (pushed < 0) {
                    s_bgm_restore_ch[1] = 1;
                }
            } else {
                s_bgm_restore_ch[1] = 1;
            }
        }
        if (s_bgm_restore_ch[1] && !s_bgm_ch_used_by_sfx[1] && !cmd1.valid && s_bgm_v1.enabled) {
            int pushed = BufferPushBytesIfChanged(1, s_bgm_v1.shadow_b1, s_bgm_v1.shadow_b2, s_bgm_v1.shadow_b3);
            if (pushed == 0) {
                s_bgm_restore_ch[1] = 0;
            }
        }
        if (cmd2.valid) {
            if (!s_bgm_ch_used_by_sfx[2]) {
                int pushed = BufferPushIfChanged(2, &cmd2);
                if (pushed < 0) {
                    s_bgm_restore_ch[2] = 1;
                }
            } else {
                s_bgm_restore_ch[2] = 1;
            }
        }
        if (s_bgm_restore_ch[2] && !s_bgm_ch_used_by_sfx[2] && !cmd2.valid && s_bgm_v2.enabled) {
            int pushed = BufferPushBytesIfChanged(2, s_bgm_v2.shadow_b1, s_bgm_v2.shadow_b2, s_bgm_v2.shadow_b3);
            if (pushed == 0) {
                s_bgm_restore_ch[2] = 0;
            }
        }
        if (s_buf_count > 0) {
            BufferCommit();
        }
        /* Clear per-frame SFX commands and end markers. */
        if (s_sfx_cmd[0].valid) s_sfx_cmd[0].valid = 0;
        if (s_sfx_cmd[1].valid) s_sfx_cmd[1].valid = 0;
        if (s_sfx_cmd[2].valid) s_sfx_cmd[2].valid = 0;
        if (s_sfx_cmd[3].valid) s_sfx_cmd[3].valid = 0;
        if (s_sfx_end_pending[0]) {
            s_sfx_end_pending[0] = 0;
            s_bgm_ch_used_by_sfx[0] = 0;
        }
        if (s_sfx_end_pending[1]) {
            s_sfx_end_pending[1] = 0;
            s_bgm_ch_used_by_sfx[1] = 0;
        }
        if (s_sfx_end_pending[2]) {
            s_sfx_end_pending[2] = 0;
            s_bgm_ch_used_by_sfx[2] = 0;
        }
        if (s_sfx_end_pending[3]) {
            s_sfx_end_pending[3] = 0;
            s_bgm_ch_used_by_sfx[3] = 0;
        }
        elapsed--;
    }
}
