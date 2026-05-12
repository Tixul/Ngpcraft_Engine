"""
core/mechanics.py — Project-level gameplay mechanics registry.

Each "mechanic" is a toggleable gameplay feature (shooting, bounce, hit flash,
death FX, etc.). The project chooses which ones to enable in the Mechanics tab;
disabled mechanics:
  - hide their config UI in scene/entity panels (less clutter)
  - skip emitting their per-type table pointer in the scene struct (runtime
    guards (`if (sc->type_X)`) already short-circuit when the pointer is NULL)

Public API:
    MECHANICS_REGISTRY  — list of MechanicEntry dicts (see below)
    get_mechanics(project_data)             -> dict[str, bool]
    is_mechanic_enabled(project_data, mid)  -> bool
    set_mechanic_enabled(project_data, mid, enabled)  — mutates in place

Backward compat: a project with no "mechanics" key gets DEFAULT_ENABLED for every
mechanic (i.e. legacy projects keep working without any UI change required).

Each registry entry is a dict with the following keys:
    id              — unique identifier (str, snake_case)
    label           — UI label (str, French by default)
    description     — one-paragraph blurb for the Mechanics tab
    default_enabled — bool, ON for legacy compat or OFF for niche features
    category        — "combat" / "audio" / "physics" / "spawning" / "score" / "movement" / "feedback"
    config_locations — list of (path_label, hint) tuples telling the user WHERE
                       to configure this mechanic in the editor. Each tuple is
                       displayed as one row in the Mechanics tab so the user
                       has a clear breadcrumb (no hunting through menus).
    keywords        — list[str] of extra search tokens (synonyms, EN labels,
                       genre hints) so the Mechanics tab search field finds
                       the mechanic even if the user types the EN word.

Adding a new mechanic = append a dict to MECHANICS_REGISTRY.
"""

from __future__ import annotations


# Registry — order matters: this is the display order in the Mechanics tab
# (grouped by category, but order within a category follows the registry).
MECHANICS_REGISTRY: list[dict] = [
    # --- Combat ---
    {
        "id":              "shooting",
        "label":           "Tir & projectiles",
        "description":     "Le joueur et/ou les ennemis tirent des balles. Bullet sprite, vitesse, cadence, condition de tir (Toujours / Portée / Face joueur) configurables par type d'entité.",
        "default_enabled": True,
        "category":        "combat",
        "config_locations": [
            ("Scene → panneau droit (entité sélectionnée) → groupe « Tir & projectiles »",
             "Coche « Peut tirer » sur un ennemi, ou choisis un bouton de tir pour le joueur."),
        ],
        "keywords": ["shoot", "fire", "bullet", "projectile", "tir", "weapon"],
    },
    {
        "id":              "hit_feedback",
        "label":           "Feedback de dégât",
        "description":     "Clignote le sprite d'une entité quand elle prend des dégâts sans mourir. Aide le joueur à voir qu'il a touché.",
        "default_enabled": True,
        "category":        "combat",
        "config_locations": [
            ("Scene → panneau droit (entité ennemi sélectionnée) → groupe « Feedback de dégât »",
             "Règle la durée du flash (0 = désactivé)."),
        ],
        "keywords": ["damage", "flash", "blink", "hit", "feedback"],
    },
    {
        "id":              "death_fx",
        "label":           "FX d'explosion à la mort",
        "description":     "Sprite séparé joué à la mort d'une entité (différent de la spritesheet de l'entité elle-même). Idéal pour explosions, étincelles, fumée.",
        "default_enabled": True,
        "category":        "combat",
        "config_locations": [
            ("Scene → panneau droit (entité ennemi/joueur) → groupe « Mort & explosion » → combo « Sprite explosion »",
             "Choisis un sprite avec role=prop, idéalement non placé dans la scène."),
        ],
        "keywords": ["death", "explosion", "fx", "particle", "vfx"],
    },
    {
        "id":              "death_actions",
        "label":           "Actions à la mort (entity_death event)",
        "description":     "Wire des actions automatiques à la mort d'un type d'entité : play_sfx, add_score, spawn_entity (loot), set_flag, emit_custom_event, etc.",
        "default_enabled": True,
        "category":        "combat",
        "config_locations": [
            ("Scene → panneau droit (entité ennemi/joueur) → groupe « Mort & explosion » → section « Actions à la mort »",
             "Le bouton « + Ajouter » ouvre le même dialog que Globals tab → Entity Types → Events."),
            ("Globals tab → Entity Types → onglet « Events » (équivalent — config par archetype directement)",
             "Alternative pour gérer les events plus en détail (16 events disponibles, pas que death)."),
        ],
        "keywords": ["death", "event", "action", "loot", "spawn", "trigger", "sfx"],
    },

    # --- Audio ---
    {
        "id":              "sfx_fire",
        "label":           "SFX au tir",
        "description":     "Son joué via Sfx_Play() à chaque tir. ID configurable par type d'entité.",
        "default_enabled": True,
        "category":        "audio",
        "config_locations": [
            ("Scene → panneau droit (entité shooter) → groupe « Tir & projectiles » → spinbox « SFX au tir »",
             "Range 0-254 = ID du SFX ; « (aucun) » = silencieux."),
            ("Globals tab → Sounds (pour préparer les IDs SFX en amont)",
             "Affiche la liste des SFX disponibles dans le projet."),
        ],
        "keywords": ["sfx", "sound", "audio", "fire", "shoot", "bang"],
    },

    # --- Physics ---
    {
        "id":              "bounce",
        "label":           "Rebond projectile",
        "description":     "Les projectiles rebondissent sur les bords de la caméra au lieu de despawn. Configurable par sprite-bullet : rebond horizontal (murs G/D), vertical (haut/bas), SFX optionnel. Idéal pour Pong, casse-brique, puzzle ricochet, grenades.",
        "default_enabled": False,  # niche — opt-in
        "category":        "physics",
        "config_locations": [
            ("Scene → panneau droit (entité dont le sprite sert de projectile) → groupe « Rebond (projectile) »",
             "Coche rebond H et/ou V ; assigne un SFX optionnel. La config est par sprite-type, donc applicable à tous les usages de ce sprite comme bullet."),
        ],
        "keywords": ["bounce", "rebound", "reflect", "ricochet", "pong", "breakout", "physics"],
    },

    # --- Combat (sprite-level stats) ---
    {
        "id":              "combat_stats",
        "label":           "Stats HP / dégâts / invincibilité",
        "description":     "Champs HP, dégâts au contact, frames d'invincibilité par type d'entité. Si désactivé, le sprite-type n'a pas de système HP/damage (jeux puzzle, narratif, casual).",
        "default_enabled": True,
        "category":        "combat",
        "config_locations": [
            ("Sprite Setup → groupe « Combat »",
             "Configure hp / damage / inv_frames pour chaque type de sprite. Si OFF, le groupe se cache et le codegen NULL les pointeurs hp/damage."),
        ],
        "keywords": ["hp", "health", "damage", "invul", "iframes", "combat", "stats"],
    },

    # --- Score ---
    {
        "id":              "scoring",
        "label":           "Score (points)",
        "description":     "Système de score : valeur de points par type d'entité défait. Si désactivé, le champ « Score » se cache du Sprite Setup.",
        "default_enabled": True,
        "category":        "score",
        "config_locations": [
            ("Sprite Setup → groupe « Misc » → champ « Score »",
             "Valeur ajoutée au score du joueur quand cette entité est défaite."),
        ],
        "keywords": ["score", "points", "scoring", "kill", "bonus"],
    },

    # --- Movement (genre-specific physics) ---
    {
        "id":              "topdown_vehicle",
        "label":           "Physique top-down véhicule",
        "description":     "Système de contrôle véhicule top-down (vitesse max, accélération, freinage, friction, taux de virage, marche arrière). Pour jeux de course, Mario Kart-like, vues plongeantes avec inertie.",
        # Default ON for backward-compat: legacy projects (Windcup-style) may
        # have td_* fields populated even if the user only edits a platformer
        # now. Forcing OFF by default would silently hide their existing data.
        "default_enabled": True,
        "category":        "movement",
        "config_locations": [
            ("Sprite Setup → groupe « Top-down »",
             "9 champs td_* configurent la physique véhicule. Si désactivé tout le groupe se cache (pertinent uniquement pour les jeux top-down avec véhicule)."),
        ],
        "keywords": ["topdown", "top-down", "vehicle", "racing", "kart", "car", "physics"],
    },
    {
        "id":              "platformer_physics",
        "label":           "Physique platformer (gravité / saut)",
        "description":     "Champs gravité, force de saut, vitesse de chute max — physique verticale typique d'un platformer. Si désactivé (jeux top-down / shmup / puzzle), ces 3 champs se cachent du Sprite Setup.",
        "default_enabled": True,
        "category":        "movement",
        "config_locations": [
            ("Sprite Setup → groupe « Physics » → champs gravité / saut / chute max",
             "Si OFF, les 3 champs jump_force / gravity / max_fall_speed sont masqués. Les autres champs physiques (max_speed, accel, friction) restent visibles."),
        ],
        "keywords": ["jump", "gravity", "platformer", "physics", "fall", "vertical"],
    },
    {
        "id":              "option_satellite",
        "label":           "Option satellite (escort drone Gradius)",
        "description":     "Drone(s) qui suivent le joueur avec un délai. Reproduit player_x/y dans un ring buffer puis affiche N satellites aux positions retardées. Tirent en sync avec le joueur (option). Coût OAM = N×1 sprite — voir l'estimateur dans la config inline. Per-scene override possible (count + enable).",
        "default_enabled": False,
        "category":        "combat",
        "config_locations": [
            ("Mechanics tab → groupe « Option satellite » → tout configurable inline",
             "Nombre d'options, délai, formation, tir sync, sprite, et estimateur OAM."),
            ("Scene → sous-onglet « Mechanics » → groupe « Option satellite » (override)",
             "Par-scène : désactiver pour une scène boss-room OAM-saturée, ou changer le count."),
            ("Triggers → action spawn_option / despawn_option / set_option_count",
             "Pour acquérir un drone via power-up ou despawn en cutscene."),
        ],
        "keywords": ["option", "satellite", "drone", "escort", "gradius", "nemesis", "trail", "follower", "shmup"],
        "inline_config": "option_satellite",
    },
    {
        "id":              "dash",
        "label":           "Dash + i-frames",
        "description":     "Dash directionnel court (burst de vitesse pendant N frames) avec invulnérabilité automatique + cooldown. Idéal action, action-RPG (roulade), platformer (dash horizontal), beat'em up.",
        "default_enabled": False,
        "category":        "movement",
        "config_locations": [
            ("Scene → panneau droit (entité player sélectionnée) → groupe « Dash »",
             "Bouton, durée, vitesse, cooldown, i-frames. Config par sprite-type joueur (chaque forme peut avoir son dash distinct)."),
        ],
        "keywords": ["dash", "roll", "burst", "evade", "dodge", "iframes", "invincibility"],
    },

    # --- Flow / state machines ---
    {
        "id":              "game_over_flow",
        "label":           "Game Over flow (continue / final / name entry)",
        "description":     "State machine 3 écrans à la fin de partie : Continue countdown (YES/NO) → Final game over → Name entry (si MECH-6 hi-score activé et score qualifie). Chaque écran a son BG scène configurable, son texte custom, sa BGM optionnelle.",
        "default_enabled": False,
        "category":        "feedback",
        "config_locations": [
            ("Mechanics tab → groupe « Game Over flow » → tout configurable inline",
             "Active/désactive chaque écran, choisis BG par écran (scene picker), customise textes et durées."),
            ("Mechanics tab → mécanique « highscore »",
             "À activer en parallèle si tu veux name entry + leaderboard à la fin."),
        ],
        "keywords": ["game over", "continue", "name entry", "screen", "state machine", "flow", "arcade"],
        "inline_config": "game_over_flow",
    },

    # --- Score / persistence ---
    {
        "id":              "highscore",
        "label":           "Tableau hi-score (top-N + flash save)",
        "description":     "Top-N des meilleurs scores avec initiales par joueur. Persistence flash automatique entre sessions (versionnée + checksum). Standard arcade — utilisable par tout jeu avec score.",
        "default_enabled": False,
        "category":        "score",
        "config_locations": [
            ("Mechanics tab → groupe « Tableau hi-score » → tout configurable inline",
             "Nombre d'entrées, longueur initiales, magic value, scène de fond pour le screen name-entry, toggle save flash."),
            ("Triggers (scène ou entité) → action submit_score / show_highscore / clear_highscores",
             "Pour soumettre le score courant, afficher le tableau, ou reset (debug). submit_score déclenche aussi le screen name-entry si le score qualifie."),
        ],
        "keywords": ["highscore", "hi-score", "leaderboard", "score", "ranking", "top", "name entry", "arcade", "flash save"],
        "inline_config": "highscore",
    },

    # --- Feedback (visual polish) ---
    {
        "id":              "damage_popup",
        "label":           "Popup de dégâts (chiffre flottant)",
        "description":     "Chiffre de dégâts rendu via ngpc_text_print_dec sur un plan tilemap qui MONTE de quelques pixels avant de disparaître. ⚠ Le plan cible (SCR1 ou SCR2) doit être configuré comme FIXE dans Layout sinon le popup scrollera avec le fond. Typique : SCR2 utilisé en HUD-fixe.",
        "default_enabled": False,
        "category":        "feedback",
        "config_locations": [
            ("Mechanics tab → groupe « Popup de dégâts » → choisis le plan + durée + montée",
             "Configuration inline ici. ⚠ Le plan choisi doit être déclaré fixe dans Scene → Layout → groupe Camera (Parallaxe 0%) sinon les chiffres bougent avec le scroll."),
            ("Scene → Layout → groupe « Caméra » → parallaxe du plan cible",
             "Configurer 0% de parallaxe (= plan fixe) sur le plan utilisé par les popups."),
        ],
        "keywords": ["damage", "popup", "floating text", "number", "hit feedback", "juice", "tilemap"],
        "inline_config": "damage_popup",
    },
    {
        "id":              "fade_transitions",
        "label":           "Fondus palette (mort + transitions + triggers)",
        "description":     "Activation des fondus palette réutilisables : (1) automatiquement à la mort du joueur, (2) sur transitions de scène, (3) via les trigger actions fade_out / fade_in. Tous partagent la même config (vitesse/couleur) définie ici.",
        "default_enabled": False,
        "category":        "feedback",
        "config_locations": [
            ("Mechanics tab → groupe « Fondus palette » → règle directement vitesse/couleur",
             "Configuration globale ici : wait frames avant fondu (mort), durée du fondu, couleur cible. Toutes les utilisations (mort, transition, trigger) lisent ces valeurs."),
            ("Triggers (scène ou entité) → action fade_out / fade_in",
             "Pour déclencher un fondu manuellement (boss room, cutscene, transition scène). Utilise les mêmes vitesse/couleur que ci-dessus."),
        ],
        "keywords": ["fade", "transition", "death", "wipe", "polish", "feedback", "game over", "palfx", "cutscene"],
        "inline_config": "fade_transitions",
    },

    # --- Spawning ---
    {
        "id":              "wave_scroll_spawn",
        "label":           "Vagues scroll-based (par-scène)",
        "description":     "Active la possibilité pour chaque scène de basculer son système waves entre frame-based (legacy) ou scroll-based (Nemesis-style). Le réglage se fait par-scène dans Scene → Vagues, jamais global. Les projets existants gardent leur mode frame-based — opt-in pur.",
        "default_enabled": False,
        "category":        "spawning",
        "config_locations": [
            ("Scene → sous-onglet Vagues → combo « Mode de déclenchement »",
             "Par-scène : « Frame-based (legacy) » par défaut, ou « Scroll horizontal (cam_px) » / « Scroll vertical (cam_py) ». Chaque scène est indépendante."),
            ("Scene → sous-onglet Vagues → wave sélectionnée → spinbox « Position scroll »",
             "Visible en mode scroll-based. Remplace le « Delay (frames) » du mode frame-based."),
        ],
        "keywords": ["wave", "vague", "scroll", "spawn", "timeline", "shmup", "nemesis", "stargunner"],
    },
    {
        "id":              "wave_spawning",
        "label":           "Vagues d'ennemis",
        "description":     "Spawn programmé d'ennemis dans une scène (par timer ou par scroll position). Idéal pour shmups, runners, beat'em up, arènes survival.",
        "default_enabled": True,  # legacy compat: existing projects keep their waves visible
        "category":        "spawning",
        "config_locations": [
            ("Scene → sous-onglet « Vagues »",
             "Définit la séquence de waves : délai, type d'ennemi, nombre, position. Si tu fais un jeu sans waves (puzzle, RPG…), désactive ici pour cacher le sous-onglet."),
        ],
        "keywords": ["wave", "vague", "spawn", "shmup", "horde", "runner", "arena"],
    },
    {
        "id":              "procgen",
        "label":           "Génération procédurale",
        "description":     "Système de génération procédurale de niveau (dungeongen, design map, cave DFS). Pour roguelikes, dungeons aléatoires, niveaux variables.",
        "default_enabled": True,  # legacy compat
        "category":        "spawning",
        "config_locations": [
            ("Scene → sous-onglet « Procgen »",
             "3 sous-onglets internes : Design Map / DungeonGen / Procgen Assets. Désactive ici si ton jeu n'utilise pas de génération procédurale pour cacher tout le sous-onglet."),
        ],
        "keywords": ["procgen", "procedural", "random", "dungeon", "cave", "roguelike", "level gen"],
    },
]


# Category labels (FR — i18n later if needed)
CATEGORY_LABELS: dict[str, str] = {
    "combat":   "Combat",
    "audio":    "Audio",
    "physics":  "Physique",
    "spawning": "Spawn",
    "score":    "Score",
    "movement": "Mouvement",
    "feedback": "Feedback",
}


# Category display order (categories not listed go last in registry order)
CATEGORY_DISPLAY_ORDER: tuple[str, ...] = (
    "combat", "audio", "physics", "spawning", "score", "movement", "feedback",
)


def get_mechanics(project_data: dict | None) -> dict[str, bool]:
    """Return the full enable state for every known mechanic, merging stored
    values with defaults. Unknown keys in the project are ignored."""
    if not isinstance(project_data, dict):
        return {m["id"]: m["default_enabled"] for m in MECHANICS_REGISTRY}
    raw = project_data.get("mechanics", {})
    if not isinstance(raw, dict):
        raw = {}
    result: dict[str, bool] = {}
    for m in MECHANICS_REGISTRY:
        result[m["id"]] = bool(raw.get(m["id"], m["default_enabled"]))
    return result


def is_mechanic_enabled(project_data: dict | None, mech_id: str) -> bool:
    """Convenience: single-mechanic check. Returns False for unknown ids."""
    return get_mechanics(project_data).get(mech_id, False)


def set_mechanic_enabled(project_data: dict, mech_id: str, enabled: bool) -> None:
    """Mutate project_data["mechanics"][mech_id]. Creates the dict if missing."""
    if not isinstance(project_data, dict):
        return
    mechs = project_data.setdefault("mechanics", {})
    if not isinstance(mechs, dict):
        mechs = {}
        project_data["mechanics"] = mechs
    mechs[mech_id] = bool(enabled)


# ---------------------------------------------------------------------------
# Per-mechanic detailed config (stored under project["mechanics_config"][id])
# ---------------------------------------------------------------------------
# Some mechanics expose tunable parameters in the MechanicsTab itself (instead
# of per-entity). This is the storage location and helpers for that pattern.

# Default config dict per mechanic that exposes inline params.
MECHANICS_CONFIG_DEFAULTS: dict[str, dict] = {
    "fade_transitions": {
        "wait_frames":  60,    # frames to hold gameplay frozen after HP=0 (death case)
        "fade_frames":  64,    # frames the palette fade itself lasts
        "fade_color":   "black",  # "black" | "white"
    },
    "damage_popup": {
        "ttl_frames":  40,
        "rise_tiles":   2,
        "plane":      "SCR2",
        "palette":      1,
    },
    "highscore": {
        "num_entries":      10,
        "initials_length":   3,
        "magic_value":   "NgpH",
        "save_to_flash":  True,
        "bg_scene_id":     "",
        "default_initials": "AAA",
        "default_score":      0,
        "auto_submit":     True,
    },
    "option_satellite": {
        # Number of drones to render at once. 1-4 is reasonable; each adds 1
        # sprite to the OAM budget every frame. Going higher means cutting HUD
        # or enemy slots — the inline config widget shows a live estimator.
        "max_options":              2,
        # Frames of lag between the player and the FIRST drone. Smaller =
        # tighter trail (drone glued to player), larger = laggier follow.
        "delay_frames":            12,
        # Frames of additional lag between drone N and drone N+1. With
        # delay_frames=12 + spacing_frames=8 and 3 drones, lookups are at
        # 12 / 20 / 28 frames back in the ring buffer.
        "spacing_frames":           8,
        # If True, drones fire on the same frame the player presses fire.
        "fire_sync_with_player": True,
        # Sprite type used for the drone visual. Must be a sprite registered in
        # the project (any scene). Empty = drone uses the player sprite as a
        # placeholder (rendered with frame 0). Picked from sprite combos.
        "sprite_type":             "",
        # How many options the player starts with at scene-enter (0-N).
        # The runtime spawn_option / despawn_option actions can change this
        # mid-scene.
        "start_count":              0,
        # Layout: "trail" (Gradius — single-file behind), "v" (V formation),
        # or "parallel" (both sides of player). v1 ships trail only; others
        # are forward-compat stubs.
        "formation":          "trail",
        # If True, drones are destroyed when hit by enemy bullets (count goes
        # down by 1). If False, drones are invincible (Gradius classic).
        "destructible":         False,
        # Bullet sprite used by options when firing. Empty = same as player.
        "bullet_sprite":           "",
    },
    "game_over_flow": {
        "enable_continue":          True,
        "continue_countdown_sec":      9,         # seconds for countdown (auto-→ NO at 0)
        "continue_max_uses":           3,         # how many continues granted per game
        "enable_final_screen":      True,
        "final_min_duration_sec":      3,
        "bg_scene_continue":          "",        # scene_id for BG (empty = current scene)
        "bg_scene_final":             "",
        "bg_scene_name_entry":        "",        # only used if highscore mechanic ON
        "bgm_continue":             0xFF,        # song id, 0xFF = no music change
        "bgm_final":                0xFF,
        "text_continue_prompt":  "CONTINUE?",
        "text_continue_yes":         "YES",
        "text_continue_no":           "NO",
        "text_final":          "GAME OVER",
        "text_name_entry":  "NEW HIGH SCORE!",
    },
}


def get_mechanic_config(project_data: dict | None, mech_id: str) -> dict:
    """Return the detailed config dict for a mechanic, merging stored values
    with defaults. Always returns a plain dict (never None)."""
    defaults = dict(MECHANICS_CONFIG_DEFAULTS.get(mech_id) or {})
    if not isinstance(project_data, dict):
        return defaults
    raw_root = project_data.get("mechanics_config")
    if not isinstance(raw_root, dict):
        return defaults
    raw = raw_root.get(mech_id)
    if not isinstance(raw, dict):
        return defaults
    out = dict(defaults)
    for k, v in raw.items():
        out[k] = v
    return out


def set_mechanic_config_field(project_data: dict, mech_id: str, key: str, value) -> None:
    """Mutate one field of a mechanic's detailed config. Creates the dict path."""
    if not isinstance(project_data, dict):
        return
    root = project_data.setdefault("mechanics_config", {})
    if not isinstance(root, dict):
        root = {}
        project_data["mechanics_config"] = root
    cfg = root.setdefault(mech_id, {})
    if not isinstance(cfg, dict):
        cfg = {}
        root[mech_id] = cfg
    cfg[key] = value


def find_mechanic(mech_id: str) -> dict | None:
    """Return the registry entry for a mechanic by id, or None if unknown."""
    for m in MECHANICS_REGISTRY:
        if m["id"] == mech_id:
            return m
    return None


# ---------------------------------------------------------------------------
# Backward-compat inference
# ---------------------------------------------------------------------------
#
# Rule: every mechanic that RETROFITS an existing feature (shooting, hp/damage,
# scoring, top-down vehicle, platformer physics, waves, procgen, etc.) defaults
# to ENABLED — so legacy projects without a "mechanics" key in their JSON keep
# their UI groups visible and codegen unchanged.
#
# Only mechanics implementing GENUINELY NEW features (`bounce`) may default to
# disabled — legacy projects don't have data for them so there's nothing to
# regress.
#
# infer_mechanics_from_project() goes one step further: it scans the project
# data and reports which mechanics have ACTIVE usage. Useful for a future
# "reset to detected state" button in the Mechanics tab. Currently unused but
# kept here as a documented safety net.

def infer_mechanics_from_project(project_data: dict | None) -> dict[str, bool]:
    """Scan project data and return True for any mechanic whose data is in
    use. A mechanic with no detected usage gets its registry default."""
    base = get_mechanics(project_data)
    if not isinstance(project_data, dict):
        return base
    scenes = project_data.get("scenes", []) or []

    # Walk every sprite-type across every scene, collecting usage flags.
    uses_shooting = False
    uses_combat_stats = False
    uses_scoring = False
    uses_topdown_vehicle = False
    uses_platformer_physics = False
    uses_bounce = False
    uses_waves = False
    uses_procgen = False
    uses_hit_feedback = False
    uses_death_fx = False
    uses_death_actions = False
    uses_sfx_fire = False

    for sc in scenes:
        if not isinstance(sc, dict):
            continue
        if sc.get("waves"):
            uses_waves = True
        if sc.get("procgen") or sc.get("dungeongen"):
            uses_procgen = True
        for spr in (sc.get("sprites") or []):
            if not isinstance(spr, dict):
                continue
            sh = spr.get("shooting") or {}
            if isinstance(sh, dict):
                if sh.get("can_shoot") or str(sh.get("button", "none") or "none") not in ("none", ""):
                    uses_shooting = True
                if sh.get("sfx_fire") not in (None, ""):
                    uses_sfx_fire = True
            if spr.get("bounce_flags"):
                uses_bounce = True
            if spr.get("hit_flash_frames"):
                uses_hit_feedback = True
            if spr.get("death_fx_sprite"):
                uses_death_fx = True
            events = (spr.get("events") or {}) if isinstance(spr.get("events"), dict) else {}
            if events.get("entity_death"):
                uses_death_actions = True
            props = spr.get("props") or {}
            if isinstance(props, dict):
                if int(props.get("hp", 1) or 1) != 1 or int(props.get("damage", 0) or 0) > 0:
                    uses_combat_stats = True
                if int(props.get("score", 0) or 0) > 0:
                    uses_scoring = True
                if int(props.get("jump_force", 0) or 0) > 0 or int(props.get("gravity", 0) or 0) > 0:
                    uses_platformer_physics = True
                td_move = str(props.get("td_move", "") or "").lower()
                if td_move == "vehicle" or int(props.get("td_speed_max", 0) or 0) > 0:
                    uses_topdown_vehicle = True

    # Also check entity_type archetypes for events.entity_death
    for t in (project_data.get("entity_types") or []):
        if not isinstance(t, dict):
            continue
        events = t.get("events") or {}
        if isinstance(events, dict) and events.get("entity_death"):
            uses_death_actions = True

    detected = {
        "shooting":           uses_shooting,
        "hit_feedback":       uses_hit_feedback,
        "death_fx":           uses_death_fx,
        "death_actions":      uses_death_actions,
        "sfx_fire":           uses_sfx_fire,
        "bounce":             uses_bounce,
        "combat_stats":       uses_combat_stats,
        "scoring":            uses_scoring,
        "topdown_vehicle":    uses_topdown_vehicle,
        "platformer_physics": uses_platformer_physics,
        "wave_spawning":      uses_waves,
        "procgen":            uses_procgen,
    }

    # OR: detected usage forces ON; otherwise keep the (already retroc-safe) base.
    out: dict[str, bool] = {}
    for m in MECHANICS_REGISTRY:
        mid = m["id"]
        out[mid] = bool(detected.get(mid, False)) or base.get(mid, m["default_enabled"])
    return out


def search_mechanics(query: str) -> list[dict]:
    """Filter the registry by a free-form query — matches against label,
    description, id, and keywords. Empty query returns the full list."""
    q = (query or "").strip().lower()
    if not q:
        return list(MECHANICS_REGISTRY)
    out: list[dict] = []
    for m in MECHANICS_REGISTRY:
        haystack = " ".join([
            m["id"],
            m["label"],
            m["description"],
            " ".join(m.get("keywords") or []),
        ]).lower()
        if q in haystack:
            out.append(m)
    return out
