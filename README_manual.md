# NgpCraft Engine

> **Last updated: 2026-03-30**

Visual asset pipeline and no-code game generator for **Neo Geo Pocket Color** homebrew.

Whether you're an experienced developer or have never written a line of C, NgpCraft Engine
removes the tedious half of NGPC development. For developers: collision grids export
directly to C arrays, RGB444 palette quantization and the 3-colors-per-tile hardware limit
are enforced live, VRAM tile/palette slots are tracked automatically, `NGP_FAR` is applied
on every ROM pointer, and the Makefile is patched with correct link order — none of that
boilerplate to write or debug by hand. For everyone else: place your entities, paint your
collision, wire your triggers visually, and get a buildable project with no C to write.

Import your PNGs, configure your game visually — get ready-to-compile C code for the
**NgpCraft_base_template** / **cc900** toolchain.

> Python 3.10+ · PyQt6 · Windows / Linux / macOS
> Entry point: `ngpcraft_engine.py`

---

## What it does

You design your game in the GUI. NgpCraft Engine generates everything:

| You provide | NgpCraft Engine generates |
|---|---|
| Sprite sheet PNGs | `*_mspr.c/h` — tiles, palettes, metasprite frames |
| Tilemap PNGs | `*_map.c/h` — scroll maps, collision grid |
| Frame slices + hitboxes | `*_hitbox.h`, `*_ctrl.h`, `*_props.h`, `*_anims.h`, `*_motion.h` |
| Entity placements + AI rules | Spawn tables, path tables, wave tables |
| Trigger rules (visual) | 68 conditions × 76 actions + OR-groups → `g_scene_trig_*[]` C arrays |
| Dialogue banks | Per-scene lines, choices, menus → `scene_*_dialogs.h` |
| Sound Creator manifest | `audio_autogen.mk`, `sound_data.c/h`, `Sfx_Play()` wrapper |
| Flash save intent | `NgpngSaveData` struct + append-only slot logic |
| — | `src/ngpng_autorun_main.c` — runnable preview, zero C to write |

One click: **Export (template-ready)** patches the Makefile and produces a buildable project.

---

## Features

**Asset pipeline**
- PNG → NGPC sprites and tilemaps with automatic VRAM slot tracking
- Per-tile collision (18 types: SOLID, ONE_WAY, LADDER, STAIR, WATER, SPRING, ICE, CONVEYOR…)
- Tile budget checker — warns at >256 tiles, errors at >384
- Tilemap compression (LZ77 / RLE)
- Multi-chunk large map assembly (streaming-ready)

**Visual level editor**
- Entity placement with per-instance role, AI behavior, physics props
- AI parameters per entity: speed, aggro/lose range, direction-change cadence
- Wave spawner editor (shmup-style or timed — delay-sorted, gap-checked)
- Regions (camera lock, no-spawn, audio zones, push-block targets, race gates, card slots…)
- Waypoint paths for patrol AI and moving platforms
- Camera deadzone overlay, parallax config, forced-scroll presets
- Neighbouring scenes → auto edge-warp triggers
- Genre-aware UI: trigger conditions/actions/presets reordered for the active profile

**Trigger system (visual scripting)**
- 68 conditions: button press, `on_jump/land/hurt/death`, player in region, enemy count, HP, timer, flags, variables, wave state, quest stage, collectibles, distance, `chance`, push-block-on-tile, all-switches-on, `dialogue_done`, `choice_result`…
- 76 actions: BGM/SFX, spawn entity/wave, scene transition, show/hide/teleport entity, set flag/variable, give item, toggle tile, flash screen, camera lock, fade, save game, `start_dialogue`, `show_menu`…
- **Move entity to exact tile** — "Place ↗" button: click any tile on the canvas to set the destination for `move_entity_to`, `teleport_player`, or `spawn_at_region`. No manual region required; a synthetic 1×1 destination region is generated at export. A dashed arrow shows the path from entity spawn to destination.
- Multi-condition AND chains + OR groups (multiple trigger sets, any can fire)
- Exported as plain C89 arrays — zero runtime overhead for unused features

**Hitbox & controller editor**
- Per-frame AABB hurtboxes and multi-box attack windows
- Animation state filter on attack boxes: restrict each box to specific animation states (e.g., only active during `attack`, `special`) — inactive boxes are skipped at zero cost
- One-click export: `_ctrl.h` with `INIT`/`UPDATE` macros wrapping the `ngpc_actor` module
- Motion pattern editor (fighting-game style): QCF, DP, double-tap, etc. → `_motion.h` with `NGP_FAR` step arrays and pattern table ready to link with `ngpc_motion`

**Dialogue system**
- Named dialogue banks per scene: ordered lines with speaker, text, and portrait
- Choices (up to 2 per line) with branching to any dialogue entry — uses `ngpc_dialog` runtime
- Menus (2–8 items) with per-item goto target — uses `ngpc_menu` runtime
- NGPC live preview at 3× scale with real sprite tiles and palette colors
- Text palette: 3 editable RGB444 color slots
- Custom dialog box background sprite (16×16 — 4 tiles 8×8)
- CSV import/export for spreadsheet-based content authoring
- Export: `scene_*_dialogs.h` — plain C arrays, included in the scene loader

**Audio (NGPC Sound Creator integration)**
- Link a `project_audio_manifest.txt` — BGM assigned per scene
- SFX mapping editor: gameplay ID → Sound Creator index
- SFX-only projects supported (no BGM required)
- Auto-generates `sound_data.c/h` and `sounds_game_sfx.c`

**Export & build**
- Single-scene, all-scenes, or template-ready (Makefile patch + autorun)
- Headless / CI mode: `python ngpcraft_engine.py --export project.ngpcraft`
- VRAM conflict checker across the whole project
- Validation center with per-scene status badges and corrective actions

**Supported genres** (genre presets configure scroll, physics, tile roles, and trigger priority)

`Horizontal shmup` · `Vertical shmup` · `Platformer` · `Run'n'gun` · `Top-down` ·
`Puzzle` · `RPG / Adventure` · `Fighting` · `Brawler` · `Racing` · `TCG / Card game` ·
`Rhythm` · `Roguelike` · `Visual novel` · `Menu` · `Single-screen`

Each genre profile pre-configures map mode, scroll axes, loop settings, tile roles, and
reorders the trigger condition/action/preset combos to surface the most relevant options first.

---

## Requirements

| | |
|---|---|
| Python | 3.10+ |
| PyQt6 | ≥ 6.4.0 |
| Pillow | ≥ 9.0.0 |
| Toolchain | NGPCraft cc900 + NgpCraft_base_template |

```
pip install -r requirements.txt
python ngpcraft_engine.py
```

---

## Quick start

1. `File > New Project` — choose **Shmup example** or **Platformer example**
2. Hitbox tab — slice frames, set `ctrl.role = player`
3. Tilemap tab — load PNG, paint collision
4. Level tab — place entities, configure waves and triggers
5. Dialogues tab *(RPG/Adventure)* — create dialogue banks, assign portraits, pick text palette
6. Project tab → **Export (template-ready)**
7. `make` from the template root

A playable preview runs in emulator or on flash cart with no additional C.

> **Auto-save** — every action (adding a sprite, editing a scene, moving an entity…) is
> saved to the `.ngpcraft` file immediately. There is no "Save" button to remember.
> A **✓ Saved** indicator flashes briefly in the status bar after each write.

---

## Documentation

- [User Manual](#table-of-contents) — full tab reference, export pipeline, audio integration (below)
- [API Reference](API_REFERENCE.md) — Python core module API
- [Sound Integration Quickstart](templates/NgpCraft_base_template/docs/SOUND_INTEGRATION_QUICKSTART.md)
- [Flash Save Guide](templates/NgpCraft_base_template/docs/NGPC_FLASH_SAVE_GUIDE.md)

---

## Related

- **NgpCraft_base_template** — C template + optional modules (physics, animation, camera, FSM…)
- **NGPC Sound Creator** — T6W28 PSG tracker (BGM + SFX authoring)
- **NGPCraft toolchain** — open-source cc900 assembler/compiler for TLCS-900

---

## Updating the embedded template

NgpCraft Engine ships with a copy of
[NgpCraft_base_template](https://github.com/Tixul/NgpCraft_base_template) inside
`templates/NgpCraft_base_template/`. This copy is what gets scaffolded into every new project.

### From the UI (end users)

Open the **Help** tab and click **↓ Update Template** at the bottom-left of the window.
The tool downloads the latest version directly from GitHub (no git required) and syncs the
embedded copy. A summary dialog shows what changed.

> **Packaging note** — the tool must be installed to a user-writable location.
> On Windows, prefer `%LOCALAPPDATA%\NgpCraft\` over `C:\Program Files\NgpCraft\`
> so the update can write to the `templates/` folder without requiring admin rights.

### From the command line (developers)

```bash
# Sync from GitHub (default — no git required)
python sync_template.py

# Dry-run: show what would change without modifying anything
python sync_template.py --dry-run

# Use the local sibling NgpCraft_base_template/ instead of GitHub
python sync_template.py --local

# Verbose: also list unchanged files
python sync_template.py --verbose
```

---

# User Manual

---

## Table of Contents

1. [Requirements & Installation](#1-requirements--installation)
2. [Quick Start](#2-quick-start)
3. [Project & Scene Concepts](#3-project--scene-concepts)
4. [Tab Reference](#4-tab-reference)
   - 4.1 [Project Tab](#41-project-tab)
   - 4.2 [Palette Tab](#42-palette-tab)
   - 4.3 [Editor Tab](#43-editor-tab)
   - 4.4 [Hitbox Tab](#44-hitbox-tab)
   - 4.5 [Tilemap Tab](#45-tilemap-tab)
   - 4.6 [Level Tab](#46-level-tab)
   - 4.7 [VRAM Tab](#47-vram-tab)
   - 4.8 [Bundle Tab](#48-bundle-tab)
   - 4.9 [Dialogues Tab](#49-dialogues-tab)
   - 4.10 [Help Tab](#410-help-tab)
5. [Export Pipeline](#5-export-pipeline)
   - 5.1 [Export Modes](#51-export-modes)
   - 5.2 [Generated Files](#52-generated-files)
   - 5.3 [Headless / CI Mode](#53-headless--ci-mode)
6. [Template Integration](#6-template-integration)
   - 6.1 [Makefile](#61-makefile)
   - 6.2 [Using a Scene in C](#62-using-a-scene-in-c)
   - 6.3 [Scenes Manifest](#63-scenes-manifest)
7. [Audio Integration](#7-audio-integration)
8. [NGPC Hardware Constraints](#8-ngpc-hardware-constraints)
9. [Runtime C Modules](#9-runtime-c-modules)
10. [Validation & QA](#10-validation--qa)
11. [Command-Line Reference](#11-command-line-reference)
12. [Extending the Tool](#12-extending-the-tool)

---

## 1. Requirements & Installation

**Prerequisites:**

| Requirement | Version |
|---|---|
| Python | 3.10+ recommended |
| PyQt6 | ≥ 6.4.0 |
| Pillow | ≥ 9.0.0 |

**Install dependencies:**

```
pip install -r requirements.txt
```

**External tools (required for sprite/tilemap export):**

- `ngpc_sprite_export.py` — sprite-to-C exporter (part of the NGPCraft toolchain)
- `ngpc_tilemap.py` — tilemap-to-C exporter

These are discovered automatically from the template `tools/` folder. You can also point to them manually via `--sprite-tool` / `--tilemap-tool` flags or the Tool Finder dialog in the GUI.

---

## 2. Quick Start

**Launch the GUI:**

```
python ngpcraft_engine.py
python ngpcraft_engine.py path/to/project.ngpcraft
```

**Recommended first-time workflow:**

1. `File > New Project` — enter project name, ROM name, select your `NgpCraft_base_template` folder, pick a starter template:
   - **Blank** — empty scene, you build everything from scratch
   - **Shmup example** — pre-filled horizontal shmup scene with sample assets
   - **Platformer example** — pre-filled platformer scene with sample assets
2. In **Project tab**: add sprites and tilemaps to your first scene. Set `export_dir` to `GraphX/gen`.
3. In **Hitbox tab**: slice your sprite frames, assign a `ctrl.role` (at minimum `player`).
4. In **Tilemap tab**: load the tilemap PNG, paint collision.
5. In **Level tab**: place the player entity, set the scene profile (e.g., `platformer`).
6. In **Dialogues tab** *(RPG/Adventure only)*: create dialogue banks, assign portraits, configure text palette.
7. In **Project tab**: click **Export (template-ready)** — this patches the template Makefile and generates `src/ngpng_autorun_main.c` for an immediate preview.
8. Build with `make` from the template root.

---

## 3. Project & Scene Concepts

### Project file (`.ngpcraft`)

A `.ngpcraft` file is a JSON document that contains:

- **Project metadata**: name, ROM name, `graphx_dir`, `export_dir`
- **Bundle**: ordered list of sprite export entries (tile/palette base tracking)
- **Scenes**: array of scene definitions
- **Game config**: start scene, audio manifest link, SFX mapping

### Scene

A scene is the fundamental unit of organization. Everything visible on screen at the same time belongs to one scene:

| Component | Description |
|---|---|
| `sprites[]` | Sprite sheets with frame dimensions, RGB444 palette, hitboxes, ctrl metadata, animations |
| `tilemaps[]` | Background planes (SCR1/SCR2), collision data |
| `entities[]` | Placed entity instances (player, enemies, items, platforms, blocks…) |
| `waves[]` | Spawn wave definitions (shmup-style or timed spawns) |
| `regions[]` | Named zones (camera lock, no-spawn, audio zones…) |
| `triggers[]` | Condition→action rules exported to C |
| `paths[]` | Waypoint routes for entity patrol / moving platforms |
| `col_map` | Scene-level collision grid (can override or supplement tilemap collision) |
| `neighbors` | Adjacent scene IDs per direction (west/east/north/south) — auto-generates edge warp triggers |
| `bg_chunk_map` | Multi-chunk assembled large map (`grid`: list of lists of tilemap PNGs) |
| Layout | Camera start, scroll axes, loop X/Y, parallax, forced scroll |

### NGPC screen facts

- Screen: **20 × 19 tiles** (160 × 152 px)
- Background tilemap hardware max: **32 × 32 tiles** (256 × 256 px)
- Tile size: 8 × 8 px
- Colors per palette: 4 (index 0 = transparent on scroll planes)
- Sprite palettes: 16 banks × 4 colors; BG palettes: 16 banks × 4 colors

---

## 4. Tab Reference

### 4.1 Project Tab

The central hub for project and scene management.

**Scene list:**
- Each scene shows a status badge: `OK` / `!` (warning) / `KO` (error)
- Tooltip on the badge lists specific issues (missing assets, no player, invalid col_map, missing export_dir…)
- Scenes can be reordered by drag & drop to set the `scenes_autogen` order
- The start scene is selected here (stored in `game.start_scene`)

**Quick actions row:**
Opens the current scene directly in Palette, Tilemap, Level, or Hitbox tab, or opens the export folder.

**Guided workflows row:**
One-click starters for Assets, Test platformer, Test shmup, and Prepare export — opens the correct tab with a short reminder of the required steps.

**Scene presets:**
Apply a reusable starter configuration (platformer, vertical shmup, top-down room, single-screen menu) to the current scene without modifying already-assigned sprites/tilemaps.

**Validation center (`Details` button):**
Lists all project / scene / level / export issues with direct navigation to the problematic scene. Includes a static export pipeline pass (filename collision detection for `scene_*`, `*_mspr.c`, `*_map.c`; suspicious export_dir; missing/stale autogens) and a template contract check (`makefile`, `src/main.c`, `tools/`, `ngpc_metasprite.h`, `NGP_FAR`).

**Audio (per scene):**
Link a Sound Creator `project_audio_manifest.txt` and assign a BGM to each scene.

**SFX mapping:**
Map gameplay SFX IDs to Sound Creator indices. When defined, export generates `ngpc_project_sfx_map.h` and `sounds_game_sfx_autogen.c`.

**Navigator panel:**
Persistent side panel listing scenes, sprites, tilemaps, entities, waves, regions, triggers, and paths. Click to select; double-click to open the relevant tab. Includes an Inspector block with a compact summary and quick actions for the selected object.

**Export buttons:**

| Button | Effect |
|---|---|
| **Scene → .c** | Export current scene only |
| **All scenes → .c** | Batch export all scenes |
| **Export (template-ready)** | All scenes + Makefile patch + autorun `main.c` |

---

### 4.2 Palette Tab

View and edit the RGB444 palette for the selected sprite.

- Preview with checkerboard background (transparent = index 0)
- Animation preview
- Layer split suggestions (when >3 colors detected)
- Shared palette editing (force a fixed palette across multiple sprites)
- Header layout: `File` and `View` blocks (consistent with Tilemap tab)

**NGPC color constraint:** Each palette has 4 colors. Color 0 is always transparent on scroll planes. RGB values are quantized to 4 bits per channel (nibble-snapped).

---

### 4.3 Editor Tab

Pixel-level editing for sprites and tiles, respecting NGPC RGB444 quantization constraints.

---

### 4.4 Hitbox Tab

Define per-sprite collision geometry and runtime metadata.

**Hurtbox sub-tab:**
- Draw the hurtbox rectangle on each animation frame
- Can be disabled per sprite (disabling hurtbox also disables gameplay body collision in the current runtime)

**Offensive hitbox sub-tab:**
- Multiple attack boxes per sprite (`Box atk n / total` navigation, add/remove from UI)
- Per-box fields:
  - `x`, `y`, `w`, `h`
  - `Dmg atk` — damage override (`0` = fall back to `props.damage`)
  - `KB x / KB y` — signed knockback applied to the hit target
  - `Prio` — priority (useful for overlap resolution in brawlers)
  - `Start / Len` — active frame window (`Len = 0` = always active)
  - `Anim filter` — restrict the box to specific named animation states (e.g., `attack`, `special`). Box is inactive in all other states — zero overhead for unused boxes.
- Can be disabled per sprite

**Ctrl metadata:**
- `ctrl.role` — `player`, `enemy`, `npc`, `item`, `trigger`, `platform`, `block`, `prop`
  - Setting `player` generates a `_ctrl.h` that wraps the `ngpc_actor` optional module. Minimal usage:
    ```c
    NgpcActor hero;
    MYSPRITE_CTRL_INIT(hero, start_x, start_y);  /* once */
    MYSPRITE_CTRL_UPDATE(hero);                   /* each frame */
    ```
  - `enemy` / `npc` are currently mostly tags; gameplay role is set in Level tab
  - `trigger` marks a sprite as a spatial trigger source (no physics, no render)
- `type_id` — free integer tag, distinct from role
- `Flip dir` — auto-apply horizontal flip based on last X direction for players/enemies

**Entity props** (physics / combat values exported to `*_props.h`):

| Field | Comment |
|---|---|
| `max_speed` | Max speed (game units/tick) |
| `accel` | Ticks to reach max_speed (0 = instant) |
| `decel` | Deceleration on release (0 = instant) |
| `weight` | Mass: 0 = light, 255 = heavy |
| `friction` | Grip: 0 = ice, 255 = full |
| `jump_force` | Initial jump velocity; 0 = no jump |
| `gravity` | Gravity force (0 = none — shmup / top-down) |
| `max_fall_speed` | Terminal fall velocity |
| `move_type` | 0 = 4-dir, 1 = 8-dir, 2 = side+jump, 3 = forced scroll |
| `axis_x / axis_y` | 0 = locked, 1 = can move on axis |
| `can_jump` | 0 = no jump, 1 = jump allowed |
| `gravity_dir` | 0 = down, 1 = up, 2 = none |
| `td_control` | Top-down orientation: 0 = absolute (D-pad → facing), 1 = relative (L/R rotate) |
| `td_move` | Top-down movement: 0 = direct (no inertia), 1 = advance (fwd/back), 2 = vehicle (A=accel, B=brake) |
| `td_speed_max` | Vehicle max speed ×16 (default 48 ≈ 3 px/frame) |
| `td_accel` | Vehicle acceleration per frame ×16 (default 4) |
| `td_brake` | Active braking per frame ×16 (default 6) |
| `td_friction` | Passive friction per frame ×16 (default 2) |
| `hp` | Hit points (0 = invincible) |
| `damage` | Damage on contact |
| `inv_frames` | Invincibility frames after hit |
| `score` | Score value × 10 on defeat (0–2550 pts) |
| `anim_spd` | Ticks per anim frame (1–60; 0 = static) |
| `type_id` | Entity type tag (game-defined) |

**Readiness checklist (visible in tab):**
Sprite loaded, frame slicing done, hurtbox coverage, ctrl role set, animation states defined, project saved, genre compatibility.

**Animation states:**
Define named animation states (idle, run, attack, hurt…) with frame ranges. Each state has:
- **Mode**: `loop`, `pingpong`, or `oneshot` → generates `ANIM_LOOP` / `ANIM_PINGPONG` / `ANIM_ONESHOT` constants
- **Speed**: ticks per frame, clamped 1–255 (default 6)

Exported to `*_namedanims.h` (for use with the `ngpc_anim` optional module). Referenced by triggers and the autorun runtime.

**Motion Patterns (ngpc_motion):**

Define fighting-game-style input sequences (quarter-circle, double-tap, etc.) that are detected at runtime via a 32-frame circular input buffer.

Each pattern has:
- **Name** — free-form identifier (e.g. `QCF_A`, `DASH_R`)
- **Steps** — direction + optional button per step, oldest to newest
- **Window** — total frames in which all steps must occur (0 = use default 32)
- **Anim** *(optional)* — animation state to trigger on match (for dispatch table)

Step notation:

| Symbol | Meaning |
|---|---|
| `N` | Neutral (no direction) |
| `U D L R` | D-pad cardinal |
| `UR UL DR DL` | Diagonal |
| `*` | Wildcard (any direction) |
| `+A +B +OPT` | Button pressed this step |

Examples: `D DR R+A` (quarter-circle + A), `R R+B` (double-tap + B), `D U+A` (charge up).

Export (`_motion.h`) generates:
- `static const u8 NGP_FAR _<name>_<pat>_s[]` — step array in ROM
- `static const NgpcMotionPattern NGP_FAR g_<name>_patterns[]` — pattern table
- `#define <NAME>_PAT_COUNT N`
- Optional dispatch table `g_<name>_pat_anim[]` (when any pattern has an Anim assigned)

Usage with the `ngpc_motion` optional module (34 bytes RAM per entity):
```c
#include "ngpc_motion/ngpc_motion.h"
#include "hero_motion.h"

NgpcMotionBuf buf;
ngpc_motion_init(&buf);

/* Each frame: */
ngpc_motion_push(&buf, ngpc_pad_held, ngpc_pad_pressed);
switch (ngpc_motion_scan(&buf, g_hero_patterns, HERO_PAT_COUNT)) {
    case 0: fire_hadouken(); ngpc_motion_clear(&buf); break;
    case 1: fire_shoryuken(); ngpc_motion_clear(&buf); break;
}
```

> **Hitbox coordinate space:** Hurtbox and attack box coordinates use sprite-local offsets from the sprite centre (`s8`, range −128..+127). This is distinct from world-space collision (`s16 x, y` in `ngpc_aabb.h`). Keep this in mind when reading or writing hitbox values manually.

---

### 4.5 Tilemap Tab

Load, view, and configure a background tilemap.

**Header:** `File` | `View` | `Edit` | `Layers / export` blocks.

**Compact scene picker:** Select which tilemap in the scene you are currently editing.

**Tileset panel (resizable right panel):**
- Multi-select tiles to populate the Stamp buffer
- `Variation` brush: randomizes tile selection within a multi-tile selection

**Editing tools:**

| Tool | Shortcut | Description |
|---|---|---|
| Paint | configurable | Place the selected tile/stamp |
| Erase | configurable | Clear to transparent |
| Stamp | configurable | Paste the current buffer |
| Line | Shift+click | Draw a line of tiles |
| Rect | — | Rectangle fill |
| Ellipse | — | Ellipse fill |
| Eyedropper | configurable | Pick tile under cursor |

Stamp presets: save and recall frequently used tile patterns.

**Collision modes:**

| Mode | Description |
|---|---|
| `tileset` | Collision type assigned per tile in the tileset (applied everywhere that tile appears) |
| `collision_paint` | Collision painted directly cell-by-cell on the map |

**Collision types (18):**

| Type | ID | Parameters (Level → Rules) |
|---|---|---|
| `PASS` | 0 | — passable |
| `SOLID` | 1 | — blocks all sides |
| `ONE_WAY` | 2 | — solid from above only |
| `DAMAGE` | 3 | `hazard_damage` (damage), `hazard_invul` (invincibility frames) |
| `LADDER` | 4 | `ladder_top_solid`, `ladder_top_exit`, `ladder_side_move` |
| `WALL_N/S/E/W` | 5–8 | — blocks entry from one side (top-down) |
| `WATER` | 9 | `water_drag` (1–8 slowdown), `water_damage` (0–255 damage/frame) |
| `FIRE` | 10 | `fire_damage` (damage/frame) |
| `VOID` | 11 | `void_damage` (damage), `void_instant` (instant death) |
| `DOOR` | 12 | — door marker |
| `STAIR_E / STAIR_W` | 13–14 | — non-blocking slopes |
| `SPRING` | 15 | `spring_force` (0–127), `spring_dir` (up/down/left/right) |
| `ICE` | 16 | `ice_friction` (0=perfect ice, 255=normal ground) |
| `CONVEYOR_L / CONVEYOR_R` | 17–18 | `conveyor_speed` (1–8 px/frame) |

All these parameters are global per scene — configured in **Level tab → Rules tab**, exported as `#define SCENE_RULE_*` in the scene header.

Genre collision presets populate a sensible default set in one click.

**Pre-flight color check (template contract):**
Before exporting, NgpCraft Engine validates each enabled sprite and tilemap:
- Max **3 visible colors per 8×8 tile** (NGPC palette limit — 4 slots, index 0 = transparent)
- Tilemap planes allow up to 6 visible colors total via SCR1 + SCR2 layer compositing (3 per plane)
- Image width and height must be a multiple of 8 and align to the declared frame size
- Tilemap: max 32×32 tiles

These checks run **before** exporters are invoked, so issues surface early with clear messages.

**Readiness checklist:** Source PNG loaded, dimensions valid for NGPC, color/plane check, collision defined, C/H export done.

---

### 4.6 Level Tab

Entity placement, wave configuration, layout, and scene diagnostics.

**Top bar:** `View` and `Scene editing` blocks — zoom and undo are clearly separated from placement tools.

**Tools bar (explicit mode switching):**

| Key | Mode |
|---|---|
| S | Select |
| E | Entity |
| W | Wave |
| R | Region |
| P | Path |
| C | Camera |
| Esc | → Select |
| Ctrl+D | Duplicate selection |
| Arrow keys | Nudge (Shift = faster) |
| Ctrl+wheel | Zoom canvas |
| Ctrl+click+drag | Move camera rectangle |

**Overlays toggle:** Collision, Regions, Triggers, Paths, Waves, Camera, NGPC bezel.

**Entity palette (left panel):**
- Starter row per type: drop preconfigured variants (player ground spawn, enemy patrol, breakable block, collectible ×10, moving platform with auto-created path).

**Entity roles (runtime):**

`player`, `enemy`, `npc`, `item`, `platform`, `block`, `prop`, `trigger`

- `platform` + `Path` = moving platform
- `block` subtypes: bump, breakable, item-block
- `item` subtypes: collectibles, pickups

**Per-instance options:**
- `Direction` — initial facing direction (right / left / up / down)
- `Behavior` — AI mode for enemies: `patrol` (turn at walls/edges), `chase` (follow player), `fixed` (stationary), `random` (wander)
- `Block in map` — prevent the entity from exiting the exported world bounds
- **AI Parameters panel** (enemies only, contextual):
  - `Speed` — movement speed in px/frame (1–255). Shown for patrol / chase / random.
  - `Aggro range` — player detection radius in ×8 px. Shown for chase.
  - `Lose range` — abandon-chase radius in ×8 px. Shown for chase.
  - `Dir. change` — frames between random direction flips. Shown for random.
  - Only non-default values are exported (zero overhead for defaults).

**Waves:**
- Spawn wave definitions (entry direction, delay, count, spacing)
- Presets for common formations
- Splitter panel (sizes memorized)

**Regions:**
Named zones exported to C. Built-in region types:

| Kind | Export | Used for |
|---|---|---|
| `zone` | generic | trigger area, destination target |
| `spawn` | `g_{sym}_spawn_points[]` | player / entity respawn |
| `camera_lock` | flag | lock camera to room |
| `no_spawn` | flag | wave suppression area |
| `checkpoint` | flag | platformer / adventure checkpoint |
| `exit_goal` | flag | level-end portal |
| `attractor` / `repulsor` | `zone_force` | physics push/pull zone |
| `danger_zone` | flag | instant-kill area |
| `push_block` | `g_{sym}_push_block_tiles[]` | Sokoban-style block target |
| `lap_gate` | `g_{sym}_region_gate_index[]` | race checkpoint / finish line |
| `race_waypoint` | `g_{sym}_waypoints[]` | AI driver steering waypoints |
| `card_slot` | `g_{sym}_region_slot_type[]` | TCG card placement slot |

Triggers can be generated directly from a selected region (`enter_region` / `leave_region` quick actions).

**Triggers:**
Condition → action rules. Exported as C arrays (`g_scene_trig_conds[]`, etc.).

68 conditions include: `btn_a/b/option`, `enter_region`, `on_jump/land/hurt/death/crouch`, `player_has_item`, `npc_talked_to`, `flag_set/clear`, `variable_ge/eq/ne/le`, `enemy_count_ge`, `health_eq`, `score_ge`, `timer_le/every`, `scene_first_enter`, `on_swim/dash/attack/pickup`, `entity_in_region`, `quest_stage_eq`, `ability_unlocked`, `resource_ge`, `combo_ge`, `lap_ge`, `btn_held_ge`, `chance`, `block_on_tile`, `all_switches_on`, `count_eq`, `dialogue_done`, `choice_result`…

78 actions include: `play_bgm/sfx`, `start/stop/fade_bgm`, `spawn_entity/wave`, `goto_scene`, `warp_to`, `show_entity`, `hide_entity`, `move_entity_to`, `teleport_player`, `spawn_at_region`, `set_flag/clear_flag/toggle_flag`, `set_variable/inc_variable/dec_variable`, `give_item/remove_item`, `unlock_door`, `set_quest_stage`, `toggle_tile`, `reset_scene`, `flash_screen`, `screen_shake`, `fade_out/in`, `camera_lock/unlock`, `add_combo/reset_combo`, `add_health/set_health`, `add_lives/set_lives`, `set_score/add_score`, `set_timer/pause_timer/resume_timer`, `save_game`, `set_bgm_volume`, `flip_sprite_h`, `flip_sprite_v`, `lock_player_input`, `unlock_player_input`, `enable_trigger/disable_trigger`, `pause_entity_path/resume_entity_path`, `set_checkpoint`, `respawn_player`, `start_dialogue`, `show_menu`…

**Move entity to exact tile (Place ↗):** When the action is `move_entity_to`, `teleport_player`, or `spawn_at_region`, a **Place ↗** button appears. Click it, then click any tile on the canvas to set the exact destination — no manual region needed. The canvas draws a dashed arrow from the entity's spawn position to the destination, and a crosshair marks the target tile. Each additional destination (C, D…) is a separate trigger with a different condition.

Extra-condition AND chains: add conditions to any trigger that must *all* be true. OR groups: add alternative AND-chains — any group firing is sufficient.

Preset workflows (genre-aware): cursor show/hide, menu confirm, hover SFX, player shot, checkpoint, exit goal, puzzle door toggle, all switches done, block on target, lap gate crossed, countdown start, TCG draw phase, card-to-slot…

**Genre-aware ordering:** when a scene profile is set, the condition/action/preset/region-kind combos reorder to surface the most relevant choices first. Conditions irrelevant to the active genre are still accessible but appear after the genre-specific ones.

**Paths:**
Waypoint routes (tile coordinates) exported to C — used for patrol AI and moving platforms.
Assign a path to an entity via the **Path** combo in instance props. The export writes the path index into `g_{sym}_ent_paths[]` (255 = none).

**Layout:**
Camera start (Cam X/Y), scroll axes (free/fixed), loop X/Y, forced scroll speed/direction.

Layout presets: single-screen menu, platformer follow, platformer room lock, run'n gun horizontal, vertical shmup, top-down room.

**Planes / parallax:**
Document SCR1/SCR2 parallax X/Y (as %) and BG_FRONT layering.

**Profile (genre preset):**
Quickly configures map mode + scroll/loop for the chosen genre and reorders all trigger/region combos to surface genre-relevant options first. Profile-guided diagnostics warn when configuration drifts (e.g., shmup without forced scroll, fighting game without Lock Y).

Available profiles: `shmup_h`, `shmup_v`, `platformer`, `run_gun`, `topdown`, `puzzle`, `rpg`, `fighting`, `brawler`, `racing`, `tcg`, `rhythm`, `roguelike`, `visual_novel`, `menu`, `single_screen`.

The **`menu`** profile is designed for sprite-based menu screens (cursor entity, flag-driven selection):
- Map mode `none`, no scroll, 20×19 tiles
- Surfaces `btn_a/b/up/down`, `flag_set/clear`, `scene_first_enter` conditions first
- Surfaces `show_entity`, `hide_entity`, `move_entity_to`, `set_flag`, `clear_flag`, `goto_scene` actions first
- Starter triggers injected when adding a new menu scene (nav up/down, confirm item 1/2, entry SFX)

**Procgen:**
Generate tile maps (SCR1/SCR2 PNGs) from the collision grid. Generated tilemaps are added to `tilemaps[]` and can be selected as BG source tiles.

**Collision import:**
Import `col_map` from the scene's BG tilemap (`auto` / `SCR1` / `SCR2`). Typical workflow: paint tilemap collision → import to col_map → add local Level overrides.

**Rules (Physics/Rules tab):**

Global per-scene parameters for physics collision types. Exported as `#define SCENE_RULE_*` in `scene_*_level.h`.

| Group | Parameter | Range | Description |
|---|---|---|---|
| Damage | `hazard_damage` | 0–255 | HP removed on contact with DAMAGE tile |
| Damage | `fire_damage` | 0–255 | HP removed per frame on FIRE tile |
| Damage | `hazard_invul` | 0–255 | Invincibility frames after a hit |
| Void | `void_damage` | 0–255 | HP removed if `void_instant = off` |
| Void | `void_instant` | on/off | Instant death on VOID tile |
| Spring | `spring_force` | 0–127 | Spring launch force |
| Spring | `spring_dir` | up/down/left/right | Spring launch direction |
| Conveyor | `conveyor_speed` | 1–8 | Conveyor belt speed (px/frame) |
| Ice | `ice_friction` | 0–255 | 0 = perfect ice, 255 = normal ground |
| Water | `water_drag` | 1–8 | Slowdown factor in water |
| Water | `water_damage` | 0–255 | Damage/frame in water (0 = safe water) |
| Ladder | `ladder_top_solid` | on/off | Solid ladder top (blocks downward exit) |
| Ladder | `ladder_top_exit` | on/off | Allow exiting from the top |
| Ladder | `ladder_side_move` | on/off | Horizontal movement while on ladder |
| Zones | `zone_force` | 1–8 | Force of ATTRACTOR/REPULSOR regions (px/frame) |

**HUD (Rules sub-tab):**

Configure HUD widgets when `hud_font_mode = custom`:
- `icon` and `value` widgets with screen position
- Sprite digit font (0–9 tile mapping)
- Falls back to system text automatically if font is incomplete
- `hud_show_score`, `hud_show_collect`, `hud_show_timer`, `hud_show_lives`, `hud_pos`
- `goal_collectibles`, `time_limit_sec`, `start_lives`, `start_continues`

**Neighbouring scenes (Track B — edge warps):**

Declare up to 4 adjacent scenes (North / South / West / East) in the Layout tab. The exporter auto-generates:
- An 8-px exit trigger region on each declared edge
- A fixed-slot entry spawn in the target scene (West=slot 0, East=1, North=2, South=3)
- A `warp_to` trigger pointing to the opposite entry slot

Manual spawns in the target scene start at index 4. No runtime module changes required.

**Chunk Map SCR1 (Track A — assembled large map):**

Assemble multiple tilemap PNG chunks into one flat `g_{name}_bg_map[]` ROM array. Configure in the BG tab:
- Set Rows × Cols grid (up to 8×8)
- Select the tilemap PNG per cell (from the scene's Tilemaps list)
- Constraint: all chunks in the same column must share the same tile height
- Export generates `SCENE_X_CHUNK_MAP_W/H` macros and forces `scr1_by_mapstream`

**Diagnostics:**
- Profile-guided hints
- Mini checklist: blockers, camera, references, export symbol, Procgen PNG mapping

---

### 4.7 VRAM Tab

Visualize tile and palette occupancy across the project.

- Tile slot usage per scene (slots 0–31 reserved, 32–127 system font, 128+ free)
- Palette bank conflicts
- Suggested fixes for detected conflicts

---

### 4.8 Bundle Tab

Inspect and reorder the sprite export bundle entries. The bundle tracks `tile_base` and `pal_base` offsets for each exported sprite, ensuring no VRAM overlap. Link order matters (sprites before maps prevents near-pointer overflow).

---

### 4.9 Dialogues Tab

Author dialogue content per scene without writing any C. Output: `scene_*_dialogs.h`, included automatically in the scene loader.

**Bank list:**
- Create one or more named dialogue banks per scene (e.g., `intro`, `npc_shopkeeper`, `boss_taunt`)
- Each bank has an ordered list of dialogue entries
- Banks are triggered from the Level tab via `start_dialogue` action or from C via `ngpc_dialog_start()`

**Dialogue entry:**
Each entry defines one exchange:
| Field | Description |
|---|---|
| `Speaker` | Character name shown above the text box (free-form string) |
| `Portrait` | Sprite tile used as portrait in the dialog box |
| `Text` | Content of the dialogue line |
| `Choice A / Choice B` | Optional choices (up to 2); each points to a goto entry index |
| `Next` | Entry index to jump to after this line (`-1` = end bank) |

**Menus:**
A bank entry can be a **Menu** (2–8 items) instead of a dialogue line. Each item has a label and a goto index. Used for item shops, yes/no prompts, multi-option dialogues. Rendered via `ngpc_menu` runtime.

**Preview:**
Live NGPC preview at 3× scale showing the actual dialog box with real sprite tiles and text palette colors.

**Text palette:**
3 editable RGB444 color slots for the text box. Exported as a `u16[3]` array in `scene_*_dialogs.h`.

**Dialog box background:**
A custom 16×16 sprite (4 tiles of 8×8) used as the dialog box frame. Linked from the scene's sprite list.

**CSV import/export:**
- **Export CSV**: dumps the entire dialogue bank to a spreadsheet-friendly format (speaker, text, choices…)
- **Import CSV**: replaces the bank content from a CSV — ideal for content authoring outside the tool

**Generated header (`scene_<name>_dialogs.h`):**
```c
/* Text palette */
static const u16 NGP_FAR g_myScene_dlg_pal[3] = { 0x0FFF, 0x0000, 0x0AAA };

/* Bank: intro */
static const NgpcDlgEntry NGP_FAR g_myScene_dlg_intro[] = {
    { "Hero",  PORTRAIT_HERO,  "Let's go!", DLG_NO_CHOICE, DLG_NO_CHOICE, 1 },
    { "Elder", PORTRAIT_ELDER, "Be careful.", DLG_NO_CHOICE, DLG_NO_CHOICE, -1 },
};
#define MYSCENE_DLG_INTRO_LEN 2
```

**Runtime (ngpc_dialog / ngpc_menu):**
Both modules are part of `NgpCraft_base_template/optional/`. Include and link them when your project uses dialogues or menus.

---

### 4.10 Help Tab

Embedded FR/EN help browser for quick in-app reference.

---

## 5. Export Pipeline

### 5.1 Export Modes

| Mode | How to trigger | Effect |
|---|---|---|
| **Single scene** | Project tab → `Scene → .c` | Exports current scene only; updates `scenes_autogen` |
| **All scenes** | Project tab → `All scenes → .c` | Batch export; refreshes `scenes_autogen` |
| **Template-ready** | Project tab → `Export (template-ready)` | All scenes + patches template Makefile + generates `src/ngpng_autorun_main.c` |

**Template-ready export details:**
- Patches `makefile` to `include GraphX/gen/assets_autogen.mk` (idempotent, marked with `# NGPNG_BEGIN` / `# NGPNG_END`)
- Generates `src/ngpng_autorun_main.c` — a zero-code preview that loads and runs all scenes
- Disable autorun at runtime: compile with `NGPNG_AUTORUN=0`
- Rollback: restore `makefile.bak_ngpng`, then delete `src/ngpng_autorun_main.c`

### 5.2 Generated Files

All files are written to `export_dir` (configured per project, e.g. `GraphX/gen`).

| File | Description |
|---|---|
| `assets_autogen.mk` | Appends all `.c` files in `export_dir` to `OBJS`. Also does `-include audio_autogen.mk` if present. |
| `scene_<name>.h` | Template-ready loader with `enter()`, `exit()`, `update()` helpers. Includes `scene_<name>_level.h`. |
| `scene_<name>_level.h` | Gameplay room metadata: entities, waves, regions, triggers, paths, collision, layout, scroll, BGM defines, `PROFILE`, `MAP_MODE`. |
| `scenes_autogen.c` | Global scene dispatch table (`g_ngp_scenes[]`) with `enter`, `exit`, `update` function pointers. |
| `scenes_autogen.h` | Declarations + `NGP_SCENE_START_INDEX` + `NGP_SCENE_COUNT`. |
| `audio_autogen.mk` | Appends Sound Creator export `.c` files to `OBJS` (generated when a manifest is linked). |
| `ngpc_project_sfx_map.h` | SFX enum + gameplay ID → Sound Creator index table (generated when SFX mapping is defined). |
| `sounds_game_sfx_autogen.c` | Ready-to-compile `Sfx_Play(u8 id)` wrapper (generated alongside the manifest). |
| `*_mspr.c / *_mspr.h` | Sprite export (tile data, palette, metasprite frames). |
| `*_map.c / *_map.h` | Tilemap export (tile indices, scroll map data). |
| `*_hitbox.h` | Per-frame hurtbox array (`NgpcSprHit g_<name>_hit[]`), sprite-local AABB offsets. |
| `*_ctrl.h` | Player control macros (`NAME_CTRL_INIT` / `NAME_CTRL_UPDATE`). Only generated when `ctrl.role = player`. |
| `*_anims.h` | Named animation state table for use with the `ngpc_anim` optional module (frame ranges, mode, speed). |
| `*_motion.h` | Motion pattern table for fighting-game inputs (`NGP_FAR` step arrays + `NgpcMotionPattern` table). Generated when at least one motion pattern is defined. |
| `scene_*_dialogs.h` | Dialogue banks for the scene: text palette, `NgpcDlgEntry` arrays, menu arrays. Generated when at least one dialogue bank is defined. |
| `*_props.h` | Entity physics and combat properties struct (speed, gravity, HP, damage, etc.). |
| `*_namedanims.h` | Named animation states for `ngpc_anim` module (frame array, mode loop/pingpong/oneshot, speed). |
| `ngpc_project_constants.h` | Project-level `#define` constants (game tuning values defined in the Project tab). |

**Anti-duplicate safety:** If `GraphX/foo.c/.h` already exists (e.g., template-provided assets), NgpCraft Engine reuses those files instead of generating a duplicate `GraphX/gen/foo_map.c` that would cause a linker "multiply defined" error. `assets_autogen.mk` filters accordingly.

### 5.3 Headless / CI Mode

Run export without launching the GUI — safe for build servers:

```
python ngpcraft_engine.py --export project.ngpcraft
python ngpcraft_engine.py --export project.ngpcraft --scene Act1
python ngpcraft_engine.py --export project.ngpcraft --sprite-tool /path/to/ngpc_sprite_export.py
python ngpcraft_engine.py --export project.ngpcraft --tilemap-tool /path/to/ngpc_tilemap.py
```

Headless mode uses `core/headless_export.py` directly — no Qt dependency at runtime.

---

## 6. Template Integration

### 6.1 Makefile

After a **template-ready export**, your `makefile` will contain:

```makefile
# NGPNG_BEGIN
include GraphX/gen/assets_autogen.mk
# NGPNG_END
```

`assets_autogen.mk` handles:
- Adding all generated `.c` files to `OBJS`
- Link-order sorting: sprites (`*_mspr.c`) → tilemaps (`*_map.c`) → other assets (prevents near-pointer overflow with cc900)
- `-include audio_autogen.mk` for Sound Creator exports
- **Mapstream auto-detection**: if a large-map streaming scene is detected, automatically injects `NGPNG_HAS_MAPSTREAM=1` and adds `ngpc_mapstream.rel` to the linker inputs

### 6.2 Using a Scene in C

Minimal usage:

```c
#include "scene_myScene.h"

/* Load assets and start BGM */
scene_myScene_enter();

/* Each frame */
scene_myScene_update();      /* audio update */

/* On exit */
scene_myScene_exit();
```

If you need to separate asset loading from audio:

```c
scene_myScene_load_all();          /* assets only */
scene_myScene_audio_enter();       /* start BGM */
scene_myScene_audio_update();      /* each frame */
scene_myScene_audio_exit();        /* optional fade out */
```

Audio helpers are compiled only when `NGP_ENABLE_SOUND=1` in the Makefile.

### 6.3 Scenes Manifest

When multiple scenes are exported, NgpCraft Engine maintains a global manifest:

```c
#include "scenes_autogen.h"

/* Boot */
g_ngp_scenes[NGP_SCENE_START_INDEX].enter();

/* Frame loop */
g_ngp_scenes[current].update();
```

`NGP_SCENE_COUNT` gives the total number of exported scenes. The start scene and order are controlled from the Project tab (drag & drop to reorder).

---

## 7. Audio Integration

### BGM (per scene)

1. In **Project tab → Audio**, link your Sound Creator `project_audio_manifest.txt`.
2. Assign a BGM track to each scene.
3. Export generates `SCENE_<NAME>_BGM_INDEX` defines in `scene_<name>_level.h`.

### SFX mapping

1. In **Project tab → SFX mapping**, map gameplay IDs to Sound Creator indices.
2. Export generates:
   - `ngpc_project_sfx_map.h` — enum + lookup table
   - `sounds_game_sfx_autogen.c` — `Sfx_Play(u8 id)` wrapper

Usage in game:

```c
#include "ngpc_project_sfx_map.h"
Sfx_Play(SFX_JUMP);
```

**Requirements:**
- Sound Creator exports must be in C mode (`project_sfx.c`). ASM mode skips SFX autogen.
- `audio_autogen.mk` sets `SFX_PLAY_EXTERNAL=1` automatically.

### Build setup

Enable sound in the Makefile:

```makefile
NGP_ENABLE_SOUND = 1
```

When `assets_autogen.mk` is included, `audio_autogen.mk` is pulled in automatically — it adds `project_sfx.c`, `song_*.c`, and `sounds_game_sfx_autogen.c` (if present) to `OBJS`. `project_audio_api.c` and `project_instruments.c` are intentionally excluded (handled via `#include` inside `sound_data.c`).

**Autorun SFX test:** In template-ready preview mode, `A` plays the current SFX and `OPTION` cycles SFX IDs.

---

## 8. NGPC Hardware Constraints

NgpCraft Engine enforces or warns about the following hardware limits:

| Constraint | Value |
|---|---|
| Screen tiles | 20 × 19 (160 × 152 px) |
| BG tilemap size | 32 × 32 tiles max |
| Tile size | 8 × 8 px |
| Colors per palette | 4 (index 0 = transparent on scroll planes) |
| Sprite palette banks | 16 |
| BG palette banks | 16 |
| VRAM tiles (free) | Slots 128+ (0–31 reserved, 32–127 = system BIOS font) |
| Compiler | cc900 — strict C89: no `inline`, no mid-block declarations, no division by zero |

**`NGP_FAR` pointers:** cc900 uses 16-bit (near) pointers by default. ROM data (tiles, palettes, maps) lives at `0x200000+`, which is out of near range. All pointers to ROM data in generated headers use `NGP_FAR`. Never remove it.

**Generated code is always C89-clean.** No inline functions, no VLAs, no mixed declarations/statements.

---

## 9. Runtime C Modules

NgpCraft Engine bundles a set of C runtime modules in `runtime/src/`. These are copied into new projects on scaffold and synced on template-ready export.

### Core (`runtime/src/core/`)

| File | Description |
|---|---|
| `ngpc_config.h` | Feature flags: `NGP_ENABLE_SOUND`, `NGP_ENABLE_FLASH_SAVE`, `NGP_ENABLE_DMA`, `NGP_ENABLE_SPR_SHADOW`, etc. |
| `ngpc_sys.c` | System initialization |
| `ngpc_timing.c` | Framerate / timing helpers |

### Graphics (`runtime/src/gfx/`)

| File | Description |
|---|---|
| `ngpc_sprite.c/.h` | Sprite management: set, move, hide, tile/flags/palette updates. Optional shadow buffer for VBlank-safe OAM flush. |

### Game engine (`runtime/src/ngpng/`)

| File | Description |
|---|---|
| `ngpng_engine.c/.h` | Camera follow modes, scroll constraints, region locking |
| `ngpng_entities.c/.h` | Entity pool: structs, spawn/update/draw, type helpers |
| `ngpng_triggers.c/.h` | Trigger evaluator (conditions, scroll state, region enter/leave) |
| `ngpng_hud.c/.h` | HUD module: palettes, system text, sprite digit fonts, state |
| `ngpng_player_runtime.c/.h` | Stable player physics helpers (movement, jump, gravity, collision response). Static module — copied as-is into the exported project; not regenerated on export. |
| `ngpng_scene_runtime.c/.h` | Scene enter/reset helpers: asset load sequencing, BGM start, entity pool reset. Regenerated on each export from scene metadata. |

**Compile-time gating:** Entity type structs are compiled only when the corresponding flag is set. This keeps binary size small for simple game types:

| Flag | What it enables |
|---|---|
| `NGPNG_HAS_ENEMY` | `NgpngEnemy` struct (AI, hitboxes, velocity, path tracking, gravity, behavior mode) |
| `NGPNG_HAS_FX` | `NgpngFx` struct (lightweight visual effects / projectile actors) |
| `NGPNG_HAS_PROP_ACTOR` | `NgpngPropActor` struct (platforms, blocks, NPCs, path traversal, bump logic) |

A horizontal shmup that only needs enemies and bullets can compile with `NGPNG_HAS_ENEMY` + `NGPNG_HAS_FX` and skip `NgpngPropActor` entirely.

### Autorun / preview runtime

Generated at export time into `src/ngpng_autorun_main.c`. Provides a zero-code preview that:
- Loads all exported scenes
- Runs camera, scroll, collision, entity, trigger, and HUD logic
- Supports platformer follow camera with dead-zones and room locks
- Supports moving platforms via Path
- Supports pickups, collectibles, bump/break/item blocks
- Supports platformer enemy AI (patrol/chase/fixed/random, wall/ledge turn, stomp)
- Supports checkpoints, `exit_goal`, and `DOOR` transitions

---

## 10. Validation & QA

### In-tool validation

The **Validation Center** (Project tab → Details) runs:

1. **Per-scene checks** — missing assets, missing player, hurtbox coverage, export_dir presence
2. **Level checks** — camera configured, references valid, export symbol present
3. **Export pipeline checks** — filename collisions (`scene_*`, `*_mspr.c`, `*_map.c`), stale autogens
4. **Template contract checks** — `makefile`, `src/main.c`, `tools/`, `ngpc_metasprite.h`, `NGP_FAR` present

### Validation suite (CI / QA)

Generate and optionally build 4 mini validation projects:

```
# Generate validation projects
python ngpcraft_engine.py --validation-suite /path/to/output/

# Export only
python ngpcraft_engine.py --validation-run /path/to/output/

# Export + build (requires make/cc900 in PATH)
python ngpcraft_engine.py --validation-run /path/to/output/ --build

# Export + build + smoke launch (requires emulator in PATH or NGPNG_SMOKE_EMULATOR set)
python ngpcraft_engine.py --validation-run /path/to/output/ --build --smoke-run
```

The four validation projects are:
- **Sprite Lab** — sprite pipeline (loading, palette, hitbox, layer split)
- **Mini Shmup** — horizontal shmup (waves, bullets, forced scroll)
- **Mini Platformer** — platformer (gravity, collision, camera, checkpoints)
- **Mini Top-Down** — top-down (free scroll, tile collision, regions)

Results are written to `VALIDATION_RUN.md` and `validation_run.json`.

### HTML report

From the Project tab, generate a standalone HTML report covering:
- VRAM / tile budget per scene
- Scene inventory
- Palette reuse analysis
- Missing asset summary

---

## 11. Command-Line Reference

```
python ngpcraft_engine.py [OPTIONS] [project.ngpcraft]
```

| Option | Description |
|---|---|
| *(no option)* | Launch GUI, optionally open project |
| `--export <project.ngpcraft>` | Headless export (all scenes) |
| `--export <p.ngpcraft> --scene <id>` | Headless export, single scene |
| `--sprite-tool <path>` | Override path to `ngpc_sprite_export.py` |
| `--tilemap-tool <path>` | Override path to `ngpc_tilemap.py` |
| `--validation-suite <outdir>` | Generate 4 validation projects |
| `--validation-run <outdir>` | Export 4 validation projects |
| `--validation-run <outdir> --build` | Export + `make` each project |
| `--validation-run <outdir> --build --smoke-run` | Export + build + emulator launch |

**Helper scripts:**

```
# Sync the embedded template copy from a dev NgpCraft_base_template folder
python sync_template.py [--dry-run] [--verbose]

# Regenerate ngpng_autorun_main.c without launching the GUI
python regen_autorun.py project.ngpcraft
```

---

## 12. Extending the Tool

NgpCraft Engine is structured so that `core/` modules can be imported independently of the Qt GUI — suitable for scripts, CI tools, or custom exporters.

### Key entry points

```python
# Headless project export
from core.headless_export import export_project, export_scene
export_project("project.ngpcraft", sprite_tool=..., tilemap_tool=...)

# Scaffold a new project
from core.project_scaffold import scaffold_project
scaffold_project(name="MyGame", template_dir=..., output_dir=...)

# VRAM budget estimation
from core.project_model import estimate_vram
budget = estimate_vram(project_data)
```

### Core module overview

| Module | Purpose |
|---|---|
| `sprite_loader.py` | Load PNG → `SpriteData` with RGB444-quantized palette |
| `rgb444.py` | NGPC RGB444 quantization, nibble snapping, image quantization |
| `layer_split.py` | Split over-colored sprites (>3 colors) into hardware layers |
| `palette_remap.py` | Shared palette helpers, color space conversion |
| `entity_roles.py` | Gameplay role helpers (`player`, `enemy`, `item`, `npc`, `trigger`, `platform`, `block`, `prop`) |
| `collision_boxes.py` | Normalize hurtbox / offensive hitbox model |
| `scene_collision.py` | Derive scene collision map from tilemap metadata |
| `scene_presets.py` | Preset configurations for common level layouts |
| `sprite_named_anims_gen.py` | Generate animation name headers from sprite frame metadata |
| `scene_level_gen.py` | Generate `scene_*_level.h` gameplay headers + `scene_*_dialogs.h` dialogue banks |
| `scene_loader_gen.py` | Generate `scene_*.h` template-ready loaders |
| `scenes_autogen_gen.py` | Maintain global `scenes_autogen.c/.h` manifest |
| `headless_export.py` | Orchestrate the full export pipeline without GUI |
| `export_validation.py` | Static export checks (pre-flight) |
| `template_integration.py` | Makefile patching, runtime sync, autorun generation |
| `template_preflight.py` | Template contract validation before export |
| `project_scaffold.py` | Scaffold new project from template |
| `project_model.py` | VRAM/palette budget estimates |
| `audio_manifest.py` | Parse Sound Creator manifest |
| `audio_autogen_mk.py` | Generate `audio_autogen.mk` |
| `sfx_map_gen.py` | Map gameplay SFX IDs → Sound Creator indices |
| `sfx_play_autogen.py` | Generate `sounds_game_sfx_autogen.c` |
| `assets_autogen_mk.py` | Generate `assets_autogen.mk` with link-order sorting |
| `game_constants_gen.py` | Generate `ngpc_project_constants.h` from project-level `#define` list |
| `game_vars_gen.py` | Generate `ngpc_game_vars.h` — game flags and variable declarations |
| `hitbox_export.py` | Generate `*_hitbox.h`, `*_ctrl.h`, `*_props.h`, `*_anims.h`, `*_motion.h` from sprite frame metadata |
| `project_templates.py` | Concrete starter templates for new projects (Blank, Shmup example, Platformer example) |
| `sprite_export_cli.py` | Robust subprocess wrapper to call `ngpc_sprite_export.py`; handles path resolution and error reporting |
| `template_updater.py` | Download and sync `NgpCraft_base_template` from GitHub (no git required); used by the **↓ Update Template** button in the Help tab |
| `report_html.py` | Generate standalone HTML budget/inventory report |
| `validation_suite.py` | Scaffold 4 mini validation projects |
| `validation_runner.py` | Run, build, and smoke-test validation projects |

**API stability:** `core/` is the stable public API. `ui/` and `ui/tabs/` are internal Qt components and may change without notice. Names prefixed with `_` are private.

For full public type signatures and function documentation, see `API_REFERENCE.md`.

---

## Appendix: Tilemap Integration Notes

When integrating a large background tilemap:

- A large BG can consume enough tile slots to overlap sprite tile bases. Adjust sprite `tile_base` values accordingly.
- If `export_dir = GraphX/gen` and the template already ships `GraphX/foo.c/.h`, NgpCraft Engine reuses those and filters them out of `assets_autogen.mk` to prevent "multiply defined" linker errors.
- The **Export (template-ready)** + autorun mode is ideal for visual validation. For a project with a custom `src/main.c`, keep `assets_autogen.mk` but set `NGPNG_AUTORUN=0` or remove the autorun file once visual validation is done.
- `ngpc_tilemap.py` output: `tiles_count` = number of `u16` words (= `nb_tiles × 8`), not the number of tiles. `map_tiles[]` = indices 0..N in the unique tile set — add `TILE_BASE` when loading into VRAM.

## Appendix: Validated Integration (Example Project)

Real-project validation confirmed:
- `lvl_1_bg.c/.h` integrated as-is as a level background — no corrections needed to exported files.
- `lvl_1_bg_col.h` integrated as-is for runtime collision — consistent with the corresponding tilemap.
- Anti-duplicate filtering (`GraphX/*.c` vs `GraphX/gen/*_map.c`) worked correctly in a mixed workflow.

What still requires game-side work (always):
- Consuming the exported BG at runtime (scroll, camera, SCR1/SCR2 loading)
- Writing collision/gameplay logic that reads the exported table (`COL_SOLID`, `COL_PLATFORM`, etc.)
- Adjusting global VRAM layout if a large BG and sprites share tile budgets
