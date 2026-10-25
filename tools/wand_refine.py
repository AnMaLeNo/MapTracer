"""Baguette magique à chaque pas du suivi : recentrage « ballon » et carrefours lus dans la sélection.

À chaque point posé par le modèle (jamais le départ), la baguette (magic_wand.analyze, tolérance automatique) colorie le
vide de galerie autour ; la sélection est réutilisée tant que le point suivant reste dedans, loin du bord de la fenêtre.
Dans cette sélection, la transformée de distance D(p) est le rayon du plus grand disque (« ballon ») centré en p qui ne
touche pas un mur.

- Recentrage : le nouveau point est articulé au précédent à distance fixe (le pas) ; on le fait glisser sur cet arc
  (± arc_deg autour du cap du modèle) jusqu'au maximum de D — le ballon gonflé touche alors les deux parois et le point est
  au milieu de la galerie. S'il y a plusieurs maxima locaux comparables (carrefour), on garde le plus proche de la
  direction du modèle : la baguette corrige la position, le modèle garde le choix de la branche. 2·D = largeur locale.
- Carrefours : deux anneaux (rayons ≈ 2 et 3 fois la demi-largeur) autour du point recentré ; chaque arc d'anneau dans la
  sélection, présent sur les deux anneaux dans la même direction, est un « bras ». Le bras arrière est celui d'où l'on
  vient ; les autres, hors continuation, sont des directions latérales proposées au suivi (comme celles du modèle).
- Garde-fou : si le point du modèle n'est pas dans la sélection, ou si la demi-largeur mesurée est sans rapport avec celle
  des pas précédents (fuite, texte, lavis : la sélection n'est pas cohérente), le point du modèle est gardé tel quel et le
  pas est marqué (`wand` = 'off' / 'incoherent') — à regarder, pas à croire.
"""
import math

import numpy as np
from scipy import ndimage as ndi

import magic_wand as WD


class WandRefiner:
    def __init__(self, img, radius=96, tol_max=64, arc_deg=45, arc_step_deg=3, margin=24, ring_k=(2.0, 3.0),
                 min_arm_deg=15, reach_px=5.0, coherent_k=3.0, min_gain=0.25, verbose=False):
        self.img, self.radius, self.tol_max = img, radius, tol_max
        self.arc = [math.radians(d) for d in range(-arc_deg, arc_deg + 1, arc_step_deg)]
        self.margin, self.ring_k, self.min_arm, self.coherent_k, self.verbose = margin, ring_k, math.radians(min_arm_deg), coherent_k, verbose
        self.reach_px, self.min_gain = reach_px, min_gain
        self.S, self.tol, self.mask, self.D, self.seed = None, None, None, None, None
        self.n_analyses = 0
        self.stats = {'steps': 0, 'recentred': 0, 'off': 0, 'incoherent': 0, 'shift_sum': 0.0, 'arms_seen': 0}

    # ---- sélection courante --------------------------------------------------------------------------------------
    def _local(self, x, y):
        return x - self.S['ox'], y - self.S['oy']

    def _covers(self, x, y):
        if self.S is None:
            return False
        lx, ly = self._local(x, y)
        h, w = self.mask.shape
        return self.margin <= lx < w - self.margin and self.margin <= ly < h - self.margin

    def _inside(self, x, y):
        lx, ly = self._local(x, y)
        return bool(self.mask[int(round(ly)), int(round(lx))])

    def _analyze(self, x, y):
        S = WD.analyze(self.img, round(x), round(y), self.radius, WD.DEFAULT_TOLS, plug=True)
        self.n_analyses += 1
        stop = S['stop']
        tol = self.tol_max if stop is None else stop['before']
        if tol is None:
            self.S = None; return False
        self.S, self.tol, self.seed = S, min(int(tol), self.tol_max), (int(round(x)), int(round(y)))
        self.mask = WD.mask_at(S, self.tol)
        self.D = ndi.distance_transform_edt(self.mask) if self.mask.any() else None
        return self.D is not None

    def ensure(self, x, y):
        """Sélection couvrant (x, y) avec marge et contenant le point. False : le point est sur un trait / hors galerie."""
        if self._covers(x, y) and self._inside(x, y):
            return True
        if not self._analyze(x, y):
            return False
        return self._inside(x, y)

    def dist(self, xs, ys):
        """D interpolée (bilinéaire) en coordonnées carte ; 0 hors sélection."""
        lx, ly = self._local(np.asarray(xs, float), np.asarray(ys, float))
        return ndi.map_coordinates(self.D, [ly, lx], order=1, mode='constant', cval=0.0)

    # ---- recentrage ------------------------------------------------------------------------------------------------
    def recenter(self, px, py, heading, step):
        """Point sur l'arc (centre (px,py), rayon step, ± arc autour de heading) au maximum local de D le plus proche du cap du
        modèle : le ballon se centre dans la galerie que le modèle a choisie — au départ d'une branche latérale, le plus
        gros disque est au centre du carrefour, derrière ; on ne doit pas y retomber. Renvoie (x, y, cap, demi-largeur) ou None."""
        th = np.array([heading + a for a in self.arc])
        xs, ys = px + step * np.cos(th), py + step * np.sin(th)
        d = self.dist(xs, ys)
        mid = self.dist((px + xs) / 2, (py + ys) / 2)        # le segment doit rester dans la sélection
        d = np.where(mid > 0, d, 0.0)
        self.last_arc = [[round(math.degrees(a)), round(float(v), 2)] for a, v in zip(self.arc, d)]
        if d.max() <= 0.5:
            return None
        cands = [i for i in range(len(d)) if d[i] > 0.5
                 and (i == 0 or d[i] >= d[i - 1]) and (i == len(d) - 1 or d[i] >= d[i + 1])]
        i = min(cands, key=lambda k: abs(self.arc[k]))
        i0 = min(range(len(d)), key=lambda k: abs(self.arc[k]))          # la direction du modèle elle-même
        if d[i0] > 0.5 and d[i] < d[i0] + self.min_gain:                 # gain négligeable (galerie de 2 px : D ≈ 1 partout) :
            i = i0                                                       # on ne dévie pas le cap pour rien
        return float(xs[i]), float(ys[i]), float(th[i]), float(d[i])

    # ---- carrefours ------------------------------------------------------------------------------------------------
    def arms(self, x, y, r, n=120):
        """Directions (rad, absolues) des bras de galerie autour de (x, y) : arcs des deux anneaux dans la sélection,
        d'ouverture ≥ min_arm et concordants (± 30°) entre les deux anneaux, et qui continuent au-delà (la sélection est
        encore là à `reach` px dans cette direction) — une dent ou une niche du bord de la galerie n'est pas un bras."""
        th = np.arange(n) * (2 * math.pi / n)
        runs_by_ring = []
        for k in self.ring_k:
            rho = max(k * r + 1.5, 4.0)
            lx, ly = self._local(x + rho * np.cos(th), y + rho * np.sin(th))
            on = ndi.map_coordinates(self.mask.astype(np.uint8), [ly, lx], order=0, mode='constant', cval=0) > 0
            runs_by_ring.append(_runs(on, th))
        reach = max(self.ring_k[1] * r + 1.5 + self.reach_px, 12.0)
        out = []
        for a0, span0 in runs_by_ring[0]:
            if span0 < self.min_arm:
                continue
            for a1, span1 in runs_by_ring[1]:
                if span1 >= self.min_arm and abs((a0 - a1 + math.pi) % (2 * math.pi) - math.pi) <= math.radians(30):
                    a = a1 if span1 < span0 else a0
                    far = self.dist([x + reach * math.cos(a)], [y + reach * math.sin(a)])[0]
                    if far > 0.5:
                        out.append(a)
                    break
        return out

    # ---- un pas ------------------------------------------------------------------------------------------------------
    def refine(self, px, py, qx, qy, heading, step, hist_w, debug=False):
        """(px,py) → point précédent, (qx,qy) → point proposé par le modèle. Renvoie (x, y, cap, info) ; avec debug, info['dbg']
        raconte le pas : point du modèle, sélection utilisée, profil D(θ) sur l'arc, bras, raison d'un refus."""
        self.stats['steps'] += 1
        info = {'wand': 'off'}
        dbg = {'model': [round(qx, 2), round(qy, 2)], 'prev': [round(px, 2), round(py, 2)], 'head_model': round(math.degrees(heading) % 360),
               'sel': None, 'arc': None, 'arms_all': None} if debug else None
        self.last_arc = None
        try:
            inside = self.ensure(qx, qy)
            if dbg and self.S is not None:
                st = self.S['stop']
                dbg['sel'] = {'x': self.seed[0], 'y': self.seed[1], 'radius': self.radius, 'tol': self.tol,
                              'ref': [int(v) for v in self.S['ref']], 'proposed': None if st is None else st['before'],
                              'stop': None if st is None else st['reason'], 'area': int(self.mask.sum())}
            if not inside:
                self.stats['off'] += 1
                if dbg:
                    dbg['reason'] = 'off : le point du modèle n\'est pas dans la sélection (trait, texte, lavis ?) — gardé tel quel'
                return qx, qy, heading, info
            rc = self.recenter(px, py, heading, step)
            if dbg:
                dbg['arc'] = self.last_arc
            if rc is None:
                self.stats['off'] += 1
                if dbg:
                    dbg['reason'] = 'off : aucune position de l\'arc n\'est dans la sélection (D ≤ 0,5 partout) — gardé tel quel'
                return qx, qy, heading, info
            x, y, h, r = rc
            info['w'] = round(2 * r, 1)
            if dbg:
                dbg['r'] = round(r, 2); dbg['head'] = round(math.degrees(h) % 360)
                dbg['hist_w'] = [round(v, 1) for v in hist_w[-12:]]
            if hist_w:
                med = float(np.median(hist_w[-12:]))
                if 2 * r > max(self.coherent_k * med, med + 6):
                    self.stats['incoherent'] += 1
                    info['wand'] = 'incoherent'
                    if dbg:
                        dbg['reason'] = f'incoherent : largeur {2 * r:.1f} px contre médiane {med:.1f} px des 12 derniers pas — gardé tel quel'
                    return qx, qy, heading, info
            shift = math.hypot(x - qx, y - qy)
            self.stats['recentred'] += 1; self.stats['shift_sum'] += shift
            info.update({'wand': 'ok', 'shift': round(shift, 2), 'tol': self.tol})
            arms = self.arms(x, y, r)
            back = [a for a in arms if abs((a - (h + math.pi) + math.pi) % (2 * math.pi) - math.pi) <= math.radians(60)]
            fwd = [a for a in arms if a not in back]
            info['arms'] = [round(math.degrees(a)) for a in fwd]
            if dbg:
                dbg['arms_all'] = [round(math.degrees(a) % 360) for a in arms]
                dbg['reason'] = 'ok : recentré' + (f' de {shift:.2f} px' if shift else '')
            if len(fwd) >= 2:
                self.stats['arms_seen'] += 1
            return x, y, h, info
        finally:
            if dbg:
                info['dbg'] = dbg

    def summary(self):
        s = dict(self.stats)
        s['mean_shift'] = round(s['shift_sum'] / max(1, s['recentred']), 2); s.pop('shift_sum')
        s['analyses'] = self.n_analyses
        return s


def _runs(on, th):
    """Arcs contigus (avec recollement en 0/2π) d'un anneau échantillonné : [(angle central, ouverture)]."""
    n = len(on)
    if on.all():
        return [(0.0, 2 * math.pi)]
    if not on.any():
        return []
    start = int(np.argmin(on))                   # commence hors sélection pour ne pas couper un arc
    runs, cur = [], None
    for i in range(n + 1):
        k = (start + i) % n
        if on[k] and cur is None:
            cur = [k, 1]
        elif on[k] and cur is not None:
            cur[1] += 1
        elif not on[k] and cur is not None:
            a0 = th[cur[0]] + (cur[1] - 1) * 0.5 * (2 * math.pi / n)
            runs.append((a0 % (2 * math.pi), cur[1] * 2 * math.pi / n)); cur = None
    return runs
