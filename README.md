# MapTracer

Outil d'annotation pour vectoriser une carte de galeries (catacombes de Paris, Nexus 2011…) **pas à pas**, et produire le
jeu de données qui servira à entraîner un modèle de suivi de galeries assisté par IA.

Principe : plutôt que de vectoriser toute la carte d'un coup, on suit une galerie point après point. À chaque étape le
modèle (ou, pour l'instant, l'humain) ne voit qu'une **fenêtre carrée** de la carte centrée sur le point courant, avec les
points déjà posés, et doit décider du **prochain point**. Chaque clic humain devient un exemple d'entraînement.

## Lancer l'application

```bash
python3 server.py                                   # http://127.0.0.1:8080/app/ — manuel + assisté + Auto avec les modèles de models/
python3 server.py 8080 --model runs/x/model.pt      # ajoute un model.pt isolé à la liste ; --device cuda|cpu
```

Les modèles livrés sont dans `models/<nom>/` (`model.pt` en float16 + `NOTES.md` : stratégie, résultats, limites) ; le
serveur les liste et l'app les propose dans le menu « Modèle » (voir `models/README.md`). Aucune dépendance pour le mode manuel : HTML/JS pur (le mode assisté demande `torch`/`torchvision`, voir plus bas). La carte Nexus 2011 (6307 px, géoréférencée) est fournie dans `maps/` ; toute autre image
peut être ouverte par glisser-déposer. Le projet est sauvegardé automatiquement dans le navigateur (IndexedDB) et
exportable en JSON.

## Règles d'annotation

| Situation | Action | Effet |
|---|---|---|
| Aucun point | clic | pose le **point de départ** (se comporte comme une intersection) |
| Point courant **normal** | clic | pose le point suivant ; la vue se recentre dessus immédiatement |
| Point courant **intersection** ou **départ** | clics | pose une amorce par direction possible (plusieurs points) |
| idem | `Espace` | passe sur la première amorce ; les autres vont dans la file d'attente |
| Cul-de-sac | `F` | termine la branche → prochaine branche en attente, sinon retour au départ |
| Zone déjà cartographiée | clic sur un point existant | **jonction** : relie et termine la branche ; si ce point était `normal`, il devient une intersection |
| Zone déjà cartographiée, intersection oubliée | clic sur un **segment** existant | insère une intersection à cet endroit (le segment est coupé en deux), puis jonction |
| Poser une intersection | `Maj+clic`, clic droit ou `I` puis clic | le nouveau point est de type intersection |
| Erreur | `Ctrl+Z` | annule le dernier événement (illimité) |
| Changer le type du point courant | `T` | normal ↔ intersection (tant qu'il n'a pas de suite) |
| Fin complète | « Terminer la session » | marque le projet comme achevé |

Un point se pose **le plus loin possible sur la galerie sans que le segment traverse un mur** (virage, changement de
direction, suivi d'une courbe). La fenêtre n'est qu'un repère visuel (le modèle final avance à pas fixe) ; l'option « hors fenêtre » permet de la rendre bloquante.

La taille de la fenêtre est réglable à tout moment ; elle est enregistrée avec chaque événement et peut être changée a
posteriori à l'export (seule la séquence ordonnée des points compte).

## Mode assisté (`tools/assist.py`, `/api/predict`)

Case « Mode assisté » (touche `A`), disponible quand le serveur a au moins un modèle (`models/` ou `--model`) et que la carte
vient de la liste (`maps/`). Le menu « Modèle » choisit celui qui propose (chargé à la première demande, gardé en mémoire ;
le choix est enregistré dans le projet et envoyé à chaque requête `/api/predict` dans `model`). À chaque point courant, le serveur suit le modèle sur « portée des propositions » px (défaut 32) et l'app dessine
en violet :

- depuis un point normal : le prochain point proposé avec sa confiance ; ou une **intersection** (plusieurs directions
  confirmées sur deux pas) avec ses directions ; ou **cul-de-sac** ; ou **jonction** (le suivi retombe sur un segment déjà
  tracé — à vous de cliquer le point/segment pour raccorder) ;
- depuis le départ ou une intersection : une amorce par direction (celles déjà couvertes par une amorce posée sont omises).

`Entrée` ou clic sur la proposition l'accepte ; cliquer ailleurs ou `F` corrige. Rien n'est posé sans votre décision, et le
mode manuel reste identique. Chaque événement `place`/`end` pris en présence d'une proposition porte `prop` (liste
`{kind, x, y, conf}`) et `accepted` ; le dérivé du graphe ignore ces champs, donc `oracle.py` apprend de vos corrections
comme du reste, et les compteurs « propositions suivies / corrigées » mesurent le modèle en conditions réelles.

La « portée » ne change **pas** le pas du modèle : le serveur avance toujours du pas d'entraînement lu dans le `.pt`
(`meta.step`, 2 px pour le modèle v3) et enchaîne autant de petits pas que la portée le permet ; elle ne fixe que la longueur
de la proposition affichée. Un modèle entraîné à 2 px s'utilise donc à 2 px — c'est automatique.

## Mode Auto : le modèle trace tout, l'humain corrige par zones (`app/auto.js`, `/api/trace`)

Bouton « Auto : le modèle trace, je corrige » en haut du panneau. Principe (*hard-example mining*) : plutôt que de réannoter
ce que le modèle sait déjà faire, on le laisse tracer, on repère **où** il se trompe et on ne corrige que là ; chaque zone
corrigée devient un mini-dataset d'exemples difficiles pour le prochain entraînement.

1. Choisir la carte (liste) et le modèle, puis **cliquer un point de départ** sur une galerie : le serveur lance la boucle
   complète de `tools/trace.py` en arrière-plan (`POST /api/trace`, budget « pas max », 20 000 par défaut ≈ 2 min sur CPU)
   et l'app affiche le tracé rouge au fur et à mesure (`GET /api/trace/<job>` toutes les 0,7 s). « Arrêter le suivi » garde
   ce qui est tracé ; « Nouveau départ » relance ailleurs **en prolongeant** le tracé existant. Les carrefours posés sont
   cerclés d'orange, les culs-de-sac annoncés par le modèle marqués d'une croix.
2. Inspecter, puis **Maj+glisser** autour d'une erreur : la zone (jaune) est **vierge** ; le tracé rouge du modèle reste
   visible dessous (et gardé dans `zone.auto`) pour voir l'erreur pendant qu'on annote.
3. Annoter la zone **à la main**, comme en mode manuel : clic = premier point, clic = point suivant relié au précédent,
   clic droit = carrefour, `F` = cul-de-sac, `Échap` = finir la branche puis clic sur un point pour en repartir. Quelques
   points suffisent (un carrefour + 2–3 points par branche). Toute extrémité non marquée `F` est **ouverte** (anneau
   pointillé) : ce n'est pas un cul-de-sac, l'oracle ignore les états dont la visée l'atteint. Retouches : glisser = déplacer ·
   clic sur un segment = insérer · `Ctrl`+clic = relier / délier · `Suppr` · `I` = type · `Ctrl+Z`. Annotez **toutes** les
   galeries de la zone : une galerie oubliée à un carrefour, c'est une direction fausse enseignée.
4. « Exporter les zones corrigées » → un fichier `*.mapzones.json` (toutes les zones, réimportable) :

```jsonc
{ "format": "maptracer-zones/1", "map": { "id": "nexus_alkhemia_2011", ... }, "seeds": [[4940, 3261]],
  "zones": [ { "id": 1, "bbox": [x0, y0, x1, y1], "model": "v4-w128-k32", "edits": 12,
               "nodes": [ { "id": 1, "x": 4931.5, "y": 3250, "kind": "normal|intersection|end", "open": false }, ... ],
               "edges": [[1, 2], ...],
               "auto": { "nodes": [...], "edges": [...] } } ] }      // le tracé du modèle avant correction, pour mémoire
```

Un nœud de degré 1 est un cul-de-sac **seulement** s'il est de type `end` ; tout autre nœud de degré 1 (`open`) est une
extrémité ouverte. Ces fichiers se donnent à l'oracle **avec** les gros projets ; leurs états reçoivent `--zone-aug` copies
perturbées (6 par défaut, contre `--aug` 2 pour les projets), ce qui les pèse ~2,3× plus :

```bash
python3 tools/oracle.py data/nexus_alkhemia_2011.maptracer.json data/nexus_alkhemia_2011-0202.maptracer.json \
        zones/*.mapzones.json maps/nexus_alkhemia_2011.jpg -o oracle_v5/ --window 128 --step 2 --lookahead 6 --near 6 \
        --holdout 4200,3200,5800,3600 --holdout 3000,2500,4100,2900
python3 tools/train.py oracle_v5/ -o runs/v5 --epochs 30
```

`meta.json` liste les entrées (`inputs`) et le nombre d'exemples par entrée (`counts.by_input`). Une zone qui tombe dans une
zone de validation `--holdout` alimente la validation, pas l'entraînement. Le mode Auto ne rend pas le modèle autonome :
c'est l'outil qui mesure ses erreurs et les transforme en données.

## Format des données

### Projet (`*.maptracer.json`)

```jsonc
{
  "format": "maptracer/1",
  "name": "...",
  "map": { "id": "nexus_alkhemia_2011", "width": 6307, "height": 6307, "hash": "…", "georef": { "lon": [a, b], "lat": [a, b] } },
  "settings": { "window": 256, "allowOutside": false },
  "events": [                       // source de vérité, dans l'ordre
    { "t": "start", "id": 1, "x": 2500, "y": 3300, "ts": 0 },
    { "t": "place", "id": 2, "from": 1, "x": 2560, "y": 3310, "kind": "normal", "window": 256 },
    { "t": "advance" }, { "t": "end" }, { "t": "join", "to": 7, "retype": true }, { "t": "retype", "id": 9, "kind": "intersection" },
    { "t": "split", "id": 12, "from": 4, "to": 5, "x": 2480, "y": 3290 },   // coupe l'arête 4→5 et s'y raccorde
    { "t": "finish" }
  ],
  "derived": { "points": [...], "edges": [...], "visits": [...] }   // commodité, recalculable depuis events
}
```

Le JSON est rejouable : l'état (point courant, file d'attente, graphe) se recalcule depuis `events`, ce qui rend l'annulation
triviale et garantit que l'ordre exact des décisions est conservé.

### Jeu d'entraînement (`tools/export_dataset.py`)

```bash
pip install pillow
python3 tools/export_dataset.py mon_projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o dataset/ --window 256 [--size 224]
```

Produit `dataset/crops/NNNNNN.png` et `dataset/samples.jsonl`, une ligne par décision :

```jsonc
{
  "image": "crops/000012.png", "window": 256, "map_center": [2560, 3310],
  "current": { "x": 128, "y": 128, "u": 0.5, "v": 0.5, "kind": "normal" },
  "previous": { "x": 71, "y": 120, ... },             // null si hors fenêtre
  "context": [ ...points déjà posés visibles dans la fenêtre... ],
  "targets": [ { "x": 190, "y": 131, "u": 0.74, "v": 0.51, "kind": "normal" } ],   // 1 pour un point normal, k pour une intersection
  "terminal": "continue" | "end" | "join",
  "join_to": { ... } | null,
  "n_targets": 1
}
```

Entrée du modèle : le crop + `current`, `previous`, `context`. Sortie attendue : `targets` (coordonnées + type), ou l'action
`end`/`join`. Si la carte est géoréférencée, `graph.geojson` (WGS84) est aussi écrit pour superposer le tracé dans
[catacombes](https://github.com/AnMaLeNo/catacombes).

## Pipeline « oracle » : pas fixe, 32 directions, canal « déjà tracé » (`tools/oracle.py`, `tools/trace.py`)

Le tracé manuel sert de **vérité** ; le modèle appris n'imite pas les clics mais apprend une politique locale :

- **Entrée** : fenêtre carrée de la carte centrée sur la position courante, **tournée pour que le cap pointe vers le haut**,
  plus un canal monochrome des **galeries déjà tracées**.
- **Sortie** : `K = 32` secteurs angulaires (secteur 0 = tout droit, sens horaire), **multi-label** : chaque secteur a sa
  propre probabilité, plusieurs secteurs actifs ⇔ intersection, **aucun secteur actif ⇔ cul-de-sac**.
- **Déplacement** : toujours du même **pas fixe** (`--step`, 2 px ≈ 1 m sur Nexus), aucune largeur à estimer.

### Génération des exemples

```bash
python3 tools/oracle.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o oracle/ --window 128 --step 2 \
        [--lookahead 6 --near 6 --bend-deg 45 --aug 2 --offset 1.5 --heading-noise 25 --holdout x0,y0,x1,y1]
```

Pour chaque arête du graphe, dans les deux sens, une position tous les `--spacing` px (défaut = pas), dupliquée `--aug`
fois avec un décalage latéral (`--offset`, défaut 0,75 × pas) et une erreur de cap (`--heading-noise`) pour apprendre le
recentrage. La cible est l'ensemble des secteurs contenant un point de l'axe à `--lookahead` px (défaut 3 × pas) le long du
graphe, une branche = un secteur (étiquettes douces gaussiennes dans `label`, secteurs entiers dans `sectors`). La visée est
**nette** : si un carrefour (degré ≥ 3) ou un virage serré (> `--bend-deg`) se trouve à plus de `--near` px (défaut 3 × pas),
la cible est ce point-là — on y va tout droit — et c'est seulement à moins de `--near` px que les directions se séparent
(cibles à `--lookahead` px *du carrefour* sur chaque branche). Sans cela, une visée longue « coupe » les coins : le modèle
apprend à tourner avant le virage et à annoncer l'intersection trop tôt (défaut du modèle v2, pas 4 px / visée 16 px, sur une
annotation dont l'arête médiane fait 5,7 px). Le canal « déjà tracé » contient
l'arête derrière la position, parfois d'autres arêtes déjà explorées (le modèle doit savoir ne pas repartir dessus).
Sortie : `map/NNNNNN.png`, `trace/NNNNNN.png`, `samples.jsonl` (+ `samples_val.jsonl` si `--holdout`, découpage **spatial**),
`meta.json`, `graph.json`.

Une extrémité de degré 1 **sans** événement `end` (amorce encore en file d'attente, point de départ) n'est pas un
cul-de-sac : la galerie continue probablement. Les états dont la visée atteint une telle extrémité sont **ignorés** (compteur
`skipped_open`) plutôt que d'enseigner une fausse fin.

### Boucle de suivi avec faux modèle

```bash
python3 tools/trace.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o trace/ --step 2 [--noise-deg 8 --drop 0.05]
```

`trace.py` est la boucle qui exploitera le modèle appris : pas fixe, suivi du secteur le plus proche du cap, ouverture d'une
branche par secteur latéral confirmé (`--confirm` observations consécutives) — le carrefour est posé **là où la direction
latérale a été vue en dernier**, c'est-à-dire au nœud lui-même, pas au premier pas où elle apparaît —, raccord au tracé
existant (jonction, insertion d'un nœud sur une arête), arrêt quand aucun secteur n'est actif (`--coast` pas tolérés), sortie de carte. Pour l'instant le seul modèle
est l'**oracle** (`--model oracle`), qui lit les directions dans le tracé manuel et peut être dégradé (`--noise-deg`,
`--drop`) pour tester la robustesse de la boucle ; `--model chemin/model.pt` branche le modèle appris (ci-dessous) et
`--bbox x0,y0,x1,y1` limite le suivi et la comparaison à une zone (la zone de validation). Elle écrit `trace_graph.json` (+ `.geojson`), `report.json` (couverture,
précision, intersections retrouvées, raisons de fin des branches) et `debug.png` (bleu = référence, rouge = tracé).

Vérification sur une carte synthétique (`tools/make_synth.py synth.png synth.maptracer.json` : galeries à double trait,
intersections, boucle, jonction, cul-de-sac, texte et trait parasites) : oracle exact → couverture 99,9 %, précision 100 %,
4/4 intersections ; oracle bruité (8°, 5 % de directions oubliées, 5 graines) → couverture 95–100 %, précision 100 %.
Ce sont des tests de **mécanique**, pas une validation du futur modèle : les jonctions créent parfois de courtes arêtes
doublons, et la politique de confiance/rejet d'un modèle appris reste à définir.

## Modèle appris (`tools/model.py`, `tools/train.py`)

Dépendances : `pip install torch torchvision` (le reste de l'outil n'en a pas besoin).

- **Réseau** : ResNet-18 pré-entraîné ImageNet, première convolution élargie à **4 canaux** (RGB carte + canal « déjà
  tracé », 4ᵉ canal initialisé par la moyenne des poids RGB), couche finale remplacée par une linéaire à **32 sorties**.
  Sigmoïde par sortie → une probabilité par direction (0–100 %) ; `end` ⇔ aucune sortie ≥ seuil. **Tout le réseau est
  entraîné** (fine-tuning complet, AdamW + OneCycle, perte BCE sur les étiquettes douces de l'oracle).
- **Augmentations** : miroir gauche↔droite (étiquette miroir), gigue de luminosité/contraste ; décalage et erreur de cap
  viennent déjà de l'oracle.

```bash
python3 tools/train.py oracle/ -o runs/v1 --epochs 15 --bs 64 --lr 3e-4          # → runs/v1/model.pt, history.json
python3 tools/trace.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o trace_v1/ \
        --model runs/v1/model.pt --bbox x0,y0,x1,y1                                # suivi réel sur la zone de validation
```

Métriques de validation (à chaque époque, sur `samples_val.jsonl`) : les secteurs actifs sont regroupés en directions comme
dans `trace.py` et appariés aux directions cibles à ±17° → précision/rappel/F1 des directions, exactitude des cul-de-sac,
rappel aux intersections, erreur angulaire moyenne. Le meilleur F1 est sauvegardé. La vraie mesure reste `trace.py`
(couverture, précision, intersections) sur une zone jamais vue.

### Résultats (Nexus 2011, 1 138 points annotés, zone de validation sud `4200,3200,5800,3600`)

Entraînement sur RTX 3080, 30 époques. **v2** : pas 4 px, visée 16 px, 10 263 exemples (3,6 s/époque) — validation
(exemples) : précision des directions 98 %, rappel 90 %, erreur angulaire 2,5°, cul-de-sac 70 %, rappel aux intersections
67 %. **v3** : pas 2 px, visée nette 6 px (`--near 6`), 25 707 exemples (8,7 s/époque) — précision 98 %, rappel 96 %, F1 0,973
(v2 : 0,941), erreur angulaire 3,4° (cibles trois fois plus proches, donc angles plus sensibles), cul-de-sac 78 %, rappel aux
intersections 79 %. Suivi réel avec `trace.py --bbox … --seed auto` (un départ par composante de la référence), tolérance 6 px
(et 3 px entre parenthèses) ; « écart carrefours » = distance médiane entre un carrefour de référence et le carrefour posé :

| modèle | couverture | précision | intersections | écart carrefours |
|---|---|---|---|---|
| oracle (borne haute de la mécanique) | 100 % (99,8 %) | 98,2 % (97,7 %) | 15/15 | 1,5 px |
| ResNet-18 v2 (pas 4, visée 16) | 93,8 % (86,6 %) | 86,0 % (80,7 %) | 8/15 | 5,0 px |
| ResNet-18 v3 (pas 2, visée nette 6) | 94,4 % (92,2 %) | 86,8 % (85,5 %) | 11/15 | 1,5 px |

Sur un second tracé jamais vu (`nexus_alkhemia_2011-02`, 137 points, 8 carrefours, bande étroite dont les branches sortent
de la zone) : v2 71,7 % / 63,6 % / 4/8, v3 59,6 % / 79,5 % / 2/8 — v3 est plus précis mais s'arrête plus souvent faute de
confiance ; trop petit pour conclure.

À lire avec prudence : une seule carte, une seule zone (1 400 px de galeries, 15 carrefours) ; la « précision » est mesurée
contre une annotation incomplète (le modèle suit vers Port-Mahon une galerie dessinée mais non annotée, comptée comme
fausse) ; les carrefours manqués sont surtout les petits embranchements rapprochés du bd Saint-Jacques. Ce n'est pas encore
un traceur autonome : il sert à proposer, l'humain valide.

### Campagne v4 (deux projets, 2 980 points) — voir `models/COMPARAISON.md`

Six variantes entraînées sur les deux gros projets (`nexus_alkhemia_2011` + `nexus_alkhemia_2011-0202`) avec deux zones de
validation (une par projet) : fenêtres 96 / 128 / 192, 32 / 64 secteurs, avec / sans états sur les traits bleus (étages
inférieurs), deux graines. Résumé : ce sont les **données** qui améliorent le suivi (zone 0202 : couverture au premier
départ 69 → 97 %, carrefours 12 → 15/20 posés à 3 px), pas les hyperparamètres ; le bruit de graine en suivi réel est du
même ordre que les écarts entre variantes ; retirer les états bleus n'apporte rien. Les poids (float16) et une note par
modèle sont dans `models/<nom>/` ; modèle recommandé par défaut : `v4-w128-k32`.

