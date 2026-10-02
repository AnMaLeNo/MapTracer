#!/usr/bin/env python3
"""Serveur de l'application d'annotation : fichiers statiques (sans cache) + API du mode assisté.

    python3 server.py [port] [--model runs/v2/model.pt] [--device cuda|cpu]

Sans --model, l'app fonctionne en mode manuel seulement (l'API répond 503)."""
import argparse, http.server, json, os, sys, threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

ARGS = None
STATE = {'model': None, 'error': None, 'images': {}, 'lock': threading.Lock()}


def get_model():
    if STATE['model'] is None and STATE['error'] is None and ARGS.model:
        try:
            from model import LearnedModel
            STATE['model'] = LearnedModel(ARGS.model, ARGS.device)
        except Exception as e:                      # torch absent, fichier illisible…
            STATE['error'] = f'{type(e).__name__}: {e}'
    return STATE['model']


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
            m = get_model()
            info = {'available': m is not None, 'path': ARGS.model, 'error': STATE['error']}
            if m is not None:
                info.update(device=str(m.device), meta={k: v for k, v in m.meta.items() if k != 'history'})
            return self.reply(200 if m is not None else 503, info)
        return super().do_GET()

    def do_POST(self):
        if self.path.split('?')[0] != '/api/predict':
            return self.reply(404, {'error': 'inconnu'})
        m = get_model()
        if m is None:
            return self.reply(503, {'error': STATE['error'] or 'aucun modèle (lancez server.py --model …)'})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            img = get_image(req['map'])
            from assist import Assistant
            with STATE['lock']:
                a = Assistant(m, img, [tuple(map(float, s)) for s in req.get('segs', [])], thr=float(req.get('thr', 0.5)))
                heading = req.get('heading')
                res = a.propose(float(req['x']), float(req['y']), None if heading is None else float(heading),
                                float(req.get('dist', 32)), bool(req.get('branching')))
            return self.reply(200, res)
        except FileNotFoundError as e:
            return self.reply(404, {'error': f'carte inconnue du serveur : {e}'})
        except Exception as e:
            return self.reply(500, {'error': f'{type(e).__name__}: {e}'})


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('port', nargs='?', type=int, default=8080)
    ap.add_argument('--model', help='model.pt de tools/train.py pour le mode assisté')
    ap.add_argument('--device', help='cuda / cpu')
    ARGS = ap.parse_args()
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(('0.0.0.0', ARGS.port), H) as srv:
        print(f'http://127.0.0.1:{ARGS.port}/app/' + (f'  (modèle : {ARGS.model})' if ARGS.model else '  (mode manuel seul)'))
        srv.serve_forever()
