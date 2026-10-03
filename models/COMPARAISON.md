# Comparaison des modèles (campagne v4, octobre 2026)

Tous les modèles : ResNet-18 pré-entraîné, 4 canaux (RGB + galeries déjà tracées), sortie multi-label (une probabilité
par secteur), cul-de-sac = aucun secteur actif. Entraînés sur la RTX 3080, 30 époques, `bs 64`, `lr 3e-4`, AdamW +
OneCycle. Les v4 utilisent les deux gros projets (`nexus_alkhemia_2011` : 1 138 points ; `nexus_alkhemia_2011-0202` :
1 839 points ; le fichier `-02` est un préfixe du second et n'est pas utilisé).

| modèle | données | fenêtre | secteurs | pas / visée | particularité |
|---|---|---|---|---|---|
| v2 (non livré) | projet 01 | 128 | 32 | 4 / 16 | ancien oracle (cible lissée) |
| `v3-pas2` | projet 01 | 128 | 32 | 2 / 6 | visée nette |
| `v4-w128-k32` | 01 + 0202 | 128 | 32 | 2 / 6 | base v4 |
| `v4-w128-k32-g1` | 01 + 0202 | 128 | 32 | 2 / 6 | graine 1 |
| `v4-w128-k32-sansbleu` | 01 + 0202 | 128 | 32 | 2 / 6 | états sur trait bleu retirés |
| `v4-w128-k64` | 01 + 0202 | 128 | **64** | 2 / 6 | |
| `v4-w96-k32` | 01 + 0202 | **96** | 32 | 2 / 6 | |
| `v4-w192-k32` | 01 + 0202 | **192** | 32 | 2 / 6 | |

## Zones de validation

Jamais vues à l'entraînement (le graphe complet est conservé pour calculer les étiquettes au bord) :

- **ho1** `4200,3200,5800,3600` — projet 01, sud (IGC, aqueducs, nœud dense devant la plaque de la ligne de Sceaux,
  bd Saint-Jacques). 15 carrefours. Annotation quasi exhaustive.
- **ho2** `3000,2500,4100,2900` — projet 0202 (salle des Fêtes, allée de Montrouge, transversales hachurées, un lavis
  bleu de galerie inférieure). 20 carrefours. **Annotation = un itinéraire, pas un relevé exhaustif** : plusieurs
  galeries dessinées n'y sont pas tracées, ce qui plafonne la « précision » de tout modèle qui explore.

## Métriques sur exemples isolés (ensemble de validation = exemples des deux zones)

| modèle | P dir. | R dir. | F1 | cul-de-sac | rappel carrefours | erreur angulaire |
|---|---|---|---|---|---|---|
| v2 ¹ | 0,985 | 0,900 | 0,941 | 0,667 | 0,681 | 2,50° |
| v3-pas2 ¹ | 0,985 | 0,961 | 0,973 | 0,741 | 0,792 | 3,36° |
| v4-w128-k32 | 0,972 | 0,952 | 0,962 | **0,756** | 0,776 | 3,41° |
| v4-w128-k32-g1 | 0,970 | 0,957 | **0,963** | 0,733 | **0,797** | 3,41° |
| v4-w128-k32-sansbleu ² | 0,969 | 0,953 | 0,961 | 0,689 | 0,789 | 3,41° |
| v4-w128-k64 | 0,967 | 0,955 | 0,961 | 0,667 | 0,796 | 3,40° |
| v4-w96-k32 | 0,972 | 0,951 | 0,961 | 0,733 | 0,772 | 3,49° |
| v4-w192-k32 | 0,971 | 0,956 | **0,963** | 0,689 | **0,797** | 3,45° |

¹ validation = ho1 seulement (projet 01), donc non comparable aux v4. ² ensemble de validation légèrement différent.

Toutes les v4 sont à **±0,3 point** les unes des autres sur ces chiffres : la fenêtre, le nombre de secteurs et le
filtre bleu ne changent pas ce que le réseau sait faire sur un exemple isolé. L'erreur angulaire (3,4°) est fixée par la
visée (6 px sur un trait de 2–3 px), pas par la résolution de la sortie. Le cul-de-sac (45 exemples) est bruité.

## Suivi réel (`tools/trace.py --seed auto --reseed 3`, tolérance 3 px)

Couverture = part de l'annotation de la zone à moins de 3 px du tracé produit. Précision = part du tracé produit (dans la
zone) à moins de 3 px de **toute** l'annotation. Carrefours = carrefours annotés retrouvés à moins de 15 px. Écart =
distance médiane carrefour produit ↔ carrefour annoté. « Trop » = longueur produite à plus de 6 px de l'annotation.
Départs = nombre de relances automatiques nécessaires (1 = la zone est couverte du premier coup).

| modèle | ho1 couv. | ho1 préc. | ho1 carrefours | écart | trop | départs | ho2 couv. | ho2 préc. | ho2 carrefours | écart | trop | départs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| oracle (borne) | 99,8 | 100 | 15/15 | 1,5 | 0 | 1 | 99,6 | 99,9 | 20/20 | 1,5 | 0 | 1 |
| v2 | 89,6 | 66,6 | 7/15 | 32,1 | 557 | 4 | 88,3 | 66,0 | 14/20 | 7,6 | 868 | 1 |
| v3-pas2 | 96,7 | 87,7 | 11/15 | 2,1 | 186 | 4 | 96,2 | 62,8 | 12/20 | 5,5 | 1 246 | 4 |
| **v4-w128-k32** | 96,8 | **94,2** | 13/15 | 1,4 | **62** | 1 | 97,1 | 60,6 | **15/20** | 3,3 | 1 363 | 1 |
| v4-w128-k32-g1 | **98,2** | 63,0 | **15/15** | 1,2 | 822 | 1 | 96,8 | 58,1 | 14/20 | 3,2 | 1 511 | 1 |
| v4-w128-k32-sansbleu | 96,7 | 79,3 | 13/15 | 1,5 | 349 | 1 | 95,9 | 60,4 | 15/20 | **1,8** | 1 451 | 4 (sans gain) |
| v4-w128-k64 | 97,8 | 63,7 | 14/15 | 1,5 | 783 | 1 | **98,5** | 59,0 | 15/20 | 2,0 | 1 468 | 2 |
| v4-w96-k32 | 97,3 | 58,2 | 13/15 | **1,0** | 1 017 | 1 | 96,9 | 58,4 | 14/20 | 1,9 | 1 536 | 3 (13,8 % au 1ᵉʳ) |
| v4-w192-k32 | 97,4 | 75,0 | 12/15 | 1,9 | 424 | 3 | 97,7 | **68,0** | 13/20 | 2,6 | **966** | 1 |

(Les rapports complets — branches, raisons d'arrêt, carrefours manqués — sont dans les `NOTES.md` de chaque modèle ;
v2 n'est pas livré : il coupe les virages, voir `v3-pas2/NOTES.md`.)

## Ce qu'on peut conclure

1. **Les données font la différence, pas les hyperparamètres.** v3 → v4-w128-k32 (même recette, deux projets au lieu
   d'un) : sur la zone 0202, couverture au premier départ 69 → 97 %, carrefours 12 → 15 posés à 3 px au lieu de 5–22, et
   ho1 progresse aussi (11 → 13 carrefours, 186 → 62 px de trop). C'est le seul écart de la campagne qui dépasse
   clairement le bruit.
2. **Le bruit de graine est énorme en suivi réel.** Deux entraînements identiques (graines 0 et 1) : exemples isolés
   indiscernables, mais 94 % contre 63 % de précision en ho1 et 13 contre 15 carrefours. Les écarts de précision entre
   w96 / w128 / w192 / k64 / sans-bleu (58–94 % en ho1) sont du même ordre : **ils ne permettent pas de classer ces
   variantes**. Ce qui est stable sur les six modèles v4 : couverture 96–98 %, 13–15/15 et 13–15/20 carrefours,
   écart 1–3 px.
3. **Fenêtre.** 96 px : mêmes scores isolés, mais le suivi est instable (13,8 % de couverture au premier départ en ho2,
   le plus de tracé en trop) — le contexte sert à *ne pas* partir dans un décor. 192 px : meilleure précision en ho2
   (68 %) et meilleur rappel de carrefours isolés, mais pas plus de carrefours retrouvés en suivi, et 2,25× plus de
   calcul. 128 reste le bon compromis.
4. **64 secteurs.** Aucun gain d'angle (3,40° contre 3,41°) ; plus de branches ouvertes, un carrefour de plus en ho1,
   mais les culs-de-sac tombent à 67 % et le seuil 0,5 n'est plus adapté (la masse des étiquettes douces se répartit sur
   plus de voisins). Pas convaincant à seuil égal.
5. **Étages inférieurs (bleu).** Retirer les 884 états posés sur du bleu ne change rien aux scores et crée un trou en
   ho2 que trois relances n'ouvrent pas : le modèle n'a jamais appris à traverser une zone bleue. **Pas la peine de
   nettoyer tes projets** ; si on veut gérer les niveaux, ce sera une sortie « niveau » en plus, pas un filtrage.
6. **D'où viennent les erreurs restantes** (en recoupant les tracés avec la carte) :
   - *Annotation incomplète* : en ho2, le « trop » de tous les modèles (950–1 500 px) longe des galeries dessinées non
     tracées (rue Gassendi, allée de Montrouge, transversales). La précision y est plafonnée vers 60–68 %. Compléter
     l'annotation de cette zone donnerait une mesure honnête.
   - *Décor pris pour une galerie* : la bande sombre de la ligne de Sceaux (ho1) est suivie par 5 modèles sur 6. Ce n'est
     jamais un négatif dans les données (on n'annote que des galeries). Des exemples « ici ce n'est pas une galerie »
     (points posés volontairement sur ces lignes avec zéro direction, ou les refus du mode assisté) seraient la
     correction la plus directe.
   - *Traceur* : les deux carrefours du nœud dense de ho1 (4431,3340 et 4461,3308 : trois branches à moins de 30 px)
     sont manqués par tous les modèles à 32 secteurs sauf g1 — fusion de branches dans `trace.py` (`--side-sep 20`,
     `--confirm 2`), pas forcément le modèle.
   - *Seuil de confiance* : la plupart des arrêts « faible confiance » sont à moins de 1 px de l'annotation, au bout des
     galeries tracées — le modèle hésite là où l'annotation s'arrête aussi. Un seuil par modèle (calibré sur la
     validation) est à faire ; il est fixé à 0,5 pour tous ici.
7. **Pistes** (par ordre de rendement attendu) : (a) moyenner 2–3 graines à l'inférence pour lisser les décisions limites ;
   (b) exemples négatifs sur les lignes qui ne sont pas des galeries ; (c) réinjecter les corrections du mode assisté
   (déjà journalisées) comme exemples ; (d) calibrer le seuil par modèle ; (e) seulement ensuite, une architecture plus
   grosse.

## Recommandation

Par défaut dans l'app : **`v4-w128-k32`**. Si tu annotes une zone dense où il s'arrête trop tôt, essaie `v4-w128-k32-g1`
ou `v4-w192-k32`. Tous restent des **outils de proposition à valider** : aucun n'a été évalué en autonomie sur une zone
de plus de 1 600 × 400 px, et la précision réelle hors des zones bien annotées est inconnue.
