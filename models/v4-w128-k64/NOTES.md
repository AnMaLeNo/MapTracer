# v4-w128-k64 — 64 secteurs au lieu de 32

Identique à v4-w128-k32 (deux projets, fenêtre 128, pas 2, visée 6) mais la sortie compte **64 directions** (5,6° par
secteur au lieu de 11,25°) ; la largeur des étiquettes douces suit (`sigma` = 1,4 secteur ≈ 7,9°, la même en degrés).
Question posée : une sortie plus fine donne-t-elle des directions plus précises et de meilleurs carrefours ?

## Entraînement
- Même dataset que k32 régénéré avec `--sectors 64` (56 118 exemples).
- `train.py --epochs 30 --bs 64 --lr 3e-4` ; meilleure époque 23 (F1 0,961).

## Résultats
Validation : P 96,7 % / R 95,5 % / F1 0,961 ; cul-de-sac **66,7 %** (k32 : 75,6 %) ; rappel des carrefours 79,6 %
(k32 : 77,6 %) ; erreur angulaire 3,40° (k32 : 3,41°) — **aucun gain angulaire**.

Suivi réel (tolérance 3 px) :

| zone | couverture | précision | carrefours | écart médian | départs | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 97,8 % | 63,7 % | **14/15** | 1,5 px | 1 | 7 faible confiance, 12 hors zone, 6 jonctions |
| ho2 | **98,5 %** | 59,0 % | 15/20 | **2,0 px** | 2 | 9 faible confiance, 16 hors zone, 15 jonctions |

## Lecture
- L'erreur angulaire ne bouge pas (3,4°) : la précision de direction est déjà limitée par l'étiquette (visée à 6 px sur
  un trait de 2–3 px), pas par la résolution de la sortie. Doubler les secteurs n'apporte rien là-dessus.
- Il retrouve un carrefour de plus en ho1 (4431,3340, que k32 et v3 manquent) et pose les carrefours de ho2 à 2 px :
  les secteurs fins séparent mieux deux branches proches (côté « ouvrir une branche », pas côté « angle exact »).
- Contrepartie : il **explore beaucoup plus** — 2 267 px tracés dans ho1 là où l'oracle (qui lit l'annotation) en trace
  1 808 et k32 1 493. Le trop
  (≈ 780 px) suit l'avenue du parc Montsouris et la maison n° 13 (galeries réelles, non annotées) mais aussi la bande
  sombre de la ligne de Sceaux (pas une galerie). Les culs-de-sac sont nettement moins bien détectés (66,7 %) : avec
  64 sorties, il y a toujours un secteur qui dépasse le seuil 0,5.
- Lecture pratique : le seuil `thr` devrait être recalibré pour 64 secteurs (les étiquettes douces répartissent la
  masse sur plus de voisins) ; à seuil égal, k64 est un modèle « optimiste ».

## Usage
Utile pour explorer une zone peu annotée (il ne s'arrête presque jamais) ; à éviter si on veut peu de corrections.
