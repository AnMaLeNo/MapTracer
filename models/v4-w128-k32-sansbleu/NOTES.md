# v4-w128-k32-sansbleu — étages inférieurs (traits bleus) retirés de l'entraînement

Identique à v4-w128-k32, mais l'oracle ignore tout état dont le voisinage (7×7 px) contient plus de 25 % de pixels
« bleus » (B > R + 25 et B > V + 10) : `--skip-blue`. Question posée (la tienne) : les étages inférieurs annotés dans le
projet 0202, dont les raccords sont incertains même pour toi, ajoutent-ils du bruit ?

## Entraînement
- 884 états sur trait bleu retirés (1,6 % des exemples) → 53 478 exemples (44 115 / 9 363). Les traits bleus restent
  **visibles** dans les fenêtres : seuls les états posés dessus disparaissent.
- `train.py --epochs 30` ; meilleure époque 23 (F1 0,961). Validation : P 96,9 % / R 95,3 % ; cul-de-sac 68,9 % ;
  carrefours 78,9 % ; 3,41° — identique à la version avec bleu (l'ensemble de validation n'est plus tout à fait le même,
  la comparaison fine n'a pas de sens).

## Résultats en suivi réel (tolérance 3 px)

| zone | couverture | précision | carrefours | écart médian | départs | arrêts |
|---|---|---|---|---|---|---|
| ho1 | 96,7 % | 79,3 % | 13/15 | 1,5 px | 1 | 9 faible confiance, 8 hors zone, 3 jonctions |
| ho2 | **95,9 %** (le plus bas de la campagne) | 60,4 % | 15/20 | 1,8 px | 4 relances **sans gain** | 12 faible confiance, 15 hors zone, 10 jonctions |

## Lecture
- Aucun gain mesurable : carrefours identiques (13 et 15), même précision en ho2 (60 % — plafonnée par les galeries non
  annotées, voir v4-w128-k32), et en ho1 précision 79 % contre 94 % (il repart vers la salle des Agapes sur ≈ 350 px de
  galerie non annotée, ce qui est une variation de seuil plus qu'un effet du bleu).
- Un effet **négatif** net : en ho2 il laisse un trou (≈ 90 px, avenue du sud de l'est, au bord du lavis bleu de la
  galerie inférieure) que trois relances successives n'arrivent pas à ouvrir — il s'arrête dès le premier pas. Comme il
  n'a jamais vu d'état posé sur du bleu, il refuse de **traverser** une zone bleue, alors que les galeries de l'étage
  supérieur y passent. Retirer les exemples ne retire pas les pixels : il faut au contraire des exemples dessus.
- Réponse à ta question : les ~880 états bleus n'ajoutent pas de bruit mesurable au modèle avec bleu (mêmes scores) ;
  les retirer coûte un peu. Pas la peine de nettoyer les deux projets. Si un jour on veut distinguer les niveaux, c'est
  une **sortie** supplémentaire (niveau du point) qu'il faudra, pas un filtrage.
- Réserve : une seule graine ; les écarts de précision entre modèles « jumeaux » (voir COMPARAISON.md, graine 1) montrent
  que ±10 points de précision en ho1 sont dans le bruit d'entraînement.

## Usage
À ne pas préférer à v4-w128-k32. Gardé pour documenter l'expérience.
