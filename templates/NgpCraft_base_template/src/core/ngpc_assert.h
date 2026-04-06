/*
 * ngpc_assert.h - Runtime assert helper for debug builds
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#ifndef NGPC_ASSERT_H
#define NGPC_ASSERT_H

#include "ngpc_types.h"

/* 1 = strip assert/log/debug helpers at compile time. */
#ifndef NGP_PROFILE_RELEASE
#define NGP_PROFILE_RELEASE 0
#endif

void ngpc_assert_fail(const char *file, u16 line);

#if NGP_PROFILE_RELEASE || !NGP_ENABLE_DEBUG
#define NGPC_ASSERT(cond) ((void)0)
#else
#define NGPC_ASSERT(cond) do { \
    if (!(cond)) ngpc_assert_fail(__FILE__, (u16)__LINE__); \
} while (0)
#endif

#endif /* NGPC_ASSERT_H */
