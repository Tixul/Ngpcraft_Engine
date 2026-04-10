"""
core/custom_events.py — Project-global custom event bus.

Custom events are named integers dispatched by ngpc_emit_event(u8 id).
They are defined once in Globals → Événements, and can be fired from:
  - entity type events (action "emit_event", a0 = event index)
  - scene triggers    (action "emit_event", a0 = event index)

Each event has optional guard conditions (AND + OR groups) and one or
more actions that execute when the guard passes.

JSON format (project_data["custom_events"]):
    [
        {
            "id":      "cev_boss_phase_2",
            "name":    "boss_phase_2",
            "category": "Combat",
            "conditions": [                         # primary AND group
                { "cond": "flag_set", "index": 2, "value": 0, "negate": false }
            ],
            "or_groups": [                          # OR-alternative groups
                [
                    { "cond": "variable_ge", "index": 0, "value": 5, "negate": false }
                ]
            ],
            "actions": [
                { "action": "start_bgm",    "a0": 2,  "once": false },
                { "action": "screen_shake", "a0": 3,  "once": false }
            ]
        },
        ...
    ]

Guard logic:
    - No conditions AND no or_groups → always fire
    - conditions[] present: fire if ALL primary conditions met
    - or_groups[] present: also fire if ALL conditions in ANY or_group met
    → overall: (all conditions[]) OR (any or_group fully met)

The C index of an event = its position in the list (0-based).
Renaming does not change existing emit_event(id) calls — only reordering does.

Public API:
    get_custom_events(project_data)               → list[dict]
    get_custom_event_actions(event)               → list[dict]
    get_custom_event_conditions(event)            → list[dict]
    get_custom_event_or_groups(event)             → list[list[dict]]
    new_custom_event(name, category="")           → dict
    new_cev_condition(cond, index, value, negate) → dict
    custom_event_index(project_data, eid)         → int | None
    custom_event_name_to_macro(name)              → str
"""
from __future__ import annotations

import re


def get_custom_events(project_data: dict) -> list[dict]:
    """Return the custom_events list from project_data, or []."""
    if not isinstance(project_data, dict):
        return []
    evs = project_data.get("custom_events", [])
    return evs if isinstance(evs, list) else []


def get_custom_event_actions(event: dict) -> list[dict]:
    """Return the actions list for a custom event, defaulting to []."""
    if not isinstance(event, dict):
        return []
    acts = event.get("actions", [])
    return acts if isinstance(acts, list) else []


def get_custom_event_conditions(event: dict) -> list[dict]:
    """Return the primary AND conditions list for a custom event, defaulting to []."""
    if not isinstance(event, dict):
        return []
    conds = event.get("conditions", [])
    return conds if isinstance(conds, list) else []


def get_custom_event_or_groups(event: dict) -> list[list[dict]]:
    """Return the OR-alternative condition groups for a custom event, defaulting to []."""
    if not isinstance(event, dict):
        return []
    groups = event.get("or_groups", [])
    if not isinstance(groups, list):
        return []
    return [g for g in groups if isinstance(g, list)]


def new_custom_event(name: str, category: str = "") -> dict:
    """Return a fresh custom event dict with no conditions and no actions."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip()).strip("_") or "event"
    return {
        "id": f"cev_{safe}",
        "name": safe,
        "category": str(category),
        "conditions": [],
        "or_groups": [],
        "actions": [],
    }


def new_cev_condition(
    cond: str,
    index: int = 0,
    value: int = 0,
    negate: bool = False,
) -> dict:
    """Return a fresh condition dict for a custom event guard."""
    return {
        "cond": str(cond),
        "index": int(index) & 0xFF,
        "value": int(value) & 0xFFFF,
        "negate": bool(negate),
    }


def custom_event_index(project_data: dict, event_id: str) -> int | None:
    """Return the 0-based C index for a custom event by its id string, or None."""
    for i, ev in enumerate(get_custom_events(project_data)):
        if isinstance(ev, dict) and ev.get("id") == event_id:
            return i
    return None


def custom_event_name_to_macro(name: str) -> str:
    """Convert an event name to its C macro (e.g. 'boss_phase_2' → 'CEV_BOSS_PHASE_2')."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", str(name or "")).strip("_").upper()
    if not safe:
        safe = "EVENT"
    return f"CEV_{safe}"
