/*
 * ngpc_log.h - Lightweight debug log ring buffer
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#ifndef NGPC_LOG_H
#define NGPC_LOG_H

#include "ngpc_types.h"

/* 1 = strip assert/log/debug helpers at compile time. */
#ifndef NGP_PROFILE_RELEASE
#define NGP_PROFILE_RELEASE 0
#endif

void ngpc_log_init(void);
void ngpc_log_clear(void);
void ngpc_log_hex(const char *label, u16 value);
void ngpc_log_str(const char *label, const char *str);
void ngpc_log_dump(u8 plane, u8 pal, u8 x, u8 y);
u8 ngpc_log_count(void);

#if NGP_PROFILE_RELEASE || !NGP_ENABLE_DEBUG
#define NGPC_LOG_HEX(label, value)    ((void)0)
#define NGPC_LOG_STR(label, str)      ((void)0)
#else
#define NGPC_LOG_HEX(label, value)    ngpc_log_hex((label), (u16)(value))
#define NGPC_LOG_STR(label, str)      ngpc_log_str((label), (str))
#endif

#endif /* NGPC_LOG_H */
