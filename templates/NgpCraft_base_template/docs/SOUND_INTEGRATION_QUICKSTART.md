# Integration Quickstart (Clean Driver)

Goal: integrate the driver into a new game without touching driver sources.

1) Add driver files
- Add `sounds.c` and `sounds.h` to your project.

2) Provide game-specific SFX mapping
- Add `sounds_game_sfx_template.c` to your project (rename if you want).
- In your build defines or a common header, add:
  `#define SFX_PLAY_EXTERNAL 1`
- Implement `Sfx_Play(u8 id)` in that file.
- If you export from NGPC Sound Creator project mode, also add `exports/project_sfx.c`
  to your game build and use its arrays in `Sfx_Play`.

3) Initialize
- Call `Sounds_Init()` once at startup.

4) Update per frame
- Call `Sfx_Update()` once per frame (VBlank).
- Call `Bgm_Update()` once per frame (VBlank).
- Or just call `Sounds_Update()` once per frame.

5) Play SFX/BGM
- SFX: call `Sfx_PlayToneEx`, `Sfx_PlayNoiseEx`, or your `Sfx_Play` mapping.
- BGM: call `Bgm_Start` / `Bgm_StartLoop` and feed a stream.

6) Provide music data
- Include `NOTE_TABLE` and your BGM stream arrays (from export output).
- Also include the companion instrument export `*_instruments.c`.
- In this template, the default wiring is:
  - `sound/sound_data.c` includes `sound_sample.c`
  - `src/audio/sounds.c` includes `sound_sample_instruments.c`
- If you keep those filenames, no extra makefile object is needed.
- If you rename the exported files, only update those two `#include` lines.

6a) If you use Project Export All
- Also generated:
  - `exports/project_audio_manifest.txt`
  - `exports/project_audio_api.h`
  - `exports/project_audio_api.c` (C export mode)
- Song symbols are namespaced (`PROJECT_<SONG_ID>_*`) to prevent collisions.
- Use the manifest/API as integration index for your song list.
- Runtime helper:
  - `NgpcProject_BgmStartLoop4ByIndex(i)` auto-switches `NOTE_TABLE` and starts the 4 streams.
  - `project_audio_api.c` provides a weak `NOTE_TABLE` fallback symbol for linker compatibility.

Example:
```c
NgpcProject_BgmStartLoop4ByIndex(0); /* start first exported song */
```

6b) Optional: integrate project SFX bank
- Build/compile `project_sfx.c` (do not keep it only as a loose file).
- In your `Sfx_Play(u8 id)` implementation, read from:
  - `PROJECT_SFX_COUNT`
  - `PROJECT_SFX_TONE_ON[]`, `PROJECT_SFX_TONE_CH[]`, `PROJECT_SFX_TONE_DIV[]`, `PROJECT_SFX_TONE_ATTN[]`, `PROJECT_SFX_TONE_FRAMES[]`
  - `PROJECT_SFX_TONE_SW_ON[]`, `PROJECT_SFX_TONE_SW_END[]`, `PROJECT_SFX_TONE_SW_STEP[]`, `PROJECT_SFX_TONE_SW_SPEED[]`, `PROJECT_SFX_TONE_SW_PING[]`
  - `PROJECT_SFX_TONE_ENV_ON[]`, `PROJECT_SFX_TONE_ENV_STEP[]`, `PROJECT_SFX_TONE_ENV_SPD[]`
  - `PROJECT_SFX_NOISE_ON[]`, `PROJECT_SFX_NOISE_RATE[]`, `PROJECT_SFX_NOISE_TYPE[]`, `PROJECT_SFX_NOISE_ATTN[]`, `PROJECT_SFX_NOISE_FRAMES[]`
  - `PROJECT_SFX_NOISE_BURST[]`, `PROJECT_SFX_NOISE_BURST_DUR[]`, `PROJECT_SFX_NOISE_ENV_ON[]`, `PROJECT_SFX_NOISE_ENV_STEP[]`, `PROJECT_SFX_NOISE_ENV_SPD[]`

Minimal mapping example:
```c
extern const unsigned char PROJECT_SFX_COUNT;
extern const unsigned char PROJECT_SFX_TONE_ON[];
extern const unsigned char PROJECT_SFX_TONE_CH[];
extern const unsigned short PROJECT_SFX_TONE_DIV[];
extern const unsigned char PROJECT_SFX_TONE_ATTN[];
extern const unsigned char PROJECT_SFX_TONE_FRAMES[];
extern const unsigned char PROJECT_SFX_TONE_SW_ON[];
extern const unsigned short PROJECT_SFX_TONE_SW_END[];
extern const signed short PROJECT_SFX_TONE_SW_STEP[];
extern const unsigned char PROJECT_SFX_TONE_SW_SPEED[];
extern const unsigned char PROJECT_SFX_TONE_SW_PING[];
extern const unsigned char PROJECT_SFX_TONE_ENV_ON[];
extern const unsigned char PROJECT_SFX_TONE_ENV_STEP[];
extern const unsigned char PROJECT_SFX_TONE_ENV_SPD[];
extern const unsigned char PROJECT_SFX_NOISE_ON[];
extern const unsigned char PROJECT_SFX_NOISE_RATE[];
extern const unsigned char PROJECT_SFX_NOISE_TYPE[];
extern const unsigned char PROJECT_SFX_NOISE_ATTN[];
extern const unsigned char PROJECT_SFX_NOISE_FRAMES[];
extern const unsigned char PROJECT_SFX_NOISE_BURST[];
extern const unsigned char PROJECT_SFX_NOISE_BURST_DUR[];
extern const unsigned char PROJECT_SFX_NOISE_ENV_ON[];
extern const unsigned char PROJECT_SFX_NOISE_ENV_STEP[];
extern const unsigned char PROJECT_SFX_NOISE_ENV_SPD[];

void Sfx_Play(u8 id) {
    if (id >= PROJECT_SFX_COUNT) return;
    if (PROJECT_SFX_TONE_ON[id]) {
        Sfx_PlayToneEx(PROJECT_SFX_TONE_CH[id], PROJECT_SFX_TONE_DIV[id], PROJECT_SFX_TONE_ATTN[id],
                       PROJECT_SFX_TONE_FRAMES[id], PROJECT_SFX_TONE_SW_END[id], PROJECT_SFX_TONE_SW_STEP[id],
                       PROJECT_SFX_TONE_SW_SPEED[id], PROJECT_SFX_TONE_SW_PING[id], PROJECT_SFX_TONE_SW_ON[id],
                       PROJECT_SFX_TONE_ENV_ON[id], PROJECT_SFX_TONE_ENV_STEP[id], PROJECT_SFX_TONE_ENV_SPD[id]);
    }
    if (PROJECT_SFX_NOISE_ON[id]) {
        Sfx_PlayNoiseEx(PROJECT_SFX_NOISE_RATE[id], PROJECT_SFX_NOISE_TYPE[id], PROJECT_SFX_NOISE_ATTN[id],
                        PROJECT_SFX_NOISE_FRAMES[id], PROJECT_SFX_NOISE_BURST[id], PROJECT_SFX_NOISE_BURST_DUR[id],
                        PROJECT_SFX_NOISE_ENV_ON[id], PROJECT_SFX_NOISE_ENV_STEP[id], PROJECT_SFX_NOISE_ENV_SPD[id]);
    }
}
```

Gameplay usage:
```c
Sfx_Play(0); /* button confirm */
```

7) Runtime controls (optional)
- Fade out: call `Bgm_FadeOut(speed)` (0 = cancel, >0 = frames between fade steps). BGM auto-stops when silent.
- Tempo change: call `Bgm_SetTempo(speed)` to change the BGM speed multiplier at runtime.
- These can also be embedded in streams via opcode `0xF6` (HOST_CMD).

Notes
- `Sfx_Play` in the driver remains a no-op unless you define `SFX_PLAY_EXTERNAL`.
- Prefer `Sfx_PlayPresetTable` for data-driven SFX banks.
- Instruments/macros/curves live in `sounds.c`.
- In the template default workflow, the instrument table itself comes from
  `sound/sound_sample_instruments.c`, included directly by `sounds.c`.
- BGM streams support ADSR envelopes (opcode `0xF9`), expression (opcode `0xF7`), and host commands (opcode `0xF6`).
- Optional slim build: set `SOUNDS_ENABLE_MACROS`, `SOUNDS_ENABLE_ENV_CURVES`,
  `SOUNDS_ENABLE_PITCH_CURVES`, or `SOUNDS_ENABLE_EXAMPLE_PRESETS` to 0.

Frame counter (VBlank sync)
- The driver uses a frame counter to keep BGM frame-locked.
- This template uses a **custom VBlank ISR** and `g_vb_counter` (in `ngpc_sys.h`).
  The driver's `sounds.c` references this counter instead of the BIOS `VBCounter`.
  Do not replace it with the BIOS counter — the BIOS VBlank may not fire with a custom ISR.

Hybrid export compatibility (NGPC Sound Creator)
- When using "Export All" or hybrid BGM+SFX from NGPC Sound Creator, the instrument export
  references IDs that must be present in the driver tables:
  - `env_curve_id` up to **2** (driver provides IDs 0..2)
  - `pitch_curve_id` up to **7** (driver provides IDs 0..7, where 5..7 are aliases of 1..2,4)
  - `macro_id` up to **3** (driver provides IDs 0..3, where 2..3 are empty stubs)
- If your export uses IDs beyond these ranges, add corresponding entries to `src/audio/sounds.c`.
- The `SFX_COUNT` literal in `sound/sound_data.c` must match `PROJECT_SFX_COUNT` from the export.
- For a BGM-only hybrid export with no project SFX bank, keep `SFX_COUNT = 0`.

Multi-song guidance
- Current driver uses one active instrument table at runtime.
- Recommended for multiple songs: maintain one shared/global instrument bank and keep
  stable instrument IDs across all exported tracks.
- Note-table switch per song is supported at runtime via `Bgm_SetNoteTable(...)`.
- If each song has its own bank, keep files paired (`songX.c` + `songX_instruments.c`)
  and make sure `sounds.c` includes the bank matching the streams you build into `sound_data.c`.
