# v5-z6-g1 — même recette que v5-z6 (2 projets + 6 zones, `--zone-aug 6`), graine 1

Même dataset que `v5-z6` (61 739 exemples), `train.py --epochs 30 --bs 64 --lr 3e-4 --seed 1` ; meilleure époque 22.
Entraîné, comme `v4-w128-k32-g1`, pour séparer l'effet des zones du bruit d'entraînement.

## Résultats
Validation : P 97,0 % / R 96,0 % / F1 **0,965** ; cul-de-sac 71,1 % ; carrefours **82,6 %** ; **3,34°** — meilleurs
chiffres isolés de toutes les campagnes, mais à ±0,3 point des autres, donc pas significatif.

Suivi réel, tolérance 3 px :

| zone | couverture | précision | carrefours | écart médian | trop | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 96,3 % | **82,7 %** (v5-z6 : 58,9 ; v4 : 94,2 / 63,0) | 13/15 | **1,1 px** | 270 px | 11 faible confiance, 7 hors zone, 2 jonctions |
| ho2 | **98,6 %** | **63,3 %** | 15/20 | 2,7 px | 1 230 px | 10 faible confiance, 14 hors zone, 10 jonctions |

Sur les six zones corrigées (dans l'entraînement — mesure l'apprentissage, pas la généralisation) :

| zone (id) | marge 10 px | marge 30 px |
|---|---|---|
| 1 | **6/6**, couv. 88 % | 6/6, 100 % |
| 2 | 0/1, 57 % | 1/1, 81 % |
| 3 | 0/1, 52 % | 1/1, 100 % |
| 4 | 0/1, 57 % | 1/1, 100 % |
| 5 | 0/2, 39 % | 2/2, 100 % |
| 6 | **7/8**, 79 % | **8/8**, 96 % |

## Lecture
- Même constat que v5-z6 : les zones sont apprises (toutes retrouvées avec 30 px de marge, les deux grosses dès 10 px),
  les holdouts ne bougent pas au-delà du bruit de graine. Cette graine est simplement la plus équilibrée des quatre v5
  sur les holdouts (ho1 83 % / 1,1 px, ho2 98,6 % / 15/20), sans la rechute de précision de la graine 0.
- Les deux carrefours du nœud dense de ho1 (4431,3340 et 4461,3308) restent manqués, comme par toutes les graines 0 ;
  ce sont des fusions de branches du traceur, les zones corrigées (toutes au sud) ne les concernent pas.
- L'affinage depuis v4-w128-k32 (`v5-ft`, non livré : 10 époques à lr 1e-4 avec `--init`, 5 min) garde la précision
  ho1 de v4 (85,6 %) et apprend aussi les zones (6/6, 5/8 à 10 px ; toutes à 30 px), mais tombe à 11/20 carrefours en
  ho2. Cinq fois moins cher qu'un entraînement complet : c'est la voie à retenir quand les zones s'accumuleront, à
  condition de surveiller ho2.

## Usage
Modèle v5 à essayer dans l'app pour la prochaine série de zones (il contient les corrections ; ses erreurs sont donc
différentes de celles de v4). Le défaut de l'app reste `v4-w128-k32` tant qu'aucune v5 n'améliore les holdouts.
Proposition à valider, pas un traceur autonome.
