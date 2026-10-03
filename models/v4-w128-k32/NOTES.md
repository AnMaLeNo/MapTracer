# v4-w128-k32 — deux projets, fenêtre 128, 32 secteurs (modèle de base de la campagne v4)

Même recette que v3 (pas 2 px, visée nette 6 px, ResNet-18 4 canaux), mais entraîné sur **les deux gros projets**
(`nexus_alkhemia_2011` + `nexus_alkhemia_2011-0202`, 2 980 points) avec une zone de validation dans chacun.
C'est le modèle à comparer à v3 pour mesurer l'effet des données seules, et la référence des autres variantes v4.

## Entraînement
- `oracle.py <projet 01> <projet 0202> --step 2 --lookahead 6 --near 6 --window 128 --sectors 32
  --holdout 4200,3200,5800,3600 --holdout 3000,2500,4100,2900` → 56 118 exemples (46 515 / 9 603), 171 fins,
  4 125 états multi-directions ; 600 amorces en attente ignorées. Étages inférieurs (traits bleus) **inclus**.
- `train.py --epochs 30 --bs 64 --lr 3e-4` (RTX 3080, ~22 s/époque) ; meilleure époque 26 (F1 0,962).

## Résultats
Validation : précision des directions 97,2 %, rappel 95,2 %, F1 0,962 ; cul-de-sac 75,6 % (45 ex.) ; rappel des
carrefours 77,6 % ; erreur angulaire 3,4°. Légèrement sous v3 sur ces chiffres — normal, la validation contient
maintenant la zone 2, plus difficile.

Suivi réel (`trace.py --seed auto --reseed 3`, tolérance 3 px, précision jugée dans la zone contre toute l'annotation) :

| zone | couverture | précision | carrefours | écart médian | départs nécessaires | arrêts |
|---|---|---|---|---|---|---|
| ho1 (projet 01) | 96,8 % | **94,2 %** | 13/15 | 1,4 px | 1 (v3 : 4) | 12 faible confiance, 6 hors zone, 2 jonctions |
| ho2 (projet 0202) | 97,1 % (v3 : 69,5 % au 1ᵉʳ départ) | 60,6 % | 15/20 (v3 : 9) | 3,3 px (v3 : 21,6) | 1 (v3 : 4) | 6 faible confiance, 13 hors zone, 12 jonctions |

## Lecture
- Les données de la zone 2 règlent le problème de v3 sur cette zone : couverture 69 → 97 % au premier départ,
  carrefours 9 → 15 posés à 3 px au lieu de 22. Et ho1 ne régresse pas (carrefours 11 → 13).
- La précision de 60 % en ho2 n'est **pas** une hallucination : en superposant tracé et carte, le « trop » (≈ 1 360 px
  dans la zone) longe des galeries dessinées mais pas encore annotées (rue Gassendi / rue Roger vers le sud, allée de
  Montrouge, transversales hachurées). L'annotation de la zone 2 est un itinéraire, pas un relevé exhaustif, donc la
  précision y est plafonnée vers 60–65 % pour tout modèle qui explore (même l'oracle fait 99 % uniquement parce qu'il
  lit l'annotation). En ho1, où l'annotation est quasi complète, le trop n'est que de 62 px.
- Modèle le plus **prudent** de la campagne : 12 arrêts « faible confiance » en ho1 (presque tous à moins de 1 px de la
  référence, au bout des galeries annotées vers la salle des Agapes et autour du nœud dense), là où w96 / k64 continuent
  et vont jusqu'à suivre la bande sombre de la ligne de Sceaux, qui n'est pas une galerie.
- Carrefours manqués en ho1 : les deux mêmes qu'avec v3 (4431,3340 de degré 4 et 4461,3308), au nœud dense devant la
  « grande plaque de la ligne de Sceaux » — trois branches à moins de 30 px, le traceur en fusionne deux.

- **Réserve importante** : le même entraînement relancé avec une autre graine (`v4-w128-k32-g1`) donne en ho1 une
  précision de 63 % (il part sur la ligne de Sceaux) et 15/15 carrefours. La précision en ho1 dépend donc d'une ou deux
  décisions « je continue / je m'arrête » que la graine fait basculer ; le 94 % ci-dessus n'est pas une propriété stable
  de la recette, c'est ce que *ce* fichier de poids fait. Les carrefours (13–15/15, 14–15/20) et la couverture (97–98 %)
  sont, eux, stables d'une graine à l'autre.

## Usage
Modèle recommandé par défaut pour le mode assisté : les meilleurs carrefours (position à 1,4 px) et le moins de tracés
parasites. Toujours une proposition à valider, pas un traceur autonome.
