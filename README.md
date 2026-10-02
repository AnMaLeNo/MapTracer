# MapTracer

Outil d'annotation pour vectoriser une carte de galeries (catacombes de Paris, Nexus 2011…) **pas à pas**, et produire le
jeu de données qui servira à entraîner un modèle de suivi de galeries assisté par IA.

Principe : plutôt que de vectoriser toute la carte d'un coup, on suit une galerie point après point. À chaque étape le
modèle (ou, pour l'instant, l'humain) ne voit qu'une **fenêtre carrée** de la carte centrée sur le point courant, avec les
points déjà posés, et doit décider du **prochain point**. Chaque clic humain devient un exemple d'entraînement.

## Lancer l'application

```bash
python3 server.py            # http://127.0.0.1:8080/app/
```

Aucune dépendance : HTML/JS pur. La carte Nexus 2011 (6307 px, géoréférencée) est fournie dans `maps/` ; toute autre image
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
- **Déplacement** : toujours du même **pas fixe** (`--step`, 4 px ≈ 2 m sur Nexus), aucune largeur à estimer.

### Génération des exemples

```bash
python3 tools/oracle.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o oracle/ --window 128 --step 4 \
        [--aug 2 --offset 3 --heading-noise 25 --holdout x0,y0,x1,y1]
```

Pour chaque arête du graphe, dans les deux sens, une position tous les `--spacing` px (défaut = pas), dupliquée `--aug`
fois avec un décalage latéral (`--offset`) et une erreur de cap (`--heading-noise`) pour apprendre le recentrage. La cible
est l'ensemble des secteurs contenant un point de l'axe à `--lookahead` px (défaut 4 × pas) le long du graphe, une branche =
un secteur (étiquettes douces gaussiennes dans `label`, secteurs entiers dans `sectors`). Le canal « déjà tracé » contient
l'arête derrière la position, parfois d'autres arêtes déjà explorées (le modèle doit savoir ne pas repartir dessus).
Sortie : `map/NNNNNN.png`, `trace/NNNNNN.png`, `samples.jsonl` (+ `samples_val.jsonl` si `--holdout`, découpage **spatial**),
`meta.json`, `graph.json`.

Une extrémité de degré 1 **sans** événement `end` (amorce encore en file d'attente, point de départ) n'est pas un
cul-de-sac : la galerie continue probablement. Les états dont la visée atteint une telle extrémité sont **ignorés** (compteur
`skipped_open`) plutôt que d'enseigner une fausse fin.

### Boucle de suivi avec faux modèle

```bash
python3 tools/trace.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o trace/ --step 4 [--noise-deg 8 --drop 0.05]
```

`trace.py` est la boucle qui exploitera le modèle appris : pas fixe, suivi du secteur le plus proche du cap, ouverture d'une
branche par secteur latéral confirmé (`--confirm` observations), raccord au tracé existant (jonction, insertion d'un nœud sur
une arête), arrêt quand aucun secteur n'est actif (`--coast` pas tolérés), sortie de carte. Pour l'instant le seul modèle
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

### Premier résultat (Nexus 2011, 1 138 points annotés, zone de validation sud `4200,3200,5800,3600`)

Entraînement sur RTX 3080 : 10 263 exemples, 30 époques (3,6 s/époque). Validation (exemples) : précision des directions
98 %, rappel 90 %, erreur angulaire 2,5°, cul-de-sac 70 %, rappel aux intersections 67 %. Suivi réel avec `trace.py
--bbox … --seed auto` (un départ par composante de la référence), tolérance 6 px :

| modèle | couverture | précision | intersections |
|---|---|---|---|
| oracle (borne haute de la mécanique) | 100 % | 98,5 % | 15/15 |
| ResNet-18 v2 | 93,8 % | 86,0 % | 8/15 |

À lire avec prudence : une seule carte, une seule zone (1 400 px de galeries, 15 carrefours) ; la « précision » est mesurée
contre une annotation incomplète (le modèle suit vers Port-Mahon une galerie dessinée mais non annotée, comptée comme
fausse) ; les carrefours manqués sont surtout les petits embranchements rapprochés du bd Saint-Jacques. Ce n'est pas encore
un traceur autonome : il sert à proposer, l'humain valide.

