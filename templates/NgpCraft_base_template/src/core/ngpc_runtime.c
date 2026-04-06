/*
 * ngpc_runtime.c - Minimal runtime helpers replacing system.lib arithmetic
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * cc900 emits calls to these symbols for some 32-bit unsigned operations:
 *   C9H_mullu : unsigned long multiply
 *   C9H_divlu : unsigned long divide
 *   C9H_remlu : unsigned long remainder
 *
 * We provide compact software implementations so the template can link
 * without a proprietary system.lib.
 */

#include "ngpc_types.h"

unsigned long C9H_mullu(unsigned long a, unsigned long b)
{
    unsigned long result = 0UL;

    while (b != 0UL) {
        if (b & 1UL) {
            result += a;
        }
        a <<= 1;
        b >>= 1;
    }

    return result;
}

unsigned long C9H_divlu(unsigned long dividend, unsigned long divisor)
{
    unsigned long quotient = 0UL;
    unsigned long rem = 0UL;
    u8 i;

    /* C behavior is undefined for /0. Return max value as a safe guard. */
    if (divisor == 0UL) {
        return 0xFFFFFFFFUL;
    }

    for (i = 0; i < 32; ++i) {
        rem <<= 1;
        rem |= (dividend >> (31 - i)) & 1UL;

        if (rem >= divisor) {
            rem -= divisor;
            quotient |= (1UL << (31 - i));
        }
    }

    return quotient;
}

unsigned long C9H_remlu(unsigned long dividend, unsigned long divisor)
{
    unsigned long rem = 0UL;
    u8 i;

    if (divisor == 0UL) {
        return dividend;
    }

    for (i = 0; i < 32; ++i) {
        rem <<= 1;
        rem |= (dividend >> (31 - i)) & 1UL;

        if (rem >= divisor) {
            rem -= divisor;
        }
    }

    return rem;
}

