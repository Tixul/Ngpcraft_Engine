"""
ui/tabs/help_tab.py - Help tab (two-panel: topic list + QTextBrowser).

Structure matches NGPC Sound Creator:
  Left  : QListWidget (220 px fixed) — topic list, bilingual labels
  Right : QTextBrowser — HTML content with dark CSS
  Bottom: language toggle buttons (FR / EN)

Topic content is embedded as Python functions (no external files).
"""

from __future__ import annotations

import platform
import sys
import urllib.parse

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n.lang import current_language, save_to_settings, set_language


# ---------------------------------------------------------------------------
# CSS — dark theme matching Sound Creator
# ---------------------------------------------------------------------------

_LIST_CSS = """
QListWidget {
    background: #1e1e28;
    color: #ccccdd;
    font-size: 13px;
    border-right: 1px solid #333;
}
QListWidget::item { padding: 8px 12px; }
QListWidget::item:selected { background: #3a3a55; color: white; }
"""

_BROWSER_CSS = """
QTextBrowser {
    background: #22222e;
    color: #dddddd;
    font-size: 13px;
    padding: 16px;
    border: none;
}
h1 { color: #88aaff; font-size: 20px; }
h2 { color: #aaccff; font-size: 16px; margin-top: 18px; }
h3 { color: #ccddff; font-size: 14px; margin-top: 12px; }
code { background: #2a2a3a; color: #ffcc66; padding: 2px 4px; }
pre  { background: #1a1a26; color: #cccccc; padding: 8px; }
table { border-collapse: collapse; margin: 8px 0; }
td, th { border: 1px solid #444; padding: 4px 8px; }
th { background: #2a2a3a; color: #aabbdd; }
"""

# ---------------------------------------------------------------------------
# Topic list (bilingual labels)
# ---------------------------------------------------------------------------

_TOPICS_FR = [
    "Bienvenue",
    "Contraintes NGPC",
    "Éditeur de palette",
    "Quantization RGB444",
    "Couches (Layers)",
    "Assistant Remap",
    "Onglet Projet",
    "Onglet Globals",
    "VRAM Map",
    "Bundle (packer de scène)",
    "Tilemap Preview",
    "Pipeline export",
    "Éditeur (retouche)",
    "Mode Mono / K1GE",
    "Éditeur Hitbox",
    "Éditeur de niveau",
    "Triggers & Régions",
    "Banque de dialogues",
    "Scene Map",
    "Templates de projet",
    "Physique & IA ennemis",
    "Top-Down vs Plateforme",
    "Banque Palettes VRAM",
    "Génération procédurale",
    "Dépannage",
]

_TOPICS_EN = [
    "Welcome",
    "NGPC Constraints",
    "Palette Editor",
    "RGB444 Quantization",
    "Layers",
    "Remap Wizard",
    "Project Tab",
    "Globals Tab",
    "VRAM Map",
    "Bundle (scene packer)",
    "Tilemap Preview",
    "Export Pipeline",
    "Editor (retouch)",
    "Mono / K1GE Mode",
    "Hitbox Editor",
    "Level Editor",
    "Triggers & Regions",
    "Dialogue Bank",
    "Scene Map",
    "Project Templates",
    "Physics & Enemy AI",
    "Top-Down vs Platformer",
    "VRAM Palette Bank",
    "Procedural Generation",
    "Troubleshooting",
]

# ---------------------------------------------------------------------------
# HTML content — French
# ---------------------------------------------------------------------------

def _fr_welcome() -> str:
    return """
<h1>Bienvenue dans NgpCraft Engine</h1>
<p>NgpCraft Engine est un outil graphique pour le workflow d'assets du
<b>Neo Geo Pocket Color</b>. Il comble l'espace entre votre logiciel de
dessin (Aseprite) et le pipeline C (ngpc_sprite_export.py, ngpc_tilemap.py).</p>

<h2>À quoi ça sert ?</h2>
<ul>
  <li>Visualiser <b>en temps réel</b> ce que le hardware NGPC affichera
      (couleurs quantizées en RGB444).</li>
  <li>Éditer la palette d'un sprite et voir le résultat immédiatement.</li>
  <li>Détecter et corriger les sprites qui dépassent les limites hardware.</li>
  <li>Importer rapidement beaucoup de sprites : multi-sélection, drag &amp; drop, import dossier.</li>
  <li>Générer les arguments <code>--fixed-palette</code> pour partager une
      palette entre plusieurs sprites.</li>
  <li>Exporter par scène (sprites + tilemaps) et générer un <b>report HTML</b>.</li>
  <li>Découper automatiquement un sprite multi-couleurs en couches superposées.</li>
</ul>

<h2>Groupes d'onglets</h2>
<p>Les onglets sont organisés en <b>quatre groupes</b> sélectionnables via la barre de boutons en haut :</p>
<table>
  <tr><th>Groupe</th><th>Onglets</th><th>Usage</th></tr>
  <tr><td><b>Projet</b></td><td>Projet · Globals</td><td>Gestion du projet et des assets globaux</td></tr>
  <tr><td><b>Scène</b></td><td>Level · Palette · Tilemap · Dialogues · Sprite Setup</td><td>Édition de la scène active</td></tr>
  <tr><td><b>Outils</b></td><td>Éditeur · VRAM Map · Bundle</td><td>Retouche pixel, budget VRAM, export batch</td></tr>
  <tr><td><b>Aide</b></td><td>Aide</td><td>Documentation en ligne</td></tr>
</table>
<p>Le groupe actif est mémorisé entre les sessions. Le dernier onglet actif dans chaque groupe est aussi restauré.</p>

<h2>Navigation globale</h2>
<table>
<tr><th>Touche</th><th>Action</th></tr>
<tr><td><b>Ctrl+Tab</b></td><td>Onglet suivant (dans le groupe actif)</td></tr>
<tr><td><b>Ctrl+Shift+Tab</b></td><td>Onglet précédent (dans le groupe actif)</td></tr>
</table>

<h2>Les onglets</h2>
<table>
  <tr><th>Onglet</th><th>Groupe</th><th>Rôle</th></tr>
  <tr><td><b>Projet</b></td><td>Projet</td><td>Vue d'ensemble des assets par scène, budget VRAM, export C</td></tr>
  <tr><td><b>Globals</b></td><td>Projet</td><td>Variables globales, manifest audio, entités globales</td></tr>
  <tr><td><b>Level</b></td><td>Scène</td><td>Éditeur de niveau : entités, vagues, régions, triggers, procgen</td></tr>
  <tr><td><b>Palette</b></td><td>Scène</td><td>Éditeur de palette RGB444 en temps réel, fixed-palette</td></tr>
  <tr><td><b>Tilemap</b></td><td>Scène</td><td>Preview ngpc_tilemap.py avant export</td></tr>
  <tr><td><b>Dialogues</b></td><td>Scène</td><td>Banque de dialogues par scène → <code>scene_*_dialogs.h</code></td></tr>
  <tr><td><b>Sprite Setup</b></td><td>Scène</td><td>Éditeur AABB par frame + props physiques/combat → export C</td></tr>
  <tr><td><b>Éditeur</b></td><td>Outils</td><td>Retouche pixel rapide (pencil/fill/undo)</td></tr>
  <tr><td><b>VRAM Map</b></td><td>Outils</td><td>Carte graphique des 512 tiles et 16 palettes sprites</td></tr>
  <tr><td><b>Bundle</b></td><td>Outils</td><td>Export batch avec budget tile/palette automatique</td></tr>
  <tr><td><b>Aide</b></td><td>Aide</td><td>Ce panneau</td></tr>
</table>

<h2>Démarrage rapide — assets seulement</h2>
<ol>
  <li>Groupe <b>Scène</b> → onglet <b>Palette</b>.</li>
  <li>Glissez un PNG ou cliquez <i>Ouvrir…</i></li>
  <li>Observez l'aperçu HW (RGB444) et la palette détectée.</li>
  <li>Cliquez un swatch pour modifier une couleur.</li>
  <li>Sauvegardez ou copiez <code>--fixed-palette</code>.</li>
</ol>

<h2>Démarrage rapide — développement jeu</h2>
<ol>
  <li>Groupe <b>Projet</b> → onglet <b>Projet</b> : créez une scène, ajoutez vos sprites et tilemaps.</li>
  <li>Groupe <b>Scène</b> → onglet <b>Sprite Setup</b> : définissez les AABB et props physiques.</li>
  <li>Groupe <b>Scène</b> → onglet <b>Level</b> : placez les entités, créez vagues, régions et triggers.</li>
  <li>Groupe <b>Projet</b> → onglet <b>Projet → Export</b> : générez <code>_scene.h</code> et incluez-le dans votre jeu C.</li>
</ol>

<h2>Sauvegarde automatique</h2>
<p>NgpCraft Engine <b>sauvegarde automatiquement</b> le projet (<code>.ngpcraft</code>) après
<b>chaque action</b> : ajout de sprite, modification de scène, placement d'entité, réglage
de trigger… Il n'y a <b>aucun bouton "Enregistrer"</b> à ne pas oublier.</p>
<p>Un indicateur <span style="color:#66bb66"><b>✓ Saved</b></span> s'affiche brièvement
dans la barre de statut en bas de la fenêtre pour confirmer chaque écriture.</p>

<h2>Où lire la documentation ?</h2>
<ul>
  <li><code>README.md</code> : démarrage rapide, workflow recommandé, mode GUI et headless.</li>
  <li><code>PROJET.md</code> : roadmap, architecture, historique des évolutions et décisions.</li>
  <li><code>API_REFERENCE.md</code> : référence code par module, fonctions publiques et types exposés.</li>
  <li><b>Aide</b> : rappel intégré dans l'application, orienté workflow et usage tab par tab.</li>
</ul>
"""


def _fr_constraints() -> str:
    return """
<h1>Contraintes matérielles NGPC</h1>
<p>Le Neo Geo Pocket Color impose des limites strictes sur les graphismes.
Les connaître est indispensable pour éviter des surprises à la compilation.</p>

<h2>Couleurs</h2>
<p>Le NGPC utilise le format <b>RGB444</b> : 4 bits par canal (R, G, B).
Chaque canal peut prendre 16 valeurs (0 à 15), soit <b>4096 couleurs au total</b>.<br>
Les couleurs 8 bits de vos PNG sont <i>arrondies</i> à la valeur RGB444 la plus proche
au moment de l'export.</p>

<h2>Contrainte fondamentale : 3 couleurs opaques par tile 8×8</h2>
<p>C'est la règle centrale du NGPC, valable pour <b>sprites ET tilemaps</b> :<br>
chaque tile 8×8 utilise un seul slot palette, qui contient 4 entrées dont l'index 0
est transparent. Il reste donc <b>3 couleurs opaques maximum</b> par tile 8×8.</p>
<ul>
  <li><b>Sprites</b> : si un personnage a 6 couleurs, certaines de ses tiles 8×8
      contiennent des pixels des deux groupes → dépassement → il faut <b>2 couches</b>
      (2 sprites superposés, chacun 3 couleurs). Sonic sur NGPC, votre vaisseau :
      même principe.</li>
  <li><b>Tilemaps</b> : chaque tile peut avoir sa propre palette, mais une tile
      individuelle ne peut toujours pas dépasser 3 couleurs opaques.</li>
</ul>

<h2>Sprites — ressources VRAM</h2>
<table>
  <tr><th>Limite</th><th>Valeur</th><th>Remarque</th></tr>
  <tr><td>Slots palette sprites</td><td>16</td><td>Partagés entre tous les sprites</td></tr>
  <tr><td>Couleurs par palette</td><td>4</td><td>Index 0 = toujours transparent</td></tr>
  <tr><td>Couleurs opaques max par palette</td><td>3</td><td>Par sprite / par couche</td></tr>
  <tr><td>Tile slots VRAM</td><td>512</td><td>0-31 réservés, 32-127 police système</td></tr>
  <tr><td>Sprites HW simultanés</td><td>64</td><td>Slots 0-63</td></tr>
</table>

<h2>Tilemaps (scroll planes SCR1/SCR2)</h2>
<table>
  <tr><th>Limite</th><th>Valeur</th></tr>
  <tr><td>Couleurs par tile 8×8</td><td>3 opaques max (même règle)</td></tr>
  <tr><td>Taille carte</td><td>32×32 tiles</td></tr>
  <tr><td>Résolution écran</td><td>160×152 px (20×19 tiles)</td></tr>
</table>

<h2>Implications pratiques</h2>
<ul>
  <li>Un sprite avec <b>4-6 couleurs</b> doit être découpé en <b>2 couches</b>
      (deux sprites superposés, chacun avec 3 couleurs).</li>
  <li>Un sprite avec <b>7-9 couleurs</b> nécessite <b>3 couches</b>
      (rare et coûteux en slots hardware).</li>
  <li>Chaque couche supplémentaire consomme 1 palette slot et N tile slots.</li>
  <li>La transparence (index 0) de la couche supérieure laisse apparaître
      la couche inférieure — c'est ainsi que la superposition fonctionne.</li>
</ul>
"""


def _fr_palette_editor() -> str:
    return """
<h1>Éditeur de palette</h1>

<h2>Ouvrir un fichier</h2> 
<p>Cliquez <b>Ouvrir…</b> ou glissez un fichier PNG directement sur l'onglet. 
Les formats BMP et GIF sont également acceptés.</p> 
<p><b>Auto-reload</b> : si le PNG est modifié sur disque, l'onglet peut le recharger automatiquement 
(utile avec Aseprite). Si vous avez déjà modifié des couleurs dans l'outil, une confirmation 
est demandée pour éviter de perdre vos changements.</p> 
<p><b>Interface</b> : la tête de l’onglet est maintenant regroupée en blocs <b>Fichier</b> et <b>Vue</b>, pour rester cohérente avec l’onglet <b>Tilemap</b>.</p>
 
<h2>Aperçus</h2> 
<p>Deux aperçus sont affichés côte à côte :</p>
<ul>
  <li><b>Original</b> — image telle qu'elle est sur disque (composite sur damier
      pour visualiser la transparence).</li>
  <li><b>Aperçu HW (RGB444)</b> — image avec toutes les couleurs opaques arrondies
      à la grille RGB444. C'est ce que le hardware affichera.</li>
</ul>

<h2>Zoom</h2> 
<p>Les boutons <code>×1 ×2 ×4 ×8</code> zooment les deux aperçus en 
<b>nearest-neighbor</b> (pas de flou) pour voir les pixels individuels.</p> 

<h2>Prévisualisation anim</h2>
<p>Le bloc <b>Prévisualisation anim</b> permet de vérifier une spritesheet animée :</p>
<ul>
  <li>Réglez <code>frame_w</code>, <code>frame_h</code> et <code>frame_count</code> (lecture en grille, row-major).</li>
  <li><b>Auto</b> essaie de deviner une config (strip vertical/horizontal).</li>
  <li>Utilisez <b>Play/Pause</b> pour lancer l’animation et le champ <b>ms</b> pour la vitesse.</li>
  <li>L’export <b>.c sprite</b> utilise ces valeurs (inclut <code>--frame-count</code>).</li>
  <li><b>Appliquer à la scène</b> : met à jour le sprite de la scène active avec ces valeurs.</li>
</ul>
<p>Si le fichier fait partie de la scène active (onglet Projet), la config anim est
pré-remplie automatiquement depuis la scène.</p>

<h2>Overlay tiles</h2>
<p>Quand la case <i>Overlay tiles</i> est cochée, une grille semi-transparente
est superposée sur l'aperçu HW. La contrainte est la même pour <b>sprites et tilemaps</b> :
chaque tile 8×8 ne peut utiliser qu'un seul slot palette = 3 couleurs opaques max.</p>
<ul>
  <li><span style="color:#00cc00">■ Vert</span> — tile ≤ 3 couleurs opaques : rendu direct possible.</li>
  <li><span style="color:#cc0000">■ Rouge</span> — tile &gt; 3 couleurs opaques : nécessite une découpe en couches (sprites) ou une réduction de couleurs (tilemaps).</li>
</ul>

<h2>Éditer une couleur</h2>
<ol>
  <li>Cliquez sur un <b>swatch</b> dans le panneau palette.</li>
  <li>Le sélecteur de couleur s'ouvre.</li>
  <li>Choisissez une couleur — elle est <b>automatiquement arrondie</b> à
      la valeur RGB444 la plus proche.</li>
  <li>Tous les pixels de cette couleur sont remappés en temps réel dans les aperçus.</li>
</ol>
<p><b>Note :</b> la couleur 0 (transparente, affichée en damier) ne peut pas être modifiée.</p>

<h2>Sauvegarder</h2>
<p><b>Sauvegarder PNG…</b> enregistre l'image <i>remappée</i> (version HW RGB444)
avec la nouvelle palette. L'image originale n'est pas écrasée tant que vous ne
sauvegardez pas sur le même fichier.</p>

<h2>Copier --fixed-palette</h2>
<p>Ce bouton place dans le presse-papier la chaîne :</p>
<pre>--fixed-palette 0x0000,0x025B,0x074A,0x0FFF</pre>
<p>Prête à être passée à <code>ngpc_sprite_export.py</code> ou
<code>ngpc_sprite_bundle.py</code> pour forcer cette palette exacte sur
un autre sprite (partage de palette entre sprites).</p>

<h2>Palettes de la scène (édition partagée)</h2>
<p>En <b>mode projet</b>, un bloc <b>Palettes de la scène</b> liste les palettes partagées
utilisées par la scène active (celles déclarées via <code>fixed_palette</code>).</p>
<ul>
  <li>Sélectionnez une palette dans la liste : ses 4 slots (0=transparent) s’affichent.</li>
  <li>Modifiez les couleurs (snap RGB444), puis cliquez <b>Appliquer</b>.</li>
  <li>L’outil remappe les pixels et met à jour <code>fixed_palette</code> pour tous les sprites liés.</li>
</ul>
"""


def _fr_rgb444() -> str:
    return """
<h1>Quantization RGB444</h1>

<h2>Principe</h2>
<p>Le NGPC stocke chaque couleur sur <b>12 bits</b> : 4 bits pour R, G et B.
Un pixel 8 bits (R8, G8, B8) est arrondi en tronquant les 4 bits de poids faible :</p>
<pre>r4 = R8 >> 4        (0..15)
g4 = G8 >> 4
b4 = B8 >> 4

r8_display = r4 * 17   (0, 17, 34, … 255)
g8_display = g4 * 17
b8_display = b4 * 17</pre>

<h2>Encodage NGPC (mot u16)</h2>
<pre>word = r4 | (g4 &lt;&lt; 4) | (b4 &lt;&lt; 8)</pre>
<table>
  <tr><th>R8</th><th>G8</th><th>B8</th><th>r4</th><th>g4</th><th>b4</th><th>Word</th><th>Affiché</th></tr>
  <tr><td>255</td><td>255</td><td>255</td><td>15</td><td>15</td><td>15</td><td>0x0FFF</td><td>blanc pur</td></tr>
  <tr><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0x0000</td><td>noir / transparent</td></tr>
  <tr><td>85</td><td>34</td><td>17</td><td>5</td><td>2</td><td>1</td><td>0x0125</td><td>brun sombre</td></tr>
  <tr><td>170</td><td>68</td><td>119</td><td>10</td><td>4</td><td>7</td><td>0x074A</td><td>violet</td></tr>
</table>

<h2>Effet visible</h2>
<p>La troncature peut provoquer des <b>bandes de couleur</b> sur des dégradés fins.
Travailler directement avec une palette RGB444 dans Aseprite (via l'extension Lua fournie
dans le template) évite les surprises.</p>

<h2>Transparence</h2>
<p>Le mot <code>0x0000</code> (noir absolu) est réservé à la <b>couleur transparente</b>
(index 0 de la palette). Évitez le noir pur comme couleur visible — utilisez
<code>0x0111</code> (très sombre) à la place.</p>
"""


def _fr_layers() -> str:
    return """
<h1>Couches (Layers)</h1>

<h2>Pourquoi des couches ?</h2>
<p>Une palette sprite NGPC contient <b>4 entrées</b>, dont l'index 0 est transparent.
Il reste donc <b>3 couleurs opaques</b> par sprite.<br>
Pour un personnage avec 6 couleurs, il faut <b>2 sprites superposés</b>
(couche A + couche B), chacun avec sa propre palette de 3 couleurs.</p>

<h2>Algorithme de découpe</h2>
<ol>
  <li>Tous les pixels opaques sont collectés et leurs couleurs RGB444 comptées.</li>
  <li>Les couleurs sont triées par <b>fréquence décroissante</b>
      (les plus utilisées en premier).</li>
  <li><b>Couche 0 (A)</b> = les 3 couleurs les plus fréquentes.</li>
  <li><b>Couche 1 (B)</b> = les 3 couleurs suivantes.</li>
  <li><b>Couche 2 (C)</b> = les 3 couleurs suivantes, etc.</li>
  <li>Chaque pixel est routé vers la couche qui contient sa couleur.</li>
</ol>

<h2>Nombre de couches recommandé</h2>
<table>
  <tr><th>Couleurs opaques</th><th>Couches</th><th>Palettes consommées</th><th>Slots HW</th></tr>
  <tr><td>1 – 3</td><td>1</td><td>1</td><td>N</td></tr>
  <tr><td>4 – 6</td><td>2</td><td>2</td><td>2N</td></tr>
  <tr><td>7 – 9</td><td>3</td><td>3</td><td>3N ⚠</td></tr>
  <tr><td>&gt; 9</td><td>≥ 4</td><td>≥ 4</td><td>très élevé ✗</td></tr>
</table>

<h2>Rendu en jeu</h2>
<p>Les deux (ou trois) couches sont dessinées <b>aux mêmes coordonnées</b>.
La transparence de la couche supérieure laisse apparaître les couleurs de la couche
inférieure. Le résultat visuel : 6 (ou 9) couleurs pour le joueur.</p>
<pre>// Exemple C — deux couches pour un sprite 16x16
ngpc_sprite_set(SPR_PLAYER_A, x, y, player_a_tile, player_a_pal, SPR_FRONT);
ngpc_sprite_set(SPR_PLAYER_B, x, y, player_b_tile, player_b_pal, SPR_FRONT);</pre>

<h2>Utiliser la découpe dans NgpCraft Engine</h2>
<ol>
  <li>Ouvrez votre sprite dans l'onglet <b>Palette</b>.</li>
  <li>Si le sprite dépasse 3 couleurs, un message de suggestion apparaît.</li>
  <li>Cliquez <b>Découper en N couches…</b></li>
  <li>Le dialogue affiche chaque couche avec son aperçu et son argument
      <code>--fixed-palette</code>.</li>
  <li>Sauvegardez chaque couche en PNG séparé.</li>
  <li>Exportez chaque couche avec <code>ngpc_sprite_export.py</code>
      en utilisant l'argument <code>--fixed-palette</code> copié.</li>
</ol>
"""


def _fr_remap() -> str:
    return """
<h1>Assistant Remap couleur-par-couleur</h1>

<h2>À quoi ça sert ?</h2>
<p>Pour que deux sprites partagent le même slot palette (<code>--fixed-palette</code>),
leurs couleurs doivent correspondre exactement. Quand elles sont <em>proches mais pas
identiques</em> (ex : deux ennemis similaires avec des variantes de teinte),
l'assistant de remap vous guide pour aligner les couleurs de l'un sur l'autre,
couleur par couleur.</p>

<h2>Lancer l'assistant</h2>
<ol>
  <li>Ouvrez le sprite source dans l'onglet <b>Palette</b>.</li>
  <li>Cliquez le bouton <b>Remap colors…</b> dans le panneau <i>Export individuel</i>.</li>
  <li>Dans la fenêtre, cliquez <b>Choisir…</b> pour sélectionner le sprite cible
      (le "donneur de palette").</li>
</ol>

<h2>Étapes de remap</h2>
<p>Pour chaque couleur opaque du sprite source :</p>
<ul>
  <li>L'aperçu gauche montre le sprite source avec la couleur courante <b>en surbrillance</b>
      (les autres pixels sont assombris).</li>
  <li>La liste de droite propose les couleurs disponibles dans le sprite cible.</li>
  <li>Sélectionnez la couleur cible correspondante, ou cliquez <b>← Passer (garder)</b>
      pour conserver la couleur originale.</li>
  <li>Naviguez avec <b>Suivant →</b> et <b>← Précédent</b>.</li>
</ul>

<h2>Aperçu et sauvegarde</h2>
<p>Après la dernière couleur, un aperçu côte à côte apparaît :</p>
<ul>
  <li><b>Source (remappée)</b> — le résultat du remap.</li>
  <li><b>Cible (référence)</b> — le sprite donneur.</li>
</ul>
<p>Cliquez <b>Appliquer et sauvegarder PNG…</b> pour enregistrer le sprite remappé.
Le résultat est automatiquement rechargé dans l'éditeur de palette.</p>

<h2>Après le remap</h2>
<p>Avec des palettes identiques, NgpCraft Engine détecte automatiquement le partage
et assigne <code>--fixed-palette</code> à la prochaine fois que vous ajoutez le
sprite remappé à une scène. <b>Résultat : 0 slot palette supplémentaire consommé.</b></p>
"""


def _fr_project() -> str:
    return """
<h1>Onglet Projet</h1>

<h2>Organisation en scènes</h2>
<p>Un projet <code>.ngpcraft</code> organise les assets par <b>scènes</b> (ex : "Menu", "Acte 1", "Boss").
Chaque scène regroupe les sprites et tilemaps qui apparaissent ensemble à l'écran.</p>

<h2>Gestion des scènes</h2>
<ul>
  <li><b>Nouvelle…</b> — crée une scène vide (saisie du nom).</li>
  <li><b>✎ Renommer</b> — modifie le nom de la scène sélectionnée.</li>
  <li><b>✕ Supprimer</b> — supprime la scène et tous ses assets enregistrés.</li>
  <li><b>Ordre</b> — glissez-déposez les scènes dans la liste pour changer l’ordre (impacte le manifest <code>scenes_autogen</code>).</li>
  <li><b>Scène de départ</b> — choisit l’entrée par défaut (<code>NGP_SCENE_START_INDEX</code>).</li>
</ul>

<p><b>Navigator :</b> le panneau permanent à gauche donne maintenant une vue globale des scènes, sprites, tilemaps, entités, waves, régions, triggers et paths. Un clic active la scène ; double-clic ou clic droit ouvre directement l'onglet logique.</p>
<p><b>Inspecteur :</b> juste sous l'arbre, un inspecteur contextuel unique résume l'élément sélectionné (scène, sprite, tilemap, entité, wave, région, trigger, path) et affiche les actions rapides les plus utiles. L'objectif de cette V1 est de réduire les allers-retours mentaux entre onglets avant un futur inspecteur plus éditable.</p>

<h2>Contenu d'une scène</h2> 
<p>Sélectionnez une scène dans la liste de gauche. Le panneau de droite affiche :</p> 
<ul> 
  <li><b>Statut de scène</b> : la liste de gauche affiche maintenant un état visuel <b>OK / ! / KO</b> avec tooltip. Cela aide à voir rapidement si la scène semble prête, en warning, ou incomplète (assets manquants, player absent, col_map invalide, refs cassées, export_dir absent…).</li>
  <li><b>Actions rapides</b> : une ligne permet d’ouvrir immédiatement la scène courante dans <b>Palette</b>, <b>Tilemap</b>, <b>Level</b>, <b>Hitbox</b>, ou d’ouvrir le <b>dossier d’export</b> sans repasser par la navigation globale.</li>
  <li><b>Presets de scène</b> : un combo applique une structure de départ réutilisable à la scène courante (<b>platformer</b>, <b>shmup vertical</b>, <b>top-down</b>, <b>menu écran unique</b>…). Ces presets gardent les sprites/tilemaps déjà posés et remplissent profil, layout, HUD et quelques starters de régions/triggers quand la scène est encore vide de ce côté.</li>
  <li><b>Validation projet</b> : en bas, un résumé compte les scènes <b>prêtes</b>, en <b>warning</b> ou <b>incomplètes</b>, une mini <b>checklist projet</b> résume scènes / start scene / export_dir / état global / compat template, le bouton <b>Premier souci</b> saute à la première scène à corriger, et le bouton <b>Détails</b> ouvre maintenant un centre de validation listant les soucis projet / scène / level / export. Ce dialogue ne se limite plus à ouvrir la scène : il propose aussi une <b>action contextuelle</b> quand le correctif est évident (ajouter une scène, fixer la start scene, régler export_dir, revoir le template, revenir au workflow export).</li>
  <li><b>Validation export</b> : ce centre vérifie aussi une première passe statique du pipeline d'export, sans lancer les outils : collisions de noms de fichiers générés (<code>scene_*</code>, <code>*_mspr.c</code>, <code>*_map.c</code>), <code>export_dir</code> douteux, et autogens absents ou incomplets (<code>assets_autogen.mk</code>, <code>audio_autogen.mk</code>, <code>scenes_autogen</code>).</li>
  <li><b>Compat template</b> : juste sous la validation, un résumé vérifie aussi le contrat de base du template détecté : <code>makefile</code>, <code>src/main.c</code>, scripts <code>tools/</code>, présence de <code>ngpc_metasprite.h</code>, macro <code>NGP_FAR</code>, <code>ngpc_types.h</code> (typedefs u8/u16/s16), et le contrat audio (<code>project_audio_manifest.txt</code> accessible + fichiers runtime <code>src/audio/sounds.h/.c</code> quand l’audio est configuré), puis un premier diagnostic toolchain (<code>build.bat</code>, <code>compilerPath</code>, helpers locaux <code>asm900/thc1/thc2</code>, outils dans le <code>PATH</code>). Le bouton <b>Détails</b> ouvre la liste complète, et <b>Étape suivante</b> propose l’action la plus utile selon l’état global.</li>
  <li><b>Sprites</b> : tableau avec fichier, taille de frame (W×H), nombre de frames, 
      et estimation de tiles consommées.</li> 
  <li><b>Import batch</b> : <i>+ Sprite…</i> supporte la multi-sélection, et vous pouvez aussi 
      glisser-déposer des PNG (fichiers ou dossier) dans la liste de sprites.</li> 
  <li><b>Ouvrir dans Palette</b> : sélectionnez un sprite et cliquez <b>Ouvrir dans Palette</b>
      (ou <b>Ctrl + double-clic</b>) pour charger le PNG dans l’onglet Palette
      avec la config anim (frame_w/h/count) pré-remplie.</li>
  <li><b>Auto-partage palettes</b> : si deux sprites utilisent les mêmes couleurs (ordre différent),
      le bouton <b>Auto-partage palettes</b> peut leur faire partager une seule palette.</li> 
  <li><b>Tilemaps</b> : liste simple des PNG de tilemaps.</li> 
  <li><b>Export</b> : décochez pour ignorer un asset lors des exports (pratique pour des fichiers temporaires ou non utilisés).</li>
  <li><b>Audio (par scène)</b> : lier un <code>project_audio_manifest.txt</code> (Sound Creator) et choisir une <b>BGM</b>.
      L’export écrit des <code>#define</code> (<code>SCENE_*_BGM_INDEX</code>…) dans <code>scene_*_level.h</code>.
      Le header <code>scene_*.h</code> expose aussi <code>scene_xxx_enter()</code> et des helpers audio optionnels
      (<code>scene_xxx_audio_*</code>, si <code>NGP_ENABLE_SOUND</code>).
      <br><b>Format requis :</b> export <b>hybride C</b> uniquement (Sound Creator → Projet → <i>Exporter tout</i>).
      Ce mode génère des bytecodes interprétés à runtime par le driver PSG embarqué.
      Le fichier <code>project_instruments.c</code> est obligatoire pour la BGM.</li>
  <li><b>Mapping SFX</b> : liste “IDs gameplay → ID Sound Creator” (global projet). L’export peut générer
      <code>ngpc_project_sfx_map.h</code> (enum + table) dans <code>export_dir</code>.</li>
  <li><b>Budget scène</b> : total tiles et palettes estimés pour cette scène seule.</li> 
  <li><b>Ouvrir dans Éditeur</b> : ouvre le PNG dans l'onglet <b>Éditeur</b> pour une retouche rapide.</li>
</ul> 

<h2>Asset Browser (GraphX)</h2>
<p>En haut du panneau de droite, un <b>Asset Browser</b> liste les images du dossier GraphX :</p>
<ul>
  <li>Filtre texte pour retrouver rapidement un PNG.</li>
  <li><b>Auto-rescan</b> : si activé, la liste se met à jour quand vous ajoutez/renommez des fichiers.</li>
  <li><b>Miniatures</b> : affiche une petite icône de chaque asset (chargement progressif).</li>
  <li>Double-clic sur un asset : l'ouvre dans l'onglet <b>Palette</b>.</li>
  <li>Boutons : ouvrir dans Palette/Tilemap/Éditeur, ou ajouter directement à la scène (sprite / tilemap).</li>
  <li>Drag &amp; drop : glissez un asset vers la liste des sprites.</li>
</ul>

<h2>Constantes projet (game constants)</h2>
<p>Le panneau <b>Constantes projet</b> (section collapsible en bas du panneau de droite) permet
de définir des constantes numériques globales au projet :</p>
<ul>
  <li><b>Nom</b> — identifiant C valide (ex : <code>PLAYER_HP_MAX</code>).</li>
  <li><b>Valeur</b> — entier signé.</li>
  <li><b>Commentaire</b> — texte libre (facultatif).</li>
</ul>
<p>Boutons <b>Ajouter…</b> / <b>Supprimer</b> pour gérer les lignes. À chaque export
(Tout en .c, Toutes scènes → .c, Scène → .c, Scène → tilemaps .c), le fichier
<code>ngpc_project_constants.h</code> est généré dans <b>Dossier export</b> :</p>
<pre>#ifndef NGPC_PROJECT_CONSTANTS_H
#define NGPC_PROJECT_CONSTANTS_H
#define PLAYER_HP_MAX  3   /* Player starting lives */
#define BULLET_SPEED   2   /* Bullet speed px/frame */
#endif /* NGPC_PROJECT_CONSTANTS_H */</pre>
<p>Incluez ce header dans votre code C : <code>#include "ngpc_project_constants.h"</code><br>
Le fichier n'est écrit que si au moins une constante est définie et que <b>Dossier export</b> est configuré.</p>

<h2>Variables de jeu (flags &amp; variables persistants)</h2>
<p>Le panneau <b>Variables de jeu</b> (collapsible, juste après Constantes projet) définit
8 <b>flags</b> et 8 <b>variables</b> persistants qui <b>survivent aux changements de scène</b>
tout au long de la session de jeu.</p>

<h3>Flags (onglet Flags)</h3>
<p>Un flag est un <b>booléen persistant</b> : il vaut 0 (faux) ou 1 (vrai). Typiquement utilisé
pour mémoriser qu'un événement s'est produit :</p>
<ul>
  <li>Le joueur a ramassé l'épée.</li>
  <li>Le boss de la zone 2 est mort.</li>
  <li>La porte secrète a été ouverte.</li>
</ul>
<p>Dans l'onglet, renseignez un <b>nom</b> pour chaque flag (0 à 15) — ce nom sera exporté comme
commentaire dans le header C pour documenter le code :</p>
<pre>GAME_FLAG_0  0   /* has_sword   */
GAME_FLAG_1  1   /* boss2_dead  */
GAME_FLAG_2  2   /* flag_2      */</pre>
<p>Contrôlez les flags via des triggers dans l'onglet Level :</p>
<table>
  <tr><th>Action trigger</th><th>Effet</th></tr>
  <tr><td><code>set_flag</code></td><td>Met le flag à 1</td></tr>
  <tr><td><code>clear_flag</code></td><td>Met le flag à 0</td></tr>
  <tr><td><code>toggle_flag</code></td><td>Inverse la valeur (0→1, 1→0)</td></tr>
</table>
<p>Vérifiez l'état d'un flag via des conditions trigger :</p>
<table>
  <tr><th>Condition</th><th>Vérifie</th></tr>
  <tr><td><code>flag_set</code></td><td>Le flag est à 1</td></tr>
  <tr><td><code>flag_clear</code></td><td>Le flag est à 0</td></tr>
</table>
<p>Dans votre code C (module <code>ngpc_game_vars</code>) :</p>
<pre>ngpc_gv_set_flag(GAME_FLAG_0);           /* a ramassé l'épée */
if (ngpc_gv_get_flag(GAME_FLAG_1)) { }  /* boss2 mort ? */</pre>

<h3>Variables (onglet Variables)</h3>
<p>Une variable est un <b>compteur persistant u8</b> (entier 0 à 255). Typiquement utilisé pour :</p>
<ul>
  <li>Nombre de pièces ramassées.</li>
  <li>Score de la session.</li>
  <li>Niveau de progression dans un dialogue.</li>
  <li>Nombre de vies restantes.</li>
</ul>
<p>Dans l'onglet, renseignez un <b>nom</b> et une valeur <b>Init</b> (0–255) pour chaque variable.
La valeur Init est appliquée lors de l'action trigger <code>init_game_vars</code>.
Le header exporté contient :</p>
<pre>GAME_VAR_0   0   /* coins  (init: 0)  */
GAME_VAR_1   1   /* health (init: 3)  */
static const u8 g_game_var_inits[16] = { 0, 3, 0, 0, 0, 0, 0, 0 };</pre>
<p>Contrôlez les variables via des triggers :</p>
<table>
  <tr><th>Action trigger</th><th>Effet</th></tr>
  <tr><td><code>set_variable</code></td><td>Affecte une valeur fixe (0–255)</td></tr>
  <tr><td><code>inc_variable</code></td><td>Incrémente (avec cap optionnel)</td></tr>
  <tr><td><code>dec_variable</code></td><td>Décrémente (plancher à 0)</td></tr>
  <tr><td><code>init_game_vars</code></td><td>Applique toutes les valeurs Init définies dans ce panneau</td></tr>
</table>
<p>Vérifiez la valeur via des conditions trigger :</p>
<table>
  <tr><th>Condition</th><th>Vérifie</th></tr>
  <tr><td><code>variable_ge</code></td><td>Variable ≥ valeur</td></tr>
  <tr><td><code>variable_eq</code></td><td>Variable = valeur</td></tr>
  <tr><td><code>variable_le</code></td><td>Variable ≤ valeur</td></tr>
  <tr><td><code>variable_ne</code></td><td>Variable ≠ valeur</td></tr>
</table>
<p>Dans votre code C :</p>
<pre>ngpc_gv_inc_var(GAME_VAR_0, 0);              /* +1 pièce, sans cap */
u8 coins = ngpc_gv_get_var(GAME_VAR_0);
ngpc_gv_set_var(GAME_VAR_1, 3);              /* health = 3 */</pre>

<h3>Module optionnel ngpc_game_vars</h3>
<p>Le module <code>optional/ngpc_game_vars/</code> gère les tableaux d'état et le dispatch
des triggers flags/variables. Pour l'intégrer dans votre <code>main.c</code> :</p>
<pre>/* 1. Copier ngpc_game_vars/ dans src/ */
/* 2. Ajouter à Makefile : OBJS += src/ngpc_game_vars/ngpc_game_vars.rel */
/* 3. Dans main.c : */
#include "GraphX/gen/ngpc_game_vars.h"  /* header généré par l'outil */
#include "ngpc_game_vars/ngpc_game_vars.h"

/* Au démarrage du jeu : */
ngpc_gv_init();   /* applique les valeurs Init */

/* Dans la boucle trigger : */
if (ngpc_gv_dispatch(t-&gt;action, t-&gt;a0, t-&gt;a1)) continue;</pre>
<p><b>Export :</b> à chaque export de scène, le fichier <code>ngpc_game_vars.h</code>
(guard <code>NGPC_GAME_VARS_GEN_H</code>) est automatiquement généré dans <b>Dossier export</b>.
Il contient les constantes <code>GAME_FLAG_x</code>, <code>GAME_VAR_x</code> et le tableau
<code>g_game_var_inits[]</code>.</p>

<h2>Réglages performance</h2>
<p>Trois options projet agissent sur le comportement à l'exécution :</p>
<ul>
  <li><b>Rayon d'activation (tiles)</b> — quand &gt; 0, les ennemis hors de cette zone
      autour de la caméra sont mis en veille. Utile pour les grandes tilemaps avec beaucoup
      d'ennemis. <code>0</code> = tous toujours actifs.</li>
  <li><b>Recyclage dynamique des palettes (LRU)</b> — recycle les 16 slots palette sprite
      à l'exécution. Utile quand le projet a plus de 16 types d'entités avec des couleurs
      différentes. Coût CPU négligeable (quelques dizaines de cycles par spawn/despawn).
      <br>Désactivé : les slots sont assignés à la compilation (baked dans la ROM).</li>
  <li><b>Désactiver la police système BIOS</b> — par défaut le BIOS charge sa police
      intégrée dans les tiles 32–127 (96 tiles × 8 mots). Cocher cette option supprime
      cet appel et libère ces 96 slots pour tes propres tiles ou une police custom.
      Définit <code>NGPNG_NO_SYSFONT=1</code> dans le Makefile.
      <br>⚠ Si tu utilises <code>ngpc_text_*</code>, ne pas cocher cette option.</li>
</ul>
<p>Ces options sont indépendantes — elles peuvent être combinées librement.</p>

<h2>Police personnalisée (Custom Font)</h2>
<p>Le champ <b>Police custom</b> permet de remplacer la police système BIOS
par ta propre police 8×8.  Une fois un PNG sélectionné :</p>
<ul>
  <li>L'option "Désactiver la police système BIOS" est cochée automatiquement.</li>
  <li>Au prochain export, <code>ngpc_font_export.py</code> génère
      <code>GraphX/ngpc_custom_font.c/.h</code>.</li>
  <li>Le <code>main.c</code> généré appelle <code>ngpc_custom_font_load()</code>
      à la place de <code>ngpc_load_sysfont()</code>.</li>
  <li>Toutes les fonctions <code>ngpc_text_*</code> continuent de fonctionner sans
      modification (même mapping ASCII → tile index).</li>
</ul>
<h3>Prévisualisation</h3>
<p>La preview affiche le PNG avec une grille tile par tile et le caractère ASCII dans chaque case.
Utilise les boutons <b>2× 3× 4× 6×</b> pour zoomer, et le bouton <b>Fond clair / sombre</b>
pour basculer l'arrière-plan.</p>
<h3>Formats PNG acceptés</h3>
<p>Sélectionne le format dans le menu déroulant <b>Format PNG</b> avant de charger le fichier.</p>
<pre><b>Format 128 × 48</b>  (16 colonnes × 6 lignes)
Tiles       : 96 au total  →  ASCII 32 (espace) … 127 (~)
Couleurs    : max 3 visibles + transparent
  Noir pur (0,0,0) ou alpha &lt; 128 = transparent (index 0)

Ordre des tiles :
  Ligne 0  ASCII  32– 47  :  espace ! " # $ % &amp; ' ( ) * + , - . /
  Ligne 1  ASCII  48– 63  :  0 1 2 3 4 5 6 7 8 9 : ; &lt; = &gt; ?
  Ligne 2  ASCII  64– 79  :  @ A B C D E F G H I J K L M N O
  Ligne 3  ASCII  80– 95  :  P Q R S T U V W X Y Z [ \ ] ^ _
  Ligne 4  ASCII  96–111  :  ` a b c d e f g h i j k l m n o
  Ligne 5  ASCII 112–127  :  p q r s t u v w x y z { | } ~</pre>
<pre><b>Format 256 × 24</b>  (32 colonnes × 3 lignes)
Tiles       : 96 au total  →  ASCII 32 (espace) … 127 (~)
Couleurs    : mêmes règles que ci-dessus

Ordre des tiles :
  Ligne 0  ASCII  32– 63  :  espace ! " # $ % &amp; ' ( ) * + , - . / 0 1 2 3 4 5 6 7 8 9 : ; &lt; = &gt; ?
  Ligne 1  ASCII  64– 95  :  @ A B C D E F G H I J K L M N O P Q R S T U V W X Y Z [ \ ] ^ _
  Ligne 2  ASCII  96–127  :  ` a b c d e f g h i j k l m n o p q r s t u v w x y z { | } ~</pre>
<p><b>Outil :</b> <code>tools/ngpc_font_export.py</code> — utilisable aussi en ligne de commande :<br>
<code>python tools/ngpc_font_export.py font.png -o GraphX/ngpc_custom_font</code></p>

<h2>Budget global</h2>
<p>La barre inférieure affiche le budget total du projet :</p>
<pre>Global : 76/512 tiles  ·  3/16 pal.  ✓</pre>
<p>Un avertissement ⚠ apparaît si le projet dépasse les 512 tiles ou 16 palettes.</p>

<h2>Exports globaux</h2> 
<table> 
  <tr><th>Bouton</th><th>Effet</th></tr> 
  <tr><td><b>Tout en PNG</b></td><td>Sauvegarde chaque sprite quantifié RGB444 à côté de son source</td></tr> 
  <tr><td><b>Tout en .c</b></td><td>Appelle <code>ngpc_sprite_export.py</code> pour chaque sprite</td></tr> 
  <tr><td><b>Toutes scènes → .c</b></td><td>Exporte <b>toutes les scènes</b> (sprites + tilemaps + headers scène/level), puis met à jour <code>scenes_autogen</code> — ouvre un dialogue d’options (assets, headers, désactivés).</td></tr>
  <tr><td><b>Palettes .c</b></td><td>Génère uniquement les tableaux <code>const u16 name_pal[]</code></td></tr> 
  <tr><td><b>Rapport HTML…</b></td><td>Génère un fichier HTML récapitulatif (budgets, scènes, fichiers manquants)</td></tr> 
  <tr><td><b>Rapport PDF…</b></td><td>Génère un PDF du même report (export partageable)</td></tr> 
</table>
<p><b>Astuce :</b> si <b>Dossier export</b> est configuré, ces exports mettent à jour les fichiers “autogen” :
<code>assets_autogen.mk</code>, <code>scene_*.h</code>, <code>scene_*_level.h</code>, <code>scenes_autogen.c/.h</code>, (si audio lié) <code>audio_autogen.mk</code>,
(si des constantes sont définies) <code>ngpc_project_constants.h</code>,
et toujours <code>ngpc_game_vars.h</code> (flags/variables de jeu).</p>
<p><b>Export (prêt à compiler)</b> ouvre un dialogue d’options (portée, assets désactivés, headers, triggers/hitbox…).</p>

<h2>Build / Run (Phase 5)</h2>
<p>Pour intégrer le workflow jeu complet :</p>
<ul>
  <li><b>Build…</b> : lance <code>make</code> dans le dossier du projet et affiche le log.</li>
  <li><b>Cible perso…</b> : permet d’entrer une cible <code>make</code> (ex : <code>release</code>).</li>
  <li><b>Jobs</b> : parallélise le build (ex : <code>-j 8</code>).</li>
  <li><b>Options</b> : ajoute des options à <code>make</code> (ex : <code>V=1</code>).</li>
  <li><b>Vider</b> / <b>Copier</b> : gère le log facilement.</li>
  <li><b>Run</b> : lance un émulateur (Mednafen/RACE) avec la ROM (auto-détection ou sélection manuelle).</li>
  <li><b>Config…</b> : configure le chemin émulateur + ROM, et mémorise les choix.</li>
</ul>

<h2>Exports par scène</h2>
<p>Quand une scène est sélectionnée, des boutons d'export dédiés sont disponibles :</p>
<ul>
  <li><b>Scène → PNG</b> : export des sprites de la scène en PNG quantifié RGB444.</li>
  <li><b>Scène → .c</b> : export <b>sprites + tilemaps</b> (scripts <code>ngpc_sprite_export.py</code> + <code>ngpc_tilemap.py</code>),
      et génère <code>scene_*.h</code> + <code>scene_*_level.h</code> (si <b>Dossier export</b> est défini), puis met à jour
      <code>scenes_autogen</code> (manifest global). Ouvre un dialogue d’options.</li>
  <li><b>Scène → tilemaps .c</b> : export des tilemaps de la scène via <code>ngpc_tilemap.py</code>.</li>
</ul>
<p><b>Audio :</b> si un manifest Sound Creator est lié, l’export génère aussi <code>audio_autogen.mk</code> dans
<b>Dossier export</b> (il ajoute les <code>sound/exports/*.c</code> à <code>OBJS</code> quand <code>NGP_ENABLE_SOUND=1</code>).
Si un mapping SFX est défini, l’export génère <code>ngpc_project_sfx_map.h</code> (dans <code>export_dir</code>) et un
<code>sounds_game_sfx_autogen.c</code> (dans le dossier audio <code>exports/</code>).</p>
<p><b>Dossier GraphX</b> : chemin relatif vers le dossier d'assets, utilisé comme base
pour les chemins relatifs dans le projet.</p>

<h2>Thumbnail rail (onglet Palette)</h2> 
<p>Quand une scène est sélectionnée ici, l'onglet Palette affiche un rail de 
miniatures des sprites de la scène. Cliquer une miniature charge cet asset 
dans l'éditeur de palette.</p> 
<p>Pour les sprites, la miniature réutilise aussi la configuration du sprite 
(<code>frame_w</code>/<code>frame_h</code>/<code>frame_count</code>) pour la prévisualisation anim.</p>
"""


def _fr_globals() -> str:
    return """
<h1>Onglet Globals</h1>
<p>L'onglet <b>Globals</b> centralise tout ce qui est <b>global au projet</b> et ne dépend
d'aucune scène en particulier. Il contient 5 sous-onglets : <b>Variables</b>, <b>Constantes</b>,
<b>Audio</b>, <b>Items</b> et <b>Templates d'entités</b>.</p>

<h2>Variables (flags &amp; variables persistants)</h2>
<p>Un projet dispose de 8 <b>flags</b> et 8 <b>variables u8</b> persistants qui survivent
aux changements de scène tout au long de la session de jeu.</p>

<h3>Flags (booléens)</h3>
<p>Un flag vaut 0 (faux) ou 1 (vrai). Utilisé pour mémoriser qu'un événement s'est produit :</p>
<ul>
  <li>Le joueur a ramassé l'épée.</li>
  <li>La porte secrète a été ouverte.</li>
  <li>Le boss est mort.</li>
</ul>
<p>Donnez un <b>nom</b> à chaque flag (0–15) pour documenter votre code. Les flags sans nom
et non référencés par un trigger <b>ne génèrent aucun code C</b> (tree-shaking).</p>
<table>
  <tr><th>Condition trigger</th><th>Vérifie</th></tr>
  <tr><td><code>flag_set</code></td><td>Le flag est à 1</td></tr>
  <tr><td><code>flag_clear</code></td><td>Le flag est à 0</td></tr>
</table>
<table>
  <tr><th>Action trigger</th><th>Effet</th></tr>
  <tr><td><code>set_flag</code></td><td>Met le flag à 1</td></tr>
  <tr><td><code>clear_flag</code></td><td>Met le flag à 0</td></tr>
  <tr><td><code>toggle_flag</code></td><td>Inverse la valeur</td></tr>
</table>

<h3>Variables u8 (compteurs)</h3>
<p>Une variable est un entier non signé 0–255. Typiquement utilisé pour :</p>
<ul>
  <li>Nombre de pièces ramassées.</li>
  <li>Points de vie restants.</li>
  <li>Progression dans une quête.</li>
</ul>
<p>Chaque variable a un <b>nom</b> et une <b>valeur initiale</b> (appliquée par l'action
<code>init_game_vars</code>). Dans l'onglet Level, le spinbox flag/var affiche le nom du slot
sélectionné directement dans l'interface.</p>
<table>
  <tr><th>Condition trigger</th><th>Vérifie</th></tr>
  <tr><td><code>variable_ge</code></td><td>var[N] ≥ valeur</td></tr>
  <tr><td><code>variable_eq</code></td><td>var[N] = valeur</td></tr>
  <tr><td><code>variable_le</code></td><td>var[N] ≤ valeur</td></tr>
</table>
<table>
  <tr><th>Action trigger</th><th>Effet</th></tr>
  <tr><td><code>set_variable</code></td><td>Assigne une valeur</td></tr>
  <tr><td><code>inc_variable</code></td><td>Incrémente de 1</td></tr>
  <tr><td><code>dec_variable</code></td><td>Décrémente de 1</td></tr>
</table>

<h3>Tree-shaking à l'export</h3>
<p>À chaque export, NgpCraft scanne toutes les scènes et ne génère un <code>#define</code>
que pour les slots <b>nommés</b> ou <b>référencés</b> dans au moins un trigger. Les slots
vides et inutilisés sont silencieusement omis du header :</p>
<pre>/* ngpc_game_vars.h — uniquement les slots actifs */
#define GAME_FLAG_0  0   /* has_sword    */
#define GAME_FLAG_3  3   /* visited_town */
#define GAME_VAR_0   0   /* coins  (init: 0) */
#define GAME_VAR_1   1   /* health (init: 3) */
static const u8 g_game_var_inits[16] = { 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };</pre>
<p><b>Avertissement à l'export :</b> si un trigger référence un slot sans nom, un
<code>[warning]</code> apparaît dans le résumé d'export.</p>

<h2>Constantes projet</h2>
<p>Les constantes sont des entiers nommés globaux au projet. Elles n'ont <b>aucun coût
runtime</b> (préprocesseur pur). Boutons <b>Ajouter…</b> / <b>Supprimer</b> pour gérer la liste.
L'export génère <code>ngpc_project_constants.h</code> :</p>
<pre>#define PLAYER_HP_MAX  3   /* Player starting lives */
#define BULLET_SPEED   2   /* Bullet speed px/frame */</pre>
<p>Incluez ce header dans votre code C avec <code>#include "ngpc_project_constants.h"</code>.</p>

<h2>Audio</h2>
<p>Ce sous-onglet reprend les réglages audio globaux du projet :</p>
<ul>
  <li><b>Manifest</b> : chemin vers le fichier <code>project_audio_manifest.txt</code>
      (Sound Creator). L'export génère <code>audio_autogen.mk</code>.</li>
  <li><b>Mapping SFX</b> : liste "ID gameplay → ID Sound Creator". L'export génère
      <code>ngpc_project_sfx_map.h</code> (enum + table de mapping).</li>
</ul>
<h3>Tree-shaking SFX</h3>
<p>À l'export, NgpCraft scanne les triggers <code>play_sfx</code> de toutes les scènes.
Les entrées SFX en queue non référencées sont <b>supprimées de la table</b> (trim de fin).
Les entrées non utilisées au milieu sont conservées (pas de re-numérotage) mais
annotées <code>/* unused */</code> dans le header.</p>

<h2>Templates d'entités (prefabs)</h2>
<p>Un <b>template d'entité</b> est un <b>prefab projet-global</b> : il regroupe en un
seul endroit <em>toutes</em> les caractéristiques d'un personnage ou ennemi :</p>
<table>
  <tr><th>Catégorie</th><th>Données stockées</th></tr>
  <tr><td><b>Sprite</b></td><td>Fichier PNG source, dimensions de frame (w×h px)</td></tr>
  <tr><td><b>Hitbox</b></td><td>Hurtboxes (dégâts reçus), attack boxes (dégâts infligés)</td></tr>
  <tr><td><b>Physique</b></td><td>Props : gravité, vitesse, saut, contact damage…</td></tr>
  <tr><td><b>Contrôle</b></td><td>Ctrl export (joueur : bindings, move_type, etc.)</td></tr>
  <tr><td><b>Animations</b></td><td>États d'animation, named anims, motion patterns</td></tr>
  <tr><td><b>IA / Comportement</b></td><td>Rôle, behavior, ai_speed, ai_range, direction, data, flags</td></tr>
</table>
<p>Les instances dans les scènes sont des <b>copies indépendantes</b> — il n'y a pas de
binding live. Le template est la <b>version maître</b> : tu l'édites librement dans
Globals, et tu appliques explicitement ("tirer depuis le maître") dans les scènes
quand tu le souhaites.</p>

<h3>Créer un template — depuis l'onglet Hitbox</h3>
<p>C'est le <b>point d'entrée principal</b>. Une fois le sprite configuré (hitbox, props,
animations, ctrl) dans l'onglet Hitbox :</p>
<ol>
  <li>Cliquer <b>💾 Enregistrer comme template</b> → dialog pour nommer le template.</li>
  <li>Le template est créé dans <code>entity_templates[]</code> du projet avec un snapshot
      complet du sprite courant.</li>
  <li>Un badge <b>📌 Template : nom</b> apparaît sous le nom du sprite pour confirmer.</li>
  <li>Si le sprite a déjà un template : le bouton devient <b>↑ Mettre à jour le template</b>
      — une confirmation est demandée avant d'écraser.</li>
</ol>
<p>Le badge réapparaît automatiquement à chaque ouverture du sprite dans Hitbox.</p>

<h3>Gérer les templates — onglet Globals</h3>
<p>La liste affiche les templates (préfixés <b>📌</b>) et les anciens archétypes
behavior-only (sans préfixe) pour la rétro-compatibilité.</p>
<ul>
  <li>Sélectionner un template → le panneau de droite montre les champs IA (éditables
      directement) <em>et</em> un résumé read-only du côté sprite : fichier, dimensions,
      nombre de hitboxes, props actifs.</li>
  <li><b>Ajouter…</b> : crée un template vide (behavior-only) à compléter depuis Hitbox.</li>
  <li><b>Supprimer</b> : retire le template du projet (les instances existantes conservent
      leurs données, le <code>type_id</code> devient orphelin).</li>
</ul>
<p>Les champs IA sont contextuels selon le rôle et le comportement :</p>
<table>
  <tr><th>Comportement</th><th>Champs visibles</th></tr>
  <tr><td>Patrol</td><td>Vitesse IA</td></tr>
  <tr><td>Chase</td><td>Vitesse IA + Portée détection + Portée perte</td></tr>
  <tr><td>Random</td><td>Vitesse IA + Changer toutes (fr)</td></tr>
  <tr><td>Fixed</td><td>Aucun paramètre IA</td></tr>
</table>

<h3>Utiliser les templates — onglet Level</h3>
<p>Dans l'inspecteur d'entité (onglet Level), le groupe <b>Template d'entité</b> offre :</p>
<ul>
  <li><b>Sauvegarder comme template…</b> : capture les paramètres IA/rôle de l'instance
      <em>et</em> le sprite meta de la scène → crée ou met à jour un template dans Globals.</li>
  <li><b>Appliquer template…</b> : picker → copie les paramètres IA/rôle dans l'instance
      courante et rafraîchit l'inspecteur.</li>
  <li><b>→ Gérer dans Globals</b> : bascule directement vers l'onglet Globals.</li>
</ul>
<p>En bas de la palette de types (colonne gauche du Level tab) :</p>
<ul>
  <li><b>＋ Depuis un template…</b> : liste les templates qui ont un sprite défini →
      sélection → le sprite est <b>auto-importé dans la scène</b> si absent, puis la
      vue est rafraîchie. Le sprite est prêt à être placé.</li>
</ul>
<p>Le label <b>"Basé sur : nom_template"</b> apparaît si l'instance est associée à un
template (<code>type_id</code> renseigné).</p>

<h3>Export C — tree-shaking complet</h3>
<p>L'export génère <code>ngpc_entity_types.h</code> avec <b>uniquement</b> les templates
référencés par au moins une instance (<code>type_id</code>) dans au moins une scène.
Les templates définis mais jamais placés → <b>aucun code C généré</b>.</p>
<pre>/* ngpc_entity_types.h */
typedef enum {
    ET_PLAYER = 0,   /* etpl_player */
    ET_SLIME  = 1,   /* etpl_slime  */
} EntityTypeId;

typedef struct {
    u8 role; u8 behavior; u8 speed; u8 range;
    u8 lose_range; u8 change_every; u8 dir; u8 data; u8 flags;
    u8 hp; u8 atk; u8 def; u8 xp;
} EntityTypeDef;

static const EntityTypeDef et_table[] = {
    /* ET_PLAYER */ { 0, 0, 3, 0,  0,  0, 0, 0, 0,  0, 0, 0, 0 },
    /* ET_SLIME  */ { 1, 0, 1, 10, 16, 60, 0, 0, 0, 10, 1, 0, 5 },
};
#define ET_TABLE_SIZE  2</pre>
<p>Toutes les données sont <code>const</code> → ROM uniquement, <b>zéro RAM, zéro CPU
overhead</b>. Le sprite/hitbox ne sont pas exportés dans ce header (ils sont générés
séparément par le pipeline bundle habituel).</p>

<h3>Validation à l'export (warnings)</h3>
<ul>
  <li>Flag/variable référencé dans un trigger mais sans nom → <code>[warning]</code>.</li>
  <li>Instance avec un <code>type_id</code> qui n'existe plus dans Globals → <code>[warning]</code>.</li>
</ul>

<h2>Événements par type d'entité (no-code global)</h2>
<p>La section <b>Événements</b> en bas de chaque template permet d'attacher des <b>actions
automatiques</b> à un type d'entité — sans écrire une ligne de C. Ces actions se déclenchent
pour <em>n'importe quelle instance</em> de ce type, dans <em>toutes les scènes</em>,
y compris les scènes générées par procgen.</p>

<h3>Événements disponibles (16)</h3>
<table>
  <tr><th>Événement</th><th>EV_* C (index)</th><th>Se déclenche quand…</th><th>Rôles types</th></tr>
  <tr><td><code>entity_death</code></td><td>0</td><td>Instance tuée</td><td>enemy, block</td></tr>
  <tr><td><code>entity_collect</code></td><td>1</td><td>Instance ramassée</td><td>item</td></tr>
  <tr><td><code>entity_activate</code></td><td>2</td><td>Instance activée (NPC parlé, trigger touché)</td><td>npc, trigger, platform, block, prop</td></tr>
  <tr><td><code>entity_hit</code></td><td>3</td><td>Instance touchée par le joueur</td><td>enemy, block</td></tr>
  <tr><td><code>entity_spawn</code></td><td>4</td><td>Instance spawnée à l'exécution</td><td>tous sauf player</td></tr>
  <tr><td><code>entity_btn_a</code></td><td>5</td><td>Bouton A pressé près d'une instance</td><td>enemy, npc, trigger, platform, block, prop</td></tr>
  <tr><td><code>entity_btn_b</code></td><td>6</td><td>Bouton B pressé près d'une instance</td><td>enemy, npc, trigger, block, prop</td></tr>
  <tr><td><code>entity_btn_opt</code></td><td>7</td><td>Option pressé près d'une instance</td><td>npc, trigger, prop</td></tr>
  <tr><td><code>entity_btn_up</code></td><td>8</td><td>Haut pressé près d'une instance</td><td>npc, trigger</td></tr>
  <tr><td><code>entity_btn_down</code></td><td>9</td><td>Bas pressé près d'une instance</td><td>npc, trigger</td></tr>
  <tr><td><code>entity_btn_left</code></td><td>10</td><td>Gauche pressé près d'une instance</td><td>npc, trigger, platform, prop</td></tr>
  <tr><td><code>entity_btn_right</code></td><td>11</td><td>Droite pressé près d'une instance</td><td>npc, trigger, platform, prop</td></tr>
  <tr><td><code>entity_player_enter</code></td><td>12</td><td>Joueur entre dans la zone de proximité</td><td>enemy, item, npc, trigger, platform, block, prop</td></tr>
  <tr><td><code>entity_player_exit</code></td><td>13</td><td>Joueur quitte la zone de proximité</td><td>enemy, npc, trigger, platform, prop</td></tr>
  <tr><td><code>entity_timer</code></td><td>14</td><td>Timer périodique (cadence définie par instance)</td><td>enemy, npc, block, prop</td></tr>
  <tr><td><code>entity_low_hp</code></td><td>15</td><td>HP passe sous un seuil (changement de phase boss…)</td><td>enemy, block</td></tr>
</table>
<p>Les événements sont filtrés par rôle dans l'interface : un ennemi ne voit pas
<code>entity_collect</code>, un NPC ne voit pas <code>entity_death</code>.</p>

<h3>Actions configurables par événement</h3>
<p>Chaque événement peut déclencher une ou plusieurs actions : <b>jouer SFX</b>,
<b>démarrer/arrêter BGM</b>, <b>incrémenter/définir variable</b>, <b>activer flag</b>,
<b>aller à scène</b>, <b>ajouter score</b>, <b>ajouter HP</b>, <b>fondu</b>,
<b>secousse écran</b>, <b>sauvegarder</b>, <b>fin de partie</b>…</p>
<p>L'option <b>[×1] une seule fois</b> fait que l'action ne se déclenche qu'une fois
par chargement de scène.</p>

<h3>Export C — ngpc_entity_type_events.h</h3>
<pre>#define EV_ENTITY_DEATH       0u
#define EV_ENTITY_COLLECT     1u
#define EV_ENTITY_BTN_A       5u
/* … */
#define TYPE_EVENT_COUNT      3

typedef struct {
    u8 type_id; u8 event; u8 action; u8 a0; u8 a1; u8 once;
} NgpngTypeEvent;

static const NgpngTypeEvent g_type_events[] = {
    { ET_GOBLIN, 0u, 31u, 0u, 1u, 0u },  /* Goblin entity_death */
    { ET_CHEST,  5u,  1u, 5u, 0u, 0u },  /* Chest entity_btn_a → play_sfx 5 */
};</pre>
<p><b>Tree-shaking :</b> seuls les types à la fois référencés dans une scène
<em>et</em> ayant au moins un événement sont émis.
Types non utilisés → aucune ligne dans <code>g_type_events[]</code>.</p>
<p>Le runtime appelle <code>ngpc_entity_dispatch_event(type_id, event_id)</code>
au bon moment (mort, collecte, btn pressé…). Le moteur parcourt la table et
exécute les actions correspondantes.</p>

<h3>Conditions scene triggers par type (18 conditions)</h3>
<p>En complément des events globaux, l'onglet <b>Triggers</b> de chaque scène propose
18 conditions qui évaluent l'état courant de toutes les instances d'un type
<em>dans cette scène</em> :</p>
<table>
  <tr><th>Condition</th><th>Valeur</th><th>Sens</th></tr>
  <tr><td><code>entity_type_all_dead</code></td><td>—</td><td>Toutes instances mortes → ouvre sortie</td></tr>
  <tr><td><code>entity_type_count_ge</code></td><td>N</td><td>Tués ≥ N (cumulatif)</td></tr>
  <tr><td><code>entity_type_alive_le</code></td><td>N</td><td>Vivants ≤ N → phase boss</td></tr>
  <tr><td><code>entity_type_any_alive</code></td><td>—</td><td>Au moins 1 vivant (escort, survival)</td></tr>
  <tr><td><code>entity_type_collected</code></td><td>—</td><td>1 item ramassé</td></tr>
  <tr><td><code>entity_type_collected_ge</code></td><td>N</td><td>Ramassés ≥ N → "5 pièces → porte"</td></tr>
  <tr><td><code>entity_type_all_collected</code></td><td>—</td><td>Tous items collectés → "3 clés → boss"</td></tr>
  <tr><td><code>entity_type_activated</code></td><td>—</td><td>1 instance activée (NPC parlé)</td></tr>
  <tr><td><code>entity_type_all_activated</code></td><td>—</td><td>Toutes activées → tous switches ON</td></tr>
  <tr><td><code>entity_type_btn_a</code></td><td>—</td><td>A près d'une instance → play_sfx, interaction</td></tr>
  <tr><td><code>entity_type_btn_b</code></td><td>—</td><td>B près d'une instance</td></tr>
  <tr><td><code>entity_type_btn_opt</code></td><td>—</td><td>Option près d'une instance</td></tr>
  <tr><td><code>entity_type_contact</code></td><td>—</td><td>Joueur touche une instance (hazard, heal)</td></tr>
  <tr><td><code>entity_type_near_player</code></td><td>—</td><td>Instance à portée joueur (aggro, alarme)</td></tr>
  <tr><td><code>entity_type_hit</code></td><td>—</td><td>1 instance touchée → feedback, phase</td></tr>
  <tr><td><code>entity_type_hit_ge</code></td><td>N</td><td>Hits totaux ≥ N → boss multi-phase</td></tr>
  <tr><td><code>entity_type_spawned</code></td><td>—</td><td>1 instance spawnée → intro cutscene</td></tr>
  <tr><td><code>entity_type_spawned_ge</code></td><td>N</td><td>Total spawné ≥ N → gestion de waves</td></tr>
  <tr><td><code>on_custom_event</code></td><td>ID événement</td><td>L'événement personnalisé spécifié a été émis → déclencheur cross-système</td></tr>
</table>
<p>Pour chaque condition, un <b>combo "Type"</b> liste les types d'entités présents
dans la scène. Les conditions avec valeur (N) affichent un spinner.</p>

<h2>Items (onglet Items)</h2>
<p>L'onglet <b>Items</b> définit la <b>table d'objets</b> du projet : chaque ligne décrit
un item ramassable (type, rareté, valeur). À l'export, le header <code>item_table.h</code>
est généré avec toutes les définitions.</p>

<h3>Colonnes de la table</h3>
<table>
  <tr><th>Colonne</th><th>Description</th></tr>
  <tr><td><b>Nom</b></td><td>Identifiant lisible (commentaire dans le header)</td></tr>
  <tr><td><b>Type</b></td><td>ITEM_HEAL, ITEM_ATK_UP, ITEM_DEF_UP, ITEM_XP_UP, ITEM_GOLD, ITEM_DICE_PLUS, ITEM_KEY, ITEM_CUSTOM</td></tr>
  <tr><td><b>Rareté</b></td><td>RARITY_COMMON, RARITY_UNCOMMON, RARITY_RARE</td></tr>
  <tr><td><b>Valeur</b></td><td>Entier u8 (puissance de l'effet : PV restaurés, bonus ATK…)</td></tr>
</table>

<h3>Header généré — item_table.h</h3>
<pre>/* item_table.h */
#define ITEM_HEAL      0
#define ITEM_ATK_UP    1
/* ... */
#define RARITY_COMMON   0
#define RARITY_UNCOMMON 1
#define RARITY_RARE     2

typedef struct { u8 type; u8 value; u8 rarity; u8 price; u8 sprite_id; } NgpcItem;

static const NgpcItem g_item_table[] = {
    /* [0] potion_heal  */ { ITEM_HEAL,    3, RARITY_COMMON,    5, 2 },
    /* [1] sword_up     */ { ITEM_ATK_UP,  1, RARITY_UNCOMMON, 15, 5 },
};</pre>
<p>Ajoutez des items via le bouton <b>＋</b> ; supprimez avec <b>－</b>. Chaque ligne
peut être éditée directement dans la table.</p>
<p>Le champ <b>Sprite</b> (colonne de droite) contient l'index du metasprite dans le bundle PNG
(<code>NGPNG_MSPR_*</code>). À runtime, l'entity type générique <em>pickup</em> (rôle <code>item</code>)
utilise <code>g_item_table[idx].sprite_id</code> pour afficher le bon visuel —
une seule entité type pour tous les items.</p>

<h2>Événements personnalisés (Custom Events)</h2>
<p>Les <b>événements personnalisés</b> ferment la boucle <code>emit_event</code> :
quand un trigger de scène ou un type d'entité déclenche <code>emit_event(id)</code>,
c'est dans cette table que le moteur sait quoi faire.</p>
<p>Définissez-les dans <b>Globals → onglet Événements</b>.</p>

<h3>Flux complet</h3>
<ol>
  <li>Dans <b>Globals → Événements</b>, créez un événement (ex : <code>boss_phase_2</code>),
      ajoutez des <b>conditions de garde</b> (AND/OR), et attachez des actions.</li>
  <li>Dans n'importe quel trigger de scène ou événement de type d'entité, choisissez
      l'action <code>emit_event</code> — le combo affiche <b>[0] boss_phase_2</b>
      au lieu d'un spinner brut.</li>
  <li>À l'export, <code>ngpc_custom_events.h</code> est généré avec macros, table de
      conditions et table d'actions.</li>
  <li>Le runtime appelle <code>ngpc_emit_event(u8 id)</code> — le moteur évalue les
      gardes puis exécute chaque action liée à cet id.</li>
</ol>

<h3>Interface — onglet Événements (Globals)</h3>
<p>L'onglet est divisé en deux zones :</p>
<ul>
  <li><b>Panneau haut — liste des événements</b> : créer, renommer, supprimer, réordonner
      (↑/↓). Les événements peuvent être regroupés en <b>catégories</b> pour l'organisation
      visuelle.</li>
  <li><b>Panneau bas — sous-tabs "Conditions" et "Actions"</b> :</li>
</ul>
<p>Sous-tab <b>Conditions</b> :</p>
<ul>
  <li><b>Groupe AND (principal)</b> : toutes les conditions de cette liste doivent être
      vraies pour que l'événement se déclenche.</li>
  <li><b>Groupes OR</b> : créez des groupes alternatifs. L'événement se déclenche si le
      groupe AND passe OU si <i>toutes</i> les conditions de n'importe quel groupe OR
      passent.</li>
  <li>Si aucune condition n'est définie, l'événement se déclenche toujours.</li>
  <li>Chaque condition peut être <b>inversée (NON)</b>.</li>
</ul>
<p>Sous-tab <b>Actions</b> : 57 actions disponibles en 11 groupes (Audio, Visuel,
Navigation, Entités, Joueur, Flags/Variables, Triggers, Narration, RPG/Quête,
Système, Avancé). Bouton <b>Présets ▾</b> pour les combinaisons courantes.</p>

<h3>Logique de garde — résumé</h3>
<pre>Déclenchement si :
  (tous les AND) OU (tous les conds du groupe OR-0) OU (tous du groupe OR-1) OU ...
Aucune condition → toujours déclenché.</pre>

<h3>⚠️ L'ordre = index C</h3>
<p>Réordonner les événements change leurs valeurs <code>CEV_*</code> et invalide les
appels <code>emit_event(id)</code> dans les ROMs déjà compilées. En production,
<b>ajoutez toujours en fin de liste</b>.</p>

<h3>Consommer un événement depuis une scène (pont via flag)</h3>
<p>Les triggers de scène ne peuvent pas écouter directement les custom events.
Le pattern recommandé est le <b>pont flag</b> :</p>
<ol>
  <li>Action de l'événement personnalisé : <code>set_flag(N)</code></li>
  <li>Trigger de scène : condition <code>flag_set(N)</code> → actions + <code>clear_flag(N)</code></li>
</ol>
<p>Cela permet de réagir à n'importe quel custom event depuis n'importe quelle scène.</p>

<h3>Actions disponibles (57)</h3>
<table>
  <tr><th>Groupe</th><th>Actions</th></tr>
  <tr><td>Audio</td><td>play_sfx, start_bgm, stop_bgm, fade_bgm</td></tr>
  <tr><td>Visuel / Effets</td><td>play_anim, screen_shake, fade_out, fade_in</td></tr>
  <tr><td>Navigation</td><td>goto_scene, warp_to, set_checkpoint, respawn_player, reset_scene</td></tr>
  <tr><td>Entités</td><td>spawn_entity, show_entity, hide_entity, move_entity_to, spawn_wave,
      spawn_at_region, pause_entity_path, resume_entity_path</td></tr>
  <tr><td>Joueur</td><td>force_jump, lock_player_input, unlock_player_input,
      enable_multijump, disable_multijump, enable_wall_grab, disable_wall_grab,
      cycle_player_form, set_player_form, fire_player_shot, set_gravity_dir</td></tr>
  <tr><td>Flags / Variables</td><td>set_flag, clear_flag, set_variable, inc_variable, dec_variable</td></tr>
  <tr><td>Caméra / Scroll</td><td>set_scroll_speed, set_cam_target, pause_scroll, resume_scroll</td></tr>
  <tr><td>Triggers / HUD</td><td>enable_trigger, disable_trigger, add_score, add_health, set_health</td></tr>
  <tr><td>Narration / Dialogue</td><td>show_dialogue, play_cutscene, set_npc_dialogue</td></tr>
  <tr><td>RPG / Quête</td><td>give_item, remove_item, drop_item, drop_random_item, unlock_door, unlock_ability,
      set_quest_stage, add_resource, remove_resource</td></tr>
  <tr><td>Système</td><td>emit_event, save_game, end_game</td></tr>
</table>
<p><b>Note "actions template-dépendantes"</b> : certaines actions (<code>unlock_ability</code>,
<code>add_resource</code>, <code>set_gravity_dir</code>, <code>cycle_player_form</code>, etc.)
émettent la constante <code>TRIG_ACT_*</code> correcte mais nécessitent que votre
<b>template C</b> implémente le cas correspondant dans <code>ngpng_trigger_execute_action()</code>.
Elles sont disponibles dans l'engine comme "hooks" à brancher.</p>

<h3>Conditions de garde disponibles (88)</h3>
<p>Même vocabulaire que les triggers de scène et les type-events.
Organisées en 9 groupes dans le dialog :</p>
<table>
  <tr><th>Groupe</th><th>Exemples</th></tr>
  <tr><td>Joueur — boutons</td><td>btn_a, btn_b, btn_held_ge…</td></tr>
  <tr><td>Joueur — état</td><td>health_le, on_jump, on_land, score_ge, player_has_item, item_count_ge…</td></tr>
  <tr><td>Caméra / Scroll</td><td>cam_x_ge, cam_y_ge, enter_region, leave_region</td></tr>
  <tr><td>Timer / Vague</td><td>timer_ge, timer_every, wave_ge, scene_first_enter…</td></tr>
  <tr><td>Flags / Variables</td><td>flag_set, flag_clear, variable_ge, variable_eq…</td></tr>
  <tr><td>Entités — globales</td><td>enemy_count_le, entity_alive, entity_contact…</td></tr>
  <tr><td>Entités — par type</td><td>entity_type_all_dead, entity_type_count_ge…</td></tr>
  <tr><td>Quête / Narration</td><td>quest_stage_eq, dialogue_done, cutscene_done…</td></tr>
  <tr><td>Ressources / Aléatoire</td><td>resource_ge, chance</td></tr>
</table>

<h3>Export C — ngpc_custom_events.h</h3>
<pre>#define CEV_BOSS_PHASE_2    0u
#define CEV_KEY_COLLECTED   1u
#define CUSTOM_EVENT_COUNT      3   /* lignes d'action */
#define CUSTOM_EVENT_COND_COUNT 1   /* lignes de condition */

/* Struct condition de garde */
typedef struct {
    u8 event_id; u8 cond; u8 index; u16 value; u8 group_id; u8 negate;
} NgpngCevCond;
/* group_id = 0xFF → groupe AND principal, 0..N → groupe OR N */

static const NgpngCevCond g_cev_conds[] = {
    { CEV_BOSS_PHASE_2, 22u, 0u, 0u, 0xFFu, 0u }, /* flag_set[0] AND */
};

typedef struct {
    u8 event_id; u8 action; u8 a0; u8 a1; u8 once;
} NgpngEventAction;

static const NgpngEventAction g_custom_events[] = {
    { CEV_BOSS_PHASE_2,  2u, 2u, 0u, 0u },  /* start_bgm 2 */
    { CEV_BOSS_PHASE_2, 15u, 3u, 0u, 0u },  /* screen_shake 3 */
    { CEV_KEY_COLLECTED,31u, 0u, 0u, 0u },  /* inc_variable[0] */
};</pre>
<p>Le runtime évalue d'abord les gardes, puis les actions :</p>
<pre>void ngpc_emit_event(u8 id) {
    /* 1. Vérifier les conditions de garde (AND + OR groups) */
    if (!ngpng_cev_guard_passes(id)) return;
    /* 2. Exécuter toutes les actions liées à cet id */
    for (u8 i = 0; i &lt; CUSTOM_EVENT_COUNT; ++i)
        if (g_custom_events[i].event_id == id)
            ngpng_exec_action(&amp;g_custom_events[i]);
}</pre>
<p><b>Tree-shaking :</b> si <code>CUSTOM_EVENT_COUNT == 0</code>, la table est vide
et aucun symbole superflu n'est émis.</p>
"""


def _fr_vram() -> str:
    return """
<h1>VRAM Map</h1>

<h2>Vue d'ensemble</h2>
<p>L'onglet VRAM Map visualise l'utilisation des ressources de la console :</p>
<ul>
  <li><b>512 tile slots</b> — grille 32×16 (chaque cellule = un tile VRAM).</li>
  <li><b>16 palette slots sprites</b> — banque palettes sprites.</li>
  <li><b>16 palettes BG (SCR1)</b> et <b>16 palettes BG (SCR2)</b> — banques palettes des plans de scroll.</li>
</ul>
<p>Par défaut, le budget affiché correspond à la <b>scène sélectionnée</b> (comme dans l'onglet Projet).
Vous pouvez aussi choisir une autre scène directement dans ce tab, ou demander le <b>pire cas</b>.</p>
<p>Les valeurs peuvent afficher un <b>~</b> si elles sont estimées (fichiers manquants, ou outils d'export non trouvés).
Quand c'est possible, le calcul tente de reproduire le <b>vrai export</b> (déduplication des tiles).</p>

<h2>Code couleur — tile slots</h2>
<table>
  <tr><th>Couleur</th><th>Plage</th><th>Signification</th></tr>
  <tr><td style="background:#373747;color:#aaa">■ Gris foncé</td><td>0–31</td><td>Réservés (hardware)</td></tr>
  <tr><td style="background:#555565;color:#aaa">■ Gris moyen</td><td>32–127</td><td>Police système (BIOS SYSFONTSET)</td></tr>
  <tr><td style="background:#569ed6;color:#fff">■ Couleur</td><td>128+</td><td>Sprite</td></tr>
  <tr><td style="background:#4ec9b0;color:#fff">■ Couleur</td><td>128+</td><td>Tilemap</td></tr>
  <tr><td style="background:#f44747;color:#fff">■ Rouge</td><td>—</td><td>Conflit / overlap (deux assets sur les mêmes slots)</td></tr>
  <tr><td style="background:#1e1e28;color:#555">■ Noir</td><td>—</td><td>Libre</td></tr>
</table>
<p>En cas de conflit, une section <b>Suggestions</b> apparaît sous la grille pour proposer
une correction (ex: déplacer <code>spr_tile_base</code>, ou repacker les tilemaps).</p>

<h2>Survol</h2>
<p>Passez la souris sur une cellule pour voir son numéro de slot et son statut
(réservé / sysfont / sprite / libre) dans l'infobulle.</p>

<h2>Palette slots sprites — banque enrichie</h2>
<p>La section <b>Sprites (16)</b> affiche une banque de 16 slots avec, pour chaque slot occupé :</p>
<ul>
  <li><b>4 swatches couleur</b> représentant les 4 entrées de la palette hardware
      (index 0 = transparent = carré sombre).</li>
  <li><b>Badge ×N</b> en jaune si plusieurs sprites partagent ce slot via
      <code>fixed_palette</code>.</li>
  <li><b>Infobulle</b> : nom du ou des sprites propriétaires.</li>
  <li><b>Clic</b> : ouvre directement le sprite dans l'onglet Palette.</li>
</ul>
<p>Les palettes BG (<b>SCR1</b> et <b>SCR2</b>) conservent l'affichage en barre simple.</p>
<p>Le tool affiche aussi une <b>analyse de banques identiques</b> par plane : si deux tilemaps d'une scène réutilisent exactement les mêmes palettes BG sur SCR1 ou SCR2, l'onglet VRAM le signale. C'est une aide au diagnostic; il n'y a pas encore de dédup automatique à l'export.</p>

<h2>Mise à jour automatique</h2>
<p>La carte est rafraîchie automatiquement quand vous sélectionnez une scène
dans l'onglet Projet ou quand le projet est modifié.</p>
"""


def _fr_bundle() -> str:
    return """
<h1>Bundle (packer de scène)</h1>

<h2>Rôle</h2>
<p>L'onglet Bundle travaille directement sur les <b>sprites de la scène active</b>
(même liste que l'onglet Projet). Son but est de :</p>
<ul>
  <li>calculer les <code>tile_base</code> / <code>pal_base</code> en cascade,</li>
  <li>visualiser le budget,</li>
  <li>exporter en batch avec les bons <code>--tile-base</code> / <code>--pal-base</code>.</li>
</ul>

<h2>Paramètres de départ</h2>
<table>
  <tr><th>Champ</th><th>Défaut</th><th>Description</th></tr>
  <tr><td><b>tile_base départ</b></td><td>256</td><td>Premier slot VRAM tile pour les sprites de cette scène (<code>scene.spr_tile_base</code>)</td></tr>
  <tr><td><b>pal_base départ</b></td><td>0</td><td>Premier slot palette sprite de cette scène (<code>scene.spr_pal_base</code>)</td></tr>
</table>
<p>Ces valeurs sont stockées dans la scène (dans le <code>.ngpcraft</code>), pas dans une config globale.</p>

<h2>Tableau des sprites</h2>
<p>Chaque ligne correspond à un sprite de la scène. Les colonnes calculées se mettent à jour automatiquement.</p>
<table>
  <tr><th>Colonne</th><th>Description</th></tr>
  <tr><td><b>#</b></td><td>Ordre d'export (commence à 1)</td></tr>
  <tr><td><b>Img</b></td><td>Miniature (aperçu visuel rapide)</td></tr>
  <tr><td><b>Fichier</b></td><td>Nom du PNG source</td></tr>
  <tr><td><b>W / H</b></td><td>Taille d'une frame (modifiable, multiples de 8 conseillés)</td></tr>
  <tr><td><b>Fr.</b></td><td>Nombre de frames (modifiable)</td></tr>
  <tr><td><b>Reuse pal</b></td><td>Partage le slot palette du sprite précédent (valide seulement si <code>fixed_palette</code> est identique et que le sprite n'utilise qu'1 palette)</td></tr>
  <tr><td><b>Tiles~</b></td><td>Nombre de tiles uniques (si <code>ngpc_sprite_export.py</code> est disponible). Préfixe <code>~</code> = estimation</td></tr>
  <tr><td><b>tile_base</b></td><td>Slot VRAM calculé automatiquement</td></tr>
  <tr><td><b>pal_base</b></td><td>Slot palette calculé automatiquement</td></tr>
</table>

<h2>Actions</h2>
<ul>
  <li><b>+ Ajouter…</b> — ajoute un sprite à la scène active (puis configure W/H/Fr.).</li>
  <li><b>Drag & drop</b> — vous pouvez aussi réordonner les sprites en glissant-déposant une ligne dans le tableau.</li>
  <li><b>↑ / ↓</b> — réordonne les sprites de la scène (impacte aussi l'onglet Projet).</li>
  <li><b>Ouvrir dans Palette</b> — ouvre l'entrée sélectionnée dans l'onglet Palette avec la config anim.</li>
  <li><b>✕ Retirer</b> — supprime l'entrée sélectionnée.</li>
  <li><b>▶ Exporter tout</b> — appelle <code>ngpc_sprite_export.py</code> pour chaque sprite de la scène,
      dans l'ordre, avec les bons <code>--tile-base</code> et <code>--pal-base</code>.</li>
  <li><b>Sauvegarder config</b> — sauvegarde le projet (<code>.ngpcraft</code>).</li>
</ul>

<h2>Budget et overflow</h2>
<p>Le budget total est affiché sous le tableau. Si le bundle dépasse 512 tiles ou
16 palettes, un avertissement ⚠ apparaît <b>avant</b> de lancer l'export.</p>

<h2>Log d'export</h2>
<p>Le panneau du bas affiche le résultat de chaque export :</p>
<pre>[OK] player — 4 tiles, pal 0
[OK] enemy1 — 1 tile, pal 1
[SKIP] boss — fichier introuvable</pre>
"""


def _fr_tilemap() -> str:
    return """
<h1>Tilemap Preview</h1>

<h2>Rôle</h2>
<p>L'onglet Tilemap ouvre un PNG et affiche une <b>grille de tiles 8×8</b>
colorée selon le nombre de couleurs opaques dans chaque tile.
C'est un prédiagnostic avant de lancer <code>ngpc_tilemap.py</code>.</p>
<p><b>Tailles (NGPC)</b> : l’écran visible est 20×19 tiles (160×152 px). La fenêtre VRAM BG est de 32×32 tiles — mais les maps plus grandes sont supportées grâce au <b>streaming automatique</b> généré à l’export (voir section ci-dessous).
Le tool affiche un rappel directement dans l’onglet quand la taille dépasse 32×32.</p>
<p><b>Checklist</b> : juste sous l'aide contextuelle, une mini checklist résume aussi si le PNG source est chargé/sauvé, si la taille reste dans les limites NGPC, si les tiles demandent un split SCR1/SCR2, si la collision est prête, et si l'export <code>ngpc_tilemap.py</code> peut partir.</p>
<p><b>Interface</b> : la zone haute garde un <b>sélecteur compact</b> pour les tilemaps de la scène active, mais les réglages secondaires passent maintenant derrière un bouton <b>Options</b>. Le <b>zoom</b>, lui, reste visible en permanence pour ne pas casser le workflow d’édition.</p>

<h2>Code couleur</h2>
<table>
  <tr><th>Couleur</th><th>Nb couleurs</th><th>Signification</th></tr>
  <tr><td><span style="color:#00c850">■ Vert</span></td><td>1 – 3</td>
      <td>OK — tile exportable en single-layer</td></tr>
  <tr><td><span style="color:#ffa000">■ Orange</span></td><td>4</td>
      <td>Limite — peut poser problème selon la config palette</td></tr>
  <tr><td><span style="color:#ff2020">■ Rouge</span></td><td>5+</td>
      <td>Erreur — tile nécessite un dual-layer ou une réduction de couleurs</td></tr>
</table>

<h2>Zoom</h2>
<p>Les boutons <code>×1 ×2 ×4 ×8 ×16 ×32</code> zooment la grille en nearest-neighbor.
Activez <b>Grille</b> pour afficher les lignes 8×8 (très utile à ×1/×2).
Le survol d'une tile affiche ses coordonnées et son nombre de couleurs en infobulle.</p>

<h2>Édition (peinture par tuile)</h2>
<p>Un mini-mode d'édition permet de <b>copier/coller des tiles 8×8</b> directement dans ce PNG :</p>
<ul>
  <li>Activez <b>Édition</b>.</li>
  <li><b>Outils</b> : utilisez les boutons <b>Peindre / Pipette / Effacer / Remplir / Remplacer / Sélection / Tampon</b>.</li>
  <li><b>Tampon</b> : un rectangle cyan (preview) montre la zone qui sera collée au survol. Vous pouvez l’alimenter soit avec <b>Ctrl+C</b> sur une sélection de la map, soit en <b>sélectionnant plusieurs tiles dans le tileset</b>.</li>
  <li><b>Forme</b> : pour <b>Peindre</b>, <b>Effacer</b> et <b>Tampon</b>, le sélecteur <b>Forme</b> permet maintenant de travailler en <b>Libre</b>, <b>Rect</b> ou <b>Ellipse</b>. En mode Rect/Ellipse, cliquez-glissez pour prévisualiser puis appliquer la forme au relâchement.</li>
  <li><b>Presets de tampon</b> : le bloc <b>Mémoriser / Charger / Suppr</b> permet aussi de garder des tampons nommés réutilisables. Ils sont stockés dans les réglages du tool, pas dans la tilemap elle-même.</li>
  <li><b>Variation</b> : avec plusieurs tiles sélectionnées dans le tileset, cocher <b>Variation</b> prépare une brosse aléatoire au lieu d'un tampon. C'est utile pour casser les répétitions sur `Peindre`, `Remplir` et `Remplacer` sans quitter le flux d'édition.</li>
  <li><b>Raccourcis...</b> : le bouton ouvre un petit éditeur de raccourcis pour les outils Tilemap (`Peindre`, `Pipette`, `Effacer`, `Remplir`, `Remplacer`, `Sélection`, `Tampon`) et les transformations de tampon (`Flip H`, `Flip V`, `Rot 90`). Les raccourcis standards `Ctrl+Z/Ctrl+S/Ctrl+C/Ctrl+V` ne sont pas concernés.</li>
  <li><b>Raccourcis outils</b> : B=peindre, P=pipette, E=effacer, F=remplir, R=remplacer, S=sélection, M=tampon (personnalisables via "Raccourcis…").</li>
  <li><b>Raccourcis fichiers</b> : <code>Ctrl+O</code>=ouvrir, <code>Ctrl+N</code>=nouveau, <code>Ctrl+S</code>=enregistrer.</li>
  <li><b>F5</b> : lancer <code>ngpc_tilemap.py</code> sur le fichier courant.</li>
  <li><b>Tileset</b> : cliquez une tile à gauche pour la prendre comme <b>brosse</b>. Une <b>sélection multiple</b> dans le tileset prépare automatiquement un <b>tampon</b>.</li>
  <li><b>Charger…</b> : charge un tileset depuis un autre PNG (bouton dans le panneau Tileset). En mode projet, le chemin peut être mémorisé pour l’auto-chargement.</li>
  <li><b>Alt+clic</b> sur une tile de la map : pipette (prend la tile comme <b>brosse</b>).</li>
  <li><b>Clic gauche</b> : peint (colle) la brosse.</li>
  <li><b>Clic droit</b> : efface la tile (tuile transparente).</li>
  <li><b>Glisser</b> : maintenez le clic gauche/droit et déplacez la souris pour peindre/effacer plusieurs tiles.</li>
  <li><b>Shift+clic</b> : trace une ligne avec la brosse courante. Le remplissage reste sur l'outil <b>Remplir</b>.</li>
  <li><b>Ctrl+clic</b> : remplace toutes les tiles identiques dans la map.</li>
  <li><b>Sélection</b> : glisser pour sélectionner une zone. <b>Ctrl+C</b> copie, <b>Ctrl+X</b> coupe, <b>Ctrl+V</b> colle, <b>Suppr</b> efface.</li>
  <li><b>Undo/Redo</b> : Ctrl+Z / Ctrl+Y.</li>
  <li><b>Enregistrer</b> : Ctrl+S.</li>
  <li><b>Redimensionner…</b> : change la taille du canvas (en tiles) et colle le contenu selon une ancre.</li>
</ul>

<h2>Collision (tileset)</h2>
<p>Le sous-onglet <b>Collision</b> permet d'assigner un <b>type de collision par tile unique</b>
(NONE/SOLID/PLATFORM/...). L'overlay coloré s'affiche sur la map, et vous pouvez :</p>
<ul>
  <li><b>Overlay</b> : choisir <b>max</b> (combine SCR1/SCR2) ou <b>SCR1</b>/<b>SCR2</b> pour visualiser un plan.</li>
  <li><b>Exporter .h…</b> : génère un header <code>*_col.h</code> indexé par tile (même ordre que l’export tilemap).</li>
  <li><b>Sauver projet</b> : enregistre la table de collision dans le <code>.ngpcraft</code> (si un projet est ouvert).</li>
</ul>

<h2>SCR1 / SCR2</h2>
<p>Si des tiles dépassent 3 couleurs opaques, l'export peut basculer en <b>2 layers</b> :
SCR1 et SCR2 sont les <b>2 plans de scroll</b> NGPC. Selon la priorité que vous définissez
dans le code jeu, SCR1 peut être devant SCR2 (ou l’inverse). Le bouton
<b>Export SCR1/SCR2 PNG</b> génère deux PNG (<code>_scr1.png</code> / <code>_scr2.png</code>)
pour inspecter/retoucher le résultat du split.</p>

<h2>Plan cible (SCR1/SCR2)</h2>
<p>Le champ <b>Plan cible</b> est une <b>métadonnée projet</b> : si la tilemap est single-layer,
il indique sur quel plan de scroll (SCR1/SCR2) vous comptez la charger dans votre code jeu.
Cela sert principalement au <b>budget palettes BG</b> dans l’onglet VRAM. Si l’export est dual-layer
(SCR1+SCR2), ce champ est ignoré.</p>

<h2>Statistiques</h2>
<ul>
  <li><b>Total</b> — nombre de tiles (largeur/8 × hauteur/8).</li>
  <li><b>OK / Limite / Erreur</b> — répartition par catégorie.</li>
  <li><b>Tiles uniques</b> — estimation après déduplication (même données pixel ⇒ même tile).</li>
  <li><b>Résultat prévu</b> — "single-layer ✓" si toutes les tiles sont ≤ 3 couleurs,
      "dual-layer requis ⚠" sinon.</li>
</ul>

<h2>Lancer ngpc_tilemap.py</h2>
<p>Le bouton <b>Générer fichiers C</b> exécute <code>ngpc_tilemap.py</code> et écrit un fichier
<code>_map.c</code> (et optionnellement <code>.h</code>) à côté du PNG.</p>
<ul>
  <li>Si <b>SCR2</b> est renseigné : export dual-layer explicite (SCR1+SCR2).</li>
  <li>Sinon : si une tile dépasse 3 couleurs, le script passe automatiquement en <b>auto-split</b> (SCR1+SCR2).</li>
</ul>

<h2>Compression des tiles (optionnel)</h2>
<p>La ligne <b>Compresser tiles</b> active une passe de compression après l'export
<code>ngpc_tilemap.py</code>. Le script <code>tools/ngpc_compress.py</code> est lancé
automatiquement et produit un <code>*_lz.c</code> ou <code>*_rle.c</code> + son <code>.h</code>
— données compressées prêtes à décompresser en VRAM au runtime.</p>
<table>
  <tr><th>Mode</th><th>Ratio typique</th><th>Cas d'usage</th></tr>
  <tr><td><b>Auto (plus petit)</b></td><td>—</td><td>Teste LZ77 et RLE, garde le résultat le plus court</td></tr>
  <tr><td><b>LZ77</b></td><td>~3:1 à 4:1</td><td>Tilesets variés — meilleur taux général</td></tr>
  <tr><td><b>RLE</b></td><td>~2:1</td><td>Zones uniformes (ciel, murs solides) — décompression ultra-rapide</td></tr>
</table>
<p><b>Runtime :</b> au lieu de <code>NGP_TILEMAP_LOAD_TILES_VRAM</code>, utilisez les fonctions
<code>ngpc_lz.h</code> :</p>
<pre>#include "niveau1_tiles_lz.h"
ngpc_lz_to_tiles(niveau1_tiles_lz, niveau1_tiles_lz_len, 128);
// ou
#include "niveau1_tiles_rle.h"
ngpc_rle_to_tiles(niveau1_tiles_rle, niveau1_tiles_rle_len, 128);</pre>
<p>Le header généré exporte <code>extern const u8 name_lz[]</code> et
<code>extern const u16 name_lz_len</code> (ou <code>_rle</code>).</p>
<p><b>Limite :</b> le buffer interne fait <b>2 Ko</b> (~128 tiles max par appel).
Pour des tilesets plus larges, fractionnez en plusieurs appels avec offset croissant,
ou utilisez les tiles non-compressées.</p>

<h2>Conseils</h2>
<ul>
  <li>Si des tiles sont rouges, retouchez le PNG dans Aseprite pour réduire le nombre
      de couleurs par zone 8×8.</li>
  <li>Alternative : laissez <code>ngpc_tilemap.py</code> générer SCR1+SCR2 automatiquement (auto-split),
      puis utilisez <b>Export SCR1/SCR2 PNG</b> si vous voulez contrôler manuellement le résultat.</li>
  <li>La contrainte ≤ 3 couleurs opaques s'applique <b>par tile 8×8</b>, pas à l'image entière —
      une image avec 20 couleurs peut être parfaitement valide si elles ne se mélangent pas
      dans la même tile.</li>
</ul>

<h2>Grandes tilemaps (streaming automatique)</h2>
<p>Il est possible d'utiliser des backgrounds <b>plus grands que 32×32 tiles</b>. Le matériel NGPC
a une fenêtre VRAM de 32×32, mais on exploite son comportement toroïdal : quand la caméra avance,
les colonnes/lignes hors-écran sont réécrites en VRAM à la volée (streaming).</p>
<p><b>Pour les projets PNG Manager :</b> le workflow est identique à une tilemap normale.
Exportez simplement la grande PNG en background de scène — l'export génère automatiquement
<code>scene_X_stream_planes()</code> qui est appelée chaque frame. Aucun code à ajouter.</p>
<table>
  <tr><th>Tiles uniques</th><th>Statut</th></tr>
  <tr><td>≤ 256</td><td>✅ Confortable — marge pour les sprites</td></tr>
  <tr><td>257 – 320</td><td>⚠ Attention — peu de marge sprites</td></tr>
  <tr><td>321 – 384</td><td>🔶 Limite critique</td></tr>
  <tr><td>&gt; 384</td><td>🔴 Dépassement VRAM — à éviter</td></tr>
</table>
<p><b>Conseil :</b> utilisez des tiles répétées (sol, ciel, mur) — un niveau 128×32 tient souvent
en 50–100 tiles uniques. Tailles recommandées : platformer 64–128×20, shmup 20×64–128,
top-down 64×64.</p>

"""


def _fr_pipeline() -> str:
    return """
<h1>Pipeline d'export</h1>

<h2>Vue d'ensemble</h2>
<pre>PNG source
  │
  ▼  (NgpCraft Engine — onglet Palette)
PNG remappé RGB444
  │
  ▼  (ngpc_sprite_export.py)
*_mspr.c + *_mspr.h
  │
  ▼  (Makefile / ngpc_sprite_bundle.py)
ROM cartouche (.ngp)</pre>

<h2>Mode headless (CLI)</h2>
<p>Le point d'entrée <code>ngpcraft_engine.py</code> peut exporter un projet sans lancer l'interface Qt.
Le mode headless réutilise le même moteur d'export que l'onglet <b>Projet</b> et génère les mêmes
fichiers C, headers et rapports.</p>
<pre>python ngpcraft_engine.py --export project.ngpcraft
python ngpcraft_engine.py --export project.ngpcraft --scene Acte1
python ngpcraft_engine.py --export project.ngpcraft --sprite-tool /path/to/ngpc_sprite_export.py
python ngpcraft_engine.py --export project.ngpcraft --tilemap-tool /path/to/ngpc_tilemap.py
python ngpcraft_engine.py --validation-suite path/to/output_folder
python ngpcraft_engine.py --validation-run path/to/output_folder
python ngpcraft_engine.py --validation-run path/to/output_folder --build
python ngpcraft_engine.py --validation-run path/to/output_folder --build --smoke-run</pre>
<p><b>Validation suite :</b> <code>--validation-suite</code> scaffold 4 mini-projets depuis le vrai template
(`Sprite Lab`, `Mini Shmup`, `Mini Platformer`, `Mini Top-Down`) pour valider le pipeline complet sur des cas réalistes.</p>
<p><b>Validation run :</b> <code>--validation-run</code> va plus loin : il génère ces 4 projets, lance l'export headless sur chacun, puis écrit un rapport <code>VALIDATION_RUN.md</code> + <code>validation_run.json</code>.</p>
<p><b>Validation run + build :</b> avec <code>--build</code>, la routine lance aussi <code>make</code> dans chaque projet généré après export. Le rapport inclut alors aussi l'état build par projet.</p>
<p>Note : ce mode suppose une toolchain NGPC vraiment installée et exécutable (<code>make</code>, cc900/T900, outils annexes).</p>
<p><b>Validation run + smoke runtime :</b> avec <code>--smoke-run</code>, la routine cherche ensuite la ROM la plus récente et tente un lancement rapide dans un émulateur si un binaire est trouvé dans le <code>PATH</code> (ou via la variable d'environnement <code>NGPNG_SMOKE_EMULATOR</code>). Si aucun émulateur n'est trouvé, le rapport note simplement un smoke test ignoré.</p>

<h2>Dossier d'export + Makefile (assets_autogen.mk)</h2>
<p>Dans l'onglet <b>Projet</b>, le champ <b>Dossier export</b> permet d'écrire tous les
<code>.c/.h</code> générés dans un dossier unique (ex: <code>GraphX/gen</code>) au lieu de les
générer à côté des PNG.</p>
<p>Quand <b>Dossier export</b> est renseigné, NgpCraft Engine génère aussi automatiquement
un fichier <code>assets_autogen.mk</code> dans ce dossier, qui ajoute les objets compilés à
<code>OBJS</code> (plus besoin d'éditer la liste à la main).</p>
<pre># Exemple Makefile (template)
include GraphX/gen/assets_autogen.mk</pre>
<p><b>Débutant (zéro code)</b> : utilisez le bouton <b>Export (prêt à compiler)</b> (onglet Projet).
Il exporte toutes les scènes, puis <b>patch automatiquement le makefile</b> et écrit <code>src/ngpng_autorun_main.c</code>
pour que vous puissiez compiler/lancer immédiatement, sans éditer de code.</p>
<p><b>Désactiver l’autorun :</b> passez <code>NGPNG_AUTORUN=0</code> à make (ou via l’environnement) pour garder <code>src/main.c</code>.
<b>Rollback :</b> restaurez <code>makefile.bak_ngpng</code> (créé une seule fois) et supprimez <code>src/ngpng_autorun_main.c</code>.</p>
<p><b>Audio (autorun) :</b> si l’audio est activé (<code>NGP_ENABLE_SOUND=1</code>) et qu’un mapping SFX existe,
<b>A</b> joue le SFX courant et <b>OPTION</b> change l’ID. La BGM peut démarrer automatiquement via
<code>SCENE_*_BGM_AUTOSTART</code>.</p>
<p>Quand vous exportez une <b>scène</b> (bouton <b>Scène → .c</b>), le tool génère aussi :</p>
<ul>
  <li>un header <code>scene_*.h</code> (loader template-ready) avec :
      <code>scene_xxx_blit_tilemaps()</code>, <code>scene_xxx_load_sprites()</code>, <code>scene_xxx_load_all()</code>,
      <code>scene_xxx_enter()</code>, <code>scene_xxx_exit()</code>, <code>scene_xxx_update()</code></li>
  <li>un header <code>scene_*_level.h</code> (gameplay) : entités/vagues + collision + layout/scroll</li>
  <li>un manifest global <code>scenes_autogen.c/.h</code> (liste des scènes déjà exportées + metadata + hooks)</li>
</ul>
<p><b>Usage minimal côté jeu :</b> <code>#include "scenes_autogen.h"</code>, puis
<code>g_ngp_scenes[NGP_SCENE_START_INDEX].enter();</code> et appelez
<code>g_ngp_scenes[i].update();</code> à chaque frame.</p>
<p>Le header <code>scene_*.h</code> inclut automatiquement <code>scene_*_level.h</code>,
donc une seule inclusion côté jeu suffit.</p>

<h3>Audio (optionnel)</h3>
<p><b>Format pris en charge : export hybride C uniquement.</b>
Dans Sound Creator, utilisez <i>Projet → Exporter tout</i> (mode C). Cela génère
<code>project_audio_manifest.txt</code>, <code>project_instruments.c</code>, <code>project_sfx.c</code>
et un <code>song_*.c</code> par BGM. Le driver PSG (<code>sounds.c</code>) est embarqué en ROM et interprète
les bytecodes à runtime. Sans <code>project_instruments.c</code>, la BGM ne peut pas jouer.</p>
<p>Si <code>NGP_ENABLE_SOUND</code> est activé dans le template, le header <code>scene_*.h</code> fournit :</p>
<ul>
  <li><code>scene_xxx_enter()</code> : équivalent de <code>scene_xxx_load_all()</code> + <code>scene_xxx_audio_enter()</code>.</li>
  <li><code>scene_xxx_audio_enter()</code> : lance la BGM si <code>SCENE_*_BGM_AUTOSTART</code> est vrai.</li>
  <li><code>scene_xxx_audio_update()</code> : appelle <code>Sounds_Update()</code> (à appeler chaque frame).</li>
  <li><code>scene_xxx_audio_exit()</code> : fade-out optionnel (<code>SCENE_*_BGM_FADE_OUT</code>).</li>
</ul>
<p><b>Build:</b> si vous utilisez les exports “Project Export All” de Sound Creator, NgpCraft Engine peut générer
un <code>audio_autogen.mk</code> (dans <code>export_dir</code> quand il est configuré) pour ajouter automatiquement
les <code>.c</code> exportés à <code>OBJS</code> (garde le build propre, sans edits manuels). Le fichier encapsule la liste
sous <code>ifneq ($(strip $(NGP_ENABLE_SOUND)),0)</code>.</p>
<p><b>Note:</b> <code>assets_autogen.mk</code> fait automatiquement un <code>-include audio_autogen.mk</code>
(dans le même dossier), donc en pratique il suffit de garder l’include template
<code>include GraphX/gen/assets_autogen.mk</code>.</p>
<p><b>SFX:</b> le panneau Audio permet de définir un mapping “IDs gameplay → IDs Sound Creator” et l’export peut générer
<code>ngpc_project_sfx_map.h</code> (enum + table) pour l’intégration côté jeu.</p>
<p>Si un mapping SFX est défini, NgpCraft Engine génère aussi <code>sounds_game_sfx_autogen.c</code> (dans <code>exports/</code> côté audio)
et active automatiquement <code>SFX_PLAY_EXTERNAL=1</code> via <code>audio_autogen.mk</code>.</p>
<p>Si le manifest audio est en mode <code>ASM</code>, l’autogen SFX est désactivé (il faut les exports C : <code>project_sfx.c</code>).</p>

<h2>Watchdog dans les boucles d'init longues</h2>
<p>Le watchdog NGPC <b>doit recevoir <code>0x4E</code> toutes les ~100 ms</b> ou le CPU redémarre silencieusement.
En jeu, le VBlank (60 fps ≈ 16 ms) le kické automatiquement dans <code>isr_vblank()</code>.</p>
<p><b>Risque :</b> une boucle d'initialisation longue qui s'exécute <i>avant</i> le premier VBlank
(upload de tiles, clear de tilemap, décompression, génération procédurale…) peut dépasser 100 ms
et provoquer un reset. Symptôme : écran blanc ou retour au menu BIOS au démarrage.</p>
<p><b>Pattern (kick toutes les ~64 itérations) :</b></p>
<pre>u16 _wdog = 0;
while (...) {
    /* ... travail ... */
    if ((++_wdog &amp; 63u) == 0u)
        HW_WATCHDOG = WATCHDOG_CLEAR;  /* = *(u8*)0x006F = 0x4E */
}</pre>
<p>64 itérations est un choix conservateur : sur T900 à 6.144 MHz, même une boucle très lente
reste largement sous le budget de 100 ms par tranche de 64 tours.</p>
<p>Référence : <i>Metal Slug 1st Mission</i> (disassembly §4.2 / §17.3) — même pattern utilisé
dans tous les loaders ROM natifs.</p>

<h2>ngpc_sprite_export.py</h2>
<p>Convertit un PNG spritesheet en données C prêtes à charger en VRAM.</p>
<pre>python tools/ngpc_sprite_export.py GraphX/player.png \\
    -o GraphX/player_mspr.c \\
    --frame-w 16 --frame-h 16 \\
    --tile-base 256 --pal-base 0 \\
    --header</pre>
<table>
  <tr><th>Option</th><th>Description</th></tr>
  <tr><td><code>--tile-base N</code></td><td>Premier slot tile en VRAM (défaut 0)</td></tr>
  <tr><td><code>--pal-base N</code></td><td>Premier slot palette (0-15)</td></tr>
  <tr><td><code>--fixed-palette A,B,C,D</code></td><td>Force une palette RGB444 externe (partage)</td></tr>
  <tr><td><code>--frame-count N</code></td><td>Nombre de frames à exporter (0 = toutes)</td></tr>
  <tr><td><code>--anim-duration N</code></td><td>Durée par frame dans la table d'animation</td></tr>
</table>

<h2>ngpc_sprite_bundle.py</h2>
<p>Exporte plusieurs sprites en séquence en gérant automatiquement
<code>tile_base</code> et <code>pal_base</code>.</p>
<pre>from ngpc_sprite_bundle import SpriteBundle, make_sheet, load_rgba

bundle = SpriteBundle(project_root, out_dir, gen_dir, tile_base=256, pal_base=0)
bundle.export("player", player_sheet, 16, 16)
bundle.export("enemy",  enemy_sheet,  8,  8)</pre>

<h2>Partage de palette (--fixed-palette)</h2>
<p>Deux sprites qui partagent exactement les mêmes couleurs peuvent réutiliser
le même slot palette — économisant un des 16 slots disponibles.</p>
<ol>
  <li>Exportez le premier sprite normalement → 1 palette consommée.</li>
  <li>Dans NgpCraft Engine, copiez <code>--fixed-palette</code> depuis l'onglet Palette.</li>
  <li>Exportez le second sprite avec cet argument → 0 palette supplémentaire.</li>
</ol>

<h2>Fichiers générés</h2>
<table>
  <tr><th>Symbole</th><th>Type</th><th>Contenu</th></tr>
  <tr><td><code>name_tiles[]</code></td><td>const u16[]</td><td>Données 2bpp des tiles</td></tr>
  <tr><td><code>name_tiles_count</code></td><td>const u16</td><td>Nb de mots u16 (= nb_tiles × 8)</td></tr>
  <tr><td><code>name_palettes[]</code></td><td>const u16[]</td><td>Mots RGB444 (4 × nb palettes)</td></tr>
  <tr><td><code>name_tile_base</code></td><td>const u16</td><td>Slot tile de départ en VRAM</td></tr>
  <tr><td><code>name_pal_base</code></td><td>const u8</td><td>Slot palette de départ (0-15)</td></tr>
  <tr><td><code>name_frame_N</code></td><td>NgpcMetasprite</td><td>Structure metasprite par frame</td></tr>
  <tr><td><code>name_anim[]</code></td><td>MsprAnimFrame[]</td><td>Table d'animation</td></tr>
</table>

<h2>ngpc_compress.py — Compression des tiles</h2>
<p>Compresse des données binaires (tiles, maps) en <b>RLE</b> ou <b>LZ77/LZSS</b>.
Le format de sortie correspond au décompresseur intégré dans <code>src/ngpc_lz.c</code>.</p>
<pre>python tools/ngpc_compress.py niveau1_tiles.bin -o niveau1_tiles_lz.c -m lz77 --header
python tools/ngpc_compress.py niveau1_tiles.bin -o niveau1_tiles_rle.c -m rle --header
python tools/ngpc_compress.py niveau1_tiles.bin -o niveau1_tiles_best.c -m both --header</pre>
<table>
  <tr><th>Option</th><th>Description</th></tr>
  <tr><td><code>-m rle</code></td><td>Compression RLE (~2:1, décompression ultra-rapide)</td></tr>
  <tr><td><code>-m lz77</code></td><td>Compression LZ77/LZSS (~3:1 à 4:1, meilleur taux général)</td></tr>
  <tr><td><code>-m both</code></td><td>Génère les deux, garde le plus court</td></tr>
  <tr><td><code>--header</code></td><td>Génère aussi le <code>.h</code> avec les déclarations <code>extern</code></td></tr>
  <tr><td><code>-n NOM</code></td><td>Préfixe du tableau C (défaut : déduit du nom de fichier)</td></tr>
</table>
<p><b>Intégration projet :</b> dans l'onglet Tilemap, la case <b>Compresser tiles</b> lance
automatiquement <code>ngpc_compress.py</code> après <code>ngpc_tilemap.py</code>. Le mode
<b>Auto (plus petit)</b> teste les deux algos et garde le résultat le plus court.
Côté jeu, remplacez <code>NGP_TILEMAP_LOAD_TILES_VRAM</code> par
<code>ngpc_lz_to_tiles()</code> ou <code>ngpc_rle_to_tiles()</code> — mêmes paramètres sauf les données sources.</p>
"""


def _fr_editor() -> str:
    return """
<h1>Éditeur (retouche)</h1>

<p>L'onglet <b>Éditeur</b> est un mini-outil pour corriger vite un pixel/une tuile
<b>sans sortir vers Aseprite</b>. Il ne cherche pas à remplacer un vrai éditeur.</p>
<p><i>Astuce :</i> survolez les boutons/réglages pour afficher une courte aide (tooltips).</p>

<h2>Ouvrir / sauvegarder</h2>
<ul>
  <li><b>Ouvrir…</b> charge un PNG (PNG/BMP/GIF) — raccourci : <code>Ctrl+O</code>.</li>
  <li><b>Enregistrer</b> écrase le fichier sur disque — raccourci : <code>Ctrl+S</code>.</li>
  <li><b>Enregistrer sous…</b> sauvegarde une copie — raccourci : <code>Ctrl+Shift+S</code>.</li>
  <li><b>Rechargement auto</b> peut recharger le fichier s'il change sur disque (workflow Aseprite).</li>
</ul>

<h2>Palette RGB444</h2>
<p>Tous les pixels opaques sont <b>snap</b> automatiquement sur la grille RGB444 (valeurs NGPC).</p>

<h2>Zoom</h2>
<p>Boutons <code>×1 ×2 ×4 ×8 ×16 ×32</code> (raccourcis : <code>Ctrl+molette</code> / <code>Ctrl++</code> / <code>Ctrl+-</code>).</p>

<h2>Charger une palette d'un autre sprite</h2>
<ul>
  <li><b>Charger palette…</b> : extrait la palette RGB444 d'un autre PNG.</li>
  <li><b>Scène → Palette</b> : charge directement la palette d'un sprite de la scène active (mode projet).</li>
  <li><b>Appliquer</b> : remappe les pixels opaques vers la <b>couleur la plus proche</b> de cette palette.</li>
  <li><b>Mapping manuel…</b> : associe couleur-par-couleur (utile pour partager exactement une palette).</li>
</ul>

<h2>Outils</h2>
<ul>
  <li><b>Crayon</b> : dessine en couleur (snap RGB444).</li>
  <li><b>Gomme</b> : rend transparent.</li>
  <li><b>Pipette</b> : récupère la couleur d'un pixel.</li>
  <li><b>Pot</b> : remplissage (flood fill) de la zone.</li>
  <li><b>Sélection</b> : sélection rectangulaire (restreint les éditions).</li>
</ul>
<p>Raccourcis : <code>P</code>=crayon, <code>E</code>=gomme, <code>I</code>=pipette, <code>F</code>=pot, <code>Ctrl+S</code>=enregistrer.</p>
<p>Sélection : <code>S</code>=outil, <code>Ctrl+C</code>=copier, <code>Ctrl+X</code>=couper, <code>Ctrl+V</code>=coller, <code>Ctrl+A</code>=tout, <code>Del</code>=effacer pixels, <code>Esc</code>=désélectionner.</p>
<p><b>Brosse</b> : taille 1/2/3. <b>Sym H/Sym V</b> : dessine en miroir (raccourcis <code>H</code> / <code>V</code>).</p>
<p>Survol : le pixel survolé est mis en surbrillance et ses infos sont affichées (coordonnées, tile, couleur).</p>
<p><b>Remplacer couleur…</b> : appuyez <code>R</code>, cliquez une couleur source, puis choisissez la couleur cible.</p>

<h2>Grille & contraintes</h2>
<p><b>Astuce :</b> clic droit = gomme temporaire (et clic droit avec <b>Pot</b> = fill transparent).</p>
<ul>
  <li><b>Grille 8×8</b> : repère les tiles NGPC.</li>
  <li><b>Overlay tiles</b> : colore les tiles selon le nombre de couleurs opaques
      (vert ≤3 / orange 4 / rouge 5+).</li>
</ul>
<p>Raccourcis : <code>G</code>=grille, <code>O</code>=overlay.</p>

<h2>Opérations</h2>
<ul>
  <li><b>Flip H</b> : miroir horizontal — raccourci : <code>Ctrl+[</code>.</li>
  <li><b>Flip V</b> : miroir vertical — raccourci : <code>Ctrl+]</code>.</li>
  <li><b>Rot -90</b> : rotation 90° CCW — raccourci : <code>Ctrl+Shift+[</code>.</li>
  <li><b>Rot +90</b> : rotation 90° CW — raccourci : <code>Ctrl+Shift+]</code>.</li>
</ul>

<h2>Undo / Redo</h2>
<p>Les raccourcis <code>Ctrl+Z</code> et <code>Ctrl+Y</code> sont supportés.</p>
"""


# ---------------------------------------------------------------------------
# HTML content — English
# ---------------------------------------------------------------------------

def _en_welcome() -> str:
    return """
<h1>Welcome to NgpCraft Engine</h1>
<p>NgpCraft Engine is a graphical tool for the <b>Neo Geo Pocket Color</b>
asset workflow. It bridges the gap between your drawing software (Aseprite)
and the C pipeline (ngpc_sprite_export.py, ngpc_tilemap.py).</p>

<h2>What does it do?</h2>
<ul> 
  <li>Visualize <b>in real time</b> what the NGPC hardware will actually display 
      (colors quantized to RGB444).</li> 
  <li>Edit a sprite's palette and see the result immediately.</li> 
  <li>Detect and fix sprites that exceed hardware limits.</li> 
  <li>Import many sprites quickly: multi-select, drag &amp; drop, folder import.</li> 
  <li>Generate <code>--fixed-palette</code> arguments to share a palette between sprites.</li> 
  <li>Export per scene (sprites + tilemaps) and generate an <b>HTML report</b>.</li> 
  <li>Automatically split a multi-color sprite into stacked layers.</li> 
</ul> 

<h2>Tab groups</h2>
<p>Tabs are organised into <b>four groups</b> selectable from the button bar at the top:</p>
<table>
  <tr><th>Group</th><th>Tabs</th><th>Use</th></tr>
  <tr><td><b>Project</b></td><td>Project · Globals</td><td>Project and global asset management</td></tr>
  <tr><td><b>Scene</b></td><td>Level · Palette · Tilemap · Dialogues · Sprite Setup</td><td>Editing the active scene</td></tr>
  <tr><td><b>Tools</b></td><td>Editor · VRAM Map · Bundle</td><td>Pixel retouch, VRAM budget, batch export</td></tr>
  <tr><td><b>Help</b></td><td>Help</td><td>Inline documentation</td></tr>
</table>
<p>The active group is remembered between sessions. The last active tab within each group is also restored.</p>

<h2>Global navigation</h2>
<table>
<tr><th>Key</th><th>Action</th></tr>
<tr><td><b>Ctrl+Tab</b></td><td>Next tab (within active group)</td></tr>
<tr><td><b>Ctrl+Shift+Tab</b></td><td>Previous tab (within active group)</td></tr>
</table>

<h2>Tabs</h2>
<table>
  <tr><th>Tab</th><th>Group</th><th>Role</th></tr>
  <tr><td><b>Project</b></td><td>Project</td><td>Scene asset overview, VRAM budget, C export</td></tr>
  <tr><td><b>Globals</b></td><td>Project</td><td>Global variables, audio manifest, global entity types</td></tr>
  <tr><td><b>Level</b></td><td>Scene</td><td>Level editor: entities, waves, regions, triggers, procgen</td></tr>
  <tr><td><b>Palette</b></td><td>Scene</td><td>Real-time RGB444 palette editor, fixed-palette</td></tr>
  <tr><td><b>Tilemap</b></td><td>Scene</td><td>ngpc_tilemap.py preview before export</td></tr>
  <tr><td><b>Dialogues</b></td><td>Scene</td><td>Per-scene dialogue banks → <code>scene_*_dialogs.h</code></td></tr>
  <tr><td><b>Sprite Setup</b></td><td>Scene</td><td>Per-frame AABB editor + physics/combat props → C export</td></tr>
  <tr><td><b>Editor</b></td><td>Tools</td><td>Quick pixel retouch (pencil/fill/undo)</td></tr>
  <tr><td><b>VRAM Map</b></td><td>Tools</td><td>Visual map of 512 tiles and 16 sprite palettes</td></tr>
  <tr><td><b>Bundle</b></td><td>Tools</td><td>Batch export with automatic tile/palette budgeting</td></tr>
  <tr><td><b>Help</b></td><td>Help</td><td>This panel</td></tr>
</table>

<h2>Quick Start — assets only</h2>
<ol>
  <li><b>Scene</b> group → <b>Palette</b> tab.</li>
  <li>Drag a PNG onto the tab, or click <i>Open…</i></li>
  <li>Observe the HW preview (RGB444) and the detected palette.</li>
  <li>Click a swatch to edit a color.</li>
  <li>Save the remapped PNG or copy <code>--fixed-palette</code>.</li>
</ol>

<h2>Quick Start — game development</h2>
<ol>
  <li><b>Project</b> group → <b>Project</b> tab: create a scene, add your sprites and tilemaps.</li>
  <li><b>Scene</b> group → <b>Sprite Setup</b> tab: define per-frame AABBs and physics props.</li>
  <li><b>Scene</b> group → <b>Level</b> tab: place entities, create waves, regions, and triggers.</li>
  <li><b>Project</b> group → <b>Project → Export</b>: generate <code>_scene.h</code> and include it in your C game.</li>
</ol>

<h2>Auto-save</h2>
<p>NgpCraft Engine <b>saves automatically</b> after <b>every action</b> — adding a sprite,
editing a scene, placing an entity, changing a trigger… There is <b>no "Save" button</b>
to remember.</p>
<p>A <span style="color:#66bb66"><b>✓ Saved</b></span> indicator flashes briefly in the
status bar at the bottom of the window to confirm each write.</p>

<h2>Where to read the docs?</h2>
<ul>
  <li><code>README.md</code>: quick start, recommended workflow, GUI and headless usage.</li>
  <li><code>PROJET.md</code>: roadmap, architecture, implementation history and design notes.</li>
  <li><code>API_REFERENCE.md</code>: module-by-module code reference, public functions and exposed types.</li>
  <li><b>Help</b>: in-app workflow guide focused on practical tab-by-tab usage.</li>
</ul>
"""


def _en_constraints() -> str:
    return """
<h1>NGPC Hardware Constraints</h1>
<p>The Neo Geo Pocket Color imposes strict graphical limits.
Understanding them is essential to avoid surprises at build time.</p>

<h2>Colors</h2>
<p>The NGPC uses <b>RGB444</b> format: 4 bits per channel (R, G, B).
Each channel has 16 values (0 to 15), for a total of <b>4096 colors</b>.<br>
8-bit colors from your PNG files are <i>rounded</i> to the nearest RGB444
value at export time.</p>

<h2>Core rule: 3 opaque colors per 8×8 tile</h2>
<p>This is the central NGPC rule, applying to <b>both sprites and tilemaps</b>:<br>
each 8×8 tile uses one palette slot with 4 entries, index 0 being transparent.
That leaves <b>3 opaque colors maximum</b> per 8×8 tile.</p>
<ul>
  <li><b>Sprites</b>: if a character has 6 colors, some of its 8×8 tiles contain
      pixels from both color groups → overflow → <b>2 layers required</b>
      (2 overlapping sprites, each 3 colors). Sonic on NGPC, your player ship:
      same principle.</li>
  <li><b>Tilemaps</b>: each tile can have its own palette, but an individual tile
      still cannot exceed 3 opaque colors.</li>
</ul>

<h2>Sprites — VRAM resources</h2>
<table>
  <tr><th>Limit</th><th>Value</th><th>Note</th></tr>
  <tr><td>Sprite palette slots</td><td>16</td><td>Shared across all sprites</td></tr>
  <tr><td>Colors per palette</td><td>4</td><td>Index 0 = always transparent</td></tr>
  <tr><td>Max opaque colors per palette</td><td>3</td><td>Per sprite / per layer</td></tr>
  <tr><td>Tile VRAM slots</td><td>512</td><td>0-31 reserved, 32-127 system font</td></tr>
  <tr><td>Simultaneous HW sprites</td><td>64</td><td>Slots 0-63</td></tr>
</table>

<h2>Tilemaps (scroll planes SCR1/SCR2)</h2>
<table>
  <tr><th>Limit</th><th>Value</th></tr>
  <tr><td>Colors per 8×8 tile</td><td>3 opaque max (same rule)</td></tr>
  <tr><td>Map size</td><td>32×32 tiles</td></tr>
  <tr><td>Screen resolution</td><td>160×152 px (20×19 tiles)</td></tr>
</table>

<h2>Practical implications</h2>
<ul>
  <li>A sprite with <b>4-6 colors</b> must be split into <b>2 layers</b>
      (two overlapping sprites, each with 3 colors).</li>
  <li>A sprite with <b>7-9 colors</b> needs <b>3 layers</b>
      (rare and expensive in hardware slots).</li>
  <li>Each additional layer consumes 1 palette slot and N tile slots.</li>
  <li>Transparency (index 0) in the top layer reveals the layer beneath —
      that is how compositing works.</li>
</ul>
"""


def _en_palette_editor() -> str:
    return """
<h1>Palette Editor</h1>

<h2>Opening a file</h2> 
<p>Click <b>Open…</b> or drag a PNG file directly onto the tab. 
BMP and GIF formats are also accepted.</p> 
<p><b>Auto-reload</b>: if the PNG changes on disk, the tab can automatically reload it 
(handy with Aseprite). If you already edited colors in the tool, a confirmation is shown 
to avoid losing your changes.</p> 
<p><b>Interface</b>: the top of the tab is now grouped into <b>File</b> and <b>View</b> blocks so it stays visually aligned with the <b>Tilemap</b> tab.</p>
 
<h2>Previews</h2> 
<p>Two previews are shown side by side:</p>
<ul>
  <li><b>Original</b> — the image as it is on disk (composited over a checkerboard
      to visualize transparency).</li>
  <li><b>HW Preview (RGB444)</b> — the image with all opaque colors rounded to the
      RGB444 grid. This is what the hardware will display.</li>
</ul>

<h2>Zoom</h2> 
<p>The <code>×1 ×2 ×4 ×8</code> buttons zoom both previews using 
<b>nearest-neighbor</b> scaling (no blur) to inspect individual pixels.</p> 

<h2>Anim preview</h2>
<p>The <b>Anim preview</b> block lets you verify an animated spritesheet:</p>
<ul>
  <li>Set <code>frame_w</code>, <code>frame_h</code> and <code>frame_count</code> (grid, row-major order).</li>
  <li><b>Auto</b> tries to guess a config (vertical/horizontal strip).</li>
  <li>Use <b>Play/Pause</b> to run the animation and the <b>ms</b> field to control speed.</li>
  <li>The <b>.c sprite</b> export uses these values (includes <code>--frame-count</code>).</li>
  <li><b>Apply to scene</b>: updates the sprite entry in the active scene with these values.</li>
</ul>
<p>If the file is part of the active scene (Project tab), the anim config is automatically
prefilled from the scene.</p>

<h2>Tile overlay</h2>
<p>When <i>Overlay tiles</i> is checked, a semi-transparent grid is superimposed
on the HW preview. The constraint applies equally to <b>sprites and tilemaps</b>:
each 8×8 tile can only use one palette slot = 3 opaque colors max.</p>
<ul>
  <li><span style="color:#00cc00">■ Green</span> — tile ≤ 3 opaque colors: direct rendering possible.</li>
  <li><span style="color:#cc0000">■ Red</span> — tile &gt; 3 opaque colors: requires layer split (sprites) or color reduction (tilemaps).</li>
</ul>

<h2>Editing a color</h2>
<ol>
  <li>Click a <b>swatch</b> in the palette panel.</li>
  <li>The color picker opens.</li>
  <li>Choose a color — it is <b>automatically rounded</b> to the nearest RGB444 value.</li>
  <li>All pixels of that color are remapped live in both previews.</li>
</ol>
<p><b>Note:</b> color 0 (transparent, shown as checkerboard) cannot be edited.</p>

<h2>Saving</h2>
<p><b>Save PNG…</b> writes the <i>remapped</i> image (RGB444 HW version)
with the new palette. The original file is not overwritten unless you save
to the same path.</p>

<h2>Copy --fixed-palette</h2>
<p>This button copies to the clipboard:</p>
<pre>--fixed-palette 0x0000,0x025B,0x074A,0x0FFF</pre>
<p>Ready to pass to <code>ngpc_sprite_export.py</code> or
<code>ngpc_sprite_bundle.py</code> to force this exact palette on another sprite
(palette sharing between sprites).</p>

<h2>Scene palettes (shared editing)</h2>
<p>In <b>project mode</b>, a <b>Scene palettes</b> panel lists the shared palettes
used by the active scene (those declared via <code>fixed_palette</code>).</p>
<ul>
  <li>Select a palette in the list: its 4 slots (0=transparent) are shown.</li>
  <li>Edit colors (RGB444 snap), then click <b>Apply</b>.</li>
  <li>The tool remaps pixels and updates <code>fixed_palette</code> for all linked sprites.</li>
</ul>
"""


def _en_rgb444() -> str:
    return """
<h1>RGB444 Quantization</h1>

<h2>Principle</h2>
<p>The NGPC stores each color in <b>12 bits</b>: 4 bits for R, G, and B.
An 8-bit pixel (R8, G8, B8) is rounded by truncating the low 4 bits:</p>
<pre>r4 = R8 >> 4        (0..15)
g4 = G8 >> 4
b4 = B8 >> 4

r8_display = r4 * 17   (0, 17, 34, … 255)
g8_display = g4 * 17
b8_display = b4 * 17</pre>

<h2>NGPC encoding (u16 word)</h2>
<pre>word = r4 | (g4 &lt;&lt; 4) | (b4 &lt;&lt; 8)</pre>
<table>
  <tr><th>R8</th><th>G8</th><th>B8</th><th>r4</th><th>g4</th><th>b4</th><th>Word</th><th>Displayed</th></tr>
  <tr><td>255</td><td>255</td><td>255</td><td>15</td><td>15</td><td>15</td><td>0x0FFF</td><td>pure white</td></tr>
  <tr><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0x0000</td><td>black / transparent</td></tr>
  <tr><td>85</td><td>34</td><td>17</td><td>5</td><td>2</td><td>1</td><td>0x0125</td><td>dark brown</td></tr>
  <tr><td>170</td><td>68</td><td>119</td><td>10</td><td>4</td><td>7</td><td>0x074A</td><td>purple</td></tr>
</table>

<h2>Visible effect</h2>
<p>Truncation can produce <b>color banding</b> on fine gradients.
Working directly with an RGB444 palette in Aseprite (using the Lua extension
provided in the template) avoids surprises.</p>

<h2>Transparency</h2>
<p>The word <code>0x0000</code> (absolute black) is reserved for the
<b>transparent color</b> (palette index 0). Avoid using pure black as a visible
color — use <code>0x0111</code> (very dark) instead.</p>
"""


def _en_layers() -> str:
    return """
<h1>Layers</h1>

<h2>Why layers?</h2>
<p>An NGPC sprite palette has <b>4 entries</b>, with index 0 always transparent.
That leaves <b>3 opaque colors</b> per sprite.<br>
For a character with 6 colors, you need <b>2 overlapping sprites</b>
(layer A + layer B), each with its own 3-color palette.</p>

<h2>Split algorithm</h2>
<ol>
  <li>All opaque pixels are collected and their RGB444 colors counted.</li>
  <li>Colors are sorted by <b>descending frequency</b>
      (most-used colors first).</li>
  <li><b>Layer 0 (A)</b> = the 3 most frequent colors.</li>
  <li><b>Layer 1 (B)</b> = the next 3 colors.</li>
  <li><b>Layer 2 (C)</b> = the next 3 colors, and so on.</li>
  <li>Each pixel is routed to the layer that owns its color.</li>
</ol>

<h2>Recommended layer count</h2>
<table>
  <tr><th>Opaque colors</th><th>Layers</th><th>Palettes used</th><th>HW slots</th></tr>
  <tr><td>1 – 3</td><td>1</td><td>1</td><td>N</td></tr>
  <tr><td>4 – 6</td><td>2</td><td>2</td><td>2N</td></tr>
  <tr><td>7 – 9</td><td>3</td><td>3</td><td>3N ⚠</td></tr>
  <tr><td>&gt; 9</td><td>≥ 4</td><td>≥ 4</td><td>very high ✗</td></tr>
</table>

<h2>In-game rendering</h2>
<p>Both (or all) layers are drawn at the <b>same screen coordinates</b>.
Transparency in the top layer reveals the colors of the layer below.
The visual result: 6 (or 9) colors for the player.</p>
<pre>// C example — two layers for a 16x16 sprite
ngpc_sprite_set(SPR_PLAYER_A, x, y, player_a_tile, player_a_pal, SPR_FRONT);
ngpc_sprite_set(SPR_PLAYER_B, x, y, player_b_tile, player_b_pal, SPR_FRONT);</pre>

<h2>Using the split in NgpCraft Engine</h2>
<ol>
  <li>Open your sprite in the <b>Palette</b> tab.</li>
  <li>If the sprite has more than 3 colors, a suggestion message appears.</li>
  <li>Click <b>Split into N layers…</b></li>
  <li>The dialog shows each layer with its preview and <code>--fixed-palette</code> argument.</li>
  <li>Save each layer as a separate PNG.</li>
  <li>Export each layer with <code>ngpc_sprite_export.py</code>
      using the copied <code>--fixed-palette</code> argument.</li>
</ol>
"""


def _en_remap() -> str:
    return """
<h1>Remap Wizard</h1>

<h2>Purpose</h2>
<p>For two sprites to share the same palette slot (<code>--fixed-palette</code>),
their colors must match exactly. When they are <em>similar but not identical</em>
(e.g. two enemies with slight color variants), the Remap Wizard guides you through
aligning one sprite's colors to the other's, one color at a time.</p>

<h2>Launching the wizard</h2>
<ol>
  <li>Open the source sprite in the <b>Palette</b> tab.</li>
  <li>Click <b>Remap colors…</b> in the <i>Individual export</i> panel.</li>
  <li>In the dialog, click <b>Choose…</b> to select the target sprite
      (the "palette donor").</li>
</ol>

<h2>Remap steps</h2>
<p>For each opaque color in the source sprite:</p>
<ul>
  <li>The left preview shows the source sprite with the current color
      <b>highlighted</b> (all other pixels are dimmed).</li>
  <li>The right panel lists the colors available in the target sprite.</li>
  <li>Select the matching target color, or click <b>← Skip (keep)</b>
      to leave the original color unchanged.</li>
  <li>Navigate with <b>Next →</b> and <b>← Previous</b>.</li>
</ul>

<h2>Preview and save</h2>
<p>After the last color, a side-by-side preview appears:</p>
<ul>
  <li><b>Source (remapped)</b> — the result of the remap.</li>
  <li><b>Target (reference)</b> — the donor sprite.</li>
</ul>
<p>Click <b>Apply &amp; Save PNG…</b> to save the remapped sprite.
The result is automatically reloaded into the palette editor.</p>

<h2>After remapping</h2>
<p>With identical palettes, NgpCraft Engine automatically detects palette sharing
and assigns <code>--fixed-palette</code> the next time you add the remapped sprite
to a scene. <b>Result: 0 extra palette slots consumed.</b></p>
"""


def _en_project() -> str:
    return """
<h1>Project Tab</h1>

<h2>Scene-based organisation</h2>
<p>A <code>.ngpcraft</code> project organises assets by <b>scenes</b> (e.g. "Menu", "Act 1", "Boss").
Each scene groups the sprites and tilemaps that appear on screen together.</p>

<h2>Managing scenes</h2>
<ul>
  <li><b>New…</b> — create an empty scene (enter a name).</li>
  <li><b>✎ Rename</b> — rename the selected scene.</li>
  <li><b>✕ Delete</b> — remove the scene and all its registered assets.</li>
  <li><b>Order</b> — drag &amp; drop scenes in the list to reorder them (affects the <code>scenes_autogen</code> manifest).</li>
  <li><b>Start scene</b> — selects the default entry (<code>NGP_SCENE_START_INDEX</code>).</li>
</ul>

<p><b>Navigator:</b> the permanent left panel now provides a global view of scenes, sprites, tilemaps, entities, waves, regions, triggers, and paths. A single click activates the scene; double-click or right-click jumps directly to the relevant tab.</p>
<p><b>Inspector:</b> right below the tree, a single contextual inspector now summarizes the selected scene/object (scene, sprite, tilemap, entity, wave, region, trigger, path) and exposes the most useful quick actions. The goal of this V1 is to reduce tab-hopping before a later, more editable inspector pass.</p>

<h2>Scene content</h2> 
<p>Select a scene in the left list. The right panel shows:</p> 
<ul> 
  <li><b>Scene status</b>: the left list now shows a visual <b>OK / ! / KO</b> state with tooltip details. This helps you quickly spot whether a scene looks ready, warning-only, or incomplete (missing assets, missing player, invalid col_map, broken refs, missing export_dir…).</li>
  <li><b>Quick actions</b>: a dedicated row lets you open the current scene directly in <b>Palette</b>, <b>Tilemap</b>, <b>Level</b>, <b>Hitbox</b>, or open the <b>export folder</b> without going through the global navigation again.</li>
  <li><b>Scene presets</b>: a combo applies a reusable starter structure to the current scene (<b>platformer</b>, <b>vertical shmup</b>, <b>top-down room</b>, <b>single-screen menu</b>…). These presets keep existing sprites/tilemaps intact and mainly fill profile, layout, HUD, plus a few starter regions/triggers when that side of the scene is still empty.</li>
  <li><b>Project validation</b>: at the bottom, a compact summary counts <b>ready</b>, <b>warning</b>, and <b>incomplete</b> scenes, while a small <b>project checklist</b> summarizes scenes / start scene / export_dir / overall scene status / template contract. The <b>First issue</b> button jumps to the first scene that still needs attention, and the <b>Details</b> button now opens a validation center listing project / scene / level / export issues. That dialog no longer only opens the scene: it also exposes a contextual <b>action</b> when the next fix is obvious (add a scene, set the start scene, configure export_dir, review template details, jump back to export workflow).</li>
  <li><b>Export validation</b>: that center also runs a first static export-pipeline pass without launching the tools: generated filename collisions (<code>scene_*</code>, <code>*_mspr.c</code>, <code>*_map.c</code>), suspicious <code>export_dir</code> locations, and missing/stale autogens (<code>assets_autogen.mk</code>, <code>audio_autogen.mk</code>, <code>scenes_autogen</code>).</li>
  <li><b>Template contract</b>: right below validation, a compact summary also checks the detected template basics: <code>makefile</code>, <code>src/main.c</code>, expected <code>tools/</code> scripts, <code>ngpc_metasprite.h</code>, the <code>NGP_FAR</code> macro, <code>ngpc_types.h</code> (u8/u16/s16 typedefs), and the audio contract (<code>project_audio_manifest.txt</code> path validity + <code>src/audio/sounds.h/.c</code> runtime files when audio is configured), plus a first toolchain diagnostic (<code>build.bat</code>, <code>compilerPath</code>, local <code>asm900/thc1/thc2</code> helpers, and build tools visible in the <code>PATH</code>). The <b>Details</b> button opens the full list, and <b>Next step</b> suggests the most useful follow-up action.</li>
  <li><b>Sprites</b>: table with file name, frame size (W×H), frame count, 
      and estimated tile usage.</li> 
  <li><b>Batch import</b>: <i>+ Sprite…</i> supports multi-select, and you can also 
      drag &amp; drop PNGs (files or a folder) into the sprite list.</li> 
  <li><b>Open in Palette</b>: select a sprite and click <b>Open in Palette</b>
      (or <b>Ctrl + double-click</b>) to load it in the Palette tab
      with the anim config (frame_w/h/count) prefilled.</li>
  <li><b>Auto-share palettes</b>: if two sprites use the same colors (different order), 
      <b>Auto-share palettes</b> can make them share a single palette slot.</li> 
  <li><b>Tilemaps</b>: simple list of tilemap PNGs.</li> 
  <li><b>Export</b>: uncheck to skip an asset during exports (useful for temporary or unused files).</li>
  <li><b>Audio (per scene)</b>: link a Sound Creator <code>project_audio_manifest.txt</code> and choose a <b>BGM</b>.
      Export writes <code>#define</code>s (<code>SCENE_*_BGM_INDEX</code>…) into <code>scene_*_level.h</code>.
      The <code>scene_*.h</code> header also provides <code>scene_xxx_enter()</code> and optional audio helpers
      (<code>scene_xxx_audio_*</code>, when <code>NGP_ENABLE_SOUND</code> is enabled).
      <br><b>Required format:</b> <b>hybrid C export</b> only (Sound Creator → Project → <i>Export All</i>).
      This mode generates bytecode streams interpreted at runtime by the embedded PSG driver.
      <code>project_instruments.c</code> is mandatory for BGM playback.</li>
  <li><b>SFX mapping</b>: global list of “gameplay IDs → Sound Creator ID”. Export can generate
      <code>ngpc_project_sfx_map.h</code> (enum + table) into <code>export_dir</code>.</li>
  <li><b>Scene budget</b>: total tiles and palettes estimated for this scene alone.</li> 
  <li><b>Open in Editor</b>: opens the PNG in the <b>Editor</b> tab for quick retouch.</li>
</ul> 

<h2>Asset Browser (GraphX)</h2>
<p>At the top of the right panel, the <b>Asset Browser</b> lists images from the GraphX folder:</p>
<ul>
  <li>Text filter to quickly find a PNG.</li>
  <li><b>Auto-rescan</b>: when enabled, the list updates when you add/rename files.</li>
  <li><b>Thumbnails</b>: shows a small icon for each asset (lazy/progressive loading).</li>
  <li>Double-click an asset: opens it in the <b>Palette</b> tab.</li>
  <li>Buttons: open in Palette/Tilemap/Editor, or add directly to the current scene (sprite / tilemap).</li>
  <li>Drag &amp; drop: drag an asset into the sprite list.</li>
</ul>

<h2>Project constants (game constants)</h2>
<p>The <b>Project constants</b> collapsible panel (at the bottom of the right panel)
lets you define global numeric constants for the project:</p>
<ul>
  <li><b>Name</b> — a valid C identifier (e.g. <code>PLAYER_HP_MAX</code>).</li>
  <li><b>Value</b> — a signed integer.</li>
  <li><b>Comment</b> — free text (optional).</li>
</ul>
<p>Use <b>Add…</b> / <b>Remove</b> to manage rows. On any export
(All to .c, All scenes → .c, Scene → .c, Scene → tilemaps .c),
<code>ngpc_project_constants.h</code> is generated into <b>Export dir</b>:</p>
<pre>#ifndef NGPC_PROJECT_CONSTANTS_H
#define NGPC_PROJECT_CONSTANTS_H
#define PLAYER_HP_MAX  3   /* Player starting lives */
#define BULLET_SPEED   2   /* Bullet speed px/frame */
#endif /* NGPC_PROJECT_CONSTANTS_H */</pre>
<p>Include it in your C code: <code>#include "ngpc_project_constants.h"</code><br>
The file is only written when at least one constant is defined and <b>Export dir</b> is configured.</p>

<h2>Performance settings</h2>
<p>Three project-level options affect runtime behavior:</p>
<ul>
  <li><b>Activation radius (tiles)</b> — when &gt; 0, enemies outside this radius around the
      camera are suspended. Useful for large tilemaps with many enemies. <code>0</code> = all always active.</li>
  <li><b>Dynamic palette recycling (LRU)</b> — recycles the 16 sprite palette slots at runtime
      using an LRU eviction policy. Useful when your project has more than 16 entity types
      with different colors. CPU cost is negligible (a few dozen cycles per spawn/despawn).
      <br>Disabled: palette slots are assigned at compile time (baked in ROM data).</li>
  <li><b>Disable BIOS system font</b> — by default the BIOS loads its built-in font into tile
      slots 32–127 (96 tiles × 8 words). Checking this option skips that call and frees those
      96 slots for your own tiles or a custom font. Sets <code>NGPNG_NO_SYSFONT=1</code> in the
      Makefile. <br>⚠ Do not enable this if you use <code>ngpc_text_*</code> functions.</li>
</ul>
<p>These options are independent and can be freely combined.</p>

<h2>Custom Font</h2>
<p>The <b>Custom font</b> field lets you replace the BIOS system font with
your own 8×8 pixel font.  When a PNG is selected:</p>
<ul>
  <li>"Disable BIOS system font" is checked automatically.</li>
  <li>On the next export, <code>ngpc_font_export.py</code> generates
      <code>GraphX/ngpc_custom_font.c/.h</code>.</li>
  <li>The generated <code>main.c</code> calls <code>ngpc_custom_font_load()</code>
      instead of <code>ngpc_load_sysfont()</code>.</li>
  <li>All <code>ngpc_text_*</code> functions keep working unchanged
      (same ASCII → tile index mapping).</li>
</ul>
<h3>Preview</h3>
<p>The preview shows the PNG with a per-tile grid and the ASCII character in each cell.
Use the <b>2× 3× 4× 6×</b> buttons to zoom, and the <b>Light / Dark bg</b> button
to toggle the background.</p>
<h3>Accepted PNG formats</h3>
<p>Select the format from the <b>PNG format</b> dropdown before loading the file.</p>
<pre><b>Format 128 × 48</b>  (16 columns × 6 rows)
Tiles   : 96 total  →  ASCII 32 (space) … 127 (~)
Colors  : max 3 visible + transparent
  Pure black (0,0,0) or alpha &lt; 128 = transparent (index 0)

Tile order:
  Row 0  ASCII  32– 47  :  space ! " # $ % &amp; ' ( ) * + , - . /
  Row 1  ASCII  48– 63  :  0 1 2 3 4 5 6 7 8 9 : ; &lt; = &gt; ?
  Row 2  ASCII  64– 79  :  @ A B C D E F G H I J K L M N O
  Row 3  ASCII  80– 95  :  P Q R S T U V W X Y Z [ \ ] ^ _
  Row 4  ASCII  96–111  :  ` a b c d e f g h i j k l m n o
  Row 5  ASCII 112–127  :  p q r s t u v w x y z { | } ~</pre>
<pre><b>Format 256 × 24</b>  (32 columns × 3 rows)
Tiles   : 96 total  →  ASCII 32 (space) … 127 (~)
Colors  : same rules as above

Tile order:
  Row 0  ASCII  32– 63  :  space ! " # $ % &amp; ' ( ) * + , - . / 0 1 2 3 4 5 6 7 8 9 : ; &lt; = &gt; ?
  Row 1  ASCII  64– 95  :  @ A B C D E F G H I J K L M N O P Q R S T U V W X Y Z [ \ ] ^ _
  Row 2  ASCII  96–127  :  ` a b c d e f g h i j k l m n o p q r s t u v w x y z { | } ~</pre>
<p><b>Tool:</b> <code>tools/ngpc_font_export.py</code> — also usable from the command line:<br>
<code>python tools/ngpc_font_export.py font.png -o GraphX/ngpc_custom_font</code></p>

<h2>Global budget</h2>
<p>The bottom bar shows the total project budget:</p>
<pre>Global: 76/512 tiles  ·  3/16 pal.  ✓</pre>
<p>A ⚠ warning appears if the project exceeds 512 tiles or 16 palettes.</p>

<h2>Global exports</h2> 
<table> 
  <tr><th>Button</th><th>Effect</th></tr> 
  <tr><td><b>All to PNG</b></td><td>Save each sprite quantized to RGB444 next to its source</td></tr> 
  <tr><td><b>All to .c</b></td><td>Call <code>ngpc_sprite_export.py</code> for each sprite</td></tr> 
  <tr><td><b>All scenes → .c</b></td><td>Exports <b>all scenes</b> (sprites + tilemaps + scene/level headers), then updates <code>scenes_autogen</code> — opens an options dialog (assets, headers, disabled assets).</td></tr>
  <tr><td><b>Palettes .c</b></td><td>Generate only <code>const u16 name_pal[]</code> arrays</td></tr> 
  <tr><td><b>HTML report…</b></td><td>Generates an HTML summary (budgets, scenes, missing files)</td></tr> 
  <tr><td><b>PDF report…</b></td><td>Generates a PDF version of the same report (shareable export)</td></tr> 
</table> 
<p><b>Tip:</b> when <b>Export dir</b> is set, these exports refresh the “autogen” files:
<code>assets_autogen.mk</code>, <code>scene_*.h</code>, <code>scene_*_level.h</code>, <code>scenes_autogen.c/.h</code>, (when audio is linked) <code>audio_autogen.mk</code>,
and (when constants are defined) <code>ngpc_project_constants.h</code>.</p>
<p><b>Export (template-ready)</b> opens an options dialog (scope, disabled assets, headers, triggers/hitbox…).</p>

<h2>Build / Run (Phase 5)</h2>
<p>To integrate the full game workflow:</p>
<ul>
  <li><b>Build…</b>: runs <code>make</code> in the project folder and shows the log.</li>
  <li><b>Custom target…</b>: lets you enter a <code>make</code> target (e.g. <code>release</code>).</li>
  <li><b>Jobs</b>: parallelizes the build (e.g. <code>-j 8</code>).</li>
  <li><b>Options</b>: adds extra arguments to <code>make</code> (e.g. <code>V=1</code>).</li>
  <li><b>Clear</b> / <b>Copy</b>: manage the build log quickly.</li>
  <li><b>Run</b>: launches an emulator (Mednafen/RACE) with the ROM (auto-detect or pick manually).</li>
  <li><b>Config…</b>: configure emulator + ROM paths and remember them.</li>
</ul>
 
<h2>Per-scene exports</h2>
<p>When a scene is selected, dedicated export buttons are available:</p>
<ul>
  <li><b>Scene → PNG</b>: exports the scene sprites as RGB444-quantized PNGs.</li>
  <li><b>Scene → .c</b>: exports <b>sprites + tilemaps</b> (<code>ngpc_sprite_export.py</code> + <code>ngpc_tilemap.py</code>),
      and generates <code>scene_*.h</code> + <code>scene_*_level.h</code> (when <b>Export dir</b> is set), then updates
      <code>scenes_autogen</code> (global manifest). Opens an options dialog.</li> 
  <li><b>Scene → tilemaps .c</b>: exports the scene tilemaps via <code>ngpc_tilemap.py</code>.</li>
</ul>
<p><b>Audio:</b> when a Sound Creator manifest is linked, export also generates <code>audio_autogen.mk</code> in
<b>Export dir</b> (it appends <code>sound/exports/*.c</code> to <code>OBJS</code> when <code>NGP_ENABLE_SOUND=1</code>).
When an SFX mapping is defined, export generates <code>ngpc_project_sfx_map.h</code> (in <code>export_dir</code>) and
<code>sounds_game_sfx_autogen.c</code> (in the audio <code>exports/</code> folder).</p>
<p><b>GraphX folder</b>: relative path to the assets folder, used as base for
relative paths stored in the project.</p>

<h2>Thumbnail rail (Palette tab)</h2> 
<p>When a scene is selected here, the Palette tab shows a thumbnail rail of 
the scene's sprites. Clicking a thumbnail loads that asset into the palette editor.</p> 
<p>For sprites, the thumbnail also reuses the sprite configuration 
(<code>frame_w</code>/<code>frame_h</code>/<code>frame_count</code>) for the anim preview.</p>
"""


def _en_globals() -> str:
    return """
<h1>Globals Tab</h1>
<p>The <b>Globals</b> tab centralises everything that is <b>project-wide</b> and not
tied to any particular scene. It has 5 sub-tabs: <b>Variables</b>, <b>Constants</b>,
<b>Audio</b>, <b>Items</b>, and <b>Entity Templates</b>.</p>

<h2>Variables (flags &amp; persistent variables)</h2>
<p>A project has 16 <b>flags</b> and 16 <b>u8 variables</b> that persist across scene
changes throughout the game session.</p>

<h3>Flags (booleans)</h3>
<p>A flag is 0 (false) or 1 (true). Typically used to remember that an event occurred:</p>
<ul>
  <li>The player picked up the sword.</li>
  <li>The secret door was opened.</li>
  <li>The boss is dead.</li>
</ul>
<p>Give each flag (0–15) a <b>name</b> to document your code. Unnamed and unreferenced
flags <b>generate no C code</b> (tree-shaking).</p>
<table>
  <tr><th>Trigger condition</th><th>Tests</th></tr>
  <tr><td><code>flag_set</code></td><td>flag is 1</td></tr>
  <tr><td><code>flag_clear</code></td><td>flag is 0</td></tr>
</table>
<table>
  <tr><th>Trigger action</th><th>Effect</th></tr>
  <tr><td><code>set_flag</code></td><td>Set flag to 1</td></tr>
  <tr><td><code>clear_flag</code></td><td>Set flag to 0</td></tr>
  <tr><td><code>toggle_flag</code></td><td>Flip value (0→1, 1→0)</td></tr>
</table>

<h3>u8 Variables (counters)</h3>
<p>A variable is an unsigned integer 0–255. Typically used for:</p>
<ul>
  <li>Number of coins collected.</li>
  <li>Remaining hit points.</li>
  <li>Quest progression stage.</li>
</ul>
<p>Each variable has a <b>name</b> and an <b>initial value</b> (applied by the
<code>init_game_vars</code> trigger action). In the Level tab, the flag/var spinbox
shows the resolved name directly in the UI.</p>
<table>
  <tr><th>Trigger condition</th><th>Tests</th></tr>
  <tr><td><code>variable_ge</code></td><td>var[N] ≥ value</td></tr>
  <tr><td><code>variable_eq</code></td><td>var[N] = value</td></tr>
  <tr><td><code>variable_le</code></td><td>var[N] ≤ value</td></tr>
</table>
<table>
  <tr><th>Trigger action</th><th>Effect</th></tr>
  <tr><td><code>set_variable</code></td><td>Assign a value</td></tr>
  <tr><td><code>inc_variable</code></td><td>Increment by 1</td></tr>
  <tr><td><code>dec_variable</code></td><td>Decrement by 1</td></tr>
</table>

<h3>Tree-shaking on export</h3>
<p>On every export, NgpCraft scans all scenes and only generates a <code>#define</code>
for slots that are <b>named</b> or <b>referenced</b> in at least one trigger. Empty,
unreferenced slots are silently omitted from the header:</p>
<pre>/* ngpc_game_vars.h — only active slots */
#define GAME_FLAG_0  0   /* has_sword    */
#define GAME_FLAG_3  3   /* visited_town */
#define GAME_VAR_0   0   /* coins  (init: 0) */
#define GAME_VAR_1   1   /* health (init: 3) */
static const u8 g_game_var_inits[16] = { 0, 3, 0, 0, 0, 0, 0, 0 };</pre>
<p><b>Export warning:</b> if a trigger references a slot with no name, a
<code>[warning]</code> appears in the export summary.</p>

<h2>Constants</h2>
<p>Constants are named integers global to the project. They have <b>zero runtime cost</b>
(pure preprocessor). Use <b>Add…</b> / <b>Delete</b> to manage the list.
Export generates <code>ngpc_project_constants.h</code>:</p>
<pre>#define PLAYER_HP_MAX  3   /* Player starting lives */
#define BULLET_SPEED   2   /* Bullet speed px/frame */</pre>
<p>Include in your C code: <code>#include "ngpc_project_constants.h"</code>.</p>

<h2>Audio</h2>
<p>This sub-tab holds the project-wide audio settings:</p>
<ul>
  <li><b>Manifest</b>: path to <code>project_audio_manifest.txt</code> (Sound Creator).
      Export generates <code>audio_autogen.mk</code>.</li>
  <li><b>SFX mapping</b>: "gameplay ID → Sound Creator ID" list.
      Export generates <code>ngpc_project_sfx_map.h</code> (enum + mapping table).</li>
</ul>
<h3>SFX tree-shaking</h3>
<p>On export, NgpCraft scans <code>play_sfx</code> triggers across all scenes.
Trailing SFX entries that are never referenced are <b>removed from the table</b> (tail trim).
Mid-array unused entries are kept (no renumbering — IDs stay stable) but annotated
<code>/* unused */</code> in the header.</p>

<h2>Entity Templates (prefabs)</h2>
<p>An <b>entity template</b> is a <b>project-wide prefab</b>: a single place that stores
<em>all</em> the characteristics of a character or enemy:</p>
<table>
  <tr><th>Category</th><th>Data stored</th></tr>
  <tr><td><b>Sprite</b></td><td>Source PNG file, frame dimensions (w×h px)</td></tr>
  <tr><td><b>Hitbox</b></td><td>Hurtboxes (damage received), attack boxes (damage dealt)</td></tr>
  <tr><td><b>Physics</b></td><td>Props: gravity, speed, jump, contact damage…</td></tr>
  <tr><td><b>Control</b></td><td>Ctrl export (player: bindings, move_type, etc.)</td></tr>
  <tr><td><b>Animations</b></td><td>Animation states, named anims, motion patterns</td></tr>
  <tr><td><b>AI / Behavior</b></td><td>Role, behavior, ai_speed, ai_range, direction, data, flags</td></tr>
</table>
<p>Scene instances are <b>independent snapshots</b> — there is no live binding. The
template is the <b>master version</b>: edit it freely in Globals, then explicitly
"pull from master" into scenes whenever you want.</p>

<h3>Creating a template — from the Hitbox tab</h3>
<p>This is the <b>main entry point</b>. Once a sprite is configured (hitbox, props,
animations, ctrl) in the Hitbox tab:</p>
<ol>
  <li>Click <b>💾 Save as Template</b> → dialog to name the template.</li>
  <li>A full snapshot of the current sprite is stored in the project's
      <code>entity_templates[]</code>.</li>
  <li>A badge <b>📌 Template: name</b> appears below the sprite name to confirm.</li>
  <li>If a template already exists for this sprite: the button becomes
      <b>↑ Update Template</b> — a confirmation is required before overwriting.</li>
</ol>
<p>The badge reappears automatically every time the sprite is opened in Hitbox.</p>

<h3>Managing templates — Globals tab</h3>
<p>The list shows full templates (prefixed <b>📌</b>) and legacy behavior-only archetypes
(no prefix) for backward compatibility.</p>
<ul>
  <li>Select a template → the right panel shows editable AI fields <em>and</em> a
      read-only sprite summary: file, dimensions, hitbox count, active props.</li>
  <li><b>Add…</b>: creates an empty template (behavior-only) to be completed from Hitbox.</li>
  <li><b>Delete</b>: removes the template from the project (existing instances keep their
      data; the <code>type_id</code> becomes orphaned).</li>
</ul>
<p>AI fields are context-sensitive by role and behavior:</p>
<table>
  <tr><th>Behavior</th><th>Visible fields</th></tr>
  <tr><td>Patrol</td><td>AI speed</td></tr>
  <tr><td>Chase</td><td>AI speed + Detection range + Lose range</td></tr>
  <tr><td>Random</td><td>AI speed + Change every (fr)</td></tr>
  <tr><td>Fixed</td><td>No AI parameters</td></tr>
</table>

<h3>Using templates — Level tab</h3>
<p>In the entity inspector (Level tab), the <b>Entity template</b> group offers:</p>
<ul>
  <li><b>Save as template…</b>: captures the AI/role parameters of the current instance
      <em>and</em> the scene sprite meta → creates or updates a template in Globals.</li>
  <li><b>Apply template…</b>: picker → copies AI/role fields into the current instance
      and refreshes the inspector.</li>
  <li><b>→ Manage in Globals</b>: switches directly to the Globals tab.</li>
</ul>
<p>At the bottom of the sprite palette (left column of the Level tab):</p>
<ul>
  <li><b>＋ From template…</b>: lists templates that have a sprite defined →
      select → the sprite is <b>auto-imported into the scene</b> if not already present,
      then the view refreshes. The sprite is ready to place.</li>
</ul>
<p>The label <b>"Based on: template_name"</b> appears when an instance is linked to a
template (<code>type_id</code> set).</p>

<h3>C export — full tree-shaking</h3>
<p>Export generates <code>ngpc_entity_types.h</code> with <b>only</b> the templates
referenced by at least one instance (<code>type_id</code>) in at least one scene.
Templates defined but never placed → <b>no C code generated</b>.</p>
<pre>/* ngpc_entity_types.h */
typedef enum {
    ET_PLAYER = 0,   /* etpl_player */
    ET_SLIME  = 1,   /* etpl_slime  */
} EntityTypeId;

typedef struct {
    u8 role; u8 behavior; u8 speed; u8 range;
    u8 lose_range; u8 change_every; u8 dir; u8 data; u8 flags;
    u8 hp; u8 atk; u8 def; u8 xp;
} EntityTypeDef;

static const EntityTypeDef et_table[] = {
    /* ET_PLAYER */ { 0, 0, 3, 0,  0,  0, 0, 0, 0,  0, 0, 0, 0 },
    /* ET_SLIME  */ { 1, 0, 1, 10, 16, 60, 0, 0, 0, 10, 1, 0, 5 },
};
#define ET_TABLE_SIZE  2</pre>
<p>All data is <code>const</code> → ROM only, <b>zero RAM, zero CPU overhead</b>.
Sprite/hitbox data is not in this header (generated separately by the bundle pipeline).</p>

<h3>Export validation (warnings)</h3>
<ul>
  <li>Flag/variable referenced in a trigger but with no name → <code>[warning]</code>.</li>
  <li>Instance with a <code>type_id</code> that no longer exists in Globals →
      <code>[warning]</code>.</li>
</ul>

<h2>Entity type events (global no-code)</h2>
<p>The <b>Events</b> section at the bottom of each template lets you attach
<b>automatic actions</b> to an entity type — no C required. These actions fire for
<em>any instance</em> of that type, across <em>all scenes</em>, including
procedurally-generated ones.</p>

<h3>Available events (16)</h3>
<table>
  <tr><th>Event</th><th>EV_* C (index)</th><th>Fires when…</th><th>Typical roles</th></tr>
  <tr><td><code>entity_death</code></td><td>0</td><td>Instance killed</td><td>enemy, block</td></tr>
  <tr><td><code>entity_collect</code></td><td>1</td><td>Instance picked up</td><td>item</td></tr>
  <tr><td><code>entity_activate</code></td><td>2</td><td>Instance activated (NPC talked to, trigger hit)</td><td>npc, trigger, platform, block, prop</td></tr>
  <tr><td><code>entity_hit</code></td><td>3</td><td>Instance hit by player</td><td>enemy, block</td></tr>
  <tr><td><code>entity_spawn</code></td><td>4</td><td>Instance spawned at runtime</td><td>all except player</td></tr>
  <tr><td><code>entity_btn_a</code></td><td>5</td><td>Button A pressed near an instance</td><td>enemy, npc, trigger, platform, block, prop</td></tr>
  <tr><td><code>entity_btn_b</code></td><td>6</td><td>Button B pressed near an instance</td><td>enemy, npc, trigger, block, prop</td></tr>
  <tr><td><code>entity_btn_opt</code></td><td>7</td><td>Option pressed near an instance</td><td>npc, trigger, prop</td></tr>
  <tr><td><code>entity_btn_up</code></td><td>8</td><td>Up pressed near an instance</td><td>npc, trigger</td></tr>
  <tr><td><code>entity_btn_down</code></td><td>9</td><td>Down pressed near an instance</td><td>npc, trigger</td></tr>
  <tr><td><code>entity_btn_left</code></td><td>10</td><td>Left pressed near an instance</td><td>npc, trigger, platform, prop</td></tr>
  <tr><td><code>entity_btn_right</code></td><td>11</td><td>Right pressed near an instance</td><td>npc, trigger, platform, prop</td></tr>
  <tr><td><code>entity_player_enter</code></td><td>12</td><td>Player enters proximity range</td><td>enemy, item, npc, trigger, platform, block, prop</td></tr>
  <tr><td><code>entity_player_exit</code></td><td>13</td><td>Player leaves proximity range</td><td>enemy, npc, trigger, platform, prop</td></tr>
  <tr><td><code>entity_timer</code></td><td>14</td><td>Periodic timer fires (rate set per instance)</td><td>enemy, npc, block, prop</td></tr>
  <tr><td><code>entity_low_hp</code></td><td>15</td><td>HP drops below threshold (boss phase change…)</td><td>enemy, block</td></tr>
</table>
<p>Events are filtered by role in the UI: an enemy does not see
<code>entity_collect</code>; an NPC does not see <code>entity_death</code>.</p>

<h3>Configurable actions</h3>
<p>Each event can trigger one or more actions: <b>play SFX</b>, <b>start/stop BGM</b>,
<b>increment/set variable</b>, <b>set flag</b>, <b>go to scene</b>, <b>add score</b>,
<b>add HP</b>, <b>fade</b>, <b>screen shake</b>, <b>save game</b>, <b>end game</b>…</p>
<p>The <b>[×1] once</b> option makes the action fire only once per scene load.</p>

<h3>C export — ngpc_entity_type_events.h</h3>
<pre>#define EV_ENTITY_DEATH       0u
#define EV_ENTITY_BTN_A       5u
/* … */
#define TYPE_EVENT_COUNT      2

static const NgpngTypeEvent g_type_events[] = {
    { ET_GOBLIN, 0u, 31u, 0u, 1u, 0u },  /* Goblin entity_death */
    { ET_CHEST,  5u,  1u, 5u, 0u, 0u },  /* Chest entity_btn_a → play_sfx 5 */
};</pre>
<p><b>Tree-shaking:</b> only types that are both referenced in a scene
<em>and</em> have at least one event are emitted.</p>
<p>The runtime calls <code>ngpc_entity_dispatch_event(type_id, event_id)</code>
at the right moment. The engine walks the table and executes matching actions.</p>

<h3>Scene trigger conditions by type (18 conditions)</h3>
<p>The scene <b>Triggers</b> tab also provides 18 conditions that evaluate the
current state of all instances of a type <em>in that scene</em>:</p>
<table>
  <tr><th>Condition</th><th>Value</th><th>Meaning</th></tr>
  <tr><td><code>entity_type_all_dead</code></td><td>—</td><td>All instances dead → open exit</td></tr>
  <tr><td><code>entity_type_count_ge</code></td><td>N</td><td>Killed ≥ N (cumulative)</td></tr>
  <tr><td><code>entity_type_alive_le</code></td><td>N</td><td>Alive ≤ N → boss phase change</td></tr>
  <tr><td><code>entity_type_any_alive</code></td><td>—</td><td>At least 1 alive (escort, survival)</td></tr>
  <tr><td><code>entity_type_collected</code></td><td>—</td><td>1 item picked up</td></tr>
  <tr><td><code>entity_type_collected_ge</code></td><td>N</td><td>Collected ≥ N → "5 coins → door"</td></tr>
  <tr><td><code>entity_type_all_collected</code></td><td>—</td><td>All items collected → "3 keys → boss"</td></tr>
  <tr><td><code>entity_type_activated</code></td><td>—</td><td>1 instance activated (NPC talked to)</td></tr>
  <tr><td><code>entity_type_all_activated</code></td><td>—</td><td>All activated → all switches ON</td></tr>
  <tr><td><code>entity_type_btn_a</code></td><td>—</td><td>A near an instance → play_sfx, interact</td></tr>
  <tr><td><code>entity_type_btn_b</code></td><td>—</td><td>B near an instance</td></tr>
  <tr><td><code>entity_type_btn_opt</code></td><td>—</td><td>Option near an instance</td></tr>
  <tr><td><code>entity_type_contact</code></td><td>—</td><td>Player overlaps an instance (hazard, heal)</td></tr>
  <tr><td><code>entity_type_near_player</code></td><td>—</td><td>Instance within range of player (aggro)</td></tr>
  <tr><td><code>entity_type_hit</code></td><td>—</td><td>1 instance hit → feedback, phase trigger</td></tr>
  <tr><td><code>entity_type_hit_ge</code></td><td>N</td><td>Total hits ≥ N → multi-phase boss</td></tr>
  <tr><td><code>entity_type_spawned</code></td><td>—</td><td>1 instance spawned → intro cutscene</td></tr>
  <tr><td><code>entity_type_spawned_ge</code></td><td>N</td><td>Total spawned ≥ N → wave management</td></tr>
  <tr><td><code>on_custom_event</code></td><td>Event ID</td><td>The specified custom event has been emitted → cross-system trigger</td></tr>
</table>
<p>A <b>Type combo</b> lists all entity types used in the scene.
Value-based conditions (N) show a spinner.</p>

<h2>Items (Items sub-tab)</h2>
<p>The <b>Items</b> sub-tab defines the project's <b>item table</b>: each row describes a
collectible (type, rarity, value). On export, <code>item_table.h</code> is generated with
all definitions.</p>

<h3>Table columns</h3>
<table>
  <tr><th>Column</th><th>Description</th></tr>
  <tr><td><b>Name</b></td><td>Human-readable identifier (comment in the header)</td></tr>
  <tr><td><b>Type</b></td><td>ITEM_HEAL, ITEM_ATK_UP, ITEM_DEF_UP, ITEM_XP_UP, ITEM_GOLD, ITEM_DICE_PLUS, ITEM_KEY, ITEM_CUSTOM</td></tr>
  <tr><td><b>Rarity</b></td><td>RARITY_COMMON, RARITY_UNCOMMON, RARITY_RARE</td></tr>
  <tr><td><b>Value</b></td><td>u8 integer (effect magnitude: HP restored, ATK bonus…)</td></tr>
</table>

<h3>Generated header — item_table.h</h3>
<pre>/* item_table.h */
#define ITEM_HEAL      0
#define ITEM_ATK_UP    1
/* ... */
#define RARITY_COMMON   0
#define RARITY_UNCOMMON 1
#define RARITY_RARE     2

typedef struct { u8 type; u8 value; u8 rarity; u8 price; u8 sprite_id; } NgpcItem;

static const NgpcItem g_item_table[] = {
    /* [0] potion_heal  */ { ITEM_HEAL,   RARITY_COMMON,   3 },
    /* [1] sword_up     */ { ITEM_ATK_UP, RARITY_UNCOMMON, 1 },
};</pre>
<p>Add items with the <b>＋</b> button; remove with <b>－</b>. Each row is editable
directly in the table.</p>

<h2>Custom Events</h2>
<p><b>Custom events</b> close the <code>emit_event</code> loop: when a scene trigger or
entity type event fires <code>emit_event(id)</code>, the engine looks up this table to
know what to do.</p>
<p>Define them in <b>Globals → Events tab</b>.</p>

<h3>Full flow</h3>
<ol>
  <li>In <b>Globals → Events</b>, create an event (e.g. <code>boss_phase_2</code>),
      add <b>guard conditions</b> (AND/OR), and attach actions.</li>
  <li>In any scene trigger or entity type event, choose the <code>emit_event</code>
      action — the combo now shows <b>[0] boss_phase_2</b> instead of a raw spinner.</li>
  <li>On export, <code>ngpc_custom_events.h</code> is generated with macros, a guard
      condition table, and an action table.</li>
  <li>The runtime calls <code>ngpc_emit_event(u8 id)</code> — the engine evaluates the
      guards, then executes every action bound to that id.</li>
</ol>

<h3>UI — Events tab (Globals)</h3>
<p>The tab has two areas:</p>
<ul>
  <li><b>Top panel — event list</b>: create, rename, delete, reorder (↑/↓). Events can be
      grouped into <b>categories</b> (visual separators) to keep the project organised.</li>
  <li><b>Bottom panel — "Conditions" and "Actions" sub-tabs</b>:</li>
</ul>
<p><b>Conditions sub-tab:</b></p>
<ul>
  <li><b>AND group (primary)</b>: all conditions in this list must be true for the event
      to fire.</li>
  <li><b>OR groups</b>: add alternative groups. The event fires if the AND group passes
      OR if <i>all</i> conditions in any OR group pass.</li>
  <li>If no conditions are defined, the event always fires.</li>
  <li>Each condition can be <b>negated (NOT)</b>.</li>
</ul>
<p><b>Actions sub-tab</b>: 57 actions in 11 groups (Audio, Visual, Navigation, Entities,
Player, Flags/Variables, Camera/Scroll, Triggers/HUD, Narrative, RPG/Quest,
System). A <b>Presets ▾</b> button inserts common combinations.</p>

<h3>Guard logic — summary</h3>
<pre>Fire if:
  (all AND conditions pass) OR (all conds in OR group 0) OR (all in OR group 1) OR ...
No conditions → always fire.</pre>

<h3>⚠️ Order = C index</h3>
<p>Reordering events changes their <code>CEV_*</code> values and invalidates existing
<code>emit_event(id)</code> calls in already-compiled ROMs. In production,
<b>always append to the end of the list</b>.</p>

<h3>Consuming a custom event from a scene trigger (flag bridge)</h3>
<p>Scene triggers cannot directly listen for a custom event. The recommended pattern
is the <b>flag bridge</b>:</p>
<ol>
  <li>Custom event action: <code>set_flag(N)</code></li>
  <li>Scene trigger condition: <code>flag_set(N)</code> → actions + <code>clear_flag(N)</code></li>
</ol>
<p>This lets any scene react to any custom event.</p>

<h3>Available actions (57)</h3>
<table>
  <tr><th>Group</th><th>Actions</th></tr>
  <tr><td>Audio</td><td>play_sfx, start_bgm, stop_bgm, fade_bgm</td></tr>
  <tr><td>Visual / Effects</td><td>play_anim, screen_shake, fade_out, fade_in</td></tr>
  <tr><td>Navigation</td><td>goto_scene, warp_to, set_checkpoint, respawn_player, reset_scene</td></tr>
  <tr><td>Entities</td><td>spawn_entity, show_entity, hide_entity, move_entity_to, spawn_wave,
      spawn_at_region, pause_entity_path, resume_entity_path</td></tr>
  <tr><td>Player</td><td>force_jump, lock_player_input, unlock_player_input,
      enable_multijump, disable_multijump, enable_wall_grab, disable_wall_grab,
      cycle_player_form, set_player_form, fire_player_shot, set_gravity_dir</td></tr>
  <tr><td>Flags / Variables</td><td>set_flag, clear_flag, set_variable, inc_variable, dec_variable</td></tr>
  <tr><td>Camera / Scroll</td><td>set_scroll_speed, set_cam_target, pause_scroll, resume_scroll</td></tr>
  <tr><td>Triggers / HUD</td><td>enable_trigger, disable_trigger, add_score, add_health, set_health</td></tr>
  <tr><td>Narrative / Dialogue</td><td>show_dialogue, play_cutscene, set_npc_dialogue</td></tr>
  <tr><td>RPG / Quest</td><td>give_item, remove_item, drop_item, drop_random_item, unlock_door, unlock_ability,
      set_quest_stage, add_resource, remove_resource</td></tr>
  <tr><td>System</td><td>emit_event, save_game, end_game</td></tr>
</table>
<p><b>Note — template-dependent actions:</b> some actions (<code>unlock_ability</code>,
<code>add_resource</code>, <code>set_gravity_dir</code>, <code>cycle_player_form</code>, etc.)
emit the correct <code>TRIG_ACT_*</code> constant but require your <b>C template</b> to
implement the matching case in <code>ngpng_trigger_execute_action()</code>. They are
available in the engine as hooks to wire up.</p>

<h3>Available guard conditions (88)</h3>
<p>Same vocabulary as scene triggers and entity type events.
Organised in 9 groups in the dialog:</p>
<table>
  <tr><th>Group</th><th>Examples</th></tr>
  <tr><td>Player — buttons</td><td>btn_a, btn_b, btn_held_ge…</td></tr>
  <tr><td>Player — state</td><td>health_le, on_jump, on_land, score_ge, player_has_item, item_count_ge…</td></tr>
  <tr><td>Camera / Scroll</td><td>cam_x_ge, cam_y_ge, enter_region, leave_region</td></tr>
  <tr><td>Timer / Wave</td><td>timer_ge, timer_every, wave_ge, scene_first_enter…</td></tr>
  <tr><td>Flags / Variables</td><td>flag_set, flag_clear, variable_ge, variable_eq…</td></tr>
  <tr><td>Entities — global</td><td>enemy_count_le, entity_alive, entity_contact…</td></tr>
  <tr><td>Entities — by type</td><td>entity_type_all_dead, entity_type_count_ge…</td></tr>
  <tr><td>Quest / Narrative</td><td>quest_stage_eq, dialogue_done, cutscene_done…</td></tr>
  <tr><td>Resources / Random</td><td>resource_ge, chance</td></tr>
</table>

<h3>C export — ngpc_custom_events.h</h3>
<pre>#define CEV_BOSS_PHASE_2    0u
#define CEV_KEY_COLLECTED   1u
#define CUSTOM_EVENT_COUNT      3   /* action rows */
#define CUSTOM_EVENT_COND_COUNT 1   /* guard condition rows */

/* Guard condition struct */
typedef struct {
    u8 event_id; u8 cond; u8 index; u16 value; u8 group_id; u8 negate;
} NgpngCevCond;
/* group_id = 0xFF → primary AND group, 0..N → OR group N */

static const NgpngCevCond g_cev_conds[] = {
    { CEV_BOSS_PHASE_2, 22u, 0u, 0u, 0xFFu, 0u }, /* flag_set[0] AND */
};

typedef struct {
    u8 event_id; u8 action; u8 a0; u8 a1; u8 once;
} NgpngEventAction;

static const NgpngEventAction g_custom_events[] = {
    { CEV_BOSS_PHASE_2,  2u, 2u, 0u, 0u },  /* start_bgm 2 */
    { CEV_BOSS_PHASE_2, 15u, 3u, 0u, 0u },  /* screen_shake 3 */
    { CEV_KEY_COLLECTED,31u, 0u, 0u, 0u },  /* inc_variable[0] */
};</pre>
<p>The runtime evaluates guards first, then actions:</p>
<pre>void ngpc_emit_event(u8 id) {
    /* 1. Evaluate guard conditions (AND + OR groups) */
    if (!ngpng_cev_guard_passes(id)) return;
    /* 2. Execute all actions bound to this id */
    for (u8 i = 0; i &lt; CUSTOM_EVENT_COUNT; ++i)
        if (g_custom_events[i].event_id == id)
            ngpng_exec_action(&amp;g_custom_events[i]);
}</pre>
<p><b>Tree-shaking:</b> if <code>CUSTOM_EVENT_COUNT == 0</code> (no events defined), the
table is empty and no dead symbols are emitted.</p>
"""


def _en_vram() -> str:
    return """
<h1>VRAM Map</h1>

<h2>Overview</h2>
<p>The VRAM Map tab visualises the console's resource usage:</p>
<ul>
  <li><b>512 tile slots</b> — a 32×16 grid (each cell = one VRAM tile).</li>
  <li><b>16 sprite palette slots</b> — sprite palette bank.</li>
  <li><b>16 BG palettes (SCR1)</b> and <b>16 BG palettes (SCR2)</b> — scroll-plane palette banks.</li>
</ul>
<p>By default, the displayed budget matches the <b>currently selected scene</b> (from the Project tab).
You can also pick another scene directly from this tab, or request the <b>worst case</b>.</p>
<p>Values may show a <b>~</b> when they are estimates (missing files, or export tools not found).
When possible, the computation tries to match the <b>real export</b> (tile deduplication).</p>

<h2>Color code — tile slots</h2>
<table>
  <tr><th>Color</th><th>Range</th><th>Meaning</th></tr>
  <tr><td style="background:#373747;color:#aaa">■ Dark grey</td><td>0–31</td><td>Reserved (hardware)</td></tr>
  <tr><td style="background:#555565;color:#aaa">■ Medium grey</td><td>32–127</td><td>System font (BIOS SYSFONTSET)</td></tr>
  <tr><td style="background:#569ed6;color:#fff">■ Color</td><td>128+</td><td>Sprite</td></tr>
  <tr><td style="background:#4ec9b0;color:#fff">■ Color</td><td>128+</td><td>Tilemap</td></tr>
  <tr><td style="background:#f44747;color:#fff">■ Red</td><td>—</td><td>Conflict / overlap (two assets share the same slots)</td></tr>
  <tr><td style="background:#1e1e28;color:#555">■ Black</td><td>—</td><td>Free</td></tr>
</table>
<p>When a conflict is detected, a <b>Suggestions</b> section appears below the grid to propose
a fix (e.g. move <code>spr_tile_base</code> or auto-pack tilemaps).</p>

<h2>Hover tooltip</h2>
<p>Hover over any cell to see its slot number and status
(reserved / sysfont / sprite / free) in the tooltip.</p>

<h2>Sprite palette slots — rich bank</h2>
<p>The <b>Sprites (16)</b> section shows a 16-slot bank. Each occupied slot displays:</p>
<ul>
  <li><b>4 colour swatches</b> for the 4 hardware palette entries
      (index 0 = transparent = dark square).</li>
  <li><b>×N badge</b> in yellow if multiple sprites share this slot via
      <code>fixed_palette</code>.</li>
  <li><b>Tooltip</b>: name(s) of the owning sprite(s).</li>
  <li><b>Click</b>: opens the sprite directly in the Palette tab.</li>
</ul>
<p>BG palettes (<b>SCR1</b> and <b>SCR2</b>) use the simpler bar display.</p>
<p>The tool also shows an <b>identical bank analysis</b> per plane: if two scene tilemaps reuse the exact same BG palettes on SCR1 or SCR2, the VRAM tab reports it. This is a diagnostic aid only for now; export-time dedupe is not automatic yet.</p>

<h2>Automatic refresh</h2>
<p>The map is refreshed automatically when you select a scene in the Project tab
or when the project is modified.</p>
"""


def _en_bundle() -> str:
    return """
<h1>Bundle (scene packer)</h1>

<h2>Role</h2>
<p>The Bundle tab works directly on the <b>active scene sprite list</b>
(same list as the Project tab). Its goals are:</p>
<ul>
  <li>compute cascading <code>tile_base</code> / <code>pal_base</code>,</li>
  <li>visualize budgets,</li>
  <li>batch-export with the correct <code>--tile-base</code> / <code>--pal-base</code>.</li>
</ul>

<h2>Start values</h2>
<table>
  <tr><th>Field</th><th>Default</th><th>Description</th></tr>
  <tr><td><b>tile_base start</b></td><td>256</td><td>First VRAM tile slot for this scene sprites (<code>scene.spr_tile_base</code>)</td></tr>
  <tr><td><b>pal_base start</b></td><td>0</td><td>First sprite palette slot for this scene (<code>scene.spr_pal_base</code>)</td></tr>
</table>
<p>These values are stored per-scene in the <code>.ngpcraft</code> file (not as a separate global bundle list).</p>

<h2>Sprite table</h2>
<p>Each row is a sprite from the scene. Calculated columns update automatically.</p>
<table>
  <tr><th>Column</th><th>Description</th></tr>
  <tr><td><b>#</b></td><td>Export order (starts at 1)</td></tr>
  <tr><td><b>Img</b></td><td>Thumbnail preview</td></tr>
  <tr><td><b>File</b></td><td>Source PNG name</td></tr>
  <tr><td><b>W / H</b></td><td>Frame size in pixels (editable, multiples of 8 recommended)</td></tr>
  <tr><td><b>Fr.</b></td><td>Frame count (editable)</td></tr>
  <tr><td><b>Reuse pal</b></td><td>Share the previous sprite palette slot (valid only if <code>fixed_palette</code> matches and the sprite uses a single palette)</td></tr>
  <tr><td><b>Tiles~</b></td><td>Unique tile count (when <code>ngpc_sprite_export.py</code> is available). Prefix <code>~</code> = estimated</td></tr>
  <tr><td><b>tile_base</b></td><td>Automatically computed VRAM slot</td></tr>
  <tr><td><b>pal_base</b></td><td>Automatically computed palette slot</td></tr>
</table>

<h2>Actions</h2>
<ul>
  <li><b>+ Add…</b> — add a sprite to the active scene (then configure W/H/Fr.).</li>
  <li><b>Drag & drop</b> — you can also reorder sprites by dragging a table row.</li>
  <li><b>↑ / ↓</b> — reorder the scene sprites (also impacts the Project tab).</li>
  <li><b>Open in Palette</b> — opens the selected entry in the Palette tab with anim config.</li>
  <li><b>✕ Remove</b> — delete the selected entry.</li>
  <li><b>▶ Export all</b> — call <code>ngpc_sprite_export.py</code> for each scene sprite in order,
      with the correct <code>--tile-base</code> and <code>--pal-base</code>.</li>
  <li><b>Save config</b> — saves the project (<code>.ngpcraft</code>).</li>
</ul>

<h2>Budget and overflow</h2>
<p>The total budget is displayed below the table. If the bundle exceeds 512 tiles or
16 palettes, a ⚠ warning appears <b>before</b> you launch the export.</p>

<h2>Export log</h2>
<p>The bottom panel shows the result of each export:</p>
<pre>[OK] player — 4 tiles, pal 0
[OK] enemy1 — 1 tile, pal 1
[SKIP] boss — file not found</pre>
"""


def _en_tilemap() -> str:
    return """
<h1>Tilemap Preview</h1>

<h2>Role</h2>
<p>The Tilemap tab opens a PNG and displays an <b>8×8 tile grid</b>
color-coded by the number of opaque colors in each tile.
It is a pre-diagnostic before running <code>ngpc_tilemap.py</code>.</p>
<p><b>Sizes (NGPC)</b>: the visible screen is 20×19 tiles (160×152 px) and the hardware BG map is limited to 32×32 tiles (256×256 px).
The tool now shows this reminder directly in the Tilemap tab (and in the New/Resize dialogs).</p>
<p><b>Checklist</b>: just below the contextual help, a small checklist also summarizes whether the source PNG is loaded/saved, whether size stays within NGPC limits, whether tiles require an SCR1/SCR2 split, whether collision is ready, and whether <code>ngpc_tilemap.py</code> export can run.</p>
<p><b>Interface</b>: the top area keeps a <b>compact picker</b> for scene tilemaps, but secondary settings now sit behind an <b>Options</b> button. <b>Zoom</b> stays permanently visible so the editing workflow does not regress.</p>

<h2>Color code</h2>
<table>
  <tr><th>Color</th><th>Count</th><th>Meaning</th></tr>
  <tr><td><span style="color:#00c850">■ Green</span></td><td>1 – 3</td>
      <td>OK — tile can be exported as single-layer</td></tr>
  <tr><td><span style="color:#ffa000">■ Orange</span></td><td>4</td>
      <td>Borderline — may cause issues depending on palette config</td></tr>
  <tr><td><span style="color:#ff2020">■ Red</span></td><td>5+</td>
      <td>Error — tile requires dual-layer or color reduction</td></tr>
</table>

<h2>Zoom</h2>
<p>The <code>×1 ×2 ×4 ×8 ×16 ×32</code> buttons zoom the grid using nearest-neighbor scaling.
Enable <b>Grid</b> to draw 8×8 tile lines (essential at ×1/×2).
Hovering over a tile shows its coordinates and color count in a tooltip.</p>

<h2>Edit (paint by tile)</h2>
<p>A small edit mode lets you <b>copy/paste 8×8 tiles</b> directly inside the PNG:</p>
<ul>
  <li>Enable <b>Edit</b>.</li>
  <li><b>Tools</b>: use the <b>Paint / Pick / Erase / Fill / Replace / Select / Stamp</b> buttons.</li>
  <li><b>Stamp</b>: a cyan preview rectangle shows the area that will be pasted on hover. You can feed it either with <b>Ctrl+C</b> from a map selection, or by <b>selecting several tiles in the tileset</b>.</li>
  <li><b>Shape</b>: for <b>Paint</b>, <b>Erase</b>, and <b>Stamp</b>, the <b>Shape</b> picker now supports <b>Free</b>, <b>Rect</b>, and <b>Ellipse</b>. In Rect/Ellipse mode, click-drag to preview the shape, then apply it on release.</li>
  <li><b>Stamp presets</b>: the <b>Save / Load / Delete</b> block can also keep named reusable stamps. They are stored in the tool settings, not inside the tilemap file itself.</li>
  <li><b>Variation</b>: with several tiles selected in the tileset, enabling <b>Variation</b> prepares a random brush instead of a stamp. This is useful to break repetition on `Paint`, `Fill`, and `Replace` without leaving the editing flow.</li>
  <li><b>Shortcuts...</b>: this button opens a small shortcut editor for Tilemap tools (`Paint`, `Pick`, `Erase`, `Fill`, `Replace`, `Select`, `Stamp`) and stamp transforms (`Flip H`, `Flip V`, `Rot 90`). Standard shortcuts such as `Ctrl+Z/Ctrl+S/Ctrl+C/Ctrl+V` are not affected.</li>
  <li><b>Tool shortcuts</b>: B=paint, P=pick, E=erase, F=fill, R=replace, S=select, M=stamp (customizable via "Shortcuts…").</li>
  <li><b>File shortcuts</b>: <code>Ctrl+O</code>=open, <code>Ctrl+N</code>=new, <code>Ctrl+S</code>=save.</li>
  <li><b>F5</b>: run <code>ngpc_tilemap.py</code> on the current file.</li>
  <li><b>Tileset</b>: click a tile on the left to pick it as the <b>brush</b>. A <b>multi-selection</b> in the tileset automatically prepares a <b>stamp block</b>.</li>
  <li><b>Load…</b>: loads a tileset from another PNG (Tileset panel button). In project mode, the path can be saved for auto-load.</li>
  <li><b>Alt+click</b> a tile in the map: picker (sets it as the <b>brush</b>).</li>
  <li><b>Left-click</b>: paint (paste) the brush.</li>
  <li><b>Right-click</b>: erase the tile (transparent tile).</li>
  <li><b>Drag</b>: hold left/right click and move the mouse to paint/erase multiple tiles.</li>
  <li><b>Shift+click</b>: draws a line with the current brush. Flood fill stays on the dedicated <b>Fill</b> tool.</li>
  <li><b>Ctrl+click</b>: replace all identical tiles in the map.</li>
  <li><b>Select</b>: drag to select an area. <b>Ctrl+C</b> copy, <b>Ctrl+X</b> cut, <b>Ctrl+V</b> paste, <b>Del</b> clears.</li>
  <li><b>Undo/Redo</b>: Ctrl+Z / Ctrl+Y.</li>
  <li><b>Save</b>: Ctrl+S.</li>
  <li><b>Resize…</b>: resizes the canvas (in tiles) and pastes existing content according to an anchor.</li>
</ul>

<h2>Collision (tileset)</h2>
<p>The <b>Collision</b> sub-tab lets you assign a <b>collision type per unique tile</b>
(NONE/SOLID/PLATFORM/...). A colored overlay is shown on the map, and you can:</p>
<ul>
  <li><b>Overlay</b>: choose <b>max</b> (combine SCR1/SCR2) or <b>SCR1</b>/<b>SCR2</b> to visualize a plane.</li>
  <li><b>Export .h…</b>: generates a <code>*_col.h</code> header indexed by tile (same order as the tilemap export).</li>
  <li><b>Save to project</b>: stores the collision table into the <code>.ngpcraft</code> (project mode).</li>
</ul>

<h2>SCR1 / SCR2</h2>
<p>If some tiles exceed 3 opaque colors, export may switch to <b>2 layers</b>:
SCR1 and SCR2 are the <b>two NGPC scroll planes</b>. Depending on the priority you set in
your game code, SCR1 can be in front of SCR2 (or the opposite). The <b>Export SCR1/SCR2 PNG</b>
button generates two PNGs (<code>_scr1.png</code> / <code>_scr2.png</code>) so you can inspect/retouch the split.</p>

<h2>Target plane (SCR1/SCR2)</h2>
<p>The <b>Target plane</b> field is <b>project metadata</b>: when the tilemap is single-layer, it tells
which scroll plane (SCR1/SCR2) you intend to load it on in your game code.
It is mainly used for <b>BG palette budgeting</b> in the VRAM tab. If export is dual-layer
(SCR1+SCR2), this field is ignored.</p>

<h2>Statistics</h2>
<ul>
  <li><b>Total</b> — number of tiles (width/8 × height/8).</li>
  <li><b>OK / Borderline / Error</b> — breakdown by category.</li>
  <li><b>Unique tiles</b> — deduplication estimate (same pixel data ⇒ same tile).</li>
  <li><b>Predicted result</b> — "single-layer ✓" if all tiles are ≤ 3 colors,
      "dual-layer required ⚠" otherwise.</li>
</ul>

<h2>Running ngpc_tilemap.py</h2>
<p>The <b>Generate C files</b> button runs <code>ngpc_tilemap.py</code> and writes a
<code>_map.c</code> file (and optionally <code>.h</code>) next to the PNG.</p>
<ul>
  <li>If <b>SCR2</b> is set: explicit dual-layer export (SCR1+SCR2).</li>
  <li>Otherwise: if a tile exceeds 3 colors, the script automatically switches to <b>auto-split</b> (SCR1+SCR2).</li>
</ul>

<h2>Tile compression (optional)</h2>
<p>The <b>Compress tiles</b> checkbox enables a compression pass after
<code>ngpc_tilemap.py</code> runs. <code>tools/ngpc_compress.py</code> is invoked automatically and
produces a <code>*_lz.c</code> or <code>*_rle.c</code> file + matching <code>.h</code> —
compressed data ready to be decompressed directly to tile VRAM at runtime.</p>
<table>
  <tr><th>Mode</th><th>Typical ratio</th><th>Best for</th></tr>
  <tr><td><b>Auto (smaller)</b></td><td>—</td><td>Tries both LZ77 and RLE, keeps the shorter result</td></tr>
  <tr><td><b>LZ77</b></td><td>~3:1 to 4:1</td><td>Varied tilesets — best general compression</td></tr>
  <tr><td><b>RLE</b></td><td>~2:1</td><td>Uniform areas (sky, solid walls) — ultra-fast decompression</td></tr>
</table>
<p><b>Runtime:</b> instead of <code>NGP_TILEMAP_LOAD_TILES_VRAM</code>, use the
<code>ngpc_lz.h</code> helpers:</p>
<pre>#include "level1_tiles_lz.h"
ngpc_lz_to_tiles(level1_tiles_lz, level1_tiles_lz_len, 128);
// or
#include "level1_tiles_rle.h"
ngpc_rle_to_tiles(level1_tiles_rle, level1_tiles_rle_len, 128);</pre>
<p>The generated header exports <code>extern const u8 name_lz[]</code> and
<code>extern const u16 name_lz_len</code> (or <code>_rle</code> variants).</p>
<p><b>Limit:</b> the internal decompression buffer is <b>2 KB</b> (~128 tiles max per call).
For larger tilesets split into multiple calls with an increasing tile offset,
or leave the tile data uncompressed.</p>

<h2>Tips</h2>
<ul>
  <li>If some tiles are red, edit the PNG in Aseprite to reduce the color count
      in those 8×8 areas.</li>
  <li>Alternative: let <code>ngpc_tilemap.py</code> auto-generate SCR1+SCR2 (auto-split),
      then use <b>Export SCR1/SCR2 PNG</b> if you want to manually control the result.</li>
  <li>The ≤ 3 opaque color rule applies <b>per 8×8 tile</b>, not to the whole image —
      an image with 20 colors can be perfectly valid if they don't mix in the same tile.</li>
</ul>

<h2>Large tilemaps (automatic streaming)</h2>
<p>Backgrounds <b>larger than 32×32 tiles</b> are supported. The NGPC hardware window is 32×32,
but its toroidal scroll behavior is exploited: as the camera advances, off-screen columns/rows are
rewritten in VRAM on-the-fly (streaming).</p>
<p><b>For PNG Manager projects:</b> the workflow is identical to a normal tilemap.
Simply export the large PNG as a scene background — the exporter automatically generates
<code>scene_X_stream_planes()</code> called every frame. No extra code needed.</p>
<table>
  <tr><th>Unique tiles</th><th>Status</th></tr>
  <tr><td>≤ 256</td><td>✅ Comfortable — room for sprites</td></tr>
  <tr><td>257 – 320</td><td>⚠ Warning — little sprite room left</td></tr>
  <tr><td>321 – 384</td><td>🔶 Critical limit</td></tr>
  <tr><td>&gt; 384</td><td>🔴 VRAM overflow — reduce tileset</td></tr>
</table>
<p><b>Tip:</b> repeated tiles (ground, sky, wall) are deduplicated — a 128×32 level often fits in
50–100 unique tiles. Recommended sizes: platformer 64–128×20, shmup 20×64–128, top-down 64×64.</p>

"""


def _en_pipeline() -> str:
    return """
<h1>Export Pipeline</h1>

<h2>Overview</h2>
<pre>Source PNG
  │
  ▼  (NgpCraft Engine — Palette tab)
Remapped RGB444 PNG
  │
  ▼  (ngpc_sprite_export.py)
*_mspr.c + *_mspr.h
  │
  ▼  (Makefile / ngpc_sprite_bundle.py)
ROM cartridge (.ngp)</pre>

<h2>Headless mode (CLI)</h2>
<p>The <code>ngpcraft_engine.py</code> entry point can export a project without starting the Qt UI.
Headless mode uses the same export engine as the <b>Project</b> tab and produces the same generated
C files, headers and reports.</p>
<pre>python ngpcraft_engine.py --export project.ngpcraft
python ngpcraft_engine.py --export project.ngpcraft --scene Act1
python ngpcraft_engine.py --export project.ngpcraft --sprite-tool /path/to/ngpc_sprite_export.py
python ngpcraft_engine.py --export project.ngpcraft --tilemap-tool /path/to/ngpc_tilemap.py
python ngpcraft_engine.py --validation-suite path/to/output_folder
python ngpcraft_engine.py --validation-run path/to/output_folder
python ngpcraft_engine.py --validation-run path/to/output_folder --build
python ngpcraft_engine.py --validation-run path/to/output_folder --build --smoke-run</pre>
<p><b>Validation suite:</b> <code>--validation-suite</code> scaffolds 4 mini-projects from the real template
(`Sprite Lab`, `Mini Shmup`, `Mini Platformer`, `Mini Top-Down`) so the full pipeline can be checked on realistic cases.</p>
<p><b>Validation run:</b> <code>--validation-run</code> goes one step further: it generates those 4 projects, runs headless export on each, then writes <code>VALIDATION_RUN.md</code> + <code>validation_run.json</code>.</p>
<p><b>Validation run + build:</b> with <code>--build</code>, the routine also runs <code>make</code> inside each generated project after export. The report then includes build status per project.</p>
<p>Note: this mode assumes a real NGPC toolchain is installed and runnable (<code>make</code>, cc900/T900, helper tools).</p>
<p><b>Validation run + runtime smoke:</b> with <code>--smoke-run</code>, the routine then looks for the newest ROM and attempts a short emulator launch if one is found in the <code>PATH</code> (or via the <code>NGPNG_SMOKE_EMULATOR</code> environment variable). If no emulator is found, the report simply marks the smoke test as skipped.</p>

<h2>Export dir + Makefile (assets_autogen.mk)</h2>
<p>In the <b>Project</b> tab, <b>Export dir</b> lets you write all generated <code>.c/.h</code> into a
single directory (example: <code>GraphX/gen</code>) instead of next to the PNG files.</p>
<p>When <b>Export dir</b> is set, NgpCraft Engine also auto-generates
<code>assets_autogen.mk</code> inside that directory, appending the compiled objects to
<code>OBJS</code> (no more manual list edits).</p>
<pre># Example Makefile (template)
include GraphX/gen/assets_autogen.mk</pre>
<p><b>Beginner (no-code)</b>: use the <b>Export (template-ready)</b> button (Project tab).
It exports all scenes, then <b>auto-patches the makefile</b> and writes <code>src/ngpng_autorun_main.c</code>
so you can build/run immediately without editing code.</p>
<p><b>Disable autorun:</b> pass <code>NGPNG_AUTORUN=0</code> to make (or set it in the environment) to keep <code>src/main.c</code>.
<b>Rollback:</b> restore <code>makefile.bak_ngpng</code> (created once) and delete <code>src/ngpng_autorun_main.c</code>.</p>
<p><b>Audio (autorun):</b> when audio is enabled (<code>NGP_ENABLE_SOUND=1</code>) and an SFX mapping exists,
<b>A</b> plays the current SFX and <b>OPTION</b> cycles the ID. BGM can autostart via
<code>SCENE_*_BGM_AUTOSTART</code>.</p>
<p>When you export a <b>scene</b> (button <b>Scene → .c</b>), the tool also generates:</p>
<ul>
  <li>a <code>scene_*.h</code> header (template-ready loader) with:
      <code>scene_xxx_blit_tilemaps()</code>, <code>scene_xxx_load_sprites()</code>, <code>scene_xxx_load_all()</code>,
      <code>scene_xxx_enter()</code>, <code>scene_xxx_exit()</code>, <code>scene_xxx_update()</code></li>
  <li>a <code>scene_*_level.h</code> header (gameplay): entities/waves + collision + layout/scroll</li>
  <li>a global manifest <code>scenes_autogen.c/.h</code> (already-exported scenes list + metadata + hooks)</li>
</ul>
<p><b>Minimal game-side usage:</b> <code>#include "scenes_autogen.h"</code>, then
<code>g_ngp_scenes[NGP_SCENE_START_INDEX].enter();</code> and call
<code>g_ngp_scenes[i].update();</code> every frame.</p>
<p>The <code>scene_*.h</code> header automatically includes <code>scene_*_level.h</code>,
so one include on the game side is enough.</p>

<h3>Audio helpers (optional)</h3>
<p><b>Supported format: hybrid C export only.</b>
In Sound Creator, use <i>Project → Export All</i> (C mode). This generates
<code>project_audio_manifest.txt</code>, <code>project_instruments.c</code>, <code>project_sfx.c</code>
and one <code>song_*.c</code> per BGM. The PSG driver (<code>sounds.c</code>) is embedded in ROM and
interprets the bytecode streams at runtime. Without <code>project_instruments.c</code>, BGM cannot play.</p>
<p>When <code>NGP_ENABLE_SOUND</code> is enabled in the template, the generated <code>scene_*.h</code> provides:</p>
<ul>
  <li><code>scene_xxx_enter()</code>: equivalent to <code>scene_xxx_load_all()</code> + <code>scene_xxx_audio_enter()</code>.</li>
  <li><code>scene_xxx_audio_enter()</code>: starts the BGM if <code>SCENE_*_BGM_AUTOSTART</code> is true.</li>
  <li><code>scene_xxx_audio_update()</code>: calls <code>Sounds_Update()</code> (call every frame).</li>
  <li><code>scene_xxx_audio_exit()</code>: optional fade-out (<code>SCENE_*_BGM_FADE_OUT</code>).</li>
</ul>
<p><b>Build:</b> when using Sound Creator “Project Export All”, NgpCraft Engine can generate an
<code>audio_autogen.mk</code> file (in <code>export_dir</code> when configured) to automatically append
exported <code>.c</code> files to <code>OBJS</code>. The file wraps the list under
<code>ifneq ($(strip $(NGP_ENABLE_SOUND)),0)</code>.</p>
<p><b>Note:</b> <code>assets_autogen.mk</code> automatically tries <code>-include audio_autogen.mk</code>
(same folder), so in practice keeping the template include
<code>include GraphX/gen/assets_autogen.mk</code> is enough.</p>
<p><b>SFX:</b> the Audio panel lets you define a “gameplay IDs → Sound Creator IDs” mapping and export can generate
<code>ngpc_project_sfx_map.h</code> (enum + table) for game-side integration.</p>
<p>When an SFX mapping is defined, NgpCraft Engine also generates <code>sounds_game_sfx_autogen.c</code> (in the audio <code>exports/</code> folder)
and automatically enables <code>SFX_PLAY_EXTERNAL=1</code> via <code>audio_autogen.mk</code>.</p>
<p>If the audio manifest is <code>ASM</code> mode, SFX autogen is disabled (it requires C exports: <code>project_sfx.c</code>).</p>

<h2>Watchdog in long init loops</h2>
<p>The NGPC watchdog <b>must receive <code>0x4E</code> every ~100 ms</b> or the CPU silently resets.
During normal gameplay, VBlank (60 fps ≈ 16 ms) kicks it automatically in <code>isr_vblank()</code>.</p>
<p><b>Risk:</b> a long initialization loop running <i>before</i> the first VBlank
(tile upload, tilemap clear, decompression, procedural generation…) can exceed 100 ms
and trigger a reset. Symptom: white screen or return to the BIOS menu at startup.</p>
<p><b>Pattern (kick every ~64 iterations):</b></p>
<pre>u16 _wdog = 0;
while (...) {
    /* ... work ... */
    if ((++_wdog &amp; 63u) == 0u)
        HW_WATCHDOG = WATCHDOG_CLEAR;  /* = *(u8*)0x006F = 0x4E */
}</pre>
<p>64 iterations is a conservative choice: even a slow loop on a T900 at 6.144 MHz
stays well within the 100 ms budget per 64-iteration chunk.</p>
<p>Reference: <i>Metal Slug 1st Mission</i> (disassembly §4.2 / §17.3) — same pattern used
in all native ROM loaders.</p>

<h2>ngpc_sprite_export.py</h2>
<p>Converts a PNG spritesheet to C data ready to load into VRAM.</p>
<pre>python tools/ngpc_sprite_export.py GraphX/player.png \\
    -o GraphX/player_mspr.c \\
    --frame-w 16 --frame-h 16 \\
    --tile-base 256 --pal-base 0 \\
    --header</pre>
<table>
  <tr><th>Option</th><th>Description</th></tr>
  <tr><td><code>--tile-base N</code></td><td>First tile slot in VRAM (default 0)</td></tr>
  <tr><td><code>--pal-base N</code></td><td>First palette slot (0-15)</td></tr>
  <tr><td><code>--fixed-palette A,B,C,D</code></td><td>Force an external RGB444 palette (sharing)</td></tr>
  <tr><td><code>--frame-count N</code></td><td>Number of frames to export (0 = all)</td></tr>
  <tr><td><code>--anim-duration N</code></td><td>Duration per frame in animation table</td></tr>
</table>

<h2>ngpc_sprite_bundle.py</h2>
<p>Exports multiple sprites in sequence, automatically managing
<code>tile_base</code> and <code>pal_base</code>.</p>
<pre>from ngpc_sprite_bundle import SpriteBundle, make_sheet, load_rgba

bundle = SpriteBundle(project_root, out_dir, gen_dir, tile_base=256, pal_base=0)
bundle.export("player", player_sheet, 16, 16)
bundle.export("enemy",  enemy_sheet,  8,  8)</pre>

<h2>Palette sharing (--fixed-palette)</h2>
<p>Two sprites that share the exact same colors can reuse the same palette slot,
saving one of the 16 available slots.</p>
<ol>
  <li>Export the first sprite normally → 1 palette consumed.</li>
  <li>In NgpCraft Engine, copy <code>--fixed-palette</code> from the Palette tab.</li>
  <li>Export the second sprite with that argument → 0 additional palettes.</li>
</ol>

<h2>Generated files</h2>
<table>
  <tr><th>Symbol</th><th>Type</th><th>Content</th></tr>
  <tr><td><code>name_tiles[]</code></td><td>const u16[]</td><td>2bpp tile data</td></tr>
  <tr><td><code>name_tiles_count</code></td><td>const u16</td><td>Word count (= tile_count × 8)</td></tr>
  <tr><td><code>name_palettes[]</code></td><td>const u16[]</td><td>RGB444 words (4 × palette_count)</td></tr>
  <tr><td><code>name_tile_base</code></td><td>const u16</td><td>Starting tile slot in VRAM</td></tr>
  <tr><td><code>name_pal_base</code></td><td>const u8</td><td>Starting palette slot (0-15)</td></tr>
  <tr><td><code>name_frame_N</code></td><td>NgpcMetasprite</td><td>Per-frame metasprite struct</td></tr>
  <tr><td><code>name_anim[]</code></td><td>MsprAnimFrame[]</td><td>Animation table</td></tr>
</table>

<h2>ngpc_compress.py — Tile compression</h2>
<p>Compresses binary data (tiles, maps) using <b>RLE</b> or <b>LZ77/LZSS</b>.
The output matches the decompressor built into <code>src/ngpc_lz.c</code>.</p>
<pre>python tools/ngpc_compress.py level1_tiles.bin -o level1_tiles_lz.c -m lz77 --header
python tools/ngpc_compress.py level1_tiles.bin -o level1_tiles_rle.c -m rle --header
python tools/ngpc_compress.py level1_tiles.bin -o level1_tiles_best.c -m both --header</pre>
<table>
  <tr><th>Option</th><th>Description</th></tr>
  <tr><td><code>-m rle</code></td><td>RLE compression (~2:1, ultra-fast decompression)</td></tr>
  <tr><td><code>-m lz77</code></td><td>LZ77/LZSS compression (~3:1 to 4:1, best general ratio)</td></tr>
  <tr><td><code>-m both</code></td><td>Generates both, keeps the shorter one</td></tr>
  <tr><td><code>--header</code></td><td>Also generate a <code>.h</code> with <code>extern</code> declarations</td></tr>
  <tr><td><code>-n NAME</code></td><td>C array name prefix (default: derived from filename)</td></tr>
</table>
<p><b>Project integration:</b> in the Tilemap tab, the <b>Compress tiles</b> checkbox automatically
runs <code>ngpc_compress.py</code> after <code>ngpc_tilemap.py</code>. The <b>Auto (smaller)</b> mode
tries both algorithms and keeps the shorter result.
On the game side, replace <code>NGP_TILEMAP_LOAD_TILES_VRAM</code> with
<code>ngpc_lz_to_tiles()</code> or <code>ngpc_rle_to_tiles()</code> — same parameters except
for the compressed source data.</p>
"""


def _en_editor() -> str:
    return """
<h1>Editor (retouch)</h1>

<p>The <b>Editor</b> tab is a tiny tool to quickly fix a pixel/tile
<b>without leaving to Aseprite</b>. It is not meant to replace a full editor.</p>
<p><i>Tip:</i> hover buttons/settings to see short help tooltips.</p>

<h2>Open / save</h2>
<ul>
  <li><b>Open…</b> loads an image (PNG/BMP/GIF) — shortcut: <code>Ctrl+O</code>.</li>
  <li><b>Save</b> overwrites the file on disk — shortcut: <code>Ctrl+S</code>.</li>
  <li><b>Save as…</b> saves a copy — shortcut: <code>Ctrl+Shift+S</code>.</li>
  <li><b>Auto-reload</b> can reload the file if it changes on disk (Aseprite workflow).</li>
</ul>

<h2>RGB444 palette</h2>
<p>All opaque pixels are automatically <b>snapped</b> to the RGB444 grid (NGPC values).</p>

<h2>Zoom</h2>
<p>Buttons <code>×1 ×2 ×4 ×8 ×16 ×32</code> (shortcuts: <code>Ctrl+wheel</code> / <code>Ctrl++</code> / <code>Ctrl+-</code>).</p>

<h2>Load a palette from another sprite</h2>
<ul>
  <li><b>Load palette…</b>: extracts the RGB444 palette from another PNG.</li>
  <li><b>Scene → Palette</b>: loads a palette directly from an active-scene sprite (Project mode).</li>
  <li><b>Apply</b>: remaps opaque pixels to the <b>closest color</b> in that palette.</li>
  <li><b>Manual mapping…</b>: maps color-by-color (useful to share a palette exactly).</li>
</ul>

<h2>Tools</h2>
<ul>
  <li><b>Pencil</b>: draw with the current color (RGB444 snapped).</li>
  <li><b>Eraser</b>: make pixels transparent.</li>
  <li><b>Picker</b>: pick a pixel color.</li>
  <li><b>Fill</b>: flood fill an area.</li>
  <li><b>Select</b>: rectangular selection (restricts edits).</li>
</ul>
<p>Shortcuts: <code>P</code>=pencil, <code>E</code>=eraser, <code>I</code>=picker, <code>F</code>=fill, <code>Ctrl+S</code>=save.</p>
<p>Selection: <code>S</code>=tool, <code>Ctrl+C</code>=copy, <code>Ctrl+X</code>=cut, <code>Ctrl+V</code>=paste, <code>Ctrl+A</code>=all, <code>Del</code>=clear pixels, <code>Esc</code>=deselect.</p>
<p><b>Brush</b>: size 1/2/3. <b>Sym H/Sym V</b>: mirror drawing (shortcuts <code>H</code> / <code>V</code>).</p>
<p>Hover: the hovered pixel is highlighted and its info is shown (coords, tile, color).</p>
<p><b>Replace color…</b>: press <code>R</code>, click a source color, then choose the target color.</p>

<h2>Grid & constraints</h2>
<p><b>Tip:</b> right-click temporarily erases (and right-click with <b>Fill</b> = transparent fill).</p>
<ul>
  <li><b>8×8 grid</b>: shows NGPC tile boundaries.</li>
  <li><b>Tile overlay</b>: colors tiles by opaque color count (green ≤3 / orange 4 / red 5+).</li>
</ul>
<p>Shortcuts: <code>G</code>=grid, <code>O</code>=overlay.</p>

<h2>Operations</h2>
<ul>
  <li><b>Flip H</b>: horizontal mirror — shortcut: <code>Ctrl+[</code>.</li>
  <li><b>Flip V</b>: vertical mirror — shortcut: <code>Ctrl+]</code>.</li>
  <li><b>Rot -90</b>: rotate 90° CCW — shortcut: <code>Ctrl+Shift+[</code>.</li>
  <li><b>Rot +90</b>: rotate 90° CW — shortcut: <code>Ctrl+Shift+]</code>.</li>
</ul>

<h2>Undo / Redo</h2>
<p>Shortcuts <code>Ctrl+Z</code> and <code>Ctrl+Y</code> are supported.</p>
"""


def _fr_mono() -> str:
    return """
<h1>Mode Mono / K1GE</h1>

<h2>À quoi ça sert ?</h2>
<p>La case <b>Mono (K1GE)</b> dans l'onglet Palette applique une conversion
<b>niveaux de gris</b> au preview HW (et à la preview animation).
C'est une approximation du rendu sur <b>Neo Geo Pocket monochrome</b>
(processeur graphique K1GE).</p>

<p>Utile pour vérifier qu'un sprite reste <b>lisible en mode mono</b>
sans lancer Mednafen en mode NGP mono.</p>

<h2>Formule appliquée</h2>
<pre>L = 0.299 × R + 0.587 × G + 0.114 × B</pre>
<p>Le preview original (gauche) n'est pas affecté — il reste en couleur.</p>

<h2>Ce que ce mode n'est pas</h2>
<ul>
  <li>Ce n'est pas un export mono — vos PNG restent en couleur.</li>
  <li>Ce n'est pas une simulation exacte du K1GE (registres palette propres, dithering possible).</li>
  <li>C'est un outil visuel rapide pour détecter les problèmes de contraste.</li>
</ul>

<h2>Cas d'usage typique</h2>
<ul>
  <li>Jeu ciblant NGP couleur et mono : vérifiez la lisibilité dans les deux modes.</li>
  <li>Deux sprites avec des couleurs distinctes mais une luminance similaire →
      en mono ils se confondent → problème de lisibilité à détecter tôt.</li>
</ul>
"""


def _en_mono() -> str:
    return """
<h1>Mono / K1GE Mode</h1>

<h2>Purpose</h2>
<p>The <b>Mono (K1GE)</b> checkbox in the Palette tab applies a grayscale
conversion to the HW preview (and animation preview).
This is an approximation of rendering on the <b>Neo Geo Pocket monochrome</b>
(K1GE graphics chip).</p>

<p>Useful for checking that a sprite remains <b>readable in mono mode</b>
without launching Mednafen in NGP mono mode.</p>

<h2>Formula applied</h2>
<pre>L = 0.299 × R + 0.587 × G + 0.114 × B</pre>
<p>The original preview (left) is unaffected — it stays in color.</p>

<h2>What this mode is not</h2>
<ul>
  <li>Not a mono export — your PNG files remain in color.</li>
  <li>Not an exact K1GE simulation (custom palette registers, possible dithering).</li>
  <li>A quick visual tool to catch contrast issues early.</li>
</ul>

<h2>Typical use case</h2>
<ul>
  <li>Game targeting both NGP color and mono: check readability in both modes.</li>
  <li>Two sprites with distinct colors but similar luminance →
      they blend together in mono → readability issue to catch early.</li>
</ul>
"""


def _fr_hitbox() -> str:
    return """
<h1>Éditeur Hitbox</h1>

<h2>Vue d'ensemble — les 3 couches</h2>
<p>L'onglet <b>Hitbox</b> gère trois couches de données indépendantes pour chaque sprite :</p>
<table>
  <tr><th>Couche</th><th>Ce qu'elle définit</th><th>Par frame ?</th></tr>
  <tr><td><b>Hurtbox</b></td><td>Zone qui <b>reçoit</b> les dégâts. Sert aussi de boîte de collision gameplay principale (sol, murs, ennemis au contact).</td><td>Oui</td></tr>
  <tr><td><b>Hitbox offensive</b></td><td>Une ou plusieurs boîtes qui <b>infligent</b> des dégâts. Chacune a ses propres dégâts, knockback, priorité, fenêtre de timing et filtre d'état d'animation.</td><td>Non (par type)</td></tr>
  <tr><td><b>Propriétés</b></td><td>Données gameplay/physiques par-sprite : PV, vitesse, gravité, saut, flip, etc.</td><td>Non (par sprite)</td></tr>
</table>
<p>Les deux premières se règlent dans les sous-onglets <b>Hurtbox</b> et <b>Attaque</b>.
Attention : désactiver une hurtbox coupe aussi la collision gameplay principale du sprite (les deux sont liées dans le runtime V1).</p>

<h2>Ouvrir un sprite</h2>
<ul>
  <li>Depuis l'onglet <b>Projet</b> : sélectionnez un sprite et cliquez <b>Ouvrir dans Hitbox</b>.</li>
  <li>Directement depuis la barre d'outils de l'onglet Hitbox : cliquez <b>Ouvrir…</b> pour charger un PNG sans contexte de scène.</li>
</ul>

<h2>Navigation par frame (◀/▶ ou ←/→ clavier)</h2>
<p>Quand un sprite est ouvert depuis un projet, le canvas utilise automatiquement les
dimensions de frame définies dans la scène (<code>frame_w</code> / <code>frame_h</code>).
Chaque frame de la spritesheet est recadrée et affichée séparément.</p>
<p>Deux façons de changer de frame :</p>
<ul>
  <li>Boutons <b>◀ / ▶</b> situés sous le canvas (colonne gauche).</li>
  <li>Touches <b>← / →</b> du clavier — plus rapide quand le panneau est visible.</li>
</ul>
<p>Chaque frame a sa propre hurtbox indépendante.
<b>Copier vers toutes les frames</b> propage la hurtbox courante à toutes les frames du sprite.</p>

<h2>Raccourcis clavier</h2>
<table>
<tr><th>Touche</th><th>Action</th></tr>
<tr><td><b>← / →</b></td><td>Frame précédente / suivante</td></tr>
<tr><td><b>Alt+← / Alt+→</b></td><td>Attack box précédente / suivante</td></tr>
<tr><td><b>Insert</b></td><td>Ajouter une attack box</td></tr>
<tr><td><b>Delete</b></td><td>Supprimer l'attack box courante</td></tr>
<tr><td><b>Ctrl+S</b></td><td>Sauvegarder les hitboxes dans le projet</td></tr>
<tr><td><b>Ctrl++</b> / <b>Ctrl+-</b></td><td>Zoom in / zoom out</td></tr>
<tr><td><b>F5</b></td><td>Export → header C (.h)</td></tr>
</table>

<h2>Système de coordonnées</h2>
<p>L'origine <code>(0, 0)</code> est le <b>centre du sprite</b> (croix blanche).
<code>x</code> et <code>y</code> sont les décalages du <b>coin haut-gauche</b> depuis ce centre.
<code>w</code> et <code>h</code> sont en pixels.</p>
<table>
  <tr><th>Champ</th><th>Description</th><th>Plage</th></tr>
  <tr><td><b>x</b></td><td>Décalage horizontal (haut-gauche)</td><td>−128 … 127</td></tr>
  <tr><td><b>y</b></td><td>Décalage vertical (haut-gauche)</td><td>−128 … 127</td></tr>
  <tr><td><b>w</b></td><td>Largeur de la boîte</td><td>1 … 255</td></tr>
  <tr><td><b>h</b></td><td>Hauteur de la boîte</td><td>1 … 255</td></tr>
</table>

<h2>Édition sur le canvas</h2>
<ul>
  <li><b>Cliquer-glisser dans une zone vide</b> : dessine une nouvelle boîte.</li>
  <li><b>Glisser le centre</b> : déplace la boîte entière.</li>
  <li><b>Glisser une poignée (coin ou bord)</b> : redimensionne la boîte.</li>
  <li>Les spinboxes <b>x / y / w / h</b> reflètent la boîte et peuvent être modifiées directement.</li>
</ul>

<h2>Hurtbox — zone qui reçoit les dégâts</h2>
<p>La hurtbox est définie <b>par frame</b>. Le sous-onglet <b>Hurtbox</b> affiche la frame courante et permet de dessiner ou ajuster la boîte sur le canvas.</p>
<p>Stockée sous <code>sprites[].hurtboxes[]</code> dans le <code>.ngpcraft</code>.
L'export génère <code>g_{name}_hit[]</code> (tableau <code>NgpcSprHit</code>, un par frame).</p>

<h2>Hitbox offensive (attack boxes)</h2>
<p>Chaque sprite peut avoir <b>plusieurs boîtes offensives</b>, indépendantes des frames.
Elles sont gérées dans le sous-onglet <b>Attaque</b>.</p>

<h3>Champs par boîte</h3>
<table>
  <tr><th>Champ</th><th>Description</th><th>Défaut</th></tr>
  <tr><td><b>x / y / w / h</b></td><td>Position et taille (même système de coords que la hurtbox)</td><td>0/0/8/8</td></tr>
  <tr><td><b>Dmg</b></td><td>Points de dégâts infligés sur collision</td><td>1</td></tr>
  <tr><td><b>KB x / KB y</b></td><td>Knockback signé (−128…127) appliqué à la cible</td><td>0</td></tr>
  <tr><td><b>Prio</b></td><td>Priorité : si plusieurs boîtes se chevauchent, la plus haute priorité gagne</td><td>0</td></tr>
  <tr><td><b>Start</b></td><td>Frame de démarrage de la fenêtre active dans le cycle (0–3)</td><td>0</td></tr>
  <tr><td><b>Len</b></td><td>Durée de la fenêtre en frames (0 = toujours active)</td><td>0</td></tr>
  <tr><td><b>État anim</b></td><td>État d'animation requis pour que cette boîte soit active (voir ci-dessous)</td><td>Tous</td></tr>
</table>

<h3>Fenêtre active (Start / Len)</h3>
<p>Le runtime évalue les attack boxes sur un cycle de <b>4 frames</b> d'animation (<code>anim_frame mod 4</code>).
<code>Start</code> et <code>Len</code> définissent la plage active dans ce cycle.</p>
<ul>
  <li><code>Len=0</code> : boîte toujours active (ignore Start).</li>
  <li><code>Start=1, Len=2</code> : active aux frames 1 et 2 du cycle (inactive à 0 et 3).</li>
  <li>Utile pour limiter la hitbox au moment du coup (l'animation «&nbsp;levée du bras&nbsp;» ne blesse pas).</li>
</ul>

<h3>Filtre par état d'animation (COMBAT-5)</h3>
<p>Le champ <b>État anim</b> permet de n'activer une boîte <b>que si le sprite est dans un état d'animation précis</b>.
Cela évite d'avoir à dupliquer les sprites ou à gérer des flags manuels côté jeu.</p>
<table>
  <tr><th>Valeur</th><th>Comportement runtime</th></tr>
  <tr><td><b>Tous</b></td><td>Boîte active quel que soit l'état courant (comportement historique).</td></tr>
  <tr><td><b>idle / walk / run / jump / fall / land / attack / hurt / death / special / …</b></td><td>Boîte active uniquement si <code>cur_anim_state == valeur</code>. Sinon ignorée même si la fenêtre Start/Len correspond.</td></tr>
</table>
<p>La liste complète des états disponibles (index 0–13) :</p>
<pre>0=idle  1=walk  2=walk_left  3=walk_right  4=walk_up  5=walk_down
6=run   7=jump  8=fall       9=land       10=attack  11=hurt
12=death  13=special</pre>
<p>Côté runtime, la fonction <code>ngpng_attack_window_active(anim_frame, start, len, anim_state, cur_anim_state)</code>
effectue d'abord le filtre d'état (si <code>anim_state != 0xFF &amp;&amp; anim_state != cur_anim_state → return 0</code>),
puis vérifie la fenêtre Start/Len.</p>

<h3>Exemple complet — épéiste avec 2 boîtes</h3>
<p>Un personnage a deux boîtes offensives :</p>
<ul>
  <li><b>Box 0 — coup bas</b> : active en état <code>attack</code>, Start=0 Len=2, knockback droit (KB x=4).</li>
  <li><b>Box 1 — coup haut</b> : active en état <code>special</code>, Start=1 Len=1, dégâts doublés, knockback vers le haut (KB y=−6).</li>
</ul>
<p>Résultat exporté :</p>
<pre>/* attack_hitbox_anim_state[] — première boîte par type */
static const u8 g_hero_attack_hitbox_anim_state[1] = { 10u };  /* 10=attack */

/* attack_hitboxes_anim_state[] — toutes les boîtes à plat */
static const u8 g_hero_attack_hitboxes_anim_state[2] = { 10u, 13u };  /* attack, special */</pre>

<h2>Panneaux repliables</h2>
<p>Le panneau droit de l'onglet Hitbox est divisé en <b>5 sections repliables</b> (cliquez le titre pour réduire/agrandir) :</p>
<ul>
  <li><b>Coordonnées</b> : x / y / w / h de la boîte courante.</li>
  <li><b>Propriétés</b> : Physique, Combat, Divers.</li>
  <li><b>Contrôleur</b> : ctrl.role + bindings PAD.</li>
  <li><b>Motion Patterns</b> : séquences D-pad/boutons (fighting-game) + export <code>_motion.h</code>.</li>
  <li><b>Animation</b> : états d'animation + preview.</li>
</ul>
<p>Replier les sections inutilisées permet de voir les champs importants sans scroller.</p>

<h2>Sauvegarder dans le projet</h2>
<p>Cliquez <b>Sauvegarder dans le projet</b> pour écrire les boîtes <em>et</em>
les propriétés sprite dans le <code>.ngpcraft</code>.
Stocké sous <code>sprites[].hurtboxes</code> (par frame),
<code>sprites[].hitboxes_attack_multi</code> (multi-box offensif, avec <code>active_anim_state</code>),
et <code>sprites[].props</code> (par sprite).</p>
<p><b>Checklist</b> : un petit résumé en haut du panneau droit indique si le sprite source est chargé,
si le découpage est cohérent, si toutes les frames ont une hurtbox valide, si un rôle <code>ctrl</code> est défini,
si des états d'animation sont actifs, et si la sauvegarde dans le projet est possible.</p>

<h2>Export C (_hitbox.h / _props.h)</h2>
<p>L'export génère :</p>
<ul>
  <li><code>g_{name}_hit[]</code> — hurtboxes par frame (<code>NgpcSprHit</code>).</li>
  <li><code>g_{name}_attack_hitbox[]</code> — première boîte offensive par type (coord + timing).</li>
  <li><code>g_{name}_attack_hitbox_anim_state[]</code> — état d'animation requis, première boîte.</li>
  <li><code>g_{name}_attack_hitboxes[]</code> — toutes les boîtes offensives à plat.</li>
  <li><code>g_{name}_attack_hitboxes_anim_state[]</code> — états d'animation requis, toutes boîtes.</li>
  <li><code>g_{name}_props</code> — struct <code>NgpcSprProps</code> (physique/combat/divers).</li>
</ul>
<pre>/* Offsets sprite-local depuis le centre */
typedef struct &#123; s8 x; s8 y; u8 w; u8 h; &#125; NgpcSprHit;

static const NgpcSprHit g_player_hit[6] = &#123;
    &#123; -4, -8,  8, 16 &#125;,   /* frame 0 */
    ...
&#125;;</pre>

<h2>Propriétés sprite (Physique / Combat / Divers)</h2>
<p>Un seul jeu de valeurs par sprite (pas par frame) :</p>
<table>
  <tr><th>Propriété</th><th>Description</th><th>Défaut</th></tr>
  <tr><td><b>V.max</b></td><td>Vitesse max (unités jeu/tick)</td><td>4</td></tr>
  <tr><td><b>Poids</b></td><td>Masse physique (0=léger, 255=lourd)</td><td>128</td></tr>
  <tr><td><b>Frict.</b></td><td>Adhérence (0=glace, 255=grip total)</td><td>255</td></tr>
  <tr><td><b>Imp.saut</b></td><td>Impulsion initiale du saut. Plus la valeur est haute, plus le saut monte si la gravité reste identique.</td><td>0</td></tr>
  <tr><td><b>PV</b></td><td>Points de vie (0=invincible)</td><td>1</td></tr>
  <tr><td><b>Dmg</b></td><td>Dommages au contact (0=inoffensif)</td><td>0</td></tr>
  <tr><td><b>I.frm</b></td><td>Frames d'invincibilité après dégât</td><td>30</td></tr>
  <tr><td><b>Score</b></td><td>Valeur de score ×10 sur défaite (0–2550 pts)</td><td>0</td></tr>
  <tr><td><b>Anim</b></td><td>Ticks par frame d'animation (1–60 ; 0=statique)</td><td>4</td></tr>
  <tr><td><b>Type</b></td><td>Tag de type entité (défini par le jeu)</td><td>0</td></tr>
  <tr><td><b>Flip dir</b></td><td>Retourne automatiquement le sprite selon la dernière direction X</td><td>0</td></tr>
</table>

<h2>Contrôleur (ctrl.role)</h2>
<p>Dans l'onglet <b>Hitbox</b>, <code>ctrl.role</code> ne décrit pas le rôle gameplay du sprite.
Il décrit surtout <b>quel type de fichier <code>_ctrl.h</code> l'outil peut préparer</b>. Le <b>rôle gameplay</b> (player, enemy, item, block, platform...) se règle une seule fois dans <b>Level</b>.</p>
<table>
  <tr><th>Valeur</th><th>Ce que ça implique ici</th></tr>
  <tr><td><b>none</b></td><td>Aucun contrôleur exportable. La section ne sert pas au runtime.</td></tr>
  <tr><td><b>player</b></td><td>Affiche les bindings PAD et permet l'export d'un <code>_ctrl.h</code> prêt à l'emploi pour un personnage contrôlé au pad.</td></tr>
  <tr><td><b>enemy</b></td><td>Mode legacy de compatibilité seulement. Ne définit pas le rôle gameplay et ne crée pas d'IA, de déplacement ni d'attaque automatiquement.</td></tr>
  <tr><td><b>npc</b></td><td>Mode legacy de compatibilité seulement. Ne définit pas le rôle gameplay et ne crée pas de logique de déplacement automatiquement.</td></tr>
</table>
<p><b>Important :</b> si vous voulez qu'un perso bouge avec le contrôleur généré, il faut en pratique :</p>
<ol>
  <li>mettre <code>ctrl.role=player</code> ;</li>
  <li>régler aussi les champs de <b>Physique / Mouvement</b> (<code>move_type</code>, axes, vitesse, gravité, saut...) ;</li>
  <li>utiliser ensuite l'export <code>_ctrl.h</code> dans votre runtime ou votre template.</li>
</ol>
<p><b>Où changer les boutons ?</b> Directement dans <b>Hitbox &gt; Ctrl export</b> sur le sprite du joueur (Left / Right / Up / Down / Jump / Action / Accélérer / Freiner). L'onglet <b>Level</b> ne change pas ces boutons : il ne fait que choisir le rôle gameplay du type et placer les instances.</p>
<p><b>Accélérer / Freiner</b> : boutons génériques pour tout jeu nécessitant accélération et freinage (course vue de dessus, shoot'em up, etc.). Non liés automatiquement à la physique ngpc_actor — utiliser <code>HERO_ACCEL_HELD</code> / <code>HERO_BRAKE_HELD</code> dans votre code pour lire l'état, et <code>HERO_SPEED</code> / <code>HERO_ACCEL</code> / <code>HERO_BRAKE_FORCE</code> pour les valeurs issues des propriétés physiques. Laissez à <b>—</b> si non utilisé.</p>
<p><b>Frein</b> (prop physique) : intensité du freinage <i>actif</i> (bouton Freiner maintenu). Distinct de <b>Décél.</b> qui s'applique uniquement quand le bouton Accélérer est relâché (décélération passive). Exporté en <code>HERO_BRAKE_FORCE</code> dans <code>_ctrl.h</code>.</p>
<p><b>Sprint</b> : quand le bouton Sprint est assigné, <code>CTRL_UPDATE</code> modifie automatiquement <code>actor.speed</code> à <code>HERO_SPRINT_SPEED</code> ou <code>HERO_SPEED</code> selon l'état du bouton. Aucun code supplémentaire requis.</p>
<p><b>Tirer</b> : quand le bouton Tirer est assigné, la macro <code>HERO_SHOOT_UPDATE(actor, pool, tile, pal, timer)</code> est générée. Elle gère le cooldown et appelle <code>ngpc_bullet_spawn</code> dans la direction courante de <code>actor.dir_x/dir_y</code>. Paramètres configurables dans le groupe <b>Projectiles</b> des propriétés physiques.</p>

<h2>move_type (type de physique joueur)</h2>
<p>La propriété <b>move_type</b> détermine le contrôleur généré pour ce sprite :</p>
<table>
  <tr><th>Valeur</th><th>Comportement</th><th>Typique pour</th></tr>
  <tr><td><b>0</b></td><td>Top-down 4 directions, position directe</td><td>RPG, puzzle, twin-stick</td></tr>
  <tr><td><b>1</b></td><td>Top-down 8 directions</td><td>Action top-view</td></tr>
  <tr><td><b>2</b></td><td>Platformer : gravité + saut + accel/decel + collision tilemap</td><td>Platformer 2D</td></tr>
  <tr><td><b>3</b></td><td>Scroll forcé (shmup)</td><td>Shoot'em up</td></tr>
</table>
<p>Pour <code>move_type=2</code> (platformer) :</p>
<table>
  <tr><th>Prop</th><th>Rôle</th><th>Valeur typique</th></tr>
  <tr><td>max_speed</td><td>Vitesse horizontale max (px/frame)</td><td>2–4</td></tr>
  <tr><td>gravity</td><td>Accélération verticale (px/frame²)</td><td>2</td></tr>
  <tr><td>jump_force</td><td>Impulsion initiale du saut (10–14 pour saut moyen)</td><td>10–14</td></tr>
  <tr><td>can_jump</td><td>1 = peut sauter, 0 = non</td><td>1</td></tr>
  <tr><td>max_fall_speed</td><td>Vitesse de chute maximale</td><td>8</td></tr>
</table>
<p><b>Saut variable</b> : maintenir le bouton de saut réduit la gravité à la montée (×½) → saut long/haut.</p>
<p><b>Collision tilemap</b> : sol (2 pieds indépendants), plafond (SOLID uniquement), murs gauche/droite.
<code>TILE_SOLID=1</code> bloque des deux côtés. <code>TILE_ONE_WAY=2</code> supporte uniquement par le dessus.</p>

<h2>Divers : Behavior vs Type ID</h2>
<table>
  <tr><th>Champ</th><th>Rôle réel</th></tr>
  <tr><td><b>behavior</b></td><td>Tag exporté dans <code>_props.h</code>. Il <b>n'est pas recopié automatiquement</b> dans le champ <b>Comportement</b> des instances Level. Pour l'autorun actuel, l'IA des ennemis dépend surtout du <b>Comportement d'instance</b> défini dans <b>Level</b>.</td></tr>
  <tr><td><b>type_id</b></td><td>Tag libre défini par votre jeu, exporté dans <code>_props.h</code>. Il sert à votre code/runtime pour distinguer bullet, pickup, boss, etc.</td></tr>
  <tr><td><b>flip_x_dir</b></td><td>Quand il vaut 1, le runtime template-ready applique automatiquement un <code>SPR_HFLIP</code> selon la dernière vitesse horizontale non nulle.</td></tr>
</table>

<h2>Frames directionnelles</h2>
<p>La section <b>Frames directionnelles</b> permet d'associer des frames du spritesheet aux 8 (ou 4)
directions d'un sprite orientable — sans rotation matérielle (le NGPC n'en a pas).</p>
<p>Le principe : tu définis les frames <b>uniques</b> (N, NE, E, SE, S), et les directions miroirs
(NW, W, SW) sont dérivées automatiquement en appliquant <code>SPR_HFLIP</code> sur la frame opposée.</p>
<p><b>Numérotation des frames :</b> la première frame du spritesheet est toujours l'index <b>0</b>,
puis 1, 2, 3… de gauche à droite, ligne par ligne.</p>

<h3>Modes disponibles</h3>
<ul>
  <li><b>Désactivé</b> — aucune donnée directionnelle exportée (comportement classique).</li>
  <li><b>4 directions</b> — N, E, S (W = miroir de E). Adapté aux mouvements cardinaux (top-down basique, tanks…).</li>
  <li><b>8 directions</b> — N, NE, E, SE, S + miroirs automatiques. Adapté aux jeux de course, voitures, personnages 8-dir.</li>
</ul>

<h3>Convention des directions (indices 0–7)</h3>
<p>Identique à <code>ngpc_vehicle</code> :</p>
<pre>  0=E  1=NE  2=N  3=NW  4=W  5=SW  6=S  7=SE</pre>

<h3>Arrays C exportés</h3>
<pre>/* 8 valeurs par type — index : type * 8 + dir */
static const u8 g_scene_type_dir_frame[] = {
    /* voiture */ 2, 1, 0, 1, 2, 3, 4, 3,
};
static const u8 g_scene_type_dir_flip[] = {
    /* voiture */ 0, 0, 0, 1, 1, 1, 0, 0,
};
#define SCENE_HAS_DIR_FRAMES 1   /* présent si au moins un type configuré */</pre>

<h3>Utilisation runtime</h3>
<pre>u8 dir   = vehicle.dir &amp; 7;               /* 0–7 */
u8 frame = g_scene_type_dir_frame[type * 8 + dir];
u8 flip  = g_scene_type_dir_flip [type * 8 + dir] ? SPR_HFLIP : 0;
ngpc_soam_put(slot, x, y, tile_base + frame * tiles_per_frame, pal, flip);</pre>
<p>Fonctionne pour tout type d'entité orientable : voitures, personnages top-down,
ennemis à 8 directions, projectiles dirigés, etc.</p>

<h2>États d'animation</h2>
<p>La section <b>Animation States</b> associe des plages de frames du spritesheet à des états nommés
(<code>idle</code>, <code>walk</code>, <code>jump</code>, <code>hurt</code>…).
À l'export, génère automatiquement un header <code>*_anims.h</code> :</p>
<pre>#define HERO_ANIM_IDLE  0u
#define HERO_ANIM_WALK  1u
#define HERO_ANIM_JUMP  2u
static const NgpngAnim g_hero_anims[HERO_ANIM_COUNT] = {
    { 0, 1, 1, 8 },  /* idle: frame 0, count 1, loop, spd 8 */
    { 1, 4, 1, 6 },  /* walk */
    { 5, 2, 0, 4 },  /* jump (one-shot) */
};</pre>
<p>Les noms des états sont fixes (liste de 14 états du runtime). Activer un état dans l'éditeur l'inclut dans l'export. Le champ <b>État anim</b> des attack boxes fait référence à ces mêmes indices.</p>

<h2>Preview d'animation (▶)</h2>
<p>Chaque état activé dispose d'un bouton <b>▶</b> dans la colonne de droite du tableau.
Cliquez-le pour lire les frames de cet état directement dans le canvas hitbox.
Le compteur de frames suit l'animation en temps réel.</p>
<ul>
  <li>Cliquez <b>⏹</b> (même bouton) pour arrêter.</li>
  <li>Naviguer manuellement avec <b>◀ / ▶</b> (ou ←/→) arrête aussi le preview.</li>
  <li>Changer de sprite arrête automatiquement le preview en cours.</li>
</ul>
<p><b>Vitesse</b> : contrôlée par le champ <b>Vit</b> de l'état.
Valeur en ticks à 60 fps — <code>spd=6</code> ≈ 10 fps, <code>spd=1</code> = 60 fps.</p>
<p><b>Non-loop</b> : le preview s'arrête automatiquement sur la dernière frame.</p>

<h2>Miniatures animées dans le rail — A-2</h2>
<p>Les miniatures du rail gauche s'animent automatiquement si le sprite a un état <code>idle</code>, <code>walk</code> ou <code>run</code> défini avec <b>Count &gt; 1</b>.
La vitesse est celle du champ <b>Vit</b> de cet état. Les timers s'arrêtent dès que vous changez de scène ou rechargez le rail.</p>

<h2>Animations nommées (ngpc_anim) — A-1</h2>
<p>En plus des <i>états fixes</i> ci-dessus, vous pouvez définir des <b>animations nommées personnalisées</b>
compatibles avec le module optionnel <code>ngpc_anim</code>. Ces séquences sont sauvegardées dans le <code>.ngpcraft</code>
et exportées via le bouton <b>Export _namedanims.h</b>.</p>
<table border="1" cellpadding="3" cellspacing="0">
<tr><th>Colonne</th><th>Description</th></tr>
<tr><td><b>Nom</b></td><td>Suffixe identifiant C (ex. <code>walk_cycle</code>) → variable <code>anim_SPRITE_walk_cycle</code></td></tr>
<tr><td><b>Frames</b></td><td>Indices de frames séparés par virgule (ex. <code>0, 1, 2, 3</code>) — base 0</td></tr>
<tr><td><b>Speed</b></td><td>Ticks NGPC par frame d'anim : 1=60 fps, 4=15 fps, 6=10 fps, 8=7,5 fps</td></tr>
<tr><td><b>Mode</b></td><td><code>loop</code> | <code>pingpong</code> | <code>oneshot</code></td></tr>
</table>
<p>Exemple de header généré :</p>
<pre>static const u8 hero_walk_cycle_frames[] = { 0u, 1u, 2u, 3u };
static const NgpcAnimDef anim_hero_walk_cycle = ANIM_DEF(hero_walk_cycle_frames, 4u, 4u, ANIM_LOOP);</pre>
<p>Utilisation dans votre code :</p>
<pre>#include "ngpc_anim.h"
#include "hero_namedanims.h"

NgpcAnim anim;
ngpc_anim_play(&amp;anim, &amp;anim_hero_walk_cycle);  /* dans init */

/* Chaque frame : */
ngpc_anim_update(&amp;anim);
ngpc_sprite_set(slot, x, y, TILE_BASE + ngpc_anim_tile(&amp;anim), pal, flags);</pre>

<h2>Motion Patterns (ngpc_motion)</h2>
<p>Le panneau <b>Motion Patterns</b> associe des séquences de D-pad + boutons (style fighting-game) à des états
d'animation. Requiert le module optionnel <code>optional/ngpc_motion/</code>.</p>

<h3>Colonnes du tableau</h3>
<table>
  <tr><th>Colonne</th><th>Description</th></tr>
  <tr><td><b>Nom</b></td><td>Identifiant C du pattern (ex. <code>QCF_A</code>) → <code>#define HERO_PAT_QCF_A 0u</code></td></tr>
  <tr><td><b>Steps</b></td><td>Séquence de directions/boutons séparés par des espaces (voir notation ci-dessous)</td></tr>
  <tr><td><b>Win</b></td><td>Fenêtre maximale en frames pour que tout le pattern soit valide (4–120 ; défaut 20)</td></tr>
  <tr><td><b>→ Anim</b></td><td>État d'animation à déclencher automatiquement (<code>special</code>, <code>attack</code>…) — laisser vide pour gérer dans le code</td></tr>
</table>

<h3>Notation des steps</h3>
<table>
  <tr><th>Token</th><th>Signification</th></tr>
  <tr><td><code>N</code></td><td>Neutre (aucune direction)</td></tr>
  <tr><td><code>U D L R</code></td><td>Haut / Bas / Gauche / Droite</td></tr>
  <tr><td><code>UR UL DR DL</code></td><td>Diagonales</td></tr>
  <tr><td><code>*</code></td><td>Wildcard — toute direction acceptée</td></tr>
  <tr><td><code>+A +B +OPT</code></td><td>Bouton requis sur ce step (combinable : <code>DR+A</code>, <code>R+A+B</code>)</td></tr>
</table>
<p>Exemples :</p>
<pre>D DR R+A     → Quarter-circle → + A  (Hadouken)
R D DR+A     → Dragon Punch + A  (Shoryuken)
R N R        → Double-tap → (dash avant)
* *+B        → N'importe quelle direction, puis n'importe laquelle + B</pre>

<h3>Bouton Preset</h3>
<p>Le bouton <b>Preset ▾</b> insère des patterns prêts à l'emploi : QCF, QCB, Dragon Punch, Double-tap ←/→.</p>

<h3>Header généré (<code>_motion.h</code>)</h3>
<p>Cliquez <b>Export _motion.h</b> pour générer :</p>
<pre>#include "ngpc_motion/ngpc_motion.h"
#include "hero_anims.h"           /* si au moins un pattern a un → Anim */

static const u8 NGP_FAR _hero_qcf_a_s[] = { MDIR_D, MDIR_DR, MDIR_R|MBTN_A };
#define HERO_PAT_QCF_A   0u
#define HERO_PAT_COUNT   1u

static const NgpcMotionPattern NGP_FAR g_hero_patterns[HERO_PAT_COUNT] = {
    { _hero_qcf_a_s, 3u, 20u }   /* QCF_A */
};

static const u8 NGP_FAR g_hero_pat_anim[HERO_PAT_COUNT] = {
    HERO_ANIM_SPECIAL   /* QCF_A → special */
};</pre>
<p>Utilisation dans votre code :</p>
<pre>static NgpcMotionBuf hero_motion;
ngpc_motion_init(&amp;hero_motion);   // game_init()

// game_update() :
ngpc_motion_push(&amp;hero_motion, ngpc_pad_held, ngpc_pad_pressed);
u8 pat = ngpc_motion_scan(&amp;hero_motion, g_hero_patterns, HERO_PAT_COUNT);
if (pat != 0xFF) {
    ngpc_motion_clear(&amp;hero_motion);
    u8 anim = g_hero_pat_anim[pat];
    if (anim != 0xFF) ngpc_anim_play(&amp;hero_anim, &amp;g_hero_anims[anim]);
}</pre>
<p><b>RAM :</b> 34 octets par entité (<code>NgpcMotionBuf</code>). Les step arrays et la pattern table sont en ROM (NGP_FAR).</p>

<h2>Affichage contextuel — pourquoi certains champs disparaissent</h2>
<p>L'onglet Hitbox affiche <b>seulement les paramètres pertinents</b> pour le type d'entité courant.
Si vous ouvrez un sprite ennemi, les champs de saut et de contrôleur PAD sont masqués automatiquement.
Aucune donnée n'est effacée — les champs cachés sont juste repliés.</p>

<h3>Profils physiques détectés automatiquement</h3>
<table>
  <tr><th>Profil</th><th>Condition de déclenchement</th><th>Champs affichés</th></tr>
  <tr><td><b>Platformer / Saut</b></td><td><code>move_type=2</code> ou scène de type platformer</td><td>Saut, gravité, chute max, accel/décel, friction</td></tr>
  <tr><td><b>Top-down 4/8 dir</b></td><td>Présence de props top-down, scène RPG/tactical, ou frames directionnelles</td><td>Vitesse, axes X/Y, flip dir</td></tr>
  <tr><td><b>Véhicule top-down</b></td><td><code>td_move=2</code> ou scène de type race</td><td>Tout le bloc top-down (td_speed_max, td_accel, td_brake…)</td></tr>
  <tr><td><b>Défilement forcé</b></td><td><code>move_type=3</code> ou scène shmup</td><td>Axes X/Y uniquement</td></tr>
  <tr><td><b>Aucune physique</b></td><td>Pas de propriété physique configurée, entité statique</td><td>Bandeau informatif (les paramètres physiques restent accessibles)</td></tr>
</table>

<h3>Profils de rôle détectés automatiquement</h3>
<table>
  <tr><th>Rôle</th><th>Condition</th><th>Sections activées</th></tr>
  <tr><td><b>Joueur</b></td><td><code>ctrl.role=player</code> ou <code>gameplay_role=player</code></td><td>Contrôleur PAD + Physique complète + Combat</td></tr>
  <tr><td><b>Ennemi</b></td><td><code>gameplay_role=enemy</code></td><td>Combat, Hurtbox, PV, dégâts</td></tr>
  <tr><td><b>PNJ</b></td><td><code>gameplay_role=npc</code></td><td>Combat si HP/dégâts configurés</td></tr>
  <tr><td><b>Prop / Décor</b></td><td>Aucun rôle explicite</td><td>Hitbox seule, pas de Combat (sauf données présentes)</td></tr>
</table>

<h2>Config. rapide et override de contexte</h2>
<p>En haut du panneau droit, une ligne compacte permet de <b>forcer le contexte</b> quand la détection automatique est insuffisante :</p>
<ul>
  <li><b>Config. rapide…</b> : ouvre un dialog avec des presets prêts à l'emploi (Joueur Platformer, Joueur Shmup, Joueur Top-down, Joueur Véhicule, Ennemi, PNJ, Prop/Décor). Sélectionner un preset adapte immédiatement les sections visibles. <b>Aucune valeur numérique n'est modifiée.</b></li>
  <li><b>Combo Rôle</b> : force le profil de rôle (Joueur, Ennemi, PNJ, Prop). Défaut = Auto.</li>
  <li><b>Combo Physique</b> : force le profil physique (Platformer/Saut, Top-down, Véhicule, Défilement, Aucune). Défaut = Auto.</li>
</ul>
<p>Quand un axe est sur Auto, la déduction automatique s'applique. Toute valeur non-Auto prime sur l'auto-détection. Le contexte forcé est sauvegardé dans <code>sprite_meta["display_hint"]</code> avec le sprite — il est rechargé automatiquement à la prochaine ouverture.</p>
<p><b>Quand utiliser l'override ?</b> Surtout sur les sprites nouvellement créés (pas encore de <code>ctrl.role</code> ni de props configurées) ou quand un sprite polyvalent doit montrer des champs spécifiques.</p>

<h2>Champs avancés et badges pipeline</h2>
<p>Le bouton <b>Afficher les champs avancés</b> (en bas du panneau) développe le groupe <b>Avancé</b> et révèle des champs peu fréquents :</p>
<table>
  <tr><th>Champ</th><th>Pourquoi dans Avancé</th></tr>
  <tr><td><b>Poids</b></td><td>Rarement ajusté — le comportement par défaut convient dans la plupart des cas</td></tr>
  <tr><td><b>Direction gravité</b></td><td>Pertinent uniquement pour les jeux avec gravité inversée</td></tr>
  <tr><td><b>Tag IA</b> (behavior)</td><td>Métadonnée sprite uniquement — le vrai comportement IA se configure dans Level</td></tr>
  <tr><td><b>Type ID</b></td><td>Tag libre pour votre runtime, rarement nécessaire côté Hitbox</td></tr>
</table>
<p>En mode avancé, des <b>badges colorés</b> apparaissent à droite de chaque champ pour indiquer dans quel pipeline la valeur est utilisée.
Survolez un badge pour obtenir une explication complète :</p>
<table>
  <tr><th>Badge</th><th>Couleur</th><th>Signification</th></tr>
  <tr><td><b>CTRL</b></td><td>Vert foncé</td><td>Va dans <code>_ctrl.h</code> — contrôleur joueur. Partagé par toutes les instances.</td></tr>
  <tr><td><b>PROPS</b></td><td>Brun-orange</td><td>Compilé en ROM dans <code>_props.h</code> — données statiques par type de sprite.</td></tr>
  <tr><td><b>SCENE</b></td><td>Bleu</td><td>Stocké dans la scène — peut différer par instance dans Level.</td></tr>
  <tr><td><b>TAG</b></td><td>Gris</td><td>Métadonnée seulement — n'affecte pas directement la physique runtime.</td></tr>
</table>
<p>Les badges n'affectent pas la sauvegarde ni l'export — ils sont purement informatifs.</p>

<h2>Tips</h2>
<ul>
  <li><b>Hitbox centrée standard</b> : sprite 16×16 → <code>x=−8, y=−8, w=16, h=16</code>. Shmup réduit : <code>x=−3, y=−3, w=6, h=6</code>.</li>
  <li><b>Attack box toujours active</b> : laisser <code>Len=0</code> et <b>État anim = Tous</b>.</li>
  <li><b>Coup qui ne blesse qu'à un seul moment</b> : <code>Start=1, Len=1</code> sur une animation 4 frames.</li>
  <li><b>Deux coups différents sur un même sprite</b> : créer deux boîtes avec des <b>État anim</b> différents (ex. <code>attack</code> et <code>special</code>). Le runtime filtre automatiquement.</li>
  <li><b>Pattern sans → Anim</b> : laisser la colonne vide — le dispatch table n'est pas généré, gérer dans un <code>switch(pat)</code>.</li>
  <li><b>Panneau droit trop chargé ?</b> Repliez les sections Contrôleur, Motion Patterns et Animation si vous ne faites que des hurtboxes.</li>
  <li><b>Sprite nouveau sans contexte ?</b> Cliquez <b>Config. rapide…</b> et choisissez le type — l'affichage s'adapte immédiatement.</li>
  <li><b>Champ attendu absent ?</b> Ouvrez le groupe <b>Avancé</b> ou forcez la Physique/Rôle avec les combos en haut du panneau.</li>
</ul>
"""


def _fr_level_editor() -> str:
    return """
<h1>Éditeur de niveau (Level)</h1>

<h2>But</h2>
<p>L'onglet <b>Level</b> sert à placer des entités sur une grille (en tiles 8×8),
à organiser des <b>vagues</b>, et à générer une <b>carte de collision</b> via le Procgen.</p>
<p><b>Tailles (NGPC)</b> : l’écran visible est 20×19 tiles (160×152 px) et une tilemap BG hardware est limitée à 32×32 tiles (256×256 px).
Le tool affiche ce rappel près du champ <b>Taille</b>.</p>
<p><b>Profil de jeu</b> : le sélecteur <b>Profil</b> applique des presets rapides (mode carte, scroll/loop, tailles par défaut) selon le genre :
<b>Platformer</b>, <b>Shmup vertical</b>, <b>Top-down open world</b>, <b>Metroidvania</b>, <b>Dungeon floor</b>, <b>RPG tactical</b>,
<b>Arcade score</b>, <b>Fighting</b>, <b>Beat 'em up</b>, <b>Run'n gun</b> et <b>Roguelite (room-by-room)</b>.
Vous pouvez ensuite tout modifier manuellement.</p>
<p><b>Splitters</b> : dans les onglets <b>Vagues</b> et <b>Procgen</b>, vous pouvez redimensionner la zone du haut et du bas (et la taille est mémorisée).</p>
<p><b>Diagnostics</b> : un panneau liste les warnings utiles de la scène (player manquant, col_map absente/taille invalide, mapping visuel procgen incomplet, caméra hors map, régions/paths invalides, triggers cassés…). Il ajoute aussi des <b>hints guidés par profil</b> : par exemple <i>Shmup</i> sans forced scroll, <i>Fighting</i> sans Lock Y, ou <i>Beat ’em up</i> sans Ground band.</p>
<p><b>Checklist</b> : juste au-dessus, une mini checklist indique rapidement ce qui est prêt ou non pour <b>tester</b> / <b>exporter</b> : diagnostics bloquants, caméra/bounds, références de scène (régions, paths, triggers), player principal, symbole d’export, mapping Procgen PNG, puis hints de profil.</p>
<p><b>Outils de scène</b> : la barre au-dessus du canvas rend maintenant les modes explicites : <b>Select</b>, <b>Entity</b>, <b>Wave</b>, <b>Region</b>, <b>Path</b> et <b>Camera</b>. L’édition ressemble donc davantage à un vrai éditeur d’objets qu’à une simple grille avec des modes cachés dans les panneaux.</p>
<p><b>Overlays</b> : une ligne dédiée permet aussi d’afficher/masquer clairement <b>Collision</b>, <b>Regions</b>, <b>Triggers</b>, <b>Paths</b>, <b>Waves</b>, <b>Camera</b> et le <b>bezel NGPC</b>, pour éviter l’effet “tout est mélangé sur le canvas”.</p>
<p><b>Interface</b> : le haut du canvas est maintenant séparé en blocs <b>Vue</b> et <b>Édition de scène</b>, pour isoler les contrôles de zoom/undo des outils et overlays.</p>

<h2>Raccourcis clavier — Canvas</h2>
<table>
<tr><th>Touche</th><th>Action</th></tr>
<tr><td><b>S</b></td><td>Outil Select</td></tr>
<tr><td><b>E</b></td><td>Outil Entity (placement)</td></tr>
<tr><td><b>W</b></td><td>Outil Wave</td></tr>
<tr><td><b>R</b></td><td>Outil Region</td></tr>
<tr><td><b>P</b></td><td>Outil Path</td></tr>
<tr><td><b>C</b></td><td>Outil Camera</td></tr>
<tr><td><b>G</b></td><td>Outil Collision (tile painting)</td></tr>
<tr><td><b>Esc</b></td><td>Revenir à Select</td></tr>
<tr><td><b>+</b> / <b>=</b></td><td>Zoom in (niveau suivant)</td></tr>
<tr><td><b>-</b></td><td>Zoom out (niveau précédent)</td></tr>
<tr><td><b>F</b></td><td>Fit to BG (ajuster zoom au fond)</td></tr>
<tr><td><b>F5</b></td><td>Export scène → .h</td></tr>
<tr><td><b>Delete</b></td><td>Supprimer la sélection active</td></tr>
<tr><td><b>Flèches</b></td><td>Nudge sélection de 1 tile</td></tr>
<tr><td><b>Shift + Flèches</b></td><td>Nudge sélection de 4 tiles</td></tr>
<tr><td><b>Ctrl+Z</b></td><td>Undo</td></tr>
<tr><td><b>Ctrl+Y</b></td><td>Redo</td></tr>
<tr><td><b>Ctrl+D</b></td><td>Dupliquer la sélection active</td></tr>
<tr><td><b>Ctrl+E</b></td><td>Export scène → .h</td></tr>
<tr><td><b>Ctrl+0</b></td><td>Fit to BG (zoom depuis clavier)</td></tr>
</table>

<h2>Raccourcis clavier — Panneaux latéraux</h2>
<p>Ces raccourcis sont actifs uniquement quand la liste correspondante a le focus (clic dessus ou Tab).</p>
<table>
<tr><th>Liste</th><th>Touche</th><th>Action</th></tr>
<tr><td><b>Waves</b></td><td>Insert</td><td>Ajouter une wave</td></tr>
<tr><td><b>Waves</b></td><td>Delete</td><td>Supprimer la wave sélectionnée</td></tr>
<tr><td><b>Waves</b></td><td>Ctrl+D</td><td>Dupliquer la wave sélectionnée</td></tr>
<tr><td><b>Régions</b></td><td>Insert</td><td>Ajouter une région</td></tr>
<tr><td><b>Régions</b></td><td>Delete</td><td>Supprimer la région sélectionnée</td></tr>
<tr><td><b>Triggers</b></td><td>Insert</td><td>Ajouter un trigger</td></tr>
<tr><td><b>Triggers</b></td><td>Delete</td><td>Supprimer le trigger sélectionné</td></tr>
<tr><td><b>Triggers</b></td><td>Ctrl+D</td><td>Dupliquer le trigger sélectionné</td></tr>
</table>

<h2>Souris</h2>
<ul>
  <li><b>Clic gauche</b> : dépend de l’outil actif (sélection, placement, région, chemin, caméra…).</li>
  <li><b>Glisser</b> : déplacer une entité (statique ou en vague).</li>
  <li><b>Clic droit</b> : supprimer l’élément sous le curseur.</li>
  <li><b>Ctrl+clic+glisser</b> : déplacer la caméra (Cam X/Y) — rectangle bleu “CAM”.</li>
  <li><b>Ctrl+molette</b> : zoomer/dézoomer.</li>
</ul>

<h2>Fond (BG SCR1/SCR2) — comment charger une tilemap</h2>
<p>Les listes déroulantes <b>BG SCR1</b> et <b>BG SCR2</b> sont peuplées depuis la liste des tilemaps de la scène.
Pour qu’une tilemap y apparaisse :</p>
<ol>
  <li>Allez dans l’onglet <b>Projet</b> → sélectionnez la scène → section <b>Tilemaps</b>.</li>
  <li>Ajoutez votre PNG via le bouton <b>+</b>. Chaque PNG ajouté apparaît ensuite dans les deux listes de Level.</li>
  <li>Revenez dans <b>Level</b> : sélectionnez le bon PNG dans <b>BG SCR1</b> et/ou <b>BG SCR2</b>.</li>
</ol>
<p><b>Tilemap simple (un seul PNG)</b> : sélectionnez-la sur SCR1. Si elle possède des variantes
<code>_scr1.png</code> / <code>_scr2.png</code> à côté, l’aperçu charge automatiquement la bonne.</p>
<p><b>Deux layers (SCR1 + SCR2)</b> : ajoutez deux PNG distincts dans Projet, puis sélectionnez-les
séparément dans BG SCR1 et BG SCR2. Le sélecteur <b>Devant</b> choisit quel plan passe au premier plan
(preview éditeur — à configurer aussi dans votre code runtime).</p>
<p><b>Grande tilemap (&gt;32×32 tiles)</b> : même workflow — ajoutez-la dans Projet, sélectionnez-la sur SCR1.
Un overlay cyan (📺) apparaît avec les spinners <b>Cam X/Y</b> pour prévisualiser différentes zones de la map.
À l’export, le streaming VRAM (<code>scene_X_stream_planes()</code>) est généré automatiquement.</p>
<p><b>Procgen</b> peut aussi (optionnellement) <b>générer des tilemaps PNG SCR1/SCR2</b> à partir de la carte de collision :
le tool crée de nouveaux fichiers, les ajoute à <code>tilemaps[]</code>, et les sélectionne comme BG.</p>

<h2>Layout (caméra / scroll)</h2>
<p>L'onglet <b>Layout</b> stocke des métadonnées utiles pour votre runtime : position de départ caméra (en tiles),
axes de scroll, scroll forcé (vitesse), et options de boucle (loop). L'export les écrit en <code>#define</code> dans <code>_scene.h</code>.</p>
<p>Vous pouvez aussi définir un <b>Mode caméra</b> (écran fixe, follow, scroll forcé, segments/arènes, loop) et des <b>bounds</b> (clamp) pour documenter la structure du level.</p>
<p><b>Presets de layout</b> : ils vont maintenant plus loin que le simple helper de mode caméra, avec des starters orientés genre (<b>menu écran fixe</b>, <b>platformer follow</b>, <b>platformer room lock</b>, <b>run'n gun horizontal</b>, <b>shmup vertical</b>, <b>salle top-down</b>) qui remplissent ensemble caméra, scroll, loop et confort du suivi.</p>
<p><b>Collision peinte (col_map)</b> : le mode de scène <b>Collision</b> ne se limite plus au pinceau simple. Vous pouvez maintenant choisir
<b>Brush</b>, <b>Rect</b> ou <b>Fill</b> directement dans la ligne dédiée au-dessus du canvas. Le <b>clic droit</b> continue d'écrire <code>PASS</code>,
et <b>Ctrl+clic</b> agit comme une pipette pour reprendre le type de collision sous le curseur. Cela sert à poser vite un sol, remplir une zone vide,
ou corriger localement un export de collision sans repasser par le tileset global.</p>
<p><b>Import BG → col_map</b> : dans cette même ligne, le bouton <b>Import BG</b> peut reconstruire la collision de <b>Level</b> à partir d'une tilemap de la scène
(`BG auto`, <code>SCR1</code> ou <code>SCR2</code>). C'est volontairement un import <b>explicite</b>, pas une synchro permanente : vous partez de la collision définie dans
<b>Tilemap</b>, puis vous retouchez localement la <code>col_map</code> si besoin. L'import remplace la <code>col_map</code> courante, mais reste protégé par l'undo.</p>
<p><b>Export build-ready</b> : même sans import manuel, l'export template-ready sait maintenant aussi reconstruire automatiquement la collision de scène depuis la tilemap BG liée si cette tilemap contient déjà sa collision sauvée. L'import manuel reste surtout utile pour partir de cette base puis faire des overrides locaux visibles dans <b>Level</b>.</p>
<p><b>Résumé de source</b> : juste sous cette ligne, <b>Level</b> affiche maintenant si la collision visible vient d'une
<b>col_map locale</b> ou d'une <b>base importée depuis une tilemap</b>. Quand la source importée reste disponible, le tool affiche aussi combien de
<b>cases locales</b> diffèrent de cette base. Cela rend le workflow plus clair : <i>collision Tilemap -> import explicite -> overrides locaux</i>.</p>
<p><b>Planes / parallax</b> : vous pouvez aussi définir un parallax (X/Y en %) pour SCR1 et SCR2, ainsi que quel plane est au premier plan (BG_FRONT).
Ce sont des <b>métadonnées exportées</b> : le runtime décide comment les interpréter.</p>
<p><b>Débordement s16 sur grande map (PERF-PAR-1) :</b> un calcul naïf <code>cam_py * pct</code> déborde s16 dès que <code>cam_py &gt; 327 px</code> (≈ 41 tiles).
L'autorun template utilise <code>ngpng_scale_pct(v, pct)</code> qui divise d'abord (q = v/100, r = v%100 → q×pct + r×pct/100) pour rester dans les bornes.
Si vous écrivez du code parallaxe custom, utilisez le même patron — ou limitez la hauteur de map à ≤ 41 tiles si la parallaxe Y est active.
Le Diagnostics de l'onglet Level affiche un hint si cette combinaison est détectée.</p>

<h2>Cycling palette — X-1 (ngpc_palfx)</h2>
<p><b>À quoi ça sert ?</b> Le cycling palette fait <em>tourner en boucle</em> les 3 couleurs d'une palette pour créer
des effets visuels animés sans toucher au code ni aux tiles : eau qui ondule, lave qui pulse, lumières clignotantes,
arc-en-ciel, etc. Les tiles elles-mêmes ne changent pas — seules leurs couleurs sont décalées à chaque frame.</p>
<p><b>Comment ça marche ?</b> La palette NGPC a 4 couleurs (0 à 3). La couleur 0 est réservée (transparence pour
les sprites, couleur de fond pour les plans). Le cycling fait tourner uniquement les <b>couleurs 1, 2 et 3</b>
dans l'ordre : 1→2→3→1→2→3… toutes les <em>N</em> frames. Plus la vitesse est basse (1 = le plus rapide), plus
l'animation est rapide.</p>
<p><b>Exemple concret :</b> vous avez un tilemap de lave qui utilise SCR1 / Palette 3 avec trois teintes
orange-rouge. Ajoutez une entrée Plan=SCR1, Pal=3, Vitesse=4 → la lave pulse toute seule à 15 cycles/sec.</p>
<p>La section <b>Cycling palette</b> se trouve dans <b>Level → Layout</b>. Chaque ligne = un cycle actif pour
cette scène. Colonnes : <b>Plan</b> (SCR1 / SCR2 / SPR), <b>Pal</b> (0–15), <b>Vitesse</b> (frames entre
chaque décalage de couleur — 1=très rapide, 8=lent).</p>
<p>À l'export, le générateur émet automatiquement <code>ngpng_palfx_enter(scene_idx)</code>, appelée à chaque
entrée de scène (démarrage, game-over, warp, checkpoint). <code>ngpc_palfx_update()</code> est ajouté dans la
boucle principale.</p>
<p><b>Prérequis :</b> le module <code>src/fx/ngpc_palfx.h</code> doit être présent dans le template.</p>
<pre>/* Exemple généré — lave sur SCR1/Pal2, eau sur SPR/Pal1 */
static void ngpng_palfx_enter(u8 scene_idx)
{
    ngpc_palfx_stop_all();
    if (scene_idx == 0u) {
        ngpc_palfx_cycle(GFX_SCR1, 2u, 4u);  /* lave : rapide */
        ngpc_palfx_cycle(GFX_SPR,  1u, 8u);  /* eau  : lent   */
    }
}</pre>

<h2>OAM viewer — X-3</h2>
<p>L'onglet <b>OAM</b> dans le panel droit du Level editor affiche la composition hardware NGPC en pire cas :
toutes les entités statiques <em>et</em> toutes les vagues actives simultanément.</p>
<p>Chaque tile 8×8 = 1 slot OAM hardware. Un sprite 16×16 = 4 slots, 32×16 = 8 slots, etc.
Le hardware NGPC dispose de <b>64 slots maximum</b>.</p>
<ul>
  <li><b>Grille 16×4</b> : visualisation colorée par rôle — vert (player), rouge (enemy), jaune (item), bleu (npc), violet (prop).</li>
  <li><b>Badge total</b> : <code>X / 64</code> en vert/orange/rouge selon l'utilisation.</li>
  <li><b>Table</b> : slot(s) alloués, type, dimensions, nombre de parts HW.</li>
</ul>
<p><b>Attention :</b> le viewer ne prend pas en compte les effets de flash ou de HUD inline — il compte uniquement les entités du projet.
Si votre jeu a des FX sprites (explosions, bullets) ou HUD sprites, ajoutez leur coût manuellement.</p>

<h2>Rôles</h2>
<p>Chaque type d'entité (liste à gauche) peut recevoir un rôle : <code>player</code>, <code>enemy</code>,
<code>item</code>, <code>npc</code>, <code>trigger</code>, <code>block</code>, <code>platform</code>, <code>prop</code>.
Le Procgen s'en sert pour placer automatiquement les entités.</p>
<p><b>Autorun actuel :</b> les entités statiques avec rôle <code>item</code> sont ramassées au contact du joueur.
Le score vient de <code>score</code>, le soin éventuel de <code>hp</code>, et <code>data</code> peut servir de multiplicateur simple.</p>
<p><b>Blocks V1 :</b> une entité statique avec rôle <code>block</code> réagit quand le joueur la tape par dessous.
Utilisez <code>data=0</code> pour un bump simple, <code>data=1</code> pour un bloc cassable, et <code>data=2</code> pour un item block one-shot.</p>
<p><b>UI Level :</b> le panneau de droite essaye maintenant aussi d'expliciter ces cas au lieu de vous laisser mémoriser les valeurs brutes.
Pour un <code>block</code>, un preset d'instance règle directement <code>data</code>. Pour un <code>item</code>, le preset couvre aussi des multiplicateurs courants
(x1/x2/x5/x10). Pour une <code>platform</code>, le preset aide à basculer rapidement entre support statique et plateforme mobile en s'appuyant sur le <code>Path</code>.
Pour un <code>enemy</code>, il propose aussi des presets simples (patrouille gauche/droite, poursuite, sentinelle, aléatoire) qui règlent les champs déjà exportés
au lieu de vous laisser manipuler seulement des indices bruts. Le résumé runtime rappelle ensuite ce que l'autorun lit réellement (props sprite, behavior d'instance, Path, etc.).</p>
<p><b>Presets de pose :</b> dans la colonne de gauche, juste sous le <b>Rôle gameplay</b>, un bloc <b>Starter</b> prépare la prochaine pose du type courant sans remplacer votre workflow normal.
Laissez <code>(aucun)</code> pour garder un placement brut. Si vous choisissez un preset, il s'applique quand vous cliquez dans la scène, et le bouton <b>Poser</b> le dépose directement au centre de la vue.
<b>Important :</b> cela n'affecte ni le spawn runtime, ni la caméra de départ, ni la scène de départ. Exemples : spawn joueur au sol, ennemi patrouille gauche/droite, bloc cassable, collectible x10, ou plateforme mobile. Dans ce dernier cas, si aucun <code>Path</code> n'existe encore, le tool crée un path minimal de démonstration et l'assigne à la plateforme.</p>
<p><b>Behavior + Paramètres IA :</b> pour les ennemis, le champ d’instance <code>behavior</code> pilote le mode de déplacement :
<code>patrol</code> marche et fait demi-tour au mur/au bord, <code>chase</code> suit le joueur horizontalement, <code>fixed</code> reste en place, et <code>random</code> erre.
Sélectionner un ennemi sur la scène fait apparaître automatiquement sous les props d’instance un panneau <b>Paramètres IA</b> avec des spinboxes contextuelles :
<code>Vitesse</code> (px/frame, pour patrol/chase/random), <code>Portée aggro</code> + <code>Portée perte</code> (×8 px, pour chase uniquement), et <code>Chg. direction</code> (frames, pour random uniquement).
Ces valeurs génèrent des tables C parallèles uniquement si nécessaires — les valeurs défaut ne produisent aucun code. Les ennemis meurent aussi sur <code>DAMAGE</code>/<code>FIRE</code>/<code>VOID</code> et peuvent être <b>stomp</b> si le joueur leur retombe dessus.</p>
<p><b>Data (u8)</b> : champ libre par entité (0–255), exporté tel quel dans <code>_scene.h</code>.
Exemples : variante d’ennemi, ID d’item, paramètre d’event, direction, etc.</p>
<p><b>Bloquer dans la map</b> : chaque instance peut aussi activer ce flag pour demander au runtime template-ready de la clamp aux limites du monde. C’est utile pour un player ou un enemy qui ne doit jamais sortir de la map, sans imposer cette contrainte à tous les types.</p>
<p><b>Respawn à la réentrée</b> : si le <b>Rayon d’activation</b> est activé dans les réglages du projet (valeur &gt; 0), cette option permet à une entité tuée de <b>réapparaître</b> quand la caméra revient dans sa zone après en être sortie. Sans ce flag, un ennemi tué reste mort définitivement pour la session. Utile pour les zones de farm, gardes de couloir, mobs de remplissage, ou tout gameplay où la densité doit rester constante. Les <b>items collectés</b> ne réapparaissent jamais, même avec ce flag.</p>

<h2>Rayon d’activation (World Activation)</h2>
<p>Réglage dans <b>Project Settings</b> (en haut du panneau projet) : <b>Rayon d’activation (tiles)</b>. Valeur 0 = désactivé.</p>
<p>Quand activé, seuls les ennemis dans un rayon donné autour de la caméra sont réellement actifs chaque frame.
Les ennemis hors rayon sont <b>gelés</b> (ni mis à jour, ni dessinés) mais restent en mémoire.
Quand la caméra revient dans leur zone, ils réapparaissent à leur position initiale.</p>
<ul>
  <li><b>0</b> : désactivé — tous les ennemis de la scène tournent en permanence (comportement par défaut)</li>
  <li><b>6–10</b> : recommandé — ennemis actifs 48–80 px au-delà du bord écran, crédible côté gameplay</li>
  <li><b>16</b> : maximum — presque toujours actif même sur grandes maps</li>
</ul>
<p>Le gain de performance est significatif : une scène avec 6 ennemis mais seulement 2–3 visibles n’exécute que 2–3 logiques IA par frame au lieu de 6. Le scan de proximité coûte ~60 cycles (6 comparaisons simples) — négligeable.</p>
<p><b>Comportement à la mort :</b> un ennemi tué (collision joueur, bullet, etc.) est marqué <code>DEAD</code>. Sans le flag <b>Respawn</b>, il ne réapparaît jamais. Avec le flag, il repasse à <code>ALIVE</code> dès que la caméra quitte sa zone — ainsi il faut vraiment sortir de la zone puis y revenir pour le voir respawn (pas de respawn instantané sur place).</p>
<p><b>Note technique :</b> le rayon est une constante de compilation (<code>NGPNG_ACTIVATION_RADIUS_TILES</code>), ce qui garantit un coût runtime minimal sur NGPC.</p>

<h2>Contraintes (Rules)</h2>
<p>L'onglet <b>Rules</b> sert surtout à <b>faciliter le placement dans l'éditeur</b>. Il ne donne pas un comportement intelligent aux ennemis à lui seul.</p>
<ul>
  <li><b>Lock Y</b> : quand vous posez ou déplacez une entité, son Y est forcé à une ligne fixe. Bon usage : jeu de combat ou menu horizontal.</li>
  <li><b>Ground band</b> : quand vous posez ou déplacez une entité, son Y reste dans une bande <code>[min..max]</code>. Bon usage : beat'em up / brawler avec profondeur simulée.</li>
  <li><b>Mirror X</b> : quand vous posez une entité, l'éditeur crée aussi sa copie de l'autre côté de l'axe X. Bon usage : arène symétrique, duel, déco miroir.</li>
  <li><b>Appliquer aux vagues</b> : décide si ces contraintes s'appliquent aussi quand vous placez des entités dans l'onglet Vagues.</li>
</ul>
<p><b>Important :</b> ces contraintes <b>n'animent pas</b> les entités, <b>ne leur donnent pas de chemin</b>, et <b>ne déplacent rien toutes seules pendant le jeu</b>. Elles modifient surtout la façon dont vous posez les objets dans l'éditeur. L'export écrit aussi ces valeurs dans <code>_scene.h</code> comme <b>métadonnées</b> que votre runtime peut exploiter... ou ignorer.</p>
<p>Exemples rapides : <b>fighting</b> = Lock Y seul ; <b>brawler</b> = Ground band ; <b>arène symétrique</b> = Mirror X ; <b>shmup</b> = souvent aucune contrainte ici, on préférera les <b>Vagues</b> et éventuellement les <b>Paths</b>.</p>
<p><b>Autorun platformer :</b> le bloc <b>Rules</b> pilote aussi plusieurs comportements natifs de preview/export :
dégâts de tile (<code>DAMAGE</code>, <code>FIRE</code>, <code>VOID</code>), ressorts, et logique d'échelle
(<code>Sortie haute échelle</code>, <code>Déplacement horizontal sur échelle</code>, <code>Sommet de l'échelle semi-solide</code>).
Dans l'autorun actuel, <code>FIRE</code> est un hazard traversable, pas un sol solide.</p>

<h2>Vagues (shmup et autres genres)</h2>
<ul>
  <li>Ajoutez des vagues, réglez leur <b>délai</b> (frames), puis activez <b>Éditer la vague</b>.</li>
  <li>En mode vague, les clics sur la grille placent les entités dans la vague courante (au lieu du placement statique).</li>
  <li>⚠ Les delays doivent être <b>triés en ordre croissant</b> — le moteur utilise un compteur monotone qui s'arrête à la première vague non prête.</li>
</ul>

<h3>Formule X pour shmup (spawn hors écran à droite)</h3>
<p>Pour un scroll horizontal à <code>speed_x</code> px/frame, l'ennemi doit spawner <em>juste hors de l'écran droit</em> :</p>
<pre>x_tiles = floor(delay × speed_x / 8) + 21
Avec speed_x=1 : x = delay/8 + 21</pre>
<p>Le helper <b>→ spawn X suggéré</b> sous le spinner de delay calcule cette valeur automatiquement. Il suffit d'utiliser la valeur affichée comme coordonnée X de l'entité dans la vague.</p>
<p>Si <code>speed_x</code> change, recalculer tous les X. La formule dérive de :
<code>cam_x_at_fire + screen_width_tiles + 1 marge</code>.</p>
<p><b>Presets de vague :</b> le bloc <b>Preset</b> ajoute aussi des formations de départ réutilisables : <b>Ligne x3</b>, <b>V x5</b> et <b>Paire au sol</b>. Le tool prend d'abord le type d'entité actuellement sélectionné ; sinon il retombe sur le premier type marqué <b>enemy</b>.</p>

<h3>Champ data (u8) — patterns de mouvement ennemis</h3>
<p>Si la scène n'a <b>pas de chemins</b> (<code>paths=[]</code>), le champ <b>data</b> contrôle le mouvement des ennemis :</p>
<table>
  <tr><th>data</th><th>Mouvement</th></tr>
  <tr><td>0</td><td>Droit vers la gauche (vx=−2)</td></tr>
  <tr><td>1</td><td>Dérive vers le bas (vy=+1, rebondit)</td></tr>
  <tr><td>2</td><td>Dérive vers le haut (vy=−1, rebondit)</td></tr>
  <tr><td>3</td><td>Alterne haut/bas selon la parité du Y de spawn</td></tr>
  <tr><td>4</td><td>Zigzag — flip vy toutes les 16 frames</td></tr>
  <tr><td>5</td><td>Rapide — vx=−4 (double vitesse, ligne droite)</td></tr>
</table>
<p>Si la scène <b>a des chemins</b> et <code>data &gt; 0</code>, l'ennemi suit le chemin <code>path[data-1]</code>.
⚠ Pour le shmup wave-based, garder <code>paths=[]</code> pour éviter que les ennemis partent vers la droite.</p>

<h2>Régions</h2>
<p>L’onglet <b>Régions</b> définit des rectangles (en tiles) dans la scène. Activez <b>Éditer régions</b>,
puis <b>glissez</b> sur la grille pour dessiner un rectangle.
Les régions sont exportées en C (<code>NgpngRegion</code> : x, y, w, h, kind).</p>
<p><b>Types disponibles :</b> <b>zone</b> (violet, générique), <b>no_spawn</b> (orange, bloque Procgen),
<b>danger_zone</b> (rouge, hazard), <b>checkpoint</b> (vert, respawn natif),
<b>exit_goal</b> (jaune, sortie native), <b>camera_lock</b> (bleu, clamp caméra),
<b>spawn</b> (cyan, cible de <code>warp_to</code>),
<b>attractor</b> (force vers le centre), <b>repulsor</b> (force depuis le centre).</p>
<p><b>Presets de région :</b> le bloc <b>Preset</b> crée aussi des points de départ utiles depuis la caméra actuelle : <b>Checkpoint 4x4</b>, <b>Zone safe no-spawn</b> et <b>Sol dangereux</b>. C’est pratique pour poser vite une zone de test, une zone protégée de spawn ou une base de piège.</p>

<h2>Triggers</h2>
<p>L’onglet <b>Triggers</b> associe des <b>conditions</b> à des <b>actions</b>.
<b>87 conditions</b> dont 18 conditions par type d’entité (régions, seuils caméra, timer, vagues, boutons, santé, ennemis, flags, variables, états joueur, physique, type d’entité…) et
<b>73 actions</b> (audio, spawn, scroll, shake, scènes, anim, flags/variables, téléportation, fondu, inventaire…) + groupes OR.</p>
<p>Fonctionnalités clés : <b>⧉ Dup</b> (dupliquer un trigger), <b>Conditions ET</b> (plusieurs conditions simultanées), <b>once</b> (ne se déclenche qu’une fois).</p>
<p>Les <b>conditions par type d’entité</b> (<code>entity_type_*</code>) sont détaillées dans le topic <b>Globals</b>.</p>
<p>→ <b>Référence complète (toutes les conditions, actions, exports, patterns) : topic <i>Triggers &amp; Régions</i></b></p>

<h2>Chemins (Paths)</h2>
<p>L'onglet <b>Chemins</b> définit des routes (liste de points en coordonnées tile) pour des PNJ, des patrouilles,
des rails de shmup, etc. Activez <b>Éditer chemins</b> puis cliquez sur la grille pour ajouter des points.
<b>Glisser</b> un point le déplace ; <b>clic droit</b> ou <b>Suppr</b> le supprime.
Les chemins sont exportés en C (offsets/lengths/flags + points).</p>
<ul>
  <li><b>Qui suit le chemin ?</b> Seulement les entités auxquelles vous attribuez ce path dans l'onglet <b>Entité</b>, via le champ <b>Chemin de patrouille</b>. Dessiner un path seul ne fait rien.</li>
  <li><b>Attribution plus simple</b> : vous pouvez aussi sélectionner un path puis utiliser le bouton <b>Assigner à l'entité sélectionnée</b> directement dans l'onglet <b>Chemins</b>.</li>
  <li><b>Quand ça démarre ?</b> L'éditeur décrit la route et exporte un index de path par entité. Le moment exact de départ dépend du runtime. Exemple fréquent : activation dès le spawn.</li>
  <li><b>Que se passe-t-il à la fin ?</b> Si <b>Boucle</b> est coché, on revient au premier point. Sinon, le trajet s'arrête au dernier point et le runtime décide de la suite.</li>
  <li><b>Important</b> : un path n'est pas une animation autonome. C'est une suite de points que votre runtime peut interpréter comme une route.</li>
</ul>
<p><b>Template livré avec le tool :</b> pour les ennemis statiques, le champ <b>Chemin</b> est maintenant utilisé directement au spawn. Sans boucle, l'ennemi quitte le path à la fin et reprend son déplacement template par défaut.</p>

<h2>Labels texte (sysfont)</h2>
<p>L'onglet <b>Labels texte</b> permet de placer du texte statique sur la scène, rendu à l'écran via la police système du BIOS NGPC (<code>ngpc_text_print</code>).</p>
<ul>
  <li><b>Ajouter</b> : crée un label vide. <b>Supprimer</b> : retire le label sélectionné.</li>
  <li><b>Texte</b> : chaîne ASCII, max 20 caractères.</li>
  <li><b>X / Y</b> : position en tiles (X : 0–19, Y : 0–18).</li>
  <li><b>Palette</b> : index couleur BG (0–3, 0 = défaut blanc/noir sysfont).</li>
  <li><b>Plan</b> : <code>SCR1</code> ou <code>SCR2</code> — plan de scroll sur lequel afficher le texte.</li>
</ul>
<p><b>Rendu dans l'éditeur :</b> les labels apparaissent en vert sur fond noir semi-transparent sur le canvas. Le label sélectionné a un contour jaune.</p>
<p><b>Export C :</b> quand la scène a au moins un label, le générateur émet dans <code>scene_*_level.h</code> :</p>
<ul>
  <li><code>#define {SYM}_TEXT_LABEL_COUNT N</code></li>
  <li><code>g_{sym}_text_label_x[]</code>, <code>g_{sym}_text_label_y[]</code>, <code>g_{sym}_text_label_pal[]</code>, <code>g_{sym}_text_label_plane[]</code></li>
  <li><code>const char * const g_{sym}_text_labels[]</code></li>
</ul>
<p>Et dans <code>scene_xxx_load_all()</code> (loader généré) :</p>
<pre><code>#if SCENE_TEXT_LABEL_COUNT &gt; 0
for (u8 i = 0; i &lt; SCENE_TEXT_LABEL_COUNT; i++)
    ngpc_text_print(g_text_label_plane[i], g_text_label_pal[i],
                    g_text_label_x[i], g_text_label_y[i], g_text_labels[i]);
#endif</code></pre>
<p>⚠ Les labels texte sont <b>statiques</b> : ils sont écrits une fois au chargement de la scène. Pour du texte dynamique (score, HP…), utilisez <code>ngpc_text_print</code> directement dans votre runtime.</p>

<h2>data (u8)</h2>
<p>Le champ <b>data (u8)</b> est volontairement générique : c'est un octet libre (0–255) exporté
tel quel avec l'entité. Exemples d'usage : variante d'ennemi, ID de script, direction de spawn,
paramètre de trigger, item type, etc.</p>

<h2>Procgen (carte de collision)</h2>
<p>Le Procgen peut générer une grille de collision (<b>u8 par tile</b>) selon un <b>mode carte</b> :
plateforme, top-down, shmup, champ libre, ou aucun (acteurs seuls).</p>
<ul>
  <li>Le toggle <b>Collision</b> affiche un overlay coloré par type (SOLID, ONE_WAY, DAMAGE, LADDER, etc.).</li>
  <li>En top-down, l'option <b>Murs directionnels</b> peut convertir certains murs en faces <code>WALL_N/S/E/W</code>.</li>
  <li><b>Rôle → tile visuel</b> : associe chaque type de collision à un index de tile (0–255)
      afin d'exporter une map visuelle en plus de la collision. Cet index correspond à votre
      <b>tileset</b> (ce n'est pas un <code>tile_base</code> VRAM).</li>
  <li><b>Variantes visuelles</b> : utilisez surtout <b>Choisir...</b> pour sélectionner visuellement une ou plusieurs tiles. Les numéros visibles sous chaque vignette sont les vrais IDs utilisés par le procgen. La saisie manuelle <code>12,13,14</code> reste possible si vous savez déjà ce que vous voulez.</li>
  <li><b>Aperçu / source</b> : la preview et le sélecteur utilisent la <b>Source tiles</b> du procgen (Auto, SCR1 ou SCR2). Si le rendu ne correspond pas, vérifiez d'abord cette source.</li>
</ul>
<p><b>Important :</b> les rôles <code>WATER</code>, <code>FIRE</code>, <code>VOID</code>, <code>DOOR</code> et <code>SPRING</code> restent des <b>catégories de collision</b>. Les dégâts, la mort directe et le rebond se règlent maintenant dans <b>Level &gt; Rules</b>, tandis que la transition de scène reste pilotée par le runtime/triggers.</p>
<p>Pour du décor purement visuel, utilisez surtout des variantes du rôle passable (<b>Vide / air</b>, <b>Sol passable</b>) ou un BG/plane séparé. Ici, le Procgen décrit d'abord la <b>collision</b>, puis l'habillage visuel associé.</p>

<h2>Sauvegarde dans le projet</h2>
<p>Le bouton <b>Sauvegarder dans le projet</b> met à jour la scène dans le <code>.ngpcraft</code> :</p>
<pre>scenes[].entities
scenes[].waves
scenes[].regions
scenes[].triggers
scenes[].paths
scenes[].entity_roles
scenes[].level_profile
scenes[].level_size
scenes[].map_mode
scenes[].level_bg_scr1
scenes[].level_bg_scr2
scenes[].level_bg_front
scenes[].level_cam_tile
scenes[].level_scroll
scenes[].level_layout
scenes[].level_layers
scenes[].level_rules
scenes[].col_map
scenes[].tile_ids
scenes[].neighbors
scenes[].bg_chunk_map</pre>

<h2>Scènes voisines — warps de bord (Track B)</h2>
<p>Le panneau <b>Scènes voisines</b> dans l'onglet <b>Layout</b> permet de relier jusqu'à 4 scènes voisines
(Nord / Sud / Ouest / Est). Quand un voisin est sélectionné, l'export génère automatiquement :</p>
<ul>
  <li>Une <b>région de sortie</b> de 8 px de large sur le bord correspondant (type <code>zone</code>).</li>
  <li>Un <b>spawn d'entrée</b> en slot fixe dans la scène voisine (W=slot 0, E=1, N=2, S=3).</li>
  <li>Un <b>trigger <code>warp_to</code></b> qui porte vers la scène cible et le bon spawn d'entrée (slot opposé).</li>
</ul>
<p><b>Zone de déclenchement :</b> la région couvre <em>tout le bord</em> (pleine largeur pour Nord/Sud,
pleine hauteur pour Est/Ouest). Il n'est pas possible de restreindre le warp à une portion du bord via ce panneau.
Si vous avez besoin d'un warp sur seulement une partie du bord (ex : une porte), utilisez à la place une région
manuelle (<b>Région → zone</b>) + un trigger <code>warp_to</code> placé à l'endroit voulu dans l'onglet
<b>Triggers</b>.</p>
<p><b>Contrainte clé :</b> les slots 0–3 des régions de spawn de la scène cible sont réservés aux entrées auto.
Vos spawns manuels commencent à l'index 4.</p>
<p><b>Comment utiliser :</b></p>
<ol>
  <li>Dans <b>Level → Layout</b>, choisissez la scène voisine dans la liste déroulante de la direction voulue.</li>
  <li>Sauvegardez dans le projet.</li>
  <li>Aucun changement runtime n'est nécessaire : tout repose sur <code>warp_to</code> + <code>spawn_points</code> existants.</li>
</ol>
<p>La validation signale si une scène cible est introuvable dans le projet.</p>

<h2>Chunk Map SCR1 — grande map assemblée (Track A)</h2>
<p>Le panneau <b>Chunk Map SCR1</b> dans l'onglet <b>BG</b> permet d'assembler plusieurs petites tilemaps PNG
en un seul grand tableau <code>g_{nom}_bg_map[]</code> en ROM, sans limite de 32×32 tiles.</p>
<ul>
  <li>Définissez la grille <b>Lignes × Cols</b> de chunks (max 8×8).</li>
  <li>Sélectionnez le PNG de tilemap correspondant dans chaque cellule (depuis les tilemaps de la scène).</li>
  <li>Les lignes d'une même colonne doivent partager la <b>même hauteur en tiles</b>.</li>
  <li>Le champ JSON enregistré est <code>bg_chunk_map.grid</code> : une liste de listes de chemins PNG relatifs.</li>
</ul>
<p><b>À l'export :</b> les chunks sont assemblés row-major en un seul tableau. Des macros
<code>SCENE_X_CHUNK_MAP_W/H</code> donnent les dimensions totales (en tiles) pour configurer
<code>ngpc_mapstream_init()</code>. Le SCR1 est automatiquement géré par <code>ngpc_mapstream</code>,
donc <code>scr1_by_mapstream = true</code> est forcé.</p>
<p><b>Contrainte :</b> les chunks doivent d'abord être présents dans <b>Tilemaps</b> de la scène
pour être proposés dans les listes déroulantes. Ajoutez-les d'abord dans l'onglet <b>Projet</b>.</p>

<h2>Export C : <code>_scene.h</code></h2>
<p>L'export génère un header complet : IDs d'entités, hitboxes/props, placement statique, tables de vagues,
et si une carte existe : <code>g_&lt;scene&gt;_tilecol</code> + <code>g_&lt;scene&gt;_tilemap_ids</code>.</p>
<p>Le header exporte aussi maintenant des métadonnées de genre et de carte :
<code>SCENE_*_PROFILE</code>, <code>SCENE_*_MAP_MODE</code> et plusieurs <code>SCENE_*_PROFILE_*_HINT</code>
pour relier plus facilement le runtime au <b>Profil</b> choisi dans l'éditeur.</p>
<p>Le format exporté est le même que vous passiez par l'export local de <b>Level</b>, l'onglet <b>Projet</b> ou l'export headless.</p>

<hr/>

<h2>Guide d'utilisation (pas à pas)</h2>
<ol>
  <li><b>Onglet Projet</b> : ajoutez vos <b>sprites</b> et <b>tilemaps</b> à la scène (et assignez le plane <code>scr1/scr2</code> si besoin).</li>
  <li><b>Level</b> : réglez la <b>Taille</b> (W×H) de la room en tiles. Utilisez <b>Fit BG</b> si vous partez d’une tilemap 32×32.</li>
  <li><b>Rôles</b> : assignez un rôle à chaque type (player/enemy/item…) pour que Procgen sache quoi placer.</li>
  <li><b>Placement manuel</b> : placez quelques entités importantes (player, points clés) ou laissez Procgen le faire.</li>
  <li><b>Procgen</b> : choisissez un <b>mode carte</b>, réglez seed/marge/densités, puis cliquez <b>Générer</b>.</li>
  <li><b>(Optionnel) Tilemaps PNG</b> : cochez <b>Générer des tilemaps PNG</b> si vous voulez produire une map visuelle SCR1/SCR2 depuis <code>col_map</code>.</li>
  <li><b>Layout</b> : configurez caméra/scroll/forced/loop/bounds pour documenter le comportement attendu côté jeu.</li>
  <li><b>Sauvegarder dans le projet</b> : écrit toutes les données dans le <code>.ngpcraft</code>.</li>
  <li><b>Exporter (Projet → Scène → .c)</b> : exporte sprites + tilemaps + headers, y compris <code>scene_&lt;name&gt;_level.h</code>.</li>
</ol>

<h2>Tour complet de l'UI</h2>
<ul>
  <li><b>Barre centrale</b> : BG SCR1 / BG SCR2 / Devant / Taille / Fit BG / Zoom / toggles (Bezel, Cam, col_map) / Undo-Redo.</li>
  <li><b>Canvas</b> : affiche le(s) BG à leur taille réelle (scalé uniquement par le zoom) + overlay collision + entités.</li>
  <li><b>Gauche</b> : liste des types (sprites de la scène) + assignation de rôles.</li>
  <li><b>Droite</b> : onglets (Vagues, Procgen, Layout, Planes/parallax, Rules, Diagnostics, Régions, Triggers, Paths) selon votre version.</li>
</ul>

<h2>Layout (détails)</h2>
<ul>
  <li><b>Cam start</b> : position initiale de caméra en tiles (visible via le rectangle “CAM”, déplaçable au Ctrl+drag).</li>
  <li><b>Scroll X/Y</b> : indique les axes où la caméra est autorisée à se déplacer (métadonnées).</li>
  <li><b>Forced scroll</b> : scrolling automatique avec <b>speed_x/speed_y</b> (unités à interpréter côté runtime).</li>
  <li><b>Loop X/Y</b> : documentation d’un niveau “boucle” (utile shmup). Le preview peut répéter le BG pour aider à visualiser.</li>
  <li><b>Mode caméra</b> : <i>single_screen</i>, <i>follow</i>, <i>forced_scroll</i>, <i>segments</i>, <i>loop</i> (exporté en <code>CAM_MODE</code>).</li>
  <li><b>Bounds / clamp</b> : min/max caméra en tiles. En “auto”, ils sont calculés depuis la taille de la map.</li>
</ul>

<h2>Rules (détails)</h2>
<ul>
  <li><b>Lock Y</b> : force Y à une ligne constante pendant le placement/déplacement. Idéal pour fighting ou menu horizontal.</li>
  <li><b>Ground band</b> : limite Y à une bande [min..max] pendant le placement/déplacement. Idéal pour brawler avec profondeur simulée.</li>
  <li><b>Mirror X</b> : place aussi une copie symétrique autour d’un axe. Idéal pour arènes et layouts symétriques.</li>
  <li><b>Appliquer aux vagues</b> : décide si ces contraintes s'appliquent aussi à l'édition des vagues.</li>
</ul>
<p><b>À ne pas confondre avec Paths :</b> les Rules servent à <b>poser</b> les entités ; les Paths servent à décrire une <b>route</b> qu'un runtime peut faire suivre.</p>

<h2>Régions / Triggers / Paths (détails)</h2>
<ul>
  <li><b>Régions</b> : rectangles en tiles. <code>no_spawn</code> empêche Procgen d’y placer des entités. <code>danger_zone</code> = hazard runtime.</li>
  <li><b>Triggers</b> : 87 conditions × 73 actions + groupes OR (dont 18 par type d'entité). Voir topics <b>Triggers &amp; Régions</b> et <b>Globals</b>.</li>
  <li><b>Paths</b> : routes en points tile (patrouilles, rails). <b>Loop</b> boucle le trajet.</li>
</ul>

<h2>Procgen : points importants</h2>
<ul>
  <li><b>Placement</b> : si <code>col_map</code> existe, Procgen ne place que sur <code>TILE_PASS</code> (et respecte <i>no-spawn</i> + Rules).</li>
  <li><b>Multi-tiles</b> : un sprite 16×16 occupe 2×2 tiles. Procgen vérifie l'empreinte pour éviter les overlaps et les tiles non passables.</li>
  <li><b>Rôle → tile visuel</b> : c'est un <b>index dans une image tileset</b> (0–255). Ce n'est <b>pas</b> un slot VRAM. Dans l'UI, utilisez surtout <b>Choisir...</b> pour voir les tiles et leurs IDs.</li>
  <li><b>Spéciaux</b> : eau, feu, vide, porte = catégories. Le gameplay exact reste défini par votre runtime.</li>
</ul>

<h2>Types de collision (rappels)</h2>
<p><code>col_map</code> utilise des constantes compatibles avec <code>ngpc_tilecol.h</code> (quand présent) :</p>
<ul>
  <li><b>PASS</b> : vide / traversable.</li>
  <li><b>SOLID</b> : mur/sol solide.</li>
  <li><b>ONE_WAY</b> : plateforme traversable par dessous (platformer).</li>
  <li><b>DAMAGE</b> : hazard (piques, lave…).</li>
  <li><b>LADDER</b> : échelle (platformer).</li>
  <li><b>SPRING</b> : ressort / projection paramétrable par scène (force + direction).</li>
  <li><b>WALL_N/S/E/W</b> : murs directionnels (top-down).</li>
  <li><b>WATER / FIRE / VOID / DOOR</b> : types “spéciaux” (le runtime du jeu décide : nage, dégâts, trou, transition…). Dans l'autorun actuel, <b>FIRE</b> inflige des dégâts mais reste traversable.</li>
</ul>

<h2>Procgen → tilemaps PNG : cohérence et limites</h2>
<ul>
  <li>Le PNG généré est <b>visuellement</b> cohérent (copie de tiles 8×8 depuis la source). Ensuite, l'export tilemap peut dédupliquer/réordonner en VRAM : c'est normal.</li>
  <li>Si vous voulez une map “logique” côté runtime, utilisez <code>g_&lt;scene&gt;_tilecol</code> (collision) + <code>g_&lt;scene&gt;_tilemap_ids</code> (IDs) et faites votre propre interprétation.</li>
  <li>Astuce : gardez des tiles réservées dans votre atlas pour les rôles gameplay (sol, mur, eau, porte…) afin que le mapping reste stable.</li>
</ul>

<h2>Exemples rapides par genre</h2>
<ul>
  <li><b>Fighting</b> : Rules → <i>Lock Y</i> + <i>Mirror X</i> (axe), mode carte = none.</li>
  <li><b>Platformer</b> : map_mode=platformer, collision overlay ON, ONE_WAY/LADDER, cam mode=follow.</li>
  <li><b>Run &amp; Gun</b> : forced_scroll OFF, scroll_x ON, waves pour spawns, regions/triggers pour scripts.</li>
  <li><b>Shmup</b> : cam mode=forced_scroll, loop_y ON, waves + paths (rails) pour patterns.</li>
  <li><b>Top-down RPG</b> : map_mode=topdown (+ dir walls), regions pour zones, triggers pour transitions/portes.</li>
</ul>

<h2>Dépannage (problèmes fréquents)</h2>
<ul>
  <li><b>Procgen : “No valid positions”</b> : la marge est trop grande, ou la map générée ne laisse pas assez de <code>TILE_PASS</code>. Réduisez la marge/densité d’obstacles, ou changez de mode.</li>
  <li><b>Procgen : placements “bizarres”</b> : vérifiez les <b>rôles</b> (player/enemy/item). Sans rôles, Procgen ne peut pas distinguer les types.</li>
  <li><b>Entités qui se chevauchent</b> : pour les gros sprites, assurez-vous que la collision laisse assez d’espace. Procgen évite les overlaps, mais le placement manuel peut en créer.</li>
  <li><b>Tilemaps PNG : erreur “needs a BG PNG”</b> : sélectionnez un BG SCR1 ou SCR2, ou mettez “Tile source” sur Auto.</li>
  <li><b>Tilemaps PNG : rendu inattendu</b> : le mapping “Rôle → tile visuel” pointe vers un mauvais index de tile dans l’atlas. Corrigez les index et régénérez.</li>
  <li><b>BG qui “ne correspond pas” à l’export</b> : l’export tilemap peut produire des variantes <code>_scr1/_scr2</code> (dual-layer). Assurez-vous d’avoir les bons fichiers et le bon plane.</li>
</ul>

<h2>Procgen runtime — sous-onglets Dungeon DFS et Cave</h2>
<p>L’onglet <b>Procgen</b> contient désormais <b>trois sous-onglets</b> :</p>
<ul>
  <li><b>Design Map</b> — génération design-time existante (BSP, scatter, etc.). Produit une <code>col_map</code> statique exportée en C.</li>
  <li><b>Dungeon DFS</b> — configuration du module <code>ngpc_procgen</code> pour une génération <em>runtime</em> dans le jeu.</li>
  <li><b>Cave</b> — configuration du module <code>ngpc_cavegen</code> (automate cellulaire 32×32 tiles) pour une génération <em>runtime</em>.</li>
</ul>
<p><b>Activation par scène :</b> chaque sous-onglet (Dungeon DFS et Cave) possède une <b>case à cocher principale</b> en haut
(<i>Enable Dungeon DFS runtime generation for this scene</i> / <i>Enable Cave runtime generation for this scene</i>).
Tant que la case est décochée, tous les paramètres sont grisés et <b>rien n’est sauvegardé ni exporté</b> pour ce module.
Cocher la case active les paramètres et les inclut dans le <code>.ngpcraft</code> lors de la prochaine sauvegarde.</p>

<h2>Sous-onglet Dungeon DFS — paramètres runtime</h2>
<p>Configure le module <code>ngpc_procgen</code> (DFS récursif sur grille N×M de rooms).</p>
<table>
  <tr><th>Paramètre</th><th>Plage</th><th>Description</th><th>→ <code>#define</code></th></tr>
  <tr><td>Grid W / H</td><td>2–8</td><td>Dimensions de la grille de rooms. RAM : ~72 B + W×H octets.</td><td><code>PROCGEN_GRID_W/H</code></td></tr>
  <tr><td>Max enemies per room</td><td>0–12</td><td>Nombre max d’ennemis placés par room à la génération.</td><td><code>PROCGEN_MAX_ENEMIES</code></td></tr>
  <tr><td>Item chance</td><td>0–100 %</td><td>Probabilité qu’un item apparaisse dans une room.</td><td><code>PROCGEN_ITEM_CHANCE</code></td></tr>
  <tr><td>Loop injection</td><td>0–80 %</td><td>Couloirs supplémentaires ajoutés après le DFS pour créer des boucles. 0 = donjon pur arbre.</td><td><code>PROCGEN_LOOP_PCT</code></td></tr>
  <tr><td>Max active enemies</td><td>1–40</td><td>Plafond global d’ennemis vivants simultanément dans toutes les rooms.</td><td><code>PROCGEN_MAX_ACTIVE</code></td></tr>
  <tr><td>Player start mode</td><td>3 options</td><td>Corner (0,0) / Random room / Furthest from exit.</td><td><code>PROCGEN_START_MODE</code></td></tr>
</table>
<p><b>Table de difficulté (5 tiers) :</b> chaque colonne correspond à un palier de difficulté (tier = <code>FLOOR / 5</code>, plafonné à 4).
Les 4 lignes sont : max enemies, item chance%, loop pct%, max active.
Valeurs éditables directement dans le tableau.</p>
<p><b>Multi-floor :</b> cochez <i>Enable multi-floor</i> pour activer les paramètres de progression :</p>
<ul>
  <li><b>Floor variable index (0–7)</b> : slot de <code>game_vars[]</code> qui stocke l’étage actuel.</li>
  <li><b>Max floors (0 = infini)</b> : au-delà, redirection vers la scène boss/fin.</li>
  <li><b>Boss/end scene</b> : scène goto quand <code>FLOOR ≥ max_floors</code>.</li>
  <li><b>Reload scene</b> : scène cible pour le prochain étage (vide = self-reload).</li>
</ul>
<p><b>Bouton Export :</b> génère <code>GraphX/gen/procgen_config.h</code> avec tous les <code>#define</code> et les macros de tiers. À inclure <em>avant</em> <code>ngpc_procgen.h</code> dans votre code C.</p>

<h2>Sous-onglet Cave — paramètres runtime</h2>
<p>Configure le module <code>ngpc_cavegen</code> (automate cellulaire 32×32 tiles, 1 024 octets RAM).</p>
<table>
  <tr><th>Paramètre</th><th>Plage</th><th>Description</th><th>→ <code>#define</code></th></tr>
  <tr><td>Initial wall %</td><td>30–70 %</td><td>Densité initiale de murs. 40–50% = cavernes organiques, &gt;55% = couloirs étroits.</td><td><code>CAVEGEN_WALL_PCT</code></td></tr>
  <tr><td>CA iterations</td><td>1–10</td><td>Passes de lissage. Plus = cavernes rondes, coût init plus élevé.</td><td><code>CAVEGEN_ITERATIONS</code></td></tr>
  <tr><td>Max enemies</td><td>0–16</td><td>Ennemis placés dans les cellules sol libres.</td><td><code>CAVEGEN_MAX_ENEMIES</code></td></tr>
  <tr><td>Max items</td><td>0–8</td><td>Pickups placés directement sur le sol — le procgen spawn l'entity type <em>pickup</em> avec le sprite de l'item tiré de l'item pool.</td><td><code>CAVEGEN_MAX_ITEMS</code></td></tr>
  <tr><td>Pickup entity type index</td><td>0–255</td><td>Index de l'entity type générique "pickup" (rôle <code>item</code>). Le runtime l'utilise pour spawner les items. Son sprite est écrasé par <code>g_item_table[idx].sprite_id</code>.</td><td><code>CAVEGEN_PICKUP_TYPE</code></td></tr>
</table>
<p><b>Table de difficulté (5 tiers) :</b> 3 lignes × 5 colonnes (wall%, max enemies, max items par tier).</p>
<p><b>Multi-floor :</b> identique au DFS — floor variable, max floors, boss/end scene.</p>
<p><b>Bouton Export :</b> génère <code>GraphX/gen/cavegen_config.h</code>. À inclure <em>avant</em> <code>ngpc_cavegen.h</code>.</p>

<h2>Persistance des paramètres procgen par scène</h2>
<p>Les paramètres des trois sous-onglets (Design Map, Dungeon DFS, Cave) sont sauvegardés <b>par scène</b> dans le <code>.ngpcraft</code> :</p>
<pre>scenes[].procgen_params    ← Design Map (seed, mode, densités…)
scenes[].rt_dfs_params     ← Dungeon DFS (grille, tiers, multi-floor…)  — uniquement si activé
scenes[].rt_cave_params    ← Cave (wall_pct, iterations, tiers, multi-floor…) — uniquement si activé</pre>
<p><b>Important :</b> <code>rt_dfs_params</code> et <code>rt_cave_params</code> ne sont écrits dans le JSON
<em>que si la case à cocher principale du sous-onglet est cochée</em>.
Si vous décochez la case et sauvegardez, la clé est supprimée du <code>.ngpcraft</code>.
Le pipeline d’export (<b>Export project</b> dans l’onglet Projet) ne génère <code>procgen_config.h</code> / <code>cavegen_config.h</code>
que pour les scènes où le module est activé.</p>
<p>Changer de scène restaure automatiquement l’état de la case à cocher et les paramètres correspondants.
La duplication de scène (bouton <b>⧉</b> dans l’onglet Projet) copie aussi ces paramètres et leur état d’activation.</p>

<h2>Intégration C — procgen_config.h</h2>
<pre>#include “GraphX/gen/procgen_config.h”  /* avant ngpc_procgen.h */
#include “ngpc_procgen.h”

static ProcgenMap g_dungeon;

void game_init(void) {
    u8 floor = ngpc_gv_get_var(PROCGEN_FLOOR_VAR);
    u8 tier  = (floor / 5u &gt; 4u) ? 4u : floor / 5u;
    u8 mx_e  = PROCGEN_TIER_MAX_ENEMIES[tier];
    u8 lp    = PROCGEN_TIER_LOOP_PCT[tier];
    ngpc_procgen_generate_ex(&amp;g_dungeon, ngpc_rng_next(),
                             PROCGEN_GRID_W, PROCGEN_GRID_H, lp);
    ngpc_procgen_gen_content(&amp;g_dungeon, mx_e,
                             PROCGEN_TIER_ITEM_CHANCE[tier]);
}</pre>
"""


def _fr_palette_bank() -> str:
    return """
<h1>Banque Palettes VRAM (sprite slots)</h1>

<h2>Vue d'ensemble</h2>
<p>Dans l'onglet <b>VRAM Map</b>, la section <i>Sprites (16)</i> affiche
désormais une <b>banque de 16 slots de palette</b> enrichie, au lieu d'une simple barre colorée.</p>

<h2>Ce que montre chaque slot</h2>
<table>
  <tr><th>Élément</th><th>Description</th></tr>
  <tr><td>Numéro du slot</td><td>Index 0–15 dans la banque palette sprites hardware</td></tr>
  <tr><td>4 swatches couleur</td><td>Les 4 couleurs de la palette (index 0 = transparent = carré sombre)</td></tr>
  <tr><td>Badge <b>×N</b></td><td>Affiché en jaune si N sprites partagent ce slot via <code>--fixed-palette</code></td></tr>
  <tr><td>Slot sombre</td><td>Slot libre (non utilisé par la scène courante)</td></tr>
</table>

<h2>Infobulle</h2>
<p>Survolez un slot pour voir le nom du (des) sprite(s) propriétaire(s).</p>

<h2>Clic → Ouvrir dans Palette</h2>
<p>Cliquez sur un slot occupé pour <b>basculer directement vers l'onglet Palette</b>
avec ce sprite chargé. Pratique pour inspecter ou modifier les couleurs sans
naviguer manuellement.</p>

<h2>Palettes partagées (<code>fixed_palette</code>)</h2>
<p>Quand plusieurs sprites partagent la même palette (configuré via l'onglet Palette
ou <code>--fixed-palette</code> dans le pipeline), ils occupent le <b>même slot</b>
et le badge <b>×N</b> indique le nombre de sprites qui le partagent.</p>

<h2>Sources des couleurs</h2>
<ul>
  <li>Si le sprite a un champ <code>fixed_palette</code> dans le projet : les couleurs
      affichées correspondent exactement à cette palette.</li>
  <li>Sinon : les couleurs sont extraites du PNG source (quantization RGB444).</li>
</ul>
"""


def _en_hitbox() -> str:
    return """
<h1>Hitbox Editor</h1>

<h2>Overview — 3 layers</h2>
<p>The <b>Hitbox</b> tab manages three independent data layers for each sprite:</p>
<table>
  <tr><th>Layer</th><th>What it defines</th><th>Per-frame?</th></tr>
  <tr><td><b>Hurtbox</b></td><td>Area that <b>receives</b> damage. Also drives the main gameplay collision box (floor, walls, contact damage).</td><td>Yes</td></tr>
  <tr><td><b>Attack hitbox</b></td><td>One or more boxes that <b>deal</b> damage. Each has its own damage, knockback, priority, timing window, and animation-state filter.</td><td>No (per type)</td></tr>
  <tr><td><b>Properties</b></td><td>Per-sprite gameplay/physics data: HP, speed, gravity, jump, flip, etc.</td><td>No (per sprite)</td></tr>
</table>
<p>The first two are edited in the <b>Hurtbox</b> and <b>Attack</b> sub-tabs.
Note: disabling a hurtbox also disables the sprite's main gameplay collision (both are linked in the V1 runtime).</p>

<h2>Opening a sprite</h2>
<ul>
  <li>From the <b>Project</b> tab: select a sprite and click <b>Open in Hitbox</b>.</li>
  <li>Directly in the Hitbox tab: click <b>Open…</b> to load a PNG without project context.</li>
</ul>

<h2>Frame navigation (◀/▶ or ←/→ keyboard)</h2>
<p>When a sprite is opened from a project, the canvas automatically uses the frame
dimensions defined in the scene (<code>frame_w</code> / <code>frame_h</code>).
Each frame of the spritesheet is cropped and displayed individually.</p>
<p>Two ways to change frames:</p>
<ul>
  <li><b>◀ / ▶</b> buttons below the canvas (left column).</li>
  <li><b>← / →</b> keyboard keys — faster when the panel is visible.</li>
</ul>
<p>Each frame has its own independent hurtbox.
<b>Copy to all frames</b> propagates the current hurtbox to every frame of the sprite.</p>

<h2>Keyboard shortcuts</h2>
<table>
<tr><th>Key</th><th>Action</th></tr>
<tr><td><b>← / →</b></td><td>Previous / next frame</td></tr>
<tr><td><b>Alt+← / Alt+→</b></td><td>Previous / next attack box</td></tr>
<tr><td><b>Insert</b></td><td>Add an attack box</td></tr>
<tr><td><b>Delete</b></td><td>Remove current attack box</td></tr>
<tr><td><b>Ctrl+S</b></td><td>Save hitboxes to project</td></tr>
<tr><td><b>Ctrl++</b> / <b>Ctrl+-</b></td><td>Zoom in / zoom out</td></tr>
<tr><td><b>F5</b></td><td>Export → C header (.h)</td></tr>
</table>

<h2>Coordinate system</h2>
<p>The origin <code>(0, 0)</code> is the <b>sprite centre</b> (white cross).
<code>x</code> and <code>y</code> are the <b>top-left corner offsets</b> from that centre.
<code>w</code> and <code>h</code> are in pixels.</p>
<table>
  <tr><th>Field</th><th>Description</th><th>Range</th></tr>
  <tr><td><b>x</b></td><td>Horizontal offset (top-left)</td><td>−128 … 127</td></tr>
  <tr><td><b>y</b></td><td>Vertical offset (top-left)</td><td>−128 … 127</td></tr>
  <tr><td><b>w</b></td><td>Box width</td><td>1 … 255</td></tr>
  <tr><td><b>h</b></td><td>Box height</td><td>1 … 255</td></tr>
</table>

<h2>Canvas editing</h2>
<ul>
  <li><b>Click-drag in empty area</b>: draw a new box.</li>
  <li><b>Drag the centre</b>: move the entire box.</li>
  <li><b>Drag a handle (corner or edge)</b>: resize the box.</li>
  <li>The <b>x / y / w / h</b> spinboxes reflect the box and can be edited directly.</li>
</ul>

<h2>Hurtbox — area that receives damage</h2>
<p>The hurtbox is defined <b>per frame</b>. The <b>Hurtbox</b> sub-tab shows the current frame and lets you draw or adjust the box on the canvas.</p>
<p>Stored under <code>sprites[].hurtboxes[]</code> in the <code>.ngpcraft</code>.
Export generates <code>g_{name}_hit[]</code> (a <code>NgpcSprHit</code> array, one entry per frame).</p>

<h2>Attack hitboxes (offensive boxes)</h2>
<p>Each sprite can have <b>multiple offensive boxes</b>, independent of frames.
They are managed in the <b>Attack</b> sub-tab.</p>

<h3>Per-box fields</h3>
<table>
  <tr><th>Field</th><th>Description</th><th>Default</th></tr>
  <tr><td><b>x / y / w / h</b></td><td>Position and size (same coordinate system as the hurtbox)</td><td>0/0/8/8</td></tr>
  <tr><td><b>Dmg</b></td><td>Damage points dealt on collision</td><td>1</td></tr>
  <tr><td><b>KB x / KB y</b></td><td>Signed knockback (−128…127) applied to the target</td><td>0</td></tr>
  <tr><td><b>Prio</b></td><td>Priority: if multiple boxes overlap, the highest priority wins</td><td>0</td></tr>
  <tr><td><b>Start</b></td><td>Starting frame of the active window in the cycle (0–3)</td><td>0</td></tr>
  <tr><td><b>Len</b></td><td>Duration of the active window in frames (0 = always active)</td><td>0</td></tr>
  <tr><td><b>Anim state</b></td><td>Animation state required for this box to be active (see below)</td><td>Any</td></tr>
</table>

<h3>Active window (Start / Len)</h3>
<p>The runtime evaluates attack boxes on a <b>4-frame cycle</b> (<code>anim_frame mod 4</code>).
<code>Start</code> and <code>Len</code> define the active range within that cycle.</p>
<ul>
  <li><code>Len=0</code>: box always active (ignores Start).</li>
  <li><code>Start=1, Len=2</code>: active at cycle frames 1 and 2 (inactive at 0 and 3).</li>
  <li>Useful for limiting the hitbox to the exact moment of the strike (the wind-up frames don't hurt).</li>
</ul>

<h3>Animation state filter (COMBAT-5)</h3>
<p>The <b>Anim state</b> field activates a box <b>only when the sprite is in a specific animation state</b>.
This avoids duplicating sprites or managing manual flags in game code.</p>
<table>
  <tr><th>Value</th><th>Runtime behaviour</th></tr>
  <tr><td><b>Any</b></td><td>Box active regardless of current state (legacy behaviour).</td></tr>
  <tr><td><b>idle / walk / run / jump / fall / land / attack / hurt / death / special / …</b></td><td>Box active only when <code>cur_anim_state == value</code>. Otherwise ignored even if the Start/Len window matches.</td></tr>
</table>
<p>Full list of available states (index 0–13):</p>
<pre>0=idle  1=walk  2=walk_left  3=walk_right  4=walk_up  5=walk_down
6=run   7=jump  8=fall       9=land       10=attack  11=hurt
12=death  13=special</pre>
<p>At runtime, <code>ngpng_attack_window_active(anim_frame, start, len, anim_state, cur_anim_state)</code>
first applies the state filter (<code>if anim_state != 0xFF &amp;&amp; anim_state != cur_anim_state → return 0</code>),
then checks the Start/Len window.</p>

<h3>Complete example — swordsman with 2 boxes</h3>
<p>A character has two offensive boxes:</p>
<ul>
  <li><b>Box 0 — low strike</b>: active in <code>attack</code> state, Start=0 Len=2, rightward knockback (KB x=4).</li>
  <li><b>Box 1 — overhead</b>: active in <code>special</code> state, Start=1 Len=1, doubled damage, upward knockback (KB y=−6).</li>
</ul>
<p>Exported result:</p>
<pre>/* attack_hitbox_anim_state[] — first box per type */
static const u8 g_hero_attack_hitbox_anim_state[1] = { 10u };  /* 10=attack */

/* attack_hitboxes_anim_state[] — all boxes flat */
static const u8 g_hero_attack_hitboxes_anim_state[2] = { 10u, 13u };  /* attack, special */</pre>

<h2>Collapsible panels</h2>
<p>The right panel of the Hitbox tab is split into <b>5 collapsible sections</b> (click the title to collapse/expand):</p>
<ul>
  <li><b>Coordinates</b>: x / y / w / h of the current box.</li>
  <li><b>Properties</b>: Physics, Combat, Misc.</li>
  <li><b>Controller</b>: ctrl.role + PAD bindings.</li>
  <li><b>Motion Patterns</b>: D-pad/button sequences (fighting-game style) + <code>_motion.h</code> export.</li>
  <li><b>Animation</b>: animation states + preview.</li>
</ul>
<p>Collapsing unused sections lets you focus on what matters without scrolling.</p>

<h2>Save to project</h2>
<p>Click <b>Save to project</b> to write both box types <em>and</em> sprite properties
into the <code>.ngpcraft</code>.
Stored under <code>sprites[].hurtboxes</code> (per frame),
<code>sprites[].hitboxes_attack_multi</code> (offensive multi-box data, with <code>active_anim_state</code>),
and <code>sprites[].props</code> (per sprite).</p>
<p><b>Checklist</b>: a small summary at the top of the right panel tells you whether the source sprite is loaded,
frame slicing is coherent, all frames have a valid hurtbox, a <code>ctrl</code> role is set, animation states are active,
and project save is possible.</p>

<h2>C export (_hitbox.h / _props.h)</h2>
<p>The export generates:</p>
<ul>
  <li><code>g_{name}_hit[]</code> — per-frame hurtboxes (<code>NgpcSprHit</code>).</li>
  <li><code>g_{name}_attack_hitbox[]</code> — first attack box per type (coords + timing).</li>
  <li><code>g_{name}_attack_hitbox_anim_state[]</code> — required anim state, first box.</li>
  <li><code>g_{name}_attack_hitboxes[]</code> — all attack boxes flat.</li>
  <li><code>g_{name}_attack_hitboxes_anim_state[]</code> — required anim states, all boxes.</li>
  <li><code>g_{name}_props</code> — <code>NgpcSprProps</code> struct (physics/combat/misc).</li>
</ul>
<pre>/* Sprite-local offsets from centre */
typedef struct &#123; s8 x; s8 y; u8 w; u8 h; &#125; NgpcSprHit;

static const NgpcSprHit g_player_hit[6] = &#123;
    &#123; -4, -8,  8, 16 &#125;,   /* frame 0 */
    ...
&#125;;</pre>

<h2>Sprite properties (Physics / Combat / Misc)</h2>
<p>A single set of values per sprite (not per frame):</p>
<table>
  <tr><th>Property</th><th>Description</th><th>Default</th></tr>
  <tr><td><b>Speed</b></td><td>Max movement speed (game units/tick)</td><td>4</td></tr>
  <tr><td><b>Weight</b></td><td>Physics mass (0=light, 255=heavy)</td><td>128</td></tr>
  <tr><td><b>Frict.</b></td><td>Surface grip (0=ice, 255=full grip)</td><td>255</td></tr>
  <tr><td><b>Jump imp.</b></td><td>Initial jump impulse. Higher value means a higher jump at the same gravity.</td><td>0</td></tr>
  <tr><td><b>HP</b></td><td>Hit points (0=invincible)</td><td>1</td></tr>
  <tr><td><b>Dmg</b></td><td>Damage on contact (0=harmless)</td><td>0</td></tr>
  <tr><td><b>I.frm</b></td><td>Invincibility frames after being hit</td><td>30</td></tr>
  <tr><td><b>Score</b></td><td>Score value ×10 on defeat (0–2550 pts)</td><td>0</td></tr>
  <tr><td><b>Anim</b></td><td>Ticks per animation frame (1–60; 0=static)</td><td>4</td></tr>
  <tr><td><b>Type</b></td><td>Entity type tag (game-defined)</td><td>0</td></tr>
  <tr><td><b>Flip dir</b></td><td>Automatically mirrors the sprite from its last X direction</td><td>0</td></tr>
</table>

<h2>Controller (ctrl.role)</h2>
<p>In the <b>Hitbox</b> tab, <code>ctrl.role</code> does not describe the sprite gameplay role.
It mainly describes <b>what kind of <code>_ctrl.h</code> the tool can prepare</b>. The <b>gameplay role</b> (player, enemy, item, block, platform...) is defined once in <b>Level</b>.</p>
<table>
  <tr><th>Value</th><th>What it means here</th></tr>
  <tr><td><b>none</b></td><td>No exportable controller. The section has no runtime effect.</td></tr>
  <tr><td><b>player</b></td><td>Shows PAD bindings and enables export of a ready-to-use <code>_ctrl.h</code> for a pad-controlled character.</td></tr>
  <tr><td><b>enemy</b></td><td>Legacy compatibility mode only. Does not define gameplay role and does not auto-create AI, movement, or attacks.</td></tr>
  <tr><td><b>npc</b></td><td>Legacy compatibility mode only. Does not define gameplay role or movement logic.</td></tr>
</table>
<p>To make a character actually move with the generated controller:</p>
<ol>
  <li>Set <code>ctrl.role=player</code>.</li>
  <li>Also configure the <b>Physics / Movement</b> fields (<code>move_type</code>, axes, speed, gravity, jump…).</li>
  <li>Use the exported <code>_ctrl.h</code> in your runtime or template.</li>
</ol>
<p><b>Where do I change the buttons?</b> Directly in <b>Hitbox &gt; Export ctrl</b> on the player sprite (Left / Right / Up / Down / Jump / Action / Accelerate / Brake). The <b>Level</b> tab does not change those buttons.</p>
<p><b>Accelerate / Brake</b>: generic buttons for any game that needs acceleration and braking actions (top-down racing, shoot'em up, etc.). Not automatically wired to ngpc_actor physics — use <code>HERO_ACCEL_HELD</code> / <code>HERO_BRAKE_HELD</code> in your code, and <code>HERO_SPEED</code> / <code>HERO_ACCEL</code> / <code>HERO_BRAKE_FORCE</code> for the values from the physics props. Leave as <b>—</b> if unused.</p>
<p><b>Brake</b> (physics prop): active braking strength when the Brake button is held. Separate from <b>Decel</b>, which applies only when the Accelerate button is released (passive slowdown). Exported as <code>HERO_BRAKE_FORCE</code> in <code>_ctrl.h</code>.</p>
<p><b>Sprint</b>: when a Sprint button is assigned, <code>CTRL_UPDATE</code> automatically switches <code>actor.speed</code> between <code>HERO_SPRINT_SPEED</code> and <code>HERO_SPEED</code>. No extra code needed.</p>
<p><b>Shoot</b>: when a Shoot button is assigned, the macro <code>HERO_SHOOT_UPDATE(actor, pool, tile, pal, timer)</code> is generated. It manages the cooldown and calls <code>ngpc_bullet_spawn</code> in the direction of <code>actor.dir_x/dir_y</code>. Bullet parameters are set in the <b>Projectiles</b> props group.</p>

<h2>move_type (player physics)</h2>
<table>
  <tr><th>Value</th><th>Behaviour</th><th>Typical use</th></tr>
  <tr><td><b>0</b></td><td>Top-down 4-direction, direct position</td><td>RPG, puzzle, twin-stick</td></tr>
  <tr><td><b>1</b></td><td>Top-down 8-direction</td><td>Top-view action</td></tr>
  <tr><td><b>2</b></td><td>Platformer: gravity + jump + accel/decel + tilemap collision</td><td>2D platformer</td></tr>
  <tr><td><b>3</b></td><td>Forced scroll (shmup)</td><td>Shoot'em up</td></tr>
</table>
<p>For <code>move_type=2</code>:</p>
<table>
  <tr><th>Prop</th><th>Role</th><th>Typical value</th></tr>
  <tr><td>max_speed</td><td>Max horizontal speed (px/frame)</td><td>2–4</td></tr>
  <tr><td>gravity</td><td>Vertical acceleration (px/frame²)</td><td>2</td></tr>
  <tr><td>jump_force</td><td>Initial jump impulse (10–14 for average jump)</td><td>10–14</td></tr>
  <tr><td>can_jump</td><td>1 = can jump, 0 = cannot</td><td>1</td></tr>
  <tr><td>max_fall_speed</td><td>Maximum fall speed</td><td>8</td></tr>
</table>
<p><b>Variable jump</b>: holding the jump button halves gravity on the way up → longer/higher jump.</p>
<p><b>Tilemap collision</b>: floor (2 feet), ceiling (SOLID only), left/right walls.
<code>TILE_SOLID=1</code> blocks from all sides. <code>TILE_ONE_WAY=2</code> supports from above only.</p>

<h2>Misc: Behavior vs Type ID</h2>
<table>
  <tr><th>Field</th><th>Actual role</th></tr>
  <tr><td><b>behavior</b></td><td>Tag exported in <code>_props.h</code>. Not automatically copied to the per-instance <b>Behavior</b> field in <b>Level</b>. In the current autorun, enemy AI mainly depends on the <b>instance Behavior</b> set in <b>Level</b>.</td></tr>
  <tr><td><b>type_id</b></td><td>Free game-defined tag exported in <code>_props.h</code>. Use it to distinguish bullet, pickup, boss, etc. Not a duplicate of <code>ctrl.role</code>.</td></tr>
  <tr><td><b>flip_x_dir</b></td><td>When set to 1, the template runtime applies <code>SPR_HFLIP</code> automatically from the last non-zero horizontal velocity.</td></tr>
</table>

<h2>Directional Frames</h2>
<p>The <b>Directional Frames</b> section lets you assign spritesheet frames to the 8 (or 4)
facing directions of a sprite — without hardware rotation (the NGPC has none).</p>
<p>You define the <b>unique</b> frames (N, NE, E, SE, S) and mirror directions (NW, W, SW)
are derived automatically by applying <code>SPR_HFLIP</code> to the opposite frame.</p>
<p><b>Frame numbering:</b> the first frame of the spritesheet is always index <b>0</b>,
then 1, 2, 3… left to right, row by row.</p>

<h3>Available modes</h3>
<ul>
  <li><b>Disabled</b> — no directional data exported (classic behaviour).</li>
  <li><b>4 directions</b> — N, E, S (W = mirror of E). For cardinal movement (basic top-down, tanks…).</li>
  <li><b>8 directions</b> — N, NE, E, SE, S + automatic mirrors. For racing, vehicles, 8-dir characters.</li>
</ul>

<h3>Direction index convention (0–7)</h3>
<p>Matches <code>ngpc_vehicle</code>:</p>
<pre>  0=E  1=NE  2=N  3=NW  4=W  5=SW  6=S  7=SE</pre>

<h3>Exported C arrays</h3>
<pre>/* 8 values per type — index: type * 8 + dir */
static const u8 g_scene_type_dir_frame[] = {
    /* car */ 2, 1, 0, 1, 2, 3, 4, 3,
};
static const u8 g_scene_type_dir_flip[] = {
    /* car */ 0, 0, 0, 1, 1, 1, 0, 0,
};
#define SCENE_HAS_DIR_FRAMES 1   /* present when at least one type is configured */</pre>

<h3>Runtime usage</h3>
<pre>u8 dir   = vehicle.dir &amp; 7;               /* 0–7 */
u8 frame = g_scene_type_dir_frame[type * 8 + dir];
u8 flip  = g_scene_type_dir_flip [type * 8 + dir] ? SPR_HFLIP : 0;
ngpc_soam_put(slot, x, y, tile_base + frame * tiles_per_frame, pal, flip);</pre>
<p>Works for any orientable entity: cars, top-down characters, 8-dir enemies, directed projectiles, etc.</p>

<h2>Animation states</h2>
<p>The <b>Animation States</b> section maps frame ranges of the spritesheet to named states
(<code>idle</code>, <code>walk</code>, <code>jump</code>, <code>hurt</code>…).
On export it generates a <code>*_anims.h</code> header:</p>
<pre>#define HERO_ANIM_IDLE  0u
#define HERO_ANIM_WALK  1u
#define HERO_ANIM_JUMP  2u
static const NgpngAnim g_hero_anims[HERO_ANIM_COUNT] = {
    { 0, 1, 1, 8 },  /* idle: frame 0, count 1, loop, spd 8 */
    { 1, 4, 1, 6 },  /* walk */
    { 5, 2, 0, 4 },  /* jump (one-shot) */
};</pre>
<p>State names are fixed (14 runtime states). Enabling a state in the editor includes it in the export. The attack box <b>Anim state</b> field refers to the same indices.</p>

<h2>Animation preview (▶)</h2>
<p>Every enabled state has a <b>▶</b> button in the right-most column.
Click it to play that state's frames on the hitbox canvas in real time.</p>
<ul>
  <li>Click <b>⏹</b> (same button) to stop.</li>
  <li>Manual navigation with <b>◀ / ▶</b> (or ←/→) also stops the preview.</li>
  <li>Loading a new sprite stops any running preview automatically.</li>
</ul>
<p><b>Speed</b>: driven by the state's <b>Spd</b> field (ticks at 60 fps —
<code>spd=6</code> ≈ 10 fps, <code>spd=1</code> = 60 fps).</p>
<p><b>Non-loop</b>: preview stops automatically on the last frame.</p>

<h2>Animated thumbnails in the rail — A-2</h2>
<p>Rail thumbnails on the left animate automatically when the sprite has an <code>idle</code>, <code>walk</code>, or <code>run</code> state defined with <b>Count &gt; 1</b>.
The speed matches the state's <b>Spd</b> field. Timers stop as soon as you change scene or rebuild the rail.</p>

<h2>Named animations (ngpc_anim) — A-1</h2>
<p>In addition to the fixed states above, you can define <b>custom named animation sequences</b>
compatible with the optional <code>ngpc_anim</code> module. These are saved in the <code>.ngpcraft</code>
and exported via the <b>Export _namedanims.h</b> button.</p>
<table border="1" cellpadding="3" cellspacing="0">
<tr><th>Column</th><th>Description</th></tr>
<tr><td><b>Name</b></td><td>C identifier suffix (e.g. <code>walk_cycle</code>) → variable <code>anim_SPRITE_walk_cycle</code></td></tr>
<tr><td><b>Frames</b></td><td>Comma-separated frame indices (e.g. <code>0, 1, 2, 3</code>) — 0-based</td></tr>
<tr><td><b>Speed</b></td><td>NGPC ticks per anim frame: 1=60 fps, 4=15 fps, 6=10 fps, 8=7.5 fps</td></tr>
<tr><td><b>Mode</b></td><td><code>loop</code> | <code>pingpong</code> | <code>oneshot</code></td></tr>
</table>
<p>Example generated header:</p>
<pre>static const u8 hero_walk_cycle_frames[] = { 0u, 1u, 2u, 3u };
static const NgpcAnimDef anim_hero_walk_cycle = ANIM_DEF(hero_walk_cycle_frames, 4u, 4u, ANIM_LOOP);</pre>
<p>Usage in your code:</p>
<pre>#include "ngpc_anim.h"
#include "hero_namedanims.h"

NgpcAnim anim;
ngpc_anim_play(&amp;anim, &amp;anim_hero_walk_cycle);  /* in init */

/* Each frame: */
ngpc_anim_update(&amp;anim);
ngpc_sprite_set(slot, x, y, TILE_BASE + ngpc_anim_tile(&amp;anim), pal, flags);</pre>

<h2>Motion Patterns (ngpc_motion)</h2>
<p>The <b>Motion Patterns</b> panel maps D-pad + button sequences (fighting-game style) to animation states.
Requires the optional module <code>optional/ngpc_motion/</code>.</p>

<h3>Table columns</h3>
<table>
  <tr><th>Column</th><th>Description</th></tr>
  <tr><td><b>Name</b></td><td>C identifier for the pattern (e.g. <code>QCF_A</code>) → <code>#define HERO_PAT_QCF_A 0u</code></td></tr>
  <tr><td><b>Steps</b></td><td>Space-separated direction/button sequence (see notation below)</td></tr>
  <tr><td><b>Win</b></td><td>Maximum frame window for the whole pattern to be valid (4–120; default 20)</td></tr>
  <tr><td><b>→ Anim</b></td><td>Animation state to trigger automatically (<code>special</code>, <code>attack</code>…) — leave blank to handle in game code</td></tr>
</table>

<h3>Step notation</h3>
<table>
  <tr><th>Token</th><th>Meaning</th></tr>
  <tr><td><code>N</code></td><td>Neutral (no direction)</td></tr>
  <tr><td><code>U D L R</code></td><td>Up / Down / Left / Right</td></tr>
  <tr><td><code>UR UL DR DL</code></td><td>Diagonals</td></tr>
  <tr><td><code>*</code></td><td>Wildcard — any direction accepted</td></tr>
  <tr><td><code>+A +B +OPT</code></td><td>Button required on this step (combinable: <code>DR+A</code>, <code>R+A+B</code>)</td></tr>
</table>
<p>Examples:</p>
<pre>D DR R+A     → Quarter-circle → + A  (Hadouken)
R D DR+A     → Dragon Punch + A  (Shoryuken)
R N R        → Double-tap → (forward dash)
* *+B        → Any direction, then any direction + B</pre>

<h3>Preset button</h3>
<p>The <b>Preset ▾</b> button inserts ready-to-use patterns: QCF, QCB, Dragon Punch, Double-tap ←/→.</p>

<h3>Generated header (<code>_motion.h</code>)</h3>
<p>Click <b>Export _motion.h</b> to generate:</p>
<pre>#include "ngpc_motion/ngpc_motion.h"
#include "hero_anims.h"           /* if at least one pattern has a → Anim */

static const u8 NGP_FAR _hero_qcf_a_s[] = { MDIR_D, MDIR_DR, MDIR_R|MBTN_A };
#define HERO_PAT_QCF_A   0u
#define HERO_PAT_COUNT   1u

static const NgpcMotionPattern NGP_FAR g_hero_patterns[HERO_PAT_COUNT] = {
    { _hero_qcf_a_s, 3u, 20u }   /* QCF_A */
};

static const u8 NGP_FAR g_hero_pat_anim[HERO_PAT_COUNT] = {
    HERO_ANIM_SPECIAL   /* QCF_A → special */
};</pre>
<p>Usage in your code:</p>
<pre>static NgpcMotionBuf hero_motion;
ngpc_motion_init(&amp;hero_motion);   // game_init()

// game_update():
ngpc_motion_push(&amp;hero_motion, ngpc_pad_held, ngpc_pad_pressed);
u8 pat = ngpc_motion_scan(&amp;hero_motion, g_hero_patterns, HERO_PAT_COUNT);
if (pat != 0xFF) {
    ngpc_motion_clear(&amp;hero_motion);
    u8 anim = g_hero_pat_anim[pat];
    if (anim != 0xFF) ngpc_anim_play(&amp;hero_anim, &amp;g_hero_anims[anim]);
}</pre>
<p><b>RAM:</b> 34 bytes per entity (<code>NgpcMotionBuf</code>). Step arrays and pattern table are ROM data (NGP_FAR).</p>

<h2>Contextual display — why some fields disappear</h2>
<p>The Hitbox tab shows <b>only the parameters relevant</b> to the current entity type.
If you open an enemy sprite, jump and PAD controller fields are automatically hidden.
No data is deleted — hidden fields are simply collapsed.</p>

<h3>Physics profiles (auto-detected)</h3>
<table>
  <tr><th>Profile</th><th>Trigger condition</th><th>Fields shown</th></tr>
  <tr><td><b>Platformer / Jump</b></td><td><code>move_type=2</code> or platformer scene</td><td>Jump force, gravity, max fall speed, accel/decel, friction</td></tr>
  <tr><td><b>Top-down 4/8 dir</b></td><td>Top-down props present, RPG/tactical scene, or dir frames</td><td>Speed, axis X/Y, flip dir</td></tr>
  <tr><td><b>Top-down vehicle</b></td><td><code>td_move=2</code> or race scene</td><td>Full top-down block (td_speed_max, td_accel, td_brake…)</td></tr>
  <tr><td><b>Forced scroll</b></td><td><code>move_type=3</code> or shmup scene</td><td>Axis X/Y only</td></tr>
  <tr><td><b>No physics</b></td><td>No physics properties configured, static entity</td><td>Info banner (physics params remain accessible)</td></tr>
</table>

<h3>Role profiles (auto-detected)</h3>
<table>
  <tr><th>Role</th><th>Condition</th><th>Sections enabled</th></tr>
  <tr><td><b>Player</b></td><td><code>ctrl.role=player</code> or <code>gameplay_role=player</code></td><td>PAD controller + full physics + combat</td></tr>
  <tr><td><b>Enemy</b></td><td><code>gameplay_role=enemy</code></td><td>Combat, hurtbox, HP, damage</td></tr>
  <tr><td><b>NPC</b></td><td><code>gameplay_role=npc</code></td><td>Combat only if HP/damage configured</td></tr>
  <tr><td><b>Prop / Decor</b></td><td>No explicit role</td><td>Hurtbox only, no combat (unless data present)</td></tr>
</table>

<h2>Quick setup and context override</h2>
<p>At the top of the right panel, a compact row lets you <b>force the display context</b> when auto-detection is not sufficient:</p>
<ul>
  <li><b>Quick setup…</b>: opens a dialog with ready-to-use presets (Player Platformer, Player Shmup, Player Top-down, Player Vehicle, Enemy, NPC, Prop/Decor). Selecting a preset instantly adjusts which sections are visible. <b>No numeric values are changed.</b></li>
  <li><b>Role combo</b>: force the role profile (Player, Enemy, NPC, Prop). Default = Auto.</li>
  <li><b>Physics combo</b>: force the physics profile (Platformer/Jump, Top-down, Vehicle, Scroll, None). Default = Auto.</li>
</ul>
<p>When an axis is set to Auto, the automatic deduction applies. Any non-Auto value overrides the auto-detection. The forced context is saved in <code>sprite_meta["display_hint"]</code> with the sprite — it is reloaded automatically next time.</p>
<p><b>When to use the override?</b> Mainly on newly created sprites (no <code>ctrl.role</code> or props configured yet), or when a general-purpose sprite needs to show specific fields.</p>

<h2>Advanced fields and pipeline badges</h2>
<p>The <b>Show advanced fields</b> button (in the panel) expands the <b>Advanced</b> group and reveals less-common fields:</p>
<table>
  <tr><th>Field</th><th>Why it's in Advanced</th></tr>
  <tr><td><b>Weight</b></td><td>Rarely adjusted — the default behaviour covers most cases</td></tr>
  <tr><td><b>Gravity direction</b></td><td>Only relevant for games with reversed gravity</td></tr>
  <tr><td><b>AI tag</b> (behavior)</td><td>Sprite metadata only — actual AI behaviour is configured in Level</td></tr>
  <tr><td><b>Type ID</b></td><td>Free tag for your runtime, rarely needed from the Hitbox side</td></tr>
</table>
<p>In advanced mode, <b>coloured badges</b> appear to the right of each field to show which pipeline consumes the value.
Hover over a badge for a full explanation:</p>
<table>
  <tr><th>Badge</th><th>Colour</th><th>Meaning</th></tr>
  <tr><td><b>CTRL</b></td><td>Dark green</td><td>Goes into <code>_ctrl.h</code> — player controller. Shared by all instances.</td></tr>
  <tr><td><b>PROPS</b></td><td>Brown-orange</td><td>Compiled into ROM in <code>_props.h</code> — static data per sprite type.</td></tr>
  <tr><td><b>SCENE</b></td><td>Blue</td><td>Stored in the scene file — can differ per instance in Level.</td></tr>
  <tr><td><b>TAG</b></td><td>Grey</td><td>Metadata only — does not directly affect runtime physics.</td></tr>
</table>
<p>Badges do not affect saving or export — they are purely informational.</p>

<h2>Tips</h2>
<ul>
  <li><b>Standard centred hitbox</b>: 16×16 sprite → <code>x=−8, y=−8, w=16, h=16</code>. Tight shmup ship: <code>x=−3, y=−3, w=6, h=6</code>.</li>
  <li><b>Always-active attack box</b>: set <code>Len=0</code> and <b>Anim state = Any</b>.</li>
  <li><b>Strike that only hurts at one moment</b>: <code>Start=1, Len=1</code> on a 4-frame animation cycle.</li>
  <li><b>Two different strikes on the same sprite</b>: create two boxes with different <b>Anim state</b> values (e.g. <code>attack</code> and <code>special</code>). The runtime filters automatically.</li>
  <li><b>Pattern with no → Anim</b>: leave the column blank — no dispatch table generated, handle it with a <code>switch(pat)</code>.</li>
  <li><b>Right panel too cluttered?</b> Collapse the Controller, Motion Patterns, and Animation sections if you are only editing hurtboxes.</li>
  <li><b>New sprite with no context?</b> Click <b>Quick setup…</b> and choose the type — the display adjusts instantly.</li>
  <li><b>Expected field missing?</b> Open the <b>Advanced</b> group or force the Physics/Role with the combos at the top of the panel.</li>
</ul>
"""


def _en_level_editor() -> str:
    return """
<h1>Level Editor</h1>

<h2>Purpose</h2>
<p>The <b>Level</b> tab lets you place entities on an 8×8 tile grid, manage <b>waves</b>,
and generate a <b>collision map</b> using Procgen.</p>
<p><b>Sizes (NGPC)</b>: the visible screen is 20×19 tiles (160×152 px) and the hardware BG map is limited to 32×32 tiles (256×256 px).
The tool now shows this reminder next to the <b>Size</b> field.</p>
<p><b>Game profile</b>: the <b>Profile</b> selector applies quick presets (map mode, scroll/loop, default sizes) depending on the genre:
<b>Platformer</b>, <b>Vertical Shmup</b>, <b>Top-down open world</b>, <b>Metroidvania</b>, <b>Dungeon floor</b>, <b>RPG tactical</b>,
<b>Arcade score</b>, <b>Fighting</b>, <b>Beat 'em up</b>, <b>Run'n gun</b>, and <b>Roguelite (room-by-room)</b>.
You can still override everything manually afterwards.</p>
<p><b>Splitters</b>: in the <b>Waves</b> and <b>Procgen</b> tabs, you can resize the top/bottom areas (and the size is saved).</p>
<p><b>Diagnostics</b>: a panel lists useful scene warnings (missing player, missing/invalid col_map, incomplete Procgen visual mapping, camera outside the map, invalid regions/paths, broken triggers…). It also adds <b>profile-guided hints</b>: for example a <i>Shmup</i> without forced scroll, a <i>Fighting</i> setup without Lock Y, or a <i>Beat 'em up</i> without Ground band.</p>
<p><b>Checklist</b>: just above it, a small checklist quickly tells you what is or is not ready for <b>testing</b> / <b>export</b>: blocking diagnostics, camera/bounds, scene references (regions, paths, triggers), main player actor, export symbol, Procgen PNG mapping, then profile hints.</p>
<p><b>Scene tools</b>: the toolbar above the canvas now makes the modes explicit: <b>Select</b>, <b>Entity</b>, <b>Wave</b>, <b>Region</b>, <b>Path</b>, and <b>Camera</b>. Editing therefore feels much closer to a real object editor instead of a plain grid with hidden edit modes in the side panels.</p>
<p><b>Overlays</b>: a dedicated row also lets you show/hide <b>Collision</b>, <b>Regions</b>, <b>Triggers</b>, <b>Paths</b>, <b>Waves</b>, <b>Camera</b>, and the <b>NGPC bezel</b>, so the canvas is easier to read when several systems overlap.</p>
<p><b>Interface</b>: the top of the canvas is now split into <b>View</b> and <b>Scene editing</b> blocks, so zoom/undo controls are more clearly separated from tools and overlays.</p>

<h2>Keyboard shortcuts — Canvas</h2>
<table>
<tr><th>Key</th><th>Action</th></tr>
<tr><td><b>S</b></td><td>Select tool</td></tr>
<tr><td><b>E</b></td><td>Entity tool (placement)</td></tr>
<tr><td><b>W</b></td><td>Wave tool</td></tr>
<tr><td><b>R</b></td><td>Region tool</td></tr>
<tr><td><b>P</b></td><td>Path tool</td></tr>
<tr><td><b>C</b></td><td>Camera tool</td></tr>
<tr><td><b>G</b></td><td>Collision tool (tile painting)</td></tr>
<tr><td><b>Esc</b></td><td>Back to Select</td></tr>
<tr><td><b>+</b> / <b>=</b></td><td>Zoom in (next step)</td></tr>
<tr><td><b>-</b></td><td>Zoom out (previous step)</td></tr>
<tr><td><b>F</b></td><td>Fit to BG (fit zoom to background)</td></tr>
<tr><td><b>F5</b></td><td>Export scene → .h</td></tr>
<tr><td><b>Delete</b></td><td>Delete active selection</td></tr>
<tr><td><b>Arrow keys</b></td><td>Nudge selection by 1 tile</td></tr>
<tr><td><b>Shift + Arrow keys</b></td><td>Nudge selection by 4 tiles</td></tr>
<tr><td><b>Ctrl+Z</b></td><td>Undo</td></tr>
<tr><td><b>Ctrl+Y</b></td><td>Redo</td></tr>
<tr><td><b>Ctrl+D</b></td><td>Duplicate active selection</td></tr>
<tr><td><b>Ctrl+E</b></td><td>Export scene → .h</td></tr>
<tr><td><b>Ctrl+0</b></td><td>Fit to BG (keyboard)</td></tr>
</table>

<h2>Keyboard shortcuts — Side panels</h2>
<p>These shortcuts only fire when the corresponding list has keyboard focus (click it or use Tab).</p>
<table>
<tr><th>List</th><th>Key</th><th>Action</th></tr>
<tr><td><b>Waves</b></td><td>Insert</td><td>Add a wave</td></tr>
<tr><td><b>Waves</b></td><td>Delete</td><td>Delete selected wave</td></tr>
<tr><td><b>Waves</b></td><td>Ctrl+D</td><td>Duplicate selected wave</td></tr>
<tr><td><b>Regions</b></td><td>Insert</td><td>Add a region</td></tr>
<tr><td><b>Regions</b></td><td>Delete</td><td>Delete selected region</td></tr>
<tr><td><b>Triggers</b></td><td>Insert</td><td>Add a trigger</td></tr>
<tr><td><b>Triggers</b></td><td>Delete</td><td>Delete selected trigger</td></tr>
<tr><td><b>Triggers</b></td><td>Ctrl+D</td><td>Duplicate selected trigger</td></tr>
</table>

<h2>Mouse</h2>
<ul>
  <li><b>Left click</b>: depends on the active tool (selection, placement, region, path, camera…).</li>
  <li><b>Drag</b>: move an entity (static or wave).</li>
  <li><b>Right click</b>: delete the element under the cursor.</li>
  <li><b>Ctrl+click+drag</b>: move the camera (Cam X/Y) — blue “CAM” rectangle.</li>
  <li><b>Ctrl+wheel</b>: zoom in/out.</li>
</ul>

<h2>Background (BG SCR1/SCR2) — how to load a tilemap</h2>
<p>The <b>BG SCR1</b> and <b>BG SCR2</b> drop-downs are populated from the scene's tilemap list.
To make a tilemap appear in them:</p>
<ol>
  <li>Go to the <b>Projet</b> tab → select the scene → <b>Tilemaps</b> section.</li>
  <li>Add your PNG via the <b>+</b> button. Each PNG added there then appears in both Level drop-downs.</li>
  <li>Come back to <b>Level</b>: select the right PNG in <b>BG SCR1</b> and/or <b>BG SCR2</b>.</li>
</ol>
<p><b>Single tilemap</b>: select it on SCR1. If matching <code>_scr1.png</code> / <code>_scr2.png</code>
variants exist next to it, the preview loads the correct one automatically.</p>
<p><b>Two layers (SCR1 + SCR2)</b>: add two separate PNGs in Projet, then pick each one in BG SCR1 and BG SCR2.
The <b>Front</b> selector controls which plane renders in front (editor preview — set this in your runtime code too).</p>
<p><b>Large tilemap (&gt;32×32 tiles)</b>: same workflow — add it in Projet, select it on SCR1.
A cyan viewport overlay (📺) appears with <b>Cam X/Y</b> spinners to preview different zones of the map.
At export, VRAM streaming (<code>scene_X_stream_planes()</code>) is generated automatically — no extra code needed.</p>
<p><b>Procgen</b> can also (optionally) <b>generate SCR1/SCR2 tilemap PNGs</b> from the collision map:
the tool creates new files, adds them to the scene <code>tilemaps[]</code> list, and selects them as BG.</p>

<h2>Layout (camera / scroll)</h2>
<p>The <b>Layout</b> tab stores runtime-friendly metadata: camera start (tile coordinates), scroll axes,
forced scroll (speed), and loop options. Export writes them as <code>#define</code> in <code>_scene.h</code>.</p>
<p>You can also set a <b>Camera mode</b> (fixed screen, follow, forced scroll, segments/arenas, loop) and <b>bounds</b> (clamp) to document the intended level structure.</p>
<p><b>Layout presets</b> now add a faster entry point than the old camera-mode helper alone: they apply a reusable genre-oriented starter (<b>single-screen menu</b>, <b>platformer follow</b>, <b>platformer room lock</b>, <b>run'n gun horizontal</b>, <b>vertical shmup</b>, <b>top-down room</b>) and fill camera, scroll, loop, and follow comfort values together.</p>
<p><b>Painted collision (col_map)</b>: the scene <b>Collision</b> tool is no longer limited to a plain brush. You can now switch between
<b>Brush</b>, <b>Rect</b>, and <b>Fill</b> in the dedicated row above the canvas. <b>Right click</b> still writes <code>PASS</code>,
and <b>Ctrl+click</b> acts as an eyedropper to reuse the collision type under the cursor. This is useful to lay down ground quickly, flood an empty area,
or patch a scene-local collision export without going back to the global tileset collision mapping.</p>
<p><b>Import BG → col_map</b>: in the same row, the <b>Import BG</b> button can rebuild the <b>Level</b> collision map from one of the scene tilemaps
(`BG auto`, <code>SCR1</code>, or <code>SCR2</code>). This is intentionally an <b>explicit import</b>, not a permanent sync: you start from the collision authored in
<b>Tilemap</b>, then apply local <code>col_map</code> overrides when needed. The import replaces the current <code>col_map</code>, but it remains undo-safe.</p>
<p><b>Build-ready export</b>: even without a manual import, the template-ready export can now also rebuild the scene collision automatically from the linked BG tilemap when that tilemap already stores painted collision. Manual import is still the right tool when you want visible local overrides inside <b>Level</b>.</p>
<p><b>Source summary</b>: right below that row, <b>Level</b> now shows whether the visible collision comes from a
<b>scene-local col_map</b> or from an <b>imported tilemap base</b>. When the imported source is still available, the tool also reports how many
<b>local cells</b> currently differ from that base. This makes the workflow explicit: <i>Tilemap collision -> explicit import -> local overrides</i>.</p>
<p><b>Planes / parallax</b>: you can also define SCR1/SCR2 parallax (X/Y in %) and which plane is in front (BG_FRONT).
Those are <b>exported metadata</b>: your runtime decides how to interpret them.</p>
<p><b>s16 overflow on large maps (PERF-PAR-1):</b> a naive <code>cam_py * pct</code> overflows s16 when <code>cam_py &gt; 327 px</code> (≈ 41 tiles).
The template autorun uses <code>ngpng_scale_pct(v, pct)</code> which divides first (q = v/100, r = v%100 → q×pct + r×pct/100) to stay in range.
If you write custom parallax code, use the same pattern — or keep map height ≤ 41 tiles when vertical parallax is active.
The Level tab Diagnostics panel shows a hint when this combination is detected.</p>

<h2>Palette cycling — X-1 (ngpc_palfx)</h2>
<p><b>What is it?</b> Palette cycling <em>loops</em> the 3 colors of a palette to create animated visual effects
without changing any tiles or writing code: rippling water, pulsing lava, blinking lights, rainbows, etc.
The tiles themselves never change — only their colors shift each frame.</p>
<p><b>How it works:</b> An NGPC palette has 4 colors (0–3). Color 0 is reserved (transparency for sprites,
background color for scroll planes). Cycling rotates only <b>colors 1, 2 and 3</b> in sequence:
1→2→3→1→2→3… every <em>N</em> frames. Lower speed = faster animation (1 = fastest, ~60 cycles/sec).</p>
<p><b>Concrete example:</b> your lava tilemap uses SCR1 / Palette 3 with three orange-red shades.
Add a row: Plane=SCR1, Pal=3, Speed=4 → the lava pulses on its own at ~15 cycles/sec.</p>
<p>The <b>Palette cycling</b> section is in <b>Level → Layout</b>. Each row = one active cycle for
this scene. Columns: <b>Plane</b> (SCR1 / SCR2 / SPR), <b>Pal</b> (0–15), <b>Speed</b> (frames per
color shift — 1=very fast, 8=slow).</p>
<p>At export, <code>ngpng_palfx_enter(scene_idx)</code> is generated automatically and called at every
scene enter (startup, game-over, warp, checkpoint). <code>ngpc_palfx_update()</code> is added to the main loop.</p>
<p><b>Requirement:</b> the module <code>src/fx/ngpc_palfx.h</code> must be present in the template.</p>
<pre>/* Generated example — lava on SCR1/Pal2, water on SPR/Pal1 */
static void ngpng_palfx_enter(u8 scene_idx)
{
    ngpc_palfx_stop_all();
    if (scene_idx == 0u) {
        ngpc_palfx_cycle(GFX_SCR1, 2u, 4u);  /* lava  : fast */
        ngpc_palfx_cycle(GFX_SPR,  1u, 8u);  /* water : slow */
    }
}</pre>

<h2>OAM viewer — X-3</h2>
<p>The <b>OAM</b> tab in the Level editor right panel shows the NGPC hardware sprite composition in worst-case:
all static entities <em>and</em> all wave entities active simultaneously.</p>
<p>Each 8×8 tile = 1 OAM hardware slot. A 16×16 sprite = 4 slots, 32×16 = 8 slots, etc.
The NGPC hardware has a maximum of <b>64 slots</b>.</p>
<ul>
  <li><b>16×4 grid</b>: color-coded by role — green (player), red (enemy), yellow (item), blue (npc), purple (prop).</li>
  <li><b>Total badge</b>: <code>X / 64</code> in green/orange/red depending on usage.</li>
  <li><b>Table</b>: allocated slot(s), type, dimensions, HW parts count.</li>
</ul>
<p><b>Note:</b> the viewer only counts project entities — it does not include FX sprites (explosions, bullets) or HUD sprites.
Add those manually if you have them.</p>

<h2>Roles</h2>
<p>Each entity type (left list) can be assigned a role: <code>player</code>, <code>enemy</code>,
<code>item</code>, <code>npc</code>, <code>trigger</code>, <code>block</code>, <code>platform</code>, <code>prop</code>.
Procgen uses those roles to place entities automatically.</p>
<p><b>Current autorun:</b> static entities with role <code>item</code> are collected on player overlap.
Score comes from <code>score</code>, optional healing from <code>hp</code>, and <code>data</code> can be used as a simple multiplier.</p>
<p><b>Blocks V1:</b> a static entity with role <code>block</code> reacts when the player hits it from below.
Use <code>data=0</code> for bump-only, <code>data=1</code> for breakable, and <code>data=2</code> for a one-shot item block.</p>
<p><b>Placement presets:</b> in the left column, right below <b>Gameplay role</b>, a <b>Starter</b> row prepares the next placement of the current type without replacing the normal workflow.
Leave <code>(none)</code> for plain placement. Once a preset is selected, it applies when you click in the scene, and the <b>Place</b> button drops the configured entity directly at the center of the current view.
<b>Important:</b> this does not define runtime spawn, camera start, or start scene. Typical uses: player ground spawn, enemy patrol left/right, breakable block, collectible x10, or a moving platform. For the moving-platform starter, if no <code>Path</code> exists yet, the tool creates a minimal demo path and links it automatically.</p>
<p><b>Behavior + AI Parameters:</b> for enemies, the instance <code>behavior</code> field controls the movement mode:
<code>patrol</code> walks and turns at walls/edges, <code>chase</code> follows the player horizontally, <code>fixed</code> stays in place, and <code>random</code> wanders.
Selecting an enemy on the canvas automatically reveals an <b>AI Parameters</b> panel below the instance props with contextual spinboxes:
<code>Speed</code> (px/frame, shown for patrol / chase / random), <code>Aggro range</code> + <code>Lose range</code> (×8 px, shown for chase only), and <code>Dir. change</code> (frames between random direction flips, shown for random only).
These values only generate parallel C tables when needed — default values produce no extra code.
Enemies also die on <code>DAMAGE</code> / <code>FIRE</code> / <code>VOID</code> tiles and can be <b>stomped</b> if the player lands on top of them.</p>
<p><b>Data (u8)</b>: per-entity free byte (0–255), exported as-is in <code>_scene.h</code>.
Examples: enemy variant, item ID, event parameter, direction, etc.</p>
<p><b>Clamp to map</b>: each instance can also enable this flag so the template-ready runtime clamps it to world bounds. This is useful for a player or enemy that must never leave the map, without forcing the same rule on every type.</p>
<p><b>Respawn on re-entry</b>: when the <b>Activation radius</b> is enabled in Project Settings (value &gt; 0), this per-entity flag allows a killed entity to <b>respawn</b> when the camera re-enters its zone after having left it. Without this flag, a killed enemy stays dead for the entire session. Useful for farming zones, corridor guards, filler mobs, or any gameplay where density should remain constant. <b>Collected items</b> never respawn, regardless of this flag.</p>

<h2>World Activation (activation radius)</h2>
<p>Setting in <b>Project Settings</b> (top of the project panel): <b>Activation radius (tiles)</b>. Value 0 = disabled.</p>
<p>When enabled, only enemies within a given radius around the camera are actually updated each frame.
Enemies outside the radius are <b>frozen</b> (not updated, not drawn) but remain in memory.
When the camera returns to their zone, they reappear at their initial position.</p>
<ul>
  <li><b>0</b>: disabled — all scene enemies run every frame (default behavior)</li>
  <li><b>6–10</b>: recommended — enemies stay active 48–80 px beyond the screen edge, which feels credible gameplay-wise</li>
  <li><b>16</b>: maximum — enemies are almost always active even on large maps</li>
</ul>
<p>The performance gain is significant: a scene with 6 enemies where only 2–3 are visible will only run 2–3 AI logic loops per frame instead of 6. The proximity scan costs ~60 cycles (6 simple comparisons) — negligible.</p>
<p><b>On death:</b> a killed enemy is marked <code>DEAD</code>. Without the <b>Respawn</b> flag, it never comes back. With it, it resets to <code>ALIVE</code> as soon as the camera leaves its zone — so the player must genuinely leave and return to trigger the respawn (no instant on-the-spot re-spawning).</p>
<p><b>Technical note:</b> the radius is a compile-time constant (<code>NGPNG_ACTIVATION_RADIUS_TILES</code>), guaranteeing minimal runtime cost on NGPC.</p>

<h2>Rules (constraints)</h2>
<p>The <b>Rules</b> tab mainly helps with <b>editor placement</b>. By itself, it does not give enemies smart runtime behavior.</p>
<ul>
  <li><b>Lock Y</b>: when you place or drag an entity, its Y is forced to one fixed row. Good for fighting games or horizontal menus.</li>
  <li><b>Ground band</b>: when you place or drag an entity, its Y stays inside a <code>[min..max]</code> range. Good for brawlers with fake depth.</li>
  <li><b>Mirror X</b>: when you place one entity, the editor also creates its mirrored copy on the other side of the X axis. Good for symmetric arenas or duel setups.</li>
  <li><b>Apply to waves</b>: decides whether those constraints also affect entities placed in the Waves tab.</li>
</ul>
<p><b>Important:</b> these constraints do <b>not animate</b> entities, do <b>not assign a path</b>, and do <b>not move anything by themselves in-game</b>. They mostly change how things are placed in the editor. Export also writes them to <code>_scene.h</code> as <b>metadata</b> that your runtime may use, or ignore.</p>
<p>Quick examples: <b>fighting</b> = Lock Y only; <b>brawler</b> = Ground band; <b>symmetric arena</b> = Mirror X; <b>shmup</b> = usually no Rules here, prefer <b>Waves</b> and sometimes <b>Paths</b>.</p>
<p><b>Platformer autorun:</b> the <b>Rules</b> block also drives several native preview/export behaviors:
tile damage (<code>DAMAGE</code>, <code>FIRE</code>, <code>VOID</code>), springs, and ladder logic
(<code>High ladder exit</code>, <code>Horizontal ladder movement</code>, <code>Semi-solid ladder top</code>).
In the current autorun, <code>FIRE</code> is a passable hazard, not a solid floor.</p>

<h2>Waves</h2>
<ul>
  <li>Add waves, set their <b>delay</b> (frames), then enable <b>Edit wave</b>.</li>
  <li>In wave mode, clicks place entities into the current wave (instead of the static placement list).</li>
</ul>
<p><b>Wave presets:</b> the <b>Preset</b> block also creates reusable starter formations: <b>Line x3</b>, <b>V x5</b>, and <b>Ground pair</b>. The tool first uses the currently selected entity type; otherwise it falls back to the first type marked <b>enemy</b>.</p>

<h2>Regions</h2>
<p>The <b>Regions</b> tab defines tile rectangles inside the scene.
Enable <b>Edit regions</b>, then <b>drag</b> on the grid to draw a rectangle.
Regions are exported to C (<code>NgpngRegion</code>: x, y, w, h, kind).</p>
<p><b>Available kinds:</b> <b>zone</b> (purple, generic), <b>no_spawn</b> (orange, Procgen-excluded),
<b>danger_zone</b> (red, hazard), <b>checkpoint</b> (green, native respawn),
<b>exit_goal</b> (yellow, native exit), <b>camera_lock</b> (blue, camera clamp),
<b>spawn</b> (cyan, <code>warp_to</code> target),
<b>attractor</b> (force toward center), <b>repulsor</b> (force away from center).</p>
<p><b>Region presets:</b> the <b>Preset</b> block also creates useful starters from the current camera view: <b>Checkpoint 4x4</b>, <b>Safe no-spawn zone</b>, and <b>Hazard floor</b>. They are meant as quick bases for tests, triggers, and hazards.</p>

<h2>Triggers</h2>
<p>The <b>Triggers</b> tab maps <b>conditions</b> to <b>actions</b>.
<b>87 conditions</b> including 18 entity-type conditions (regions, camera thresholds, timer, waves, buttons, health, enemies, flags, variables, player states, physics, entity type…) and
<b>73 actions</b> (audio, spawn, scroll, shake, scene transitions, anim, flags/variables, teleport, fade, inventory…) + OR groups.</p>
<p>Key features: <b>⧉ Dup</b> (duplicate a trigger), <b>AND conditions</b> (multiple simultaneous conditions), <b>OR groups</b> (alternative condition sets), <b>once</b> (fires only once).</p>
<p>The <b>entity type conditions</b> (<code>entity_type_*</code>) are detailed in the <b>Globals</b> topic.</p>
<p>→ <b>Full reference (all conditions, actions, exports, patterns): see the <i>Triggers &amp; Regions</i> topic</b></p>

<h2>Paths</h2>
<p>The <b>Paths</b> tab defines routes (a list of points in tile coordinates) for NPC patrols, shmup rails, etc.
Enable <b>Edit paths</b> then click on the grid to add points. <b>Drag</b> a point to move it;
<b>right click</b> or <b>Delete</b> removes a point. Paths are exported as C arrays (offsets/lengths/flags + points).</p>
<ul>
  <li><b>Who follows the path?</b> Only entities you assign to that path from the <b>Entity</b> tab, using <b>Patrol path</b>. Drawing a path alone does nothing.</li>
  <li><b>Easier assignment</b>: you can also select a path and use the <b>Assign to selected entity</b> button directly in the <b>Paths</b> tab.</li>
  <li><b>When does it start?</b> The editor describes the route and exports one path index per entity. The exact start timing depends on your runtime. A common choice is to activate it on spawn.</li>
  <li><b>What happens at the end?</b> If <b>Loop</b> is enabled, it goes back to the first point. Otherwise the route ends on the last point and your runtime decides what happens next.</li>
  <li><b>Important</b>: a path is not an autonomous animation. It is a list of points your runtime may interpret as a route.</li>
</ul>
<p><b>Template shipped with the tool:</b> for static enemies, the <b>Path</b> field is now used directly on spawn. Without loop, the enemy leaves the path at the end and resumes the template's default movement.</p>

<h2>Text Labels (sysfont)</h2>
<p>The <b>Text Labels</b> tab lets you place static text on the scene, rendered via the NGPC BIOS system font (<code>ngpc_text_print</code>).</p>
<ul>
  <li><b>Add</b>: creates a new empty label. <b>Remove</b>: deletes the selected label.</li>
  <li><b>Text</b>: ASCII string, max 20 characters.</li>
  <li><b>X / Y</b>: position in tiles (X: 0–19, Y: 0–18).</li>
  <li><b>Palette</b>: BG color index (0–3; 0 = default sysfont white/black).</li>
  <li><b>Plane</b>: <code>SCR1</code> or <code>SCR2</code> — the scroll plane on which to display the text.</li>
</ul>
<p><b>Editor rendering:</b> labels are displayed as green text on a semi-transparent black rect on the canvas. The selected label has a yellow outline.</p>
<p><b>C export:</b> when the scene has at least one label, the generator emits in <code>scene_*_level.h</code>:</p>
<ul>
  <li><code>#define {SYM}_TEXT_LABEL_COUNT N</code></li>
  <li><code>g_{sym}_text_label_x[]</code>, <code>g_{sym}_text_label_y[]</code>, <code>g_{sym}_text_label_pal[]</code>, <code>g_{sym}_text_label_plane[]</code></li>
  <li><code>const char * const g_{sym}_text_labels[]</code></li>
</ul>
<p>And in the generated <code>scene_xxx_load_all()</code> loader:</p>
<pre><code>#if SCENE_TEXT_LABEL_COUNT &gt; 0
for (u8 i = 0; i &lt; SCENE_TEXT_LABEL_COUNT; i++)
    ngpc_text_print(g_text_label_plane[i], g_text_label_pal[i],
                    g_text_label_x[i], g_text_label_y[i], g_text_labels[i]);
#endif</code></pre>
<p>⚠ Text labels are <b>static</b>: they are written once when the scene loads. For dynamic text (score, HP…), call <code>ngpc_text_print</code> directly from your runtime.</p>

<h2>data (u8)</h2>
<p>The <b>data (u8)</b> field is intentionally generic: it is a free byte (0–255) exported to
the entity as-is. Typical uses: enemy variant, script ID, spawn direction, trigger parameter,
item type, etc.</p>

<h2>Procgen (collision map)</h2>
<p>Procgen can generate a collision grid (<b>u8 per tile</b>) depending on a <b>map mode</b>:
platformer, top-down, shmup, open field, or none (actors only).</p>
<ul>
  <li>The <b>Collision</b> toggle displays a colored overlay per collision type (SOLID, ONE_WAY, DAMAGE, LADDER…).</li>
  <li>In top-down mode, <b>Directional walls</b> can convert some walls into <code>WALL_N/S/E/W</code> faces.</li>
  <li><b>Role → visual tile</b>: maps each collision role to a tile index (0–255)
      so you can export a visual tile map alongside collision. This index is from your <b>tileset</b>
      (it is not a VRAM <code>tile_base</code>).</li>
  <li><b>Visual variants</b>: use <b>Choose...</b> to select one or several tiles visually. The numbers shown under each thumbnail are the actual IDs used by Procgen. Manual input like <code>12,13,14</code> still works if you already know the atlas.</li>
  <li><b>Preview / source</b>: both the preview and the picker use the Procgen <b>Tile source</b> (Auto, SCR1, or SCR2). If the result looks wrong, check that source first.</li>
</ul>
<p><b>Important:</b> <code>WATER</code>, <code>FIRE</code>, <code>VOID</code>, <code>DOOR</code>, and <code>SPRING</code> remain <b>collision categories</b>. Damage, instant death, and rebound are now configured in <b>Level &gt; Rules</b>, while scene transitions still belong to runtime/triggers.</p>
<p>For purely decorative visuals, mainly use variants of a passable role (<b>Empty / air</b>, <b>Walkable</b>) or a separate BG plane. Procgen describes <b>collision first</b>, then the associated visual dressing.</p>

<h2>Save to project</h2>
<p><b>Save to project</b> updates the scene inside the <code>.ngpcraft</code> file:</p>
<pre>scenes[].entities
scenes[].waves
scenes[].regions
scenes[].triggers
scenes[].paths
scenes[].entity_roles
scenes[].level_profile
scenes[].level_size
scenes[].map_mode
scenes[].level_bg_scr1
scenes[].level_bg_scr2
scenes[].level_bg_front
scenes[].level_cam_tile
scenes[].level_scroll
scenes[].level_layout
scenes[].level_layers
scenes[].level_rules
scenes[].col_map
scenes[].tile_ids
scenes[].neighbors
scenes[].bg_chunk_map</pre>

<h2>Neighbouring scenes — edge warps (Track B)</h2>
<p>The <b>Neighbouring scenes</b> panel in the <b>Layout</b> tab links up to 4 adjacent scenes
(North / South / West / East). When a neighbour is set, the export automatically generates:</p>
<ul>
  <li>An 8-px <b>exit region</b> on the corresponding edge (kind <code>zone</code>).</li>
  <li>An <b>entry spawn</b> at a fixed slot in the target scene (W=slot 0, E=1, N=2, S=3).</li>
  <li>A <b><code>warp_to</code> trigger</b> pointing to the target scene and the correct entry spawn (opposite slot).</li>
</ul>
<p><b>Trigger zone:</b> the exit region covers <em>the entire edge</em> — full width for North/South,
full height for East/West. It is not possible to restrict the warp to a portion of an edge via this panel.
If you need a warp on only part of an edge (e.g. a door), use a manual region (<b>Region → zone</b>)
and a <code>warp_to</code> trigger placed at the exact location in the <b>Triggers</b> tab instead.</p>
<p><b>Key constraint:</b> spawn slots 0–3 in the target scene are reserved for auto-entry.
Your manually placed spawns start at index 4.</p>
<p><b>How to use:</b></p>
<ol>
  <li>In <b>Level → Layout</b>, pick the neighbouring scene from the dropdown for the desired direction.</li>
  <li>Save to project.</li>
  <li>No runtime changes required: everything is built on the existing <code>warp_to</code> + <code>spawn_points</code> system.</li>
</ol>
<p>Validation flags any target scene that cannot be found in the project.</p>

<h2>Chunk Map SCR1 — assembled large map (Track A)</h2>
<p>The <b>Chunk Map SCR1</b> panel in the <b>BG</b> tab lets you assemble several small tilemap PNGs
into a single large <code>g_{name}_bg_map[]</code> ROM array, bypassing the 32×32-tile hardware limit.</p>
<ul>
  <li>Set the <b>Rows × Cols</b> grid of chunks (up to 8×8).</li>
  <li>Select the matching tilemap PNG in each cell (from the scene's tilemaps list).</li>
  <li>All chunks in the same column must share the <b>same height in tiles</b>.</li>
  <li>The JSON field saved is <code>bg_chunk_map.grid</code>: a list-of-lists of relative PNG paths.</li>
</ul>
<p><b>At export:</b> chunks are assembled row-major into a single array. Macros
<code>SCENE_X_CHUNK_MAP_W/H</code> give the total dimensions (in tiles) to pass to
<code>ngpc_mapstream_init()</code>. SCR1 is automatically handled by <code>ngpc_mapstream</code>
(<code>scr1_by_mapstream = true</code> is forced).</p>
<p><b>Constraint:</b> chunks must first appear in the scene's <b>Tilemaps</b> list before they show
up in the dropdowns. Add them from the <b>Project</b> tab first.</p>

<h2>C export: <code>_scene.h</code></h2>
<p>The export generates a complete header: entity IDs, hitboxes/props, static placement, wave tables,
and when a map exists: <code>g_&lt;scene&gt;_tilecol</code> + <code>g_&lt;scene&gt;_tilemap_ids</code>.</p>
<p>The header now also exports genre/map metadata:
<code>SCENE_*_PROFILE</code>, <code>SCENE_*_MAP_MODE</code>, and several <code>SCENE_*_PROFILE_*_HINT</code>
defines so a runtime can branch more easily from the <b>Profile</b> chosen in the editor.</p>
<p>The exported format is now the same whether you use the local <b>Level</b> export, the <b>Project</b> tab export, or headless export.</p>

<hr/>

<h2>Step-by-step workflow</h2>
<ol>
  <li><b>Project tab</b>: add your <b>sprites</b> and <b>tilemaps</b> to the scene (and set the <code>scr1/scr2</code> plane if needed).</li>
  <li><b>Level</b>: set the room <b>Size</b> (W×H) in tiles. Use <b>Fit BG</b> if you start from a 32×32 tilemap.</li>
  <li><b>Roles</b>: assign a role per type (player/enemy/item…) so Procgen knows what to place.</li>
  <li><b>Manual placement</b>: place key entities (player, important points), or let Procgen do it.</li>
  <li><b>Procgen</b>: pick a <b>map mode</b>, adjust seed/margin/densities, then click <b>Generate</b>.</li>
  <li><b>(Optional) Tilemap PNGs</b>: enable <b>Generate tilemap PNGs</b> to output SCR1/SCR2 maps from <code>col_map</code>.</li>
  <li><b>Layout</b>: configure camera/scroll/forced/loop/bounds as runtime metadata.</li>
  <li><b>Save to project</b>: writes everything into the <code>.ngpcraft</code>.</li>
  <li><b>Export (Project → Scene → .c)</b>: exports sprites + tilemaps + headers, including <code>scene_&lt;name&gt;_level.h</code>.</li>
</ol>

<h2>Full UI tour</h2>
<ul>
  <li><b>Top/center bar</b>: BG SCR1 / BG SCR2 / Front / Size / Fit BG / Zoom / toggles (Bezel, Cam, col_map) / Undo-Redo.</li>
  <li><b>Canvas</b>: draws BG(s) at their real pixel size (only scaled by zoom) + collision overlay + entities.</li>
  <li><b>Left</b>: types list (scene sprites) + role assignment.</li>
  <li><b>Right</b>: tabs (Waves, Procgen, Layout, Planes/parallax, Rules, Diagnostics, Regions, Triggers, Paths) depending on your build.</li>
</ul>

<h2>Layout (details)</h2>
<ul>
  <li><b>Cam start</b>: initial camera position in tiles (shown by the “CAM” rectangle, movable with Ctrl+drag).</li>
  <li><b>Scroll X/Y</b>: indicates which axes the camera is allowed to move on (metadata).</li>
  <li><b>Forced scroll</b>: automatic scrolling with <b>speed_x/speed_y</b> (units are interpreted by your runtime).</li>
  <li><b>Loop X/Y</b>: documents looping levels (useful for shmups). The preview can tile the BG to make loops readable.</li>
  <li><b>Camera mode</b>: <i>single_screen</i>, <i>follow</i>, <i>forced_scroll</i>, <i>segments</i>, <i>loop</i> (exported as <code>CAM_MODE</code>).</li>
  <li><b>Bounds / clamp</b>: camera min/max in tiles. In “auto”, bounds are derived from map size.</li>
</ul>

<h2>Rules (details)</h2>
<ul>
  <li><b>Lock Y</b>: forces Y to a constant value (fighting).</li>
  <li><b>Ground band</b>: clamps Y to a [min..max] band (brawler).</li>
  <li><b>Mirror X</b>: also places a mirrored copy around an axis (duels/arenas).</li>
  <li><b>Apply to waves</b>: enables/disables Rules when placing entities in wave edit mode.</li>
</ul>

<h2>Regions / Triggers / Paths (details)</h2>
<ul>
  <li><b>Regions</b>: rectangles in tile coords. <code>no_spawn</code> blocks Procgen. <code>danger_zone</code> = runtime hazard.</li>
  <li><b>Triggers</b>: 87 conditions × 73 actions + OR groups (incl. 18 entity-type conditions). See <b>Triggers &amp; Regions</b> and <b>Globals</b> topics.</li>
  <li><b>Paths</b>: routes made of tile points (patrols, rails). <b>Loop</b> closes the route.</li>
</ul>

<h2>Procgen: key points</h2>
<ul>
  <li><b>Placement</b>: when <code>col_map</code> exists, Procgen only places on <code>TILE_PASS</code> tiles (and respects <i>no-spawn</i> regions + Rules).</li>
  <li><b>Multi-tile sprites</b>: e.g. a 16×16 sprite occupies 2×2 tiles. Procgen checks the footprint to avoid overlaps and blocked tiles.</li>
  <li><b>Role → visual tile</b>: this is a <b>tile index inside an atlas image</b> (0–255). It is <b>not</b> a VRAM slot. In the UI, prefer <b>Choose...</b> so you can see the tiles and their IDs directly.</li>
  <li><b>Special roles</b>: water, fire, void, door are categories; exact gameplay remains runtime-defined.</li>
</ul>

<h2>Collision types (reminder)</h2>
<p><code>col_map</code> uses constants compatible with <code>ngpc_tilecol.h</code> (when present):</p>
<ul>
  <li><b>PASS</b>: empty/passable.</li>
  <li><b>SOLID</b>: solid floor/wall.</li>
  <li><b>ONE_WAY</b>: one-way platform (platformer).</li>
  <li><b>DAMAGE</b>: hazard (spikes, lava…).</li>
  <li><b>LADDER</b>: ladder (platformer).</li>
  <li><b>SPRING</b>: scene-configurable launcher / bounce tile (force + direction).</li>
  <li><b>WALL_N/S/E/W</b>: directional walls (top-down).</li>
  <li><b>WATER / FIRE / VOID / DOOR</b>: “special” types (your game decides how to interpret them). In the current autorun, <b>FIRE</b> hurts but stays traversable.</li>
</ul>

<h2>Procgen → tilemap PNGs: coherence and limits</h2>
<ul>
  <li>The generated PNG is <b>visually</b> coherent (it copies 8×8 tiles from the source atlas). Tilemap export may deduplicate/reorder tiles in VRAM afterwards: that is expected.</li>
  <li>If you want a “logical” runtime map, use <code>g_&lt;scene&gt;_tilecol</code> (collision) + <code>g_&lt;scene&gt;_tilemap_ids</code> (IDs) and interpret them in your own code.</li>
  <li>Tip: reserve stable atlas tiles for gameplay roles (floor, wall, water, door…) so the mapping stays consistent.</li>
</ul>

<h2>Quick genre examples</h2>
<ul>
  <li><b>Fighting</b>: Rules → <i>Lock Y</i> + <i>Mirror X</i> (axis), map mode = none.</li>
  <li><b>Platformer</b>: map_mode=platformer, collision overlay ON, ONE_WAY/LADDER, cam mode=follow.</li>
  <li><b>Run &amp; Gun</b>: forced_scroll OFF, scroll_x ON, waves for spawns, regions/triggers for scripting.</li>
  <li><b>Shmup</b>: cam mode=forced_scroll, loop_y ON, waves + paths (rails) for patterns.</li>
  <li><b>Top-down RPG</b>: map_mode=topdown (+ dir walls), regions for zones, triggers for transitions/doors.</li>
</ul>

<h2>Troubleshooting (common issues)</h2>
<ul>
  <li><b>Procgen: “No valid positions”</b>: margin is too large, or the generated map leaves too few <code>TILE_PASS</code> tiles. Reduce margin/obstacle density or switch mode.</li>
  <li><b>Procgen: weird placements</b>: check <b>roles</b> (player/enemy/item). Without roles, Procgen cannot categorize types.</li>
  <li><b>Overlapping entities</b>: big sprites need space. Procgen avoids overlaps, but manual placement can create them.</li>
  <li><b>Tilemap PNGs: “needs a BG PNG”</b>: select a BG SCR1 or SCR2, or set “Tile source” to Auto.</li>
  <li><b>Tilemap PNGs: unexpected look</b>: “Role → visual tile” points to the wrong tile index in the atlas. Fix indices and regenerate.</li>
  <li><b>BG preview differs from export</b>: tilemap export may generate <code>_scr1/_scr2</code> variants (dual-layer). Make sure you reference the correct files/plane.</li>
</ul>

<h2>Runtime procgen — Dungeon DFS and Cave sub-tabs</h2>
<p>The <b>Procgen</b> tab now has <b>three sub-tabs</b>:</p>
<ul>
  <li><b>Design Map</b> — existing design-time generation (BSP, scatter, etc.). Produces a static <code>col_map</code> exported to C.</li>
  <li><b>Dungeon DFS</b> — configures the <code>ngpc_procgen</code> module for <em>in-game runtime</em> dungeon generation.</li>
  <li><b>Cave</b> — configures the <code>ngpc_cavegen</code> module (32×32 cellular automaton cave) for <em>runtime</em> generation.</li>
</ul>
<p><b>Per-scene activation:</b> each sub-tab (Dungeon DFS and Cave) has a <b>master checkbox</b> at the top
(<i>Enable Dungeon DFS runtime generation for this scene</i> / <i>Enable Cave runtime generation for this scene</i>).
While unchecked, all parameters are grayed out and <b>nothing is saved or exported</b> for that module.
Checking the box enables the parameters and includes them in the <code>.ngpcraft</code> on next save.</p>

<h2>Dungeon DFS sub-tab — runtime parameters</h2>
<p>Configures <code>ngpc_procgen</code> (recursive DFS on an N×M grid of rooms).</p>
<table>
  <tr><th>Parameter</th><th>Range</th><th>Description</th><th>→ <code>#define</code></th></tr>
  <tr><td>Grid W / H</td><td>2–8</td><td>Room grid dimensions. RAM: ~72 B base + W×H bytes.</td><td><code>PROCGEN_GRID_W/H</code></td></tr>
  <tr><td>Max enemies per room</td><td>0–12</td><td>Maximum enemies placed per room during generation.</td><td><code>PROCGEN_MAX_ENEMIES</code></td></tr>
  <tr><td>Item chance</td><td>0–100 %</td><td>Probability that an item spawns in a room.</td><td><code>PROCGEN_ITEM_CHANCE</code></td></tr>
  <tr><td>Loop injection</td><td>0–80 %</td><td>Extra corridors added after DFS to create loops. 0 = pure tree dungeon.</td><td><code>PROCGEN_LOOP_PCT</code></td></tr>
  <tr><td>Max active enemies</td><td>1–40</td><td>Global cap on simultaneously live enemies across all rooms.</td><td><code>PROCGEN_MAX_ACTIVE</code></td></tr>
  <tr><td>Player start mode</td><td>3 options</td><td>Corner (0,0) / Random room / Furthest from exit.</td><td><code>PROCGEN_START_MODE</code></td></tr>
</table>
<p><b>Difficulty tier table (5 tiers):</b> each column is a difficulty level (tier = <code>FLOOR / 5</code>, clamped to 4).
The 4 rows are: max enemies, item chance%, loop pct%, max active.
Values are editable directly in the table.</p>
<p><b>Multi-floor:</b> check <i>Enable multi-floor</i> to activate progression parameters:</p>
<ul>
  <li><b>Floor variable index (0–7)</b>: which <code>game_vars[]</code> slot tracks the current floor number.</li>
  <li><b>Max floors (0 = infinite)</b>: when exceeded, redirect to the boss/end scene.</li>
  <li><b>Boss/end scene</b>: scene to go to when <code>FLOOR ≥ max_floors</code>.</li>
  <li><b>Reload scene</b>: target scene for the next floor (blank = self-reload).</li>
</ul>
<p><b>Export button:</b> writes <code>GraphX/gen/procgen_config.h</code> with all <code>#define</code>s and tier macros. Include it <em>before</em> <code>ngpc_procgen.h</code> in your C code.</p>

<h2>Cave sub-tab — runtime parameters</h2>
<p>Configures <code>ngpc_cavegen</code> (32×32 cellular automaton cave, 1 024 bytes RAM).</p>
<table>
  <tr><th>Parameter</th><th>Range</th><th>Description</th><th>→ <code>#define</code></th></tr>
  <tr><td>Initial wall %</td><td>30–70 %</td><td>Initial wall seed density. 40–50% = organic caves, &gt;55% = narrow corridors.</td><td><code>CAVEGEN_WALL_PCT</code></td></tr>
  <tr><td>CA iterations</td><td>1–10</td><td>Smoothing passes. More = rounder caves, heavier init cost.</td><td><code>CAVEGEN_ITERATIONS</code></td></tr>
  <tr><td>Max enemies</td><td>0–16</td><td>Enemies placed in open floor cells.</td><td><code>CAVEGEN_MAX_ENEMIES</code></td></tr>
  <tr><td>Max items</td><td>0–8</td><td>Item pickups placed directly on the floor — the procgen spawns the <em>pickup</em> entity type with the sprite from the item pool.</td><td><code>CAVEGEN_MAX_ITEMS</code></td></tr>
  <tr><td>Pickup entity type index</td><td>0–255</td><td>Index of the generic "pickup" entity type (role <code>item</code>). Used by the runtime to spawn items. Its sprite is overridden by <code>g_item_table[idx].sprite_id</code>.</td><td><code>CAVEGEN_PICKUP_TYPE</code></td></tr>
</table>
<p><b>Difficulty tier table (5 tiers):</b> 3 rows × 5 columns (wall%, max enemies, max items per tier).</p>
<p><b>Multi-floor:</b> same as DFS — floor variable, max floors, boss/end scene.</p>
<p><b>Export button:</b> writes <code>GraphX/gen/cavegen_config.h</code>. Include it <em>before</em> <code>ngpc_cavegen.h</code>.</p>

<h2>Per-scene parameter persistence</h2>
<p>All three sub-tab parameters (Design Map, Dungeon DFS, Cave) are saved <b>per scene</b> in the <code>.ngpcraft</code> file:</p>
<pre>scenes[].procgen_params    ← Design Map (seed, mode, densities…)
scenes[].rt_dfs_params     ← Dungeon DFS (grid, tiers, multi-floor…)  — only when enabled
scenes[].rt_cave_params    ← Cave (wall_pct, iterations, tiers, multi-floor…) — only when enabled</pre>
<p><b>Important:</b> <code>rt_dfs_params</code> and <code>rt_cave_params</code> are only written to the JSON
<em>when the sub-tab's master checkbox is checked</em>.
Unchecking and saving removes the key from the <code>.ngpcraft</code>.
The project export pipeline (<b>Export project</b> in the Project tab) only generates
<code>procgen_config.h</code> / <code>cavegen_config.h</code> for scenes where the module is enabled.</p>
<p>Switching scenes automatically restores the checkbox state and matching parameters.
The <b>⧉ Duplicate scene</b> button (Project tab) deep-copies all procgen parameters and their activation state.</p>

<h2>C integration — procgen_config.h</h2>
<pre>#include "GraphX/gen/procgen_config.h"  /* before ngpc_procgen.h */
#include "ngpc_procgen.h"

static ProcgenMap g_dungeon;

void game_init(void) {
    u8 floor = ngpc_gv_get_var(PROCGEN_FLOOR_VAR);
    u8 tier  = (floor / 5u &gt; 4u) ? 4u : floor / 5u;
    u8 mx_e  = PROCGEN_TIER_MAX_ENEMIES[tier];
    u8 lp    = PROCGEN_TIER_LOOP_PCT[tier];
    ngpc_procgen_generate_ex(&amp;g_dungeon, ngpc_rng_next(),
                             PROCGEN_GRID_W, PROCGEN_GRID_H, lp);
    ngpc_procgen_gen_content(&amp;g_dungeon, mx_e,
                             PROCGEN_TIER_ITEM_CHANCE[tier]);
}
</pre>
"""


def _en_palette_bank() -> str:
    return """
<h1>VRAM Palette Bank (sprite slots)</h1>

<h2>Overview</h2>
<p>In the <b>VRAM Map</b> tab, the <i>Sprites (16)</i> section now displays
a rich <b>16-slot palette bank</b> instead of a plain coloured bar.</p>

<h2>What each slot shows</h2>
<table>
  <tr><th>Element</th><th>Description</th></tr>
  <tr><td>Slot number</td><td>Index 0–15 in the hardware sprite palette bank</td></tr>
  <tr><td>4 colour swatches</td><td>The 4 palette colours (index 0 = transparent = dark square)</td></tr>
  <tr><td>Badge <b>×N</b></td><td>Shown in yellow when N sprites share this slot via <code>--fixed-palette</code></td></tr>
  <tr><td>Dark slot</td><td>Free slot (not used by the current scene)</td></tr>
</table>

<h2>Tooltip</h2>
<p>Hover over a slot to see the name(s) of the owning sprite(s).</p>

<h2>Click → Open in Palette</h2>
<p>Click on an occupied slot to <b>switch directly to the Palette tab</b>
with that sprite loaded. Handy for inspecting or editing colours without
navigating manually.</p>

<h2>Shared palettes (<code>fixed_palette</code>)</h2>
<p>When several sprites share the same palette (configured via the Palette tab
or <code>--fixed-palette</code> in the pipeline), they occupy the <b>same slot</b>
and the <b>×N</b> badge shows how many sprites share it.</p>

<h2>Colour sources</h2>
<ul>
  <li>If the sprite has a <code>fixed_palette</code> field in the project: the displayed
      colours match that palette exactly.</li>
  <li>Otherwise: colours are extracted from the source PNG (RGB444 quantization).</li>
</ul>
"""


# ---------------------------------------------------------------------------
# Templates de projet — FR / EN
# ---------------------------------------------------------------------------

def _fr_project_templates() -> str:
    return """
<h1>Templates de projet</h1>
<p>Le wizard de création (<b>Nouveau projet</b>) propose trois templates :</p>

<h2>Projet vierge</h2>
<p>Un <code>.ngpcraft</code> minimal avec une scène vide. Idéal pour partir de zéro avec vos propres assets.</p>

<h2>Exemple Shmup</h2>
<p>Démo jouable de shoot'em up avec :</p>
<ul>
  <li>Joueur (vaisseau, 2 variantes) avec contrôle clavier et tir</li>
  <li>3 types d'ennemis avec 6 patterns de mouvement (data=0..5)</li>
  <li>9 vagues espacées pour garantir l'overlap visuel</li>
  <li>Scroll forcé, 2 plans parallax, triggers de score</li>
  <li>BGM (song_01) + 7 SFX (explosion, tir, menu…)</li>
  <li>Flash save : meilleur score persistant</li>
</ul>
<p><b>Assets bundlés</b> dans le tool — aucune dépendance externe.</p>

<h2>Exemple Platformer</h2>
<p>Démo jouable de platformer 2D avec :</p>
<ul>
  <li>Héro avec physique complète (<code>move_type=2</code>) : gravité, saut variable, accel/decel</li>
  <li>Collision tilemap sol (2 pieds) + murs + plafond</li>
  <li>Camera follow centrée sur le joueur</li>
  <li>6 plateformes (SOLID et ONE_WAY), slimes ennemis</li>
  <li>Triggers de score (zones intermédiaire + finale)</li>
</ul>
<p><b>Sprites générés programmatiquement</b> (PIL) — remplacez-les par votre art.</p>

<h2>Workflow depuis un projet vierge</h2>
<p>Toutes les mécaniques (physique, waves, collision, flash save) sont générées à l'export selon la configuration du projet — <b>elles fonctionnent depuis n'importe quelle origine</b>.</p>
<ol>
  <li>Créer un projet vierge (ou votre propre structure)</li>
  <li>Ajouter vos sprites dans l'onglet <b>Projet</b></li>
  <li>Configurer <b>ctrl.role</b> + <b>move_type</b> + props dans <b>Hitbox</b></li>
  <li>Définir les entités, vagues et col_map dans <b>Level</b></li>
  <li>Exporter → le code C est généré automatiquement</li>
</ol>

<h2>Scène statique vs monde chunké</h2>
<p>Choisissez le modèle qui correspond à votre jeu :</p>
<table>
  <tr><th>Critère</th><th>Scènes statiques</th><th>Monde chunké (ngpc_mapstream)</th></tr>
  <tr><td>Taille map</td><td>≤ 32×32 tiles (512 KB ROM)</td><td>Jusqu'à 256×256 tiles (FAR ROM)</td></tr>
  <tr><td>Nombre de tiles</td><td>≤ 256 tiles distincts</td><td>≤ 256 tiles (même limite hardware)</td></tr>
  <tr><td>RAM utilisée</td><td>Zéro buffer streaming</td><td>~200 octets (colonne courante)</td></tr>
  <tr><td>Vitesse scroll</td><td>Instantané — copie VRAM VBlank</td><td>1 colonne/frame max (streaming VBlank)</td></tr>
  <tr><td>Transitions</td><td>goto_scene / warp_to</td><td>Scroll continu sans rechargement</td></tr>
  <tr><td>Entités / waves</td><td>Complètes (n'importe quelle densité)</td><td>À gérer manuellement (pas d'autorun natif sur grande map)</td></tr>
  <tr><td>Cas d'usage</td><td>Shmup, platformer 1 écran, menu, RPG salle par salle</td><td>Grand monde ouvert, donjon multi-salles sans transition</td></tr>
</table>

<p><b>Règle pratique :</b> commencez toujours avec des <b>scènes statiques</b>.
Passez au monde chunké uniquement si votre niveau ne tient pas dans 32×32 tiles.
Un jeu entier peut être fait avec 10–20 scènes statiques — c'est le chemin le moins risqué sur NGPC.</p>

<p><b>Budget tiles (avertissements PNG Manager) :</b></p>
<ul>
  <li>≤ 256 tiles distincts — ✓ OK</li>
  <li>257–320 — ⚠ attention, tiles déduplication critique</li>
  <li>321–384 — 🔶 fort risque de dépassement VRAM</li>
  <li>&gt; 384 — 🔴 dépassement certain (512 slots VRAM, dont 128 réservés)</li>
</ul>
"""


def _en_project_templates() -> str:
    return """
<h1>Project Templates</h1>
<p>The creation wizard (<b>New Project</b>) offers three templates:</p>

<h2>Blank project</h2>
<p>A minimal <code>.ngpcraft</code> with an empty scene. Best when starting from scratch with your own assets.</p>

<h2>Shmup example</h2>
<p>A playable shoot'em up demo featuring:</p>
<ul>
  <li>Player ship (2 variants) with keyboard control and shooting</li>
  <li>3 enemy types with 6 movement patterns (data=0..5)</li>
  <li>9 waves timed to guarantee visual overlap</li>
  <li>Forced scroll, 2 parallax planes, score triggers</li>
  <li>BGM (song_01) + 7 SFX (explosion, shoot, menu…)</li>
  <li>Flash save: persistent best score</li>
</ul>
<p><b>Assets bundled</b> in the tool — no external dependency.</p>

<h2>Platformer example</h2>
<p>A playable 2D platformer demo featuring:</p>
<ul>
  <li>Hero with full physics (<code>move_type=2</code>): gravity, variable jump, accel/decel</li>
  <li>Tilemap collision: floor (2-foot check) + walls + ceiling</li>
  <li>Camera follow centered on the player</li>
  <li>6 platforms (SOLID and ONE_WAY), slime enemies</li>
  <li>Score triggers (mid and finish zones)</li>
</ul>
<p><b>Sprites generated programmatically</b> (PIL) — replace with your own art.</p>

<h2>Workflow from a blank project</h2>
<p>All mechanics (physics, waves, collision, flash save) are generated at export time from the project configuration — <b>they work regardless of project origin</b>.</p>
<ol>
  <li>Create a blank project (or use your own structure)</li>
  <li>Add your sprites in the <b>Project</b> tab</li>
  <li>Configure <b>ctrl.role</b> + <b>move_type</b> + props in <b>Hitbox</b></li>
  <li>Define entities, waves and col_map in <b>Level</b></li>
  <li>Export → C code is generated automatically</li>
</ol>

<h2>Static scene vs chunked world</h2>
<p>Choose the model that fits your game:</p>
<table>
  <tr><th>Criterion</th><th>Static scenes</th><th>Chunked world (ngpc_mapstream)</th></tr>
  <tr><td>Map size</td><td>≤ 32×32 tiles (512 KB ROM)</td><td>Up to 256×256 tiles (FAR ROM)</td></tr>
  <tr><td>Distinct tiles</td><td>≤ 256 tiles</td><td>≤ 256 tiles (same hardware limit)</td></tr>
  <tr><td>RAM used</td><td>Zero streaming buffer</td><td>~200 bytes (current column)</td></tr>
  <tr><td>Scroll speed</td><td>Instant — VRAM copy during VBlank</td><td>1 column/frame max (VBlank streaming)</td></tr>
  <tr><td>Transitions</td><td>goto_scene / warp_to</td><td>Continuous scroll without reload</td></tr>
  <tr><td>Entities / waves</td><td>Full support (any density)</td><td>Manual management (no native autorun on large map)</td></tr>
  <tr><td>Use case</td><td>Shmup, 1-screen platformer, menu, room-by-room RPG</td><td>Open world, multi-room dungeon without loading screens</td></tr>
</table>

<p><b>Practical rule:</b> always start with <b>static scenes</b>.
Switch to a chunked world only when your level cannot fit in 32×32 tiles.
A full game can be built with 10–20 static scenes — it is the safest path on NGPC.</p>

<p><b>Tile budget warnings (PNG Manager):</b></p>
<ul>
  <li>≤ 256 distinct tiles — ✓ OK</li>
  <li>257–320 — ⚠ caution, tile deduplication critical</li>
  <li>321–384 — 🔶 high overflow risk</li>
  <li>&gt; 384 — 🔴 certain overflow (512 VRAM slots, 128 reserved)</li>
</ul>
"""


# ---------------------------------------------------------------------------
# Physique & IA ennemis — FR / EN
# ---------------------------------------------------------------------------

def _fr_physics_ai() -> str:
    return """
<h1>Physique joueur &amp; IA ennemis</h1>

<h2>Physique joueur (move_type=2)</h2>
<p>Configurer <code>move_type=2</code> sur un sprite joueur dans l'onglet <b>Hitbox</b>
génère un contrôleur complet à l'export. L'ordre des opérations par frame :</p>
<ol>
  <li>Calcul vx (accel/decel depuis input)</li>
  <li>Gravité (variable : ½ si bouton saut maintenu à la montée)</li>
  <li>Saut (si on_ground + bouton pressé)</li>
  <li>Déplacement horizontal → collision murs</li>
  <li>Déplacement vertical → collision plafond puis sol</li>
  <li>Camera follow (centre à screen_x=80)</li>
</ol>

<h3>Collision tilemap</h3>
<table>
  <tr><th>Type</th><th>Valeur</th><th>Comportement</th></tr>
  <tr><td>TILE_PASS</td><td>0</td><td>Traversable</td></tr>
  <tr><td>TILE_SOLID</td><td>1</td><td>Bloque tous côtés (sol, murs, plafond)</td></tr>
  <tr><td>TILE_ONE_WAY</td><td>2</td><td>Sol seulement — on peut sauter à travers par le bas</td></tr>
</table>
<p>La détection de sol utilise <b>2 points de pied</b> (gauche + droite, à 2px du bord chaque côté).
Le joueur reste sur une plateforme tant qu'au moins un pied la touche.</p>

<h2>IA ennemis — implémenté</h2>

<h3>Patterns de mouvement (champ data)</h3>
<table>
  <tr><th>data</th><th>Nom</th><th>Comportement</th></tr>
  <tr><td>0</td><td>straight</td><td>Droit vers la gauche (vx=−2)</td></tr>
  <tr><td>1</td><td>drift_down</td><td>Dérive vers le bas (vy=+1, rebondit y=16/136)</td></tr>
  <tr><td>2</td><td>drift_up</td><td>Dérive vers le haut (vy=−1)</td></tr>
  <tr><td>3</td><td>alt_y</td><td>Alterne selon parité du Y de spawn</td></tr>
  <tr><td>4</td><td>zigzag</td><td>Flip vy toutes les 16 frames (anim counter)</td></tr>
  <tr><td>5</td><td>fast</td><td>vx=−4, ligne droite</td></tr>
  <tr><td>6</td><td>patrol</td><td>Va-et-vient : flip vx toutes les 48 frames</td></tr>
  <tr><td>7</td><td>aggro+patrol</td><td>Patrouille + chase si joueur &lt;5 tiles (40px)</td></tr>
</table>
<p>Si la scène a des <b>paths</b> et <code>data &gt; 0</code>, l'ennemi suit le path <code>data−1</code> (ignore les règles ci-dessus).</p>

<h3>Comportement IA par instance (TRIG-7)</h3>
<p>Pour chaque ennemi posé dans la scène, le panneau <b>Paramètres IA</b> apparaît automatiquement sous les props d'instance quand le comportement n'est pas <code>fixed</code> :</p>
<table>
  <tr><th>Paramètre</th><th>Mode(s)</th><th>Plage</th><th>Défaut</th><th>Notes</th></tr>
  <tr><td><b>Vitesse</b></td><td>patrol, chase, random</td><td>1–255 px/frame</td><td>1</td><td>Exporté si ≥1 entité ≠ 1</td></tr>
  <tr><td><b>Portée aggro</b></td><td>chase</td><td>0–255 (×8 px)</td><td>10 (80 px)</td><td>Rayon joueur → ennemi déclenche chase</td></tr>
  <tr><td><b>Portée perte</b></td><td>chase</td><td>0–255 (×8 px)</td><td>16 (128 px)</td><td>Rayon au-delà duquel le chase s'arrête</td></tr>
  <tr><td><b>Chg. direction</b></td><td>random</td><td>1–255 frames</td><td>60</td><td>Fréquence changement direction aléatoire</td></tr>
</table>
<p>Les tables C ne sont émises que si le mode concerné est utilisé : <code>g_{sym}_ent_ai_speed[]</code> si une vitesse ≠ 1 existe, <code>g_{sym}_ent_ai_range/lose_range[]</code> si au moins un ennemi est en mode chase, <code>g_{sym}_ent_ai_change_every[]</code> si au moins un ennemi est en mode random.
Chaque table est accompagnée de son define de guard (<code>SCENE_ENTITY_AI_SPEED_TABLE 1</code>, etc.) pour conditionner le code runtime.</p>
<p><b>Règle portée :</b> aggro &lt; perte pour éviter le "flickering" (l'ennemi ne commence à chasser que si le joueur est proche, et n'abandonne que s'il s'est suffisamment éloigné).</p>

<h3>Gravité ennemis (prop <code>gravity</code>)</h3>
<p>La propriété <b>gravity</b> dans le Hitbox tab s'applique aussi aux ennemis :</p>
<ul>
  <li><code>gravity=0</code> (défaut) → ennemi shmup-style (rebondit aux bords, pas de sol)</li>
  <li><code>gravity=2</code> → ennemi platformer (chute, detection sol tilecol, <code>on_ground</code>)</li>
</ul>
<p>La valeur est exportée dans <code>g_*_type_gravity[]</code> et lue par <code>ngpng_enemies_update</code>.
Max fall speed plafonné à 6 (anti-tunneling, tuiles de 8px).</p>

<h3>SFX gameplay (platformer)</h3>
<table>
  <tr><th>Événement</th><th>SFX index</th><th>Condition</th></tr>
  <tr><td>Saut</td><td>1 (tir/blip)</td><td>jump_buf déclenché, si NGPNG_SFX_COUNT &gt; 1</td></tr>
  <tr><td>Atterrissage</td><td>2 (menu_move)</td><td>vy &gt; 2 à l'impact, si NGPNG_SFX_COUNT &gt; 2</td></tr>
  <tr><td>Mort ennemi</td><td>0 (explosion)</td><td>hp=0, toujours</td></tr>
</table>

<h3>Screen shake</h3>
<p>Trigger action <b>screen_shake</b> (ID 15) dans l'onglet Level :</p>
<ul>
  <li><code>a0</code> = amplitude en pixels (défaut 2)</li>
  <li><code>a1</code> = durée en frames (défaut 8)</li>
</ul>
<p>L'offset alterne <code>±amp</code> sur <code>cam_px</code> chaque frame pendant la durée.
Exemple : <code>a0=3, a1=12</code> = shake fort de 0.2 secondes.</p>

<h3>Coyote time &amp; jump buffer (joueur)</h3>
<ul>
  <li><b>Coyote (6 frames)</b> : le joueur peut encore sauter 6 frames après avoir quitté une plateforme.</li>
  <li><b>Jump buffer (8 frames)</b> : appuyer sauter jusqu'à 8 frames avant d'atterrir → déclenche dès l'impact.</li>
</ul>

<h2>État actuel</h2>
<ul>
  <li>✅ Physique joueur : gravity, saut variable, wall/ceiling/floor, coyote, buffer</li>
  <li>✅ 8 patterns ennemis (data 0..7 : straight→fast→patrol→aggro)</li>
  <li>✅ Gravité ennemis (prop gravity) + détection sol tilecol</li>
  <li>✅ SFX jump / land / kill</li>
  <li>✅ Screen shake (trigger a0=amp, a1=durée)</li>
  <li>🔲 Jump_patrol (ennemi platformer qui saute les gaps)</li>
</ul>
"""


def _en_physics_ai() -> str:
    return """
<h1>Player Physics &amp; Enemy AI</h1>

<h2>Player physics (move_type=2)</h2>
<p>Setting <code>move_type=2</code> on a player sprite in the <b>Hitbox</b> tab generates a full
controller at export time. Per-frame order of operations:</p>
<ol>
  <li>Compute vx (accel/decel from input)</li>
  <li>Gravity (variable: ½ if jump button held while rising)</li>
  <li>Jump (if on_ground + button pressed)</li>
  <li>Horizontal movement → wall collision</li>
  <li>Vertical movement → ceiling then floor collision</li>
  <li>Camera follow (centered at screen_x=80)</li>
</ol>

<h3>Tilemap collision</h3>
<table>
  <tr><th>Type</th><th>Value</th><th>Behaviour</th></tr>
  <tr><td>TILE_PASS</td><td>0</td><td>Passable</td></tr>
  <tr><td>TILE_SOLID</td><td>1</td><td>Blocks all sides (floor, walls, ceiling)</td></tr>
  <tr><td>TILE_ONE_WAY</td><td>2</td><td>Floor only — player can jump through from below</td></tr>
</table>
<p>Floor detection uses <b>2 foot points</b> (left + right, 2px inset from each edge).
Player stays on a platform as long as at least one foot is on it.</p>

<h2>Enemy AI — implemented</h2>

<h3>Movement patterns (data field)</h3>
<table>
  <tr><th>data</th><th>Name</th><th>Behaviour</th></tr>
  <tr><td>0</td><td>straight</td><td>Left (vx=−2)</td></tr>
  <tr><td>1</td><td>drift_down</td><td>Drifts down (vy=+1, bounces y=16/136)</td></tr>
  <tr><td>2</td><td>drift_up</td><td>Drifts up (vy=−1)</td></tr>
  <tr><td>3</td><td>alt_y</td><td>Alternates based on spawn Y parity</td></tr>
  <tr><td>4</td><td>zigzag</td><td>Flips vy every 16 frames (anim counter)</td></tr>
  <tr><td>5</td><td>fast</td><td>vx=−4, straight left</td></tr>
  <tr><td>6</td><td>patrol</td><td>Back-and-forth: flips vx every 48 frames</td></tr>
  <tr><td>7</td><td>aggro+patrol</td><td>Patrol + chase if player &lt;5 tiles (40px)</td></tr>
</table>
<p>If the scene has <b>paths</b> and <code>data &gt; 0</code>, enemy follows path <code>data−1</code> instead.</p>

<h3>Per-instance AI behavior (TRIG-7)</h3>
<p>For each enemy placed in the scene, the <b>AI Parameters</b> panel appears automatically below instance props whenever the behavior is not <code>fixed</code>:</p>
<table>
  <tr><th>Parameter</th><th>Mode(s)</th><th>Range</th><th>Default</th><th>Notes</th></tr>
  <tr><td><b>Speed</b></td><td>patrol, chase, random</td><td>1–255 px/frame</td><td>1</td><td>Exported if any entity ≠ 1</td></tr>
  <tr><td><b>Aggro range</b></td><td>chase</td><td>0–255 (×8 px)</td><td>10 (80 px)</td><td>Player detection radius → triggers chase</td></tr>
  <tr><td><b>Lose range</b></td><td>chase</td><td>0–255 (×8 px)</td><td>16 (128 px)</td><td>Radius beyond which chase is dropped</td></tr>
  <tr><td><b>Dir. change</b></td><td>random</td><td>1–255 frames</td><td>60</td><td>Random direction change frequency</td></tr>
</table>
<p>C tables are only emitted when the relevant mode is actually used: <code>g_{sym}_ent_ai_speed[]</code> if any speed ≠ 1, <code>g_{sym}_ent_ai_range/lose_range[]</code> if at least one enemy is in chase mode, <code>g_{sym}_ent_ai_change_every[]</code> if at least one is in random mode.
Each table has a guard define (<code>SCENE_ENTITY_AI_SPEED_TABLE 1</code>, etc.) to conditionally compile the runtime logic.</p>
<p><b>Range rule:</b> aggro &lt; lose to avoid flickering (enemy only starts chasing when player is close enough, stops only when far enough away).</p>

<h3>Enemy gravity (prop <code>gravity</code>)</h3>
<p>The <b>gravity</b> prop in the Hitbox tab also applies to enemies:</p>
<ul>
  <li><code>gravity=0</code> (default) → shmup-style (bounces at screen edges, no floor)</li>
  <li><code>gravity=2</code> → platformer (falls, tilecol floor detection, <code>on_ground</code>)</li>
</ul>
<p>Exported as <code>g_*_type_gravity[]</code>, read by <code>ngpng_enemies_update</code>.
Fall speed capped at 6 (anti-tunneling — tiles are 8px).</p>

<h3>Gameplay SFX (platformer)</h3>
<table>
  <tr><th>Event</th><th>SFX index</th><th>Condition</th></tr>
  <tr><td>Jump</td><td>1 (blip)</td><td>jump_buf triggered, if NGPNG_SFX_COUNT &gt; 1</td></tr>
  <tr><td>Land</td><td>2 (menu_move)</td><td>vy &gt; 2 on impact, if NGPNG_SFX_COUNT &gt; 2</td></tr>
  <tr><td>Enemy kill</td><td>0 (explosion)</td><td>hp=0, always</td></tr>
</table>

<h3>Screen shake</h3>
<p>Trigger action <b>screen_shake</b> (ID 15) in the Level tab:</p>
<ul>
  <li><code>a0</code> = amplitude in pixels (default 2)</li>
  <li><code>a1</code> = duration in frames (default 8)</li>
</ul>
<p>Alternates <code>±amp</code> on <code>cam_px</code> each frame for the duration.
Example: <code>a0=3, a1=12</code> = hard shake for 0.2 seconds.</p>

<h3>Coyote time &amp; jump buffer (player)</h3>
<ul>
  <li><b>Coyote (6 frames)</b>: player can still jump 6 frames after walking off a ledge.</li>
  <li><b>Jump buffer (8 frames)</b>: pressing jump up to 8 frames before landing → triggers on impact.</li>
</ul>

<h2>Current status</h2>
<ul>
  <li>✅ Player physics: gravity, variable jump, wall/ceiling/floor, coyote, buffer</li>
  <li>✅ 8 enemy patterns (data 0..7: straight→fast→patrol→aggro)</li>
  <li>✅ Enemy gravity (prop gravity) + tilecol floor detection</li>
  <li>✅ SFX jump / land / kill</li>
  <li>✅ Screen shake (trigger a0=amp, a1=duration)</li>
  <li>🔲 Jump_patrol (platformer enemy that jumps gaps)</li>
</ul>
"""


# ---------------------------------------------------------------------------
# Triggers & Regions — FR
# ---------------------------------------------------------------------------

def _fr_physics_ai_runtime_v2() -> str:
    return """
<h1>Physique joueur &amp; IA ennemis</h1>

<h2>Physique joueur (move_type=2)</h2>
<p>Configurer <code>move_type=2</code> sur un sprite joueur dans l'onglet <b>Hitbox</b>
génère un contrôleur complet à l'export. Ordre des opérations par frame :</p>
<ol>
  <li>Calcul vx (accel/décel depuis input)</li>
  <li>Gravité variable pendant la montée</li>
  <li>Saut (si <code>on_ground</code> ou coyote time)</li>
  <li>Déplacement horizontal puis collision murs</li>
  <li>Déplacement vertical puis collision plafond / sol</li>
  <li>Camera follow centrée à screen_x=80</li>
</ol>

<h3>Collision tilemap</h3>
<table>
  <tr><th>Type</th><th>Valeur</th><th>Comportement runtime autorun</th></tr>
  <tr><td>TILE_PASS</td><td>0</td><td>Traversable</td></tr>
  <tr><td>TILE_SOLID</td><td>1</td><td>Bloque tous côtés</td></tr>
  <tr><td>TILE_ONE_WAY</td><td>2</td><td>Sol traversable par dessous</td></tr>
  <tr><td>TILE_DAMAGE</td><td>3</td><td>Hazard marchable, retire 1 HP au contact</td></tr>
  <tr><td>TILE_LADDER</td><td>4</td><td>Exporté / peignable, grimpe native player disponible dans l'autorun exporté</td></tr>
  <tr><td>TILE_WALL_N</td><td>5</td><td>Bord de sol directionnel</td></tr>
  <tr><td>TILE_WALL_S</td><td>6</td><td>Bord de plafond directionnel</td></tr>
  <tr><td>TILE_WALL_E</td><td>7</td><td>Bloque l'entrée depuis la droite</td></tr>
  <tr><td>TILE_WALL_W</td><td>8</td><td>Bloque l'entrée depuis la gauche</td></tr>
  <tr><td>TILE_WATER</td><td>9</td><td>Zone liquide. Ralentissement : <code>water_drag</code> (1–8, défaut 2). Dégâts/frame : <code>water_damage</code> (0=sans). Réglage dans Level &gt; Rules.</td></tr>
  <tr><td>TILE_FIRE</td><td>10</td><td>Comme DAMAGE : hazard marchable, retire 1 HP</td></tr>
  <tr><td>TILE_VOID</td><td>11</td><td>Zone mortelle instantanée</td></tr>
  <tr><td>TILE_DOOR</td><td>12</td><td>Marqueur de porte marchable ; l'autorun peut l'utiliser comme porte simple vers la scène suivante avec UP/A</td></tr>
  <tr><td>TILE_STAIR_E</td><td>13</td><td>Pente marchable non bloquante. Bas à gauche, haut à droite.</td></tr>
  <tr><td>TILE_STAIR_W</td><td>14</td><td>Pente marchable non bloquante. Bas à droite, haut à gauche.</td></tr>
  <tr><td>TILE_SPRING</td><td>15</td><td>Tile tremplin/rebond. Force et direction réglables dans Level &gt; Rules.</td></tr>
  <tr><td>TILE_ICE</td><td>16</td><td>Glace : friction réduite selon <code>ice_friction</code> (0=glace parfaite, 255=sol normal). Réglage dans Level &gt; Rules.</td></tr>
  <tr><td>TILE_CONVEYOR_L</td><td>17</td><td>Tapis roulant vers la gauche. La vitesse est réglable dans Level &gt; Rules.</td></tr>
  <tr><td>TILE_CONVEYOR_R</td><td>18</td><td>Tapis roulant vers la droite. La vitesse est réglable dans Level &gt; Rules.</td></tr>
</table>
<p>La détection de sol utilise <b>2 points de pied</b>. Le joueur reste sur une plateforme tant
qu'au moins un pied la touche.</p>
<p>Première passe runtime : l'autorun comprend maintenant <b>hazards</b>, <b>VOID</b> et les
<b>murs directionnels</b> N/S/E/W. <code>LADDER</code> et <code>WATER</code> restent des marqueurs de gameplay
pour votre runtime final. <code>DOOR</code> a maintenant une V1 native : si le joueur appuie sur <code>UP</code> ou <code>A</code>
en le touchant, l'autorun tente de charger la scène suivante du projet. Si une région au même endroit porte déjà
un trigger <code>goto_scene</code>, cette cible explicite est utilisée en priorité.</p>
<p><b>Escaliers V1 :</b> <code>TILE_STAIR_E</code> et <code>TILE_STAIR_W</code> servent à faire des marches/pentes simples en platformer.
Ils comptent comme du sol pour les pieds, mais ne bloquent pas latéralement et ne remplacent pas <code>LADDER</code>.</p>
<p>Checkpoint V1 : avec un trigger <code>set_checkpoint</code>, une mort future relance
automatiquement le joueur sur cette région après un court délai, sans repasser par le spawn initial.
La preview runtime mémorise aussi maintenant la <b>scène du checkpoint</b> : si le joueur meurt dans une scène suivante sans nouveau checkpoint,
il revient sur la bonne scène puis sur la bonne région. En revanche, un <code>goto_scene</code> normal continue d'utiliser le spawn d'entrée de la scène cible.</p>
<p><b>Camera follow V1 :</b> si la scene est en mode <code>follow</code>, l'autorun utilise maintenant aussi
une <b>dead-zone X/Y</b> et une <b>marge de descente</b> exportees depuis l'onglet Layout. Cela donne un suivi
platformer plus confortable que le simple centrage permanent du joueur.</p>
<p><b>Camera lag (suivi fluide) :</b> le champ <b>Lag caméra</b> dans l'onglet Layout contrôle la fluidité
du suivi (mode <code>follow</code> uniquement). <b>0 = snap instantané</b> (comportement par défaut).
1 à 4 divise l'écart restant par 2, 4, 8 ou 16 par frame — plus la valeur est haute, plus la caméra
«&nbsp;glisse&nbsp;» derrière le joueur. Formule runtime&nbsp;:
<code>cam_x += (target_x - cam_x) &gt;&gt; lag</code>.
Recommandé : <b>1–2</b> pour platformer/RPG, <b>0</b> pour shmup/action rapide.</p>
<p><b>Tiles physiques — ICE, WATER et CONVEYOR (PHY-1) :</b></p>
<ul>
  <li><b>ICE (16) :</b> tile de sol glissant. Quand le joueur est au sol sur une tile <code>TILE_ICE</code>,
  sa décélération horizontale est réduite selon <b>ice_friction</b>.
  <ul>
    <li><b>0</b> (défaut) = glace parfaite : aucune décélération, le joueur garde son <code>vx</code> intact.</li>
    <li><b>255</b> = friction normale (identique au sol ordinaire).</li>
    <li>Valeurs intermédiaires = glace partiellement glissante — idéal pour différencier une banquise légère d'une patinoire.</li>
  </ul>
  Le joueur peut toujours accélérer avec les touches directionnelles. Régler dans <b>Level &gt; Rules &gt; Friction glace (0–255)</b>.</li>
  <li><b>WATER (9) :</b> tile liquide. Deux paramètres indépendants :
  <ul>
    <li><b>water_drag (1–8)</b> : ralentissement. La vitesse du joueur est divisée par cette valeur à chaque frame dans l'eau.
    1 = aucun effet (eau transparente), 8 = eau très résistante / sirop. Régler dans <b>Level &gt; Rules &gt; Résistance eau</b>.</li>
    <li><b>water_damage (0–255)</b> : dégâts par frame. 0 = eau sûre (nage sans risque), 1+ = acide ou eau toxique.
    Régler dans <b>Level &gt; Rules &gt; Dégâts eau</b>.</li>
  </ul>
  Les deux valeurs sont exportées comme <code>SCENE_RULE_WATER_DRAG</code> et <code>SCENE_RULE_WATER_DAMAGE</code> dans le header de scène.</li>
  <li><b>CONVEYOR_L (17) / CONVEYOR_R (18) :</b> tapis roulant. Ajoute ou soustrait
  <b>conveyor_speed</b> px/frame au <code>vx</code> du joueur à chaque frame au sol.
  La vitesse se règle dans <b>Level &gt; Rules &gt; Vitesse tapis (1–8)</b>.</li>
</ul>
<p><b>Forces localisées — ATTRACTOR et REPULSOR (PHY-2) :</b></p>
<ul>
  <li><b>ATTRACTOR :</b> région qui attire le joueur vers son centre. Chaque frame où le joueur
  est à l'intérieur, <b>zone_force</b> px/frame est ajouté à <code>vx</code> et <code>vy</code>
  dans la direction du centre de la région. Utile pour gravité locale, courant d'aspiration, ventilateur.</li>
  <li><b>REPULSOR :</b> région qui repousse le joueur depuis son centre. Même logique, force inversée.
  Utile pour zones de répulsion, champ de force, courant d'air sortant.</li>
  <li>La magnitude se règle dans <b>Level &gt; Rules &gt; Force zone (1–8)</b>.
  Les deux types fonctionnent aussi bien au sol qu'en l'air.</li>
</ul>
<p>Les régions <code>checkpoint</code> et <code>exit_goal</code> ont aussi maintenant une V1 native dans l'autorun :
entrer dans une région <code>checkpoint</code> mémorise directement le point de reprise, et entrer dans une région <code>exit_goal</code>
charge la scène suivante sans trigger manuel. Si cette région a déjà un trigger <code>goto_scene</code>, l'autorun reprend cette cible
au lieu de supposer simplement “scène suivante”.</p>

<h2>HUD custom V2</h2>
<p><b>Base gameplay :</b> les règles de scène peuvent maintenant piloter un petit HUD autorun
et une boucle portable simple : affichage optionnel du score / des collectibles / du timer / des vies,
<code>goal_collectibles</code> pour un <b>STAGE CLEAR</b> simple, <code>time_limit_sec</code> pour un
<b>GAME OVER</b> simple, <code>start_lives</code> pour activer un compteur de vies de départ, et
<code>start_continues</code> pour donner un stock de continues consommé sur <b>GAME OVER</b>.</p>
<p><b>Mode system vs custom :</b> le HUD texte intégré peut être placé <b>en haut</b> ou <b>en bas</b>.
Le mode <code>system</code> affiche les compteurs texte internes. Le mode <code>custom</code> masque ces compteurs
et ouvre une édition de widgets HUD dans <b>Level &gt; HUD</b>, tout en gardant une ligne simple de statut
<code>GAME OVER</code> / <code>STAGE CLEAR</code>.</p>

<h3>Workflow conseillé</h3>
<ol>
  <li>L'édition HUD se fait maintenant dans un <b>onglet HUD dédié</b> et <b>scrollable</b> dans le panneau droit du Level editor.</li>
  <li>Dans <b>Level &gt; HUD</b>, choisissez <code>HUD font mode = custom</code>.</li>
  <li>Ajoutez des widgets dans le bloc <b>HUD custom</b>.</li>
  <li>Pour un widget <code>icon</code>, choisissez un sprite source parmi vos types d'entités exportés.</li>
  <li>Pour un widget <code>value</code>, choisissez la métrique à afficher : <code>hp</code>, <code>score</code>, <code>collect</code>, <code>timer</code>, <code>lives</code> ou <code>continues</code>.</li>
  <li>Réglez sa position écran en tiles, son nombre de digits, et activez ou non le <code>zero pad</code>.</li>
  <li>Pour utiliser une vraie fonte graphique, renseignez les 10 entrées du bloc <b>Fonte sprite 0-9</b> avec des types d'entités correspondant aux chiffres <code>0..9</code>.</li>
  <li>Si besoin, complétez avec des triggers <code>show_entity</code> / <code>hide_entity</code> pour des éléments d'UI plus réactifs.</li>
</ol>

<h3>Ce que la V2 sait faire</h3>
<ul>
  <li><b>Icon</b> : dessine un sprite HUD ancré à l'écran, choisi depuis vos types d'entités.</li>
  <li><b>Value</b> : affiche une valeur runtime soit en <b>fonte sprite 0-9</b>, soit en <b>texte système</b> si la fonte est incomplète.</li>
  <li><b>Digits / zero pad</b> : chaque widget value choisit sa largeur d'affichage et son remplissage.</li>
  <li><b>Ancrage écran</b> : la position reste en coordonnées HUD, pas en coordonnées monde.</li>
  <li><b>Export</b> : les widgets sont exportés dans les scènes générées et lus par l'autorun.</li>
  <li><b>Mix possible</b> : vous pouvez mélanger HUD custom, triggers UI et logique gameplay existante.</li>
</ul>

<h3>Fonte sprite : contrat pratique</h3>
<ul>
  <li>la fonte attend <b>10 types d'entités</b>, un pour chaque chiffre <code>0..9</code> ;</li>
  <li>pour un rendu propre et économique, le plus simple reste des chiffres en <b>1 sprite 8x8</b> chacun ;</li>
  <li>des chiffres multi-sprites fonctionnent aussi, mais consomment plus vite les slots HUD ;</li>
  <li>si un seul chiffre manque, la preview garde le HUD fonctionnel via le <b>fallback texte système</b>.</li>
</ul>

<h3>Ce que la V2 ne fait pas encore</h3>
<ul>
  <li>pas encore de labels libres ou de formatage complexe ;</li>
  <li>pas encore de layout automatique, d'alignement ou de groupes ;</li>
  <li>pas encore de binding déclaratif riche (ex : “si HP ≤ 1, cache tel widget”) directement dans l'éditeur HUD lui-même.</li>
</ul>
<p>Pour ce dernier cas, la voie actuelle reste :
<code>widgets HUD custom</code> pour la base d'affichage, puis <code>triggers</code> et <code>show_entity/hide_entity</code>
pour les états plus scriptés.</p>

<h3>Fond de HUD : tiles BG ou sprites ?</h3>
<p><b>Oui, dans certains cas utiliser le fond du HUD dans la tilemap est utile.</b> Si votre HUD a un cadre, une bande ou une déco
largement statique, le mettre en <b>BG/tilemap</b> peut économiser des <b>sprites OAM</b> et éviter de consommer des
<b>palettes sprites</b> pour un simple décor de fond.</p>
<p><b>Mais ce n'est pas toujours possible ni idéal :</b> dans une scène scrollable, un HUD fixe à l'écran est souvent plus simple
en sprites, parce qu'un BG fait naturellement partie du décor et scrolle avec lui, sauf si votre runtime réserve explicitement
une zone/plane pour l'UI. Dans la preview NGPNG, l'option implémente maintenant un <b>plan HUD fixe</b> :
<b>SCR1</b> ou <b>SCR2</b> peut être figé complètement à l'écran. C'est volontaire, parce que le scroll NGPC est
<b>par plan</b>, pas par rectangle. Donc en pratique :</p>
<ul>
  <li><b>Sprites / texte only</b> : aucun fond BG HUD n'est figé ; le HUD repose sur les sprites et le texte.</li>
  <li><b>si vous cochez un plan HUD fixe</b> : ce plan doit être réservé au HUD, car son décor ne scrollera plus ;</li>
  <li><b>fond statique / bandeau / cadre</b> : tilemap souvent intéressante si votre runtime peut le garder fixe ;</li>
  <li><b>icônes et éléments ancrés écran</b> : sprites souvent plus simples ;</li>
  <li><b>valeurs dynamiques</b> : texte système ou fonte sprite custom selon le rendu visé.</li>
</ul>
<p>Autrement dit, la bonne approche est souvent <b>hybride</b> :
fond de HUD en tiles quand c'est viable, icônes/widgets en sprites, et valeurs en texte ou fonte custom.</p>

<h2>IA ennemis</h2>
<p>Les ennemis à gravité utilisent le même contrat de sol que le joueur pour les surfaces
marchables (<code>SOLID</code>, <code>ONE_WAY</code>, hazards marchables, <code>DOOR</code>, <code>WALL_N</code>).</p>
"""


def _en_physics_ai_runtime_v2() -> str:
    return """
<h1>Player Physics &amp; Enemy AI</h1>

<h2>Player physics (move_type=2)</h2>
<p>Setting <code>move_type=2</code> on a player sprite in the <b>Hitbox</b> tab generates a full
controller at export time. Per-frame order of operations:</p>
<ol>
  <li>Compute vx (accel/decel from input)</li>
  <li>Variable gravity while rising</li>
  <li>Jump (if <code>on_ground</code> or coyote time)</li>
  <li>Horizontal movement then wall collision</li>
  <li>Vertical movement then ceiling / floor collision</li>
  <li>Camera follow centered at screen_x=80</li>
</ol>

<h3>Tilemap collision</h3>
<table>
  <tr><th>Type</th><th>Value</th><th>Autorun runtime behaviour</th></tr>
  <tr><td>TILE_PASS</td><td>0</td><td>Passable</td></tr>
  <tr><td>TILE_SOLID</td><td>1</td><td>Blocks all sides</td></tr>
  <tr><td>TILE_ONE_WAY</td><td>2</td><td>Floor only, jump-through from below</td></tr>
  <tr><td>TILE_DAMAGE</td><td>3</td><td>Walkable hazard, removes 1 HP on contact</td></tr>
  <tr><td>TILE_LADDER</td><td>4</td><td>Exported / paintable, native player climbing is available in the exported autorun</td></tr>
  <tr><td>TILE_WALL_N</td><td>5</td><td>Directional floor edge</td></tr>
  <tr><td>TILE_WALL_S</td><td>6</td><td>Directional ceiling edge</td></tr>
  <tr><td>TILE_WALL_E</td><td>7</td><td>Blocks entry from the right</td></tr>
  <tr><td>TILE_WALL_W</td><td>8</td><td>Blocks entry from the left</td></tr>
  <tr><td>TILE_WATER</td><td>9</td><td>Liquid zone. Slowdown: <code>water_drag</code> (1–8, default 2). Damage/frame: <code>water_damage</code> (0=safe). Configured in Level &gt; Rules.</td></tr>
  <tr><td>TILE_FIRE</td><td>10</td><td>Same as DAMAGE: walkable hazard, removes 1 HP</td></tr>
  <tr><td>TILE_VOID</td><td>11</td><td>Instant fatal zone</td></tr>
  <tr><td>TILE_DOOR</td><td>12</td><td>Walkable door marker; autorun can use it as a simple next-scene door with UP/A</td></tr>
  <tr><td>TILE_STAIR_E</td><td>13</td><td>Non-blocking walkable slope. Low on the left, high on the right.</td></tr>
  <tr><td>TILE_STAIR_W</td><td>14</td><td>Non-blocking walkable slope. Low on the right, high on the left.</td></tr>
  <tr><td>TILE_SPRING</td><td>15</td><td>Spring/rebound tile. Force and direction are configured in Level &gt; Rules.</td></tr>
  <tr><td>TILE_ICE</td><td>16</td><td>Ice: reduced friction according to <code>ice_friction</code> (0=perfect ice, 255=normal ground). Configured in Level &gt; Rules.</td></tr>
  <tr><td>TILE_CONVEYOR_L</td><td>17</td><td>Conveyor belt pushing left. Speed is configured in Level &gt; Rules.</td></tr>
  <tr><td>TILE_CONVEYOR_R</td><td>18</td><td>Conveyor belt pushing right. Speed is configured in Level &gt; Rules.</td></tr>
</table>
<p>Floor detection uses <b>2 foot points</b>. The player remains grounded as long as at least one
foot still touches the platform.</p>
<p>First runtime pass: autorun now understands <b>hazards</b>, <b>VOID</b>, and directional
<b>N/S/E/W walls</b>. <code>LADDER</code> and <code>WATER</code> still export cleanly but remain gameplay markers
for your own final runtime. <code>DOOR</code> now has a native autorun V1: pressing <code>UP</code> or <code>A</code>
while touching it tries to load the next project scene. If a region at the same spot already has a
<code>goto_scene</code> trigger, that explicit target is used first.</p>
<p><b>Stairs V1:</b> <code>TILE_STAIR_E</code> and <code>TILE_STAIR_W</code> are for simple platformer stairs/slopes.
They count as floor for feet placement, but do not block laterally and are not a replacement for <code>LADDER</code>.</p>
<p>Checkpoint V1: with a <code>set_checkpoint</code> trigger, a later death automatically respawns
the player on that region after a short delay instead of always returning to the initial spawn.
Autorun now also remembers the <b>checkpoint scene</b>, so dying in a later scene can return to the
correct earlier scene and checkpoint region. Normal <code>goto_scene</code> transitions still use the entry
spawn of the destination scene.</p>
<p><b>Camera follow V1:</b> when the scene uses <code>follow</code> mode, autorun now also uses
exported <b>X/Y dead-zones</b> and a <b>downward drop margin</b> from the Layout tab. This gives a
more comfortable platformer camera than permanently centering the player.</p>
<p><b>Camera lag (smooth follow):</b> the <b>Camera lag</b> field in the Layout tab controls follow
smoothness (<code>follow</code> mode only). <b>0 = instant snap</b> (default).
Values 1–4 halve the remaining gap per frame (÷2, ÷4, ÷8, ÷16) — higher values make the camera
slide behind the player. Runtime formula: <code>cam_x += (target_x - cam_x) &gt;&gt; lag</code>.
Recommended: <b>1–2</b> for platformer/RPG, <b>0</b> for fast-action/shmup.</p>
<p><b>Physics tiles — ICE, WATER and CONVEYOR (PHY-1):</b></p>
<ul>
  <li><b>ICE (16):</b> slippery floor tile. While the player is on-ground on a <code>TILE_ICE</code> tile,
  horizontal deceleration is reduced according to <b>ice_friction</b>.
  <ul>
    <li><b>0</b> (default) = perfect ice: no deceleration at all — the player keeps their full <code>vx</code>.</li>
    <li><b>255</b> = normal friction (same as regular ground).</li>
    <li>Intermediate values = partially slippery — useful to distinguish light frost from a full ice rink.</li>
  </ul>
  Directional input still accelerates normally. Set in <b>Level &gt; Rules &gt; Ice friction (0–255)</b>.</li>
  <li><b>WATER (9):</b> liquid tile. Two independent parameters:
  <ul>
    <li><b>water_drag (1–8)</b>: slowdown factor. The player's speed is divided by this value every frame
    while inside a WATER tile. 1 = no effect, 8 = heavy resistance (treacle/thick liquid).
    Set in <b>Level &gt; Rules &gt; Water drag</b>.</li>
    <li><b>water_damage (0–255)</b>: damage per frame. 0 = safe water (swimming without penalty), 1+ = acid or
    toxic water. Set in <b>Level &gt; Rules &gt; Water damage</b>.</li>
  </ul>
  Both values are exported as <code>SCENE_RULE_WATER_DRAG</code> and <code>SCENE_RULE_WATER_DAMAGE</code> in the scene header.</li>
  <li><b>CONVEYOR_L (17) / CONVEYOR_R (18):</b> conveyor belt. Adds or subtracts
  <b>conveyor_speed</b> px/frame to the player's <code>vx</code> every frame while on-ground.
  Speed is set in <b>Level &gt; Rules &gt; Conveyor speed (1–8)</b>.</li>
</ul>
<p><b>Localised forces — ATTRACTOR and REPULSOR (PHY-2):</b></p>
<ul>
  <li><b>ATTRACTOR:</b> region that pulls the player toward its center. Every frame the player is
  inside, <b>zone_force</b> px/frame is added to <code>vx</code> and <code>vy</code> toward the
  region center. Useful for local gravity, suction, or fan intake.</li>
  <li><b>REPULSOR:</b> region that pushes the player away from its center. Same logic, reversed force.
  Useful for force fields, exhaust fans, or push-back zones.</li>
  <li>Magnitude is set in <b>Level &gt; Rules &gt; Zone force (1–8)</b>.
  Both types work on-ground and in the air.</li>
</ul>
<p><code>checkpoint</code> and <code>exit_goal</code> regions now also have a native autorun V1:
entering a <code>checkpoint</code> region stores the respawn point, and entering an <code>exit_goal</code>
region loads the next project scene without requiring a manual trigger. If that region already has a
<code>goto_scene</code> trigger, autorun reuses its explicit target instead of assuming “next scene”.</p>

<h2>Custom HUD V2</h2>
<p><b>Gameplay base:</b> scene rules can now drive a small autorun HUD and a simple
portable-console loop: optional score / collectibles / timer / lives display, <code>goal_collectibles</code>
for a simple <b>STAGE CLEAR</b>, <code>time_limit_sec</code> for a simple <b>GAME OVER</b>,
<code>start_lives</code> to enable a simple starting-lives counter, and <code>start_continues</code>
to provide a continue stock consumed on <b>GAME OVER</b>.</p>
<p><b>System vs custom mode:</b> the built-in text HUD can be placed at the <b>top</b> or <b>bottom</b>.
<code>system</code> mode shows built-in counters. <code>custom</code> mode hides those counters
and opens a HUD widget editor in <b>Level &gt; HUD</b>, while keeping a simple
<code>GAME OVER</code> / <code>STAGE CLEAR</code> status line.</p>

<h3>Recommended workflow</h3>
<ol>
  <li>HUD editing now lives in a dedicated, <b>scrollable HUD tab</b> in the Level editor right panel.</li>
  <li>In <b>Level &gt; HUD</b>, set <code>HUD font mode = custom</code>.</li>
  <li>Add widgets in the <b>Custom HUD</b> block.</li>
  <li>For an <code>icon</code> widget, choose a source sprite from your exported entity types.</li>
  <li>For a <code>value</code> widget, choose the metric to display: <code>hp</code>, <code>score</code>, <code>collect</code>, <code>timer</code>, <code>lives</code>, or <code>continues</code>.</li>
  <li>Set its screen position in tiles, digit count, and whether it uses zero-padding.</li>
  <li>If you want a true graphical number font, fill the <b>Sprite font 0-9</b> block with entity types matching digits <code>0..9</code>.</li>
  <li>If needed, complement it with <code>show_entity</code> / <code>hide_entity</code> triggers for more reactive UI states.</li>
</ol>

<h3>What V2 already does</h3>
<ul>
  <li><b>Icon</b>: draws a screen-anchored HUD sprite chosen from your entity types.</li>
  <li><b>Value</b>: displays a runtime metric either as a <b>sprite font 0-9</b> or as <b>system text</b> when the font mapping is incomplete.</li>
  <li><b>Digits / zero pad</b>: each value widget can control its display width and padding.</li>
  <li><b>Screen anchoring</b>: widget positions are HUD/screen coordinates, not world coordinates.</li>
  <li><b>Export</b>: widgets are exported in generated scenes and consumed by autorun.</li>
  <li><b>Mixing</b>: you can combine custom HUD widgets with trigger-driven UI logic.</li>
</ul>

<h3>Sprite font: practical contract</h3>
<ul>
  <li>the font expects <b>10 entity types</b>, one for each digit <code>0..9</code>;</li>
  <li>for clean and cheap rendering, the simplest setup is still <b>one 8x8 sprite per digit</b>;</li>
  <li>multi-sprite digits also work, but consume HUD sprite slots faster;</li>
  <li>if even one digit is missing, preview keeps the HUD usable by falling back to <b>system text</b>.</li>
</ul>

<h3>What V2 does not do yet</h3>
<ul>
  <li>no free labels or advanced number formatting yet;</li>
  <li>no automatic layout/alignment/grouping yet;</li>
  <li>no richer declarative binding such as “if HP-1 then hide that heart” directly inside the HUD editor itself.</li>
</ul>
<p>For that last case, the current practical route is:
<code>custom HUD widgets</code> for the display base, then <code>triggers</code> and <code>show_entity/hide_entity</code>
for more scripted states.</p>

<h3>HUD background: BG tiles or sprites?</h3>
<p><b>Yes, using the HUD background in the tilemap can be useful in some cases.</b> If your HUD uses a mostly static frame,
panel, or decorative strip, putting that in a <b>BG/tilemap</b> can save <b>OAM sprite slots</b> and avoid spending
<b>sprite palettes</b> on a purely decorative background.</p>
<p><b>But it is not always possible or ideal:</b> in a scrolling scene, a fixed screen HUD is often easier with sprites,
because a BG naturally belongs to the level and scrolls with it unless your runtime explicitly reserves a plane/area for UI.
In NGPNG preview, the implemented option is now a true <b>fixed HUD plane</b>: <b>SCR1</b> or <b>SCR2</b> can be frozen
entirely on screen. This is deliberate, because NGPC scroll is <b>per plane</b>, not per rectangle.
So in practice:</p>
<ul>
  <li><b>Sprites / text only</b>: no HUD BG plane is frozen; HUD relies on sprites and text.</li>
  <li><b>if you enable a fixed HUD plane</b>: that plane must be reserved for HUD, because its level art will stop scrolling;</li>
  <li><b>static panel / frame / strip</b>: tilemap can be a good optimisation if your runtime can keep it fixed;</li>
  <li><b>screen-anchored icons and widgets</b>: sprites are often simpler;</li>
  <li><b>dynamic values</b>: system text or custom sprite font depending on the target look.</li>
</ul>
<p>In other words, the most practical setup is often <b>hybrid</b>:
HUD background in tiles when viable, icons/widgets in sprites, and values in system text or custom sprite font.</p>

<h2>Enemy AI</h2>
<p>Gravity enemies now use the same floor contract as the player for walkable surfaces
(<code>SOLID</code>, <code>ONE_WAY</code>, walkable hazards, <code>DOOR</code>, <code>WALL_N</code>).</p>
"""


def _fr_topdown_vs_platform() -> str:
    return """
<h1>Top-Down vs Plateforme / Vue de côté</h1>

<p>NgpCraft Engine supporte deux modes physiques distincts pour le joueur,
sélectionnés automatiquement selon le champ <b>move_type</b> du sprite joueur
dans l'onglet <b>Hitbox</b>.</p>

<h2>Choisir le mode physique</h2>
<table>
  <tr><th>move_type</th><th>Mode</th><th>CDEFS générés</th></tr>
  <tr><td><b>0</b> (4-dir)</td><td>Top-Down</td><td><code>NGPNG_MOVE_TOPDOWN=1</code></td></tr>
  <tr><td><b>1</b> (8-dir)</td><td>Top-Down</td><td><code>NGPNG_MOVE_TOPDOWN=1</code></td></tr>
  <tr><td><b>2</b> (side+jump)</td><td>Plateforme / Vue de côté</td><td><code>NGPNG_MOVE_PLATFORM=1</code></td></tr>
  <tr><td><b>3</b> (scroll forcé)</td><td>Top-Down (shmup)</td><td><code>NGPNG_MOVE_TOPDOWN=1</code></td></tr>
</table>
<p>Le mode est détecté à l'export et configure automatiquement le runtime.
Aucune modification de code C n'est nécessaire.</p>

<h2>Contrat du CTRL function — règle critique</h2>
<p>Dans <b>les deux modes</b>, la fonction CTRL ne doit <b>jamais</b> appliquer
<code>vx</code>/<code>vy</code> directement à <code>x</code>/<code>y</code>.
Elle doit seulement <b>calculer et stocker</b> les vitesses.
Le moteur applique ensuite le déplacement avec résolution de collision.</p>

<table>
  <tr><th></th><th style="color:#6ef;">✓ Correct</th><th style="color:#f66;">✗ Incorrect</th></tr>
  <tr>
    <td>CTRL function</td>
    <td><code>actor-&gt;vx = speed;<br>actor-&gt;vy = 0;</code></td>
    <td><code>actor-&gt;x += speed;<br>/* bypasse collision! */</code></td>
  </tr>
</table>

<p><b>Pourquoi ?</b> La fonction <code>ngpng_player_clamp_tilecol_topdown</code> (top-down)
et les fonctions <code>resolve_platforms</code>/<code>bump_blocks</code> (plateforme)
appliquent elles-mêmes le déplacement :
<code>world_x += vx</code>, puis testent la collision et poussent le joueur hors des tuiles solides.
Si votre CTRL a déjà bougé <code>x</code>, le joueur se déplace deux fois et la collision
ne se déclenche jamais correctement.</p>

<h2>Ordre des opérations par frame</h2>
<h3>Top-Down (move_type 0/1/3)</h3>
<ol>
  <li><b>CTRL_UPDATE</b> — calcule et stocke <code>vx</code>, <code>vy</code></li>
  <li><b>clamp_tilecol_topdown</b> — applique <code>vx</code> (axe X en premier),
      détecte collision, pousse hors des tuiles; puis idem axe Y</li>
  <li><b>clamp_world</b> — force les bords de carte</li>
  <li><b>apply_tile_effects</b> — water, conveyor, spring, dégâts (tous les 2 frames)</li>
  <li><b>Camera follow</b> — suit le centre du joueur</li>
</ol>

<h3>Plateforme / Vue de côté (move_type 2)</h3>
<ol>
  <li>Platform delta (si props/plateformes mobiles actives)</li>
  <li><b>CTRL_UPDATE</b> — calcule <code>vx</code>, gère saut (met <code>vy</code>
      négatif), modifie l'animation</li>
  <li><b>resolve_platforms</b> — plateformes mobiles</li>
  <li><b>bump_blocks</b> — blocs destructibles</li>
  <li><b>clamp_world</b> — bords de carte</li>
  <li><b>apply_tile_effects</b> — water, ice, conveyor, spring, dégâts
      (<code>on_ground</code> requis pour ice et conveyor)</li>
  <li><b>Camera follow</b></li>
</ol>

<h2>Collision tilemap — quelles tuiles utiliser</h2>
<table>
  <tr><th>Tuile</th><th>ID</th><th>Top-Down</th><th>Plateforme</th></tr>
  <tr><td>TILE_PASS</td><td>0</td><td>Libre</td><td>Libre</td></tr>
  <tr><td>TILE_SOLID</td><td>1</td><td>✓ Bloque tous côtés</td><td>✓ Bloque tous côtés</td></tr>
  <tr><td>TILE_ONE_WAY</td><td>2</td><td>— (ignoré)</td><td>✓ Sol uniquement, saut en-dessous</td></tr>
  <tr><td>TILE_DAMAGE</td><td>3</td><td>✓ Marchable, 1 dégât/contact</td><td>✓ Marchable, 1 dégât/contact</td></tr>
  <tr><td>TILE_LADDER</td><td>4</td><td>— (ignoré)</td><td>✓ Escalade verticale</td></tr>
  <tr><td>TILE_WALL_N</td><td>5</td><td>✓ Bloque si on va vers le <b>bas</b></td><td>✓ Sol directionnel</td></tr>
  <tr><td>TILE_WALL_S</td><td>6</td><td>✓ Bloque si on va vers le <b>haut</b></td><td>✓ Plafond directionnel</td></tr>
  <tr><td>TILE_WALL_E</td><td>7</td><td>✓ Bloque si on va vers la <b>gauche</b></td><td>✓ Mur droit directionnel</td></tr>
  <tr><td>TILE_WALL_W</td><td>8</td><td>✓ Bloque si on va vers la <b>droite</b></td><td>✓ Mur gauche directionnel</td></tr>
  <tr><td>TILE_WATER</td><td>9</td><td>✓ Ralentit vx et vy (÷2)</td><td>✓ Ralentit + dégâts optionnels</td></tr>
  <tr><td>TILE_FIRE</td><td>10</td><td>✓ 1 dégât/contact</td><td>✓ 1 dégât/contact</td></tr>
  <tr><td>TILE_VOID</td><td>11</td><td>✓ Fatal instantané</td><td>✓ Fatal instantané</td></tr>
  <tr><td>TILE_SPRING</td><td>15</td><td>✓ Rebond configurable</td><td>✓ Rebond configurable</td></tr>
  <tr><td>TILE_ICE</td><td>16</td><td>✓ Glisse (probe centre hitbox)</td><td>✓ Glisse (probe pied, si <code>on_ground</code>)</td></tr>
  <tr><td>TILE_CONVEYOR_L/R</td><td>17/18</td><td>✓ Décale vx (probe centre, toujours actif)</td><td>✓ Décale vx (probe pied, si <code>on_ground</code>)</td></tr>
</table>

<h2>Différences comportementales clés</h2>

<h3>Gravité et saut</h3>
<p>En <b>top-down</b> : pas de gravité. <code>vy</code> est intégralement contrôlé par le CTRL.
En <b>plateforme</b> : le moteur ajoute la gravité à <code>vy</code> chaque frame et gère
<code>on_ground</code>, coyote time et jump buffer.</p>

<h3>Ice et Conveyor</h3>
<p>En <b>plateforme</b>, ice et conveyor vérifient <code>on_ground</code> (probe pied).
En <b>top-down</b>, ils vérifient la tuile au centre de la hitbox et s'appliquent
quelle que soit la "pose" (il n'y a pas de sol en top-down).</p>

<h3>WALL_N/S/E/W — sémantique</h3>
<p>Pour le top-down, la sémantique est directionnelle selon le <b>mouvement du joueur</b> :</p>
<ul>
  <li><b>WALL_N</b> = face nord de la tuile est solide → bloque si <code>vy &gt; 0</code> (descend)</li>
  <li><b>WALL_S</b> = face sud → bloque si <code>vy &lt; 0</code> (monte)</li>
  <li><b>WALL_E</b> = face est → bloque si <code>vx &lt; 0</code> (va à gauche)</li>
  <li><b>WALL_W</b> = face ouest → bloque si <code>vx &gt; 0</code> (va à droite)</li>
</ul>
<p>Utilisez les murs directionnels pour des passages en sens unique (portes à sens unique,
bords de route franchissables depuis un seul côté).</p>

<h2>Schéma de contrôle top-down — td_control &amp; td_move</h2>

<p>En top-down, deux propriétés indépendantes configurent comment le joueur oriente et déplace son sprite.
Elles se définissent dans les <b>props</b> du sprite joueur (onglet Hitbox).</p>

<h3>td_control — comment le joueur oriente le sprite</h3>
<table>
  <tr><th>Valeur</th><th>Comportement</th><th>Exemple</th></tr>
  <tr>
    <td><b>"absolute"</b> (défaut)</td>
    <td>La direction pressée devient immédiatement le nouvel avant du sprite.<br>
        Haut → face Nord, Droite → face Est.</td>
    <td>RPG, dungeon crawler (Zelda)</td>
  </tr>
  <tr>
    <td><b>"relative"</b></td>
    <td>Gauche/Droite font <b>pivoter</b> l'avant par rapport à la direction courante.<br>
        Si l'avant est à l'Est et tu appuies Droite → l'avant devient Sud.</td>
    <td>Tank, voiture, vaisseau</td>
  </tr>
</table>

<h3>td_move — modèle de mouvement</h3>
<table>
  <tr><th>Valeur</th><th>Comportement</th><th>Boutons</th><th>Exemple</th></tr>
  <tr>
    <td><b>"direct"</b> (défaut)</td>
    <td>Les touches appliquent vx/vy instantanément. Pas d'inertie.</td>
    <td>Croix directionnelle</td>
    <td>RPG, puzzle, Bomberman</td>
  </tr>
  <tr>
    <td><b>"advance"</b></td>
    <td>Haut/Bas avancent/reculent dans la direction du facing. Pas d'inertie.</td>
    <td>Haut/Bas + Gauche/Droite (rotation)</td>
    <td>Tank shooter, Smash TV</td>
  </tr>
  <tr>
    <td><b>"vehicle"</b></td>
    <td>A = accélère, B = freine. Friction passive. Inertie scalaire décomposée en vx/vy.</td>
    <td>A/B + Gauche/Droite (rotation)</td>
    <td>Racing, vaisseau orbital</td>
  </tr>
</table>

<h3>Combinaisons typiques</h3>
<table>
  <tr><th>td_control</th><th>td_move</th><th>Résultat</th></tr>
  <tr><td>absolute</td><td>direct</td><td>RPG classique (Zelda, Pokémon)</td></tr>
  <tr><td>absolute</td><td>advance</td><td>Action top-down avec inertie directe</td></tr>
  <tr><td>relative</td><td>advance</td><td>Tank (tourne puis avance)</td></tr>
  <tr><td>relative</td><td>vehicle</td><td>Voiture / vaisseau avec drift</td></tr>
</table>

<p><b>Note :</b> Sans ces propriétés, le comportement par défaut est
<code>absolute + direct</code> — mouvement immédiat dans la direction pressée,
compatible avec tous les projets top-down existants.</p>

<h3>Ce que le générateur émet automatiquement</h3>
<p>Dès qu'un projet est top-down (<code>move_type ≠ 2</code>), l'export génère dans
<code>ngpng_autorun_main.c</code> :</p>
<ul>
  <li><b>Tables trigo ×16</b> : <code>ngpng_td_sin8[8]</code> et <code>ngpng_td_cos8[8]</code>
      (valeurs entières, évite tout float sur T900)</li>
  <li><b>Mapping sprite</b> : <code>ngpng_td_angle_frame[8]</code> (frame à afficher)
      et <code>ngpng_td_angle_fliph[8]</code> (miroir H pour SW/W/NW)</li>
  <li><b>Variable d'angle</b> : <code>s_td_angle</code> — 0=N, 1=NE, 2=E … 7=NW</li>
  <li><b>Variable de vitesse</b> : <code>s_td_speed</code> — uniquement si <code>td_move = "advance"</code>
      ou <code>"vehicle"</code></li>
  <li><b>Constantes physiques</b> (uniquement <code>td_move = "vehicle"</code>) :<br>
      <code>TD_SPEED_MAX</code>, <code>TD_ACCEL</code>, <code>TD_BRAKE</code>, <code>TD_FRICTION</code>
      — valeurs par défaut 48/4/6/2, configurables dans l'onglet <b>Hitbox → groupe Top-down</b>.
      Exportées comme <code>CDEFS += -DTD_SPEED_MAX=X</code> dans le Makefile généré.</li>
  <li><b>td_control / td_move</b> : configurables dans <b>Hitbox → Top-down</b>
      (0=absolute/1=relative ; 0=direct/1=advance/2=vehicle).</li>
</ul>
<p>Décomposition vectorielle : <code>vx = sin8[angle]*speed&gt;&gt;4</code>,
<code>vy = cos8[angle]*speed&gt;&gt;4</code>.
Angles : N = vy négatif (vers le haut écran), Y+ = vers le bas.</p>

<h3>Contrat CTRL — règle obligatoire</h3>
<p>Le CTRL_UPDATE généré ne modifie <b>jamais</b> <code>actor.x</code> ou <code>actor.y</code>
directement. Il calcule uniquement <code>vx</code> et <code>vy</code>.
Le moteur applique ensuite le déplacement et la collision via
<code>ngpng_player_clamp_tilecol_topdown</code> + <code>ngpng_player_clamp_world</code>.</p>
<p>À chaque scene-enter ou respawn, <code>CTRL_INIT</code> remet <code>s_td_angle = 0</code>
et <code>s_td_speed = 0</code> automatiquement.</p>
<p><b>Collision et vitesse (advance/vehicle) :</b> après
<code>ngpng_player_clamp_tilecol_topdown</code>, si <code>vx</code> ou <code>vy</code>
a changé (mur touché), <code>s_td_speed</code> est remis à 0.
Résultat : le véhicule s'arrête net au contact d'un obstacle.</p>

<h2>Workflow rapide — circuit / jeu de voiture</h2>
<ol>
  <li>Sprite joueur : <b>move_type = 0</b> ou <b>1</b>, <b>td_control = "relative"</b>, <b>td_move = "vehicle"</b></li>
  <li>Hitbox non nulle (body_w &gt; 0, body_h &gt; 0)</li>
  <li>8 frames directionnelles dans le sprite (N/NE/E/SE/S + miroir H pour SW/W/NW)</li>
  <li>Col map : piste = <code>0</code> (PASS), hors piste = <code>1</code> (SOLID) ou
      <code>9</code> (WATER pour ralentissement)</li>
  <li>Exporter → make → A accélère, B freine, L/R tourne, le sprite suit la direction</li>
</ol>

<h2>Workflow rapide — platformer / vue de côté</h2>
<ol>
  <li>Sprite joueur : <b>move_type = 2</b></li>
  <li>Configurer gravity, jump_force, hspeed_max dans Hitbox &gt; Physics</li>
  <li>CTRL function : gère vx (accel/decel input) et appuie bouton saut
      (le moteur s'occupe du saut si <code>on_ground</code> est vrai)</li>
  <li>Col map : sol = <code>1</code> (SOLID) ou <code>2</code> (ONE_WAY),
      plateformes passables = <code>2</code>, LADDER = <code>4</code></li>
  <li>Exporter → make → saut et collision fonctionnent</li>
</ol>

<h2>Physique mixte — platformer + top-down selon la scène</h2>
<p>Un projet peut mélanger des scènes platformer et des scènes top-down en plaçant
<b>plusieurs formes joueur</b> (sprites avec le rôle <code>player</code> et des
<code>move_type</code> différents) dans des scènes distinctes.</p>

<h3>Comment ça marche</h3>
<ol>
  <li>Créez <b>N sprites joueur</b> : un avec <code>move_type = 2</code> (platformer),
      un autre avec <code>move_type = 0</code> ou <code>1</code> (top-down).</li>
  <li>Placez chaque sprite dans les scènes appropriées via l'onglet <b>Level</b>.</li>
  <li>L'export détecte automatiquement quelle forme est active dans chaque scène
      et génère le code de sélection de forme (<code>player_form</code>) correspondant.</li>
</ol>

<h3>Ce que l'engine génère automatiquement</h3>
<ul>
  <li><b>player_form_mode = 1</b> : mode "une seule forme visible à la fois" activé.</li>
  <li><b>player_form</b> : sélectionné à l'entrée de chaque scène selon le sprite placé.</li>
  <li><b>Override top-down</b> : pour les scènes top-down, le moteur remplace le CTRL_UPDATE
      platformer par un bloc 4-dir qui définit <code>vx</code>/<code>vy</code>, puis appelle
      <code>ngpng_player_clamp_tilecol_topdown</code> pour la collision.</li>
  <li><b>Gravité désactivée</b> : <code>on_ground = 1</code> forcé dans les scènes top-down
      pour neutraliser la gravité.</li>
  <li><b>NGPNG_MOVE_TOPDOWN=1</b> : ajouté au Makefile même si la physique principale
      est platformer, dès qu'au moins une scène utilise une forme top-down.</li>
</ul>

<h3>Contrainte hitbox</h3>
<p>Chaque forme joueur doit avoir une <b>body hitbox non nulle</b>
(<code>body_w &gt; 0</code>, <code>body_h &gt; 0</code>) pour que la collision top-down
fonctionne. Configurez-la dans l'onglet <b>Hitbox</b> de chaque sprite.</p>

<h3>Exemple minimal</h3>
<table>
  <tr><th>Scène</th><th>Sprite joueur</th><th>move_type</th><th>Comportement</th></tr>
  <tr><td>scene_1</td><td>hero_side</td><td>2</td><td>Platformer classique</td></tr>
  <tr><td>scene_2</td><td>hero_top</td><td>0</td><td>Top-down 4 directions</td></tr>
</table>
<p>Aucun code C supplémentaire n'est nécessaire. L'export gère tout.</p>
"""


def _en_topdown_vs_platform() -> str:
    return """
<h1>Top-Down vs Platformer / Side-View</h1>

<p>NgpCraft Engine supports two distinct physics modes for the player,
automatically selected based on the <b>move_type</b> field of the player sprite
in the <b>Hitbox</b> tab.</p>

<h2>Choosing the physics mode</h2>
<table>
  <tr><th>move_type</th><th>Mode</th><th>Generated CDEFs</th></tr>
  <tr><td><b>0</b> (4-dir)</td><td>Top-Down</td><td><code>NGPNG_MOVE_TOPDOWN=1</code></td></tr>
  <tr><td><b>1</b> (8-dir)</td><td>Top-Down</td><td><code>NGPNG_MOVE_TOPDOWN=1</code></td></tr>
  <tr><td><b>2</b> (side+jump)</td><td>Platformer / Side-View</td><td><code>NGPNG_MOVE_PLATFORM=1</code></td></tr>
  <tr><td><b>3</b> (forced scroll)</td><td>Top-Down (shmup)</td><td><code>NGPNG_MOVE_TOPDOWN=1</code></td></tr>
</table>
<p>The mode is detected at export time and automatically configures the runtime.
No C code changes are required.</p>

<h2>CTRL function contract — critical rule</h2>
<p>In <b>both modes</b>, the CTRL function must <b>never</b> apply
<code>vx</code>/<code>vy</code> directly to <code>x</code>/<code>y</code>.
It should only <b>compute and store</b> the velocities.
The engine then applies movement with collision resolution.</p>

<table>
  <tr><th></th><th style="color:#6ef;">✓ Correct</th><th style="color:#f66;">✗ Wrong</th></tr>
  <tr>
    <td>CTRL function</td>
    <td><code>actor-&gt;vx = speed;<br>actor-&gt;vy = 0;</code></td>
    <td><code>actor-&gt;x += speed;<br>/* bypasses collision! */</code></td>
  </tr>
</table>

<p><b>Why?</b> The function <code>ngpng_player_clamp_tilecol_topdown</code> (top-down)
and <code>resolve_platforms</code>/<code>bump_blocks</code> (platformer)
apply movement themselves:
<code>world_x += vx</code>, then test collision and push the player out of solid tiles.
If your CTRL already moved <code>x</code>, the player moves twice and collision
never triggers correctly.</p>

<h2>Per-frame order of operations</h2>
<h3>Top-Down (move_type 0/1/3)</h3>
<ol>
  <li><b>CTRL_UPDATE</b> — compute and store <code>vx</code>, <code>vy</code></li>
  <li><b>clamp_tilecol_topdown</b> — apply <code>vx</code> (X axis first),
      detect collision, push out; then same for Y axis</li>
  <li><b>clamp_world</b> — enforce map bounds</li>
  <li><b>apply_tile_effects</b> — water, conveyor, spring, damage (every 2 frames)</li>
  <li><b>Camera follow</b> — follows player centre</li>
</ol>

<h3>Platformer / Side-View (move_type 2)</h3>
<ol>
  <li>Platform delta (if moving props/platforms are active)</li>
  <li><b>CTRL_UPDATE</b> — compute <code>vx</code>, handle jump (sets negative
      <code>vy</code>), update animation</li>
  <li><b>resolve_platforms</b> — moving platforms</li>
  <li><b>bump_blocks</b> — breakable blocks</li>
  <li><b>clamp_world</b> — map bounds</li>
  <li><b>apply_tile_effects</b> — water, ice, conveyor, spring, damage
      (<code>on_ground</code> required for ice and conveyor)</li>
  <li><b>Camera follow</b></li>
</ol>

<h2>Tilemap collision — which tiles to use</h2>
<table>
  <tr><th>Tile</th><th>ID</th><th>Top-Down</th><th>Platformer</th></tr>
  <tr><td>TILE_PASS</td><td>0</td><td>Passable</td><td>Passable</td></tr>
  <tr><td>TILE_SOLID</td><td>1</td><td>✓ Blocks all sides</td><td>✓ Blocks all sides</td></tr>
  <tr><td>TILE_ONE_WAY</td><td>2</td><td>— (ignored)</td><td>✓ Floor only, jump-through from below</td></tr>
  <tr><td>TILE_DAMAGE</td><td>3</td><td>✓ Walkable hazard, 1 HP/contact</td><td>✓ Walkable hazard, 1 HP/contact</td></tr>
  <tr><td>TILE_LADDER</td><td>4</td><td>— (ignored)</td><td>✓ Vertical climbing</td></tr>
  <tr><td>TILE_WALL_N</td><td>5</td><td>✓ Blocks if moving <b>down</b></td><td>✓ Directional floor</td></tr>
  <tr><td>TILE_WALL_S</td><td>6</td><td>✓ Blocks if moving <b>up</b></td><td>✓ Directional ceiling</td></tr>
  <tr><td>TILE_WALL_E</td><td>7</td><td>✓ Blocks if moving <b>left</b></td><td>✓ Directional right wall</td></tr>
  <tr><td>TILE_WALL_W</td><td>8</td><td>✓ Blocks if moving <b>right</b></td><td>✓ Directional left wall</td></tr>
  <tr><td>TILE_WATER</td><td>9</td><td>✓ Slows vx and vy (÷2)</td><td>✓ Slowdown + optional damage</td></tr>
  <tr><td>TILE_FIRE</td><td>10</td><td>✓ 1 HP/contact</td><td>✓ 1 HP/contact</td></tr>
  <tr><td>TILE_VOID</td><td>11</td><td>✓ Instant fatal</td><td>✓ Instant fatal</td></tr>
  <tr><td>TILE_SPRING</td><td>15</td><td>✓ Configurable bounce</td><td>✓ Configurable bounce</td></tr>
  <tr><td>TILE_ICE</td><td>16</td><td>✓ Slide (probe hitbox centre)</td><td>✓ Slide (probe foot, if <code>on_ground</code>)</td></tr>
  <tr><td>TILE_CONVEYOR_L/R</td><td>17/18</td><td>✓ Shifts vx (probe centre, always active)</td><td>✓ Shifts vx (probe foot, if <code>on_ground</code>)</td></tr>
</table>

<h2>Key behavioural differences</h2>

<h3>Gravity and jumping</h3>
<p>In <b>top-down</b>: no gravity. <code>vy</code> is entirely controlled by the CTRL function.
In <b>platformer</b>: the engine adds gravity to <code>vy</code> every frame and manages
<code>on_ground</code>, coyote time, and jump buffer.</p>

<h3>Ice and Conveyor</h3>
<p>In <b>platformer</b> mode, ice and conveyor check <code>on_ground</code> (foot probe).
In <b>top-down</b> mode, they probe the tile at the hitbox centre and apply regardless
of ground state (there is no "ground" in top-down).</p>

<h3>WALL_N/S/E/W — semantics</h3>
<p>In top-down, the semantics are based on the <b>player's movement direction</b>:</p>
<ul>
  <li><b>WALL_N</b> = tile's north face is solid → blocks when <code>vy &gt; 0</code> (moving down)</li>
  <li><b>WALL_S</b> = south face → blocks when <code>vy &lt; 0</code> (moving up)</li>
  <li><b>WALL_E</b> = east face → blocks when <code>vx &lt; 0</code> (moving left)</li>
  <li><b>WALL_W</b> = west face → blocks when <code>vx &gt; 0</code> (moving right)</li>
</ul>
<p>Use directional walls for one-way passages (one-way doors, road edges crossable from one side only).</p>

<h2>Top-down control scheme — td_control &amp; td_move</h2>

<p>Two independent properties configure how the player orients and moves their sprite in top-down mode.
Set them in the player sprite's <b>props</b> (Hitbox tab).</p>

<h3>td_control — how the player orients the sprite</h3>
<table>
  <tr><th>Value</th><th>Behaviour</th><th>Example</th></tr>
  <tr>
    <td><b>"absolute"</b> (default)</td>
    <td>The pressed direction immediately becomes the sprite's new facing.<br>
        Up → face North, Right → face East.</td>
    <td>RPG, dungeon crawler (Zelda)</td>
  </tr>
  <tr>
    <td><b>"relative"</b></td>
    <td>Left/Right <b>rotate</b> the current facing direction.<br>
        If facing East and you press Right → facing becomes South.</td>
    <td>Tank, car, spaceship</td>
  </tr>
</table>

<h3>td_move — movement model</h3>
<table>
  <tr><th>Value</th><th>Behaviour</th><th>Buttons</th><th>Example</th></tr>
  <tr>
    <td><b>"direct"</b> (default)</td>
    <td>D-pad applies vx/vy immediately. No inertia.</td>
    <td>D-pad</td>
    <td>RPG, puzzle, Bomberman</td>
  </tr>
  <tr>
    <td><b>"advance"</b></td>
    <td>Up/Down move forward/backward along the facing direction. No inertia.</td>
    <td>Up/Down + Left/Right (rotate)</td>
    <td>Tank shooter, Smash TV</td>
  </tr>
  <tr>
    <td><b>"vehicle"</b></td>
    <td>A = accelerate, B = brake. Passive friction. Scalar inertia decomposed into vx/vy.</td>
    <td>A/B + Left/Right (rotate)</td>
    <td>Racing, orbital spaceship</td>
  </tr>
</table>

<h3>Typical combinations</h3>
<table>
  <tr><th>td_control</th><th>td_move</th><th>Result</th></tr>
  <tr><td>absolute</td><td>direct</td><td>Classic RPG (Zelda, Pokémon)</td></tr>
  <tr><td>absolute</td><td>advance</td><td>Top-down action with direct inertia</td></tr>
  <tr><td>relative</td><td>advance</td><td>Tank (rotate then drive)</td></tr>
  <tr><td>relative</td><td>vehicle</td><td>Car / spaceship with drift</td></tr>
</table>

<p><b>Note:</b> Without these properties the default behaviour is
<code>absolute + direct</code> — immediate movement in the pressed direction,
fully compatible with all existing top-down projects.</p>

<h3>What the generator emits automatically</h3>
<p>As soon as a project is top-down (<code>move_type ≠ 2</code>), the export writes
into <code>ngpng_autorun_main.c</code>:</p>
<ul>
  <li><b>Trig tables ×16</b>: <code>ngpng_td_sin8[8]</code> and <code>ngpng_td_cos8[8]</code>
      (integer values, no float on T900)</li>
  <li><b>Sprite mapping</b>: <code>ngpng_td_angle_frame[8]</code> (frame to display)
      and <code>ngpng_td_angle_fliph[8]</code> (H-mirror for SW/W/NW)</li>
  <li><b>Angle variable</b>: <code>s_td_angle</code> — 0=N, 1=NE, 2=E … 7=NW</li>
  <li><b>Speed variable</b>: <code>s_td_speed</code> — only when <code>td_move = "advance"</code>
      or <code>"vehicle"</code></li>
  <li><b>Physics constants</b> (only <code>td_move = "vehicle"</code>):<br>
      <code>TD_SPEED_MAX</code>, <code>TD_ACCEL</code>, <code>TD_BRAKE</code>, <code>TD_FRICTION</code>
      — defaults 48/4/6/2, configurable in <b>Hitbox → Top-down group</b>.
      Exported as <code>CDEFS += -DTD_SPEED_MAX=X</code> in the generated Makefile.</li>
  <li><b>td_control / td_move</b>: configurable in <b>Hitbox → Top-down</b>
      (0=absolute/1=relative ; 0=direct/1=advance/2=vehicle).</li>
</ul>
<p>Vector decomposition: <code>vx = sin8[angle]*speed&gt;&gt;4</code>,
<code>vy = cos8[angle]*speed&gt;&gt;4</code>.
Angles: N = negative vy (screen up), Y+ = screen down.</p>

<h3>CTRL contract — required rule</h3>
<p>The generated CTRL_UPDATE <b>never</b> modifies <code>actor.x</code> or <code>actor.y</code>
directly. It only computes <code>vx</code> and <code>vy</code>.
The engine then applies movement and collision via
<code>ngpng_player_clamp_tilecol_topdown</code> + <code>ngpng_player_clamp_world</code>.</p>
<p>On every scene-enter or respawn, <code>CTRL_INIT</code> automatically resets
<code>s_td_angle = 0</code> and <code>s_td_speed = 0</code>.</p>
<p><b>Collision and speed (advance/vehicle only):</b> after
<code>ngpng_player_clamp_tilecol_topdown</code>, if <code>vx</code> or <code>vy</code>
changed (wall hit), <code>s_td_speed</code> is reset to 0.
This stops the vehicle dead on impact with an obstacle.</p>

<h2>Quick workflow — circuit / racing game</h2>
<ol>
  <li>Player sprite: <b>move_type = 0</b> or <b>1</b>, <b>td_control = "relative"</b>, <b>td_move = "vehicle"</b></li>
  <li>Non-zero hitbox (body_w &gt; 0, body_h &gt; 0)</li>
  <li>8 directional frames in the sprite (N/NE/E/SE/S + H-mirror for SW/W/NW)</li>
  <li>Col map: track = <code>0</code> (PASS), off-track = <code>1</code> (SOLID) or
      <code>9</code> (WATER for slowdown)</li>
  <li>Export → make → A accelerates, B brakes, L/R rotates, sprite follows direction</li>
</ol>

<h2>Quick workflow — platformer / side-view</h2>
<ol>
  <li>Player sprite: <b>move_type = 2</b></li>
  <li>Configure gravity, jump_force, hspeed_max in Hitbox &gt; Physics</li>
  <li>CTRL function: handles vx (accel/decel from input) and sets jump flag
      (engine handles the actual jump when <code>on_ground</code> is true)</li>
  <li>Col map: ground = <code>1</code> (SOLID) or <code>2</code> (ONE_WAY),
      pass-through platforms = <code>2</code>, LADDER = <code>4</code></li>
  <li>Export → make → jump and collision work</li>
</ol>

<h2>Mixed physics — platformer + top-down per scene</h2>
<p>A project can mix platformer scenes and top-down scenes by placing
<b>multiple player forms</b> (sprites with the <code>player</code> role and different
<code>move_type</code> values) in separate scenes.</p>

<h3>How it works</h3>
<ol>
  <li>Create <b>N player sprites</b>: one with <code>move_type = 2</code> (platformer),
      another with <code>move_type = 0</code> or <code>1</code> (top-down).</li>
  <li>Place each sprite in the appropriate scenes via the <b>Level</b> tab.</li>
  <li>The exporter automatically detects which form is active in each scene
      and generates the matching form-selection code (<code>player_form</code>).</li>
</ol>

<h3>What the engine generates automatically</h3>
<ul>
  <li><b>player_form_mode = 1</b>: "one visible form at a time" mode is enabled.</li>
  <li><b>player_form</b>: selected on scene entry based on which player sprite is placed there.</li>
  <li><b>Top-down override</b>: for top-down scenes, the engine replaces the platformer
      CTRL_UPDATE with a 4-dir block that sets <code>vx</code>/<code>vy</code>,
      then calls <code>ngpng_player_clamp_tilecol_topdown</code> for collision.</li>
  <li><b>Gravity disabled</b>: <code>on_ground = 1</code> forced in top-down scenes
      to neutralise gravity.</li>
  <li><b>NGPNG_MOVE_TOPDOWN=1</b>: added to the Makefile even if the primary physics
      is platformer, as long as at least one scene uses a top-down player form.</li>
</ul>

<h3>Hitbox requirement</h3>
<p>Each player form must have a <b>non-zero body hitbox</b>
(<code>body_w &gt; 0</code>, <code>body_h &gt; 0</code>) for top-down collision
to work. Configure it in the <b>Hitbox</b> tab of each sprite.</p>

<h3>Minimal example</h3>
<table>
  <tr><th>Scene</th><th>Player sprite</th><th>move_type</th><th>Behaviour</th></tr>
  <tr><td>scene_1</td><td>hero_side</td><td>2</td><td>Classic platformer</td></tr>
  <tr><td>scene_2</td><td>hero_top</td><td>0</td><td>Top-down 4 directions</td></tr>
</table>
<p>No extra C code needed. The exporter handles everything.</p>
"""


def _fr_triggers() -> str:
    return """
<h1>Triggers &amp; Régions — Référence complète</h1>

<p>Ce topic est la référence exhaustive du système trigger/région du Level Editor.
Pour la vue d'ensemble de l'onglet Level, voir <b>Éditeur de niveau</b>.</p>

<h2>Flux de travail (résumé)</h2>
<ol>
  <li>Créez des <b>Régions</b> (onglet Régions) : dessinez un rectangle sur la grille, nommez-le, choisissez son type.</li>
  <li>Créez des <b>Triggers</b> (onglet Triggers) : <i>+ Ajouter</i>, sélectionnez une condition, choisissez une action.</li>
  <li>Si vous avez besoin que <b>plusieurs conditions soient vraies simultanément</b>, ajoutez des conditions ET dans le groupe "Conditions ET" en bas.</li>
  <li>Utilisez <b>⧉ Dup</b> pour dupliquer un trigger existant et créer des variantes rapidement.</li>
  <li>Sauvegardez dans le projet → Exportez (<code>_scene.h</code>).</li>
</ol>

<h2>Types de régions</h2>
<table>
  <tr><th>Type</th><th>ID</th><th>Couleur</th><th>Usage</th></tr>
  <tr><td><b>zone</b></td><td>0</td><td>Violet</td><td>Zone générique (déclenche enter/leave_region)</td></tr>
  <tr><td><b>no_spawn</b></td><td>1</td><td>Orange</td><td>Zone interdite au Procgen</td></tr>
  <tr><td><b>danger_zone</b></td><td>2</td><td>Rouge</td><td>Zone de danger (runtime l'interprète : mort, dégâts, checkpoint…)</td></tr>
  <tr><td><b>checkpoint</b></td><td>3</td><td>Vert</td><td>Point de reprise natif en autorun. Entrer dedans mémorise la scène et la région de respawn.</td></tr>
  <tr><td><b>exit_goal</b></td><td>4</td><td>Jaune</td><td>Sortie native en autorun. Entrer dedans charge la scène suivante, ou la cible d'un <code>goto_scene</code> déjà posé sur la même région.</td></tr>
  <tr><td><b>camera_lock</b></td><td>5</td><td>Bleu</td><td>Lock caméra natif en autorun. En mode <code>follow</code>, la caméra reste clampée à cette salle/section tant que le joueur est dedans.</td></tr>
  <tr><td><b>spawn</b></td><td>6</td><td>Cyan</td><td>Point de spawn (cible <code>warp_to</code>). Le centre de la région définit la position pixel de téléportation. Index dans l'ordre des régions spawn de la scène.</td></tr>
  <tr><td><b>attractor</b></td><td>7</td><td>—</td><td>Attire le joueur vers le centre de la région. Ajoute <code>zone_force</code> px/frame à <code>vx</code>/<code>vy</code> vers le centre, à chaque frame où le joueur est à l'intérieur (sol ou air).</td></tr>
  <tr><td><b>repulsor</b></td><td>8</td><td>—</td><td>Repousse le joueur depuis le centre de la région. Même logique, force inversée. Utile pour champs de force, courants d'air, zones de répulsion.</td></tr>
</table>
<p>Toutes les régions sont exportées en C avec leurs coordonnées (x, y, w, h) et leur type.</p>
<p><b>Runtime autorun V1 :</b> les régions <code>checkpoint</code> et <code>exit_goal</code> ne sont plus de simples marqueurs documentaires.
Elles ont maintenant un comportement natif dans la preview fournie, sans trigger manuel obligatoire.</p>
<p><b>Camera room locks V1 :</b> une région <code>camera_lock</code> utilise son propre rectangle comme contrainte caméra.
Si la région est plus petite que l'écran, la caméra se fige simplement sur son origine ; sinon elle peut encore se déplacer dans la sous-zone visible.</p>
<p>Si plusieurs régions <code>camera_lock</code> se chevauchent, l'autorun choisit maintenant automatiquement la plus petite.
Cela permet déjà de faire des locks imbriqués sans système de priorité manuel.</p>

<h2>Conditions — table complète</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>Région ?</th><th>Valeur ?</th><th>Description</th></tr>
  <tr><td>0</td><td><code>enter_region</code></td><td>Oui</td><td>Non</td><td>Déclenché quand le joueur/caméra entre dans la région cible</td></tr>
  <tr><td>1</td><td><code>leave_region</code></td><td>Oui</td><td>Non</td><td>Déclenché à la sortie de la région</td></tr>
  <tr><td>2</td><td><code>cam_x_ge</code></td><td>Non</td><td>Oui (tiles)</td><td>Caméra X ≥ valeur (tiles). Idéal shmup/scroll horizontal</td></tr>
  <tr><td>3</td><td><code>cam_y_ge</code></td><td>Non</td><td>Oui (tiles)</td><td>Caméra Y ≥ valeur (tiles). Utile scroll vertical, donjons</td></tr>
  <tr><td>4</td><td><code>timer_ge</code></td><td>Non</td><td>Oui (frames)</td><td>Timer de scène ≥ valeur frames (60fps). Cutscenes, intro, timeout</td></tr>
  <tr><td>5</td><td><code>wave_ge</code></td><td>Non</td><td>Oui (index)</td><td>Vague courante ≥ index. Chaîner les vagues de spawn</td></tr>
  <tr><td>6</td><td><code>btn_a</code></td><td>Non</td><td>Non</td><td>Bouton A pressé. Interaction, skip cinématique</td></tr>
  <tr><td>7</td><td><code>btn_b</code></td><td>Non</td><td>Non</td><td>Bouton B pressé</td></tr>
  <tr><td>8</td><td><code>btn_a_b</code></td><td>Non</td><td>Non</td><td>Boutons A+B pressés ensemble. Utile pour raccourcis ou menus</td></tr>
  <tr><td>9</td><td><code>btn_up</code></td><td>Non</td><td>Non</td><td>Direction haut pressée. Navigation de menu, sélection verticale</td></tr>
  <tr><td>10</td><td><code>btn_down</code></td><td>Non</td><td>Non</td><td>Direction bas pressée. Navigation de menu, sélection verticale</td></tr>
  <tr><td>11</td><td><code>btn_left</code></td><td>Non</td><td>Non</td><td>Direction gauche pressée. Menus, embranchements, puzzle</td></tr>
  <tr><td>12</td><td><code>btn_right</code></td><td>Non</td><td>Non</td><td>Direction droite pressée. Menus, embranchements, puzzle</td></tr>
  <tr><td>13</td><td><code>btn_opt</code></td><td>Non</td><td>Non</td><td>Bouton Option (start/pause)</td></tr>
  <tr><td>14</td><td><code>on_jump</code></td><td>Non</td><td>Non</td><td>Le joueur vient de sauter. Utile puzzle ou effets de saut</td></tr>
  <tr><td>15</td><td><code>wave_cleared</code></td><td>Non</td><td>Oui (index)</td><td>Vague d'index "valeur" entièrement éliminée. Spawn boss, ouvre porte</td></tr>
  <tr><td>16</td><td><code>health_le</code></td><td>Non</td><td>Oui (HP)</td><td>HP joueur ≤ valeur. Musique danger, spawn items santé</td></tr>
  <tr><td>17</td><td><code>health_ge</code></td><td>Non</td><td>Oui (HP)</td><td>HP joueur ≥ valeur. Afficher indicateur pleine santé, reprendre musique</td></tr>
  <tr><td>18</td><td><code>enemy_count_le</code></td><td>Non</td><td>Oui (nb)</td><td>Nombre d'ennemis vivants ≤ valeur. Déclenche suite de combat</td></tr>
  <tr><td>19</td><td><code>lives_le</code></td><td>Non</td><td>Oui (nb)</td><td>Vies restantes ≤ valeur. Avertissement "dernière vie", difficulté dynamique</td></tr>
  <tr><td>20</td><td><code>lives_ge</code></td><td>Non</td><td>Oui (nb)</td><td>Vies restantes ≥ valeur. Débloquer bonus ou comportements spéciaux</td></tr>
  <tr><td>21</td><td><code>collectible_count_ge</code></td><td>Non</td><td>Oui (nb)</td><td>Nombre de collectibles ramassés ≥ valeur. Ouvre porte, valide objectif de collecte</td></tr>
  <tr><td>22</td><td><code>flag_set</code></td><td>Non</td><td>Non</td><td>Flag booléen[index] == 1. "Index" = champ <b>Index</b> (0–15). Utile progression inter-scènes, déverrouillages</td></tr>
  <tr><td>23</td><td><code>flag_clear</code></td><td>Non</td><td>Non</td><td>Flag booléen[index] == 0. Inverse de flag_set</td></tr>
  <tr><td>24</td><td><code>variable_ge</code></td><td>Non</td><td>Oui (seuil)</td><td>Variable u8[index] ≥ valeur. Compteur de clés, points de quête, niveau difficulté</td></tr>
  <tr><td>25</td><td><code>variable_eq</code></td><td>Non</td><td>Oui (cible)</td><td>Variable u8[index] == valeur. Etat exact (état boss, phase de puzzle)</td></tr>
  <tr><td>26</td><td><code>timer_every</code></td><td>Non</td><td>Oui (N frames)</td><td>Vrai toutes les N frames (<code>timer % N == 0</code>). Utile clignotement, spawn périodique, polling</td></tr>
  <tr><td>27</td><td><code>scene_first_enter</code></td><td>Non</td><td>Non</td><td>Vrai uniquement sur la première frame de la scène (<code>timer == 0</code>). Combiné à <code>once</code>, exécute une action à l'entrée</td></tr>
  <tr><td>28</td><td><code>on_nth_jump</code></td><td>Non</td><td>Oui (N)</td><td>Nième saut du joueur. value=0 = n'importe quel saut, 1=premier saut, 2=double saut, 3=triple, etc.</td></tr>
  <tr><td>29</td><td><code>on_wall_left</code></td><td>Non</td><td>Non</td><td>Joueur en contact avec un mur à gauche</td></tr>
  <tr><td>30</td><td><code>on_wall_right</code></td><td>Non</td><td>Non</td><td>Joueur en contact avec un mur à droite</td></tr>
  <tr><td>31</td><td><code>on_ladder</code></td><td>Non</td><td>Non</td><td>Joueur sur une tile échelle</td></tr>
  <tr><td>32</td><td><code>on_ice</code></td><td>Non</td><td>Non</td><td>Joueur sur une tile de glace</td></tr>
  <tr><td>33</td><td><code>on_conveyor</code></td><td>Non</td><td>Non</td><td>Joueur sur une tile convoyeur</td></tr>
  <tr><td>34</td><td><code>on_spring</code></td><td>Non</td><td>Non</td><td>Joueur sur une tile ressort</td></tr>
  <tr><td>35</td><td><code>player_has_item</code></td><td>Non</td><td>Oui (item_id)</td><td>Le joueur possède l'item sélectionné dans son inventaire. Sélecteur item dans l'UI.</td></tr>
  <tr><td>88</td><td><code>item_count_ge</code></td><td>Non</td><td>Oui (count)</td><td>Le joueur possède au moins <em>value</em> exemplaires de l'item sélectionné. Sélecteur item + spinner quantité. Utile pour craft/échange.</td></tr>
  <tr><td>36</td><td><code>npc_talked_to</code></td><td>Non</td><td>Oui (entity_id)</td><td>Le PNJ d'index value a reçu une interaction de dialogue</td></tr>
  <tr><td>37</td><td><code>count_eq</code></td><td>Non</td><td>Oui (count)</td><td>Compteur d'entités du type flag_var_index == value. Ex : ennemis restants, collectibles d'un type</td></tr>
  <tr><td>63</td><td><code>all_switches_on</code></td><td>Non</td><td>Non</td><td>Tous les interrupteurs de la scène sont activés. Puzzle "activer toutes les cases"</td></tr>
  <tr><td>64</td><td><code>block_on_tile</code></td><td>Région</td><td>Non</td><td>Un bloc poussable est positionné sur la région cible. Puzzle push-block classique</td></tr>
  <tr><td>65</td><td><code>dialogue_done</code></td><td>Non</td><td>Non</td><td>Le dialogue sélectionné a déjà été joué au moins une fois. Sélecteur combo dialogue (par ID). Utile pour chaîner les dialogues RPG ou poser un flag implicite</td></tr>
</table>

<h2>Conditions — genres RPG / stratégie / fighting / racing</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>Flag/Var idx</th><th>Valeur</th><th>Description</th></tr>
  <tr><td>38</td><td><code>entity_alive</code></td><td>Non</td><td>Oui (entity_id)</td><td>L'entité d'index value est vivante/active dans la scène</td></tr>
  <tr><td>39</td><td><code>entity_dead</code></td><td>Non</td><td>Oui (entity_id)</td><td>L'entité d'index value est morte/inactive</td></tr>
  <tr><td>40</td><td><code>quest_stage_eq</code></td><td>Oui (quest_id)</td><td>Oui (étape)</td><td>La quête flag_var_index est à l'étape exacte value. Exemple : quête 1, étape 3</td></tr>
  <tr><td>41</td><td><code>ability_unlocked</code></td><td>Non</td><td>Oui (ability_id)</td><td>La capacité d'index value est déverrouillée pour le joueur</td></tr>
  <tr><td>42</td><td><code>resource_ge</code></td><td>Oui (type)</td><td>Oui (seuil)</td><td>Ressource de type flag_var_index ≥ value (or, cristaux, mana, etc.)</td></tr>
  <tr><td>43</td><td><code>combo_ge</code></td><td>Non</td><td>Oui (N)</td><td>Compteur de combo ≥ value. Fighting / beat-em-up</td></tr>
  <tr><td>44</td><td><code>lap_ge</code></td><td>Non</td><td>Oui (N)</td><td>Tour / manche en cours ≥ value. Racing / survie par rounds</td></tr>
  <tr><td>45</td><td><code>btn_held_ge</code></td><td>Non</td><td>Oui (N frames)</td><td>N'importe quel bouton maintenu ≥ N frames. Charge, action longue</td></tr>
  <tr><td>46</td><td><code>chance</code></td><td>Non</td><td>Oui (% 0-100)</td><td>Probabilité aléatoire. Utile spawn ennemi optionnel, loot, événement rare</td></tr>
</table>

<h2>Conditions — événements joueur + états divers (IDs 47–54)</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>Flag/Var idx</th><th>Valeur</th><th>Description</th></tr>
  <tr><td>47</td><td><code>on_land</code></td><td>Non</td><td>Non</td><td>Joueur touche le sol après avoir été en l'air (atterrissage)</td></tr>
  <tr><td>48</td><td><code>on_hurt</code></td><td>Non</td><td>Non</td><td>Joueur subit des dégâts cette frame</td></tr>
  <tr><td>49</td><td><code>on_death</code></td><td>Non</td><td>Non</td><td>Compteur de vies décrémenté (mort du joueur)</td></tr>
  <tr><td>50</td><td><code>score_ge</code></td><td>Non</td><td>Oui (seuil u16)</td><td>Score actuel ≥ value. Utile pour déblocages basés sur le score</td></tr>
  <tr><td>51</td><td><code>timer_le</code></td><td>Non</td><td>Oui (frames)</td><td>Timer scène ≤ value. Compte à rebours, urgence</td></tr>
  <tr><td>52</td><td><code>variable_le</code></td><td>Oui (idx)</td><td>Oui (seuil)</td><td>Variable u8[index] ≤ value. Complément de variable_ge</td></tr>
  <tr><td>53</td><td><code>on_crouch</code></td><td>Non</td><td>Non</td><td>Joueur dans l'état accroupi</td></tr>
  <tr><td>54</td><td><code>cutscene_done</code></td><td>Non</td><td>Oui (cutscene_id)</td><td>La cinématique d'index value vient de se terminer</td></tr>
</table>

<h2>Actions — genres RPG / stratégie / fighting (IDs 45–50)</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>45</td><td><code>add_resource</code></td><td>resource_type (u8)</td><td>amount (u8)</td><td>Ajoute amount à la ressource de type a0 (or, cristaux, mana, etc.)</td></tr>
  <tr><td>46</td><td><code>remove_resource</code></td><td>resource_type (u8)</td><td>amount (u8)</td><td>Retire amount de la ressource de type a0 (ne passe pas sous 0)</td></tr>
  <tr><td>47</td><td><code>unlock_ability</code></td><td>ability_id (u8)</td><td>—</td><td>Déverrouille la capacité d'index a0 pour le joueur (double saut, dash, etc.)</td></tr>
  <tr><td>48</td><td><code>set_quest_stage</code></td><td>quest_id (u8)</td><td>stage (u8)</td><td>Définit la quête a0 à l'étape a1. Progression RPG / aventure</td></tr>
  <tr><td>49</td><td><code>play_cutscene</code></td><td>cutscene_id (u8)</td><td>—</td><td>Lance la cinématique d'index a0. Nécessite votre table de cinématiques dans le runtime</td></tr>
  <tr><td>50</td><td><code>end_game</code></td><td>result (u8)</td><td>—</td><td>Termine la partie. a0=0=défaite, a0=1=victoire, a0=2=crédits</td></tr>
</table>

<h2>Actions — santé, vies, entités, timer, score (IDs 51–62)</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>51</td><td><code>dec_variable</code></td><td>var_idx (0–15)</td><td>floor cap (0=libre)</td><td>Décrémente variable u8[index]. Si cap > 0, plancher à cette valeur.</td></tr>
  <tr><td>52</td><td><code>add_health</code></td><td>amount (u8)</td><td>—</td><td>Ajoute amount PV au joueur (plafonné au max)</td></tr>
  <tr><td>53</td><td><code>set_health</code></td><td>value (u8)</td><td>—</td><td>Définit les PV du joueur à exactement value</td></tr>
  <tr><td>54</td><td><code>add_lives</code></td><td>amount (u8)</td><td>—</td><td>Donne amount vies supplémentaires au joueur</td></tr>
  <tr><td>55</td><td><code>set_lives</code></td><td>value (u8)</td><td>—</td><td>Définit le compteur de vies à exactement value</td></tr>
  <tr><td>56</td><td><code>destroy_entity</code></td><td>entity_idx (u8)</td><td>—</td><td>Retire l'entité d'index a0 de la scène (mort instantanée)</td></tr>
  <tr><td>57</td><td><code>teleport_player</code></td><td>region_idx (u8)</td><td>—</td><td>Téléporte le joueur au centre de la région spawn a0</td></tr>
  <tr><td>58</td><td><code>toggle_flag</code></td><td>flag_idx (0–15)</td><td>—</td><td>Bascule le flag booléen[a0] (0→1, 1→0)</td></tr>
  <tr><td>59</td><td><code>set_score</code></td><td>score_hi (u8)</td><td>score_lo (u8)</td><td>Définit le score = (a0×256)+a1 (max 65535)</td></tr>
  <tr><td>60</td><td><code>set_timer</code></td><td>frames (u8)</td><td>—</td><td>Remet le timer de scène à a0 frames</td></tr>
  <tr><td>61</td><td><code>pause_timer</code></td><td>—</td><td>—</td><td>Fige le timer de scène (utile pendant une cinématique)</td></tr>
  <tr><td>62</td><td><code>resume_timer</code></td><td>—</td><td>—</td><td>Relance le timer de scène après une pause</td></tr>
</table>

<h2>Conditions — physique eau + événements attaque/dash (IDs 55–62)</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>Région</th><th>Valeur</th><th>Description</th></tr>
  <tr><td>55</td><td><code>enemy_count_ge</code></td><td>Non</td><td>Oui (N)</td><td>Nombre d’ennemis actifs ≥ value. Complément de enemy_count_le</td></tr>
  <tr><td>56</td><td><code>variable_ne</code></td><td>Non</td><td>Oui</td><td>Variable u8[index] ≠ value. Ferme le jeu de comparaisons (ge/eq/le/ne)</td></tr>
  <tr><td>57</td><td><code>health_eq</code></td><td>Non</td><td>Oui (PV)</td><td>PV joueur == value exactement. “Si 1 PV restant”</td></tr>
  <tr><td>58</td><td><code>on_swim</code></td><td>Non</td><td>Non</td><td>Joueur dans une tile d’eau (état nage)</td></tr>
  <tr><td>59</td><td><code>on_dash</code></td><td>Non</td><td>Non</td><td>Joueur déclenche un dash cette frame</td></tr>
  <tr><td>60</td><td><code>on_attack</code></td><td>Non</td><td>Non</td><td>Joueur déclenche une attaque (frame active hitbox)</td></tr>
  <tr><td>61</td><td><code>on_pickup</code></td><td>Non</td><td>Non</td><td>Joueur ramasse un collectible cette frame</td></tr>
  <tr><td>62</td><td><code>entity_in_region</code></td><td>Oui (région)</td><td>Oui (entity_id)</td><td>L’entité d’index value se trouve dans la région sélectionnée</td></tr>
</table>

<h2>Actions — fondu, caméra, combo, spawn, sauvegarde, audio (IDs 63–72)</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>63</td><td><code>fade_out</code></td><td>durée (frames)</td><td>—</td><td>Fondu vers le noir en a0 frames (0 = instantané). Utilise ngpc_palfx.</td></tr>
  <tr><td>64</td><td><code>fade_in</code></td><td>durée (frames)</td><td>—</td><td>Fondu depuis le noir en a0 frames.</td></tr>
  <tr><td>65</td><td><code>camera_lock</code></td><td>—</td><td>—</td><td>Fige la caméra à sa position courante (stoppe le suivi joueur).</td></tr>
  <tr><td>66</td><td><code>camera_unlock</code></td><td>—</td><td>—</td><td>Reprend le suivi joueur par la caméra.</td></tr>
  <tr><td>67</td><td><code>add_combo</code></td><td>amount (u8)</td><td>—</td><td>Ajoute a0 points au compteur de combo.</td></tr>
  <tr><td>68</td><td><code>reset_combo</code></td><td>—</td><td>—</td><td>Remet le compteur de combo à 0.</td></tr>
  <tr><td>69</td><td><code>flash_screen</code></td><td>intensité (u8)</td><td>durée (frames)</td><td>Flash d’écran coloré. a0=intensité, a1=durée. Utilise ngpc_palfx.</td></tr>
  <tr><td>70</td><td><code>spawn_at_region</code></td><td>entity_type (u8)</td><td>region_idx (u8)</td><td>Spawne une entité du type a0 au centre de la région a1.</td></tr>
  <tr><td>71</td><td><code>save_game</code></td><td>—</td><td>—</td><td>Déclenche une sauvegarde flash. Nécessite ngpc_flash_save dans le runtime.</td></tr>
  <tr><td>72</td><td><code>set_bgm_volume</code></td><td>volume (0-255)</td><td>—</td><td>Ajuste le volume de lecture du BGM courant.</td></tr>
  <tr><td>76</td><td><code>flip_sprite_h</code></td><td>—</td><td>—</td><td>Bascule le retournement horizontal du sprite joueur (face_hflip ^= 1). Utile en top-down.</td></tr>
  <tr><td>77</td><td><code>flip_sprite_v</code></td><td>—</td><td>—</td><td>Bascule le retournement vertical du sprite joueur (face_vflip ^= 1). Utile en top-down.</td></tr>
</table>

<h2>Logique OR entre groupes de conditions (TRIG-OR1)</h2>
<p>La section <b>Groupes alternatifs (OR)</b> permet de définir des groupes de conditions supplémentaires. Le trigger se déclenche si :</p>
<ul>
  <li>La condition principale (ET ses conditions AND supplémentaires) est vraie, <b>OU</b></li>
  <li>N'importe quel groupe OR est entièrement vrai (toutes ses conditions sont vraies en même temps)</li>
</ul>
<p>Exemple : <code>(health_le 20 AND flag_set 3) OR (scene_first_enter AND btn_a)</code></p>
<p>Le JSON exporté contient <code>or_groups</code> = liste de groupes, chaque groupe = liste de <code>NgpngCond</code>. Les tableaux C générés sont : <code>trig_or_conds[]</code>, <code>trig_or_cond_start[]</code>, <code>trig_or_cond_count[]</code>, <code>trig_or_group_start[]</code>, <code>trig_or_group_count[]</code>.</p>

<h2>Actions — table complète</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>0</td><td><code>emit_event</code></td><td>id événement</td><td>—</td><td>Déclenche un événement personnalisé. L'id est choisi dans le combo nommé (<code>CEV_*</code>). Les actions liées sont définies dans <b>Globals → Événements</b> et exportées dans <code>ngpc_custom_events.h</code>.</td></tr>
  <tr><td>1</td><td><code>play_sfx</code></td><td>sfx_id (u8)</td><td>—</td><td>Joue un SFX gameplay. Nécessite votre mapping SFX.</td></tr>
  <tr><td>2</td><td><code>start_bgm</code></td><td>song_idx (u8)</td><td>—</td><td>Lance un BGM (index Sound Creator).</td></tr>
  <tr><td>3</td><td><code>stop_bgm</code></td><td>—</td><td>—</td><td>Coupe le BGM immédiatement.</td></tr>
  <tr><td>4</td><td><code>fade_bgm</code></td><td>fade_spd (u8)</td><td>—</td><td>Fondu BGM. 0 = coupure nette.</td></tr>
  <tr><td>5</td><td><code>goto_scene</code></td><td>scene_idx (u8)</td><td>—</td><td>Change de scène. Choisissez la cible dans le sélecteur.</td></tr>
  <tr><td>6</td><td><code>spawn_wave</code></td><td>wave_idx (u8)</td><td>—</td><td>Force le spawn d'une vague par son index.</td></tr>
  <tr><td>7</td><td><code>pause_scroll</code></td><td>—</td><td>—</td><td>Suspend le scroll forcé (boss arena).</td></tr>
  <tr><td>8</td><td><code>resume_scroll</code></td><td>—</td><td>—</td><td>Reprend le scroll forcé.</td></tr>
  <tr><td>9</td><td><code>spawn_entity</code></td><td>ent_type (u8)</td><td>slot (u8)</td><td>Spawne une entité dans un slot de spawn_slots[].</td></tr>
  <tr><td>10</td><td><code>set_scroll_speed</code></td><td>spd_x (u8)</td><td>spd_y (u8)</td><td>Change la vitesse du scroll forcé à la volée.</td></tr>
  <tr><td>11</td><td><code>play_anim</code></td><td>ent_type (u8)</td><td>anim_state (u8)</td><td>Force l'état d'animation d'un type d'entité.</td></tr>
  <tr><td>12</td><td><code>force_jump</code></td><td>ent_type (u8)</td><td>—</td><td>Force un saut sur un type d'entité (IA ou joueur).</td></tr>
  <tr><td>23</td><td><code>fire_player_shot</code></td><td>—</td><td>—</td><td>Déclenche un tir joueur natif. <b>Legacy :</b> toujours supporté via trigger. <b>Recommandé :</b> utiliser le groupe <i>Tir</i> dans Level → Entité pour configurer bouton + bullet sprite — l'autorun tire alors automatiquement.</td></tr>
  <tr><td>13</td><td><code>enable_trigger</code></td><td>trig_idx (u8)</td><td>—</td><td>Active un trigger désactivé (par index dans la liste).</td></tr>
  <tr><td>14</td><td><code>disable_trigger</code></td><td>trig_idx (u8)</td><td>—</td><td>Désactive un trigger (il ne se déclenchera plus).</td></tr>
  <tr><td>15</td><td><code>screen_shake</code></td><td>intensity (u8)</td><td>duration (u8)</td><td>Secousse d'écran. Intensité 0–255, durée en frames.</td></tr>
  <tr><td>16</td><td><code>set_cam_target</code></td><td>cam_x (u8)</td><td>cam_y (u8)</td><td>Déplace la cible caméra en tiles.</td></tr>
  <tr><td>18</td><td><code>show_entity</code></td><td>entity_idx (u8)</td><td>—</td><td>Affiche une entité statique déjà placée dans la scène. Pratique pour un curseur ou une option de menu.</td></tr>
  <tr><td>19</td><td><code>hide_entity</code></td><td>entity_idx (u8)</td><td>—</td><td>Masque une entité statique déjà placée dans la scène.</td></tr>
  <tr><td>20</td><td><code>move_entity_to</code></td><td>entity_idx (u8)</td><td>region_idx (u8)</td><td>Déplace une entité statique vers une région cible. Bon point de base pour des menus ou des pointeurs.</td></tr>
  <tr><td>21</td><td><code>cycle_player_form</code></td><td>—</td><td>—</td><td>Passe à la forme joueur suivante. Active le mode “une forme visible à la fois” dans l'autorun.</td></tr>
  <tr><td>22</td><td><code>set_player_form</code></td><td>form_idx (u8)</td><td>—</td><td>Force une forme joueur précise par index. 0 = première forme exportée avec le rôle <code>player</code>.</td></tr>
  <tr><td>24</td><td><code>set_checkpoint</code></td><td>region_idx (u8)</td><td>—</td><td>Mémorise explicitement une région de checkpoint. Pratique si vous voulez piloter le respawn par trigger.</td></tr>
  <tr><td>25</td><td><code>respawn_player</code></td><td>—</td><td>—</td><td>Force immédiatement un respawn joueur sur le checkpoint courant. Sans checkpoint valide, le runtime retombe sur le spawn d'entrée.</td></tr>
  <tr><td>26</td><td><code>pause_entity_path</code></td><td>entity_idx (u8)</td><td>—</td><td>Met en pause le suivi de path d'une entité statique, utile pour une plateforme mobile ou un lift.</td></tr>
  <tr><td>27</td><td><code>resume_entity_path</code></td><td>entity_idx (u8)</td><td>—</td><td>Relance le suivi de path d'une entité statique liée à un <code>Path</code>.</td></tr>
  <tr><td>28</td><td><code>set_flag</code></td><td>flag_idx (0–15)</td><td>—</td><td>Met le flag booléen[index] à 1. L'index est dans le champ <b>Index</b> de l'UI trigger.</td></tr>
  <tr><td>29</td><td><code>clear_flag</code></td><td>flag_idx (0–15)</td><td>—</td><td>Remet le flag booléen[index] à 0.</td></tr>
  <tr><td>30</td><td><code>set_variable</code></td><td>var_idx (0–15)</td><td>valeur (u8)</td><td>Assigne directement variable u8[index] = valeur (champ <b>Valeur</b>).</td></tr>
  <tr><td>31</td><td><code>inc_variable</code></td><td>var_idx (0–15)</td><td>cap (0=libre)</td><td>Incrémente variable u8[index]. Si cap &gt; 0, plafonne à cette valeur.</td></tr>
  <tr><td>32</td><td><code>warp_to</code></td><td>scene_idx (u8)</td><td>spawn_idx (u8)</td><td>Change de scène <i>et</i> place le joueur au centre de la région <code>spawn</code> numéro spawn_idx de la scène cible.</td></tr>
  <tr><td>33</td><td><code>lock_player_input</code></td><td>—</td><td>—</td><td>Zéroïse <code>ngpc_pad_held</code> et <code>ngpc_pad_pressed</code> chaque frame jusqu'à unlock. Utile pour cinématiques ou dialogues.</td></tr>
  <tr><td>34</td><td><code>unlock_player_input</code></td><td>—</td><td>—</td><td>Relâche le verrou posé par <code>lock_player_input</code>. Le joueur récupère le contrôle dès la frame suivante.</td></tr>
  <tr><td>35</td><td><code>enable_multijump</code></td><td>max_jumps (2–5)</td><td>—</td><td>Active le multi-saut pour le joueur avec un plafond de max_jumps sauts en l'air.</td></tr>
  <tr><td>36</td><td><code>disable_multijump</code></td><td>—</td><td>—</td><td>Désactive le multi-saut. Retour au comportement saut standard.</td></tr>
  <tr><td>37</td><td><code>reset_scene</code></td><td>—</td><td>—</td><td>Recharge la scène courante depuis zéro (positions, entités, timer). Utile mort du joueur, puzzle raté.</td></tr>
  <tr><td>38</td><td><code>show_dialogue</code></td><td>dlg_idx (u8)</td><td>—</td><td>Affiche le dialogue d'index a0. L'index est résolu depuis l'ID de dialogue de l'onglet <b>Dialogues</b> (stable après réorganisation). Génère <code>g_dlg_*[]</code> dans <code>scene_*_dialogs.h</code>.</td></tr>
  <tr><td>74</td><td><code>set_npc_dialogue</code></td><td>entity_idx (u8)</td><td>dlg_idx (u8)</td><td>Change le dialogue du NPC a0 pour le dialogue a1. Permet à un PNJ de donner une réplique différente selon l'avancement. Sélecteurs entité + dialogue dans l'UI.</td></tr>
  <tr><td>39</td><td><code>give_item</code></td><td>item_id (u8)</td><td>—</td><td>Ajoute l'item sélectionné directement à l'inventaire du joueur (sans visuel sur la map). Sélecteur item dans l'UI.</td></tr>
  <tr><td>40</td><td><code>remove_item</code></td><td>item_id (u8)</td><td>—</td><td>Retire l'item sélectionné de l'inventaire du joueur. Sélecteur item dans l'UI.</td></tr>
  <tr><td>78</td><td><code>drop_item</code></td><td>item_id (u8)</td><td>—</td><td>Fait apparaître un pickup visuel de l'item sélectionné à la position de l'entité. Le runtime utilise <code>g_item_table[a0].sprite_id</code> pour l'affichage. Cas classique : <code>on_death → drop_item</code> pour qu'un monstre lâche un item. Sélecteur item dans l'UI.</td></tr>
  <tr><td>79</td><td><code>drop_random_item</code></td><td>—</td><td>—</td><td>Fait apparaître un pickup visuel d'un item aléatoire tiré de <code>CAVEGEN_ITEM_POOL</code> (ou de tous les items si le pool est vide). Utile pour un monstre générique qui peut lâcher n'importe quoi.</td></tr>
  <tr><td>41</td><td><code>unlock_door</code></td><td>door_id (u8)</td><td>—</td><td>Déverrouille la porte d'index door_id (entité de type porte dans la scène).</td></tr>
  <tr><td>42</td><td><code>enable_wall_grab</code></td><td>—</td><td>—</td><td>Active l'agrippement de mur pour le joueur.</td></tr>
  <tr><td>43</td><td><code>disable_wall_grab</code></td><td>—</td><td>—</td><td>Désactive l'agrippement de mur.</td></tr>
  <tr><td>44</td><td><code>set_gravity_dir</code></td><td>dir (u8)</td><td>—</td><td>Change la direction de la gravité du joueur. 0=bas (normal), 1=haut (inversé), 2=aucune (apesanteur).</td></tr>
</table>
<p><b>Validation export :</b> les références cassées (scène, trigger, entité, région) sont maintenant détectées avant génération du <code>scene_*_level.h</code>. Un export GUI, projet ou headless bloquera la scène concernée au lieu de produire un header incohérent.</p>
<p><b>Autorun template (couverture V1) :</b> la preview runtime générée exécute maintenant aussi un noyau utile d'actions exportées :
<code>spawn_wave</code>, <code>pause_scroll</code>, <code>resume_scroll</code>, <code>set_scroll_speed</code>,
<code>set_cam_target</code>, <code>enable_trigger</code>, <code>disable_trigger</code>,
<code>show_entity</code>, <code>hide_entity</code>, <code>move_entity_to</code>,
<code>pause_entity_path</code>, <code>resume_entity_path</code>,
<code>cycle_player_form</code>, <code>set_player_form</code>, <code>fire_player_shot</code>,
<code>set_checkpoint</code>, <code>respawn_player</code>,
<code>set_flag</code>, <code>clear_flag</code>, <code>set_variable</code>, <code>inc_variable</code>, <code>warp_to</code>,
<code>lock_player_input</code> et <code>unlock_player_input</code>.
En preview, <code>play_anim</code> agit sur les props statiques, et <code>force_jump</code> agit sur les ennemis à gravité déjà spawnés.</p>
<p><b>Gameplay plus intuitif :</b> l'onglet Triggers propose aussi désormais des presets rapides <b>Tir joueur sur A</b> et <b>Attaque joueur (event) sur A</b>. Le premier utilise l'action native <code>fire_player_shot</code>; le second prépare un <code>emit_event</code> sémantique quand votre runtime gère une attaque melee ou un comportement custom.</p>
<p><b>Conditions runtime couvertes :</b> la preview autorun couvre aussi maintenant <code>on_jump</code> sur le joueur principal. Les triggers basés sur le saut ne sont donc plus seulement “documentaires” dans le template fourni.</p>
<p><b>Départ rapide</b> : si vous voulez un trigger “posé à la main”, commencez en pratique par dessiner une <b>région</b> sur la scène, puis utilisez les actions rapides <b>Enter</b> / <b>Leave</b> de l’onglet Triggers. Le format exporté V1 est surtout <b>région + condition + action</b>, pas encore un système de points libres indépendants.</p>

<p><b>HUD custom / UI runtime :</b> en plus de <code>health_le</code>, la preview comprend maintenant aussi
<code>health_ge</code>, <code>lives_le</code> et <code>lives_ge</code>. C'est la base la plus pratique pour piloter
un HUD en entités statiques : cœurs, segments de barre, icônes de vies, etc., via <code>show_entity</code> /
<code>hide_entity</code>.</p>

<h2>Presets de menus graphiques</h2>
<p>Le bloc <b>Preset</b> de l'onglet Triggers sert à créer rapidement des triggers V1 pour interfaces et menus sans repartir de zéro.</p>
<ul>
  <li>Si vous avez déjà sélectionné une <b>région</b>, le preset la réutilise comme zone source quand c'est pertinent.</li>
  <li>Si vous avez déjà sélectionné une <b>entité statique</b> dans la scène, le preset la réutilise comme cible pour les actions show/hide/move.</li>
  <li>Le preset ne remplace pas les réglages finaux : après création, vérifiez la scène cible, le SFX ou la région de destination selon le cas.</li>
</ul>
<table>
  <tr><th>Preset</th><th>Condition créée</th><th>Action créée</th><th>Usage</th></tr>
  <tr><td><b>Curseur sur entrée région</b></td><td><code>enter_region</code></td><td><code>move_entity_to</code></td><td>Déplace un curseur ou pointeur vers la région survolée. Donnez ensuite l'entité curseur et, si besoin, la région de destination.</td></tr>
  <tr><td><b>Afficher entité sur entrée</b></td><td><code>enter_region</code></td><td><code>show_entity</code></td><td>Montre une option, une info-bulle ou un décor d'UI quand la zone devient active.</td></tr>
  <tr><td><b>Masquer entité sur sortie</b></td><td><code>leave_region</code></td><td><code>hide_entity</code></td><td>Cache un élément d'UI quand on quitte une zone de menu.</td></tr>
  <tr><td><b>Valider menu -&gt; scène</b></td><td><code>btn_a</code></td><td><code>goto_scene</code></td><td>Confirme une option avec A puis charge la scène choisie dans le sélecteur.</td></tr>
  <tr><td><b>SFX au survol de région</b></td><td><code>enter_region</code></td><td><code>play_sfx</code></td><td>Joue un son de navigation quand le curseur entre dans une zone.</td></tr>
</table>
<p><b>Limites V1 :</b> ces presets posent la structure sans code, mais il n'y a pas encore de <code>move_entity_lerp</code>, d'easing ni de répétition automatique de menu côté runtime. Ils couvrent déjà les cas simples : curseur, options visibles/masquées, validation de scène et hover SFX.</p>

<h2>Conditions ET multiples (AND)</h2>
<p>Un trigger a une <b>condition primaire</b> (champs Condition + Région/Valeur) et peut avoir
des <b>conditions ET supplémentaires</b> dans le groupe "Conditions ET" en bas du panneau.</p>
<ul>
  <li>Cliquez <b>+</b> pour ajouter une condition ET.</li>
  <li>Sélectionnez une ligne pour éditer son type (combo), région ou valeur.</li>
  <li>Cliquez <b>−</b> pour supprimer la condition sélectionnée.</li>
  <li>Le trigger ne se déclenche que si <b>toutes</b> les conditions sont vraies simultanément.</li>
</ul>
<p><b>Export :</b> quand au moins un trigger a des conditions ET, l'export génère :</p>
<pre>typedef struct &#123; u8 cond; u8 region; u16 value; &#125; NgpngCond;
static const NgpngCond g_scene_trig_conds[] = &#123; ... &#125;;
static const u8 g_scene_trig_cond_count[] = &#123; 0, 2, 0, 1, ... &#125;;
static const u8 g_scene_trig_cond_start[] = &#123; 0, 0, 2, 2, ... &#125;;</pre>
<p>Le runtime itère <code>trig_conds[start..start+count-1]</code> pour vérifier les ET. L’autorun template généré lit maintenant aussi ces tableaux, donc la preview respecte enfin les triggers AND simples sans code manuel supplémentaire.</p>

<h2>Dupliquer un trigger (⧉ Dup)</h2>
<p>Le bouton <b>⧉ Dup</b> à côté du champ Nom crée une copie du trigger sélectionné
(nouveau ID, nouveau nom automatique <code>nom_2</code>, <code>nom_3</code>…).
Le duplicate est inséré juste après l'original et sélectionné automatiquement.</p>
<p>Usage typique : créer une série de triggers similaires (ex. 4 régions de spawn avec la même action) :
dupliquez et changez uniquement la région cible.</p>

<h2>Props par instance (entités)</h2>
<p>Dans le panneau de propriétés d'une entité sélectionnée (onglet Entities), vous pouvez définir :</p>
<table>
  <tr><th>Champ</th><th>Valeurs</th><th>Description</th></tr>
  <tr><td><b>Direction</b></td><td>0=droite, 1=gauche, 2=haut, 3=bas</td><td>Direction initiale de spawn</td></tr>
  <tr><td><b>Comportement</b></td><td>0=patrol, 1=chase, 2=fixed, 3=random</td><td>IA par défaut</td></tr>
  <tr><td><b>Chemin</b></td><td>(aucun) ou nom d'un chemin de la scène</td><td>Assigne ce path à l'entité sélectionnée ; l'export écrit son index dans paths[]</td></tr>
</table>
<p>Ces champs génèrent des tables C parallèles à <code>g_scene_entities[]</code> :</p>
<pre>static const u8 g_scene_ent_dirs[]      = &#123; 0, 1, 0, 2, ... &#125;;
static const u8 g_scene_ent_behaviors[] = &#123; 0, 0, 2, 1, ... &#125;;
static const u8 g_scene_ent_paths[]     = &#123; 255, 0, 255, 1, ... &#125;; /* 255=aucun */</pre>
<p>Ces tables ne sont générées que si au moins une entité a une valeur non-nulle/non-255.</p>

<h2>Paramètres IA par entité (TRIG-7)</h2>
<p>Lorsque le comportement d'un ennemi est sélectionné, un panneau <b>Paramètres IA</b> apparaît sous les props d'instance et expose des spinboxes contextuelles :</p>
<table>
  <tr><th>Champ</th><th>Comportements</th><th>Description</th><th>Export C</th></tr>
  <tr><td><b>Vitesse</b></td><td>patrol, chase, random</td><td>Déplacement en px/frame (1–255, défaut 1)</td><td><code>g_{sym}_ent_ai_speed[]</code> si ≥ 1 valeur ≠ 1</td></tr>
  <tr><td><b>Portée aggro</b></td><td>chase</td><td>Rayon de détection joueur (valeur × 8 px, défaut 80 px)</td><td><code>g_{sym}_ent_ai_range[]</code> si chase présent</td></tr>
  <tr><td><b>Portée perte</b></td><td>chase</td><td>Rayon d'abandon de la poursuite (valeur × 8 px, défaut 128 px)</td><td><code>g_{sym}_ent_ai_lose_range[]</code> si chase présent</td></tr>
  <tr><td><b>Chg. direction</b></td><td>random</td><td>Frames entre deux changements de direction aléatoire (1–255, défaut 60)</td><td><code>g_{sym}_ent_ai_change_every[]</code> si random présent</td></tr>
</table>
<p>Seules les tables nécessaires sont émises ; les valeurs défaut ne gonflent pas le code. Exemple :</p>
<pre>#define LEVEL1_ENTITY_AI_SPEED_TABLE 1
static const u8 g_level1_ent_ai_speed[]         = &#123;   1,   2,   1,   4 &#125;;  /* px/frame */

#define LEVEL1_ENTITY_AI_RANGE_TABLE 1
static const u8 g_level1_ent_ai_range[]         = &#123;  10,   8,  10,   0 &#125;;  /* x8 px */
static const u8 g_level1_ent_ai_lose_range[]    = &#123;  16,  12,  16,   0 &#125;;  /* x8 px */

#define LEVEL1_ENTITY_AI_CHANGE_TABLE 1
static const u8 g_level1_ent_ai_change_every[]  = &#123;  60,  60,  30,  60 &#125;;  /* frames */</pre>
<p>Le comportement <b>fixed</b> n'affiche aucun paramètre (l'entité est stationnaire).</p>

<h2>Structure export C (<code>_scene.h</code>)</h2>
<pre>/* Régions */
typedef struct &#123; u8 x; u8 y; u8 w; u8 h; u8 kind; &#125; NgpngRegion;
static const NgpngRegion g_scene_regions[] = &#123; ... &#125;;

/* Triggers */
typedef struct &#123; u8 cond; u8 region; u16 value; u8 action; u8 a0; u8 a1; u8 once; &#125; NgpngTrigger;
static const NgpngTrigger g_scene_triggers[] = &#123; ... &#125;;

/* Conditions ET (seulement si nécessaire) */
typedef struct &#123; u8 cond; u8 region; u16 value; &#125; NgpngCond;
static const NgpngCond  g_scene_trig_conds[]       = &#123; ... &#125;;
static const u8         g_scene_trig_cond_count[]  = &#123; ... &#125;;
static const u8         g_scene_trig_cond_start[]  = &#123; ... &#125;;

/* Points de spawn (régions kind=spawn) — cibles de warp_to */
#define SCENE_XXX_SPAWN_COUNT 2
static const NgpngPoint g_xxx_spawn_points[] = &#123; &#123;80, 64&#125;, &#123;200, 120&#125; &#125;;</pre>

<h2>Patterns pratiques par genre</h2>
<table>
  <tr><th>Genre</th><th>Pattern</th><th>Recette</th></tr>
  <tr><td>Shmup</td><td>Spawn vague 2 après vague 1 éliminée</td><td>cond=wave_cleared(0) → spawn_wave(1)</td></tr>
  <tr><td>Shmup</td><td>Pause scroll pour boss</td><td>cond=wave_ge(5) → pause_scroll ; une fois le boss mort : cond=wave_cleared(5) → resume_scroll</td></tr>
  <tr><td>Shmup</td><td>Musique danger bas HP</td><td>cond=health_le(3) → start_bgm(DANGER_BGM)</td></tr>
  <tr><td>RPG/Donjon</td><td>Transition de salle simple</td><td>cond=enter_region(porte) → goto_scene(salle_suivante)</td></tr>
  <tr><td>RPG/Donjon</td><td>Porte avec téléportation précise</td><td>cond=enter_region(porte) → warp_to(salle_B, spawn_idx=1) — place le joueur au spawn[1] de la salle B</td></tr>
  <tr><td>RPG/Donjon</td><td>Spawn boss sur switch</td><td>cond=btn_a + wave_cleared(0) (ET) → spawn_entity(BOSS, slot0)</td></tr>
  <tr><td>Progression</td><td>Déverrouiller une zone via flag</td><td>cond=flag_set(index=0) + enter_region(porte_verrouillée) → goto_scene(zone2)</td></tr>
  <tr><td>Progression</td><td>Compteur de clés pour porte</td><td>enter_region(clé) → inc_variable(0) ; cond=variable_ge(0,3) → emit_event(PORTE_OUVERTE)</td></tr>
  <tr><td>Platformer</td><td>Checkpoint musique</td><td>cond=enter_region(zone2) → start_bgm(2) ; once ✓</td></tr>
  <tr><td>Platformer</td><td>Séquence scriptée</td><td>trig1: enter_region → screen_shake(4,30) ; trig2: disable_trigger(trig1), spawn_wave(0)</td></tr>
  <tr><td>Puzzle</td><td>Ouvrir porte sur saut</td><td>cond=on_jump + enter_region(pad) (ET) → emit_event(EV_DOOR, door_id)</td></tr>
  <tr><td>Tous</td><td>Intro audio</td><td>cond=timer_ge(60) → start_bgm(0) ; once ✓</td></tr>
</table>

<h2>Conseils</h2>
<ul>
  <li><b>Ordonnez vos triggers</b> : le runtime les parcourt dans l'ordre. Mettez les conditions fréquentes en premier.</li>
  <li><b>Utilisez "once"</b> pour les transitions (musique, scène) afin de ne pas les rejouer à chaque frame.</li>
  <li><b>Chaîner enable/disable_trigger</b> : créez des triggers désactivés et activez-les via d'autres triggers pour simuler un état machine simple.</li>
  <li><b>cam_x_ge / cam_y_ge</b> sont souvent préférables à enter_region pour un shmup : pas besoin de dessiner une région, juste un seuil.</li>
  <li><b>Les conditions ET</b> permettent de combiner sans code : ex. wave_cleared(0) ET enter_region(zone2) → ne déclenche que si le joueur est dans la bonne zone ET la vague est finie.</li>
</ul>
"""


# ---------------------------------------------------------------------------
# Triggers & Regions — EN
# ---------------------------------------------------------------------------

def _en_triggers() -> str:
    return """
<h1>Triggers &amp; Regions — Complete Reference</h1>

<p>This topic is the exhaustive reference for the Level Editor's trigger/region system.
For a general overview of the Level tab, see <b>Level Editor</b>.</p>

<h2>Workflow (summary)</h2>
<ol>
  <li>Create <b>Regions</b> (Regions tab): draw a rectangle on the grid, name it, pick its kind.</li>
  <li>Create <b>Triggers</b> (Triggers tab): click <i>+ Add</i>, pick a condition, pick an action.</li>
  <li>Need <b>multiple conditions to be true at once</b>? Add AND conditions in the "AND conditions" group at the bottom.</li>
  <li>Use <b>⧉ Dup</b> to duplicate an existing trigger and make variants quickly.</li>
  <li>Save to project → Export (<code>_scene.h</code>).</li>
</ol>

<h2>Region kinds</h2>
<table>
  <tr><th>Kind</th><th>ID</th><th>Colour</th><th>Use</th></tr>
  <tr><td><b>zone</b></td><td>0</td><td>Purple</td><td>Generic zone (fires enter/leave_region)</td></tr>
  <tr><td><b>no_spawn</b></td><td>1</td><td>Orange</td><td>Procgen never places entities inside</td></tr>
  <tr><td><b>danger_zone</b></td><td>2</td><td>Red</td><td>Hazard area (runtime decides: death, damage, checkpoint…)</td></tr>
  <tr><td><b>checkpoint</b></td><td>3</td><td>Green</td><td>Native autorun respawn point. Entering it stores both the respawn scene and region.</td></tr>
  <tr><td><b>exit_goal</b></td><td>4</td><td>Yellow</td><td>Native autorun exit. Entering it loads the next scene, or reuses an explicit <code>goto_scene</code> already attached to the same region.</td></tr>
  <tr><td><b>camera_lock</b></td><td>5</td><td>Blue</td><td>Native autorun camera lock. In <code>follow</code> mode, the camera stays clamped to that room/section while the player remains inside it.</td></tr>
  <tr><td><b>spawn</b></td><td>6</td><td>Cyan</td><td>Spawn point (target of <code>warp_to</code>). The region centre defines the pixel teleport position. Indexed by order among spawn regions in the scene.</td></tr>
  <tr><td><b>attractor</b></td><td>7</td><td>—</td><td>Pulls the player toward the region centre. Adds <code>zone_force</code> px/frame to <code>vx</code>/<code>vy</code> toward the centre every frame the player is inside (on-ground or airborne).</td></tr>
  <tr><td><b>repulsor</b></td><td>8</td><td>—</td><td>Pushes the player away from the region centre. Same logic, reversed direction. Useful for force fields, exhaust fans, and push-back zones.</td></tr>
</table>
<p>All regions are exported to C with their coordinates (x, y, w, h) and kind.</p>
<p><b>Autorun V1:</b> <code>checkpoint</code> and <code>exit_goal</code> are no longer documentation-only markers.
They now have native behaviour in the generated preview runtime, even without a manual trigger.</p>
<p><b>Camera room locks V1:</b> a <code>camera_lock</code> region uses its own rectangle as a camera constraint.
If the region is smaller than the screen, the camera simply freezes on its origin; otherwise it can still move inside that visible subsection.</p>
<p>If several <code>camera_lock</code> regions overlap, autorun now automatically chooses the smallest one.
This already gives usable nested locks without a dedicated manual priority system.</p>

<h2>Conditions — full table</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>Region?</th><th>Value?</th><th>Description</th></tr>
  <tr><td>0</td><td><code>enter_region</code></td><td>Yes</td><td>No</td><td>Fires when the player/camera enters the target region</td></tr>
  <tr><td>1</td><td><code>leave_region</code></td><td>Yes</td><td>No</td><td>Fires on exit from the region</td></tr>
  <tr><td>2</td><td><code>cam_x_ge</code></td><td>No</td><td>Yes (tiles)</td><td>Camera X ≥ value (tiles). Ideal for shmup / horizontal scroll</td></tr>
  <tr><td>3</td><td><code>cam_y_ge</code></td><td>No</td><td>Yes (tiles)</td><td>Camera Y ≥ value (tiles). Useful for vertical scroll, dungeons</td></tr>
  <tr><td>4</td><td><code>timer_ge</code></td><td>No</td><td>Yes (frames)</td><td>Scene timer ≥ value frames (60fps). Cutscenes, intro, timeout</td></tr>
  <tr><td>5</td><td><code>wave_ge</code></td><td>No</td><td>Yes (index)</td><td>Current wave ≥ index. Chain spawn waves</td></tr>
  <tr><td>6</td><td><code>btn_a</code></td><td>No</td><td>No</td><td>Button A pressed. Interaction, skip cutscene</td></tr>
  <tr><td>7</td><td><code>btn_b</code></td><td>No</td><td>No</td><td>Button B pressed</td></tr>
  <tr><td>8</td><td><code>btn_a_b</code></td><td>No</td><td>No</td><td>Buttons A+B pressed together. Useful for shortcuts or menus</td></tr>
  <tr><td>9</td><td><code>btn_up</code></td><td>No</td><td>No</td><td>Up direction pressed. Menu navigation, vertical selection</td></tr>
  <tr><td>10</td><td><code>btn_down</code></td><td>No</td><td>No</td><td>Down direction pressed. Menu navigation, vertical selection</td></tr>
  <tr><td>11</td><td><code>btn_left</code></td><td>No</td><td>No</td><td>Left direction pressed. Menus, branches, puzzle input</td></tr>
  <tr><td>12</td><td><code>btn_right</code></td><td>No</td><td>No</td><td>Right direction pressed. Menus, branches, puzzle input</td></tr>
  <tr><td>13</td><td><code>btn_opt</code></td><td>No</td><td>No</td><td>Option button (start/pause)</td></tr>
  <tr><td>14</td><td><code>on_jump</code></td><td>No</td><td>No</td><td>Player just jumped. Useful for jump-pad puzzles or effects</td></tr>
  <tr><td>15</td><td><code>wave_cleared</code></td><td>No</td><td>Yes (index)</td><td>Wave at index "value" is fully defeated. Spawn boss, open door</td></tr>
  <tr><td>16</td><td><code>health_le</code></td><td>No</td><td>Yes (HP)</td><td>Player HP ≤ value. Danger music, spawn health items</td></tr>
  <tr><td>17</td><td><code>health_ge</code></td><td>No</td><td>Yes (HP)</td><td>Player HP ≥ value. Show full-health indicator, resume music</td></tr>
  <tr><td>18</td><td><code>enemy_count_le</code></td><td>No</td><td>Yes (count)</td><td>Living enemy count ≤ value. Triggers next combat phase</td></tr>
  <tr><td>19</td><td><code>lives_le</code></td><td>No</td><td>Yes (count)</td><td>Lives remaining ≤ value. "Last life" warning, dynamic difficulty</td></tr>
  <tr><td>20</td><td><code>lives_ge</code></td><td>No</td><td>Yes (count)</td><td>Lives remaining ≥ value. Unlock bonuses or special behaviour</td></tr>
  <tr><td>21</td><td><code>collectible_count_ge</code></td><td>No</td><td>Yes (count)</td><td>Collected item count ≥ value. Open door, validate collection goal</td></tr>
  <tr><td>22</td><td><code>flag_set</code></td><td>No</td><td>No</td><td>Boolean flag[index] == 1. "Index" = the <b>Index</b> field (0–15). Cross-scene progression, unlocks</td></tr>
  <tr><td>23</td><td><code>flag_clear</code></td><td>No</td><td>No</td><td>Boolean flag[index] == 0. Inverse of flag_set</td></tr>
  <tr><td>24</td><td><code>variable_ge</code></td><td>No</td><td>Yes (threshold)</td><td>u8 variable[index] ≥ value. Key counters, quest points, difficulty level</td></tr>
  <tr><td>25</td><td><code>variable_eq</code></td><td>No</td><td>Yes (target)</td><td>u8 variable[index] == value. Exact state check (boss phase, puzzle state)</td></tr>
  <tr><td>26</td><td><code>timer_every</code></td><td>No</td><td>Yes (N frames)</td><td>True every N frames (<code>timer % N == 0</code>). Periodic blink, spawn loop, poll interval</td></tr>
  <tr><td>27</td><td><code>scene_first_enter</code></td><td>No</td><td>No</td><td>True only on the first frame of the scene (<code>timer == 0</code>). Combined with <code>once</code>, runs an action exactly once on scene entry</td></tr>
  <tr><td>28</td><td><code>on_nth_jump</code></td><td>No</td><td>Yes (N)</td><td>Player's Nth jump. value=0 = any jump, 1=first jump, 2=double jump, 3=triple, etc.</td></tr>
  <tr><td>29</td><td><code>on_wall_left</code></td><td>No</td><td>No</td><td>Player is in contact with a wall on the left</td></tr>
  <tr><td>30</td><td><code>on_wall_right</code></td><td>No</td><td>No</td><td>Player is in contact with a wall on the right</td></tr>
  <tr><td>31</td><td><code>on_ladder</code></td><td>No</td><td>No</td><td>Player is on a ladder tile</td></tr>
  <tr><td>32</td><td><code>on_ice</code></td><td>No</td><td>No</td><td>Player is standing on an ice tile</td></tr>
  <tr><td>33</td><td><code>on_conveyor</code></td><td>No</td><td>No</td><td>Player is standing on a conveyor tile</td></tr>
  <tr><td>34</td><td><code>on_spring</code></td><td>No</td><td>No</td><td>Player is on a spring tile</td></tr>
  <tr><td>35</td><td><code>player_has_item</code></td><td>No</td><td>Yes (item_id)</td><td>Player holds the selected item in their inventory. Item combo selector in UI.</td></tr>
  <tr><td>88</td><td><code>item_count_ge</code></td><td>No</td><td>Yes (count)</td><td>Player holds at least <em>value</em> copies of the selected item. Item combo + count spinner in UI. Useful for crafting or trade.</td></tr>
  <tr><td>36</td><td><code>npc_talked_to</code></td><td>No</td><td>Yes (entity_id)</td><td>The NPC at entity index value has received a dialogue interaction</td></tr>
  <tr><td>37</td><td><code>count_eq</code></td><td>No</td><td>Yes (count)</td><td>Entity count of type flag_var_index == value. E.g. remaining enemies, collectibles of a type</td></tr>
  <tr><td>63</td><td><code>all_switches_on</code></td><td>No</td><td>No</td><td>All switches in the scene are activated. Classic "hit all switches" puzzle condition</td></tr>
  <tr><td>64</td><td><code>block_on_tile</code></td><td>Region</td><td>No</td><td>A pushable block is positioned on the target region. Classic push-block puzzle</td></tr>
  <tr><td>65</td><td><code>dialogue_done</code></td><td>No</td><td>No</td><td>The selected dialogue has been played at least once. Combo selector (by dialogue ID). Use to chain RPG dialogues or as an implicit progression flag</td></tr>
</table>

<h2>Conditions — RPG / strategy / fighting / racing genres</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>Flag/Var idx</th><th>Value</th><th>Description</th></tr>
  <tr><td>38</td><td><code>entity_alive</code></td><td>No</td><td>Yes (entity_id)</td><td>The entity at index value is alive/active in the scene</td></tr>
  <tr><td>39</td><td><code>entity_dead</code></td><td>No</td><td>Yes (entity_id)</td><td>The entity at index value is dead/inactive</td></tr>
  <tr><td>40</td><td><code>quest_stage_eq</code></td><td>Yes (quest_id)</td><td>Yes (stage)</td><td>Quest at flag_var_index is exactly at stage value. E.g. quest 1 stage 3</td></tr>
  <tr><td>41</td><td><code>ability_unlocked</code></td><td>No</td><td>Yes (ability_id)</td><td>The ability at index value is unlocked for the player</td></tr>
  <tr><td>42</td><td><code>resource_ge</code></td><td>Yes (type)</td><td>Yes (threshold)</td><td>Resource of type flag_var_index ≥ value (gold, crystals, mana, etc.)</td></tr>
  <tr><td>43</td><td><code>combo_ge</code></td><td>No</td><td>Yes (N)</td><td>Hit combo count ≥ value. Fighting / beat-em-up</td></tr>
  <tr><td>44</td><td><code>lap_ge</code></td><td>No</td><td>Yes (N)</td><td>Current lap / round ≥ value. Racing / survival rounds</td></tr>
  <tr><td>45</td><td><code>btn_held_ge</code></td><td>No</td><td>Yes (N frames)</td><td>Any button held for ≥ N frames. Charge attacks, long-press actions</td></tr>
  <tr><td>46</td><td><code>chance</code></td><td>No</td><td>Yes (% 0-100)</td><td>Random probability. Useful for optional enemy spawns, loot, rare events</td></tr>
</table>

<h2>Conditions — player events and general states (IDs 47–54)</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>Flag/Var idx</th><th>Value</th><th>Description</th></tr>
  <tr><td>47</td><td><code>on_land</code></td><td>No</td><td>No</td><td>Player touches the ground after being airborne (landing event)</td></tr>
  <tr><td>48</td><td><code>on_hurt</code></td><td>No</td><td>No</td><td>Player takes damage this frame</td></tr>
  <tr><td>49</td><td><code>on_death</code></td><td>No</td><td>No</td><td>Player life counter decremented (player death)</td></tr>
  <tr><td>50</td><td><code>score_ge</code></td><td>No</td><td>Yes (threshold u16)</td><td>Current score ≥ value. Useful for score-based unlocks</td></tr>
  <tr><td>51</td><td><code>timer_le</code></td><td>No</td><td>Yes (frames)</td><td>Scene timer ≤ value. Countdowns, urgency triggers</td></tr>
  <tr><td>52</td><td><code>variable_le</code></td><td>Yes (idx)</td><td>Yes (threshold)</td><td>u8 variable[index] ≤ value. Complement of variable_ge</td></tr>
  <tr><td>53</td><td><code>on_crouch</code></td><td>No</td><td>No</td><td>Player is in the crouching state</td></tr>
  <tr><td>54</td><td><code>cutscene_done</code></td><td>No</td><td>Yes (cutscene_id)</td><td>The cutscene at index value has just finished playing</td></tr>
</table>

<h2>Actions — RPG / strategy / fighting genres (IDs 45–50)</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>45</td><td><code>add_resource</code></td><td>resource_type (u8)</td><td>amount (u8)</td><td>Adds amount to resource of type a0 (gold, crystals, mana, etc.)</td></tr>
  <tr><td>46</td><td><code>remove_resource</code></td><td>resource_type (u8)</td><td>amount (u8)</td><td>Removes amount from resource of type a0 (floor-clamped to 0)</td></tr>
  <tr><td>47</td><td><code>unlock_ability</code></td><td>ability_id (u8)</td><td>—</td><td>Unlocks the ability at index a0 for the player (double-jump, dash, etc.)</td></tr>
  <tr><td>48</td><td><code>set_quest_stage</code></td><td>quest_id (u8)</td><td>stage (u8)</td><td>Sets quest a0 to stage a1. RPG / adventure progression</td></tr>
  <tr><td>49</td><td><code>play_cutscene</code></td><td>cutscene_id (u8)</td><td>—</td><td>Plays the cutscene at index a0. Requires a cutscene table in your runtime</td></tr>
  <tr><td>50</td><td><code>end_game</code></td><td>result (u8)</td><td>—</td><td>Ends the game. a0=0=lose, a0=1=win, a0=2=credits</td></tr>
</table>

<h2>Actions — health, lives, entities, timer, score (IDs 51–62)</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>51</td><td><code>dec_variable</code></td><td>var_idx (0–15)</td><td>floor cap (0=none)</td><td>Decrements u8 variable[index]. If cap > 0, the variable is floor-clamped to that value.</td></tr>
  <tr><td>52</td><td><code>add_health</code></td><td>amount (u8)</td><td>—</td><td>Adds amount HP to the player (capped at max)</td></tr>
  <tr><td>53</td><td><code>set_health</code></td><td>value (u8)</td><td>—</td><td>Sets player HP to exactly value</td></tr>
  <tr><td>54</td><td><code>add_lives</code></td><td>amount (u8)</td><td>—</td><td>Gives the player amount extra lives</td></tr>
  <tr><td>55</td><td><code>set_lives</code></td><td>value (u8)</td><td>—</td><td>Sets the lives counter to exactly value</td></tr>
  <tr><td>56</td><td><code>destroy_entity</code></td><td>entity_idx (u8)</td><td>—</td><td>Removes the entity at index a0 from the scene immediately</td></tr>
  <tr><td>57</td><td><code>teleport_player</code></td><td>region_idx (u8)</td><td>—</td><td>Teleports the player to the centre of spawn region a0</td></tr>
  <tr><td>58</td><td><code>toggle_flag</code></td><td>flag_idx (0–15)</td><td>—</td><td>Flips boolean flag[a0] (0→1, 1→0)</td></tr>
  <tr><td>59</td><td><code>set_score</code></td><td>score_hi (u8)</td><td>score_lo (u8)</td><td>Sets score = (a0×256)+a1 (max 65535)</td></tr>
  <tr><td>60</td><td><code>set_timer</code></td><td>frames (u8)</td><td>—</td><td>Resets the scene timer to a0 frames</td></tr>
  <tr><td>61</td><td><code>pause_timer</code></td><td>—</td><td>—</td><td>Freezes the scene timer (useful during cutscenes)</td></tr>
  <tr><td>62</td><td><code>resume_timer</code></td><td>—</td><td>—</td><td>Resumes the scene timer after a pause</td></tr>
</table>

<h2>Conditions — water physics and attack/dash events (IDs 55–62)</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>Region</th><th>Value</th><th>Description</th></tr>
  <tr><td>55</td><td><code>enemy_count_ge</code></td><td>No</td><td>Yes (N)</td><td>Active enemy count ≥ value. Complements enemy_count_le</td></tr>
  <tr><td>56</td><td><code>variable_ne</code></td><td>No</td><td>Yes</td><td>u8 variable[index] ≠ value. Completes the comparison set (ge/eq/le/ne)</td></tr>
  <tr><td>57</td><td><code>health_eq</code></td><td>No</td><td>Yes (HP)</td><td>Player HP == value exactly. “If exactly 1 HP left”</td></tr>
  <tr><td>58</td><td><code>on_swim</code></td><td>No</td><td>No</td><td>Player is in a water tile (swimming state)</td></tr>
  <tr><td>59</td><td><code>on_dash</code></td><td>No</td><td>No</td><td>Player triggers a dash this frame</td></tr>
  <tr><td>60</td><td><code>on_attack</code></td><td>No</td><td>No</td><td>Player triggers an attack (active hitbox frame)</td></tr>
  <tr><td>61</td><td><code>on_pickup</code></td><td>No</td><td>No</td><td>Player picks up a collectible this frame</td></tr>
  <tr><td>62</td><td><code>entity_in_region</code></td><td>Yes (region)</td><td>Yes (entity_id)</td><td>The entity at index value is currently inside the selected region</td></tr>
</table>

<h2>Actions — fade, camera, combo, spawn, save, audio (IDs 63–72)</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>63</td><td><code>fade_out</code></td><td>duration (frames)</td><td>—</td><td>Fade to black over a0 frames (0 = instant). Uses ngpc_palfx.</td></tr>
  <tr><td>64</td><td><code>fade_in</code></td><td>duration (frames)</td><td>—</td><td>Fade from black over a0 frames.</td></tr>
  <tr><td>65</td><td><code>camera_lock</code></td><td>—</td><td>—</td><td>Freezes the camera at its current position (stops player follow).</td></tr>
  <tr><td>66</td><td><code>camera_unlock</code></td><td>—</td><td>—</td><td>Resumes player-follow camera behaviour.</td></tr>
  <tr><td>67</td><td><code>add_combo</code></td><td>amount (u8)</td><td>—</td><td>Adds a0 points to the combo counter.</td></tr>
  <tr><td>68</td><td><code>reset_combo</code></td><td>—</td><td>—</td><td>Resets the combo counter to 0.</td></tr>
  <tr><td>69</td><td><code>flash_screen</code></td><td>intensity (u8)</td><td>duration (frames)</td><td>Coloured screen flash. a0=intensity, a1=duration. Uses ngpc_palfx.</td></tr>
  <tr><td>70</td><td><code>spawn_at_region</code></td><td>entity_type (u8)</td><td>region_idx (u8)</td><td>Spawns an entity of type a0 at the centre of region a1.</td></tr>
  <tr><td>71</td><td><code>save_game</code></td><td>—</td><td>—</td><td>Triggers a flash save. Requires ngpc_flash_save in your runtime.</td></tr>
  <tr><td>72</td><td><code>set_bgm_volume</code></td><td>volume (0-255)</td><td>—</td><td>Adjusts the current BGM playback volume.</td></tr>
  <tr><td>76</td><td><code>flip_sprite_h</code></td><td>—</td><td>—</td><td>Toggles horizontal flip on the player sprite (face_hflip ^= 1). Useful in top-down games.</td></tr>
  <tr><td>77</td><td><code>flip_sprite_v</code></td><td>—</td><td>—</td><td>Toggles vertical flip on the player sprite (face_vflip ^= 1). Useful in top-down games.</td></tr>
</table>

<h2>OR condition groups (TRIG-OR1)</h2>
<p>The <b>Alternative condition groups (OR)</b> section lets you define extra condition groups. The trigger fires if:</p>
<ul>
  <li>The main condition (and its AND extras) is true, <b>OR</b></li>
  <li>Any OR-group is fully satisfied (all its conditions are true simultaneously)</li>
</ul>
<p>Example: <code>(health_le 20 AND flag_set 3) OR (scene_first_enter AND btn_a)</code></p>
<p>The exported JSON has <code>or_groups</code> = list of groups, each group = list of <code>NgpngCond</code>. Generated C arrays: <code>trig_or_conds[]</code>, <code>trig_or_cond_start[]</code>, <code>trig_or_cond_count[]</code>, <code>trig_or_group_start[]</code>, <code>trig_or_group_count[]</code>.</p>

<h2>Actions — full table</h2>
<table>
  <tr><th>ID</th><th>Name</th><th>a0</th><th>a1</th><th>Description</th></tr>
  <tr><td>0</td><td><code>emit_event</code></td><td>event id</td><td>—</td><td>Fires a custom event. The id is picked from the named combo (<code>CEV_*</code>). Bound actions are defined in <b>Globals → Events</b> and exported to <code>ngpc_custom_events.h</code>.</td></tr>
  <tr><td>1</td><td><code>play_sfx</code></td><td>sfx_id (u8)</td><td>—</td><td>Play a gameplay SFX. Requires your SFX mapping.</td></tr>
  <tr><td>2</td><td><code>start_bgm</code></td><td>song_idx (u8)</td><td>—</td><td>Start a BGM (Sound Creator song index).</td></tr>
  <tr><td>3</td><td><code>stop_bgm</code></td><td>—</td><td>—</td><td>Stop BGM immediately.</td></tr>
  <tr><td>4</td><td><code>fade_bgm</code></td><td>fade_spd (u8)</td><td>—</td><td>Fade out BGM. 0 = hard stop.</td></tr>
  <tr><td>5</td><td><code>goto_scene</code></td><td>scene_idx (u8)</td><td>—</td><td>Switch scene. Pick the target from the scene dropdown.</td></tr>
  <tr><td>6</td><td><code>spawn_wave</code></td><td>wave_idx (u8)</td><td>—</td><td>Force-spawn a wave by its index.</td></tr>
  <tr><td>7</td><td><code>pause_scroll</code></td><td>—</td><td>—</td><td>Suspend forced scroll (boss arena).</td></tr>
  <tr><td>8</td><td><code>resume_scroll</code></td><td>—</td><td>—</td><td>Resume forced scroll.</td></tr>
  <tr><td>9</td><td><code>spawn_entity</code></td><td>ent_type (u8)</td><td>slot (u8)</td><td>Spawn an entity at a slot from spawn_slots[].</td></tr>
  <tr><td>10</td><td><code>set_scroll_speed</code></td><td>spd_x (u8)</td><td>spd_y (u8)</td><td>Change forced scroll speed on the fly.</td></tr>
  <tr><td>11</td><td><code>play_anim</code></td><td>ent_type (u8)</td><td>anim_state (u8)</td><td>Force an animation state on an entity type.</td></tr>
  <tr><td>12</td><td><code>force_jump</code></td><td>ent_type (u8)</td><td>—</td><td>Force a jump on an entity type (AI or player).</td></tr>
  <tr><td>13</td><td><code>enable_trigger</code></td><td>trig_idx (u8)</td><td>—</td><td>Re-enable a disabled trigger (by index in the list).</td></tr>
  <tr><td>14</td><td><code>disable_trigger</code></td><td>trig_idx (u8)</td><td>—</td><td>Disable a trigger so it no longer fires.</td></tr>
  <tr><td>15</td><td><code>screen_shake</code></td><td>intensity (u8)</td><td>duration (u8)</td><td>Camera shake. Intensity 0–255, duration in frames.</td></tr>
  <tr><td>16</td><td><code>set_cam_target</code></td><td>cam_x (u8)</td><td>cam_y (u8)</td><td>Move the camera target in tiles.</td></tr>
  <tr><td>18</td><td><code>show_entity</code></td><td>entity_idx (u8)</td><td>—</td><td>Show a static entity already placed in the scene. Useful for cursors or menu options.</td></tr>
  <tr><td>19</td><td><code>hide_entity</code></td><td>entity_idx (u8)</td><td>—</td><td>Hide a static entity already placed in the scene.</td></tr>
  <tr><td>20</td><td><code>move_entity_to</code></td><td>entity_idx (u8)</td><td>region_idx (u8)</td><td>Move a static entity toward a target region. Good starting point for menus and pointers.</td></tr>
  <tr><td>21</td><td><code>cycle_player_form</code></td><td>—</td><td>—</td><td>Switch to the next player form. This enables the “one visible form at a time” mode in autorun.</td></tr>
  <tr><td>22</td><td><code>set_player_form</code></td><td>form_idx (u8)</td><td>—</td><td>Force a specific player form by index. 0 = first exported form using the <code>player</code> role.</td></tr>
  <tr><td>23</td><td><code>fire_player_shot</code></td><td>—</td><td>—</td><td>Fire the native player shot. <b>Legacy:</b> still supported via trigger. <b>Recommended:</b> use the <i>Shooting</i> group in Level → Entity to configure the fire button and bullet sprite — autorun handles shooting automatically.</td></tr>
  <tr><td>24</td><td><code>set_checkpoint</code></td><td>region_idx (u8)</td><td>—</td><td>Explicitly store a checkpoint region. Useful when you want trigger-driven respawn logic.</td></tr>
  <tr><td>25</td><td><code>respawn_player</code></td><td>—</td><td>—</td><td>Force an immediate player respawn on the current checkpoint. Without a valid checkpoint, autorun falls back to the normal entry spawn.</td></tr>
  <tr><td>26</td><td><code>pause_entity_path</code></td><td>entity_idx (u8)</td><td>—</td><td>Pause path following on a static entity, useful for moving platforms and lifts.</td></tr>
  <tr><td>27</td><td><code>resume_entity_path</code></td><td>entity_idx (u8)</td><td>—</td><td>Resume path following on a static entity linked to a <code>Path</code>.</td></tr>
  <tr><td>28</td><td><code>set_flag</code></td><td>flag_idx (0–15)</td><td>—</td><td>Set boolean flag[index] = 1. The index is set in the trigger UI <b>Index</b> field.</td></tr>
  <tr><td>29</td><td><code>clear_flag</code></td><td>flag_idx (0–15)</td><td>—</td><td>Clear boolean flag[index] = 0.</td></tr>
  <tr><td>30</td><td><code>set_variable</code></td><td>var_idx (0–15)</td><td>value (u8)</td><td>Directly assign u8 variable[index] = value (set in the <b>Value</b> field).</td></tr>
  <tr><td>31</td><td><code>inc_variable</code></td><td>var_idx (0–15)</td><td>cap (0=none)</td><td>Increment u8 variable[index]. If cap &gt; 0, the variable is clamped to that maximum.</td></tr>
  <tr><td>32</td><td><code>warp_to</code></td><td>scene_idx (u8)</td><td>spawn_idx (u8)</td><td>Switch scene <i>and</i> place the player at the centre of the <code>spawn</code> region #spawn_idx in the target scene.</td></tr>
  <tr><td>33</td><td><code>lock_player_input</code></td><td>—</td><td>—</td><td>Zeroes <code>ngpc_pad_held</code> and <code>ngpc_pad_pressed</code> every frame until unlocked. Useful for cutscenes or dialogues.</td></tr>
  <tr><td>34</td><td><code>unlock_player_input</code></td><td>—</td><td>—</td><td>Releases the lock set by <code>lock_player_input</code>. The player regains control from the next frame.</td></tr>
  <tr><td>35</td><td><code>enable_multijump</code></td><td>max_jumps (2–5)</td><td>—</td><td>Enables multi-jump for the player with a ceiling of max_jumps mid-air jumps.</td></tr>
  <tr><td>36</td><td><code>disable_multijump</code></td><td>—</td><td>—</td><td>Disables multi-jump. Returns to standard single-jump behaviour.</td></tr>
  <tr><td>37</td><td><code>reset_scene</code></td><td>—</td><td>—</td><td>Reloads the current scene from scratch (positions, entities, timer). Useful on player death or failed puzzle.</td></tr>
  <tr><td>38</td><td><code>show_dialogue</code></td><td>dlg_idx (u8)</td><td>—</td><td>Shows the dialogue at index a0. Index is resolved from the dialogue ID set in the <b>Dialogues</b> tab (stable across reorders). Generates <code>g_dlg_*[]</code> in <code>scene_*_dialogs.h</code>.</td></tr>
  <tr><td>74</td><td><code>set_npc_dialogue</code></td><td>entity_idx (u8)</td><td>dlg_idx (u8)</td><td>Changes the dialogue of NPC a0 to dialogue a1. Lets an NPC give a different reply based on quest progress. Entity + dialogue combo selectors in UI.</td></tr>
  <tr><td>39</td><td><code>give_item</code></td><td>item_id (u8)</td><td>—</td><td>Adds the selected item directly to the player's inventory (no visual on map). Item combo selector in UI.</td></tr>
  <tr><td>40</td><td><code>remove_item</code></td><td>item_id (u8)</td><td>—</td><td>Removes the selected item from the player's inventory. Item combo selector in UI.</td></tr>
  <tr><td>78</td><td><code>drop_item</code></td><td>item_id (u8)</td><td>—</td><td>Spawns a visible pickup for the selected item at the entity's current position. The runtime uses <code>g_item_table[a0].sprite_id</code> for display. Classic use: <code>on_death → drop_item</code> to make an enemy drop loot. Item combo selector in UI.</td></tr>
  <tr><td>79</td><td><code>drop_random_item</code></td><td>—</td><td>—</td><td>Spawns a visible pickup for a random item drawn from <code>CAVEGEN_ITEM_POOL</code> (or all items if the pool is empty). Useful for generic enemies that can drop anything.</td></tr>
  <tr><td>41</td><td><code>unlock_door</code></td><td>door_id (u8)</td><td>—</td><td>Unlocks the door entity at index door_id in the scene.</td></tr>
  <tr><td>42</td><td><code>enable_wall_grab</code></td><td>—</td><td>—</td><td>Enables wall-grab/wall-slide for the player.</td></tr>
  <tr><td>43</td><td><code>disable_wall_grab</code></td><td>—</td><td>—</td><td>Disables wall-grab/wall-slide.</td></tr>
  <tr><td>44</td><td><code>set_gravity_dir</code></td><td>dir (u8)</td><td>—</td><td>Changes the player's gravity direction. 0=down (normal), 1=up (inverted), 2=none (zero-g).</td></tr>
</table>
<p><b>Export validation:</b> broken references (scene, trigger, entity, region) are now detected before generating <code>scene_*_level.h</code>. GUI, project, and headless exports will block the affected scene instead of producing an inconsistent header.</p>
<p><b>Template autorun (V1 coverage):</b> the generated runtime preview now also executes a practical first batch of exported actions:
<code>spawn_wave</code>, <code>pause_scroll</code>, <code>resume_scroll</code>, <code>set_scroll_speed</code>,
<code>set_cam_target</code>, <code>enable_trigger</code>, <code>disable_trigger</code>,
<code>show_entity</code>, <code>hide_entity</code>, <code>move_entity_to</code>,
<code>pause_entity_path</code>, <code>resume_entity_path</code>,
<code>cycle_player_form</code>, <code>set_player_form</code>, <code>fire_player_shot</code>,
<code>set_checkpoint</code>, <code>respawn_player</code>,
<code>set_flag</code>, <code>clear_flag</code>, <code>set_variable</code>, <code>inc_variable</code>, <code>warp_to</code>,
<code>lock_player_input</code>, and <code>unlock_player_input</code>.
In preview mode, <code>play_anim</code> applies to static props, and <code>force_jump</code> applies to already-spawned gravity enemies.</p>
<p><b>More intuitive gameplay setup:</b> the Triggers tab now also includes quick presets such as <b>Player shot on A</b> and <b>Player attack (event) on A</b>. The first uses native <code>fire_player_shot</code>; the second prepares a semantic <code>emit_event</code> for runtimes that own melee/custom attacks.</p>
<p><b>Covered runtime conditions:</b> autorun preview now also supports <code>on_jump</code> on the main player. Jump-based triggers are no longer just “documentary” in the shipped template.</p>
<p><b>Quick start</b>: if you want a “manual” trigger, in practice you usually start by drawing a <b>region</b> on the scene, then use the quick <b>Enter</b> / <b>Leave</b> actions in the Triggers tab. The current V1 export format is mainly <b>region + condition + action</b>, not yet a free-standing trigger-point system.</p>

<p><b>Custom HUD / runtime UI:</b> in addition to <code>health_le</code>, the preview now also supports
<code>health_ge</code>, <code>lives_le</code>, and <code>lives_ge</code>. This is the most practical base for a HUD built
from static scene entities: hearts, bar segments, life icons, and similar elements, driven with
<code>show_entity</code> / <code>hide_entity</code>.</p>

<h2>Graphical menu presets</h2>
<p>The <b>Preset</b> block in the Triggers tab is meant to create V1 UI/menu triggers quickly instead of wiring everything from scratch.</p>
<ul>
  <li>If a <b>region</b> is already selected, the preset reuses it as the source zone when relevant.</li>
  <li>If a <b>static entity</b> is already selected in the scene, the preset reuses it as the target for show/hide/move actions.</li>
  <li>The preset is only a starting point: after creation, still review the target scene, SFX, or destination region depending on the workflow.</li>
</ul>
<table>
  <tr><th>Preset</th><th>Created condition</th><th>Created action</th><th>Typical use</th></tr>
  <tr><td><b>Cursor on region enter</b></td><td><code>enter_region</code></td><td><code>move_entity_to</code></td><td>Moves a cursor or pointer toward the hovered region. Then assign the cursor entity and, if needed, the destination region.</td></tr>
  <tr><td><b>Show entity on enter</b></td><td><code>enter_region</code></td><td><code>show_entity</code></td><td>Shows an option, tooltip, or UI prop when the zone becomes active.</td></tr>
  <tr><td><b>Hide entity on leave</b></td><td><code>leave_region</code></td><td><code>hide_entity</code></td><td>Hides a UI element when leaving a menu zone.</td></tr>
  <tr><td><b>Confirm menu -&gt; scene</b></td><td><code>btn_a</code></td><td><code>goto_scene</code></td><td>Confirms an option with A, then loads the selected scene from the picker.</td></tr>
  <tr><td><b>Hover SFX on region</b></td><td><code>enter_region</code></td><td><code>play_sfx</code></td><td>Plays a navigation sound when the cursor enters a zone.</td></tr>
</table>
<p><b>V1 limits:</b> these presets create the no-code structure, but there is still no <code>move_entity_lerp</code>, easing, or automatic menu repeat on the runtime side. They already cover the simple cases: cursor, visible/hidden options, scene confirm, and hover SFX.</p>

<h2>AND conditions (multi-condition triggers)</h2>
<p>A trigger has a <b>primary condition</b> (Condition + Region/Value fields) and can have additional
<b>AND conditions</b> in the "AND conditions" group at the bottom of the trigger props panel.</p>
<ul>
  <li>Click <b>+</b> to add an AND condition.</li>
  <li>Select a row to edit its type (combo), region, or value in the inline editor below the list.</li>
  <li>Click <b>−</b> to remove the selected condition.</li>
  <li>The trigger only fires when <b>all</b> conditions are simultaneously true.</li>
</ul>
<p><b>Export:</b> when at least one trigger has AND conditions, the export generates:</p>
<pre>typedef struct &#123; u8 cond; u8 region; u16 value; &#125; NgpngCond;
static const NgpngCond g_scene_trig_conds[] = &#123; ... &#125;;
static const u8 g_scene_trig_cond_count[] = &#123; 0, 2, 0, 1, ... &#125;;
static const u8 g_scene_trig_cond_start[] = &#123; 0, 0, 2, 2, ... &#125;;</pre>
<p>Your runtime iterates <code>trig_conds[start..start+count-1]</code> to check the AND conditions. The generated template autorun now reads those arrays too, so preview mode finally matches simple AND-trigger behavior without extra manual code.</p>

<h2>Duplicating triggers (⧉ Dup)</h2>
<p>The <b>⧉ Dup</b> button next to the Name field creates a deep copy of the selected trigger
(new unique ID, auto-named <code>name_2</code>, <code>name_3</code>…, including AND conditions).
The duplicate is inserted right after the original and selected automatically.</p>
<p>Typical use: create a series of similar triggers (e.g. 4 spawn regions with the same action) —
duplicate and change only the target region each time.</p>

<h2>Per-instance entity props</h2>
<p>In the entity properties panel (selected entity), you can set:</p>
<table>
  <tr><th>Field</th><th>Values</th><th>Description</th></tr>
  <tr><td><b>Direction</b></td><td>0=right, 1=left, 2=up, 3=down</td><td>Initial spawn direction</td></tr>
  <tr><td><b>Behavior</b></td><td>0=patrol, 1=chase, 2=fixed, 3=random</td><td>Default AI mode</td></tr>
  <tr><td><b>Path</b></td><td>(none) or path name from scene</td><td>Assigns that path to the selected entity; export writes its index into paths[]</td></tr>
</table>
<p>These fields generate C tables parallel to <code>g_scene_entities[]</code>:</p>
<pre>static const u8 g_scene_ent_dirs[]      = &#123; 0, 1, 0, 2, ... &#125;;
static const u8 g_scene_ent_behaviors[] = &#123; 0, 0, 2, 1, ... &#125;;
static const u8 g_scene_ent_paths[]     = &#123; 255, 0, 255, 1, ... &#125;; /* 255 = none */</pre>
<p>Tables are only generated when at least one entity has a non-default value.</p>

<h2>Per-entity AI parameters (TRIG-7)</h2>
<p>When an enemy behavior is selected, an <b>AI Parameters</b> panel appears below the instance props with context-sensitive spinboxes:</p>
<table>
  <tr><th>Field</th><th>Behaviors</th><th>Description</th><th>C export</th></tr>
  <tr><td><b>Speed</b></td><td>patrol, chase, random</td><td>Move speed in px/frame (1–255, default 1)</td><td><code>g_{sym}_ent_ai_speed[]</code> if any ≠ 1</td></tr>
  <tr><td><b>Aggro range</b></td><td>chase</td><td>Player detection radius (value × 8 px, default 80 px)</td><td><code>g_{sym}_ent_ai_range[]</code> if chase present</td></tr>
  <tr><td><b>Lose range</b></td><td>chase</td><td>Abandon-chase radius (value × 8 px, default 128 px)</td><td><code>g_{sym}_ent_ai_lose_range[]</code> if chase present</td></tr>
  <tr><td><b>Dir. change</b></td><td>random</td><td>Frames between random direction changes (1–255, default 60)</td><td><code>g_{sym}_ent_ai_change_every[]</code> if random present</td></tr>
</table>
<p>Only the needed tables are emitted; default values produce no output. Example:</p>
<pre>#define LEVEL1_ENTITY_AI_SPEED_TABLE 1
static const u8 g_level1_ent_ai_speed[]         = &#123;   1,   2,   1,   4 &#125;;  /* px/frame */

#define LEVEL1_ENTITY_AI_RANGE_TABLE 1
static const u8 g_level1_ent_ai_range[]         = &#123;  10,   8,  10,   0 &#125;;  /* x8 px */
static const u8 g_level1_ent_ai_lose_range[]    = &#123;  16,  12,  16,   0 &#125;;  /* x8 px */

#define LEVEL1_ENTITY_AI_CHANGE_TABLE 1
static const u8 g_level1_ent_ai_change_every[]  = &#123;  60,  60,  30,  60 &#125;;  /* frames */</pre>
<p>The <b>fixed</b> behavior shows no parameters (entity is stationary).</p>

<h2>C export structure (<code>_scene.h</code>)</h2>
<pre>/* Regions */
typedef struct &#123; u8 x; u8 y; u8 w; u8 h; u8 kind; &#125; NgpngRegion;
static const NgpngRegion g_scene_regions[] = &#123; ... &#125;;

/* Triggers */
typedef struct &#123; u8 cond; u8 region; u16 value; u8 action; u8 a0; u8 a1; u8 once; &#125; NgpngTrigger;
static const NgpngTrigger g_scene_triggers[] = &#123; ... &#125;;

/* AND conditions (only when needed) */
typedef struct &#123; u8 cond; u8 region; u16 value; &#125; NgpngCond;
static const NgpngCond  g_scene_trig_conds[]       = &#123; ... &#125;;
static const u8         g_scene_trig_cond_count[]  = &#123; ... &#125;;
static const u8         g_scene_trig_cond_start[]  = &#123; ... &#125;;

/* Spawn points (regions with kind=spawn) — warp_to targets */
#define SCENE_XXX_SPAWN_COUNT 2
static const NgpngPoint g_xxx_spawn_points[] = &#123; &#123;80, 64&#125;, &#123;200, 120&#125; &#125;;

/* #defines for trigger/condition/action/region IDs */
#define TRIG_ENTER_REGION 0  /* ... */
#define TRIG_ACT_EMIT_EVENT 0  /* ... */
#define REGION_KIND_ZONE 0  /* ... */</pre>

<h2>Practical patterns by genre</h2>
<table>
  <tr><th>Genre</th><th>Pattern</th><th>Recipe</th></tr>
  <tr><td>Shmup</td><td>Spawn wave 2 after wave 1 cleared</td><td>cond=wave_cleared(0) → spawn_wave(1)</td></tr>
  <tr><td>Shmup</td><td>Boss arena: pause scroll</td><td>wave_ge(5) → pause_scroll ; wave_cleared(5) → resume_scroll</td></tr>
  <tr><td>Shmup</td><td>Danger music on low HP</td><td>cond=health_le(3) → start_bgm(DANGER_BGM) ; once ✓</td></tr>
  <tr><td>RPG/Dungeon</td><td>Simple room transition</td><td>cond=enter_region(door) → goto_scene(next_room) ; once ✓</td></tr>
  <tr><td>RPG/Dungeon</td><td>Door with precise spawn</td><td>cond=enter_region(door) → warp_to(room_B, spawn_idx=1) — player placed at room B's spawn[1]</td></tr>
  <tr><td>RPG/Dungeon</td><td>Boss spawn on switch</td><td>cond=btn_a AND enter_region(switch) → spawn_entity(BOSS, 0)</td></tr>
  <tr><td>Progression</td><td>Flag-gated area</td><td>cond=flag_set(0) AND enter_region(locked_door) → goto_scene(zone2)</td></tr>
  <tr><td>Progression</td><td>Key counter for door</td><td>enter_region(key) → inc_variable(0) ; cond=variable_ge(0,3) → emit_event(DOOR_OPEN)</td></tr>
  <tr><td>Platformer</td><td>Checkpoint music</td><td>cond=enter_region(zone2) → start_bgm(2) ; once ✓</td></tr>
  <tr><td>Platformer</td><td>Scripted sequence</td><td>trig1: enter_region → screen_shake(4,30) ; trig2: disable(trig1), spawn_wave(0)</td></tr>
  <tr><td>Puzzle</td><td>Open door on jump-pad</td><td>cond=on_jump AND enter_region(pad) → emit_event(EV_DOOR, door_id)</td></tr>
  <tr><td>All</td><td>Intro audio</td><td>cond=timer_ge(60) → start_bgm(0) ; once ✓</td></tr>
</table>

<h2>Tips</h2>
<ul>
  <li><b>Order your triggers</b>: the runtime walks them in order. Put frequent conditions first.</li>
  <li><b>Use "once"</b> for transitions (music, scene) so they don't re-fire every frame.</li>
  <li><b>Chain enable/disable_trigger</b>: create disabled triggers and activate them via other triggers to build a simple state machine.</li>
  <li><b>cam_x_ge / cam_y_ge</b> are often simpler than enter_region for a shmup: no region to draw, just a threshold.</li>
  <li><b>AND conditions</b> let you gate logic without code: e.g. wave_cleared(0) AND enter_region(zone2) → only fires in the right area after the wave is done.</li>
  <li><b>⧉ Dup</b> is your best friend for multi-region patterns: set up one trigger perfectly, then duplicate and swap the region.</li>
</ul>
"""


def _fr_procgen() -> str:
    return """
<h1>Génération procédurale (Roguelike / Cave)</h1>

<h2>⚠ Deux systèmes distincts — lequel utiliser ?</h2>

<table>
  <tr>
    <th></th>
    <th>PNG Manager — onglet Level (Procgen)</th>
    <th>ngpc_procgen / ngpc_cavegen (C)</th>
  </tr>
  <tr>
    <td><b>Quoi</b></td>
    <td>Outil de design sur PC</td>
    <td>Code C qui tourne sur le NGPC</td>
  </tr>
  <tr>
    <td><b>Quand</b></td>
    <td>À la compilation (avant le jeu)</td>
    <td>Au runtime (pendant le jeu)</td>
  </tr>
  <tr>
    <td><b>Résultat</b></td>
    <td>Tilemap PNG statique baked dans la ROM</td>
    <td>Donjon/cave différent à chaque seed</td>
  </tr>
  <tr>
    <td><b>Demande du code ?</b></td>
    <td>Non — click dans l'UI</td>
    <td><b>Oui</b> — C89, à intégrer manuellement</td>
  </tr>
</table>

<h3>Ce que fait l'onglet Level (Procgen du PNG Manager)</h3>
<p>Il génère un <b>tilemap de collision visuel</b> (PNG SCR1/SCR2) pour
concevoir une map dans l'éditeur. C'est un outil pour <b>toi</b> pendant le
développement. Le résultat est un fichier PNG statique, exporté en C et inclus
dans la ROM. Le joueur verra toujours la même map à chaque partie.</p>

<h3>Ce que font ngpc_procgen / ngpc_cavegen</h3>
<p>Ce sont des <b>modules C</b> qui tournent directement sur le hardware NGPC.
La génération se passe au démarrage du niveau, en RAM. Chaque partie produit
un donjon ou une cave différent. Ça demande d'écrire du code C dans ton jeu.</p>

<h3>Peut-on combiner les deux ?</h3>
<p>Oui — c'est même la bonne approche :</p>
<ol>
  <li>Utilise le <b>PNG Manager</b> pour designer les visuels de tes rooms
      (murs, décors, tiles) → exporter en ROM.</li>
  <li>Dans ton code C, le callback <code>room_load_cb</code> reçoit
      <code>tpl-&gt;variant</code> (0=plain, 1=piliers, 2=divisé…) →
      tu charges le tileset correspondant depuis la ROM.</li>
  <li><code>ngpc_procgen_generate_ex()</code> décide <b>quelle structure</b>
      de donjon générer ; c'est ton code qui affiche les graphiques.</li>
</ol>
<p>Le lien entre les deux <b>n'est pas automatique</b> — il faut quelques
lignes de C pour relier le template procgen à tes assets.</p>

<hr>

<h2>Mode 1 — Donjon room-by-room (Dicing Knight)</h2>

<h3>Architecture</h3>
<p>Le donjon est une <b>grille 4×4</b> (configurable). Chaque cellule active
est une <b>room = un écran NGPC complet</b> (20×19 tiles, 160×152 px).
Les transitions se font via des portes N/S/W/E dessinées sur les bords.</p>

<pre>
+---+---+---+---+
| S |   | . |   |   S = départ    . = visitée
+---+---+---+---+   @ = joueur    X = sortie (boss)
|   | @ |===|   |   = = boucle   ? = non visitée
+---+---+---+---+
|   | . | X |   |
+---+---+---+---+
</pre>

<h3>Génération</h3>
<ol>
  <li>DFS depuis la cellule 0,0 → arbre couvrant connexe (labyrinthe parfait)</li>
  <li>BFS → room la plus lointaine du départ = <b>EXIT</b> (boss)</li>
  <li>Injection de boucles optionnelle (<code>loop_pct</code>) → raccourcis</li>
  <li>Assignation de templates graphiques par configuration de portes</li>
</ol>

<table>
  <tr><th>loop_pct</th><th>Résultat</th></tr>
  <tr><td>0</td><td>Labyrinthe parfait, 1 seul chemin par room</td></tr>
  <tr><td>20</td><td><b>Recommandé</b> — bon équilibre variété / lisibilité</td></tr>
  <tr><td>35+</td><td>Donjon très ouvert, nombreux chemins alternatifs</td></tr>
</table>

<h3>Contenu procédural</h3>
<pre>ProcgenContent content[PROCGEN_MAX_ROOMS];
ngpc_procgen_gen_content(&amp;map, content, 3, 40);</pre>
<table>
  <tr><th>Room type</th><th>enemies</th><th>items</th><th>special</th></tr>
  <tr><td>START</td><td>0</td><td>0</td><td>0</td></tr>
  <tr><td>NORMAL</td><td>aléatoire</td><td>aléatoire</td><td>0</td></tr>
  <tr><td>EXIT (boss)</td><td>0xFF</td><td>—</td><td><b>1</b></td></tr>
  <tr><td>SHOP</td><td>0</td><td>0xFF</td><td><b>2</b></td></tr>
  <tr><td>SECRET</td><td>1 type</td><td>0xFF</td><td><b>3</b></td></tr>
</table>

<h3>Code complet — init et update</h3>
<pre>#define PROCGEN_ROOMS_IMPL
#include "ngpc_procgen/ngpc_procgen.h"
#include "ngpc_procgen/ngpc_procgen_rooms.h"

static ProcgenMap     g_dungeon;
static ProcgenContent g_content[PROCGEN_MAX_ROOMS];
static u8 g_px, g_py;

/* Callback : rendu de la room courante */
static void room_cb(const ProcgenCell *cell,
                    const NgpcRoomTemplate NGP_FAR *tpl,
                    u8 entry_dir, void *ud)
{
    u8 idx = g_dungeon.current_idx;
    ngpc_procgen_fill_room(cell, tpl,
                           TILE_WALL, TILE_FLOOR, TILE_PILLAR, 0u);
    if (!(cell-&gt;flags &amp; PROCGEN_FLAG_VISITED)) {
        /* Spawner g_content[idx].count ennemis... */
    }
    (void)entry_dir; (void)ud;
}

/* Initialisation (une fois par niveau) */
void level_init(u16 seed)
{
    ngpc_procgen_generate_ex(&amp;g_dungeon,
        g_procgen_rooms, PROCGEN_ROOMS_COUNT, seed, 20u);
    ngpc_procgen_gen_content(&amp;g_dungeon, g_content, 3u, 40u);
    ngpc_procgen_load_room(&amp;g_dungeon, g_dungeon.start_idx,
        g_procgen_rooms, room_cb, 0xFFu, 0);
    ngpc_procgen_spawn_pos(0xFFu, &amp;g_px, &amp;g_py);
}

/* Update (chaque frame) */
void level_update(void)
{
    u8 cur = g_dungeon.current_idx;
    u8 dir = 0xFFu, next;
    /* déplacer g_px, g_py... */
    if (g_py == 0u  &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_N)) dir = PROCGEN_DIR_N;
    if (g_py == 18u &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_S)) dir = PROCGEN_DIR_S;
    if (g_px == 0u  &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_W)) dir = PROCGEN_DIR_W;
    if (g_px == 19u &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_E)) dir = PROCGEN_DIR_E;
    if (dir != 0xFFu) {
        next = ngpc_procgen_neighbor(&amp;g_dungeon, cur, dir);
        if (next != PROCGEN_IDX_NONE) {
            ngpc_procgen_load_room(&amp;g_dungeon, next,
                g_procgen_rooms, room_cb, dir, 0);
            ngpc_procgen_spawn_pos(dir, &amp;g_px, &amp;g_py);
        }
    }
}</pre>

<h3>Templates et variantes graphiques</h3>
<p><b>ngpc_procgen_rooms.h</b> fournit 48 templates (3 variantes × 16 configs d'exits).
<code>fill_room()</code> dessine la variante sélectionnée :</p>
<table>
  <tr><th>Variante</th><th>Rendu</th></tr>
  <tr><td>0 — plain</td><td>Room vide, sol dégagé</td></tr>
  <tr><td>1 — pillars</td><td>4 piliers symétriques</td></tr>
  <tr><td>2 — divided</td><td>Mur horizontal partiel avec passage central</td></tr>
</table>
<p>Pour ajouter tes propres layouts : ajouter des entrées dans <code>g_procgen_rooms[]</code>
avec <code>variant &gt; 2</code>, puis étendre <code>ngpc_procgen_fill_room()</code>.</p>

<h3>Mini-map</h3>
<pre>/* Afficher chaque cellule de la grille comme un caractère */
for (y = 0; y &lt; PROCGEN_GRID_H; y++) {
    for (x = 0; x &lt; PROCGEN_GRID_W; x++) {
        u8 idx = procgen_cell_idx(x, y);
        char c = ' ';
        if (!procgen_cell_active(&amp;g_dungeon, idx)) c = ' ';
        else if (idx == g_dungeon.current_idx) c = '@';
        else if (idx == g_dungeon.exit_idx)    c = 'X';
        else if (g_dungeon.cells[idx].flags &amp; PROCGEN_FLAG_VISITED) c = '.';
        else c = '?';
        /* afficher c à (x, y) en texte */
    }
}</pre>

<hr>

<h2>Mode 2 — Cave ouverte avec scrolling (Cave Noir)</h2>

<h3>Architecture</h3>
<p>La cave est une grille <b>32×32 tiles</b> générée en début de partie.
Le joueur se déplace librement, la caméra suit en montrant une fenêtre
<b>20×19 tiles</b> (un écran NGPC).</p>

<pre>/* Types de tiles dans la map */
CAVE_WALL  = 0   /* mur solide */
CAVE_FLOOR = 1   /* sol passable */
CAVE_ENTRY = 2   /* spawn joueur */
CAVE_EXIT  = 3   /* sortie du niveau */
CAVE_CHEST = 4   /* coffre */
CAVE_ENEMY = 5   /* spawn ennemi */</pre>

<h3>Algorithme</h3>
<ol>
  <li><b>Fill aléatoire</b> — wall_pct% de murs dans l'intérieur, bordures toujours murs</li>
  <li><b>Lissage × 5</b> — règle de Moore : ≥5 voisins-murs → mur, sinon → sol</li>
  <li><b>Flood-fill</b> — garde seulement la région connexe la plus grande</li>
  <li><b>Placement</b> — entrée à gauche, sortie à droite, ennemis/coffres par sections 8×8</li>
</ol>

<table>
  <tr><th>wall_pct</th><th>Résultat</th></tr>
  <tr><td>40</td><td>Très ouvert, grandes salles, peu de couloirs</td></tr>
  <tr><td><b>47</b></td><td><b>Recommandé</b> — cave naturelle équilibrée</td></tr>
  <tr><td>52</td><td>Étroite, nombreux couloirs et culs-de-sac</td></tr>
</table>

<h3>Code complet — init et update</h3>
<pre>#include "ngpc_cavegen/ngpc_cavegen.h"

static NgpcCaveMap g_cave;
static u8 g_view[20 * 19];
static u8 g_px, g_py, g_cam_x, g_cam_y;

/* Correspondance CAVE_* → tile NGPC */
static const u16 s_tiles[6] = {
    TILE_WALL, TILE_FLOOR, TILE_FLOOR,
    TILE_EXIT, TILE_CHEST, TILE_ENEMY
};

void cave_render(void)
{
    u8 x, y; u8 t;
    for (y = 0u; y &lt; 19u; y++)
        for (x = 0u; x &lt; 20u; x++) {
            t = g_view[(u16)y * 20u + x];
            ngpc_gfx_put_tile(GFX_SCR1, x, y, s_tiles[t &lt; 6u ? t : 0u], 0u);
        }
}

void cave_init(u16 seed)
{
    ngpc_cavegen_generate(&amp;g_cave, seed, 47u, 8u, 3u);
    g_px = g_cave.entry_x;
    g_py = g_cave.entry_y;
    ngpc_cavegen_cam_center(g_px, g_py, &amp;g_cam_x, &amp;g_cam_y);
    ngpc_cavegen_viewport(&amp;g_cave, g_cam_x, g_cam_y, g_view);
    cave_render();
}

void cave_update(void)
{
    u8 new_px = g_px, new_py = g_py;
    u8 tile;
    u8 new_cx, new_cy;
    /* déplacer new_px/new_py selon le pad... */
    tile = g_cave.map[(u16)new_py * CAVEGEN_W + new_px];
    if (tile == CAVE_WALL) { new_px = g_px; new_py = g_py; }    /* collision */
    if (tile == CAVE_CHEST) {
        g_cave.map[(u16)new_py * CAVEGEN_W + new_px] = CAVE_FLOOR;
        /* collecte objet */
    }
    if (tile == CAVE_EXIT)  { /* niveau suivant */ }
    g_px = new_px; g_py = new_py;
    ngpc_cavegen_cam_center(g_px, g_py, &amp;new_cx, &amp;new_cy);
    if (new_cx != g_cam_x || new_cy != g_cam_y) {
        g_cam_x = new_cx; g_cam_y = new_cy;
        ngpc_cavegen_viewport(&amp;g_cave, g_cam_x, g_cam_y, g_view);
        cave_render();  /* re-rendre uniquement si la caméra a bougé */
    }
    ngpc_gfx_put_tile(GFX_SCR1,
        (u8)(g_px - g_cam_x), (u8)(g_py - g_cam_y), TILE_PLAYER, 0u);
}</pre>

<h3>Plusieurs niveaux</h3>
<pre>u16 g_seed = 0xCAFEu;

void next_floor(void) {
    g_seed = (u16)(g_seed * 0x6C07u + 0x3925u); /* LCG simple */
    cave_init(g_seed);
}</pre>

<hr>

<h2>Intégration avec le PNG Manager</h2>

<p>L'onglet <b>Level</b> du PNG Manager contient un générateur de tilemaps de
collision (onglet Procgen). Il génère des <b>fichiers PNG SCR1/SCR2</b>
à partir de cartes de collision — c'est complémentaire aux modules C :
le Procgen C gère la <b>structure du donjon</b>, le PNG Manager gère
les <b>assets visuels</b> de chaque room.</p>

<p>Workflow recommandé :</p>
<ol>
  <li>Créer les tilesets de room dans Aseprite (murs, sol, portes)</li>
  <li>Les exporter via le PNG Manager (Palette + Tilemap tabs)</li>
  <li>Dans le callback <code>ProcgenLoadFn</code>, charger les tiles selon
      <code>cell-&gt;template_id</code> et <code>tpl-&gt;variant</code></li>
  <li>Utiliser <code>ngpc_procgen_fill_room()</code> comme base, puis
      superposer les tiles d'assets réels</li>
</ol>

<hr>

<h2>Budget RAM et conseils</h2>

<table>
  <tr><th>Données</th><th>Taille</th></tr>
  <tr><td>ProcgenMap + ProcgenContent×16</td><td>136 octets</td></tr>
  <tr><td>NgpcCaveMap (map 32×32)</td><td>1032 octets</td></tr>
  <tr><td>Viewport u8[20×19]</td><td>380 octets</td></tr>
  <tr><td>Fog of war (optionnel)</td><td>+1024 octets</td></tr>
  <tr><td><b>Donjon seul</b></td><td><b>136 octets</b></td></tr>
  <tr><td><b>Cave seule</b></td><td><b>1412 octets</b></td></tr>
</table>

<h3>Conseils</h3>
<ul>
  <li><b>Reproductibilité</b> : même seed → même donjon/cave.
      Stocke le seed en flash pour sauvegarder le niveau courant.</li>
  <li><b>Seed aléatoire</b> : utilise un timer VBlank ou
      <code>ngpc_rng_init_vbl()</code> pour un seed différent à chaque partie.</li>
  <li><b>Rendu cave</b> : appelle <code>ngpc_cavegen_viewport()</code> uniquement
      quand la caméra a bougé, pas à chaque frame — économise des cycles CPU.</li>
  <li><b>Donjon + mini-map</b> : la mini-map peut être affichée en texte
      (20 colonnes max → exactement 4×4 + espaces).</li>
  <li><b>Choisir le mode</b> : donjon si tu veux des rooms distinctes + boss ;
      cave si tu veux de l'exploration libre + ambiance oppressante.</li>
  <li><b>Combiner</b> : génère un donjon procédural, et chaque room utilise
      une mini-cave générée localement depuis <code>room_seed()</code>.</li>
</ul>

<h3>Fichiers de référence</h3>
<ul>
  <li><code>optional/ngpc_procgen/README.md</code> — doc complète donjon</li>
  <li><code>optional/ngpc_cavegen/README.md</code> — doc complète cave</li>
  <li><code>optional/ngpc_cavegen/ngpc_cavegen_example.c</code> — démo jouable
      (B = nouveau seed, OPTION = basculer donjon/cave)</li>
</ul>
"""


def _en_procgen() -> str:
    return """
<h1>Procedural Generation (Roguelike / Cave)</h1>

<h2>⚠ Two distinct systems — which one to use?</h2>

<table>
  <tr>
    <th></th>
    <th>PNG Manager — Level tab (Procgen)</th>
    <th>ngpc_procgen / ngpc_cavegen (C)</th>
  </tr>
  <tr>
    <td><b>What</b></td>
    <td>PC design tool</td>
    <td>C code that runs on the NGPC</td>
  </tr>
  <tr>
    <td><b>When</b></td>
    <td>At compile time (before the game)</td>
    <td>At runtime (during the game)</td>
  </tr>
  <tr>
    <td><b>Output</b></td>
    <td>Static PNG tilemap baked into ROM</td>
    <td>Different dungeon/cave every seed</td>
  </tr>
  <tr>
    <td><b>Requires code?</b></td>
    <td>No — click in the UI</td>
    <td><b>Yes</b> — C89, manual integration</td>
  </tr>
</table>

<h3>What the Level tab Procgen does</h3>
<p>It generates a <b>visual collision tilemap</b> (PNG SCR1/SCR2) to help
you design a map in the editor. The result is a static PNG file, exported
to C and included in the ROM. The player always sees the same map every game.</p>

<h3>What ngpc_procgen / ngpc_cavegen do</h3>
<p>These are <b>C modules</b> that run directly on NGPC hardware.
Generation happens when the level starts, in RAM. Every game produces a
different dungeon or cave. They require writing C code in your game.</p>

<h3>Can you combine both?</h3>
<p>Yes — that's actually the recommended approach:</p>
<ol>
  <li>Use the <b>PNG Manager</b> to design your room visuals
      (walls, floors, decorations) → export to ROM.</li>
  <li>In your C code, the <code>room_load_cb</code> callback receives
      <code>tpl-&gt;variant</code> (0=plain, 1=pillars, 2=divided…) →
      load the matching tileset from ROM.</li>
  <li><code>ngpc_procgen_generate_ex()</code> decides <b>which dungeon
      structure</b> to generate; your code handles the graphics.</li>
</ol>
<p>The link between the two is <b>not automatic</b> — you need a few lines
of C to connect the procgen template to your assets.</p>

<hr>

<h2>Mode 1 — Room-by-room dungeon (Dicing Knight)</h2>

<h3>Architecture</h3>
<p>The dungeon is a <b>4×4 grid</b> (configurable). Each active cell is a room =
one full NGPC screen (20×19 tiles).</p>

<ul>
  <li><b>ngpc_procgen</b> — Room-by-room dungeon (Dicing Knight style)</li>
  <li><b>ngpc_cavegen</b> — Open scrolling cave (Cave Noir style)</li>
</ul>

<hr>

<h2>Mode 1 — Room-by-room dungeon (Dicing Knight)</h2>

<h3>Architecture</h3>
<p>The dungeon is a <b>4×4 grid</b> (configurable). Each active cell is a
<b>room = one full NGPC screen</b> (20×19 tiles, 160×152 px).
Transitions happen through N/S/W/E doors drawn on the screen borders.</p>

<pre>
+---+---+---+---+
| S |   | . |   |   S = start     . = visited
+---+---+---+---+   @ = player    X = exit (boss)
|   | @ |===|   |   = = loop     ? = not visited
+---+---+---+---+
|   | . | X |   |
+---+---+---+---+
</pre>

<h3>Generation</h3>
<ol>
  <li>DFS from cell 0,0 → spanning tree (perfect maze)</li>
  <li>BFS → farthest room from start = <b>EXIT</b> (boss room)</li>
  <li>Optional loop injection (<code>loop_pct</code>) → shortcuts</li>
  <li>Template assignment by door configuration</li>
</ol>

<table>
  <tr><th>loop_pct</th><th>Result</th></tr>
  <tr><td>0</td><td>Perfect maze — exactly one path to each room</td></tr>
  <tr><td>20</td><td><b>Recommended</b> — good balance variety / readability</td></tr>
  <tr><td>35+</td><td>Very open dungeon, many alternate routes</td></tr>
</table>

<h3>Procedural content</h3>
<pre>ProcgenContent content[PROCGEN_MAX_ROOMS];
ngpc_procgen_gen_content(&amp;map, content, 3, 40);</pre>
<table>
  <tr><th>Room type</th><th>enemies</th><th>items</th><th>special</th></tr>
  <tr><td>START</td><td>0</td><td>0</td><td>0</td></tr>
  <tr><td>NORMAL</td><td>random</td><td>random</td><td>0</td></tr>
  <tr><td>EXIT (boss)</td><td>0xFF</td><td>—</td><td><b>1</b></td></tr>
  <tr><td>SHOP</td><td>0</td><td>0xFF</td><td><b>2</b></td></tr>
  <tr><td>SECRET</td><td>1 type</td><td>0xFF</td><td><b>3</b></td></tr>
</table>

<h3>Full code — init and update</h3>
<pre>#define PROCGEN_ROOMS_IMPL
#include "ngpc_procgen/ngpc_procgen.h"
#include "ngpc_procgen/ngpc_procgen_rooms.h"

static ProcgenMap     g_dungeon;
static ProcgenContent g_content[PROCGEN_MAX_ROOMS];
static u8 g_px, g_py;

/* Render callback — called on every room transition */
static void room_cb(const ProcgenCell *cell,
                    const NgpcRoomTemplate NGP_FAR *tpl,
                    u8 entry_dir, void *ud)
{
    u8 idx = g_dungeon.current_idx;
    ngpc_procgen_fill_room(cell, tpl,
                           TILE_WALL, TILE_FLOOR, TILE_PILLAR, 0u);
    if (!(cell-&gt;flags &amp; PROCGEN_FLAG_VISITED)) {
        /* Spawn g_content[idx].count enemies... */
    }
    (void)entry_dir; (void)ud;
}

/* Initialization (once per floor) */
void level_init(u16 seed)
{
    ngpc_procgen_generate_ex(&amp;g_dungeon,
        g_procgen_rooms, PROCGEN_ROOMS_COUNT, seed, 20u);
    ngpc_procgen_gen_content(&amp;g_dungeon, g_content, 3u, 40u);
    ngpc_procgen_load_room(&amp;g_dungeon, g_dungeon.start_idx,
        g_procgen_rooms, room_cb, 0xFFu, 0);
    ngpc_procgen_spawn_pos(0xFFu, &amp;g_px, &amp;g_py);
}

/* Update (each frame) */
void level_update(void)
{
    u8 cur = g_dungeon.current_idx;
    u8 dir = 0xFFu, next;
    /* move g_px, g_py... */
    if (g_py == 0u  &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_N)) dir = PROCGEN_DIR_N;
    if (g_py == 18u &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_S)) dir = PROCGEN_DIR_S;
    if (g_px == 0u  &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_W)) dir = PROCGEN_DIR_W;
    if (g_px == 19u &amp;&amp; (g_dungeon.cells[cur].exits &amp; PROCGEN_EXIT_E)) dir = PROCGEN_DIR_E;
    if (dir != 0xFFu) {
        next = ngpc_procgen_neighbor(&amp;g_dungeon, cur, dir);
        if (next != PROCGEN_IDX_NONE) {
            ngpc_procgen_load_room(&amp;g_dungeon, next,
                g_procgen_rooms, room_cb, dir, 0);
            ngpc_procgen_spawn_pos(dir, &amp;g_px, &amp;g_py);
        }
    }
}</pre>

<h3>Room templates and visual variants</h3>
<p><b>ngpc_procgen_rooms.h</b> provides 48 templates (3 variants × 16 door configs).
<code>fill_room()</code> draws the selected variant:</p>
<table>
  <tr><th>Variant</th><th>Visual</th></tr>
  <tr><td>0 — plain</td><td>Empty room, clear floor</td></tr>
  <tr><td>1 — pillars</td><td>4 symmetric pillars</td></tr>
  <tr><td>2 — divided</td><td>Partial horizontal wall with center gap</td></tr>
</table>
<p>To add your own layouts: add entries to <code>g_procgen_rooms[]</code>
with <code>variant &gt; 2</code>, then extend <code>ngpc_procgen_fill_room()</code>.</p>

<h3>Mini-map</h3>
<pre>for (y = 0; y &lt; PROCGEN_GRID_H; y++) {
    for (x = 0; x &lt; PROCGEN_GRID_W; x++) {
        u8 idx = procgen_cell_idx(x, y);
        char c = ' ';
        if (!procgen_cell_active(&amp;g_dungeon, idx)) c = ' ';
        else if (idx == g_dungeon.current_idx) c = '@';
        else if (idx == g_dungeon.exit_idx)    c = 'X';
        else if (g_dungeon.cells[idx].flags &amp; PROCGEN_FLAG_VISITED) c = '.';
        else c = '?';
        /* draw c at tile (x, minimap_row + y) */
    }
}</pre>

<hr>

<h2>Mode 2 — Open scrolling cave (Cave Noir)</h2>

<h3>Architecture</h3>
<p>The cave is a <b>32×32 tile</b> grid generated at the start of the game.
The player moves freely; the camera follows showing a
<b>20×19 tile window</b> (one NGPC screen).</p>

<pre>/* Tile types in the map */
CAVE_WALL  = 0   /* solid wall */
CAVE_FLOOR = 1   /* walkable floor */
CAVE_ENTRY = 2   /* player spawn */
CAVE_EXIT  = 3   /* level exit */
CAVE_CHEST = 4   /* chest / item */
CAVE_ENEMY = 5   /* enemy spawn */</pre>

<h3>Algorithm</h3>
<ol>
  <li><b>Random fill</b> — wall_pct% walls inside, borders always walls</li>
  <li><b>Smooth × 5</b> — Moore rule: ≥5 wall-neighbours → wall, else → floor</li>
  <li><b>Flood-fill</b> — keep only the largest connected floor region</li>
  <li><b>Placement</b> — entry on the left, exit on the right, enemies/chests in 8×8 sections</li>
</ol>

<table>
  <tr><th>wall_pct</th><th>Result</th></tr>
  <tr><td>40</td><td>Very open, large rooms, few corridors</td></tr>
  <tr><td><b>47</b></td><td><b>Recommended</b> — natural balanced cave</td></tr>
  <tr><td>52</td><td>Narrow, many corridors and dead ends</td></tr>
</table>

<h3>Full code — init and update</h3>
<pre>#include "ngpc_cavegen/ngpc_cavegen.h"

static NgpcCaveMap g_cave;
static u8 g_view[20 * 19];
static u8 g_px, g_py, g_cam_x, g_cam_y;

static const u16 s_tiles[6] = {
    TILE_WALL, TILE_FLOOR, TILE_FLOOR,
    TILE_EXIT, TILE_CHEST, TILE_ENEMY
};

void cave_render(void) {
    u8 x, y, t;
    for (y = 0u; y &lt; 19u; y++)
        for (x = 0u; x &lt; 20u; x++) {
            t = g_view[(u16)y * 20u + x];
            ngpc_gfx_put_tile(GFX_SCR1, x, y, s_tiles[t &lt; 6u ? t : 0u], 0u);
        }
}

void cave_init(u16 seed) {
    ngpc_cavegen_generate(&amp;g_cave, seed, 47u, 8u, 3u);
    g_px = g_cave.entry_x;
    g_py = g_cave.entry_y;
    ngpc_cavegen_cam_center(g_px, g_py, &amp;g_cam_x, &amp;g_cam_y);
    ngpc_cavegen_viewport(&amp;g_cave, g_cam_x, g_cam_y, g_view);
    cave_render();
}

void cave_update(void) {
    u8 new_px = g_px, new_py = g_py, tile;
    u8 new_cx, new_cy;
    /* move new_px/new_py based on pad... */
    tile = g_cave.map[(u16)new_py * CAVEGEN_W + new_px];
    if (tile == CAVE_WALL)  { new_px = g_px; new_py = g_py; } /* collision */
    if (tile == CAVE_CHEST) {
        g_cave.map[(u16)new_py * CAVEGEN_W + new_px] = CAVE_FLOOR;
        /* pick up item */
    }
    if (tile == CAVE_EXIT)  { /* go to next floor */ }
    g_px = new_px; g_py = new_py;
    ngpc_cavegen_cam_center(g_px, g_py, &amp;new_cx, &amp;new_cy);
    if (new_cx != g_cam_x || new_cy != g_cam_y) {
        g_cam_x = new_cx; g_cam_y = new_cy;
        ngpc_cavegen_viewport(&amp;g_cave, g_cam_x, g_cam_y, g_view);
        cave_render();  /* only re-render when camera moved */
    }
    ngpc_gfx_put_tile(GFX_SCR1,
        (u8)(g_px - g_cam_x), (u8)(g_py - g_cam_y), TILE_PLAYER, 0u);
}</pre>

<h3>Multiple floors</h3>
<pre>u16 g_seed = 0xCAFEu;

void next_floor(void) {
    g_seed = (u16)(g_seed * 0x6C07u + 0x3925u); /* simple LCG */
    cave_init(g_seed);
}</pre>

<hr>

<h2>Integration with the PNG Manager</h2>

<p>The <b>Level</b> tab of the PNG Manager contains its own tilemap collision
generator (Procgen tab). It generates <b>SCR1/SCR2 PNG files</b> from
collision maps — complementary to the C modules: the C Procgen handles
<b>dungeon structure</b>, the PNG Manager handles <b>visual room assets</b>.</p>

<p>Recommended workflow:</p>
<ol>
  <li>Design room tilesets in Aseprite (walls, floors, doors)</li>
  <li>Export via the PNG Manager (Palette + Tilemap tabs)</li>
  <li>In the <code>ProcgenLoadFn</code> callback, load assets based on
      <code>cell-&gt;template_id</code> and <code>tpl-&gt;variant</code></li>
  <li>Use <code>ngpc_procgen_fill_room()</code> as a base, then overlay real tile assets</li>
</ol>

<hr>

<h2>RAM budget and tips</h2>

<table>
  <tr><th>Data</th><th>Size</th></tr>
  <tr><td>ProcgenMap + ProcgenContent×16</td><td>136 bytes</td></tr>
  <tr><td>NgpcCaveMap (32×32 map)</td><td>1032 bytes</td></tr>
  <tr><td>Viewport u8[20×19]</td><td>380 bytes</td></tr>
  <tr><td>Fog of war (optional)</td><td>+1024 bytes</td></tr>
  <tr><td><b>Dungeon only</b></td><td><b>136 bytes</b></td></tr>
  <tr><td><b>Cave only</b></td><td><b>1412 bytes</b></td></tr>
</table>

<h3>Tips</h3>
<ul>
  <li><b>Reproducibility</b>: same seed → same dungeon/cave. Store the seed
      in flash save to remember the current floor.</li>
  <li><b>Random seed</b>: use a VBlank timer or <code>ngpc_rng_init_vbl()</code>
      for a different dungeon each game.</li>
  <li><b>Cave rendering</b>: call <code>ngpc_cavegen_viewport()</code> only when
      the camera moves — not every frame. Saves CPU cycles.</li>
  <li><b>Dungeon + mini-map</b>: the mini-map can be displayed as text
      (4 columns × 4 rows of chars fits within 20 tiles width).</li>
  <li><b>Choosing a mode</b>: dungeon for distinct rooms + boss fights;
      cave for free exploration + oppressive atmosphere.</li>
  <li><b>Combining</b>: generate a dungeon, then generate a mini-cave per
      room using <code>ngpc_procgen_room_seed()</code> as the cave seed.</li>
</ul>

<h3>Reference files</h3>
<ul>
  <li><code>optional/ngpc_procgen/README.md</code> — full dungeon documentation</li>
  <li><code>optional/ngpc_cavegen/README.md</code> — full cave documentation</li>
  <li><code>optional/ngpc_cavegen/ngpc_cavegen_example.c</code> — playable demo
      (B = new seed, OPTION = switch dungeon/cave)</li>
</ul>
"""


def _fr_dialogues() -> str:
    return """
<h1>Banque de dialogues — Référence</h1>

<p>L'onglet <b>Dialogues</b> gère le contenu textuel des dialogues RPG/aventure par scène.
Il génère <code>scene_&lt;name&gt;_dialogs.h</code> et s'intègre au système trigger via
<code>show_dialogue</code>, <code>open_menu</code>, <code>dialogue_done</code>, <code>choice_result</code> et <code>set_npc_dialogue</code>.</p>

<h2>Concepts</h2>
<table>
  <tr><th>Concept</th><th>Description</th></tr>
  <tr><td><b>Dialogue</b></td><td>Banque nommée (ex. <code>dlg_intro</code>) = séquence de lignes. Un NPC a en général un dialogue par étape de quête.</td></tr>
  <tr><td><b>Ligne</b></td><td>Une réplique : locuteur + texte + portrait optionnel.</td></tr>
  <tr><td><b>Choix</b></td><td>0–2 choix par ligne (runtime <code>ngpc_dialog</code>). Chaque choix a un label et un dialogue cible optionnel (→ goto). Affiché quand le texte de la ligne est terminé ; le joueur navigue au D-pad.</td></tr>
  <tr><td><b>Menu</b></td><td>Liste 2–8 items (runtime <code>ngpc_menu</code>). Séparé des dialogues, déclenché par <code>open_menu</code>. Chaque item a un label et un dialogue cible optionnel.</td></tr>
  <tr><td><b>Portrait</b></td><td>Sprite du projet affiché dans la boîte. Sélectionné avec un combo visuel (icône PNG).</td></tr>
  <tr><td><b>Fond (bg_sprite)</b></td><td>PNG 16×16, 4 tiles 8×8. Le hardware NGPC fait H/V flip natif — zéro CPU pour toutes les variantes.</td></tr>
  <tr><td><b>Palette texte</b></td><td>3 couleurs RGB444 éditables. Slot 0 = transparent hardware (fixe).</td></tr>
</table>

<h2>Workflow</h2>
<ol>
  <li>Sélectionnez la <b>scène cible</b> dans le combo en haut.</li>
  <li>Cliquez <b>+</b> pour ajouter un dialogue, donnez-lui un ID (ex. <code>dlg_elder_intro</code>).</li>
  <li>Cliquez <b>+</b> dans la liste Lignes pour ajouter des répliques.</li>
  <li>Renseignez <b>Locuteur</b> (≤ 12 car.), <b>Texte</b> (≤ 80 car.) et optionnellement un <b>Portrait</b>.</li>
  <li>Pour ajouter des <b>choix</b> à une ligne : cliquez <b>+</b> dans la section Choix (max 2). Renseignez le texte de chaque choix et optionnellement un dialogue cible (→). Les lignes avec choix affichent un ▸ dans la liste.</li>
  <li>Pour créer un <b>menu</b> : cliquez <b>+</b> dans la section Menus (panneau gauche). Ajoutez les items, chaque item a un label et un dialogue cible optionnel.</li>
  <li>Choisissez un <b>Fond</b> dans le combo (ou laissez vide pour la boîte par défaut).</li>
  <li>Ajustez la <b>Palette texte</b> en cliquant les swatches de couleur.</li>
  <li>L'<b>aperçu NGPC</b> (3×) met à jour en temps réel.</li>
  <li>Exportez via l'onglet <b>Projet</b> → <code>scene_*_dialogs.h</code> est généré automatiquement.</li>
</ol>

<h2>Fond custom (dialogue_box.png)</h2>
<p>Le PNG de fond doit faire <b>16×16 px</b> et contenir 4 tiles 8×8 :</p>
<table>
  <tr><th>Position</th><th>Tile</th><th>Variantes hardware</th></tr>
  <tr><td>Haut-gauche [0,0]</td><td>Coin TL</td><td>H-flip=TR, V-flip=BL, HV-flip=BR</td></tr>
  <tr><td>Haut-droite [8,0]</td><td>Bord H haut</td><td>V-flip = bord bas</td></tr>
  <tr><td>Bas-gauche [0,8]</td><td>Fill (centre)</td><td>Répété pour remplir</td></tr>
  <tr><td>Bas-droite [8,8]</td><td>Bord V droite</td><td>H-flip = bord gauche</td></tr>
</table>
<p>Un exemple <code>dialogue_box.png</code> est fourni dans <code>GraphX/</code> du template.</p>
<p>Les constantes d'offset sont exportées dans le header :</p>
<pre>#define DLG_BG_CORNER_OFS   0  /* coin TL; H-flip=TR, V-flip=BL, HV=BR */
#define DLG_BG_HBORDER_OFS  1  /* bord top; V-flip = bas                */
#define DLG_BG_FILL_OFS     2  /* centre, répété                        */
#define DLG_BG_VBORDER_OFS  3  /* bord droite; H-flip = gauche          */</pre>

<h2>Palette texte</h2>
<p>3 swatches cliquables + 1 transparent fixe :</p>
<table>
  <tr><th>Slot</th><th>Rôle</th><th>Défaut</th></tr>
  <tr><td>0 (T)</td><td>Transparent — fixe hardware</td><td>—</td></tr>
  <tr><td>1</td><td>Couleur texte principal</td><td>#000 (noir)</td></tr>
  <tr><td>2</td><td>Couleur locuteur / mise en valeur</td><td>#888 (gris)</td></tr>
  <tr><td>3</td><td>Couleur accent</td><td>#FFF (blanc)</td></tr>
</table>
<p>Les couleurs sont en RGB444 (NGPC natif). Exportées comme :</p>
<pre>#define DLG_PAL_1  0x0000  /* slot 1 */
#define DLG_PAL_2  0x0888  /* slot 2 */
#define DLG_PAL_3  0x0FFF  /* slot 3 */</pre>

<h2>Import / Export CSV</h2>
<p>Format des colonnes : <code>dialogue_id, line_index, speaker, text, portrait</code></p>
<p>Utilisez <b>Exporter CSV</b> pour obtenir un tableur à remplir par vos auteurs, puis <b>Importer CSV</b> pour injecter le contenu. Les dialogues existants sont remplacés ; les nouveaux sont créés.</p>

<h2>Export C — scene_*_dialogs.h</h2>
<pre>static const char* g_dlg_intro[] = {
    "\\x01Elder\\x02Bienvenue, voyageur.",
    "\\x01Elder\\x02Tu dois trouver la clé.",
    NULL
};
#define DLG_INTRO 0
#define DLG_COUNT 1</pre>
<p>Encodage : <code>\\x01</code> = début locuteur, <code>\\x02</code> = séparateur texte, <code>NULL</code> = fin.</p>
<p>Pour les lignes avec choix :</p>
<pre>static const char* g_dlg_intro_l1_choices[] = { "OUI", "NON", NULL };
static const u8    g_dlg_intro_l1_goto[]    = { DLG_ACCEPT, 0xFF }; // 0xFF = fermer
#define DLG_INTRO_L1_CHOICE_COUNT 2</pre>
<p>Pour les menus :</p>
<pre>static const char* g_menu_shop_items[] = { "Acheter", "Vendre", "Partir", NULL };
static const u8    g_menu_shop_goto[]  = { DLG_BUY, DLG_SELL, 0xFF };
#define MENU_SHOP        0
#define MENU_SHOP_COUNT  3
#define MENU_COUNT       1</pre>

<h2>Triggers associés</h2>
<table>
  <tr><th>Trigger</th><th>Usage</th></tr>
  <tr><td><code>show_dialogue(a0=idx)</code></td><td>Afficher un dialogue. Sélecteur combo dans l'onglet Triggers.</td></tr>
  <tr><td><code>open_menu(a0=idx)</code></td><td>Afficher un menu ngpc_menu. Sélecteur combo dans l'onglet Triggers.</td></tr>
  <tr><td><code>dialogue_done(value=idx)</code></td><td>Condition : ce dialogue a déjà été joué.</td></tr>
  <tr><td><code>choice_result(region=dlg, value=0/1)</code></td><td>Condition : le choix 0 ou 1 a été sélectionné dans ce dialogue.</td></tr>
  <tr><td><code>menu_result(region=menu, value=item)</code></td><td>Condition : l'item <em>item</em> a été sélectionné dans le menu <em>menu</em>.</td></tr>
  <tr><td><code>set_npc_dialogue(a0=entity, a1=idx)</code></td><td>Changer le dialogue d'un NPC. Exemple : après une quête, l'elder dit autre chose.</td></tr>
</table>

<h2>Exemple RPG — flow complet avec choix</h2>
<pre>// Première rencontre (ligne 0 = texte, ligne 1 = texte + 2 choix : OUI / NON)
[npc_talked_to NPC_elder]         → show_dialogue "dlg_intro"       [once]
[choice_result dlg_intro, choix=0]→ set_flag FLAG_ACCEPT             // OUI
[choice_result dlg_intro, choix=0]→ show_dialogue "dlg_elder_quest"
[choice_result dlg_intro, choix=1]→ show_dialogue "dlg_elder_refuse" // NON

// Boutique
[player_in_region shop_zone]      → open_menu "menu_shop"
[dialogue_done dlg_intro]         → set_npc_dialogue NPC_elder "dlg_repeat"

// Quête terminée
[flag_set FLAG_QUEST_DONE]        → set_npc_dialogue NPC_elder "dlg_thanks"</pre>

<h2>Aperçu temps réel</h2>
<p>Le widget d'aperçu (3×, 160×40 px) reflète le rendu NGPC :</p>
<ul>
  <li><b>Police bitmap</b> : si le projet a une police custom (<code>custom_font_png</code>), les glyphes 8×8 réels sont utilisés à la place de Courier. Les pixels sombres (R,G,B&lt;64) = encre, colorisés avec la palette active.</li>
  <li><b>Plein écran</b> : cochez <b>Plein écran</b> pour voir la boîte dans son contexte 160×152 avec la zone gameplay sombre au-dessus.</li>
  <li><b>Compteur de tiles par ligne</b> : sous le champ texte, <code>L1:12/18  L2:8/18</code> — 18 colonnes sans portrait, 15 avec. Un ⚠ signale le débordement.</li>
</ul>
"""


def _en_dialogues() -> str:
    return """
<h1>Dialogue Bank — Reference</h1>

<p>The <b>Dialogues</b> tab manages RPG/adventure dialogue content per scene.
It generates <code>scene_&lt;name&gt;_dialogs.h</code> and integrates with the trigger system via
<code>show_dialogue</code>, <code>open_menu</code>, <code>dialogue_done</code>, <code>choice_result</code> and <code>set_npc_dialogue</code>.</p>

<h2>Concepts</h2>
<table>
  <tr><th>Concept</th><th>Description</th></tr>
  <tr><td><b>Dialogue</b></td><td>A named bank (e.g. <code>dlg_intro</code>) = sequence of lines. An NPC typically has one dialogue per quest stage.</td></tr>
  <tr><td><b>Line</b></td><td>One reply: speaker + text + optional portrait.</td></tr>
  <tr><td><b>Choices</b></td><td>0–2 choices per line (<code>ngpc_dialog</code> runtime). Each choice has a label and an optional target dialogue (→ goto). Shown when the line's text is complete; player navigates with D-pad.</td></tr>
  <tr><td><b>Menu</b></td><td>2–8 items list (<code>ngpc_menu</code> runtime). Separate from dialogues, triggered by <code>open_menu</code>. Each item has a label and an optional target dialogue.</td></tr>
  <tr><td><b>Portrait</b></td><td>A project sprite displayed in the box. Selected with a visual combo (PNG icon).</td></tr>
  <tr><td><b>Background (bg_sprite)</b></td><td>16×16 PNG, 4 tiles 8×8. NGPC hardware handles H/V flips natively — zero CPU cost for all variants.</td></tr>
  <tr><td><b>Text palette</b></td><td>3 editable RGB444 color slots. Slot 0 = hardware-transparent (fixed).</td></tr>
</table>

<h2>Workflow</h2>
<ol>
  <li>Select the <b>target scene</b> in the top combo.</li>
  <li>Click <b>+</b> to add a dialogue, give it an ID (e.g. <code>dlg_elder_intro</code>).</li>
  <li>Click <b>+</b> in the Lines list to add replies.</li>
  <li>Fill in <b>Speaker</b> (≤ 12 chars), <b>Text</b> (≤ 80 chars) and optionally a <b>Portrait</b>.</li>
  <li>To add <b>choices</b> to a line: click <b>+</b> in the Choices section (max 2). Fill the label of each choice and optionally pick a target dialogue. Lines with choices show a ▸ in the list.</li>
  <li>To create a <b>menu</b>: click <b>+</b> in the Menus section (left panel). Add items with label + optional target dialogue.</li>
  <li>Pick a <b>Background</b> in the combo (or leave blank for the default box).</li>
  <li>Adjust the <b>Text palette</b> by clicking the color swatches.</li>
  <li>The <b>NGPC preview</b> (3×) updates in real time.</li>
  <li>Export from the <b>Project</b> tab → <code>scene_*_dialogs.h</code> is generated automatically.</li>
</ol>

<h2>Custom background (dialogue_box.png)</h2>
<p>The background PNG must be <b>16×16 px</b> with 4 tiles 8×8:</p>
<table>
  <tr><th>Position</th><th>Tile</th><th>Hardware variants</th></tr>
  <tr><td>Top-left [0,0]</td><td>Corner TL</td><td>H-flip=TR, V-flip=BL, HV-flip=BR</td></tr>
  <tr><td>Top-right [8,0]</td><td>H-border top</td><td>V-flip = bottom border</td></tr>
  <tr><td>Bottom-left [0,8]</td><td>Fill (centre)</td><td>Tiled to fill interior</td></tr>
  <tr><td>Bottom-right [8,8]</td><td>V-border right</td><td>H-flip = left border</td></tr>
</table>
<p>A <code>dialogue_box.png</code> example is included in the template's <code>GraphX/</code> folder.</p>
<p>Offset constants are exported in the header:</p>
<pre>#define DLG_BG_CORNER_OFS   0  /* TL; H-flip=TR, V-flip=BL, HV=BR */
#define DLG_BG_HBORDER_OFS  1  /* top edge; V-flip = bottom edge   */
#define DLG_BG_FILL_OFS     2  /* centre fill, tiled               */
#define DLG_BG_VBORDER_OFS  3  /* right edge; H-flip = left edge   */</pre>

<h2>Text palette</h2>
<p>3 clickable swatches + 1 fixed transparent:</p>
<table>
  <tr><th>Slot</th><th>Role</th><th>Default</th></tr>
  <tr><td>0 (T)</td><td>Transparent — hardware fixed</td><td>—</td></tr>
  <tr><td>1</td><td>Main text color</td><td>#000 (black)</td></tr>
  <tr><td>2</td><td>Speaker / highlight color</td><td>#888 (grey)</td></tr>
  <tr><td>3</td><td>Accent color</td><td>#FFF (white)</td></tr>
</table>
<p>Colors are RGB444 (NGPC native). Exported as:</p>
<pre>#define DLG_PAL_1  0x0000  /* slot 1 */
#define DLG_PAL_2  0x0888  /* slot 2 */
#define DLG_PAL_3  0x0FFF  /* slot 3 */</pre>

<h2>CSV import / export</h2>
<p>Column format: <code>dialogue_id, line_index, speaker, text, portrait</code></p>
<p>Use <b>Export CSV</b> to get a spreadsheet for your writers, then <b>Import CSV</b> to inject the content. Existing dialogues are replaced; new ones are created.</p>

<h2>C export — scene_*_dialogs.h</h2>
<pre>static const char* g_dlg_intro[] = {
    "\\x01Elder\\x02Welcome, traveller.",
    "\\x01Elder\\x02You must find the key.",
    NULL
};
#define DLG_INTRO 0
#define DLG_COUNT 1</pre>
<p>For lines with choices:</p>
<pre>static const char* g_dlg_intro_l1_choices[] = { "YES", "NO", NULL };
static const u8    g_dlg_intro_l1_goto[]    = { DLG_ACCEPT, 0xFF }; // 0xFF = close
#define DLG_INTRO_L1_CHOICE_COUNT 2</pre>
<p>For menus:</p>
<pre>static const char* g_menu_shop_items[] = { "Buy", "Sell", "Leave", NULL };
static const u8    g_menu_shop_goto[]  = { DLG_BUY, DLG_SELL, 0xFF };
#define MENU_SHOP        0
#define MENU_SHOP_COUNT  3
#define MENU_COUNT       1</pre>

<h2>Related triggers</h2>
<table>
  <tr><th>Trigger</th><th>Use</th></tr>
  <tr><td><code>show_dialogue(a0=idx)</code></td><td>Show a dialogue. Combo selector in the Triggers tab.</td></tr>
  <tr><td><code>open_menu(a0=idx)</code></td><td>Show a menu (ngpc_menu). Combo selector in the Triggers tab.</td></tr>
  <tr><td><code>dialogue_done(value=idx)</code></td><td>Condition: this dialogue has already been played.</td></tr>
  <tr><td><code>choice_result(region=dlg, value=0/1)</code></td><td>Condition: choice 0 or 1 was selected in this dialogue.</td></tr>
  <tr><td><code>menu_result(region=menu, value=item)</code></td><td>Condition: item <em>item</em> was selected in menu <em>menu</em>.</td></tr>
  <tr><td><code>set_npc_dialogue(a0=entity, a1=idx)</code></td><td>Change an NPC's dialogue. Example: after a quest, the elder says something different.</td></tr>
</table>

<h2>RPG example — full flow with choices</h2>
<pre>// First encounter (line 1 = text + 2 choices: YES / NO)
[npc_talked_to NPC_elder]          → show_dialogue "dlg_intro"      [once]
[choice_result dlg_intro, choice=0]→ set_flag FLAG_ACCEPT             // YES
[choice_result dlg_intro, choice=0]→ show_dialogue "dlg_elder_quest"
[choice_result dlg_intro, choice=1]→ show_dialogue "dlg_elder_refuse" // NO

// Shop
[player_in_region shop_zone]       → open_menu "menu_shop"

// Quest complete
[flag_set FLAG_QUEST_DONE]         → set_npc_dialogue NPC_elder "dlg_thanks"</pre>

<h2>Real-time preview</h2>
<p>The preview widget (3×, 160×40 px) reflects the NGPC output:</p>
<ul>
  <li><b>Bitmap font</b>: if the project has a custom font (<code>custom_font_png</code>), the actual 8×8 glyphs are used instead of Courier. Dark pixels (R,G,B&lt;64) = ink, tinted with the active palette.</li>
  <li><b>Fullscreen</b>: check <b>Fullscreen</b> to see the box in its 160×152 context with the dark gameplay area above.</li>
  <li><b>Per-line tile counter</b>: below the text field, <code>L1:12/18  L2:8/18</code> — 18 columns without portrait, 15 with. A ⚠ warns about overflow.</li>
</ul>
"""


def _fr_troubleshoot() -> str:
    return """
<h1>Dépannage — Problèmes fréquents</h1>

<h2>BG tout noir, sprites OK</h2>
<p>Cause la plus fréquente : la tilemap de background n'est jamais écrite
en VRAM correctement. Plusieurs cas connus :</p>

<h3>1. Grande map + mapstream — BG noir, sprites OK</h3>
<p>Lorsque SCR1 est une grande map (&gt; 32×32 tiles) gérée par
<code>ngpc_mapstream</code>, le fond peut rester noir si la chaîne
de compilation n'est pas à jour. Causes les plus fréquentes :</p>
<ul>
  <li><b><code>NGPNG_HAS_MAPSTREAM</code> absent des CDEFS</b> — le bloc
      d'init est compilé à 0. <b>Fix :</b> re-exporter le projet pour
      régénérer <code>assets_autogen.mk</code> (le flag est ajouté
      automatiquement si un fichier <code>*_bg_map.c</code> est présent).</li>
  <li><b>Header de scène non inclus</b> — <code>ngpng_autorun_main.c</code>
      ne voit pas l'<code>extern g_XXX_bg_map[]</code>. <b>Fix :</b>
      re-exporter pour régénérer <code>ngpng_autorun_main.c</code> (l'include
      est ajouté automatiquement).</li>
  <li><b>Mauvais nombre d'arguments</b> — appel update sans pointeur
      <code>map_tiles</code>. <b>Fix :</b> re-exporter.</li>
</ul>
<p>→ En cas de BG noir sur grande map : <b>toujours re-exporter le projet
depuis PNG Manager</b> pour s'assurer que les fichiers générés sont à jour.</p>

<h3>2. Palette 0 couleur 0 non initialisée — texte noir sur noir</h3>
<p>Le BIOS initialise parfois la palette 0 de SCR1 à une couleur non-noire.
Si <code>ngpc_gfx_set_palette(GFX_SCR1, 0, ...)</code> n'est pas appelé
explicitement, le fond peut sembler normal mais le texte debug est invisible
(noir sur noir ou blanc sur blanc).</p>
<p><b>Fix :</b> Toujours appeler <code>ngpc_gfx_set_palette(GFX_SCR1, 0u, ...)</code>
dans l'init ou la fonction <code>scene_enter()</code>.</p>

<h3>3. SCR1 effacé après l'init de la tilemap</h3>
<p>Si <code>ngpc_gfx_clear(GFX_SCR1)</code> est appelé APRÈS avoir rempli
la tilemap en VRAM, tout le travail de la tilemap est effacé.</p>
<p><b>Ordre correct dans scene_load_all() :</b></p>
<pre>ngpc_gfx_clear(GFX_SCR1);       // 1. clear d'abord
ngpc_gfx_clear(GFX_SCR2);
scene_blit_tilemaps();           // 2. charge tiles + palettes
// ngpc_mapstream_init() après   // 3. remplissage tilemap (appelé depuis main())</pre>

<h3>4. tile_base mal appliqué</h3>
<p>Les tilewords dans <code>g_{scene}_bg_map[]</code> sont pré-calculés avec
<code>tile_base</code> inclus par le générateur
(<code>(tile_base + idx) | (pal &lt;&lt; 9)</code>).
Si vous modifiez <code>tile_base</code> dans le projet sans re-exporter,
les tilewords pointent vers de mauvais slots VRAM → fond noir ou artefacts.</p>
<p><b>Fix :</b> Re-exporter après tout changement de tile_base.</p>

<h3>5. DUAL LARGE-MAP BLOCKED — SCR2 jamais rempli</h3>
<p>Si SCR1 <i>et</i> SCR2 sont tous les deux des grandes maps (> 32×32), le
générateur désactive le streaming de SCR2 (budget VBlank insuffisant pour
streamer deux plans). SCR2 tombe en mode scroll hardware pur — il affichera
les tiles 0 si la tilemap SCR2 n'a pas été pré-remplie.</p>
<p><b>Fix :</b> Garder <b>au maximum un scroll plane > 32×32 par scène</b>.
L'autre plan doit rester ≤ 32×32 tiles pour être chargé statiquement avec
<code>NGP_TILEMAP_PUT_MAP_SCR2()</code>.</p>

<h2>Sprites visibles mais positionnés bizarrement</h2>
<ul>
  <li><b>offset render_off_x/y mal réglé</b> — vérifier les hitbox settings dans le
      bundle / level editor.</li>
  <li><b>tile_base sprites incorrect</b> — re-vérifier que les slots VRAM ne se
      chevauchent pas entre tiles tilemap (≥128) et tiles sprites.</li>
</ul>

<h2>Tout noir (fond ET sprites)</h2>
<ul>
  <li>Watchdog non kické dans une boucle d'init longue → reset console.
      Pattern : <code>*(volatile u8*)0x006F = 0x4E;</code> toutes les 64 itérations.</li>
  <li>FAR pointer manquant sur données ROM → lecture RAM corrompue.
      Toujours déclarer <code>NGP_FAR</code> sur les tableaux de tiles/palettes/maps.</li>
  <li>Crash au démarrage (division par zéro, pointeur null) — tester avec émulateur +
      breakpoints GDB.</li>
</ul>
"""


def _en_troubleshoot() -> str:
    return """
<h1>Troubleshooting — Common Issues</h1>

<h2>Background all black, sprites OK</h2>
<p>Most common cause: the background tilemap is never written to VRAM correctly.
Known cases:</p>

<h3>1. Large map + mapstream — black BG, sprites OK</h3>
<p>When SCR1 is a large map (&gt; 32×32 tiles) managed by
<code>ngpc_mapstream</code>, the background may remain black if the
generated files are out of date. Most common causes:</p>
<ul>
  <li><b><code>NGPNG_HAS_MAPSTREAM</code> missing from CDEFS</b> — the
      init block compiles to nothing. <b>Fix:</b> re-export the project to
      regenerate <code>assets_autogen.mk</code> (the flag is added
      automatically when a <code>*_bg_map.c</code> file is present).</li>
  <li><b>Scene header not included</b> — <code>ngpng_autorun_main.c</code>
      cannot see the <code>extern g_XXX_bg_map[]</code> declaration.
      <b>Fix:</b> re-export to regenerate <code>ngpng_autorun_main.c</code>
      (the include is added automatically).</li>
  <li><b>Wrong number of arguments</b> — update call missing the
      <code>map_tiles</code> pointer. <b>Fix:</b> re-export.</li>
</ul>
<p>→ For black BG on a large map: <b>always re-export from PNG Manager</b>
to ensure generated files are current.</p>

<h3>2. Palette 0 color 0 not set — black text on black</h3>
<p>The BIOS may not initialize SCR1 palette 0 to black. If
<code>ngpc_gfx_set_palette(GFX_SCR1, 0, ...)</code> is never called,
the background may look correct but debug text is invisible.</p>
<p><b>Fix:</b> Always call <code>ngpc_gfx_set_palette(GFX_SCR1, 0u, ...)</code>
in init or <code>scene_enter()</code>.</p>

<h3>3. SCR1 cleared after tilemap init</h3>
<p>If <code>ngpc_gfx_clear(GFX_SCR1)</code> is called AFTER the tilemap is
filled in VRAM, the tile data is wiped.</p>
<p><b>Correct order in scene_load_all():</b></p>
<pre>ngpc_gfx_clear(GFX_SCR1);       // 1. clear first
ngpc_gfx_clear(GFX_SCR2);
scene_blit_tilemaps();           // 2. load tiles + palettes
// ngpc_mapstream_init() after   // 3. fill tilemap (called from main())</pre>

<h3>4. tile_base mismatch</h3>
<p>Tilewords in <code>g_{scene}_bg_map[]</code> are pre-baked with
<code>tile_base</code> by the generator
(<code>(tile_base + idx) | (pal &lt;&lt; 9)</code>).
If you change <code>tile_base</code> in the project without re-exporting,
tilewords reference wrong VRAM slots → black or garbled background.</p>
<p><b>Fix:</b> Re-export after any tile_base change.</p>

<h3>5. DUAL LARGE-MAP BLOCKED — SCR2 never filled</h3>
<p>If both SCR1 and SCR2 are large maps (&gt; 32×32), the generator disables
SCR2 streaming (insufficient VBlank budget to stream two planes).
SCR2 falls back to hardware scroll-wrap — it will show tile 0 if its tilemap
was not pre-filled statically.</p>
<p><b>Fix:</b> Keep <b>at most one scroll plane &gt; 32×32 per scene</b>.
The other plane must stay ≤ 32×32 to be loaded statically with
<code>NGP_TILEMAP_PUT_MAP_SCR2()</code>.</p>

<h2>Sprites visible but mispositioned</h2>
<ul>
  <li><b>Wrong render_off_x/y</b> — check hitbox settings in the bundle / level editor.</li>
  <li><b>Wrong sprite tile_base</b> — verify VRAM slots don't overlap between tilemap
      tiles (≥128) and sprite tiles.</li>
</ul>

<h2>Everything black (background AND sprites)</h2>
<ul>
  <li>Watchdog not kicked inside a long init loop → console reset.
      Pattern: <code>*(volatile u8*)0x006F = 0x4E;</code> every 64 iterations.</li>
  <li>Missing FAR pointer on ROM data → corrupted reads.
      Always declare <code>NGP_FAR</code> on tile/palette/map arrays.</li>
  <li>Crash at startup (division by zero, null pointer) — test with emulator +
      GDB breakpoints.</li>
</ul>
"""


def _fr_scene_map() -> str:
    return """
<h1>Scene Map</h1>

<p>L'onglet <b>Scene Map</b> (groupe Project) affiche toutes les scènes du projet sous forme de cartes
draggables sur un canvas infini. Les flèches sont tracées automatiquement depuis les triggers
<code>goto_scene</code> / <code>warp_to</code>.</p>

<h2>Navigation</h2>
<ul>
  <li><b>Zoom</b> : molette souris.</li>
  <li><b>Déplacer le canvas</b> : clic-gauche + glisser sur fond vide.</li>
  <li><b>Déplacer une carte</b> : clic-gauche + glisser sur la carte.</li>
  <li><b>Ouvrir une scène</b> : double-clic sur la carte → ouvre dans l'onglet Level.</li>
  <li><b>Fit All</b> : bouton toolbar, recentre la vue sur toutes les cartes.</li>
  <li><b>Auto Layout</b> : bouton toolbar, réorganise les cartes en grille propre.</li>
</ul>

<h2>Cartes — informations affichées</h2>
<table>
  <tr><th>Élément</th><th>Signification</th></tr>
  <tr><td>Titre</td><td>Nom de la scène</td></tr>
  <tr><td>Sous-titre</td><td>Profil de jeu (Platformer, Shmup, RPG…)</td></tr>
  <tr><td>Dimensions</td><td>Taille en tiles (ex. 40×19 tiles)</td></tr>
  <tr><td>Miniature droite</td><td>Aperçu de la première tilemap assignée à la scène</td></tr>
  <tr><td><span style="color:#4caf70">●</span> Vert</td><td>Scène complète : tilemap assignée + entité joueur placée</td></tr>
  <tr><td><span style="color:#e0a020">●</span> Orange</td><td>Tilemap présente mais pas d'entité joueur placée</td></tr>
  <tr><td><span style="color:#555566">●</span> Gris</td><td>Aucune tilemap assignée</td></tr>
  <tr><td><code>⬡ N</code></td><td>Nombre d'entités placées dans la scène</td></tr>
  <tr><td>Bande verte + badge "▶ START"</td><td>Scène de départ du jeu</td></tr>
</table>

<h2>Flèches de transition</h2>
<p>Chaque flèche représente un trigger <code>goto_scene</code> ou <code>warp_to</code>.
Cliquez sur une flèche pour voir ses détails dans la bande d'info en bas :</p>
<pre>Source  →  Destination   [condition]</pre>
<p>Survoler une carte met ses flèches en évidence et atténue les autres — utile sur un grand projet.</p>

<h2>Menu clic-droit</h2>
<table>
  <tr><th>Action</th><th>Effet</th></tr>
  <tr><td>Open scene</td><td>Ouvre la scène dans l'onglet Level</td></tr>
  <tr><td>Rename…</td><td>Renommer la scène</td></tr>
  <tr><td>Duplicate</td><td>Copie complète de la scène (nouveau ID)</td></tr>
  <tr><td>Set as start scene</td><td>Définit cette scène comme point d'entrée du jeu</td></tr>
  <tr><td>Delete scene…</td><td>Suppression (confirmation requise)</td></tr>
</table>

<h2>Filtre par genre</h2>
<p>Le combo <b>Filter</b> dans la toolbar liste les profils présents.
Sélectionner un profil masque les autres scènes et leurs flèches.
Utile sur un projet avec 20+ scènes de types variés.</p>

<h2>Export PNG</h2>
<p>Le bouton <b>Export PNG</b> exporte la carte complète en image pour de la documentation
ou un partage rapide.</p>
"""


def _en_scene_map() -> str:
    return """
<h1>Scene Map</h1>

<p>The <b>Scene Map</b> tab (Project group) displays all project scenes as draggable cards
on an infinite canvas. Arrows are drawn automatically from <code>goto_scene</code> /
<code>warp_to</code> triggers.</p>

<h2>Navigation</h2>
<ul>
  <li><b>Zoom</b>: mouse wheel.</li>
  <li><b>Pan canvas</b>: left-click + drag on empty background.</li>
  <li><b>Move card</b>: left-click + drag on a card.</li>
  <li><b>Open scene</b>: double-click on a card → opens in the Level tab.</li>
  <li><b>Fit All</b>: toolbar button, re-centers the view on all cards.</li>
  <li><b>Auto Layout</b>: toolbar button, reorganises cards into a clean grid.</li>
</ul>

<h2>Cards — information displayed</h2>
<table>
  <tr><th>Element</th><th>Meaning</th></tr>
  <tr><td>Title</td><td>Scene name</td></tr>
  <tr><td>Subtitle</td><td>Game profile (Platformer, Shmup, RPG…)</td></tr>
  <tr><td>Dimensions</td><td>Size in tiles (e.g. 40×19 tiles)</td></tr>
  <tr><td>Right thumbnail</td><td>Preview of the first tilemap assigned to the scene</td></tr>
  <tr><td><span style="color:#4caf70">●</span> Green</td><td>Complete scene: tilemap assigned + player entity placed</td></tr>
  <tr><td><span style="color:#e0a020">●</span> Orange</td><td>Tilemap present but no player entity placed</td></tr>
  <tr><td><span style="color:#555566">●</span> Grey</td><td>No tilemap assigned</td></tr>
  <tr><td><code>⬡ N</code></td><td>Number of entities placed in the scene</td></tr>
  <tr><td>Green stripe + "▶ START" badge</td><td>Game entry point</td></tr>
</table>

<h2>Transition arrows</h2>
<p>Each arrow represents a <code>goto_scene</code> or <code>warp_to</code> trigger.
Click an arrow to see its details in the info strip at the bottom:</p>
<pre>Source  →  Destination   [condition]</pre>
<p>Hovering over a card highlights its arrows and dims all others — helpful in large projects.</p>

<h2>Right-click menu</h2>
<table>
  <tr><th>Action</th><th>Effect</th></tr>
  <tr><td>Open scene</td><td>Opens the scene in the Level tab</td></tr>
  <tr><td>Rename…</td><td>Rename the scene</td></tr>
  <tr><td>Duplicate</td><td>Full copy of the scene (new ID)</td></tr>
  <tr><td>Set as start scene</td><td>Sets this scene as the game entry point</td></tr>
  <tr><td>Delete scene…</td><td>Deletion (confirmation required)</td></tr>
</table>

<h2>Genre filter</h2>
<p>The <b>Filter</b> combo in the toolbar lists the profiles present in the project.
Selecting a profile hides other scenes and their arrows.
Useful in projects with 20+ scenes of mixed types.</p>

<h2>Export PNG</h2>
<p>The <b>Export PNG</b> button exports the full map as an image for documentation
or quick sharing.</p>
"""


def _fr_scene_map_nav() -> str:
    return """
<h1>Scene Map — Navigation &amp; Actions (MAP-3 à MAP-10)</h1>

<h2>MAP-3 — Highlight connexions au survol</h2>
<p>Survoler une carte met en évidence ses flèches entrantes/sortantes (bleu clair) et atténue toutes les autres.
Indispensable quand le projet dépasse une dizaine de scènes.</p>

<h2>MAP-4 — Menu contextuel clic-droit</h2>
<p>Clic-droit sur une carte → menu contextuel :</p>
<table>
  <tr><th>Action</th><th>Effet</th></tr>
  <tr><td>Open scene</td><td>Équivalent double-clic — ouvre la scène dans l'onglet Level</td></tr>
  <tr><td>Rename…</td><td>Dialogue de saisie — renomme la scène sur le canvas et dans les données</td></tr>
  <tr><td>Duplicate</td><td>Copie profonde de la scène (nouveau UUID, label " (copy)"), ajoutée en fin de liste</td></tr>
  <tr><td>Set as start scene</td><td>Définit cette scène comme point d'entrée du jeu</td></tr>
  <tr><td>Delete scene…</td><td>Suppression avec confirmation — irréversible</td></tr>
</table>

<h2>MAP-5 — Indicateur START amélioré</h2>
<p>La scène de départ est distinguée par :</p>
<ul>
  <li>Une <b>bande verte</b> en haut de la carte.</li>
  <li>Un <b>badge pill "▶ START"</b> fond vert en bas-droite.</li>
  <li>La bordure verte existante.</li>
</ul>

<h2>MAP-6 — Info strip au clic sur une flèche</h2>
<p>Cliquer sur une flèche de transition affiche une bande d'information en bas de la vue :</p>
<pre>Source  →  Destination   [condition]</pre>
<p>Le type de transition (<code>goto_scene</code> ou <code>⤳ Warp</code>) est indiqué.
Cliquez ✕ ou ailleurs pour masquer la bande.</p>
<p><b>Astuce :</b> la zone de clic des flèches est élargie (12 px) pour faciliter la sélection.</p>

<h2>MAP-7 — Filtre par genre</h2>
<p>Le combo <b>Filter</b> dans la toolbar liste tous les profils présents dans le projet.
Sélectionner un profil masque les autres scènes (et leurs flèches).
"All profiles" restaure la vue complète.</p>

<h2>MAP-8 — Export PNG</h2>
<p>Le bouton <b>Export PNG</b> dans la toolbar ouvre un dialogue de sauvegarde et génère une image PNG de
toute la Scene Map avec le fond sombre correct.</p>

<h2>MAP-10 — Badge count entités</h2>
<p>Un badge <code>⬡ N</code> dans le coin bas-droit de la zone texte indique le nombre d'entités placées
dans la scène. N=0 → badge masqué.</p>
"""


def _en_scene_map_nav() -> str:
    return """
<h1>Scene Map — Navigation &amp; Actions (MAP-3 to MAP-10)</h1>

<h2>MAP-3 — Hover connection highlight</h2>
<p>Hovering over a card brightens its connected arrows (light blue) and dims all others.
Essential when the project has more than ~10 scenes.</p>

<h2>MAP-4 — Right-click context menu</h2>
<p>Right-click on a card to open a context menu:</p>
<table>
  <tr><th>Action</th><th>Effect</th></tr>
  <tr><td>Open scene</td><td>Same as double-click — opens the scene in the Level tab</td></tr>
  <tr><td>Rename…</td><td>Text input dialog — renames the scene on the canvas and in data</td></tr>
  <tr><td>Duplicate</td><td>Deep copy of the scene (new UUID, label " (copy)"), appended to the list</td></tr>
  <tr><td>Set as start scene</td><td>Sets this scene as the game entry point</td></tr>
  <tr><td>Delete scene…</td><td>Deletion with confirmation — irreversible</td></tr>
</table>

<h2>MAP-5 — Improved START indicator</h2>
<p>The start scene is distinguished by:</p>
<ul>
  <li>A <b>green stripe</b> at the top of the card.</li>
  <li>A <b>"▶ START" pill badge</b> in the bottom-right corner.</li>
  <li>The existing green border.</li>
</ul>

<h2>MAP-6 — Arrow info strip</h2>
<p>Clicking a transition arrow shows an info strip at the bottom of the view:</p>
<pre>Source  →  Destination   [condition]</pre>
<p>The transition type (<code>goto_scene</code> or <code>⤳ Warp</code>) is shown.
Click ✕ or anywhere else to dismiss it.</p>
<p><b>Tip:</b> the arrow click area is widened to 12 px for easier selection.</p>

<h2>MAP-7 — Genre filter</h2>
<p>The <b>Filter</b> combo in the toolbar lists all profiles present in the project.
Selecting a profile hides other scenes (and their arrows).
"All profiles" restores the full view.</p>

<h2>MAP-8 — Export PNG</h2>
<p>The <b>Export PNG</b> toolbar button opens a save dialog and exports the full
Scene Map as a PNG image with the correct dark background.</p>

<h2>MAP-10 — Entity count badge</h2>
<p>A <code>⬡ N</code> badge in the bottom-right of the text area shows how many entities
are placed in the scene. Hidden when N=0.</p>
"""


def _fr_scene_map_map12() -> str:
    return """
<h1>Scene Map — Miniatures &amp; Badges de statut (MAP-1/2)</h1>

<p>L'onglet <b>Scene Map</b> affiche toutes les scènes du projet sous forme de cartes draggables
reliées par des flèches (transitions <code>goto_scene</code> / <code>warp_to</code>).
Deux améliorations ont été ajoutées : miniature tilemap (MAP-1) et badge de statut coloré (MAP-2).</p>

<h2>MAP-1 — Miniature tilemap</h2>
<p>La première tilemap assignée à chaque scène est chargée et affichée dans la zone droite de la carte
(50×38 px, chargement paresseux au premier affichage). Le fond reste sombre si aucune tilemap
n'est encore assignée.</p>
<ul>
  <li>Source : <code>scene["tilemaps"][0]["path"]</code> — chemin relatif au projet.</li>
  <li>Aucun thread dédié : chargement au premier <code>paint()</code>, mis en cache ensuite.</li>
  <li>Largeur de carte portée à 192 px (était 168) pour accueillir la miniature.</li>
</ul>

<h2>MAP-2 — Badge de statut</h2>
<p>Un point coloré en haut-droite de chaque carte résume l'état de la scène :</p>
<table>
  <tr><th>Couleur</th><th>Signification</th></tr>
  <tr><td><span style="color:#4caf70">●</span> Vert</td><td>Tilemap assignée + entité joueur placée (ou profil sans joueur)</td></tr>
  <tr><td><span style="color:#e0a020">●</span> Orange</td><td>Tilemap présente mais aucune entité joueur placée</td></tr>
  <tr><td><span style="color:#555566">●</span> Gris</td><td>Aucune tilemap assignée — scène vide</td></tr>
</table>
<p>Profils exemptés du check joueur (toujours vert si tilemap présente) :
<code>menu</code>, <code>visual_novel</code>, <code>puzzle</code>, <code>race</code>.</p>
<p>La détection joueur repose sur <code>sprites[].gameplay_role == "player"</code> et la présence
d'une entité de ce type dans <code>entities[]</code>.</p>
"""


def _en_scene_map_map12() -> str:
    return """
<h1>Scene Map — Thumbnails &amp; Status Badges (MAP-1/2)</h1>

<p>The <b>Scene Map</b> tab displays all project scenes as draggable cards connected by arrows
(<code>goto_scene</code> / <code>warp_to</code> transitions).
Two improvements were added: tilemap thumbnail (MAP-1) and colored status badge (MAP-2).</p>

<h2>MAP-1 — Tilemap thumbnail</h2>
<p>The first tilemap assigned to a scene is loaded and displayed in the right area of its card
(50×38 px, lazy-loaded on first paint). The area stays dark if no tilemap has been assigned yet.</p>
<ul>
  <li>Source: <code>scene["tilemaps"][0]["path"]</code> — path relative to the project.</li>
  <li>No dedicated thread: loaded on the first <code>paint()</code> call, cached thereafter.</li>
  <li>Card width increased to 192 px (was 168) to fit the thumbnail.</li>
</ul>

<h2>MAP-2 — Status badge</h2>
<p>A colored dot in the top-right corner of each card summarises the scene state:</p>
<table>
  <tr><th>Color</th><th>Meaning</th></tr>
  <tr><td><span style="color:#4caf70">●</span> Green</td><td>Tilemap assigned + player entity placed (or profile needs no player)</td></tr>
  <tr><td><span style="color:#e0a020">●</span> Orange</td><td>Tilemap present but no player entity placed</td></tr>
  <tr><td><span style="color:#555566">●</span> Gray</td><td>No tilemap assigned — empty scene</td></tr>
</table>
<p>Profiles exempt from the player check (always green when tilemap present):
<code>menu</code>, <code>visual_novel</code>, <code>puzzle</code>, <code>race</code>.</p>
<p>Player detection uses <code>sprites[].gameplay_role == "player"</code> cross-referenced with
entities placed in <code>entities[]</code>.</p>
"""


def _fr_dialogue_preview() -> str:
    return """
<h1>Aperçu Dialogue — Police bitmap &amp; plein écran (DLG-1/2/3)</h1>

<p>Trois améliorations ont été apportées à l'onglet <b>Dialogues</b> pour rendre l'aperçu fidèle
au rendu NGPC réel : police bitmap custom (DLG-1), mode plein écran (DLG-2), compteur de tiles
par ligne (DLG-3).</p>

<h2>DLG-1 — Police bitmap custom</h2>
<p>Si la scène utilise une <b>police custom</b> (<code>custom_font_png</code> dans les données projet),
l'aperçu charge chaque glyphe (ASCII 32–127) depuis l'image PNG et les affiche en tiles 8×8,
exactement comme le hardware le ferait.</p>
<table>
  <tr><th>Paramètre</th><th>Valeur attendue</th></tr>
  <tr><td><code>custom_font_png</code></td><td>Chemin vers le PNG de police (128×48 ou 256×24)</td></tr>
  <tr><td><code>font_format</code></td><td><code>"8x8"</code> (défaut) — 16 glyphes/ligne × 6 lignes</td></tr>
  <tr><td>Couleur encre</td><td>Pixels avec R&lt;64, G&lt;64, B&lt;64 = encre → rendu blanc puis colorisé</td></tr>
  <tr><td>Colorisation</td><td>QPainter <code>SourceIn</code> avec la couleur de palette active</td></tr>
</table>
<p>Si aucune police custom n'est définie, l'aperçu utilise la police système Courier comme avant.</p>

<h2>DLG-2 — Mode plein écran (160×152)</h2>
<p>La case à cocher <b>Plein écran</b> agrandit le widget d'aperçu de 160×40 à 160×152 (facteur 3×).
La zone sombre au-dessus représente le gameplay visible pendant le dialogue.</p>
<ul>
  <li>La boîte de dialogue reste en bas (offset <code>by = fh - bh</code>).</li>
  <li>La zone gameplay est affichée avec un fond foncé uniforme (simulation).</li>
  <li>Le mode est mémorisé par scène (clé <code>dlg_preview_fullscreen</code>).</li>
</ul>

<h2>DLG-3 — Compteur de tiles par ligne</h2>
<p>Le champ <b>Texte</b> affiche en temps réel le nombre de tiles utilisés sur chaque ligne,
avec un avertissement si une ligne dépasse la largeur de la boîte.</p>
<table>
  <tr><th>Format</th><th>Exemple</th></tr>
  <tr><td>Normal</td><td><code>L1:12/18  L2:8/18</code></td></tr>
  <tr><td>Dépassement</td><td><code>L1:20/18 ⚠  L2:8/18</code></td></tr>
</table>
<p>La largeur max est <b>18 colonnes</b> sans portrait, <b>15 colonnes</b> avec portrait actif.
Le calcul tient compte du word-wrap — il ne coupe pas les mots.</p>

<h2>Police custom — format PNG</h2>
<p>Préparez votre police dans un éditeur d'images (Aseprite, GIMP, etc.) :</p>
<ul>
  <li>Format <code>128×48</code> : 16 glyphes par ligne, 6 lignes (ASCII 32–127 dans l'ordre).</li>
  <li>Chaque glyphe = 8×8 pixels. Pixels sombres (R,G,B &lt; 64) = encre.</li>
  <li>Pixels clairs = transparent (background).</li>
  <li>Sauvegardez le chemin dans <code>custom_font_png</code> via l'onglet Police/Projet.</li>
</ul>
"""


def _en_dialogue_preview() -> str:
    return """
<h1>Dialogue Preview — Bitmap Font &amp; Fullscreen (DLG-1/2/3)</h1>

<p>Three improvements were added to the <b>Dialogues</b> tab to make the preview match the actual
NGPC hardware output: custom bitmap font (DLG-1), fullscreen mode (DLG-2), per-line tile counter (DLG-3).</p>

<h2>DLG-1 — Custom bitmap font</h2>
<p>If the scene uses a <b>custom font</b> (<code>custom_font_png</code> in the project data),
the preview loads each glyph (ASCII 32–127) from the PNG and renders them as 8×8 tiles,
exactly as the hardware would.</p>
<table>
  <tr><th>Parameter</th><th>Expected value</th></tr>
  <tr><td><code>custom_font_png</code></td><td>Path to the font PNG (128×48 or 256×24)</td></tr>
  <tr><td><code>font_format</code></td><td><code>"8x8"</code> (default) — 16 glyphs/row × 6 rows</td></tr>
  <tr><td>Ink color</td><td>Pixels with R&lt;64, G&lt;64, B&lt;64 = ink → rendered white then tinted</td></tr>
  <tr><td>Colorization</td><td>QPainter <code>SourceIn</code> with the active palette color</td></tr>
</table>
<p>If no custom font is defined, the preview falls back to the system Courier font as before.</p>

<h2>DLG-2 — Fullscreen mode (160×152)</h2>
<p>The <b>Fullscreen</b> checkbox expands the preview widget from 160×40 to 160×152 (3× scale).
The dark area above represents the visible gameplay during dialogue.</p>
<ul>
  <li>The dialogue box stays at the bottom (offset <code>by = fh - bh</code>).</li>
  <li>The gameplay area is shown as a uniform dark background (simulation).</li>
  <li>The mode is saved per scene (key <code>dlg_preview_fullscreen</code>).</li>
</ul>

<h2>DLG-3 — Per-line tile counter</h2>
<p>The <b>Text</b> field shows in real time how many tiles are used on each line,
with a warning if a line exceeds the box width.</p>
<table>
  <tr><th>Format</th><th>Example</th></tr>
  <tr><td>Normal</td><td><code>L1:12/18  L2:8/18</code></td></tr>
  <tr><td>Overflow</td><td><code>L1:20/18 ⚠  L2:8/18</code></td></tr>
</table>
<p>Max width is <b>18 columns</b> without portrait, <b>15 columns</b> with portrait active.
The count respects word-wrap — words are never split mid-character.</p>

<h2>Custom font — PNG format</h2>
<p>Prepare your font in an image editor (Aseprite, GIMP, etc.):</p>
<ul>
  <li>Format <code>128×48</code>: 16 glyphs per row, 6 rows (ASCII 32–127 in order).</li>
  <li>Each glyph = 8×8 pixels. Dark pixels (R,G,B &lt; 64) = ink.</li>
  <li>Light pixels = transparent (background).</li>
  <li>Save the path to <code>custom_font_png</code> via the Font/Project tab.</li>
</ul>
"""


# ---------------------------------------------------------------------------
# Topic dispatch
# ---------------------------------------------------------------------------

_FR_TOPICS = [
    _fr_welcome,
    _fr_constraints,
    _fr_palette_editor,
    _fr_rgb444,
    _fr_layers,
    _fr_remap,
    _fr_project,
    _fr_globals,
    _fr_vram,
    _fr_bundle,
    _fr_tilemap,
    _fr_pipeline,
    _fr_editor,
    _fr_mono,
    _fr_hitbox,
    _fr_level_editor,
    _fr_triggers,
    _fr_dialogues,
    _fr_scene_map,
    _fr_project_templates,
    _fr_physics_ai_runtime_v2,
    _fr_topdown_vs_platform,
    _fr_palette_bank,
    _fr_procgen,
    _fr_troubleshoot,
]

_EN_TOPICS = [
    _en_welcome,
    _en_constraints,
    _en_palette_editor,
    _en_rgb444,
    _en_layers,
    _en_remap,
    _en_project,
    _en_globals,
    _en_vram,
    _en_bundle,
    _en_tilemap,
    _en_pipeline,
    _en_editor,
    _en_mono,
    _en_hitbox,
    _en_level_editor,
    _en_triggers,
    _en_dialogues,
    _en_scene_map,
    _en_project_templates,
    _en_physics_ai_runtime_v2,
    _en_topdown_vs_platform,
    _en_palette_bank,
    _en_procgen,
    _en_troubleshoot,
]


def _get_html(lang: str, index: int) -> str:
    topics = _EN_TOPICS if lang == "en" else _FR_TOPICS
    if 0 <= index < len(topics):
        return topics[index]()
    return "<p>—</p>"


def _topic_labels(lang: str) -> list[str]:
    return _TOPICS_EN if lang == "en" else _TOPICS_FR


# ---------------------------------------------------------------------------
# HelpTab widget
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bug report dialog
# ---------------------------------------------------------------------------

class _BugReportDialog(QDialog):
    """Collect bug info and open a pre-filled GitHub issue in the browser."""

    _GITHUB_NEW_ISSUE = "https://github.com/Tixul/Ngpcraft_Engine/issues/new"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report a bug")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._title = QLineEdit()
        self._title.setPlaceholderText("Short description of the problem")
        form.addRow("Title:", self._title)

        self._desc = QTextEdit()
        self._desc.setPlaceholderText("What happened? What did you expect?")
        self._desc.setMinimumHeight(80)
        form.addRow("Description:", self._desc)

        self._steps = QTextEdit()
        self._steps.setPlaceholderText("1. Open project\n2. Click Export\n3. …")
        self._steps.setMinimumHeight(60)
        form.addRow("Steps to reproduce:", self._steps)

        lay.addLayout(form)

        self._cb_sysinfo = QCheckBox("Include system info  (OS, app version, Python)")
        self._cb_sysinfo.setChecked(True)
        lay.addWidget(self._cb_sysinfo)

        hint = QLabel(
            "A browser tab will open with the form pre-filled. "
            "You can review and edit before submitting."
        )
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        btns = QDialogButtonBox()
        self._open_btn = btns.addButton(
            "Open GitHub Issues", QDialogButtonBox.ButtonRole.AcceptRole
        )
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._open_issue)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _build_body(self) -> str:
        desc  = self._desc.toPlainText().strip()
        steps = self._steps.toPlainText().strip()
        lines: list[str] = []

        if desc:
            lines += ["## Description", desc, ""]
        if steps:
            lines += ["## Steps to reproduce", steps, ""]

        if self._cb_sysinfo.isChecked():
            try:
                from core.version import APP_VERSION
                ver = APP_VERSION
            except Exception:
                ver = "unknown"
            lines += [
                "## Environment",
                f"- NgpCraft Engine: v{ver}",
                f"- OS: {platform.system()} {platform.version()}",
                f"- Python: {sys.version.split()[0]}",
                "",
            ]

        return "\n".join(lines).strip()

    def _open_issue(self) -> None:
        title = self._title.text().strip()
        if not title:
            QMessageBox.warning(self, "Report a bug", "Please enter a title.")
            return
        body  = self._build_body()
        params = urllib.parse.urlencode({
            "title": title,
            "body":  body,
            "labels": "bug",
        })
        url = QUrl(f"{self._GITHUB_NEW_ISSUE}?{params}")
        QDesktopServices.openUrl(url)
        self.accept()


# ---------------------------------------------------------------------------
# Template updater worker (runs in a background thread)
# ---------------------------------------------------------------------------

class _UpdateWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def run(self) -> None:
        try:
            from core.template_updater import fetch_and_sync
            result = fetch_and_sync(on_progress=self.progress.emit)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# App update checker worker
# ---------------------------------------------------------------------------

class _AppCheckWorker(QThread):
    """Background thread: check GitHub releases for a newer app version."""

    result = pyqtSignal(str)   # emits latest version string, or "" if unreachable / up-to-date
    error  = pyqtSignal(str)

    def run(self) -> None:
        try:
            from core.app_updater import check_latest_release, is_newer
            from core.version import APP_VERSION, APP_GITHUB_REPO
            latest = check_latest_release(APP_GITHUB_REPO)
            if latest and is_newer(APP_VERSION, latest):
                self.result.emit(latest)
            else:
                self.result.emit("")
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# HelpTab
# ---------------------------------------------------------------------------

class HelpTab(QWidget):
    """
    Two-panel help tab (Sound Creator style):
      Left  : QListWidget (220 px) — topic list
      Right : QTextBrowser — HTML content with dark CSS
      Bottom: Update Template button · FR / EN toggle buttons
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lang = current_language()
        self._build_ui()
        self._topic_list.setCurrentRow(0)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — topic list
        self._topic_list = QListWidget()
        self._topic_list.setStyleSheet(_LIST_CSS)
        self._topic_list.setFixedWidth(220)
        self._topic_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label in _topic_labels(self._lang):
            self._topic_list.addItem(label)
        self._topic_list.currentRowChanged.connect(self._load_topic)
        splitter.addWidget(self._topic_list)

        # Right — browser
        self._browser = QTextBrowser()
        self._browser.setStyleSheet(_BROWSER_CSS)
        self._browser.setOpenExternalLinks(False)
        splitter.addWidget(self._browser)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        # Bottom bar — Update Template button (left) + language buttons (right)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(8, 4, 8, 4)

        self._update_btn = QPushButton("↓ Update Template")
        self._update_btn.setToolTip(
            "Download the latest NgpCraft_base_template from GitHub\n"
            "and sync the embedded copy inside this tool."
        )
        self._update_btn.setStyleSheet(
            "QPushButton { padding: 2px 10px; border-radius: 4px; }"
            "QPushButton:disabled { color: #666; }"
        )
        self._update_btn.clicked.connect(self._on_update_template)
        btn_row.addWidget(self._update_btn)

        self._update_status = QLabel("")
        self._update_status.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        btn_row.addWidget(self._update_status)

        # Separator
        _sep = QLabel("|")
        _sep.setStyleSheet("color: #444; padding: 0 4px;")
        btn_row.addWidget(_sep)

        self._app_check_btn = QPushButton("⬆ Check for app update")
        self._app_check_btn.setToolTip(
            "Check GitHub for a newer version of NgpCraft Engine."
        )
        self._app_check_btn.setStyleSheet(
            "QPushButton { padding: 2px 10px; border-radius: 4px; }"
            "QPushButton:disabled { color: #666; }"
        )
        self._app_check_btn.clicked.connect(self._on_check_app_update)
        btn_row.addWidget(self._app_check_btn)

        self._app_update_status = QLabel("")
        self._app_update_status.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        btn_row.addWidget(self._app_update_status)

        # Separator
        _sep2 = QLabel("|")
        _sep2.setStyleSheet("color: #444; padding: 0 4px;")
        btn_row.addWidget(_sep2)

        self._bug_report_btn = QPushButton("🐛 Report a bug")
        self._bug_report_btn.setToolTip(
            "Open a pre-filled GitHub issue to report a bug."
        )
        self._bug_report_btn.setStyleSheet(
            "QPushButton { padding: 2px 10px; border-radius: 4px; }"
        )
        self._bug_report_btn.clicked.connect(self._on_report_bug)
        btn_row.addWidget(self._bug_report_btn)

        btn_row.addStretch()
        self._btn_fr = QPushButton("Français")
        self._btn_en = QPushButton("English")
        self._btn_fr.setCheckable(True)
        self._btn_en.setCheckable(True)
        self._btn_fr.clicked.connect(lambda: self._switch_lang("fr"))
        self._btn_en.clicked.connect(lambda: self._switch_lang("en"))
        btn_row.addWidget(self._btn_fr)
        btn_row.addWidget(self._btn_en)
        root.addLayout(btn_row)

        self._update_lang_buttons()
        self._worker: _UpdateWorker | None = None
        self._app_check_worker: _AppCheckWorker | None = None

    # ------------------------------------------------------------------
    # Template updater
    # ------------------------------------------------------------------

    def _on_update_template(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        confirm = QMessageBox.question(
            self,
            "Update Template",
            "Download the latest NgpCraft_base_template from GitHub\n"
            "and update the embedded copy inside this tool?\n\n"
            "Requires an internet connection.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Ok:
            return

        self._update_btn.setEnabled(False)
        self._update_status.setText("Connecting…")

        self._worker = _UpdateWorker(self)
        self._worker.progress.connect(self._update_status.setText)
        self._worker.finished.connect(self._on_update_finished)
        self._worker.error.connect(self._on_update_error)
        self._worker.start()

    def _on_update_finished(self, result: dict) -> None:
        self._update_btn.setEnabled(True)
        added   = result.get("added",   0)
        updated = result.get("updated", 0)
        removed = result.get("removed", 0)
        if added == updated == removed == 0:
            self._update_status.setText("Already up to date.")
        else:
            self._update_status.setText(
                f"+{added}  ~{updated}  -{removed}"
            )
        QMessageBox.information(
            self,
            "Update Template",
            f"Template updated successfully.\n\n"
            f"  Added  : {added}\n"
            f"  Updated: {updated}\n"
            f"  Removed: {removed}",
        )

    def _on_update_error(self, msg: str) -> None:
        self._update_btn.setEnabled(True)
        self._update_status.setText("Update failed.")
        QMessageBox.warning(self, "Update Template — Error", msg)

    # ------------------------------------------------------------------
    # App update checker
    # ------------------------------------------------------------------

    def start_silent_update_check(self) -> None:
        """Start a background update check without user interaction.

        If a newer version is found, the status label is updated.
        Called by MainWindow on startup after a short delay.
        """
        if self._app_check_worker is not None and self._app_check_worker.isRunning():
            return
        self._app_check_worker = _AppCheckWorker(self)
        self._app_check_worker.result.connect(self._on_app_check_done_silent)
        self._app_check_worker.error.connect(lambda _: None)   # silent — ignore errors
        self._app_check_worker.start()

    def _on_check_app_update(self) -> None:
        """Manual check triggered by the button."""
        if self._app_check_worker is not None and self._app_check_worker.isRunning():
            return
        self._app_check_btn.setEnabled(False)
        self._app_update_status.setText("Checking…")
        self._app_check_worker = _AppCheckWorker(self)
        self._app_check_worker.result.connect(self._on_app_check_done)
        self._app_check_worker.error.connect(self._on_app_check_error)
        self._app_check_worker.start()

    def _on_app_check_done(self, latest: str) -> None:
        self._app_check_btn.setEnabled(True)
        if not latest:
            from core.version import APP_VERSION
            self._app_update_status.setText("Up to date.")
            QMessageBox.information(
                self,
                "NgpCraft Engine — Update",
                f"You are running the latest version ({APP_VERSION}).",
            )
            return

        from core.version import APP_VERSION, APP_GITHUB_REPO
        self._app_update_status.setText(f"● v{latest} available")
        self._app_update_status.setStyleSheet("color: #ffcc44; font-size: 11px; font-weight: bold;")
        reply = QMessageBox.question(
            self,
            "NgpCraft Engine — Update available",
            f"Version {latest} is available (you have {APP_VERSION}).\n\n"
            f"Open the releases page on GitHub?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(
                QUrl(f"https://github.com/{APP_GITHUB_REPO}/releases/latest")
            )

    def _on_app_check_done_silent(self, latest: str) -> None:
        """Result handler for the silent startup check — no dialog."""
        if not latest:
            return
        self._app_update_status.setText(f"● v{latest} available")
        self._app_update_status.setStyleSheet("color: #ffcc44; font-size: 11px; font-weight: bold;")
        self._app_check_btn.setToolTip(
            f"Version {latest} is available — click to open GitHub releases."
        )
        # Re-wire button to open the releases page directly
        try:
            self._app_check_btn.clicked.disconnect()
        except RuntimeError:
            pass
        from core.version import APP_GITHUB_REPO
        self._app_check_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl(f"https://github.com/{APP_GITHUB_REPO}/releases/latest")
            )
        )
        self._app_check_btn.setText(f"⬆ v{latest} available")

    def _on_app_check_error(self, msg: str) -> None:
        self._app_check_btn.setEnabled(True)
        self._app_update_status.setText("Check failed.")

    # ------------------------------------------------------------------
    def _load_topic(self, index: int) -> None:
        html = _get_html(self._lang, index)
        self._browser.setHtml(html)

    def _switch_lang(self, lang: str) -> None:
        self._lang = lang
        set_language(lang)
        save_to_settings(lang)
        current_row = self._topic_list.currentRow()
        # Rebuild topic list labels
        self._topic_list.blockSignals(True)
        self._topic_list.clear()
        for label in _topic_labels(lang):
            self._topic_list.addItem(label)
        self._topic_list.setCurrentRow(current_row)
        self._topic_list.blockSignals(False)
        self._load_topic(current_row)
        self._update_lang_buttons()

    def _update_lang_buttons(self) -> None:
        self._btn_fr.setChecked(self._lang == "fr")
        self._btn_en.setChecked(self._lang == "en")

    def retranslate(self) -> None:
        """Call after a global language change to refresh content."""
        self._switch_lang(current_language())

    # ------------------------------------------------------------------
    # Bug reporter
    # ------------------------------------------------------------------

    def _on_report_bug(self) -> None:
        dlg = _BugReportDialog(self)
        dlg.exec()
