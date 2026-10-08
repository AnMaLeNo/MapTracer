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


def jump(areas, tols, factor=2.5, min_area=30):
    """Première tolérance où l'aire bondit (× factor, une fois la sélection non triviale) : la précédente est la tolérance
    « proposée ». Heuristique à regarder, pas une décision."""
    for i in range(1, len(tols)):
        if areas[i - 1] >= min_area and areas[i] > factor * areas[i - 1]:
            return tols[i - 1], tols[i]
    return tols[-1], None


def png_mask(mask, rgb=(0, 200, 255)):
    rgba = np.zeros(mask.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = rgb
    rgba[..., 3] = mask.astype(np.uint8) * 255
    buf = io.BytesIO()
    Image.fromarray(rgba, 'RGBA').save(buf, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def wand(img, x, y, tol, radius=256, tols=None, sweep=True, near=12):
    sub, (ox, oy), (sx, sy) = window(img, x, y, radius)
    ref = reference(sub, sx, sy)
    res = {'x': x, 'y': y, 'tol': tol, 'origin': [ox, oy], 'size': [sub.shape[1], sub.shape[0]],
           'ref': [int(v) for v in ref], 'seed_px': [int(v) for v in sub[sy, sx]]}
    mask, used = component(candidates(sub, ref, tol), sx, sy)
    res['seed_used'] = None if used is None else [ox + used[0], oy + used[1]]
    st = shape_stats(mask, *(used or (sx, sy)), near=near) if used else light_stats(mask)
    if st.get('bbox'):
        st['bbox'] = [st['bbox'][0] + ox, st['bbox'][1] + oy, st['bbox'][2] + ox, st['bbox'][3] + oy]
    if st.get('center'):
        st['center'] = [st['center'][0] + ox, st['center'][1] + oy, st['center'][2]]
    res['stats'] = st
    res['mask'] = png_mask(mask) if st['area'] else None
    if sweep:
        tols = list(tols or DEFAULT_TOLS)
        rows = []
        for t in tols:
            m, u = component(candidates(sub, ref, t), sx, sy)
            ls = light_stats(m)
            rows.append({'tol': t, 'area': ls['area'], 'border': ls['border'], 'width': ls['width'], 'fill': ls['fill']})
        res['sweep'] = rows
        res['proposed'], res['jump'] = jump([r['area'] for r in rows], tols)
    return res


if __name__ == '__main__':
    import argparse, json, sys
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image'); ap.add_argument('x', type=float); ap.add_argument('y', type=float)
    ap.add_argument('--tol', type=int, default=32); ap.add_argument('--radius', type=int, default=256)
    ap.add_argument('--png', help='écrit le masque PNG ici')
    a = ap.parse_args()
    r = wand(Image.open(a.image), a.x, a.y, a.tol, a.radius)
    if a.png and r['mask']:
        open(a.png, 'wb').write(base64.b64decode(r['mask'].split(',', 1)[1]))
    r.pop('mask', None)
    json.dump(r, sys.stdout, indent=1)
