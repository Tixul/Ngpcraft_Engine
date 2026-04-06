# Référence BIOS NGPC — Appels système

Le BIOS de la Neo Geo Pocket Color expose des fonctions système accessibles
depuis le programme utilisateur. Ce document couvre les conventions d'appel
et tous les vecteurs utilisés dans ce template.

---

## 1. Convention d'appel — table de vecteurs (0xFFFE00)

La plupart des fonctions BIOS sont accessibles via une table de fonctions à `0xFFFE00`.
Chaque entrée est un pointeur 32-bit. Index = numéro de vecteur.

**Séquence d'appel :**

```asm
; 1. Charger le numéro de vecteur dans RW3
ld rw3, <VECTEUR>

; 2. Charger les paramètres dans les registres bank 3 (XHL3, XDE3, RB3, RC3...)

; 3. Switcher vers bank 3
ldf 3

; 4. Calculer l'offset dans la table (vecteur × 4)
add w, w        ; w *= 2
add w, w        ; w *= 2  =>  w = vecteur * 4

; 5. Charger l'adresse depuis la table et appeler
ld xix, 0xfffe00
ld xix, (xix+w)
call xix
```

**Exemple C (ngpc_rtc_get) :**
```c
__asm(" ld rw3, " NGPC_STR(BIOS_RTCGET));
__asm(" ld xde, (xsp+4)");    /* NgpcTime* depuis la pile */
__asm(" ld xhl3, xde");       /* XHL3 = pointeur vers struct */
__asm(" ldf 3");
__asm(" add w, w");
__asm(" add w, w");
__asm(" ld xix, 0xfffe00");
__asm(" ld xix, (xix+w)");
__asm(" call xix");
```

---

## 2. Convention d'appel — SWI 1

Certaines fonctions BIOS utilisent l'instruction `swi 1` (software interrupt 1)
avec les paramètres dans les registres bank 3 avant le `swi`.

```asm
; Charger paramètres dans bank 3 SANS switcher (les swi lisent directement)
ldb ra3, <code_fonction>
ldb rw3, <VECTEUR>
swi 1
```

**Exemple C (ngpc_shutdown) :**
```c
__asm("ldb ra3, 3");
__asm("ldb rw3, " NGPC_STR(BIOS_SHUTDOWN));
__asm("swi 1");
```

---

## 3. Registres bank 3

Les appels BIOS utilisent les registres du "bank 3" (registres dédiés aux appels système).

| Registre | Alias | Taille | Rôle |
|---|---|---|---|
| `RW3` | W de bank 3 | 16-bit | Numéro de vecteur |
| `RA3` | A de bank 3 | 8-bit | Code fonction / paramètre |
| `RB3` | B de bank 3 | 8-bit | Paramètre entier (ex: numéro de bloc flash) |
| `RC3` | C de bank 3 | 8-bit | Paramètre entier (ex: flag auto-speedup) |
| `RBC3` | BC de bank 3 | 16-bit | Paramètre 16-bit (ex: nombre de pages flash) |
| `XHL3` | HL de bank 3 | 24-bit | Pointeur source (ex: adresse données) |
| `XDE3` | DE de bank 3 | 24-bit | Pointeur destination / offset |

---

## 4. Table des vecteurs BIOS

Définis dans `ngpc_hw.h` comme `BIOS_*` constants.

| Constante | Valeur | Description | Convention |
|---|---|---|---|
| `BIOS_SHUTDOWN` | 0 | Éteindre la console | SWI 1, ra3=3 |
| `BIOS_CLOCKGEARSET` | 1 | Changer la vitesse CPU | Table 0xFFFE00 |
| `BIOS_RTCGET` | 2 | Lire l'heure/date (BCD) | Table 0xFFFE00 |
| `BIOS_INTLVSET` | 4 | Configurer niveaux interruptions | Table 0xFFFE00 |
| `BIOS_SYSFONTSET` | 5 | Charger la police système en VRAM | SWI 1, ra3=3 |
| `BIOS_FLASHWRITE` | 6 | Écrire en flash | SWI 1 |
| `BIOS_FLASHALLERS` | 7 | Effacer tous les blocs flash | SWI 1 |
| `BIOS_FLASHERS` | 8 | Effacer un bloc flash | SWI 1, ra3=0, rb3=bloc |
| `BIOS_ALARMSET` | 9 | Programmer une alarme (console allumée) | Table 0xFFFE00 |
| `BIOS_ALARMDOWNSET` | 11 | Programmer un réveil (console éteinte) | Table 0xFFFE00 |
| `BIOS_FLASHPROTECT` | 13 | Protéger des blocs flash | Table 0xFFFE00 |
| `BIOS_GEMODESET` | 14 | Switcher mode K1GE/K2GE | Table 0xFFFE00 |

---

## 5. Détail des appels utilisés dans le template

### BIOS_SHUTDOWN (0) — Éteindre
```c
/* ra3=3 = code fonction shutdown */
__asm("ldb ra3, 3");
__asm("ldb rw3, " NGPC_STR(BIOS_SHUTDOWN));
__asm("swi 1");
```

### BIOS_CLOCKGEARSET (1) — Vitesse CPU
```c
/* rb3 = diviseur (0=6MHz, 1=3MHz, 2=1.5MHz, 3=768KHz, 4=384KHz) */
/* rc3 = 0 (pas d'auto-speedup joypad), ou 1 pour activer */
__asm("ld rw3, " NGPC_STR(BIOS_CLOCKGEARSET));
/* charger divider depuis la pile : */
__asm("ld xde, (xsp+4)");
__asm("ld b, e");           /* rb3 = divider */
__asm("ld c, 0");           /* rc3 = 0 */
__asm("ldf 3");
__asm("add w, w"); __asm("add w, w");
__asm("ld xix, 0xfffe00");
__asm("ld xix, (xix+w)");
__asm("call xix");
```

### BIOS_RTCGET (2) — Lire l'horloge
```c
/* xhl3 = pointeur vers NgpcTime (7 octets, BCD) */
__asm(" ld rw3, " NGPC_STR(BIOS_RTCGET));
__asm(" ld xde, (xsp+4)");  /* NgpcTime* depuis pile */
__asm(" ld xhl3, xde");
__asm(" ldf 3");
__asm(" add w, w"); __asm(" add w, w");
__asm(" ld xix, 0xfffe00");
__asm(" ld xix, (xix+w)");
__asm(" call xix");
```

### BIOS_SYSFONTSET (5) — Charger la police
```c
/* Charge les 96 glyphes ASCII (0x20-0x7F) dans tile RAM dès le slot 32 */
__asm("ldb ra3, 3");
__asm("ldb rw3, " NGPC_STR(BIOS_SYSFONTSET));
__asm("swi 1");
```

### BIOS_FLASHERS (8) + BIOS_FLASHWRITE (6) — Sauvegarder
```c
/* Étape 1 : effacer le bloc flash */
/* ra3=0 (base ROM), rb3=numéro du bloc (0x1F pour offset 0x1FA000), rw3=8 */
__asm("ld ra3,0");
__asm("ld rb3," NGPC_STR(SAVE_BLOCK));
__asm("ld rw3," NGPC_STR(BIOS_FLASHERS));
HW_WATCHDOG = WATCHDOG_CLEAR;   /* obligatoire avant opération flash longue */
__asm("swi 1");

/* Étape 2 : écrire 256 octets */
/* ra3=0, rbc3=1 (1*256=256 octets), xhl3=source, xde3=offset destination, rw3=6 */
__asm("ld ra3,0");
__asm("ld rbc3,1");
__asm("ld xhl,(xsp+4)");    /* data* depuis pile */
__asm("ld xhl3,xhl");
__asm("ld xde3," NGPC_STR(SAVE_OFFSET_ASM));
__asm("ld rw3," NGPC_STR(BIOS_FLASHWRITE));
HW_WATCHDOG = WATCHDOG_CLEAR;
__asm("swi 1");
HW_WATCHDOG = WATCHDOG_CLEAR;
```

### BIOS_ALARMSET (9) — Alarme pendant le jeu
```c
/* xiy = pointeur vers NgpcAlarm { u8 day, u8 hour, u8 minute } (BCD) */
__asm(" ld rw3, " NGPC_STR(BIOS_ALARMSET));
__asm(" ld xiy, (xsp+4)");
__asm(" ldf 3");
__asm(" ld h, (xiy +)");  /* day   -> H */
__asm(" ld qc, h");       /* QC = day */
__asm(" ld b, (xiy +)");  /* hour  -> B */
__asm(" ld c, (xiy +)");  /* minute -> C */
__asm(" add w, w"); __asm(" add w, w");
__asm(" ld xix, 0xfffe00");
__asm(" ld xix, (xix+w)");
__asm(" call xix");
```

---

## 6. Valeurs BCD

L'horloge RTC renvoie des valeurs **BCD** (Binary Coded Decimal).
`0x23` = vingt-trois (pas 35).

```c
/* Macros de conversion (ngpc_rtc.h) */
#define BCD_TO_BIN(bcd)  (((bcd) >> 4) * 10 + ((bcd) & 0xF))
#define BIN_TO_BCD(bin)  ((((bin) / 10) << 4) | ((bin) % 10))

/* Exemple */
NgpcTime t;
ngpc_rtc_get(&t);
u8 heure   = BCD_TO_BIN(t.hour);    /* 0x14 -> 14 */
u8 minutes = BCD_TO_BIN(t.minute);  /* 0x30 -> 30 */
```

---

## 7. Watchdog

La console réinitialise le CPU si le watchdog n'est pas alimenté pendant ~100ms.
Le VBL (60 Hz) le nourrit automatiquement via `ngpc_sys.c`.

```c
#define HW_WATCHDOG    (*(volatile u8 *)0x006F)
#define WATCHDOG_CLEAR 0x4E

/* À appeler manuellement avant toute opération longue (flash erase/write) */
HW_WATCHDOG = WATCHDOG_CLEAR;
```

---

## 8. Table des vecteurs d'interruption utilisateur

Les vecteurs sont des pointeurs 32-bit stockés en RAM à `0x6FB8-0x6FFC`.

```c
/* Assigner un handler (ngpc_hw.h) */
HW_INT_VBL  = isr_vblank;   /* OBLIGATOIRE */
HW_INT_TIM0 = isr_hblank;   /* HBlank (pour raster / sprmux) */
HW_INT_DMA0 = isr_dma_done; /* DMA channel 0 completion */
```

Voir la table complète dans [NGPC_HW_REGISTERS.md](NGPC_HW_REGISTERS.md#interruptions).
