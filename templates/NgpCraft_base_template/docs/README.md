# NgpCraft_base_template — Documentation annexe

Ce dossier contient les références techniques condensées pour développer sur Neo Geo Pocket Color.
Ces documents permettent de travailler avec le template **sans RAG externe** — toutes les
informations critiques sont ici.

---

## Documents disponibles

| Fichier | Contenu |
|---|---|
| [NGPC_CC900_GUIDE.md](NGPC_CC900_GUIDE.md) | Compilateur cc900 : règles C89, far pointers, inline asm, solution de secours tilemap |
| [NGPC_BIOS_REF.md](NGPC_BIOS_REF.md) | Appels BIOS : conventions, vecteurs, registres bank 3 |
| [NGPC_HW_REGISTERS.md](NGPC_HW_REGISTERS.md) | Registres matériels : K2GE, palette, sprites, tilemap, timings, budgets CPU/RAM |
| [NGPC_GRAPHICS_GUIDE.md](NGPC_GRAPHICS_GUIDE.md) | Pipeline graphique : PNG → tilemap → affichage, méthodes helpers et VRAM brut, checklist debug, fill_rect/set_rect_pal, tileblitter |
| [SOUND_DRIVER_REF.md](SOUND_DRIVER_REF.md) | Driver son custom : capacités, API BGM/SFX, protocole CPU↔Z80, opcodes stream |

---

## Lecture rapide — les 5 règles d'or

1. **Far pointers** — toute donnée en ROM cartouche (`0x200000+`) nécessite `NGP_FAR`
2. **C89 strict** — cc900 refuse le C99 : pas de `//`, pas de déclarations en milieu de bloc
3. **`volatile` partout** — tous les accès registres hardware DOIVENT être `volatile`
4. **VBL obligatoire** — `HW_INT_VBL` doit pointer sur un handler valide, toujours
5. **Watchdog** — écrire `HW_WATCHDOG = 0x4E` au moins une fois toutes les ~100ms (le VBL s'en charge)

---

## Structure de la documentation

```
NgpCraft_base_template/
├── README.md                     ← point d'entrée principal + statut hardware downstream
├── ROADMAP.md                    ← feuille de route et statut des modules
├── dev/DMA.md                    ← notes MicroDMA, pièges hardware, validation
│
├── docs/                         ← référence technique permanente (ce dossier)
│   ├── README.md                 ← cet index
│   ├── NGPC_CC900_GUIDE.md       ← compilateur, far pointers, inline asm
│   ├── NGPC_BIOS_REF.md          ← vecteurs BIOS, conventions d'appel
│   ├── NGPC_HW_REGISTERS.md      ← registres K2GE, timings, budgets
│   └── NGPC_GRAPHICS_GUIDE.md   ← pipeline graphique, exemples de code
│
├── dev/                          ← artefacts de développement interne
│   └── SOURCES.md               ← traçabilité sources techniques (DMA, format VRAM...)
│
├── examples/                     ← exemples de code et pipelines
│   └── ASSET_PIPELINE.md        ← workflow complet PNG → ROM
│   └── dma_example.c            ← patterns MicroDMA (Timer0/Timer1, re-arm, eviter CHAIN)
│   └── dma_raster_example.c     ← exemple ngpc_dma_raster (parallax sans ISR HBlank CPU)
│
└── optional/                     ← modules optionnels
    └── README.md                ← liste et usage des modules optionnels
```

---

## Utilisation avec un LLM / Claude Code

Ces docs sont conçues pour tenir dans une fenêtre de contexte.
Pour un nouveau projet, inclure dans le contexte :
- Ce README (règles d'or + structure)
- `NGPC_CC900_GUIDE.md` (indispensable)
- `NGPC_GRAPHICS_GUIDE.md` (si travail sur l'affichage)
- `NGPC_HW_REGISTERS.md` (si travail proche du hardware)
- `NGPC_BIOS_REF.md` (si utilisation d'appels BIOS directs)

Avec le README principal du template et ces docs, un LLM peut générer du code correct
sans RAG supplémentaire pour la grande majorité des tâches de gameplay.

---

## Roadmap documentation

### Fait — dans ce dossier (`docs/`)
- [x] `NGPC_CC900_GUIDE.md` — compilateur, far pointers, inline asm, solution de secours
- [x] `NGPC_BIOS_REF.md` — vecteurs BIOS, conventions d'appel bank 3
- [x] `NGPC_HW_REGISTERS.md` — registres complets K2GE + timings + budgets CPU/RAM
- [x] `NGPC_GRAPHICS_GUIDE.md` — pipeline graphique, fill_rect/set_rect_pal, wrap-safe, tileblitter
- [x] `SOUND_DRIVER_REF.md` — driver son custom, API BGM/SFX, protocole Z80, opcodes stream

### Déjà couvert — ne pas dupliquer
- **Son** → `README.md` principal §Sound driver (Init, BGM, SFX, opcodes, debug)
- **Asset pipeline** → `examples/ASSET_PIPELINE.md` + section ngpc_lz/ngpc_tilemap du README
- **Modules optionnels** → `optional/README.md`

### Potentiellement utile plus tard
- [ ] `NGPC_LINKER_SCRIPT.md` — sections mémoire, symbols `_DataROM/_Bss`, placement ROM/RAM, contraintes 12 KB
- [ ] `NGPC_DEBUG_GUIDE.md` — workflow debug sur hardware : assert écran, log ring buffer, profiler raster, lecture état émulateur
