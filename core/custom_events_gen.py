"""
core/custom_events_gen.py — Generate ngpc_custom_events.h from project custom events.

Custom events are the receiving side of emit_event(id): they define what
happens when ngpc_emit_event(u8 id) is called at runtime.

Generated output — ngpc_custom_events.h:
    #define CEV_BOSS_PHASE_2    0u
    #define CUSTOM_EVENT_COUNT  2   /* action rows */
    #define CUSTOM_EVENT_COND_COUNT 3  /* guard condition rows */

    typedef struct {
        u8 event_id; u8 action; u8 a0; u8 a1; u8 once;
    } NgpngEventAction;

    typedef struct {
        u8 event_id;   /* CEV_* */
        u8 cond;       /* TRIG_COND_* (same IDs as scene triggers) */
        u8 index;      /* flag_var_index / entity-type index / item ID … */
        u16 value;     /* threshold / comparison value */
        u8 group_id;   /* 0xFF = primary AND group, 0..N = OR-group index */
        u8 negate;     /* 1 = NOT */
    } NgpngCevCond;

    static const NgpngCevCond g_cev_conds[] = { ... };
    static const NgpngEventAction g_custom_events[] = { ... };

Guard logic in ngpc_emit_event():
    - No conditions → always execute actions
    - Primary AND group (group_id=0xFF): all must pass
    - OR groups (group_id=0..N): event fires if primary group passes
      OR if all conditions in any OR group pass

If no custom events are defined the header is still valid (counts = 0).
"""
from __future__ import annotations

from pathlib import Path

from core.custom_events import (
    get_custom_events,
    get_custom_event_actions,
    get_custom_event_conditions,
    get_custom_event_or_groups,
    custom_event_name_to_macro,
)

_OUTPUT_FILENAME = "ngpc_custom_events.h"

# Maps condition string → TRIG_COND_* integer (same IDs as scene_level_gen.py)
_COND_TO_ID: dict[str, int] = {
    "enter_region": 0,      "leave_region": 1,
    "cam_x_ge": 2,          "cam_y_ge": 3,
    "timer_ge": 4,          "wave_ge": 5,
    "btn_a": 6,             "btn_b": 7,
    "btn_a_b": 8,           "btn_up": 9,
    "btn_down": 10,         "btn_left": 11,
    "btn_right": 12,        "btn_opt": 13,
    "on_jump": 14,          "wave_cleared": 15,
    "health_le": 16,        "health_ge": 17,
    "enemy_count_le": 18,   "lives_le": 19,
    "lives_ge": 20,         "collectible_count_ge": 21,
    "flag_set": 22,         "flag_clear": 23,
    "variable_ge": 24,      "variable_eq": 25,
    "timer_every": 26,      "scene_first_enter": 27,
    "on_nth_jump": 28,      "on_wall_left": 29,
    "on_wall_right": 30,    "on_ladder": 31,
    "on_ice": 32,           "on_conveyor": 33,
    "on_spring": 34,        "player_has_item": 35,
    "npc_talked_to": 36,    "entity_contact": 68,
    "count_eq": 37,         "entity_alive": 38,
    "entity_dead": 39,      "quest_stage_eq": 40,
    "ability_unlocked": 41, "resource_ge": 42,
    "combo_ge": 43,         "lap_ge": 44,
    "btn_held_ge": 45,      "chance": 46,
    "on_land": 47,          "on_hurt": 48,
    "on_death": 49,         "score_ge": 50,
    "timer_le": 51,         "variable_le": 52,
    "on_crouch": 53,        "cutscene_done": 54,
    "enemy_count_ge": 55,   "variable_ne": 56,
    "health_eq": 57,        "on_swim": 58,
    "on_dash": 59,          "on_attack": 60,
    "on_pickup": 61,        "entity_in_region": 62,
    "all_switches_on": 63,  "block_on_tile": 64,
    "dialogue_done": 65,    "choice_result": 66,
    "menu_result": 67,
    "entity_type_all_dead": 69,      "entity_type_count_ge": 70,
    "entity_type_collected": 71,     "entity_type_alive_le": 72,
    "entity_type_collected_ge": 73,  "entity_type_all_collected": 74,
    "entity_type_activated": 75,     "entity_type_all_activated": 76,
    "entity_type_any_alive": 77,     "entity_type_btn_a": 78,
    "entity_type_btn_b": 79,         "entity_type_btn_opt": 80,
    "entity_type_contact": 81,       "entity_type_near_player": 82,
    "entity_type_hit": 83,           "entity_type_hit_ge": 84,
    "entity_type_spawned": 85,       "entity_type_spawned_ge": 86,
}

# Maps action string → TRIG_ACT_* integer (same table as entity_type_events_gen)
_ACT_TO_ID: dict[str, int] = {
    "emit_event":           0,
    "play_sfx":             1,
    "start_bgm":            2,
    "stop_bgm":             3,
    "fade_bgm":             4,
    "goto_scene":           5,
    "spawn_wave":           6,
    "pause_scroll":         7,
    "resume_scroll":        8,
    "spawn_entity":         9,
    "set_scroll_speed":    10,
    "play_anim":           11,
    "force_jump":          12,
    "enable_trigger":      13,
    "disable_trigger":     14,
    "screen_shake":        15,
    "set_cam_target":      16,
    "add_score":           17,
    "show_entity":         18,
    "hide_entity":         19,
    "move_entity_to":      20,
    "cycle_player_form":   21,
    "set_player_form":     22,
    "fire_player_shot":    23,
    "set_checkpoint":      24,
    "respawn_player":      25,
    "pause_entity_path":   26,
    "resume_entity_path":  27,
    "set_flag":            28,
    "clear_flag":          29,
    "set_variable":        30,
    "inc_variable":        31,
    "warp_to":             32,
    "lock_player_input":   33,
    "unlock_player_input": 34,
    "enable_multijump":    35,
    "disable_multijump":   36,
    "reset_scene":         37,
    "show_dialogue":       38,
    "give_item":           39,
    "remove_item":         40,
    "unlock_door":         41,
    "enable_wall_grab":    42,
    "disable_wall_grab":   43,
    "set_gravity_dir":     44,
    "add_resource":        45,
    "remove_resource":     46,
    "unlock_ability":      47,
    "set_quest_stage":     48,
    "play_cutscene":       49,
    "end_game":            50,
    "dec_variable":        51,
    "add_health":          52,
    "set_health":          53,
    "fade_out":            63,
    "fade_in":             64,
    "save_game":           71,
}


def _int(v: object, default: int = 0) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _build_cond_rows(
    valid_events: list[dict],
) -> list[tuple[int, int, int, int, int, int]]:
    """Return (ev_idx, cond_id, index, value_lo, value_hi, group_id, negate) rows.

    group_id=0xFF for primary AND conditions, 0..N for OR groups.
    Returned as (ev_idx, cond_id, index, value_u16, group_id, negate).
    """
    rows: list[tuple[int, int, int, int, int, int]] = []
    for ev_idx, ev in enumerate(valid_events):
        # Primary AND conditions (group_id = 0xFF)
        for c in get_custom_event_conditions(ev):
            if not isinstance(c, dict):
                continue
            cond_str = str(c.get("cond") or "").strip()
            cond_id  = _COND_TO_ID.get(cond_str, 0)
            index    = _int(c.get("index")) & 0xFF
            value    = _int(c.get("value")) & 0xFFFF
            negate   = 1 if c.get("negate") else 0
            rows.append((ev_idx, cond_id, index, value, 0xFF, negate))
        # OR groups (group_id = 0, 1, …)
        for grp_idx, group in enumerate(get_custom_event_or_groups(ev)):
            if not isinstance(group, list):
                continue
            for c in group:
                if not isinstance(c, dict):
                    continue
                cond_str = str(c.get("cond") or "").strip()
                cond_id  = _COND_TO_ID.get(cond_str, 0)
                index    = _int(c.get("index")) & 0xFF
                value    = _int(c.get("value")) & 0xFFFF
                negate   = 1 if c.get("negate") else 0
                rows.append((ev_idx, cond_id, index, value, grp_idx & 0xFE, negate))
    return rows


def make_custom_events_h(*, project_data: dict) -> str:
    """Return the full content of ngpc_custom_events.h as a string."""
    events = get_custom_events(project_data)

    # Build scene_id → index map for goto_scene/warp_to resolution
    scene_id_to_idx: dict[str, int] = {}
    for i, sc in enumerate(project_data.get("scenes", []) or []):
        if isinstance(sc, dict):
            sid = str(sc.get("id") or "").strip()
            if sid:
                scene_id_to_idx[sid] = i

    valid_events: list[dict] = [
        ev for ev in events
        if isinstance(ev, dict) and str(ev.get("name") or "").strip()
    ]

    # --- action rows -------------------------------------------------------
    act_rows: list[tuple[int, int, int, int, int]] = []
    for ev_idx, ev in enumerate(valid_events):
        for act in get_custom_event_actions(ev):
            if not isinstance(act, dict):
                continue
            act_str = str(act.get("action") or "emit_event").lower()
            act_int = _ACT_TO_ID.get(act_str, 0)
            once    = 1 if act.get("once") else 0
            if act_str in ("goto_scene", "warp_to"):
                sid = str(act.get("scene_to") or "").strip()
                a0  = int(scene_id_to_idx.get(sid, _int(act.get("a0")))) & 0xFF
            elif act_str in ("set_flag", "clear_flag", "toggle_flag",
                             "set_variable", "inc_variable", "dec_variable"):
                a0  = _int(act.get("flag_var_index")) & 0xFF
            else:
                a0  = _int(act.get("a0")) & 0xFF
            a1 = _int(act.get("a1")) & 0xFF
            act_rows.append((ev_idx, act_int, a0, a1, once))

    # --- condition rows ----------------------------------------------------
    cond_rows = _build_cond_rows(valid_events)

    # --- header output -----------------------------------------------------
    lines: list[str] = [
        "/* ngpc_custom_events.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — configure via Globals > Événements personnalisés */",
        "#ifndef NGPC_CUSTOM_EVENTS_H",
        "#define NGPC_CUSTOM_EVENTS_H",
        "",
    ]

    # CEV_* macros
    if valid_events:
        lines.append("/* Custom event IDs — pass to ngpc_emit_event() */")
        max_macro = max(len(custom_event_name_to_macro(ev.get("name", "")))
                        for ev in valid_events)
        for i, ev in enumerate(valid_events):
            macro = custom_event_name_to_macro(str(ev.get("name") or ""))
            lines.append(f"#define {macro:<{max_macro}} {i}u")
        lines.append("")

    # NgpngEventAction typedef (guard-avoided duplicate)
    lines += [
        "#ifndef NGPNG_EVENT_ACTION_T",
        "#define NGPNG_EVENT_ACTION_T",
        "typedef struct {",
        "    u8 event_id;  /* CEV_* */",
        "    u8 action;    /* TRIG_ACT_* */",
        "    u8 a0;",
        "    u8 a1;",
        "    u8 once;      /* 1 = fire only once per scene load */",
        "} NgpngEventAction;",
        "#endif",
        "",
    ]

    # NgpngCevCond typedef (guard condition struct)
    lines += [
        "#ifndef NGPNG_CEV_COND_T",
        "#define NGPNG_CEV_COND_T",
        "typedef struct {",
        "    u8  event_id;  /* CEV_* */",
        "    u8  cond;      /* TRIG_COND_* */",
        "    u8  index;     /* flag/var/entity-type index */",
        "    u16 value;     /* threshold or comparison value */",
        "    u8  group_id;  /* 0xFF = primary AND group, 0..N = OR group */",
        "    u8  negate;    /* 1 = NOT condition */",
        "} NgpngCevCond;",
        "#endif",
        "",
        f"#define CUSTOM_EVENT_COUNT      {len(act_rows)}",
        f"#define CUSTOM_EVENT_COND_COUNT {len(cond_rows)}",
        "",
    ]

    # Condition table
    if cond_rows:
        lines.append("static const NgpngCevCond g_cev_conds[] = {")
        ev_names = {i: str(ev.get("name") or f"event_{i}")
                    for i, ev in enumerate(valid_events)}
        for (ev_idx, cond_id, index, value, group_id, negate) in cond_rows:
            en    = ev_names.get(ev_idx, f"event_{ev_idx}")
            macro = custom_event_name_to_macro(en)
            grp_s = "0xFFu" if group_id == 0xFF else f"{group_id}u"
            lines.append(
                f"    {{ {macro}, {cond_id}u, {index}u, {value}u, {grp_s}, {negate}u }},"
                f"  /* {en} */"
            )
        lines.append("};")
    else:
        lines.append("/* No guard conditions defined — all custom events fire unconditionally. */")

    lines.append("")

    # Action table
    if act_rows:
        lines.append("static const NgpngEventAction g_custom_events[] = {")
        ev_names = {i: str(ev.get("name") or f"event_{i}")
                    for i, ev in enumerate(valid_events)}
        for (ev_idx, act_int, a0, a1, once) in act_rows:
            en    = ev_names.get(ev_idx, f"event_{ev_idx}")
            macro = custom_event_name_to_macro(en)
            lines.append(
                f"    {{ {macro}, {act_int}u, {a0}u, {a1}u, {once}u }},"
                f"  /* {en} */"
            )
        lines.append("};")
    else:
        lines.append("/* No custom events defined. */")

    lines += ["", "#endif /* NGPC_CUSTOM_EVENTS_H */", ""]
    return "\n".join(lines)


def write_custom_events_h(*, project_data: dict, export_dir: Path) -> Path:
    """Write ``ngpc_custom_events.h`` to *export_dir*. Returns the path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_custom_events_h(project_data=project_data)
    out = export_dir / _OUTPUT_FILENAME
    out.write_text(content, encoding="utf-8")
    return out


if __name__ == "__main__":
    import json, sys
    data = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else {}
    print(make_custom_events_h(project_data=data))
