#!/usr/bin/env python3
"""Serveur de l'application d'annotation : fichiers statiques (sans cache) + API du mode assisté.

    python3 server.py [port] [--models-dir models] [--model runs/v2/model.pt] [--device cuda|cpu]

Les modèles sont les sous-dossiers de --models-dir (défaut : models/ s'il existe) contenant un model.pt ; l'app en
propose la liste et chaque requête /api/predict nomme le modèle voulu (`model`). --model ajoute un fichier isolé.
Sans aucun modèle, l'app fonctionne en mode manuel seulement (l'API répond 503)."""
import argparse, http.server, json, os, sys, threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

ARGS = None
STATE = {'models': {}, 'metas': {}, 'errors': {}, 'images': {}, 'lock': threading.Lock()}


def list_models():
    """{nom: chemin du .pt} — sous-dossiers de --models-dir contenant model.pt, puis --model (nom = dossier du fichier)."""
    out = {}
    d = ARGS.models_dir if ARGS.models_dir else (os.path.join(ROOT, 'models') if os.path.isdir(os.path.join(ROOT, 'models')) else None)
    if d and os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            pt = os.path.join(d, name, 'model.pt')
            if os.path.isfile(pt):
                out[name] = pt
    if ARGS.model:
        out[os.path.basename(os.path.dirname(os.path.abspath(ARGS.model))) or 'model'] = ARGS.model
    return out


def model_notes(pt):
    """Première ligne non vide de NOTES.md à côté du .pt (titre du modèle), ou None."""
    md = os.path.join(os.path.dirname(pt), 'NOTES.md')
    if os.path.isfile(md):
        for line in open(md, encoding='utf-8'):
            if line.strip():
                return line.strip().lstrip('# ').strip()
    return None


NO_MODEL = 'aucun modèle (dossier models/ vide ou lancez server.py --model …)'


def get_model(name=None):
    """(modèle chargé, erreur, nom) — `name` inconnu ou absent → premier modèle de la liste."""
    models = list_models()
    if not models:
        return None, NO_MODEL, None
    name = name if name in models else next(iter(models))
    if name not in STATE['models'] and name not in STATE['errors']:
        try:
            from model import LearnedModel
            STATE['models'][name] = LearnedModel(models[name], ARGS.device)
            STATE['metas'][name] = STATE['models'][name].meta
        except Exception as e:                      # torch absent, fichier illisible…
            STATE['errors'][name] = f'{type(e).__name__}: {e}'
    return STATE['models'].get(name), STATE['errors'].get(name), name


def get_meta(name, pt):
    """Métadonnées d'un .pt sans charger le réseau (mises en cache)."""
    if name not in STATE['metas'] and name not in STATE['errors']:
        try:
            import torch
            STATE['metas'][name] = torch.load(pt, map_location='cpu', weights_only=False)['meta']
        except Exception as e:
            STATE['errors'][name] = f'{type(e).__name__}: {e}'
    return STATE['metas'].get(name)


def get_image(rel):
    rel = rel.lstrip('./')
    path = os.path.normpath(os.path.join(ROOT, rel))
    if not path.startswith(ROOT + os.sep) or not os.path.isfile(path):
        raise FileNotFoundError(rel)
    if path not in STATE['images']:
        from PIL import Image
        STATE['images'][path] = Image.open(path).convert('RGB')
    return STATE['images'][path]


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?')[0] == '/api/model':
            lst = []
            for name, pt in list_models().items():
                meta = get_meta(name, pt)
                lst.append({'name': name, 'path': os.path.relpath(pt, ROOT), 'title': model_notes(pt), 'error': STATE['errors'].get(name),
                            'meta': meta and {k: meta[k] for k in ('sectors', 'window', 'step', 'lookahead', 'val', 'epoch') if k in meta}})
            ok = [m for m in lst if not m['error']]
            device = None
            if ok:
                m, _, _ = get_model(ok[0]['name'])
                device = str(m.device) if m else None
            return self.reply(200 if ok else 503, {'available': bool(ok), 'models': lst, 'device': device,
                                                   'error': None if ok else (lst[0]['error'] if lst else NO_MODEL)})
        return super().do_GET()

    def do_POST(self):
        if self.path.split('?')[0] != '/api/predict':
            return self.reply(404, {'error': 'inconnu'})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            m, err, name = get_model(req.get('model'))
            if m is None:
                return self.reply(503, {'error': err})
            img = get_image(req['map'])
            from assist import Assistant
            with STATE['lock']:
                a = Assistant(m, img, [tuple(map(float, s)) for s in req.get('segs', [])], thr=float(req.get('thr', 0.5)))
                heading = req.get('heading')
                res = a.propose(float(req['x']), float(req['y']), None if heading is None else float(heading),
                                float(req.get('dist', 32)), bool(req.get('branching')))
            res['model'] = name
            return self.reply(200, res)
        except FileNotFoundError as e:
            return self.reply(404, {'error': f'carte inconnue du serveur : {e}'})
        except Exception as e:
            return self.reply(500, {'error': f'{type(e).__name__}: {e}'})


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('port', nargs='?', type=int, default=8080)
    ap.add_argument('--models-dir', help='dossier de modèles (un sous-dossier par modèle, avec model.pt ; défaut : models/)')
    ap.add_argument('--model', help='model.pt isolé de tools/train.py, ajouté à la liste')
    ap.add_argument('--device', help='cuda / cpu')
    ARGS = ap.parse_args()
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(('0.0.0.0', ARGS.port), H) as srv:
        names = list(list_models())
        print(f'http://127.0.0.1:{ARGS.port}/app/' + (f'  (modèles : {", ".join(names)})' if names else '  (mode manuel seul)'))
        srv.serve_forever()
