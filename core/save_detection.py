"""
Helpers for detecting whether a project uses the generated flash save runtime.
"""

from __future__ import annotations


def _action_is_save_game(action: object) -> bool:
    if action == 71:
        return True
    if isinstance(action, str):
        text = action.strip()
        if text == "save_game":
            return True
        if text.isdigit():
            return int(text) == 71
    return False


def project_has_save_triggers(project_data: dict | None) -> bool:
    """
    Return True when any scene trigger requires the generated flash save runtime.

    Supports both trigger layouts used by NgpCraft projects:
    - legacy single-action triggers:
        {"action": "save_game", ...}
    - newer multi-action triggers:
        {"actions": [{"action_id": 71}, ...], ...}
    """
    scenes = (project_data or {}).get("scenes", [])
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        for trig in (scene.get("triggers") or []):
            if not isinstance(trig, dict):
                continue
            if _action_is_save_game(trig.get("action")):
                return True
            for act in (trig.get("actions") or []):
                if not isinstance(act, dict):
                    continue
                if _action_is_save_game(act.get("action_id")):
                    return True
                if _action_is_save_game(act.get("action")):
                    return True
    return False
