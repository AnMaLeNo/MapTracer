# v4-w192-k32 — fenêtre 192 px (vue plus large)

Identique à v4-w128-k32 avec une fenêtre de **192 px** (96 px de rayon). Question posée (la tienne) : voir plus large
aide-t-il à trouver le point suivant, surtout aux carrefours et dans les zones chargées ?

## Entraînement
- Même dataset régénéré avec `--window 192` (56 118 exemples ; 2,25× plus de pixels par exemple, ~42 s/époque au lieu
  de 22) ; `train.py --epochs 30` ; meilleure époque 18 (F1 0,963, la plus haute de la campagne).

## Résultats
Validation : P 97,1 % / R 95,6 % / F1 **0,963** ; cul-de-sac 68,9 % ; rappel carrefours **79,7 %** ; erreur
angulaire 3,45°.

Suivi réel (tolérance 3 px) :

| zone | couverture | précision | carrefours | écart médian | départs | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 97,4 % | 75,0 % | 12/15 | 1,9 px | 3 (96,3 → 96,8 → 97,4 %) | 9 faible confiance, 10 hors zone, 3 jonctions |
| ho2 | 97,7 % | **68,0 %** (meilleur v4) | 13/20 | 2,6 px | 1 | 7 faible confiance, 12 hors zone, 11 jonctions |

## Lecture
- Le contexte large donne le meilleur rappel de carrefours sur exemples isolés (79,7 %) et la précision la plus haute
  en ho2 (68 % ; trop ≈ 970 px contre 1 360 pour w128) : il part moins dans les transversales hachurées.
- Mais en suivi réel il retrouve **moins** de carrefours que w128 (12/15 et 13/20 contre 13 et 15) : il « voit » le
  carrefour mais l'ouvre moins souvent ; et en ho1 il suit l'avenue du parc Montsouris jusqu'à la maison n° 13
  (galerie réelle non annotée, ≈ 420 px de trop) là où w128 s'arrête.
- Fenêtre 192 = 2,25× plus de calcul par proposition (sur CPU : ~2× plus lent dans l'app) pour un gain nul sur la
  position des carrefours et la direction (3,45°). À pas de 2 px, la décision locale n'a pas besoin de 96 px de rayon.

## Usage
Bon second choix si w128 s'arrête trop tôt dans une zone dense ; pas de gain assez net pour en faire le défaut.
