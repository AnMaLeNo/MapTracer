# v6-ft — affinage de `v5-z6-g1` sur le dataset v6 (2 projets + 14 zones), 10 époques

Dataset `v6` : les deux gros projets + les trois lots de `data/zones/` (sud v4 : 6 zones, sud2 v5 : 7 zones, nord-est v5 :
1 zone utile + 1 zone d'un seul point sans effet), zones répétées `--zone-aug 6` → **88 304 exemples** (train 78 701, dont
≈ 34 % issus des zones ; val 9 603, inchangée). `train.py --epochs 10 --lr 1e-4 --init models/v5-z6-g1/model.pt --seed 0`,
meilleure époque 8, ≈ 5 min sur RTX 3080.

## Résultats
Validation : P 96,9 % / R 96,6 % / F1 **0,968** ; cul-de-sac 71,1 % ; carrefours 85,1 % ; 3,51°. Comme toujours à
±0,3 point des autres modèles : la validation ne contient pas les zones.

Suivi réel (`trace.py --seed auto --reseed 3`, tolérance 3 px), holdouts jamais vus :

| zone | couverture | précision | carrefours (posés) | écart médian | trop | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 97,2 % | **81,8 %** (v5-z6-g1 : 82,7) | **14/15** (16) | 1,8 px | 293 px | 11 faible confiance, 9 hors zone, 2 jonctions |
| ho2 | **98,6 %** | 61,6 % (v5-z6-g1 : 63,3) | **17/20** (41) | 2,1 px | 1 314 px | 11 faible confiance, 15 hors zone, 12 jonctions |

Sur les zones apprises (mesure l'apprentissage, pas la généralisation) :

| lot | v5-z6-g1 | v6-ft |
|---|---|---|
| nord-est (65 carrefours, 2 282 px) | 49 % couv., 18/65 | **90,5 % couv., 56/65** (134 posés), précision 50 % |
| sud2 zone 0 (24 carrefours) | 91 %, 23/24 | 96 %, 23/24 |
| sud2 zone 3 (11) | 71 %, 5/11 | **98 %, 10/11** |
| sud2 zone 4 (9) | 63 %, 3/9 | **98 %, 8/9** |
| sud2 zone 5 (1, 60 px) | 45 %, 0/1 | 0 % (le traceur sort de la zone au premier pas : zone trop petite pour être évaluée) |

## Lecture
- C'est le seul v6 qui **garde la précision de v5-z6-g1 sur ho1** (82 → 82 %) tout en gagnant un carrefour en ho1 et deux
  en ho2 ; les réentraînements complets (`v6-z14`, graines 0 et 1) tombent à 68 % et 57 % en ho1. Un carrefour de plus
  est dans le bruit de graine ; la précision conservée est l'argument.
- Le lot nord-est (secteur Val-de-Grâce : hagues et murs en noir épais, galeries sinueuses entre des taches bleu clair —
  un style graphique absent des deux projets) est appris à 90 %, mais le modèle y pose **134 carrefours pour 65** : le
  dessin y est plein de départs de galeries non annotés, et il est devenu généreux sur les branches. La précision de 50 %
  dans cette zone est plafonnée par l'annotation (un réseau parmi d'autres dessinés), pas seulement par le modèle.
- En ho2 il pose 41 carrefours pour 20 (v5 : 35) : même tendance, plus de fausses branches dans les zones denses.

## Usage
Modèle à utiliser pour la prochaine série de zones Auto : il contient les 14 corrections, ses erreurs sont donc de
nouvelles erreurs. Proposition à valider, jamais un traceur autonome.
