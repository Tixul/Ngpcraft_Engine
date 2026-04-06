#ifndef NGPC_MOTION_H
#define NGPC_MOTION_H

/*
 * ngpc_motion -- Buffer d'inputs et détection de patterns (fighting-game style)
 * =============================================================================
 * Enregistre l'état du pad chaque frame dans un buffer circulaire 32 frames.
 * Détecte des séquences de directions/boutons (quarter-circle, double-tap, etc.)
 * avec une fenêtre temporelle configurable par pattern.
 *
 * Format d'un frame dans le buffer : (dir << 4) | btn_pressed
 *   - dir    : nibble haut — direction D-pad (MDIR_*)
 *   - btn    : nibble bas  — boutons pressés ce frame uniquement (rising edge, MBTN_*)
 *
 * Dépendances : ngpc_hw.h (u8, NGP_FAR)
 *   ngpc_pad_held    : variable core — état D-pad ce frame
 *   ngpc_pad_pressed : variable core — fronts montants ce frame (rising edge)
 *
 * Usage :
 *   Copier ngpc_motion/ dans src/
 *   OBJS += src/ngpc_motion/ngpc_motion.rel
 *   #include "ngpc_motion/ngpc_motion.h"
 *
 * Exemple (quarter-circle avant + A) :
 *   static const u8 qcf_steps[] = { MDIR_D, MDIR_DR, MDIR_R|MBTN_A };
 *   static const NgpcMotionPattern QCF_A = { qcf_steps, 3, 20 };
 *
 *   // Chaque frame :
 *   ngpc_motion_push(&buf, ngpc_pad_held, ngpc_pad_pressed);
 *   if (ngpc_motion_test(&buf, &QCF_A)) { fire_hadouken(); }
 */

#include "ngpc_hw.h"   /* u8, NGP_FAR */

/* ── Constantes ─────────────────────────────────────────────────────── */

#define NGPC_MOTION_BUF_SIZE    32   /* taille buffer (puissance de 2) */
#define NGPC_MOTION_FINAL_WINDOW 4   /* fenêtre max (frames) pour le dernier step */

/* Directions D-pad — nibble haut (bits 7..4) */
#define MDIR_N    0x00   /* neutre */
#define MDIR_U    0x10   /* haut */
#define MDIR_D    0x20   /* bas */
#define MDIR_L    0x30   /* gauche */
#define MDIR_R    0x40   /* droite */
#define MDIR_UR   0x50   /* haut-droite */
#define MDIR_UL   0x60   /* haut-gauche */
#define MDIR_DR   0x70   /* bas-droite */
#define MDIR_DL   0x80   /* bas-gauche */
#define MDIR_ANY  0xF0   /* wildcard — toute direction acceptée */

/* Boutons — nibble bas (bits 3..0) — combinaisons possibles */
#define MBTN_NONE 0x00
#define MBTN_A    0x01
#define MBTN_B    0x02
#define MBTN_OPT  0x04

/* Masques */
#define MDIR_MASK 0xF0
#define MBTN_MASK 0x0F

/* ── Structures ──────────────────────────────────────────────────────── */

/*
 * NgpcMotionPattern — pattern décrit en ROM (lire avec pointeur far)
 *   steps : tableau d'octets (dir|btn), du plus ancien au plus récent
 *   count : nombre de steps (max recommandé : 8)
 *   window: fenêtre totale en frames pour que tout le pattern soit valide
 *           (0 = utiliser NGPC_MOTION_BUF_SIZE par défaut)
 */
typedef struct {
    const u8 NGP_FAR *steps;  /* tableau en ROM */
    u8 count;
    u8 window;
} NgpcMotionPattern;

/*
 * NgpcMotionBuf — buffer circulaire par entité (RAM)
 *   34 octets RAM total.
 */
typedef struct {
    u8 frames[NGPC_MOTION_BUF_SIZE];  /* (dir<<4)|btn — index 0..31 */
    u8 head;                           /* index du frame le plus récent */
    u8 count;                          /* frames valides (0..NGPC_MOTION_BUF_SIZE) */
} NgpcMotionBuf;

/* ── API ─────────────────────────────────────────────────────────────── */

/* Initialise le buffer (met tout à zéro). */
void ngpc_motion_init(NgpcMotionBuf *buf);

/* Enregistre le frame courant dans le buffer.
 *   pad_held    : état D-pad (ngpc_pad_held)
 *   pad_pressed : boutons pressés ce frame uniquement (ngpc_pad_pressed) */
void ngpc_motion_push(NgpcMotionBuf *buf, u8 pad_held, u8 pad_pressed);

/* Teste un pattern unique contre le buffer.
 * Retourne 1 si le pattern est détecté, 0 sinon.
 * Algorithme : dernier step dans NGPC_MOTION_FINAL_WINDOW frames depuis head,
 * steps précédents trouvés en remontant (frames neutres ignorées). */
u8 ngpc_motion_test(const NgpcMotionBuf *buf,
                    const NgpcMotionPattern NGP_FAR *pat);

/* Teste un tableau de patterns, retourne l'index du premier trouvé (0..count-1)
 * ou 0xFF si aucun. Utile pour gérer plusieurs coups spéciaux. */
u8 ngpc_motion_scan(const NgpcMotionBuf *buf,
                    const NgpcMotionPattern NGP_FAR *pats, u8 count);

/* Vide le buffer (après avoir déclenché une action pour éviter re-trigger). */
void ngpc_motion_clear(NgpcMotionBuf *buf);

#endif /* NGPC_MOTION_H */
