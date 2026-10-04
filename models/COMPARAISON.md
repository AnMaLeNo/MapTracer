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

---

# Campagne v5 (octobre 2026) : exemples difficiles du mode Auto

Même recette que `v4-w128-k32` (fenêtre 128, 32 secteurs, pas 2 / visée 6, 30 époques), avec en plus les **six zones
corrigées** de `data/zones/nexus_alkhemia_2011_sud_v4-w128-k32_2026-10-04.mapzones.json` : tracé Auto de
`v4-w128-k32` depuis (4262, 5426), six zones (≈ 950 px de galeries, 18 carrefours, sud de la carte) réannotées à la main
là où il se trompait. Les zones sont répétées `--zone-aug` fois dans le dataset (les projets : 1 fois). Validation
inchangée (mêmes holdouts, 9 603 exemples). Provenance et tracé complet du modèle dans le fichier ; comparaison zone par
zone avec `tools/zones_report.py`.

| modèle | données | particularité | livré |
|---|---|---|---|
| `v5-z6` | 01 + 0202 + 6 zones ×6 | 61 739 ex. (zones ≈ 11 % du train) | oui |
| `v5-z6-g1` | idem | graine 1 | oui |
| v5-z20 | 01 + 0202 + 6 zones ×20 | 72 981 ex. | non |
| v5-ft | 01 + 0202 + 6 zones ×6 | affinage de `v4-w128-k32` (`--init`, 10 ép., lr 1e-4, 5 min) | non |

## Exemples isolés (validation)

| modèle | P dir. | R dir. | F1 | cul-de-sac | rappel carrefours | erreur angulaire |
|---|---|---|---|---|---|---|
| v4-w128-k32 (rappel) | 0,972 | 0,952 | 0,962 | 0,756 | 0,776 | 3,41° |
| v5-z6 | 0,972 | 0,956 | 0,964 | 0,756 | 0,790 | 3,40° |
| v5-z6-g1 | 0,970 | 0,960 | **0,965** | 0,711 | **0,826** | **3,34°** |
| v5-z20 | 0,972 | 0,956 | 0,964 | 0,733 | 0,799 | 3,45° |
| v5-ft | 0,970 | 0,957 | 0,964 | **0,800** | 0,797 | 3,48° |

Toujours ±0,3 point : la validation ne contient pas les zones, elle ne peut pas voir ce qu'elles apportent.

## Suivi réel sur les holdouts (jamais vus)

| modèle | ho1 couv. | ho1 préc. | ho1 carrefours | écart | trop | ho2 couv. | ho2 préc. | ho2 carrefours | écart | trop |
|---|---|---|---|---|---|---|---|---|---|---|
| v4-w128-k32 | 96,8 | **94,2** | 13/15 | 1,4 | **62** | 97,1 | 60,6 | 15/20 | 3,3 | 1 363 |
| v4-w128-k32-g1 | **98,2** | 63,0 | **15/15** | 1,2 | 822 | 96,8 | 58,1 | 14/20 | 3,2 | 1 511 |
| v5-z6 | 97,2 | 58,9 | 13/15 | 2,0 | 944 | 98,2 | 59,9 | **16/20** | **2,3** | 1 413 |
| v5-z6-g1 | 96,3 | 82,7 | 13/15 | **1,1** | 270 | **98,6** | **63,3** | 15/20 | 2,7 | **1 230** |
| v5-z20 | 98,0 | 69,9 | 14/15 | 1,8 | 586 | 97,4 | 57,4 | 14/20 | 3,2 | 1 554 |
| v5-ft | 97,0 | 85,6 | 13/15 | 1,9 | 211 | 97,0 | 62,6 | 11/20 | 4,1 | 1 251 |

## Suivi relancé sur les six zones corrigées

`trace.py --zone i --seed auto`, référence = l'annotation de la zone, carrefours comptés par `trace.py` dans la zone
découpée. **Ces zones sont dans l'entraînement des v5** : on mesure si le modèle a appris la correction, pas s'il
généralise. Marge 10 px (défaut) puis 30 px (le traceur a la place de revenir dans la zone) — carrefours retrouvés /
annotés :

| zone (id) | v4-w128-k32 | v4 g1 | v5-z6 | v5-z6-g1 | v5-z20 | v5-ft |
|---|---|---|---|---|---|---|
| 1 (nœud, 6) | 0/6 → 1/6 | 4/6 → 3/6 | **6/6 → 6/6** | **6/6 → 6/6** | **6/6 → 6/6** | 6/6 → 5/6 |
| 2 (croix) | 0 → 0 | 0 → 0 | 0 → **1/1** | 0 → **1/1** | 0 → **1/1** | 0 → **1/1** |
| 3 (croix) | 0 → **1/1** | 0 → 0 | 0 → **1/1** | 0 → **1/1** | 0 → **1/1** | 0 → **1/1** |
| 4 | 0 → 0 | 0 → 0 | **1/1 → 1/1** | 0 → **1/1** | 0 → **1/1** | 0 → **1/1** |
| 5 | 0/2 → 0/2 | 0/2 → 0/2 | **2/2 → 2/2** | 0/2 → **2/2** | 0/2 → 1/2 | 0/2 → **2/2** |
| 6 (8) | 1/8 → 4/8 | 0/8 → 1/8 | **7/8** → 7/8 | **7/8 → 8/8** | **8/8 → 8/8** | 5/8 → **8/8** |

Couverture de l'annotation des zones (marge 30) : v4 43–94 %, v5 81–100 %.

## Ce qu'on peut conclure

1. **Les corrections sont apprises.** Les quatre v5 retrouvent tous les carrefours des six zones (marge 30), là où v4
   en voyait 1 à 5 sur 18. ×6 suffit ; ×20 n'apporte rien de plus. L'affinage de 5 min (`v5-ft`) les apprend aussi.
2. **Les holdouts ne bougent pas au-delà du bruit de graine** : carrefours 13–14/15 et 14–16/20 (v4 : 13–15 et 14–15),
   couverture 96–99 %, précision ho1 59–86 % (v4 : 63–94 %, voir `v4-w128-k32-g1`). Six zones ≈ 950 px contre 22 500 px
   de graphe : elles corrigent ce qu'elles couvrent, pas plus. C'est le résultat attendu d'une première itération ;
   l'effet sur la généralisation viendra du **cumul** de zones, à des endroits et sur des configurations variés
   (et de zones autour des erreurs *de v5*, pas seulement de v4).
3. **Petites zones = évaluation fragile.** Dans les croix de 60 px (zones 2–3), le traceur parti d'un bout sort de la
   zone avant d'avoir confirmé la branche latérale (`--confirm 2`) : 0/1 à 10 px de marge, 1/1 à 30 px, pour tous les
   v5. Pour l'entraînement ça ne gêne pas ; pour juger une zone, la prendre un peu plus large (≈ 150 px).
4. **Affinage vs réentraînement.** `v5-ft` (10 époques depuis v4) garde la précision ho1 de v4 (85,6 %) et apprend les
   zones, mais perd 4 carrefours en ho2 (11/20, dans le bruit). Cinq fois moins cher : à retenir quand les zones
   s'accumuleront, avec ho2 sous surveillance.

## Recommandation

Défaut de l'app inchangé : **`v4-w128-k32`** (aucune v5 ne fait mieux sur les holdouts de façon mesurable). Pour la
prochaine série de zones, lancer le mode Auto avec **`v5-z6-g1`** : il contient les six corrections, ses erreurs sont
donc de nouvelles erreurs, et ses holdouts sont les plus équilibrés des v5 (ho1 83 % / 1,1 px ; ho2 98,6 % / 15/20).
Toujours des outils de proposition à valider.
