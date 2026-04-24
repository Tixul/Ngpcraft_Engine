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

/* ---- PRNG state (16-bit LCG) ----
 *
 * Why u16 and not u32: cc900's u32 multiply and modulo runtime helpers are
 * buggy on NGPC hardware. A prior u32 LCG with `result % ((u32)max + 1)`
 * didn't reduce at all — `ngpc_random(max)` returned values in ~0..32767
 * regardless of `max`, biasing every gameplay roll. Hardware confirmed
 * 2026-04-23 (menu_kuroi_dokutsu: crit 98% instead of 2/7, damage 35 for
 * a formula maxing at 4). TLCS-900 has a native 16×16 → 32 MUL opcode,
 * so u16 * u16 uses hardware and stays inside cc900's safe path.
 *
 * Constants: Turbo Pascal 2^16 LCG. Hull-Dobell satisfied (a≡1 mod 4,
 * c odd) → full period 65536.
 */
static u16 s_rng_state = 1u;

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
    /* Seed from VBCounter, which varies based on when the user first presses
     * a button. `| 1u` avoids the degenerate zero state. */
    s_rng_state = (u16)((u16)g_vb_counter | 1u);
}

u16 ngpc_random(u16 max)
{
    /* u16 LCG step: state = state * 25173 + 13849 (mod 2^16).
     * u16 * u16 → u16 uses the native TLCS-900 MUL opcode. No u32 helpers. */
    s_rng_state = (u16)((u16)(s_rng_state * 25173u) + 13849u);

    if (max == 0u) return 0u;
    if (max == 65535u) return s_rng_state;   /* avoid (max+1)==0 */
    return (u16)(s_rng_state % (u16)(max + 1u));
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
