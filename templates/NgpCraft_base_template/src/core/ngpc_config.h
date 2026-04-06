/*
 * ngpc_config.h - Global feature flags for NgpCraft_base_template
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * This header centralizes compile-time feature toggles.
 * Makefile passes the same symbols with -D by default.
 */

#ifndef NGPC_CONFIG_H
#define NGPC_CONFIG_H

#ifndef NGP_ENABLE_SOUND
#define NGP_ENABLE_SOUND        1
#endif

#ifndef NGP_ENABLE_FLASH_SAVE
#define NGP_ENABLE_FLASH_SAVE   0
#endif

#ifndef NGP_ENABLE_DEBUG
#define NGP_ENABLE_DEBUG        1
#endif

#ifndef NGP_ENABLE_DMA
#define NGP_ENABLE_DMA          0
#endif

#ifndef NGP_ENABLE_SPRMUX
#define NGP_ENABLE_SPRMUX       0
#endif

#ifndef NGP_ENABLE_PROFILER
#define NGP_ENABLE_PROFILER     0
#endif

/* 1 = strip assert/log/debug helpers (release profile). */
#ifndef NGP_PROFILE_RELEASE
#define NGP_PROFILE_RELEASE     0
#endif

#endif /* NGPC_CONFIG_H */
