#include "sounds.h"

/*
 * Game-specific SFX mapping template.
 * Keep the driver clean; implement your own mapping here.
 *
 * How to use:
 * - Compile this file in your game project.
 * - Add `#define SFX_PLAY_EXTERNAL 1` in a global config or compiler defines.
 * - Replace the example logic with your own.
 */

/* Example data-driven table (replace with your own presets). */
/*
static const SfxPreset kSfxTable[] = {
    { SFX_PRESET_TONE,  { .tone  = {0, 240, 2, 6, 280, 2, 1, 0, 1, 1, 2} } },
    { SFX_PRESET_NOISE, { .noise = {1, 1, 6, 8, 0, 1, 0, 1, 2} } },
};
*/

/* Example: use NGPC Sound Creator project export (`project_sfx.c`). */
/*
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
*/

void Sfx_Play(u8 id)
{
    /* Example: table-driven */
    /* Sfx_PlayPresetTable(kSfxTable, (u8)(sizeof(kSfxTable) / sizeof(kSfxTable[0])), id); */

    /* Example: manual mapping */
    /*
    switch (id) {
    case 0:
        Sfx_PlayToneEx(0, 240, 2, 6, 280, 2, 1, 0, 1, 1, 2, 2);
        break;
    case 1:
        Sfx_PlayNoiseEx(1, 1, 6, 8, 0, 1, 0, 1, 2);
        break;
    default:
        break;
    }
    */

    /* Example: project_sfx.c driven mapping */
    /*
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
    */

    (void)id;
}
