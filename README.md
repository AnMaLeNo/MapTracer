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
| Zone déjà cartographiée | clic sur un point existant | **jonction** : relie et termine la branche |
| Poser une intersection | `Maj+clic`, clic droit ou `I` puis clic | le nouveau point est de type intersection |
| Erreur | `Ctrl+Z` | annule le dernier événement (illimité) |
| Changer le type du point courant | `T` | normal ↔ intersection (tant qu'il n'a pas de suite) |
| Fin complète | « Terminer la session » | marque le projet comme achevé |

Un point se pose **le plus loin possible sur la galerie sans que le segment traverse un mur** (virage, changement de
direction, suivi d'une courbe). Par défaut un point hors de la fenêtre est refusé, puisque le modèle ne le verrait pas.

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
    { "t": "advance" }, { "t": "end" }, { "t": "join", "to": 7 }, { "t": "retype", "id": 9, "kind": "intersection" }, { "t": "finish" }
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

## Pistes pour le modèle (hors périmètre de cet outil)

- Tête de régression/heatmap sur un backbone de vision pré-entraîné (ConvNeXt/ViT), entrée = crop + canal « points posés »,
  sortie = heatmap du prochain point + classe (normal / intersection / fin) ; pour les intersections, prédire une heatmap
  multi-pics puis extraire les k maxima.
- Augmentations : rotations par 90°, miroirs (en transformant les coordonnées), variations de la taille de fenêtre.
- Évaluation : distance au point humain, taux de segments qui coupent un mur, rappel des branches aux intersections.
