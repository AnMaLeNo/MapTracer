# v6-z14 — réentraînement complet sur le dataset v6 (2 projets + 14 zones), graine 0

Même dataset que `v6-ft` (88 304 exemples, zones ≈ 34 % du train), `train.py --epochs 30 --bs 64 --lr 3e-4 --seed 0`,
meilleure époque 20, ≈ 15 min sur RTX 3080.

## Résultats
Validation : P 97,3 % / R 96,8 % / F1 **0,971** (meilleur de toutes les campagnes, non significatif) ; cul-de-sac 68,9 % ;
carrefours 84,8 % ; 3,39°.

Suivi réel (tolérance 3 px), holdouts jamais vus :

| zone | couverture | précision | carrefours (posés) | écart médian | trop | arrêts |
|---|---|---|---|---|---|---|
| ho1 | **98,0 %** | 68,0 % (v5-z6-g1 : 82,7) | **14/15** (21) | **1,0 px** | 650 px | 9 faible confiance, 11 hors zone, 3 jonctions |
| ho2 | 96,9 % | 56,6 % (v5-z6-g1 : 63,3) | **16/20** (40) | 3,6 px | 1 597 px | 9 faible confiance, 14 hors zone, 19 jonctions |

Zones apprises : nord-est **94,7 % de couverture, 60/65 carrefours** (190 posés, précision 44,5 %) ; sud2 zone 0 98 %
23/24, zone 3 94 % 10/11, zone 4 97 % **9/9**, zone 6 100 % 3/3.

## Lecture
- Il explore plus que tous les autres : meilleure couverture et plus de carrefours retrouvés partout (holdouts compris),
  au prix de la précision — en ho1 il suit les escaliers de l'IGC et prolonge l'avenue du parc Montsouris hors de
  l'annotation (650 px de trop contre 270–293 pour v5-z6-g1 / v6-ft). La graine 1 (`v6-z14-g1`, non livrée) fait pareil
  en pire (57 % en ho1, 1 042 px de trop) : ce n'est pas un hasard de graine, c'est l'effet d'un tiers du train tiré de
  zones denses où presque chaque trait est une galerie.
- Sur le nord-est il pose trois carrefours pour un annoté. Utile pour chercher ce que l'annotation a oublié ; pénible si
  on veut un tracé propre.

## Usage
Variante « exploratrice » : à essayer quand `v6-ft` s'arrête trop tôt dans une zone dense. Pas le défaut.

Variante `--zone-aug 3` (v6-z14-za3, graine 1, non livrée) : ho1 97,9 % / 69,8 % / 14/15, ho2 98,6 % / 64,0 % / 18/20,
nord-est 93 % / 61/65 — mais sud2 z3 retombe à 52 % de couverture, 1/11 carrefours : trois répétitions ne suffisent plus
aux petites zones.
