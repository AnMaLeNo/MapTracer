"""Baguette magique : remplissage flou (flood fill à tolérance de couleur) du « vide » d'une galerie depuis un point.

Preuve de concept. L'idée : sur Nexus une galerie est du blanc entre deux traits ; en partant d'un point posé et en montant la
tolérance, la sélection épouse la galerie (et ses carrefours) jusqu'au moment où elle « déborde » par un trait interrompu ou un
fond de même teinte. On renvoie la sélection, ses statistiques de forme, le balayage aire(tolérance) et un centre suggéré
(maximum de la transformée de distance près du point). Rien ici n'est une vérité terrain : c'est de l'information à regarder.
"""
import base64
import io

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

DEFAULT_TOLS = list(range(0, 129, 4))


def window(img, x, y, radius):
    """Sous-image RGB (uint8) de côté 2·radius autour de (x, y), coin (ox, oy) et coordonnées du point dedans."""
    W, H = img.size
    x0, y0 = max(0, int(round(x)) - radius), max(0, int(round(y)) - radius)
    x1, y1 = min(W, int(round(x)) + radius), min(H, int(round(y)) + radius)
    sub = np.asarray(img.convert('RGB').crop((x0, y0, x1, y1)), dtype=np.int16)
    return sub, (x0, y0), (int(round(x)) - x0, int(round(y)) - y0)


def reference(sub, sx, sy, half=3, far=40):
    """Couleur de référence : le pixel cliqué (comme la baguette de Photoshop), sauf s'il tombe sur un trait — alors le ton clair
    dominant du voisinage (2·half+1)² (90e centile par canal), puisque la galerie est le vide clair entre deux traits."""
    seed = sub[sy, sx].astype(float)
    patch = sub[max(0, sy - half):sy + half + 1, max(0, sx - half):sx + half + 1].reshape(-1, 3)
    light = np.percentile(patch, 90, axis=0)
    return seed if np.abs(seed - light).max() <= far else light


def candidates(sub, ref, tol):
    """Pixels dont chaque canal est à ≤ tol de la référence (tolérance « Photoshop », distance de Chebyshev)."""
    return np.abs(sub - ref[None, None, :]).max(axis=2) <= tol


def component(ok, sx, sy, snap=8):
    """Composante 4-connexe de `ok` contenant le point (ou le pixel acceptable le plus proche à ≤ snap px). (masque, (sx, sy) utilisés)."""
    if not ok[sy, sx]:
        if not ok.any():
            return np.zeros_like(ok), None
        _, idx = ndi.distance_transform_edt(~ok, return_indices=True)
        ny, nx = int(idx[0, sy, sx]), int(idx[1, sy, sx])
        if abs(nx - sx) > snap or abs(ny - sy) > snap:
            return np.zeros_like(ok), None
        sx, sy = nx, ny
    lab, _ = ndi.label(ok)                                   # structure par défaut = 4-connexité : un trait fin diagonal bloque
    return lab == lab[sy, sx], (sx, sy)


def light_stats(mask):
    area = int(mask.sum())
    if not area:
        return {'area': 0, 'bbox': None, 'border': False, 'fill': 0.0, 'width': 0.0}
    ys, xs = np.nonzero(mask)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    border = bool(xs.min() == 0 or ys.min() == 0 or xs.max() == mask.shape[1] - 1 or ys.max() == mask.shape[0] - 1)
    perim = int((mask & ~ndi.binary_erosion(mask)).sum())
    return {'area': area, 'bbox': bbox, 'border': border,
            'fill': round(area / ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])), 3),
            'perimeter': perim,
            'width': round(2.0 * area / max(1, perim), 1)}  # bande de largeur w et longueur L : aire L·w, périmètre ≈ 2L


def shape_stats(mask, sx, sy, near=12):
    """Statistiques complètes : + allongement (ACP des pixels), demi-largeur au point, centre suggéré (max de distance près du point)."""
    st = light_stats(mask)
    if not st['area']:
        return st
    ys, xs = np.nonzero(mask)
    pts = np.stack([xs, ys], 1).astype(float)
    cov = np.cov(pts.T) if len(pts) > 2 else np.eye(2)
    ev = np.sort(np.linalg.eigvalsh(cov))[::-1]
    st['elong'] = round(float(np.sqrt(ev[0] / max(ev[1], 1e-6))), 2)
    D = ndi.distance_transform_edt(mask)
    st['half_width_at_seed'] = round(float(D[sy, sx]), 1)
    y0, y1 = max(0, sy - near), min(mask.shape[0], sy + near + 1)
    x0, x1 = max(0, sx - near), min(mask.shape[1], sx + near + 1)
    loc = D[y0:y1, x0:x1]
    iy, ix = np.unravel_index(int(np.argmax(loc)), loc.shape)
    st['center'] = [int(x0 + ix), int(y0 + iy), round(float(loc[iy, ix]), 1)]
    st['n_components_holes'] = int(ndi.label(~mask)[1] - 1)   # trous (piliers, lettres…) : composantes du complément moins l'extérieur
    return st


CROSS = ndi.generate_binary_structure(2, 1)


def _width(mask):
    """Largeur moyenne d'une bande : 2·aire/périmètre (bande de largeur w et longueur L : aire L·w, périmètre ≈ 2L)."""
    a = int(mask.sum())
    return 2.0 * a / max(1, int((mask & ~ndi.binary_erosion(mask)).sum())) if a else 0.0


def leaks(prev, new, max_neck=3, width_ratio=2.5, min_area=200, rel_area=0.3):
    """Fuites entre deux crans de tolérance. `new` = pixels gagnés ; chaque région nouvelle (4-connexe) est reliée à l'ancienne
    sélection par ses pixels de contact. Une région est une fuite si elle entre par un goulot (plus grand contact connexe)
    de ≤ max_neck px et qu'elle est ≥ width_ratio fois plus large que l'ancienne sélection : l'eau s'engouffre par un pixel
    clair du trait et inonde une zone qui ne ressemble pas à la galerie suivie. Une vraie branche, même fine, garde une largeur
    comparable ; une salle qui s'ouvre largement n'a pas de goulot (→ pas bouchée, c'est le bond d'aire qui l'arrête).
    Retourne [(pixels de contact à boucher, infos)]. Heuristique."""
    a_prev = int(prev.sum())
    if not a_prev:
        return []
    w_prev = max(_width(prev), 1.5)
    lab, n = ndi.label(new)
    reach = ndi.binary_dilation(prev, structure=CROSS)
    out = []
    for k in range(1, n + 1):
        reg = lab == k
        a = int(reg.sum())
        if a < min_area and a < rel_area * a_prev:
            continue
        contact = reg & reach
        clab, cn = ndi.label(contact, structure=np.ones((3, 3)))
        if not cn:
            continue
        neck = int(max(ndi.sum(contact, clab, range(1, cn + 1))))
        w = _width(reg)
        if neck <= max_neck and w > width_ratio * w_prev:
            ys, xs = np.nonzero(contact)
            out.append((contact, {'contact': int(contact.sum()), 'necks': int(cn), 'neck': neck, 'area': a,
                                  'width': round(w, 1), 'width_prev': round(w_prev, 1), 'x': int(xs.mean()), 'y': int(ys.mean())}))
    return out


def sweep(sub, ref, sx, sy, tols, plug=True, factor=2.5, min_tol=8, min_area=30, porous_px=8):
    """Balayage incrémental des tolérances. À chaque cran : remplissage, puis (si plug) détection des fuites par rapport au cran
    précédent ; leurs pixels de contact sont interdits pour ce cran et tous les suivants (le trou est « bouché »), et le
    remplissage est refait. Arrêt proposé (`stop`) au premier cran, après un palier (croissance < 1,3), où soit l'aire bondit
    ×factor en s'élargissant (largeur ×1,5) ou en couvrant ≥ ¼ de la fenêtre (`overflow` : débordement large, sans goulot —
    une galerie fine qui « file » le long de son tracé bondit en aire sans s'élargir et n'est pas un débordement), soit
    ≥ porous_px pixels de goulots alimentant ≥ 2× l'aire courante ont dû être bouchés d'un coup (`porous` : le trait entier
    devient transparent, il n'y a plus de mur à boucher). `proposed` = cran précédent.
    Retourne masks (par tol), rows (courbe), plugs (bouchons, coordonnées fenêtre), stop."""
    forb = np.zeros(sub.shape[:2], bool)
    prev, a_prev, t_prev = None, 0, None
    rows, plugs, masks, stop, stable = [], [], {}, None, False
    for t in tols:
        ok = candidates(sub, ref, t) & ~forb
        m, _ = component(ok, sx, sy)
        step = []
        if plug and prev is not None and a_prev >= min_area and t >= min_tol:
            for _ in range(8):
                found = leaks(prev, m & ~prev)
                if not found:
                    break
                for c, info in found:
                    forb |= c
                    ys, xs = np.nonzero(c)
                    step.append(dict(tol=t, pixels=[[int(x), int(y)] for x, y in zip(xs, ys)], **info))
                m, _ = component(ok & ~forb, sx, sy)
        a = int(m.sum())
        r = a / max(a_prev, 1)
        w_prev = light_stats(prev)['width'] if prev is not None else 0.0
        if prev is not None and t >= min_tol and a_prev >= min_area and r < 1.3:
            stable = True
        ls = light_stats(m)
        if stop is None and stable:
            n_px, a_plug = sum(p['contact'] for p in step), sum(p['area'] for p in step)
            if n_px >= porous_px and a_plug >= 2 * a_prev:
                stop = {'tol': t, 'before': t_prev, 'reason': 'porous', 'plugged_px': n_px, 'plugged_area': a_plug}
            elif r > factor and (ls['width'] > 1.5 * w_prev or a >= 0.25 * m.size):
                stop = {'tol': t, 'before': t_prev, 'reason': 'overflow', 'ratio': round(r, 1),
                        'width_ratio': round(ls['width'] / max(w_prev, 0.1), 1), 'window_frac': round(a / m.size, 2)}
        rows.append({'tol': t, 'area': a, 'border': ls['border'], 'width': ls['width'], 'fill': ls['fill'], 'plugs': len(step),
                     'plugged_px': sum(p['contact'] for p in step)})
        plugs += step
        masks[t] = m
        prev, a_prev, t_prev = m, a, t
    return masks, rows, plugs, stop


_CACHE = {}


def analyze(img, x, y, radius, tols, plug=True):
    """Fenêtre + référence + balayage, mémorisés par (image, point, rayon, crans, plug) : le curseur de tolérance ne recalcule rien."""
    key = (id(img), float(x), float(y), int(radius), tuple(tols), bool(plug))
    if key in _CACHE:
        return _CACHE[key]
    sub, (ox, oy), (sx, sy) = window(img, x, y, radius)
    ref = reference(sub, sx, sy)
    masks, rows, plugs, stop = sweep(sub, ref, sx, sy, tols, plug=plug)
    S = {'sub': sub, 'ref': ref, 'sx': sx, 'sy': sy, 'ox': ox, 'oy': oy, 'tols': list(tols),
         'masks': masks, 'rows': rows, 'plugs': plugs, 'stop': stop}
    while len(_CACHE) >= 12:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = S
    return S


def mask_at(S, tol):
    """Masque à une tolérance quelconque : celui du balayage si elle en fait partie, sinon remplissage avec les bouchons posés
    jusqu'au cran inférieur."""
    if tol in S['masks']:
        return S['masks'][tol]
    forb = np.zeros(S['sub'].shape[:2], bool)
    for p in S['plugs']:
        if p['tol'] <= tol:
            for px, py in p['pixels']:
                forb[py, px] = True
    m, _ = component(candidates(S['sub'], S['ref'], tol) & ~forb, S['sx'], S['sy'])
    return m


def png_mask(mask, rgb=(0, 200, 255)):
    rgba = np.zeros(mask.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = rgb
    rgba[..., 3] = mask.astype(np.uint8) * 255
    buf = io.BytesIO()
    Image.fromarray(rgba, 'RGBA').save(buf, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def wand(img, x, y, tol, radius=256, tols=None, sweep=True, near=12, plug=True):
    tols = list(tols or DEFAULT_TOLS)
    S = analyze(img, x, y, radius, tols, plug=plug)
    sub, ref, sx, sy, ox, oy = S['sub'], S['ref'], S['sx'], S['sy'], S['ox'], S['oy']
    res = {'x': x, 'y': y, 'tol': tol, 'radius': radius, 'plug': bool(plug), 'origin': [ox, oy],
           'size': [sub.shape[1], sub.shape[0]], 'ref': [int(v) for v in ref], 'seed_px': [int(v) for v in sub[sy, sx]]}
    mask = mask_at(S, tol)
    used = (sx, sy) if mask[sy, sx] else None
    if used is None and mask.any():
        ys, xs = np.nonzero(mask)
        i = int(np.argmin((xs - sx) ** 2 + (ys - sy) ** 2))
        used = (int(xs[i]), int(ys[i]))
    res['seed_used'] = None if used is None else [ox + used[0], oy + used[1]]
    st = shape_stats(mask, *used, near=near) if used else light_stats(mask)
    if st.get('bbox'):
        st['bbox'] = [st['bbox'][0] + ox, st['bbox'][1] + oy, st['bbox'][2] + ox, st['bbox'][3] + oy]
    if st.get('center'):
        st['center'] = [st['center'][0] + ox, st['center'][1] + oy, st['center'][2]]
    res['stats'] = st
    res['mask'] = png_mask(mask) if st['area'] else None
    res['sweep'] = S['rows']
    res['plugs'] = [{k: v for k, v in p.items() if k != 'pixels'} | {'x': ox + p['x'], 'y': oy + p['y'],
                     'pixels': [[ox + px, oy + py] for px, py in p['pixels']]} for p in S['plugs']]
    stop = S['stop']
    res['stop'] = stop
    res['proposed'], res['jump'] = (stop['before'], stop['tol']) if stop else (None, None)
    return res


def report_png(img, res, S_tols=(None, None, None), path=None):
    """Planche de contrôle : fenêtre brute, puis sélection à 3 tolérances (bouchons en rouge). Pour rejouer un exemple."""
    S = analyze(img, res['x'], res['y'], res['radius'], DEFAULT_TOLS, plug=res['plug'])
    sub8 = np.clip(np.asarray(S['sub']), 0, 255).astype(np.uint8)
    tiles = [sub8]
    for t in S_tols:
        if t is None:
            continue
        rgb = sub8.astype(float)
        m = mask_at(S, t)
        rgb[m] = 0.4 * rgb[m] + 0.6 * np.array((0, 200, 255))
        for p in S['plugs']:
            if p['tol'] <= t:
                rgb[max(0, p['y'] - 2):p['y'] + 3, max(0, p['x'] - 2):p['x'] + 3] = (255, 0, 0)
        tiles.append(rgb.astype(np.uint8))
    im = Image.fromarray(np.concatenate(tiles, 1))
    if path:
        im.save(path)
    return im


if __name__ == '__main__':
    import argparse, json, sys
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image'); ap.add_argument('x', type=float); ap.add_argument('y', type=float)
    ap.add_argument('--tol', type=int, default=32); ap.add_argument('--radius', type=int, default=192)
    ap.add_argument('--no-plug', action='store_true', help='sans bouchage des fuites (comportement brut)')
    ap.add_argument('--png', help='écrit le masque PNG ici')
    ap.add_argument('--report', help='planche PNG : fenêtre, sélection à --tol, à la tolérance proposée, au cran du débordement')
    ap.add_argument('--steps', action='store_true', help='affiche la courbe cran par cran (aire, largeur, bouchons)')
    a = ap.parse_args()
    img = Image.open(a.image)
    r = wand(img, a.x, a.y, a.tol, a.radius, plug=not a.no_plug)
    if a.png and r['mask']:
        open(a.png, 'wb').write(base64.b64decode(r['mask'].split(',', 1)[1]))
    if a.report:
        report_png(img, r, (a.tol, r['proposed'], r['jump']), a.report)
    if a.steps:
        for row in r['sweep']:
            print(f"tol {row['tol']:3d}  aire {row['area']:7d}  largeur {row['width']:5.1f}  bouchons {row['plugs']} ({row['plugged_px']} px)"
                  f"{'  ← bord' if row['border'] else ''}", file=sys.stderr)
        for p in r['plugs']:
            print(f"  bouchon tol {p['tol']} en {p['x']},{p['y']} : goulot {p['neck']} px ({p['contact']} px de contact, {p['necks']} trou(s))"
                  f" → {p['area']} px² gagnés, largeur {p['width']} vs {p['width_prev']}", file=sys.stderr)
        print(f"arrêt : {r['stop']}", file=sys.stderr)
    r.pop('mask', None)
    for p in r['plugs']:
        p.pop('pixels', None)
    json.dump(r, sys.stdout, indent=1)
