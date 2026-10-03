# v4-w96-k32 — fenêtre 96 px (vue plus serrée)

Identique à v4-w128-k32 avec une fenêtre de **96 px** (48 px de rayon au lieu de 64). Question posée : le modèle a-t-il
besoin de contexte, ou un voisinage étroit suffit-il (et serait plus rapide : 1,8× moins de pixels) ?

## Entraînement
- Même dataset régénéré avec `--window 96` (56 118 exemples) ; `train.py --epochs 30` (~17 s/époque) ; meilleure époque 26.

## Résultats
Validation : P 97,2 % / R 95,1 % / F1 0,961 ; cul-de-sac 73,3 % ; rappel carrefours 77,2 % ; erreur angulaire 3,49°.
Quasi identiques à w128 sur exemples isolés.

Suivi réel (tolérance 3 px) :

| zone | couverture | précision | carrefours | écart médian | départs | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 97,3 % | 58,2 % | 13/15 | **1,0 px** | 1 | 8 faible confiance, 11 hors zone, 4 jonctions |
| ho2 | 96,9 % | 58,4 % | 14/20 | 1,9 px | **3** (13,8 % → 94 % → 97 %) | 9 faible confiance, 15 hors zone, 11 jonctions |

## Lecture
- Sur exemples isolés, la fenêtre étroite ne perd rien : à 2 px de pas, la décision « où continue le trait » se joue
  dans les 20–30 px autour du point. Les carrefours sont même posés un peu plus précisément (1,0 px).
- En suivi réel, c'est le modèle le moins stable : au premier départ en ho2 il n'a couvert que **13,8 %** de la zone
  (il a suivi l'allée des deux carrefours, est rentré dans son propre tracé et s'est arrêté sans avoir ouvert une seule
  branche latérale) ; il a fallu deux relances pour atteindre 97 %. En ho1 il trace 2 457 px là où l'oracle en trace 1 808 — le
  plus de « trop » de la campagne (≈ 1 020 px), là encore ligne de Sceaux et galeries non annotées.
- Interprétation : avec 48 px de rayon, une salle, un double trait ou une hachure remplit toute la fenêtre et le modèle
  perd la notion de « galerie principale » ; il n'a pas le contexte pour décider si une ouverture latérale est une
  branche ou un décor. Le contexte sert à **ne pas** partir, pas à trouver la direction.

## Usage
Pas recommandé seul ; garde une valeur de comparaison (et de vitesse sur CPU).
