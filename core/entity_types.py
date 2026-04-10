"""
core/entity_types.py — Project-global entity type archetypes.

An entity type defines default properties (role, behavior, AI params, etc.)
that scene instances can inherit. Instances stored in scenes keep their own
explicit values and are not automatically rewritten when a type changes —
the type is a creation-time preset, not a live binding.

Public API:
    ROLE_VALUES        — tuple of valid role strings
    BEHAVIOR_LABELS    — (internal_value, display_label) pairs
    DIRECTION_LABELS   — (internal_value, display_label) pairs
    ET_DEFAULTS        — default field values for a new type
    EVENT_IDS          — ordered list of event name strings (index = C EV_* value)
    EVENTS_BY_ROLE     — dict mapping role → list of applicable event names

    new_entity_type(name) -> dict
    get_entity_types(project_data) -> list[dict]
    get_entity_type_by_id(project_data, type_id) -> dict | None
    get_type_events(entity_type) -> dict[str, list[dict]]

Type event format (stored in entity_type["events"]):
    {
        "entity_death": [
            { "action": "inc_variable", "flag_var_index": 0, "a1": 0, "once": False },
            { "action": "play_sfx",     "a0": 3,             "a1": 0, "once": False }
        ],
        "entity_spawn": [
            { "action": "start_bgm", "a0": 2, "a1": 0, "once": False }
        ]
    }

Available events and their C EV_* index (see EVENT_IDS for the authoritative list):
    entity_death        ( 0) — any instance killed
    entity_collect      ( 1) — any instance collected/picked up (role: item)
    entity_activate     ( 2) — any instance activated (role: npc/trigger)
    entity_hit          ( 3) — any instance hit by player
    entity_spawn        ( 4) — any instance spawned at runtime
    entity_btn_a/b/opt  (5-7) — button pressed near an instance
    entity_btn_up/down  (8-9) — d-pad up/down near an instance
    entity_btn_left/right (10-11) — d-pad left/right near an instance
    entity_player_enter (12) — player enters proximity range
    entity_player_exit  (13) — player leaves proximity range
    entity_timer        (14) — periodic timer fires (rate set per instance)
    entity_low_hp       (15) — HP drops below threshold

NOTE: "on_death" (condition id 49) in scene triggers means the PLAYER dies.
      entity_death on the player type = same semantic, but as a global cross-scene event.
      Entity type events use distinct names (entity_death, etc.) to avoid collision.
"""

from __future__ import annotations

from core.entity_roles import ROLE_VALUES


# ---------------------------------------------------------------------------
# Entity type events
# ---------------------------------------------------------------------------

# Ordered list — index = C EV_ENTITY_* value in ngpc_entity_type_events.h
EVENT_IDS: tuple[str, ...] = (
    "entity_death",         #  0 — instance killed
    "entity_collect",       #  1 — instance collected / picked up
    "entity_activate",      #  2 — instance activated (NPC interact, trigger)
    "entity_hit",           #  3 — instance hit by player
    "entity_spawn",         #  4 — instance spawned at runtime
    "entity_btn_a",         #  5 — button A pressed near instance
    "entity_btn_b",         #  6 — button B pressed near instance
    "entity_btn_opt",       #  7 — Option pressed near instance
    "entity_btn_up",        #  8 — Up pressed near instance
    "entity_btn_down",      #  9 — Down pressed near instance
    "entity_btn_left",      # 10 — Left pressed near instance
    "entity_btn_right",     # 11 — Right pressed near instance
    "entity_player_enter",  # 12 — player enters entity proximity range
    "entity_player_exit",   # 13 — player leaves entity proximity range
    "entity_timer",         # 14 — periodic timer fires (rate set per instance)
    "entity_low_hp",        # 15 — HP drops below threshold (boss phase change, etc.)
)

# Which events make sense for each role (used to filter the UI dropdown)
EVENTS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "enemy":    ("entity_death", "entity_hit", "entity_spawn",
                 "entity_btn_a", "entity_btn_b",
                 "entity_player_enter", "entity_player_exit",
                 "entity_timer", "entity_low_hp"),
    "item":     ("entity_collect", "entity_spawn",
                 "entity_player_enter"),
    "npc":      ("entity_activate", "entity_spawn",
                 "entity_btn_a", "entity_btn_b", "entity_btn_opt",
                 "entity_btn_up", "entity_btn_down",
                 "entity_btn_left", "entity_btn_right",
                 "entity_player_enter", "entity_player_exit",
                 "entity_timer"),
    "trigger":  ("entity_activate",
                 "entity_btn_a", "entity_btn_b", "entity_btn_opt",
                 "entity_btn_up", "entity_btn_down",
                 "entity_btn_left", "entity_btn_right",
                 "entity_player_enter", "entity_player_exit"),
    "platform": ("entity_activate", "entity_spawn",
                 "entity_btn_a", "entity_btn_b",
                 "entity_btn_left", "entity_btn_right",
                 "entity_player_enter", "entity_player_exit"),
    "block":    ("entity_death", "entity_activate", "entity_spawn",
                 "entity_hit", "entity_btn_a", "entity_btn_b",
                 "entity_player_enter", "entity_timer", "entity_low_hp"),
    "prop":     ("entity_activate", "entity_spawn",
                 "entity_btn_a", "entity_btn_b", "entity_btn_opt",
                 "entity_btn_left", "entity_btn_right",
                 "entity_player_enter", "entity_player_exit",
                 "entity_timer"),
    "player":   ("entity_death", "entity_hit", "entity_spawn", "entity_low_hp",
                 "entity_btn_a", "entity_btn_b", "entity_btn_opt",
                 "entity_timer"),
}


# (stored_value, display label)
BEHAVIOR_LABELS: tuple[tuple[int, str], ...] = (
    (0, "Patrol"),
    (1, "Chase"),
    (2, "Fixed"),
    (3, "Random"),
)

DIRECTION_LABELS: tuple[tuple[int, str], ...] = (
    (0, "Droite (0)"),
    (1, "Haut (1)"),
    (2, "Gauche (2)"),
    (3, "Bas (3)"),
)

# Default values stored in every new archetype
ET_DEFAULTS: dict[str, object] = {
    "role":            "enemy",
    "behavior":        0,
    "ai_speed":        1,
    "ai_range":        10,
    "ai_lose_range":   16,
    "ai_change_every": 60,
    "direction":       0,
    "data":            0,
    "flags":           0,
}


def new_entity_type(name: str) -> dict:
    """Return a fresh entity type dict with all defaults.

    Note: ``"events"`` is intentionally absent — it is initialised on first
    write so we never share a mutable default dict between instances.
    """
    safe = str(name or "").strip().replace(" ", "_") or "type"
    return {"id": f"etype_{safe}", "name": safe, **ET_DEFAULTS}


def get_type_events(entity_type: dict) -> dict[str, list[dict]]:
    """Return the events dict for an entity type, defaulting to {}.

    Always returns a plain dict — never None, never a non-dict value.
    """
    if not isinstance(entity_type, dict):
        return {}
    ev = entity_type.get("events")
    return ev if isinstance(ev, dict) else {}


def get_entity_types(project_data: dict) -> list[dict]:
    """Return the entity_types list from project_data, or []."""
    if not isinstance(project_data, dict):
        return []
    types = project_data.get("entity_types", [])
    return types if isinstance(types, list) else []


def get_entity_type_by_id(project_data: dict, type_id: str) -> dict | None:
    """Find an entity type by its id field."""
    for t in get_entity_types(project_data):
        if isinstance(t, dict) and t.get("id") == type_id:
            return t
    return None
