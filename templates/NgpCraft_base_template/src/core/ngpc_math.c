/*
 * ngpc_math.c - Math utilities (sin/cos, RNG, 32-bit multiply)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Sin table: standard 256-entry sine table, computed as:
 *   sin_table[i] = round(sin(i * 2*PI / 256) * 127)
 * This is pure mathematics, not derived from any copyrighted code.
 */

#include "ngpc_hw.h"
#include "ngpc_sys.h"
#include "ngpc_math.h"

/* ---- Sine lookup table (first quadrant + symmetry) ---- */

static const s8 sin_table[256] = {
      0,   3,   6,   9,  12,  16,  19,  22,
     25,  28,  31,  34,  37,  40,  43,  46,
     49,  51,  54,  57,  60,  63,  65,  68,
     71,  73,  76,  78,  81,  83,  85,  88,
     90,  92,  94,  96,  98, 100, 102, 104,
    106, 107, 109, 111, 112, 113, 115, 116,
    117, 118, 120, 121, 122, 122, 123, 124,
    125, 125, 126, 126, 126, 127, 127, 127,
    127, 127, 127, 127, 126, 126, 126, 125,
    125, 124, 123, 122, 122, 121, 120, 118,
    117, 116, 115, 113, 112, 111, 109, 107,
    106, 104, 102, 100,  98,  96,  94,  92,
     90,  88,  85,  83,  81,  78,  76,  73,
     71,  68,  65,  63,  60,  57,  54,  51,
     49,  46,  43,  40,  37,  34,  31,  28,
     25,  22,  19,  16,  12,   9,   6,   3,
      0,  -3,  -6,  -9, -12, -16, -19, -22,
    -25, -28, -31, -34, -37, -40, -43, -46,
    -49, -51, -54, -57, -60, -63, -65, -68,
    -71, -73, -76, -78, -81, -83, -85, -88,
    -90, -92, -94, -96, -98,-100,-102,-104,
   -106,-107,-109,-111,-112,-113,-115,-116,
   -117,-118,-120,-121,-122,-122,-123,-124,
   -125,-125,-126,-126,-126,-127,-127,-127,
   -127,-127,-127,-127,-126,-126,-126,-125,
   -125,-124,-123,-122,-122,-121,-120,-118,
   -117,-116,-115,-113,-112,-111,-109,-107,
   -106,-104,-102,-100, -98, -96, -94, -92,
    -90, -88, -85, -83, -81, -78, -76, -73,
    -71, -68, -65, -63, -60, -57, -54, -51,
    -49, -46, -43, -40, -37, -34, -31, -28,
    -25, -22, -19, -16, -12,  -9,  -6,  -3
};

/* ---- PRNG state (32-bit LCG) ---- */

static u32 s_rng_state = 1;

/* ---- Public API ---- */

s8 ngpc_sin(u8 angle)
{
    return sin_table[angle];
}

s8 ngpc_cos(u8 angle)
{
    /* cos(x) = sin(x + 64), since 64/256 = 90 degrees. */
    return sin_table[(u8)(angle + 64)];
}

void ngpc_rng_seed(void)
{
    /* Seed from VBCounter, which varies based on when user presses start. */
    s_rng_state = (u32)g_vb_counter * 1103515245UL + 12345UL;
    if (s_rng_state == 0) s_rng_state = 1;
}

u16 ngpc_random(u16 max)
{
    u32 result;

    /* Linear congruential generator (Numerical Recipes constants). */
    s_rng_state = s_rng_state * 1103515245UL + 12345UL;

    /* Extract bits 16-30 for better distribution. */
    result = (s_rng_state >> 16) & 0x7FFF;

    /* Scale to 0..max range. */
    if (max == 0) return 0;
    return (u16)(result % ((u32)max + 1));
}

/* ---- Quick random (table-based) ---- */

/*
 * Pre-shuffled table of 256 bytes (Fisher-Yates via LCG at init).
 * Initialized with a simple deterministic pattern; call ngpc_qrandom_init()
 * after seeding the LCG to get a unique shuffle per playthrough.
 */
static u8 s_qr_table[256];
static u8 s_qr_index = 0;

void ngpc_qrandom_init(void)
{
    u16 i;
    u8 j, tmp;

    /* Fill with identity. */
    for (i = 0; i < 256; i++)
        s_qr_table[i] = (u8)i;

    /* Fisher-Yates shuffle using the LCG. */
    for (i = 255; i > 0; i--) {
        j = (u8)(ngpc_random((u16)i));
        tmp = s_qr_table[i];
        s_qr_table[i] = s_qr_table[j];
        s_qr_table[j] = tmp;
    }

    s_qr_index = 0;
}

u8 ngpc_qrandom(void)
{
    return s_qr_table[s_qr_index++]; /* u8 wraps at 256 */
}

/* ---- 32-bit multiply ---- */

s32 ngpc_mul32(s32 a, s32 b)
{
    /*
     * The TLCS-900/H lacks a native 32x32 multiply instruction.
     * We implement it using 16x16 partial products:
     *   a = (a_hi << 16) + a_lo
     *   b = (b_hi << 16) + b_lo
     *   result = a_lo*b_lo + (a_lo*b_hi + a_hi*b_lo) << 16
     * (a_hi*b_hi is beyond 32 bits and discarded)
     *
     * This is a standard decomposition, not derived from any specific code.
     */
    u16 a_lo = (u16)(a & 0xFFFF);
    u16 a_hi = (u16)((a >> 16) & 0xFFFF);
    u16 b_lo = (u16)(b & 0xFFFF);
    u16 b_hi = (u16)((b >> 16) & 0xFFFF);

    u32 lo_lo = (u32)a_lo * (u32)b_lo;
    u32 cross = (u32)a_lo * (u32)b_hi + (u32)a_hi * (u32)b_lo;

    return (s32)(lo_lo + (cross << 16));
}
