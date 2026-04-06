#ifndef SOUNDS_H
#define SOUNDS_H

#include "ngpc_types.h"

#define NOTE_MAX_INDEX 50

/* Provided by your music data (e.g., midi_to_ngpc output). */
#if defined(__GNUC__)
#define SOUNDS_WEAK_SYMBOL __attribute__((weak))
#else
#define SOUNDS_WEAK_SYMBOL
#endif
extern const u8 NOTE_TABLE[] SOUNDS_WEAK_SYMBOL;

#ifndef SOUNDS_MAX_CATCHUP
/* 0 = no clamp. If >0, cap BGM catch-up frames per update to avoid long stalls. */
#define SOUNDS_MAX_CATCHUP 0
#endif

#define BGM_OP_SET_ATTN  0xF0
#define BGM_OP_SET_ENV   0xF1
#define BGM_OP_SET_VIB   0xF2
#define BGM_OP_SET_SWEEP 0xF3
#define BGM_OP_SET_INST  0xF4
#define BGM_OP_SET_PAN   0xF5
#define BGM_OP_HOST_CMD  0xF6
#define BGM_OP_SET_EXPR  0xF7
#define BGM_OP_PITCH_BEND 0xF8
#define BGM_OP_SET_ADSR  0xF9
#define BGM_OP_SET_LFO   0xFA
#define BGM_OP_SET_ENV_CURVE   0xFB
#define BGM_OP_SET_PITCH_CURVE 0xFC
#define BGM_OP_SET_MACRO       0xFD
#define BGM_OP_EXT      0xFE

#define BGM_EXT_SET_ADSR5 0x01
#define BGM_EXT_SET_MOD2  0x02

#ifndef BGM_DEBUG
#define BGM_DEBUG 0
#endif

typedef struct {
    u32 song_frame;
    u32 v0_next_frame;
    u32 v1_next_frame;
    u32 v2_next_frame;
    u32 vn_next_frame;
    u32 v0_ptr;
    u32 v1_ptr;
    u32 v2_ptr;
    u32 vn_ptr;
    u32 v0_events;
    u32 v1_events;
    u32 v2_events;
    u32 vn_events;
    u8 v0_last_note;
    u8 v1_last_note;
    u8 v2_last_note;
    u8 vn_last_note;
    u8 v0_last_cmd;
    u8 v1_last_cmd;
    u8 v2_last_cmd;
    u8 vn_last_cmd;
    u8 v0_enabled;
    u8 v1_enabled;
    u8 v2_enabled;
    u8 vn_enabled;
    u8 ch1_muted_by_sfx;
    u8 restore_ch1;
} BgmDebug;

void Sounds_Init(void);
void Sounds_ResetState(void);
void Sounds_Update(void);
u8 Sounds_DebugFault(void);
u16 Sounds_DebugDrops(void);
u8 Sounds_DebugLastSfx(void);
void Sfx_Update(void);
/* By default, Sfx_Play() is a no-op. Define SFX_PLAY_EXTERNAL to provide your
 * own mapping, or use the data table helpers below.
 * Example (custom):
 *   case 0: Sfx_PlayToneEx(0, 240, 2, 6, 280, 2, 1, 0, 1, 1, 2, 2); break;
 *   case 1: Sfx_PlayNoiseEx(1, 1, 6, 8, 0, 1, 0, 1, 2); break; */
void Sfx_Play(u8 id);

typedef enum {
    SFX_PRESET_TONE = 0,
    SFX_PRESET_NOISE = 1
} SfxPresetKind;

typedef struct {
    u8 ch;
    u16 divider;
    u8 attn;
    u8 frames;
    u16 sw_end;
    s16 sw_step;
    u8 sw_speed;
    u8 sw_ping;
    u8 sw_on;
    u8 env_on;
    u8 env_step;
    u8 env_spd;
} SfxTonePreset;

typedef struct {
    u8 rate;
    u8 type;
    u8 attn;
    u8 frames;
    u8 burst;
    u8 burst_dur;
    u8 env_on;
    u8 env_step;
    u8 env_spd;
} SfxNoisePreset;

typedef struct {
    u8 kind;
    union {
        SfxTonePreset tone;
        SfxNoisePreset noise;
    } u;
} SfxPreset;

/* Example table (data-driven presets):
 * static const SfxPreset kSfxTable[] = {
 *   { SFX_PRESET_TONE,  { .tone  = {0, 240, 2, 6, 280, 2, 1, 0, 1, 1, 2} } },
 *   { SFX_PRESET_NOISE, { .noise = {1, 1, 6, 8, 0, 1, 0, 1, 2} } },
 * };
 * Sfx_PlayPresetTable(kSfxTable, sizeof(kSfxTable)/sizeof(kSfxTable[0]), id);
 */
void Sfx_PlayPreset(const SfxPreset *preset);
void Sfx_PlayPresetTable(const SfxPreset *table, u8 count, u8 id);
void Sfx_PlayToneCh(u8 ch, u16 divider, u8 attn, u8 frames);
void Sfx_PlayToneEx(u8 ch, u16 divider, u8 attn, u8 frames,
                    u16 sw_end, s16 sw_step, u8 sw_speed, u8 sw_ping, u8 sw_on,
                    u8 env_on, u8 env_step, u8 env_spd);
void Sfx_PlayNoise(u8 noise_val, u8 attn, u8 frames);
void Sfx_PlayNoiseEx(u8 rate, u8 type, u8 attn, u8 frames,
                     u8 burst, u8 burst_dur,
                     u8 env_on, u8 env_step, u8 env_spd);
void Sfx_SendBytes(u8 b1, u8 b2, u8 b3);
void Sfx_BufferBegin(void);
void Sfx_BufferPush(u8 b1, u8 b2, u8 b3);
void Sfx_BufferCommit(void);
void Sfx_Stop(void);
void Bgm_Start(const u8 *stream);
void Bgm_StartEx(const u8 *stream, u16 loop_offset);
void Bgm_StartLoop(const u8 *stream);
void Bgm_StartLoop2(const u8 *stream0, const u8 *stream1);
void Bgm_StartLoop2Ex(const u8 *stream0, u16 loop0, const u8 *stream1, u16 loop1);
void Bgm_StartLoop3(const u8 *stream0, const u8 *stream1, const u8 *stream2);
void Bgm_StartLoop3Ex(const u8 *stream0, u16 loop0, const u8 *stream1, u16 loop1, const u8 *stream2, u16 loop2);
void Bgm_StartLoop4(const u8 *stream0, const u8 *stream1, const u8 *stream2, const u8 *streamN);
void Bgm_StartLoop4Ex(const u8 *stream0, u16 loop0, const u8 *stream1, u16 loop1, const u8 *stream2, u16 loop2, const u8 *streamN, u16 loopN);
void Bgm_SetNoteTable(const u8 *note_table);
void Bgm_Stop(void);
void Bgm_FadeOut(u8 speed);
void Bgm_SetTempo(u8 speed);
void Bgm_Update(void);
void Bgm_SetSpeed(u8 mul);
void Bgm_SetGate(u8 percent);
void Bgm_DebugReset(void);
void Bgm_DebugSnapshot(BgmDebug *out);

#undef SOUNDS_WEAK_SYMBOL

#endif
