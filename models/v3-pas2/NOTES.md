# v3 — pas 2 px, visée nette 6 px, fenêtre 128, 32 secteurs (projet 01 seul)

Modèle de référence avant la campagne v4 : il corrige le défaut de v2 (virages coupés, carrefours annoncés trop tôt) en
réduisant le pas à 2 px et en visant une cible à 6 px qui **s'arrête** au carrefour ou au virage serré (> 45°) au lieu de
passer derrière.

## Entraînement
- Données : `nexus_alkhemia_2011.maptracer.json` seul (1 138 points), zone de validation `4200,3200,5800,3600` exclue.
- `oracle.py --step 2 --lookahead 6 --near 6 --bend-deg 45 --window 128 --sectors 32` → 25 707 exemples (21 684 / 4 023).
- `train.py --epochs 30 --bs 64 --lr 3e-4` sur RTX 3080 ; meilleure époque 18.

## Résultats
Validation (exemples isolés) : précision des directions 98,5 %, rappel 96,1 %, F1 0,973 ; cul-de-sac 74 % ; rappel des
carrefours 79 % ; erreur angulaire 3,4°.

Suivi réel (`trace.py --seed auto --reseed 3`, tolérance 3 px, précision jugée dans la zone contre toute l'annotation) :

| zone | couverture (1ᵉʳ départ → après relances) | précision | carrefours | écart médian carrefour | départs |
|---|---|---|---|---|---|
| ho1 (projet 01, sud) | 92,2 % → 96,7 % | 87,7 % | 11/15 | 2,1 px | 4 |
| ho2 (projet 0202, jamais vu) | 69,5 % → 96,2 % | 62,8 % | 12/20 | 5,5 px | 4 |

Au premier départ seul (ancienne mesure) : ho1 92,2 % / 85,5 % / 11 carrefours ; ho2 69,5 % / 61,5 % / 9 carrefours,
écart médian 21,6 px.

## Limites
- Entraîné sur une seule zone de la carte : sur la zone 2 (galeries larges hachurées, salle des fêtes, tracés doubles) il
  s'arrête faute de confiance sur 650 px de référence (un tronçon de 380 px, un de 145 px) et manque 11 carrefours sur 20
  au premier départ ; il faut 3 relances pour couvrir la zone, là où v4-w128-k32 la couvre d'un seul départ.
- Comparaison : voir `v4-w128-k32/NOTES.md` (même recette, entraîné sur les deux projets).
- Les culs-de-sac restent le point faible (27 exemples seulement en validation).
- Outil de proposition à valider, pas un traceur autonome.
