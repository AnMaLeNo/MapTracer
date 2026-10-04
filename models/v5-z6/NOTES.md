# v5-z6 — recette v4-w128-k32 + les 6 zones corrigées du mode Auto (`--zone-aug 6`)

Premier modèle entraîné avec des **exemples difficiles** : les deux gros projets (`nexus_alkhemia_2011`,
`nexus_alkhemia_2011-0202`) **plus** `data/zones/nexus_alkhemia_2011_sud_v4-w128-k32_2026-10-04.mapzones.json` — six
zones (≈ 950 px de galeries, 18 carrefours) annotées à la main là où `v4-w128-k32` se trompait, après un tracé Auto
lancé depuis (4262, 5426). Le tracé complet du modèle et sa provenance sont dans le fichier ; le rapport zone par zone
(« ce que le modèle avait fait / ce qui a été corrigé ») s'obtient avec `tools/zones_report.py`.

## Entraînement
- `oracle.py <01> <0202> <zones> --step 2 --lookahead 6 --near 6 --window 128 --sectors 32 --zone-aug 6
  --holdout 4200,3200,5800,3600 --holdout 3000,2500,4100,2900` → 61 739 exemples (52 136 / 9 603 — la validation est
  la même que v4), 178 fins, 5 448 états multi-directions. Les zones apportent 5 600 exemples (≈ 11 % du train) :
  chaque état y est tiré 6 fois (décalages / rotations différents), contre 1 fois dans les projets.
- `train.py --epochs 30 --bs 64 --lr 3e-4` (RTX 3080, 21 s/époque) ; meilleure époque 19.

## Résultats
Validation (identique à v4) : P 97,2 % / R 95,6 % / F1 0,964 ; cul-de-sac 75,6 % ; carrefours 79,0 % ; 3,40°.
Indiscernable de v4-w128-k32 (0,962) — attendu, les zones ne sont pas dans la validation.

Suivi réel sur les holdouts (jamais vus), tolérance 3 px :

| zone | couverture | précision | carrefours | écart médian | trop | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 97,2 % | 58,9 % (v4 : 94,2 / g1 : 63,0) | 13/15 | 2,0 px | 944 px | 8 faible confiance, 10 hors zone, 4 jonctions |
| ho2 | 98,2 % | 59,9 % | **16/20** (v4 : 15) | 2,3 px | 1 413 px | 8 faible confiance, 14 hors zone, 10 jonctions |

Suivi relancé **sur les six zones corrigées** (`trace.py --zone i --seed auto`, référence = l'annotation de la zone ;
ces zones sont dans l'entraînement, donc ce chiffre mesure l'apprentissage de l'exemple, pas la généralisation) :

| zone (id) | v4-w128-k32 | v4 g1 | **v5-z6** | v5-z6 marge 30 px |
|---|---|---|---|---|
| 1 (nœud 6 carrefours) | 0/6, couv. 5 % | 4/6, 82 % | **6/6, 90 %** | 6/6, 100 % |
| 2 (croix) | 0/1, 57 % | 0/1 | 0/1, 57 % | 1/1, 81 % |
| 3 (croix) | 0/1, 52 % | 0/1 | 0/1, 52 % | 1/1, 100 % |
| 4 | 0/1, 57 % | 0/1 | **1/1, 77 %** | 1/1, 100 % |
| 5 | 0/2, 26 % | 0/2 | **2/2, 100 %** | 2/2, 100 % |
| 6 (8 carrefours) | 1/8, 41 % | 0/8 | **7/8, 92 %** | 7/8, 91 % |

(Carrefours = ceux que `trace.py` compte dans le graphe de la zone découpé ; marge 10 px par défaut, donc le traceur
s'arrête « hors zone » très vite dans ces zones de 60–120 px.)

## Lecture
- **Le mécanisme fonctionne** : les quatre zones où v4 ne voyait rien (1, 4, 5, 6) sont maintenant suivies avec leurs
  carrefours. Les zones 2 et 3 (petites croix) ne sont retrouvées qu'avec une marge de 30 px : parti du bout d'une
  branche, le traceur sort de la zone de 60 px avant d'avoir confirmé la branche latérale (`--confirm 2`) — artefact de
  l'évaluation sur une zone minuscule, pas forcément du modèle.
- **Sur les holdouts, rien de mesurable** : 13/15 et 16/20 carrefours, couverture 97–98 %, et une précision ho1 de 59 %
  qui est dans la fourchette du bruit de graine de v4 (63–94 %). Six zones (≈ 950 px contre 22 500 px de graphe) sont
  trop peu pour déplacer la généralisation ; elles corrigent ce qu'elles couvrent. C'est le résultat attendu d'une
  première itération — l'intérêt viendra du cumul de zones, posées à des endroits différents de la carte.
- `--zone-aug 20` (v5-z20, non livré : 72 981 exemples) donne la même chose : 6/6, 0/1, 0/1, 0/1, 0/2, 8/8 sur les zones,
  14/15 et 14/20 sur les holdouts. Au-delà de 6 répétitions, les zones sont apprises ; en rajouter ne change rien.

## Usage
Référence de la recette v5 (graine 0). Pour l'app, préférer `v5-z6-g1` (même recette, autre graine, meilleurs holdouts).
Outil de proposition à valider, pas un traceur autonome.
