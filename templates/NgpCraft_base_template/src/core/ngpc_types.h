/*
 * ngpc_types.h - Base integer types for NGPC development
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from scratch - no third-party code.
 */

#ifndef NGPC_TYPES_H
#define NGPC_TYPES_H

#include "ngpc_config.h"

typedef unsigned char   u8;
typedef unsigned short  u16;
typedef unsigned long   u32;
typedef signed char     s8;
typedef signed short    s16;
typedef signed long     s32;

typedef void (*FuncPtr)(void);
typedef void __interrupt IntHandler(void);

#endif /* NGPC_TYPES_H */
