#!/usr/bin/env python3
"""Serveur de l'application d'annotation : fichiers statiques (sans cache) + API du mode assisté.

    python3 server.py [port] [--models-dir models] [--model runs/v2/model.pt] [--device cuda|mps|cpu]

Les modèles sont les sous-dossiers de --models-dir (défaut : models/ s'il existe) contenant un model.pt ; l'app en
propose la liste et chaque requête /api/predict nomme le modèle voulu (`model`). --model ajoute un fichier isolé.
Sans aucun modèle, l'app fonctionne en mode manuel seulement (l'API répond 503).

Mode Auto : POST /api/trace {map, model, x, y[, heading, graph, max_steps, thr]} lance en arrière-plan la boucle de suivi
complète de tools/trace.py depuis ce point (en prolongeant `graph` s'il est donné) et renvoie {job} ; GET /api/trace/<job>
donne l'avancement et le graphe produit jusque-là ; POST /api/trace/<job>/stop l'interrompt.

Audit des annotations : POST /api/audit {map, model, graphs: [{name, nodes: [{id, x, y, kind, open}], edges: [[a, b]]}][, thr]}
rejoue le modèle sur chaque point annoté (tools/audit.py) en arrière-plan et renvoie {job} ; GET /api/audit/<job> donne
l'avancement puis {anomalies, stats} ; POST /api/audit/<job>/stop l'interrompt."""
import argparse, http.server, importlib, importlib.util, json, os, subprocess, sys, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))

def git_commit():
    """Commit courant du dépôt (pour la provenance des exports), None hors dépôt git."""
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


COMMIT = git_commit()
sys.path.insert(0, os.path.join(ROOT, 'tools'))

ARGS = None
STATE = {'models': {}, 'metas': {}, 'errors': {}, 'images': {}, 'lock': threading.Lock(), 'jobs': {}, 'job_seq': 0}
MAX_JOBS = 8


def tracer_module():
    """tools/trace.py (le module stdlib `trace` porte le même nom : on charge explicitement le fichier si besoin)."""
    T = importlib.import_module('trace')
    if not hasattr(T, 'Tracer'):
        spec = importlib.util.spec_from_file_location('mt_trace', os.path.join(ROOT, 'tools', 'trace.py'))
        T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
    return T


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


STEP_IDLE_S = 3600


def grant_steps(job, n):
    """Pas à pas : accorde n pas (n ≤ 0 = reprise en continu)."""
    with job['cv']:
        if n <= 0:
            job['step'] = False; job['grant'] = 1
        else:
            job['grant'] += n
        job['cv'].notify_all()


def job_view(job):
    return {k: job[k] for k in ('id', 'status', 'model', 'steps', 'branches', 'queue', 'error', 'seed', 'reasons', 'graph')} | \
           {'elapsed_s': round((job.get('t_end') or time.time()) - job['t0'], 1),
            'step': job.get('step', False), 'paused': job.get('paused', False), 'cursor': job.get('cursor')}


def start_trace(req):
    """Lance le suivi complet en arrière-plan ; renvoie le job (dict partagé avec le fil de travail)."""
    m, err, name = get_model(req.get('model'))
    if m is None:
        raise RuntimeError(err)
    img = get_image(req['map'])
    x, y = float(req['x']), float(req['y'])
    heading = req.get('heading')
    STATE['job_seq'] += 1
    job = {'id': STATE['job_seq'], 'status': 'running', 'model': name, 'steps': 0, 'branches': 0, 'queue': 0, 'error': None,
           'seed': [x, y], 'reasons': {}, 'graph': req.get('graph') or {'nodes': [], 'edges': []}, 'stop': False,
           't0': time.time(), 't_snap': 0.0, 't_end': None,
           # pas à pas : le fil de suivi s'arrête après chaque prédiction tant que `grant` (pas accordés via /step) est nul
           'step': bool(req.get('step')), 'grant': 0, 'paused': False, 'cursor': None, 'cv': threading.Condition()}
    for old in sorted(STATE['jobs'])[:-MAX_JOBS + 1]:
        if STATE['jobs'][old]['status'] != 'running':
            del STATE['jobs'][old]
    STATE['jobs'][job['id']] = job
    T = tracer_module()
    import mt_graph as G

    def snapshot(tr):
        job['graph'] = tr.out.to_dict(); job['steps'] = tr.steps; job['branches'] = len(tr.branches); job['queue'] = len(tr.queue)
        job['cursor'] = tr.cursor
        job['reasons'] = {}
        for b in tr.branches:
            job['reasons'][b['reason']] = job['reasons'].get(b['reason'], 0) + 1

    def hook(tr):
        if job['stop']:
            raise T.StopTrace()
        if job['step']:
            snapshot(tr); job['t_snap'] = time.time()
            with job['cv']:
                t_wait = time.time()
                while job['grant'] <= 0 and not job['stop'] and job['step']:
                    job['paused'] = True
                    job['cv'].wait(0.5)
                    if time.time() - t_wait > STEP_IDLE_S:       # pas à pas abandonné : on libère le fil
                        job['stop'] = True
                job['paused'] = False
                job['grant'] -= 1
            if job['stop']:
                raise T.StopTrace()
            return
        if time.time() - job['t_snap'] > 0.5:
            snapshot(tr); job['t_snap'] = time.time()

    def work():
        try:
            mt = m.meta
            tr = T.Tracer(m, mt['step'], mt['sectors'], float(req.get('thr', mt.get('thr', 0.5))), img, mt['window'],
                          trace_width=mt['trace_width'], map_size=img.size, max_steps=int(req.get('max_steps', 20000)), hook=hook)
            if req.get('graph'):
                tr.out = G.Graph.from_dict(req['graph'])
            tr.seed(x, y, None if heading is None else float(heading))
            tr.run()
            snapshot(tr)
            job['status'] = 'stopped' if job['stop'] else ('done' if not tr.queue else 'budget')
        except Exception as e:
            job['status'] = 'error'; job['error'] = f'{type(e).__name__}: {e}'
        job['t_end'] = time.time()

    threading.Thread(target=work, daemon=True).start()
    return job


def audit_view(job):
    return {k: job[k] for k in ('id', 'status', 'model', 'done', 'total', 'error', 'anomalies', 'stats', 'thr')} | \
           {'elapsed_s': round((job.get('t_end') or time.time()) - job['t0'], 1)}


def start_audit(req):
    """Audit en arrière-plan des graphes annotés envoyés par l'app (projet courant ou zones du mode Auto)."""
    m, err, name = get_model(req.get('model'))
    if m is None:
        raise RuntimeError(err)
    img = get_image(req['map'])
    graphs = req.get('graphs') or []
    if not any(gd.get('edges') for gd in graphs):
        raise RuntimeError('rien à vérifier : aucun segment annoté')
    thr = float(req.get('thr', m.meta.get('thr', 0.5)))
    STATE['job_seq'] += 1
    job = {'id': STATE['job_seq'], 'status': 'running', 'model': name, 'done': 0, 'total': 0, 'error': None, 'anomalies': [],
           'stats': {}, 'thr': thr, 'stop': False, 't0': time.time(), 't_end': None}
    STATE['jobs'][job['id']] = job
    import mt_graph as G
    import audit as AU

    def work():
        try:
            base = 0
            for gd in graphs:
                if not gd.get('edges'):
                    continue
                g = G.graph_from_zone(gd)
                off = base

                def hook(done, total):
                    if job['stop']:
                        raise InterruptedError()
                    job['done'], job['total'] = off + done, max(job['total'], off + total)
                an, st = AU.audit_graph(g, img, m, thr=thr, hook=hook, source=gd.get('name', ''))
                job['anomalies'] += an; job['stats'][gd.get('name', '')] = st
                base = job['done']
            job['anomalies'].sort(key=lambda r: -r['score'])
            job['status'] = 'done'
        except InterruptedError:
            job['status'] = 'stopped'
        except Exception as e:
            job['status'] = 'error'; job['error'] = f'{type(e).__name__}: {e}'
        job['t_end'] = time.time()

    threading.Thread(target=work, daemon=True).start()
    return job


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
        path = self.path.split('?')[0]
        if path.startswith('/api/trace/') or path.startswith('/api/audit/'):
            job = STATE['jobs'].get(int(path.split('/')[3]) if path.split('/')[3].isdigit() else None)
            if not job:
                return self.reply(404, {'error': 'tâche inconnue (serveur redémarré ?)'})
            return self.reply(200, audit_view(job) if 'anomalies' in job else job_view(job))
        if path == '/api/model':
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
            return self.reply(200 if ok else 503, {'available': bool(ok), 'models': lst, 'device': device, 'commit': COMMIT,
                                                   'error': None if ok else (lst[0]['error'] if lst else NO_MODEL)})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split('?')[0]
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if path == '/api/trace':
                try:
                    return self.reply(200, job_view(start_trace(req)))
                except RuntimeError as e:
                    return self.reply(503, {'error': str(e)})
            if path == '/api/audit':
                try:
                    return self.reply(200, audit_view(start_audit(req)))
                except RuntimeError as e:
                    return self.reply(503, {'error': str(e)})
            if path.startswith('/api/trace/') and path.endswith('/step'):
                job = STATE['jobs'].get(int(path.split('/')[3]))
                if not job:
                    return self.reply(404, {'error': 'tâche inconnue'})
                if job['status'] != 'running':
                    return self.reply(409, {'error': 'suivi terminé'})
                grant_steps(job, int(req.get('n', 1)))
                return self.reply(200, {'ok': True})
            if path == '/api/wand':
                import magic_wand as WD
                img = get_image(req['map'])
                tols = req.get('tols')
                return self.reply(200, WD.wand(img, float(req['x']), float(req['y']), int(req.get('tol', 32)),
                                               radius=max(32, min(512, int(req.get('radius', 192)))),
                                               tols=[int(t) for t in tols] if tols else None, sweep=bool(req.get('sweep', True)),
                                               near=int(req.get('near', 12))))
            if (path.startswith('/api/trace/') or path.startswith('/api/audit/')) and path.endswith('/stop'):
                job = STATE['jobs'].get(int(path.split('/')[3]))
                if not job:
                    return self.reply(404, {'error': 'tâche inconnue'})
                job['stop'] = True
                return self.reply(200, {'ok': True})
            if path != '/api/predict':
                return self.reply(404, {'error': 'inconnu'})
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
    ap.add_argument('--device', help='cuda / mps / cpu (défaut : cuda, sinon mps sur Mac à puce Apple, sinon cpu)')
    ARGS = ap.parse_args()
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(('0.0.0.0', ARGS.port), H) as srv:
        names = list(list_models())
        print(f'http://127.0.0.1:{ARGS.port}/app/' + (f'  (modèles : {", ".join(names)})' if names else '  (mode manuel seul)'))
        srv.serve_forever()
