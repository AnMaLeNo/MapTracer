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

### Boucle de suivi avec faux modèle

```bash
python3 tools/trace.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o trace/ --step 4 [--noise-deg 8 --drop 0.05]
```

`trace.py` est la boucle qui exploitera le modèle appris : pas fixe, suivi du secteur le plus proche du cap, ouverture d'une
branche par secteur latéral confirmé (`--confirm` observations), raccord au tracé existant (jonction, insertion d'un nœud sur
une arête), arrêt quand aucun secteur n'est actif (`--coast` pas tolérés), sortie de carte. Pour l'instant le seul modèle
est l'**oracle** (`--model oracle`), qui lit les directions dans le tracé manuel et peut être dégradé (`--noise-deg`,
`--drop`) pour tester la robustesse de la boucle. Elle écrit `trace_graph.json` (+ `.geojson`), `report.json` (couverture,
précision, intersections retrouvées, raisons de fin des branches) et `debug.png` (bleu = référence, rouge = tracé).

Vérification sur une carte synthétique (`tools/make_synth.py synth.png synth.maptracer.json` : galeries à double trait,
intersections, boucle, jonction, cul-de-sac, texte et trait parasites) : oracle exact → couverture 99,9 %, précision 100 %,
4/4 intersections ; oracle bruité (8°, 5 % de directions oubliées, 5 graines) → couverture 95–100 %, précision 100 %.
Ce sont des tests de **mécanique**, pas une validation du futur modèle : les jonctions créent parfois de courtes arêtes
doublons, et la politique de confiance/rejet d'un modèle appris reste à définir.

## Pistes pour le modèle (hors périmètre de cet outil)

- Encodeur de vision pré-entraîné (ResNet-18/ConvNeXt) à 4 canaux (RGB + canal « déjà tracé »), tête sigmoïde à 32 sorties
  (une par secteur, perte BCE sur les étiquettes douces) ; `end` = aucun secteur au-dessus du seuil.
- Augmentations déjà faites par l'oracle (décalage, erreur de cap) ; en plus, variations de contraste et de taille de fenêtre.
- Validation sur un secteur entier de carte (`--holdout`), métriques de `trace.py` (couverture, précision, intersections) en
  branchant le modèle à la place de l'oracle ; définir le seuil de confiance et la politique de rejet avant tout usage.
