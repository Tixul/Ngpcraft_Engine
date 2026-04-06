# Registres matériels NGPC — Référence complète

Source : ngpcspec.txt (NeeGee, 2000) + datasheet TLCS-900/H.
Toutes les valeurs sont tirées de `ngpc_hw.h` dans ce template.

---

## Carte mémoire

```
0x000000 - 0x0000FF   Registres I/O internes (CPU, timers, DMA, watchdog)
0x004000 - 0x005FFF   RAM principale (8 KB)
0x006000 - 0x006BFF   RAM battery-backed (3 KB) — pour sauvegardes légères
0x007000 - 0x007FFF   Z80 RAM (4 KB, partagée avec le CPU son)
0x006F80 - 0x006FFF   Zone système BIOS (variables, vecteurs ISR)
0x008000 - 0x0087FF   Registres vidéo K2GE
0x008800 - 0x008BFF   Sprite VRAM (64 sprites × 4 octets)
0x008C00 - 0x008C3F   Sprite palette indices (64 octets)
0x009000 - 0x0097FF   Scroll plane 1 — tilemap (32×32 × 2 octets = 2 KB)
0x009800 - 0x009FFF   Scroll plane 2 — tilemap (32×32 × 2 octets = 2 KB)
0x00A000 - 0x00BFFF   Character/tile RAM (512 tiles × 16 octets = 8 KB)
0x200000 - 0x3FFFFF   ROM cartouche (2 MB — accès FAR uniquement)
0xFF0000 - 0xFFFFFF   ROM interne BIOS (64 KB)
0xFFFE00              Table de vecteurs BIOS (fonctions système)
```

---

## CPU / Timers internes

| Registre | Adresse | Taille | Description |
|---|---|---|---|
| `HW_WATCHDOG` | `0x006F` | u8 | Watchdog — écrire `0x4E` (WATCHDOG_CLEAR) |
| `HW_TRUN` | `0x0020` | u8 | Timer run control (bit0=TIM0, bit1=TIM1...) |
| `HW_TREG0` | `0x0022` | u8 | Valeur de recharge timer 0 |
| `HW_TREG1` | `0x0023` | u8 | Valeur de recharge timer 1 |
| `HW_T01MOD` | `0x0024` | u8 | Mode timer 0/1 (source horloge) |
| `HW_TFFCR` | `0x0025` | u8 | Timer flip-flop control |
| `HW_TREG2` | `0x0026` | u8 | Timer 2 (PWM0) |
| `HW_TREG3` | `0x0027` | u8 | Timer 3 (PWM1, son) |
| `HW_T23MOD` | `0x0028` | u8 | Mode timer 2/3 |
| `HW_DMA0V` | `0x007C` | u8 | Vecteur démarrage DMA canal 0 |
| `HW_DMA1V` | `0x007D` | u8 | Vecteur démarrage DMA canal 1 |
| `HW_DMA2V` | `0x007E` | u8 | Vecteur démarrage DMA canal 2 |
| `HW_DMA3V` | `0x007F` | u8 | Vecteur démarrage DMA canal 3 |

**Timer 0 → HBlank :**
```c
HW_T01MOD &= (u8)~0xC3;  /* clock source = TI0, mode 8-bit */
HW_TREG0   = 0x01;        /* reload = 1 (fire every HBlank) */
HW_TRUN   |= 0x01;        /* démarrer timer 0 */
```

---

## Zone système BIOS (variables à 0x6F80)

| Registre | Adresse | Taille | Description |
|---|---|---|---|
| `HW_BAT_VOLT` | `0x6F80` | u16 | Tension batterie (10 bits, 0-1023) |
| `HW_JOYPAD` | `0x6F82` | u8 | État joypad (bits = boutons) |
| `HW_USR_BOOT` | `0x6F84` | u8 | Raison du boot (0=normal, 1=resume, 2=alarme) |
| `HW_USR_SHUTDOWN` | `0x6F85` | u8 | Flag arrêt demandé par l'OS |
| `HW_USR_ANSWER` | `0x6F86` | u8 | Réponse user — bit5 doit être 0 |
| `HW_LANGUAGE` | `0x6F87` | u8 | Langue système |
| `HW_OS_VERSION` | `0x6F91` | u8 | 0=monochrome NGP, !=0=couleur NGPC |

**Joypad — masques de bits (HW_JOYPAD) :**
```c
PAD_UP     = 0x01
PAD_DOWN   = 0x02
PAD_LEFT   = 0x04
PAD_RIGHT  = 0x08
PAD_A      = 0x10
PAD_B      = 0x20
PAD_OPTION = 0x40
PAD_POWER  = 0x80
```

---

## Interruptions

Vecteurs ISR stockés en RAM — pointeurs 32-bit vers la fonction handler.

| Registre | Adresse | Description |
|---|---|---|
| `HW_INT_SWI3` | `0x6FB8` | Software interrupt 3 |
| `HW_INT_SWI4` | `0x6FBC` | Software interrupt 4 |
| `HW_INT_SWI5` | `0x6FC0` | Software interrupt 5 |
| `HW_INT_SWI6` | `0x6FC4` | Software interrupt 6 |
| `HW_INT_RTC` | `0x6FC8` | Alarme RTC |
| `HW_INT_VBL` | `0x6FCC` | **VBlank 60 Hz — OBLIGATOIRE** |
| `HW_INT_Z80` | `0x6FD0` | Interruption Z80 (son) |
| `HW_INT_TIM0` | `0x6FD4` | Timer 0 → HBlank (raster, sprmux) |
| `HW_INT_TIM1` | `0x6FD8` | Timer 1 |
| `HW_INT_TIM2` | `0x6FDC` | Timer 2 |
| `HW_INT_TIM3` | `0x6FE0` | Timer 3 (horloge son) |
| `HW_INT_SER_TX` | `0x6FE4` | Serial TX (réservé) |
| `HW_INT_SER_RX` | `0x6FE8` | Serial RX (réservé) |
| `HW_INT_DMA0` | `0x6FF0` | DMA canal 0 terminé |
| `HW_INT_DMA1` | `0x6FF4` | DMA canal 1 terminé |
| `HW_INT_DMA2` | `0x6FF8` | DMA canal 2 terminé |
| `HW_INT_DMA3` | `0x6FFC` | DMA canal 3 terminé |

**Activer les interruptions :** `__asm("ei");`

**Le VBL ne doit JAMAIS être désactivé.** Le handler VBL minimal doit :
1. Écrire `HW_WATCHDOG = 0x4E`
2. Tester `HW_USR_SHUTDOWN` et demander un shutdown.
   Dans ce template, le shutdown est exécuté en contexte "main loop" (dans `ngpc_vsync()`)
   pour éviter d'appeler le BIOS depuis une ISR sur certains setups hardware.

---

## Registres vidéo K2GE (0x8000)

### Contrôle affichage

| Registre | Adresse | Taille | Description |
|---|---|---|---|
| `HW_DISP_CTL` | `0x8000` | u8 | Display enable |
| `HW_WIN_X` | `0x8002` | u8 | Origine fenêtre X |
| `HW_WIN_Y` | `0x8003` | u8 | Origine fenêtre Y |
| `HW_WIN_W` | `0x8004` | u8 | Largeur fenêtre (max 160) |
| `HW_WIN_H` | `0x8005` | u8 | Hauteur fenêtre (max 152) |
| `HW_FRAME_RATE` | `0x8006` | u8 | **NE PAS MODIFIER** (0xC6 au reset) |
| `HW_RAS_H` | `0x8008` | u8 | Position raster horizontale (lecture seule) |
| `HW_RAS_V` | `0x8009` | u8 | **Ligne raster courante** (0-151 visible, 152+ VBlank) |
| `HW_STATUS` | `0x8010` | u8 | Bit7=CharOver, Bit6=VBlank (lecture seule) |
| `HW_LCD_CTL` | `0x8012` | u8 | Bit7=inversion LCD, Bit2-0=couleur hors fenêtre |
| `HW_GE_MODE` | `0x87E2` | u8 | **NE PAS MODIFIER** (0=K2GE couleur) |

```c
/* Vérifier si on est en VBlank */
if (HW_STATUS & STATUS_VBLANK) { /* en vblank */ }  /* STATUS_VBLANK = 0x40 */

/* Lire la ligne courante (pour profiler le CPU) */
u8 line = HW_RAS_V;  /* 0=haut écran, 151=bas, 152+=vblank */
```

### Sprites

| Registre | Adresse | Taille | Description |
|---|---|---|---|
| `HW_SPR_OFS_X` | `0x8020` | u8 | Décalage global X de tous les sprites |
| `HW_SPR_OFS_Y` | `0x8021` | u8 | Décalage global Y de tous les sprites |

### Scroll planes

| Registre | Adresse | Taille | Description |
|---|---|---|---|
| `HW_SCR_PRIO` | `0x8030` | u8 | Bit7: 0=plane1 devant, 1=plane2 devant |
| `HW_SCR1_OFS_X` | `0x8032` | u8 | Scroll plane 1 — offset X (0-255, 8-bit) |
| `HW_SCR1_OFS_Y` | `0x8033` | u8 | Scroll plane 1 — offset Y (0-255, 8-bit) |
| `HW_SCR2_OFS_X` | `0x8034` | u8 | Scroll plane 2 — offset X |
| `HW_SCR2_OFS_Y` | `0x8035` | u8 | Scroll plane 2 — offset Y |
| `HW_BG_CTL` | `0x8118` | u8 | Background color (Bit7-6=10 pour activer) |

**Important :** les registres scroll sont **8-bit** (tilemap 256×256 px).
Pour un niveau > 256px, il faut mettre à jour la tilemap dynamiquement (ring buffer).
Lors du passage d'une coordonnée monde s16 : `(u8)(cam_x & 0xFF)`.

---

## Palette RAM

**Accès 16-bit uniquement.** Format par entrée : `0x0BGR` (4 bits par canal, 4096 couleurs).

| Zone | Adresse | Palettes |
|---|---|---|
| `HW_PAL_SPR` | `0x8200` | Sprites : palettes 0-15 (64 entrées × u16) |
| `HW_PAL_SCR1` | `0x8280` | Scroll plane 1 : palettes 0-15 |
| `HW_PAL_SCR2` | `0x8300` | Scroll plane 2 : palettes 0-15 |
| `HW_PAL_BG` | `0x83E0` | Couleur de fond |
| `HW_PAL_WIN` | `0x83F0` | Couleur hors-fenêtre |

**Format couleur :**
```c
#define RGB(r, g, b)  ((u16)((r)&0xF) | (((g)&0xF)<<4) | (((b)&0xF)<<8))
/* 0x0BGR : bits 11-8=B, 7-4=G, 3-0=R */

/* Lire/écrire une entrée de palette */
HW_PAL_SCR1[pal_id * 4 + color_idx] = RGB(15, 0, 0);  /* rouge vif */
```

**Convention index 0 :** la couleur 0 de chaque palette est **transparente** pour les scroll planes. Ne jamais y mettre une couleur visible pour les backgrounds.

---

## Sprite VRAM (0x8800)

64 sprites, 4 octets chacun. **Accès octet.**

```
Sprite n :
  0x8800 + n*4 + 0  : tile (bits 7-0 de l'index 9-bit)
  0x8800 + n*4 + 1  : flags
                        bit7    : H flip
                        bit6    : V flip
                        bit4-3  : priorité (00=masqué, 01=derrière, 10=milieu, 11=devant)
                        bit2    : H chain (sprite élargi à droite)
                        bit1    : V chain (sprite élargi en bas)
                        bit0    : tile bit 8 (pour tiles 256-511)
  0x8800 + n*4 + 2  : X position (pixels)
  0x8800 + n*4 + 3  : Y position (pixels)

Palette du sprite n :
  0x8C00 + n        : bits 3-0 = numéro de palette (0-15)
```

```c
/* Constantes de priorité / flip (ngpc_hw.h) */
SPR_HIDE   = (0 << 3)  /* caché */
SPR_BEHIND = (1 << 3)  /* derrière les plans */
SPR_MIDDLE = (2 << 3)  /* entre les plans */
SPR_FRONT  = (3 << 3)  /* devant tout */
SPR_HFLIP  = 0x80
SPR_VFLIP  = 0x40
SPR_HCHAIN = 0x04      /* étendre le sprite de 8px à droite */
SPR_VCHAIN = 0x02      /* étendre le sprite de 8px en bas */
```

---

## Tilemap scroll planes (0x9000 / 0x9800)

Deux plans 32×32 tiles. Chaque entrée = 1 mot u16. **Accès 16-bit.**

```
HW_SCR1_MAP[ty * 32 + tx] = entrée
HW_SCR2_MAP[ty * 32 + tx] = entrée

Format entrée (u16) :
  bit15      : H flip
  bit14      : V flip
  bit12-9    : numéro de palette (0-15)  [bits 4-1 du high byte]
  bit8       : bit 8 de l'index tile (pour tiles 256-511)
  bit7-0     : bits 7-0 de l'index tile
```

```c
/* Macro de construction (ngpc_hw.h) */
#define SCR_ENTRY(tile, pal, hflip, vflip) \
    ((u16)((tile)&0xFF) | \
     (((u16)(hflip)&1)<<15) | (((u16)(vflip)&1)<<14) | \
     (((u16)(pal)&0xF)<<9)  | (((u16)(((tile)>>8)&1))<<8))

#define SCR_TILE(tile, pal)  SCR_ENTRY((tile), (pal), 0, 0)

/* Exemple : placer tile 200, palette 3, à la position (5, 2) */
HW_SCR1_MAP[2 * 32 + 5] = SCR_TILE(200, 3);
```

---

## Tile/Character RAM (0xA000)

512 tiles, 8×8 pixels, 2bpp (4 couleurs). 8 mots u16 par tile = 16 octets.

```
HW_TILE_DATA[tile_id * 8 + row] = u16 représentant une ligne de 8 pixels

Format d'une ligne u16 (8 pixels, 2 bits chacun, big-endian) :
  bits 15-14 : pixel colonne 0 (gauche)
  bits 13-12 : pixel colonne 1
  ...
  bits  1-0  : pixel colonne 7 (droite)

Index couleur 0 = transparent sur les scroll planes.
```

```c
/* Accéder directement à un pixel */
/* pixel col c, row r du tile id */
volatile u16 *row_ptr = HW_TILE_DATA + tile_id * 8 + r;
u8 shift = 14 - c * 2;
u8 color = (*row_ptr >> shift) & 3;

/* Écrire */
*row_ptr = (*row_ptr & ~(3 << shift)) | ((u16)(new_color & 3) << shift);
```

---

## Son — Z80

| Registre | Adresse | Description |
|---|---|---|
| `HW_SOUNDCPU_CTRL` | `0x00B8` | Contrôle Z80 — `0xAAAA`=stop, `0x5555`=start |
| `HW_Z80_NMI` | `0x00BA` | Déclencher NMI Z80 |
| `HW_Z80_COMM` | `0x00BC` | Octet de communication CPU↔Z80 |
| `HW_Z80_RAM` | `0x7000` | Base de la RAM Z80 (4 KB) |

Le Z80 accède au T6W28 via ses ports I/O : port `0x4000` (droite), `0x4001` (gauche).
Le driver son du template (`src/audio/sounds.c`) gère tout cela de façon transparente.

---

## Cartouche ROM

| Constante | Valeur | Description |
|---|---|---|
| `CART_ROM_BASE` | `0x200000` | Adresse CPU de la ROM |
| `CART_ROM_SIZE` | `0x200000` | Taille max (2 MB) |
| Dernier 16 KB | `0x3FC000-0x3FFFFF` | Réservé système — ne pas utiliser |
| Zone save type. | `0x3FA000` | Offset de sauvegarde par défaut (template) |

**Accès ROM depuis C :**
```c
/* Toujours via NGP_FAR */
const u16 NGP_FAR *my_tiles = (const u16 NGP_FAR *)0x210000;

/* Ou via symboles linker (adresses résolues automatiquement) */
extern const u16 NGP_FAR my_tileset[];
```

---

## Timings et budgets

### Budget CPU par frame

| Élément | Valeur |
|---|---|
| Fréquence CPU | 6.144 MHz |
| Cycles par frame (60 Hz) | ~102 400 cycles |
| Durée VBlank | ~3.94 ms = ~24 200 cycles |
| Durée HBlank | ~5 µs (~30 cycles) |

Répartition typique :
```
VBI (watchdog + input + audio)  : ~2 000 cycles
Logique jeu                     : ~50 000 cycles (variable)
Mises à jour VRAM               : ~20 000 cycles (idéalement en VBlank)
Marge                           : ~30 000 cycles
```

**Important :** un accès VRAM pendant le rendu actif peut causer un Character Over
(glitch graphique). Concentrer les écritures VRAM dans le VBlank ou via `ngpc_vramq`.

### Budget RAM

| Zone | Taille |
|---|---|
| RAM totale | 12 KB (`0x004000-0x005FFF`) |
| Stack | ~1 KB |
| Variables globales template | ~200 bytes |
| Driver son (voices, state) | ~500 bytes |
| Sprite/metasprite state | ~300 bytes |
| **Game state disponible** | **~9-10 KB** |

### Registres compiler cc900

- **Banks 0-2** : disponibles pour le code utilisateur
- **Bank 3** : réservé système — ne pas utiliser sauf pour les appels BIOS
- Les ISR doivent sauvegarder/restaurer tous les registres utilisés (le keyword
  `__interrupt` le fait automatiquement)
