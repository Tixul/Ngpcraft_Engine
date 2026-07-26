/*
 * battle_engine_hooks.c — default no-op hooks called by battle_engine.c.
 *
 * v1.1.5 : weak-linkage (__attribute__((weak))) doesn't work on cc900 / Toshiba,
 * so we ship plain no-op definitions. Users who want BGM dispatch or custom
 * event emission must REPLACE this file with their own implementation
 * (remove battle_engine_hooks.rel from OBJS in the Makefile + provide their
 * own .c file with the same two function definitions wired to their project).
 *
 * Example user override :
 *
 *   #include "../audio/sounds.h"
 *   #include "../GraphX/gen/ngpc_custom_events.h"
 *
 *   void battle_engine_play_bgm(u8 bgm_id) {
 *       switch (bgm_id) {
 *           case 1u: Bgm_StartLoop(bgm_battle); break;
 *           default: break;
 *       }
 *   }
 *
 *   void battle_engine_emit_event(u8 event_id) {
 *       emit_custom_event(event_id);
 *   }
 */
#include "ngpc_hw.h"


void battle_engine_play_bgm(u8 bgm_id)
{
    (void)bgm_id;
}


void battle_engine_emit_event(u8 event_id)
{
    (void)event_id;
}
