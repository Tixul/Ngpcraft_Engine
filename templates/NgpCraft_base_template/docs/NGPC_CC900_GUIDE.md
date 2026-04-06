# Guide cc900 — Compilateur C pour TLCS-900/H

cc900 est le compilateur C de Toshiba pour le CPU TLCS-900/H de la Neo Geo Pocket Color.
Il est **C89 strict** avec des extensions propriétaires. Ce guide liste tous les pièges.

---

## 1. Règles C89 — ce qui est interdit

### Pas de commentaires `//`
```c
/* Correct */
x = 1; /* initialise x */

// INTERDIT — cc900 refuse les commentaires C++
```

### Déclarations en début de bloc uniquement
```c
/* Correct */
void foo(void) {
    u8 i;
    u8 j;
    i = 0;
    j = 1;
}

/* INTERDIT — déclaration après une instruction */
void foo(void) {
    i = 0;
    u8 j = 1;  /* erreur de compilation */
}
```

### Pas de déclaration dans le `for`
```c
/* Correct */
u8 i;
for (i = 0; i < 10; i++) { ... }

/* INTERDIT — C99 */
for (u8 i = 0; i < 10; i++) { ... }
```

### Pas de `long long`, pas de `double`
```c
/* Types disponibles (définis dans ngpc_types.h) */
u8   /* unsigned char  — 1 octet */
s8   /* signed char    — 1 octet */
u16  /* unsigned int   — 2 octets */
s16  /* signed int     — 2 octets */
u32  /* unsigned long  — 4 octets */
s32  /* signed long    — 4 octets */

/* INTERDIT */
long long x;   /* pas de 64-bit */
double y;      /* pas de FPU */
float z;       /* pas de FPU */
```

**Important :** sur cc900, `unsigned long` = 32 bits, `unsigned int` = 16 bits.

---

## 2. Far pointers — règle critique

### Pourquoi

cc900 utilise des pointeurs **16-bit (near) par défaut**. La RAM est à `0x004000-0x005FFF`
(portée near). La ROM cartouche commence à `0x200000` — hors portée near.

Sans `NGP_FAR`, le compilateur génère une adresse 16-bit tronquée → lecture depuis une
adresse fausse → données corrompues, crash, ou image décalée.

### La macro NGP_FAR

```c
/* ngpc_types.h */
#define NGP_FAR  __far
```

### Quand l'utiliser

**TOUJOURS** pour les pointeurs vers données en ROM (tiles, palettes, maps, sons, textes).

```c
/* CORRECT — données tiles en ROM */
void ngpc_gfx_load_tiles_at(const u16 NGP_FAR *tiles, u16 count, u16 offset);

/* INTERDIT — compile mais lit la mauvaise adresse */
void ngpc_gfx_load_tiles_at(const u16 *tiles, u16 count, u16 offset);
```

### Pointeurs near acceptables

Les pointeurs vers la RAM (variables locales, tableaux statiques, structs de jeu)
**n'ont pas besoin** de `NGP_FAR` — ils sont dans la portée 16-bit.

```c
static u8 s_buffer[256];      /* RAM statique : near OK */
NgpcRect *rect;               /* pointeur vers struct RAM : near OK */
const u16 NGP_FAR *tiles;     /* données ROM : NGP_FAR obligatoire */
```

### Extension automatique

Quand cc900 passe un pointeur near vers une fonction attendant `NGP_FAR`, il
**zero-étend** le pointeur 16-bit en 24-bit. Pour la RAM (base `0x004000`), cela
donne `0x004000` en 24-bit — correct. Pour la ROM (`0x200000`), un near pointer
ne peut pas encoder cette adresse du tout.

### Solution de secours — macros VRAM brut

Si un affichage reste corrompu malgré `NGP_FAR` correct (ou pour diagnostiquer),
utiliser `src/gfx/ngpc_tilemap_blit.h` :

```c
/* Écriture directe sans passer de pointeur en paramètre */
NGP_TILEMAP_BLIT_SCR1(prefix, tile_base)
NGP_TILEMAP_BLIT_SCR2(prefix, tile_base)
```

Ces macros indexent directement les symboles générés dans l'unité de compilation —
il n'y a pas de pointeur passé en paramètre, donc pas de problème near/far possible.

**Recommandation pratique :**
1. Projet normal → utiliser les helpers (`ngpc_gfx_load_tiles_at()` etc.)
2. Rendu corrompu inexplicable → basculer sur `NGP_TILEMAP_BLIT_*` pour débloquer
3. Tout nouveau helper lisant des `const` ROM → annoter les paramètres avec `NGP_FAR`

Voir [NGPC_GRAPHICS_GUIDE.md](NGPC_GRAPHICS_GUIDE.md) pour les exemples complets.

---

## 3. Mot-clé `volatile`

Obligatoire pour tous les accès registres hardware et les variables modifiées par ISR.

```c
/* Registres hardware : toujours volatile (défini dans ngpc_hw.h) */
#define HW_RAS_V  (*(volatile u8 *)0x8009)

/* Variables modifiées par ISR : volatile */
volatile u8 g_vb_counter;   /* incrémenté dans isr_vblank */

/* Compteur DMA : volatile car modifié par hardware */
static volatile u8 s_done_flag[4];
```

Sans `volatile`, le compilateur peut mettre la valeur en cache dans un registre CPU
et ne jamais relire la mémoire → la boucle d'attente ne se termine jamais.

---

## 4. Fonctions interrupt

Keyword `__interrupt` pour les handlers d'interruption. cc900 génère automatiquement
le prologue/épilogue RETI (return from interrupt).

```c
static void __interrupt isr_vblank(void)
{
    HW_WATCHDOG = WATCHDOG_CLEAR;
    g_vb_counter++;
}

/* Installation du vecteur */
HW_INT_VBL = isr_vblank;
```

**Règles pour les ISR :**
- Aussi courtes que possible (budget serré, surtout HBlank = ~5 µs)
- Ne jamais appeler `ngpc_vsync()` depuis une ISR (deadlock)
- Accès aux variables partagées : déclarer `volatile`

---

## 5. Inline assembly

Syntaxe : `__asm("instruction");` — une instruction par appel.

```c
/* Activer les interruptions */
__asm("ei");

/* Désactiver */
__asm("di");

/* Appel BIOS (voir NGPC_BIOS_REF.md) */
__asm("swi 1");
```

### Stringifier une constante C dans l'ASM

Les constantes C ne sont pas directement accessibles en inline asm.
Utiliser `NGPC_STR(x)` (défini dans `ngpc_hw.h`) :

```c
#define BIOS_SHUTDOWN  0
#define NGPC_STR(x) #x

__asm("ldb rw3, " NGPC_STR(BIOS_SHUTDOWN));
/* génère : ldb rw3, 0 */
```

### Convention de pile pour lire les arguments

Dans une fonction avec `(void)arg` (suppression du warning), l'argument est
accessible à `(xsp+4)` pour le premier, `(xsp+8)` pour le second :

```c
void my_func(const u8 NGP_FAR *ptr, u16 count)
{
    (void)ptr;    /* supprime warning "unused" */
    (void)count;
    __asm("ld xwa,(xsp+4)");  /* xwa = ptr (24-bit far) */
    __asm("ld wa,(xsp+8)");   /* wa  = count (16-bit)   */
    /* ... */
}
```

---

## 6. Modèle mémoire et sections

| Zone | Adresse | Taille | Usage |
|---|---|---|---|
| RAM principale | `0x004000-0x005FFF` | 8 KB | Variables C, pile, BSS |
| RAM battery | `0x006000-0x006BFF` | 3 KB | Peut servir à la sauvegarde |
| Z80 RAM | `0x007000-0x007FFF` | 4 KB | Driver son, partagée |
| ROM cartouche | `0x200000-0x3FFFFF` | 2 MB | Code + assets (near interdit) |

Le linker script (`ngpc.lcf`) définit les sections. Le bootstrap `runtime_bootstrap()`
(dans `ngpc_sys.c`) copie les données initialisées ROM→RAM et zéro le BSS au démarrage.

**Symbols linker utiles :**
```c
extern const u8 _DataROM_START;  /* début des données init en ROM */
extern const u8 _DataROM_END;
extern u8 _DataRAM_START;        /* destination RAM */
extern u8 _Bss_START;            /* début BSS */
extern u8 _Bss_END;
```

---

## 7. Récapitulatif des pièges fréquents

| Symptôme | Cause probable | Fix |
|---|---|---|
| Image corrompue / décalée | Pointeur ROM sans NGP_FAR | Ajouter NGP_FAR sur le paramètre |
| Boucle d'attente infinie | Variable ISR non `volatile` | Ajouter `volatile` |
| Erreur de compilation C89 | `//` ou déclaration tardive | Corriger selon §1 |
| Crash ou comportement aléatoire | POOL_EACH avec `for (u8 i=0;...)` | Déclarer `u8 i;` avant le for |
| Valeurs incorrectes lues | `unsigned long` supposé 32-bit | Vérifier : sur cc900 `u32 = unsigned long` |
| Assertion fausse sur taille struct | Padding inattendu | Utiliser `u8 _pad` si alignement nécessaire |
