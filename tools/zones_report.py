#!/usr/bin/env python3
"""Rapport sur un fichier de zones corrigées (maptracer-zones/1, mode Auto de l'app) : pour chaque zone, ce que le
modèle avait tracé (`zone.auto`) face à ce que l'humain a annoté (`nodes`/`edges`), avec une image par zone.

Usage : python3 tools/zones_report.py zones.mapzones.json maps/carte.jpg -o rapport/ [--tol 3] [--scale 4]

Pour chaque zone : longueur des deux graphes, carrefours du modèle vs annotés (appariés à --inter-tol px), couverture de
l'annotation par le tracé du modèle (part de l'annotation à moins de --tol px du tracé), part du tracé du modèle qui
longe l'annotation, culs-de-sac annotés, extrémités ouvertes. Écrit rapport/README.md, rapport/zones.json et
rapport/zone_<id>.png (carte ×scale, rouge = modèle, bleu = humain, orange = carrefour, croix = cul-de-sac, pointillé =
extrémité ouverte). Informatif : sert à comprendre quelles erreurs les mini-datasets corrigent, pas à entraîner.
"""
import argparse, json, math, os

from PIL import Image, ImageDraw


def seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def segments(g):
    pos = {n['id']: (n['x'], n['y']) for n in g['nodes']}
    return [(pos[a], pos[b]) for a, b in g['edges'] if a in pos and b in pos]


def samples(segs, every=1.0):
    pts = []
    for (ax, ay), (bx, by) in segs:
        L = math.hypot(bx - ax, by - ay)
        k = max(1, int(L / every))
        pts += [(ax + (bx - ax) * i / k, ay + (by - ay) * i / k) for i in range(k + 1)]
    return pts


def near_fraction(pts, segs, tol):
    if not pts:
        return None
    ok = sum(1 for x, y in pts if segs and min(seg_dist(x, y, ax, ay, bx, by) for (ax, ay), (bx, by) in segs) <= tol)
    return ok / len(pts)


def degrees(g):
    d = {}
    for a, b in g['edges']:
        d[a] = d.get(a, 0) + 1; d[b] = d.get(b, 0) + 1
    return d


def zone_stats(z, tol, inter_tol):
    human, model = {'nodes': z['nodes'], 'edges': z['edges']}, z.get('auto') or {'nodes': [], 'edges': []}
    hs, ms = segments(human), segments(model)
    deg = degrees(human)
    h_inter = [(n['x'], n['y']) for n in human['nodes'] if n['kind'] == 'intersection']
    m_inter = [(n['x'], n['y']) for n in model['nodes'] if n['kind'] == 'intersection']
    matched = sum(1 for x, y in h_inter if any(math.hypot(x - u, y - v) <= inter_tol for u, v in m_inter))
    return {
        'id': z['id'], 'bbox': z['bbox'], 'model': z.get('model'), 'edits': z.get('edits'),
        'human_len_px': round(sum(math.dist(a, b) for a, b in hs), 1), 'model_len_px': round(sum(math.dist(a, b) for a, b in ms), 1),
        'human_nodes': len(human['nodes']), 'human_intersections': len(h_inter), 'model_intersections': len(m_inter),
        'intersections_found_by_model': matched,
        'ends': sum(1 for n in human['nodes'] if n['kind'] == 'end'),
        'open_ends': sum(1 for n in human['nodes'] if n['kind'] != 'end' and deg.get(n['id'], 0) <= 1),
        'coverage_of_human_by_model': near_fraction(samples(hs), ms, tol),
        'model_on_human': near_fraction(samples(ms), hs, tol),
    }


def render(img, z, path, scale, margin=24):
    x0, y0, x1, y1 = z['bbox']
    box = (int(x0 - margin), int(y0 - margin), int(math.ceil(x1 + margin)), int(math.ceil(y1 + margin)))
    crop = img.crop(box).resize(((box[2] - box[0]) * scale, (box[3] - box[1]) * scale), Image.LANCZOS)
    d = ImageDraw.Draw(crop)
    T = lambda x, y: ((x - box[0]) * scale, (y - box[1]) * scale)
    d.rectangle([*T(x0, y0), *T(x1, y1)], outline=(255, 209, 102), width=2)
    for g, col, w in ((z.get('auto') or {'nodes': [], 'edges': []}, (255, 77, 77), 2), ({'nodes': z['nodes'], 'edges': z['edges']}, (78, 161, 255), 3)):
        for a, b in segments(g):
            d.line([*T(*a), *T(*b)], fill=col, width=w)
        deg = degrees(g)
        for n in g['nodes']:
            x, y = T(n['x'], n['y']); r = 3 if col[2] == 77 else 5
            if n['kind'] == 'intersection':
                d.ellipse([x - r * 2, y - r * 2, x + r * 2, y + r * 2], outline=(255, 122, 26), width=3)
            elif n['kind'] == 'end':
                d.line([x - r * 2, y - r * 2, x + r * 2, y + r * 2], fill=(255, 255, 255), width=2)
                d.line([x + r * 2, y - r * 2, x - r * 2, y + r * 2], fill=(255, 255, 255), width=2)
            elif col[2] == 255 and deg.get(n['id'], 0) <= 1:
                for k in range(0, 360, 45):
                    d.arc([x - r * 2, y - r * 2, x + r * 2, y + r * 2], k, k + 22, fill=(255, 255, 255), width=2)
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    crop.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('zones'); ap.add_argument('image')
    ap.add_argument('-o', '--out', default='zones_report')
    ap.add_argument('--tol', type=float, default=3.0, help='distance (px) pour « longe l’annotation »')
    ap.add_argument('--inter-tol', type=float, default=10.0, help='distance (px) d’appariement des carrefours')
    ap.add_argument('--scale', type=int, default=4)
    a = ap.parse_args()
    d = json.load(open(a.zones, encoding='utf-8'))
    if d.get('format') != 'maptracer-zones/1':
        raise SystemExit('pas un fichier maptracer-zones/1')
    img = Image.open(a.image).convert('RGB')
    os.makedirs(a.out, exist_ok=True)
    prov = d.get('provenance') or {}
    rows = []
    for z in d.get('zones', []):
        st = zone_stats(z, a.tol, a.inter_tol)
        st['image'] = f'zone_{z["id"]}.png'
        render(img, z, os.path.join(a.out, st['image']), a.scale)
        rows.append(st)
    pct = lambda v: '—' if v is None else f'{100 * v:.0f} %'
    lines = [f'# Zones corrigées : {os.path.basename(a.zones)}', '',
             f"Carte `{(d.get('map') or {}).get('id')}` · exporté {d.get('exported', '?')} · modèle(s) "
             f"{', '.join(sorted({str(r['model']) for r in rows})) or '?'} · mode {prov.get('mode', '?')} · app {((prov.get('app') or {}).get('commit')) or '?'} · "
             f"{len(d.get('seeds', []))} départ(s) · tracé complet du modèle : {len((d.get('trace') or {}).get('nodes', []))} points", '',
             f'Couverture = part de l’annotation humaine à moins de {a.tol:g} px du tracé du modèle (ce qu’il avait trouvé) ; '
             f'« modèle sur annotation » = part de son tracé qui longe l’annotation (le reste est faux ou non annoté). '
             f'Carrefours retrouvés = carrefours annotés avec un carrefour du modèle à moins de {a.inter_tol:g} px.', '',
             '| zone | taille | annoté (px / pts / carrefours) | modèle (px / carrefours) | carrefours retrouvés | couverture | modèle sur annotation | culs-de-sac | ouvertes | image |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        b = r['bbox']
        lines.append(f"| {r['id']} | {b[2] - b[0]:.0f}×{b[3] - b[1]:.0f} | {r['human_len_px']:.0f} / {r['human_nodes']} / {r['human_intersections']} | "
                     f"{r['model_len_px']:.0f} / {r['model_intersections']} | {r['intersections_found_by_model']}/{r['human_intersections']} | "
                     f"{pct(r['coverage_of_human_by_model'])} | {pct(r['model_on_human'])} | {r['ends']} | {r['open_ends']} | ![]({r['image']}) |")
    open(os.path.join(a.out, 'README.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    json.dump({'source': os.path.basename(a.zones), 'provenance': prov, 'zones': rows}, open(os.path.join(a.out, 'zones.json'), 'w'), indent=1)
    print('\n'.join(lines[6:]))


if __name__ == '__main__':
    main()
