# NgpCraft Engine

> ### ⚠️ BETA — Not yet stable
>
> This tool is in **early beta** and is **not yet fully stable**.
> Bugs exist, some workflows are still rough, and things may break between updates.
>
> **If you are looking for a polished, friction-free experience, it is probably worth waiting
> for a more stable release.** In its current state, using NgpCraft Engine means accepting
> that you will likely run into issues — your patience and feedback are what make it better.
>
> - **Your feedback matters.** Bug reports, usability issues and feature requests are all welcome
>   and directly shape the roadmap — open an issue on [GitHub Issues](https://github.com/Tixul/NgpCraft_engine/issues).
> - **Fixes are prioritized.** I aim to respond to reported bugs as quickly as possible,
>   while striving to keep backward compatibility with existing `.ngpcraft` projects.
> - **Keep the tool updated.** The embedded template and runtime modules improve regularly.
>   Use **Help tab → ↓ Update Template** to stay on the latest version for the best experience.
> - **Project format stability.** Backward compatibility with older `.ngpcraft` files is a priority.
>   That said, during beta some migrations may be unavoidable — keep a backup of important projects
>   before updating, just in case.
> - **Tested on Windows (primary platform).** Linux and macOS should work but may require
>   adjustments — feedback on non-Windows setups is especially welcome.
>
> Thank you for trying NgpCraft Engine and helping make it better!

---

**Visual asset pipeline and no-code game generator for Neo Geo Pocket Color homebrew.**

NgpCraft Engine is a GUI tool that bridges the gap between your art and a buildable NGPC cartridge.
You design visually — it generates all the C code, Makefile patches and runtime glue.
No boilerplate. No manual VRAM accounting. No hand-coding collision maps.

> Part of the **[NgpCraft ecosystem](https://github.com/Tixul)** —
> a complete open-source toolchain for Neo Geo Pocket Color development.

---

## ⚠️ Current focus

The current priority is **stabilizing the engine**, not adding new features.

The focus right now is to:
- fix bugs
- improve reliability
- make the workflow more robust

New features will come later, once the core is stable.

---

## What it does

| You provide | NgpCraft Engine generates |
|---|---|
| Sprite sheet PNGs | `*_mspr.c/h` — tiles, palettes, metasprite frames |
| Tilemap PNGs | `*_map.c/h` — scroll maps + collision grid |
| Frame slices + hitboxes | `*_hitbox.h`, `*_ctrl.h`, `*_props.h`, `*_anims.h`, `*_motion.h` |
| Entity placements + AI rules | Spawn tables, path tables, wave tables |
| Trigger rules (visual) | 68 conditions × 76 actions → `g_scene_trig_*[]` C arrays |
| Dialogue banks | Per-scene lines, choices, menus → `scene_*_dialogs.h` |
| Audio manifest | `sound_data.c/h`, `Sfx_Play()` wrapper, BGM per scene |
| Global vars / flags / entity types | `game_vars.h` (tree-shaken), `entity_types.h` (ROM-only table) |
| — | `src/ngpng_autorun_main.c` — runnable preview, zero C to write |

One click on **Export (template-ready)** produces a project that compiles and runs.

---

## Features at a glance

**Asset pipeline**
- PNG → NGPC sprites and tilemaps with live RGB444 quantization and 3-color-per-tile enforcement
- Automatic VRAM tile/palette slot tracking across the whole project
- Per-tile collision painting: 18 types (SOLID, ONE_WAY, LADDER, STAIR, WATER, ICE, SPRING, CONVEYOR…)
- Tilemap compression (LZ77 / RLE), large-map streaming support
- Tile budget checker with live warnings

**Globals tab — project-wide data**
- 8 boolean flags + 8 integer variables with optional names — referenced by index in triggers
- Tree-shaking: only named or used vars/flags get a `#define` alias in the generated `game_vars.h`
- 16 user-defined constants (`CONST_NAME = value`) emitted as `#define` — no runtime cost
- 8 SFX slots with names, tail-trimming (only export up to the last used entry)
- Entity type library: define archetypes (role, behavior, AI params, direction) once at project level,
  reuse across scenes via **Save as type** / **Apply type** in the Level tab
- ROM-only `entity_types.h`: `static const EntityTypeDef et_table[]` — zero RAM, zero CPU overhead

**Visual level editor**
- Entity placement: role, AI behavior (speed, aggro range, patrol cadence), physics props
- Wave spawner for shmup-style or timed enemy groups — gap-checked, delay-sorted
- Camera deadzone overlay, parallax config, forced-scroll presets
- Waypoint paths for patrol AI and moving platforms
- Neighboring scene edge-warp generation
- 16 genre presets (Platformer, Shmup, RPG, Fighting, Puzzle, Roguelike, Visual Novel…)
  each one reorders conditions, actions, and presets to surface what matters for that genre

**Trigger system — visual scripting**
- 68 conditions: `on_jump/land/hurt/death`, player in region, HP, timer, flags, variables,
  wave state, quest stage, enemy count, `dialogue_done`, `choice_result`, `chance`, push-block-on-tile…
- 76 actions: BGM/SFX, spawn, scene transition, move entity to exact tile, set flag/variable,
  give item, toggle tile, flash screen, camera lock, fade in/out, save game…
- Multi-condition AND chains + OR groups
- All exported as plain C89 arrays — zero runtime overhead for unused features
- Flag/var spinboxes show the name from the Globals tab inline, no context switching needed

**Dialogue system**
- Named dialogue banks per scene: ordered lines with speaker, text and portrait
- Choices (up to 2 per line) with branching to any dialogue — `ngpc_dialog` runtime
- Menus (2–8 items) with per-item goto — `ngpc_menu` runtime
- NGPC preview at 3× scale with real sprite tiles and palette colors
- Text palette: 3 editable RGB444 color slots
- Custom dialog box background sprite (16×16 — 4 tiles 8×8)
- CSV import/export for spreadsheet-based content authoring

**Hitbox & controller editor**
- Per-frame AABB hitboxes and multi-box attack windows
- Animation state filter on attack boxes (active only in `attack`, `special`, etc.)
- One-click export: `_ctrl.h` with INIT/UPDATE macros for a pad-controlled character
- Motion patterns (fighting-game style): QCF, DP, double-tap → `_motion.h` with `NGP_FAR` ROM data

**Audio integration**
- Link a Sound Creator project manifest — BGM per scene, SFX ID mapping
- Auto-generates `sound_data.c/h` and SFX wrapper, SFX-only projects supported

**Export & build**
- Single scene, all scenes, or template-ready (Makefile patched, autorun generated)
- Headless / CI mode: `python ngpcraft_engine.py --export project.ngpcraft`
- Full validation center with per-scene badges and corrective actions

---

## Quick start

```
pip install -r requirements.txt
python ngpcraft_engine.py
```

1. **File › New Project** — pick *Shmup example* or *Platformer example* to start with a working scene
2. **Hitbox tab** — slice your sprite frames, assign `ctrl.role = player`
3. **Tilemap tab** — load your background PNG, paint the collision layer
4. **Globals tab** — name your flags/vars/SFX, define entity type archetypes *(optional but recommended)*
5. **Level tab** — place entities, configure waves and triggers; use **Save as type** / **Apply type** to reuse archetypes
6. **Dialogues tab** *(RPG/Adventure)* — create dialogue banks, assign portraits, pick text palette
7. **Project tab › Export (template-ready)**
8. `make` from the template root → flash or emulate

> **Auto-save** — every change is written to the `.ngpcraft` file immediately.
> There is no Save button.

---

## Requirements

| | |
|---|---|
| Python | 3.10+ |
| PyQt6 | ≥ 6.4.0 |
| Pillow | ≥ 9.0.0 |
| Toolchain | [NgpCraft_base_template](https://github.com/Tixul/NgpCraft_base_template) + Toshiba cc900 compiler |

---

## Toolchain

NgpCraft Engine currently requires the **official Toshiba cc900 compiler** to build projects.
This is a proprietary tool that was distributed as part of the official NGPC SDK.

An open-source replacement — **[NGPCraft toolchain](https://github.com/Tixul/NGPCraft)** (assembler, linker and C compiler for the TLCS-900/H CPU) — is actively in development,
but is not yet ready to fully replace the official compiler for production use.

Once the open-source toolchain reaches that milestone, NgpCraft Engine will support it as a drop-in alternative,
and the Toshiba dependency will no longer be required.

---

## NgpCraft Ecosystem

NgpCraft Engine is one part of a complete NGPC development stack,
all available at **[github.com/Tixul](https://github.com/Tixul)**.

| Project | What it is |
|---|---|
| **[NgpCraft_base_template](https://github.com/Tixul/NgpCraft_base_template)** | C project template + 40+ optional runtime modules (physics, FSM, camera, animation, dialogue, audio, flash save…). The output of NgpCraft Engine targets this template. |
| **[NGPC Sound Creator](https://github.com/Tixul/NGPC_Sound_Creator)** | T6W28 PSG tracker for composing BGM and SFX. Exports a manifest that NgpCraft Engine reads directly. |
| **[NGPCraft toolchain](https://github.com/Tixul/NGPCraft)** | Open-source assembler, linker and C compiler (cc900) for the TLCS-900/H CPU. No Toshiba SDK required. *(coming soon)* |

---

## Updating the embedded template

The tool ships with a copy of **NgpCraft_base_template** used for new project scaffolding.
Keep it in sync without needing git:

- **In the GUI:** Help tab → **↓ Update Template** — downloads the latest version from GitHub
- **CLI:** `python sync_template.py` (add `--dry-run` to preview changes)

---

## Documentation

Full documentation lives in the [User Manual (README_manual.md)](README_manual.md)
and the embedded **Help tab** (FR / EN) inside the tool itself.

---

## Known limitations

- Some trigger conditions and actions are not yet fully wired — behavior may be incomplete or inconsistent
- Dialogue display and stability are still being improved
- Projects mixing top-down and platformer scenes in the same game may produce unexpected results
- Build setup can be sensitive depending on environment
- Some features may change between versions — see the BETA notice at the top for details

All of the above are actively worked on and will improve over time.

---

## Contributing

NgpCraft Engine is still in active development, and community help is very welcome.

### Ways to contribute

- **Report bugs** — open an issue with steps to reproduce
- **Test the tool** — try building small projects, explore features, push edge cases
- **Create example projects / templates** — small playable demos (platformer, shmup…) help others get started
- **Contribute assets** — sprites, tilemaps, UI elements can be included as examples (with credit)
- **Improve documentation / tutorials** — help make the tool more accessible to beginners
- **Report performance issues** — especially useful for DMA, streaming, and hardware constraints
- **Test on real hardware** — differences between emulator and real hardware are extremely valuable
- **Suggest improvements** — UX ideas, workflow improvements, missing features
- **Design an icon / visual identity** — a proper icon or logo would greatly improve presentation
- **Improve build / toolchain setup** — any help making setup easier or more robust is welcome

### Support the project

- Star the repo
- Share it with the NGPC / retro dev community
- GitHub Sponsors (optional)

---

## ⏱️ About support

I'll do my best to fix reported issues as quickly as possible.

However, this is a solo project developed in my free time,
so response times and fixes may vary.

Thanks for your patience and support.

---

## Philosophy

This isn't meant to be just my tool.

I'd really like NgpCraft to become a tool for the whole community —
something you can explore, improve, and make your own.

---

## License

See [LICENSE](LICENSE).
