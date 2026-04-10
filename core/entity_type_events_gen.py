"""
core/entity_type_events_gen.py — Generate ngpc_entity_type_events.h from
project entity type events (entity_types[i]["events"]).

Entity type events fire for *any* instance of that type, regardless of which
scene it is in. This makes them the no-code solution for procgen gameplay:
    - "any Goblin killed → inc kill_count"  (global, no scene needed)
    - "any Boss killed → goto credits scene"
    - "any Key collected → set flag HAS_KEY"

Scene-specific logic (e.g. "all goblins in THIS room dead → show exit") is
handled by new conditions entity_type_all_dead / entity_type_count_ge in the
existing NgpngTrigger scene trigger system (scene_level_gen.py).

Generated output — ngpc_entity_type_events.h:
    #define EV_ENTITY_DEATH    0u
    #define EV_ENTITY_COLLECT  1u
    ...
    #define TYPE_EVENT_COUNT   3
    typedef struct { u8 type_id; u8 event; u8 action; u8 a0; u8 a1; u8 once; } NgpngTypeEvent;
    static const NgpngTypeEvent g_type_events[] = { ... };

C runtime usage (template side):
    void ngpc_entity_dispatch_event(u8 type_id, u8 event_id) {
        for (u8 i = 0; i < TYPE_EVENT_COUNT; ++i) {
            const NgpngTypeEvent *ev = &g_type_events[i];
            if (ev->type_id == type_id && ev->event == event_id)
                ngpng_trigger_execute_action(ev->action, ev->a0, ev->a1);
        }
    }

Tree-shaking: only emits entries for types that are both:
    1. referenced by at least one entity instance in any scene
    2. have at least one event defined

If no events exist the header is still valid (TYPE_EVENT_COUNT = 0,
empty array declaration omitted).
"""
from __future__ import annotations

from pathlib import Path

from core.entity_types import (
    EVENT_IDS,
    get_entity_types,
    get_type_events,
)
from core.entity_types_gen import _enum_name, collect_used_type_ids  # reuse helpers

_OUTPUT_FILENAME = "ngpc_entity_type_events.h"

# Maps action string → TRIG_ACT_* integer (subset — extend as needed)
_ACT_TO_ID: dict[str, int] = {
    "emit_event":          0,
    "play_sfx":            1,
    "start_bgm":           2,
    "stop_bgm":            3,
    "fade_bgm":            4,
    "goto_scene":          5,
    "spawn_wave":          6,
    "pause_scroll":        7,
    "resume_scroll":       8,
    "spawn_entity":        9,
    "set_scroll_speed":   10,
    "play_anim":          11,
    "force_jump":         12,
    "enable_trigger":     13,
    "disable_trigger":    14,
    "screen_shake":       15,
    "set_cam_target":     16,
    "add_score":          17,
    "show_entity":        18,
    "hide_entity":        19,
    "move_entity_to":     20,
    "cycle_player_form":  21,
    "set_player_form":    22,
    "fire_player_shot":   23,
    "set_checkpoint":     24,
    "respawn_player":     25,
    "pause_entity_path":  26,
    "resume_entity_path": 27,
    "set_flag":           28,
    "clear_flag":         29,
    "set_variable":       30,
    "inc_variable":       31,
    "warp_to":            32,
    "lock_player_input":  33,
    "unlock_player_input":34,
    "enable_multijump":   35,
    "disable_multijump":  36,
    "reset_scene":        37,
    "show_dialogue":      38,
    "give_item":          39,
    "remove_item":        40,
    "unlock_door":        41,
    "enable_wall_grab":   42,
    "disable_wall_grab":  43,
    "set_gravity_dir":    44,
    "add_resource":       45,
    "remove_resource":    46,
    "unlock_ability":     47,
    "set_quest_stage":    48,
    "play_cutscene":      49,
    "end_game":           50,
    "dec_variable":       51,
    "add_health":         52,
    "set_health":         53,
    "fade_out":           63,
    "fade_in":            64,
    "save_game":          71,
}


def _int(v: object, default: int = 0) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def make_entity_type_events_h(*, project_data: dict) -> str:
    """Return the full content of ngpc_entity_type_events.h as a string."""
    used_ids = collect_used_type_ids(project_data)
    all_types = get_entity_types(project_data)

    # Build ordered list of used types (same order as entity_types_gen.py)
    used_types = [t for t in all_types
                  if isinstance(t, dict) and t.get("id") in used_ids]

    # type_id index: position in the used_types list (matches ET_* enum in ngpc_entity_types.h)
    type_index: dict[str, int] = {
        str(t.get("id", "")): i for i, t in enumerate(used_types)
    }

    # Build scene_id → scene_index map for goto_scene resolution
    scene_id_to_idx: dict[str, int] = {}
    for i, sc in enumerate(project_data.get("scenes", []) or []):
        if isinstance(sc, dict):
            sid = str(sc.get("id") or "").strip()
            if sid:
                scene_id_to_idx[sid] = i

    # Collect all (type_id_int, event_int, action_int, a0, a1, once) tuples
    entries: list[tuple[int, int, int, int, int, int]] = []

    for t in used_types:
        tid_str = str(t.get("id") or "")
        tid_int = type_index.get(tid_str, 255)
        if tid_int > 254:
            continue
        events = get_type_events(t)
        for ev_name, actions in events.items():
            if not isinstance(actions, list):
                continue
            ev_int = EVENT_IDS.index(ev_name) if ev_name in EVENT_IDS else None
            if ev_int is None:
                continue
            for act in actions:
                if not isinstance(act, dict):
                    continue
                act_str = str(act.get("action") or "emit_event").lower()
                act_int = _ACT_TO_ID.get(act_str, 0)
                once = 1 if act.get("once") else 0

                # Resolve a0 based on action type
                if act_str in ("goto_scene", "warp_to"):
                    sid = str(act.get("scene_to") or "").strip()
                    a0 = int(scene_id_to_idx.get(sid, _int(act.get("a0")))) & 0xFF
                elif act_str in ("set_flag", "clear_flag", "toggle_flag",
                                 "set_variable", "inc_variable", "dec_variable"):
                    a0 = _int(act.get("flag_var_index")) & 0xFF
                else:
                    a0 = _int(act.get("a0")) & 0xFF

                a1 = _int(act.get("a1")) & 0xFF
                entries.append((tid_int, ev_int, act_int, a0, a1, once))

    lines: list[str] = [
        "/* ngpc_entity_type_events.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — configure via Globals > Entity Types > Events */",
        "#ifndef NGPC_ENTITY_TYPE_EVENTS_H",
        "#define NGPC_ENTITY_TYPE_EVENTS_H",
        "",
        "/* Entity event IDs — pass to ngpc_entity_dispatch_event() */",
    ]
    for i, ev_name in enumerate(EVENT_IDS):
        macro = "EV_" + ev_name.upper()
        lines.append(f"#define {macro:<28} {i}u")

    lines += [
        "",
        "#ifndef NGPNG_TYPE_EVENT_T",
        "#define NGPNG_TYPE_EVENT_T",
        "typedef struct {",
        "    u8 type_id;  /* EntityTypeId enum value (ET_*) */",
        "    u8 event;    /* EV_ENTITY_* */",
        "    u8 action;   /* TRIG_ACT_* */",
        "    u8 a0;",
        "    u8 a1;",
        "    u8 once;     /* 1 = fire only once per scene load */",
        "} NgpngTypeEvent;",
        "#endif",
        "",
        f"#define TYPE_EVENT_COUNT {len(entries)}",
        "",
    ]

    if entries:
        lines.append("static const NgpngTypeEvent g_type_events[] = {")
        # Collect display names for comments
        type_names = {type_index[str(t.get("id", ""))]: str(t.get("name") or "?")
                      for t in used_types if str(t.get("id", "")) in type_index}
        ev_name_by_id = {i: n for i, n in enumerate(EVENT_IDS)}
        for (tid, ev, act, a0, a1, once) in entries:
            tn = type_names.get(tid, f"type_{tid}")
            en = ev_name_by_id.get(ev, f"ev_{ev}")
            enum = _enum_name(tn)
            lines.append(f"    {{ {enum}, {ev}u, {act}u, {a0}u, {a1}u, {once}u }},  /* {tn} {en} */")
        lines.append("};")
    else:
        lines.append("/* No entity type events defined. */")

    lines += ["", "#endif /* NGPC_ENTITY_TYPE_EVENTS_H */", ""]
    return "\n".join(lines)


def write_entity_type_events_h(*, project_data: dict, export_dir: Path) -> Path:
    """Write ``ngpc_entity_type_events.h`` to *export_dir*. Returns the path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_entity_type_events_h(project_data=project_data)
    out = export_dir / _OUTPUT_FILENAME
    out.write_text(content, encoding="utf-8")
    return out


if __name__ == "__main__":
    import json, sys
    data = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else {}
    print(make_entity_type_events_h(project_data=data))
