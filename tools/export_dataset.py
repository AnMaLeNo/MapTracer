#!/usr/bin/env python3
"""Transforme un projet Catatrace (JSON exporté par l'app) en jeu d'entraînement.

Pour chaque *décision* (passage sur un point courant), on produit :
  - crops/<n>.png : image carrée de la carte centrée sur le point courant (taille --window, défaut : celle de l'annotation) ;
  - une ligne JSONL avec les points déjà présents dans la fenêtre (coordonnées crop et normalisées), le point précédent,
    le type du point courant et la cible : les points suivants posés (1 pour un point normal, k pour une intersection)
    et l'action terminale (continue / end / join).
Le JSON exporté contient aussi le graphe complet (points, segments) → graph.geojson si la carte est géoréférencée.

Exemple : python3 tools/export_dataset.py mon_projet.catatrace.json maps/nexus_alkhemia_2011.jpg -o dataset/ --window 256
"""
import argparse, json, os
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def replay(events):
    """Reproduit la dérivation de app.js et renvoie la liste des décisions dans l'ordre."""
    pts, children, visited, queue = {}, {}, set(), []
    st = {'cur': None, 'start': None}
    decisions = []          # {point, prev, context_ids, children:[ids], terminal, window}
    open_dec = {}           # id point -> décision en cours

    def add(id_, x, y, kind, parent):
        pts[id_] = {'id': id_, 'x': x, 'y': y, 'kind': kind, 'parent': parent, 'order': len(pts)}
        children[id_] = []

    def visit(id_, window):
        st['cur'] = id_; visited.add(id_)
        d = {'point': id_, 'prev': pts[id_]['parent'], 'context_ids': list(pts), 'children': [],
             'terminal': None, 'window': window}
        decisions.append(d); open_dec[id_] = d

    def advance(window):
        c = st['cur']
        unv = [k for k in children[c] if k not in visited]
        if unv:
            queue.extend(unv[1:]); visit(unv[0], window); return
        if queue:
            visit(queue.pop(0), window); return
        if c != st['start']:
            visit(st['start'], window)

    for ev in events:
        t = ev['t']; w = ev.get('window')
        if t == 'start':
            add(ev['id'], ev['x'], ev['y'], 'start', None); st['start'] = ev['id']; visit(ev['id'], w)
        elif t == 'place':
            add(ev['id'], ev['x'], ev['y'], ev['kind'], ev['from'])
            children[ev['from']].append(ev['id'])
            open_dec[ev['from']]['children'].append(ev['id'])
            if open_dec[ev['from']]['window'] is None:
                open_dec[ev['from']]['window'] = w
            if pts[ev['from']]['kind'] == 'normal':
                open_dec[ev['from']]['terminal'] = 'continue'; visit(ev['id'], w)
        elif t in ('advance', 'end', 'join'):
            d = open_dec[st['cur']]
            d['terminal'] = 'continue' if t == 'advance' else ('end' if t == 'end' else 'join')
            if t == 'join':
                d['join_to'] = ev['to']
            if d['window'] is None:
                d['window'] = w
            advance(w)
        elif t == 'retype':
            pts[ev['id']]['kind'] = ev['kind']
        elif t == 'finish':
            pass
    return pts, decisions


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project'); ap.add_argument('image')
    ap.add_argument('-o', '--out', default='dataset')
    ap.add_argument('--window', type=int, help='taille du crop en px carte (défaut : taille utilisée à l’annotation)')
    ap.add_argument('--size', type=int, help='redimensionner les crops à NxN px (défaut : taille native)')
    ap.add_argument('--skip-incomplete', action='store_true', help='ignorer la décision encore ouverte à la fin')
    a = ap.parse_args()

    proj = json.load(open(a.project, encoding='utf-8'))
    assert proj.get('format') == 'catatrace/1', 'format inattendu'
    pts, decisions = replay(proj['events'])
    img = Image.open(a.image).convert('RGB')
    if proj.get('map') and (img.width, img.height) != (proj['map']['width'], proj['map']['height']):
        raise SystemExit(f"image {img.size} ≠ carte du projet {proj['map']['width']}×{proj['map']['height']}")
    os.makedirs(os.path.join(a.out, 'crops'), exist_ok=True)
    default_w = proj.get('settings', {}).get('window', 256)
    n = 0
    with open(os.path.join(a.out, 'samples.jsonl'), 'w', encoding='utf-8') as f:
        for i, d in enumerate(decisions):
            if d['terminal'] is None and (a.skip_incomplete or not d['children']):
                continue
            w = a.window or d['window'] or default_w
            c = pts[d['point']]; x0, y0 = c['x'] - w / 2, c['y'] - w / 2
            crop = img.crop((round(x0), round(y0), round(x0) + w, round(y0) + w))  # bords hors carte : noirs
            if a.size:
                crop = crop.resize((a.size, a.size), Image.LANCZOS)
            name = f'{i:06d}.png'; crop.save(os.path.join(a.out, 'crops', name))
            inside = lambda p: abs(p['x'] - c['x']) <= w / 2 and abs(p['y'] - c['y']) <= w / 2
            rel = lambda p: {'id': p['id'], 'kind': p['kind'], 'x': p['x'] - x0, 'y': p['y'] - y0,
                             'u': (p['x'] - x0) / w, 'v': (p['y'] - y0) / w}
            ctx = [rel(pts[k]) for k in d['context_ids'] if inside(pts[k])]
            targets = [rel(pts[k]) for k in d['children']]
            row = {
                'sample': i, 'image': f'crops/{name}', 'window': w, 'map_center': [c['x'], c['y']],
                'current': rel(c), 'current_kind': c['kind'],
                'previous': rel(pts[d['prev']]) if d['prev'] is not None and inside(pts[d['prev']]) else None,
                'context': ctx, 'targets': targets,
                'terminal': d['terminal'] or 'open',
                'join_to': rel(pts[d['join_to']]) if d.get('join_to') is not None else None,
                'n_targets': len(targets),
            }
            f.write(json.dumps(row, ensure_ascii=False) + '\n'); n += 1
    print(f'{n} échantillons → {a.out}/samples.jsonl, crops dans {a.out}/crops/')

    g = (proj.get('map') or {}).get('georef')
    if g:
        feats = []
        for e in proj.get('derived', {}).get('edges', []):
            p, q = pts[e['from']], pts[e['to']]
            ll = lambda p: [g['lon'][0] * p['x'] + g['lon'][1], g['lat'][0] * p['y'] + g['lat'][1]]
            feats.append({'type': 'Feature', 'properties': {'kind': e['kind']},
                          'geometry': {'type': 'LineString', 'coordinates': [ll(p), ll(q)]}})
        for p in pts.values():
            feats.append({'type': 'Feature', 'properties': {'kind': p['kind'], 'order': p['order']},
                          'geometry': {'type': 'Point', 'coordinates': ll(p)}})
        json.dump({'type': 'FeatureCollection', 'features': feats}, open(os.path.join(a.out, 'graph.geojson'), 'w'))
        print(f"graphe géoréférencé → {a.out}/graph.geojson ({len(feats)} entités)")


if __name__ == '__main__':
    main()
