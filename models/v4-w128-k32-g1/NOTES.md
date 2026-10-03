# v4-w128-k32-g1 — même recette que v4-w128-k32, autre graine aléatoire

Rien ne change par rapport à `v4-w128-k32` (deux projets, fenêtre 128, 32 secteurs, pas 2, visée 6, 30 époques) sauf la
graine (`--seed 1` : initialisation de la tête, ordre des lots, augmentations). Entraîné pour répondre à une question
préalable à toutes les autres : **quelle part des écarts entre variantes est du simple bruit d'entraînement ?**

## Résultats
Validation : P 97,0 % / R 95,7 % / F1 0,963 ; cul-de-sac 73,3 % ; carrefours 79,7 % ; 3,41° (meilleure époque 27).
Identique à la graine 0 à ±0,5 point.

Suivi réel (tolérance 3 px) :

| zone | couverture | précision | carrefours | écart médian | départs | arrêts |
|---|---|---|---|---|---|---|
| ho1 | **98,2 %** | 63,0 % (graine 0 : 94,2 %) | **15/15** (graine 0 : 13) | **1,2 px** | 1 | 11 faible confiance, 12 hors zone, 3 jonctions |
| ho2 | 96,8 % | 58,1 % | 14/20 (graine 0 : 15) | 3,2 px | 1 | 5 faible confiance, 17 hors zone, 9 jonctions |

## Lecture
- Sur exemples isolés les deux graines sont indiscernables. En suivi réel, **la précision en ho1 passe de 94 à 63 %** :
  cette graine suit la bande sombre de la ligne de Sceaux et l'avenue du parc Montsouris (≈ 820 px de trop), la graine 0
  s'y arrête. Même phénomène que k64 / w96 / w192 : ce n'est donc pas la fenêtre ni le nombre de secteurs qui fait ces
  30 points d'écart, c'est une ou deux décisions de poursuite que n'importe quel réentraînement peut faire basculer.
- En revanche elle retrouve les **15 carrefours** de ho1, dont les deux du nœud dense (4431,3340 et 4461,3308) que toutes
  les autres variantes à 32 secteurs manquent, posés à 1,2 px. Là aussi : graine, pas recette.
- Ce qui est stable d'une graine à l'autre : couverture 97–98 %, carrefours 13–15/15 et 14–15/20 à 1–3 px, précision
  ho2 ≈ 60 % (plafond de l'annotation). Ce qui ne l'est pas : la précision en ho1 et le nombre de branches ouvertes.
- Conséquence pour toute la campagne : comparer deux variantes sur une seule graine ne permet pas de conclure à ±30
  points de précision ni à ±2 carrefours. Il faudrait 3 graines par variante (≈ 35 min de GPU par variante) ou, mieux,
  moyenner les sorties de plusieurs graines à l'inférence (ensemble), ce qui lisserait aussi ces décisions limites.

## Usage
Alternative légitime à `v4-w128-k32` : plus de carrefours, plus de propositions à refuser. À essayer dans l'app sur une
zone où `v4-w128-k32` s'arrête trop tôt.
