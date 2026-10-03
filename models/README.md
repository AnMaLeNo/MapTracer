# Modèles livrés

Un sous-dossier par modèle :

```
models/<nom>/model.pt     poids (float16, ~22 Mo) + métadonnées : sectors, window, step, lookahead, trace_width, val, epoch, args…
models/<nom>/NOTES.md     stratégie, jeu d'entraînement, résultats (validation + suivi réel), limites, idées
```

`server.py` liste ces dossiers (`/api/model`), l'app les propose dans le menu « Modèle » et chaque requête `/api/predict`
nomme celui qu'elle veut. Le serveur lit le pas, la fenêtre et le nombre de secteurs dans le `.pt` : rien à régler côté
app quand on change de modèle.

Ajouter un modèle entraîné avec `tools/train.py` :

```bash
python3 tools/model.py runs/mon_run/model.pt models/mon_modele/model.pt --half   # copie en float16
$EDITOR models/mon_modele/NOTES.md                                               # 1re ligne = titre affiché dans l'app
```

La comparaison entre modèles est dans [COMPARAISON.md](COMPARAISON.md).
