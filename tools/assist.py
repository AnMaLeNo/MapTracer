"""Mode assisté : à partir du point courant, suit le modèle appris sur une courte distance et renvoie une proposition
(prochain point normal, intersection, cul-de-sac ou jonction) avec sa confiance, pour validation humaine dans l'app."""
import math

import mt_graph as G

ABS_TOL = math.radians(135)      # une direction « derrière » n'est pas une continuation


def _dedupe(dirs, sep=math.radians(20)):
    out = []
    for a, p in sorted(dirs, key=lambda d: -d[1]):
        if all(abs((a - b + math.pi) % (2 * math.pi) - math.pi) > sep for b, _ in out):
            out.append((a, p))
    return out


def _near_segment(x, y, segs, r, skip):
    for i, (x1, y1, x2, y2) in enumerate(segs):
        if i in skip:
            continue
        vx, vy = x2 - x1, y2 - y1; L2 = vx * vx + vy * vy
        t = 0.0 if not L2 else max(0.0, min(1.0, ((x - x1) * vx + (y - y1) * vy) / L2))
        if math.hypot(x1 + t * vx - x, y1 + t * vy - y) <= r:
            return True
    return False


class Assistant:
    def __init__(self, model, img, segs, thr=0.5, side_sep_deg=20, confirm=2, coast=2):
        self.model, self.img, self.segs = model, img, list(segs)
        self.K, self.W = model.meta['sectors'], model.meta['window']
        self.step, self.tw = model.meta['step'], model.meta['trace_width']
        self.thr, self.side_sep, self.confirm, self.coast = thr, math.radians(side_sep_deg), confirm, coast

    def probs(self, x, y, h, extra):
        segs = self.segs + extra
        crops = (G.crop_rotated(self.img, x, y, h, self.W), G.render_traced(segs, x, y, h, self.W, self.tw))
        return self.model.predict(x, y, h, crops)

    def directions(self, x, y, heading):
        """Directions absolues (angle, confiance) au point (x,y) ; cap inconnu → union de deux caps opposés."""
        hs = [heading] if heading is not None else [0.0, math.pi]
        dirs = []
        for h in hs:
            pk = G.peaks(self.probs(x, y, h, []), self.K, self.thr)
            if heading is not None:
                pk = [p for p in pk if abs(p[0]) < ABS_TOL]
            dirs += [((h + rel) % (2 * math.pi), float(sc)) for rel, sc in pk]
        return _dedupe(dirs)

    def follow(self, x0, y0, heading, dist, touching):
        """Avance pas à pas depuis (x0,y0) dans le cap donné sur `dist` px au plus.

        `touching` : indices des segments déjà tracés qui touchent le point de départ (ignorés pour la jonction).
        Renvoie {'kind': normal|intersection|end|junction, 'x', 'y', 'conf', 'path', 'dirs'}."""
        x, y, h = x0, y0, heading
        path, extra, confs = [(x0, y0)], [], []
        pending, coasting = [], 0
        n_max = max(1, int(round(dist / self.step)))
        kind, dirs = 'normal', []
        for n in range(n_max):
            probs = self.probs(x, y, h, extra)
            pk = [p for p in G.peaks(probs, self.K, self.thr) if abs(p[0]) < ABS_TOL]
            if not pk:
                coasting += 1
                if coasting > self.coast or n == 0:
                    kind = 'end'
                    k = max(0, len(path) - coasting)
                    path = path[:k + 1]; confs = confs[:k]
                    break
                pk = [(0.0, 0.0)]
            else:
                coasting = 0
            main = min(pk, key=lambda p: abs(p[0]))
            sides = [(p[0], p[1]) for p in pk if p is not main and abs(p[0] - main[0]) >= self.side_sep]
            seen = set()
            for rel, sc in sides:
                a = (h + rel) % (2 * math.pi)
                for i, pd in enumerate(pending):
                    if i not in seen and abs((a - pd['a'] + math.pi) % (2 * math.pi) - math.pi) < math.radians(75):
                        pd.update(a=a, n=pd['n'] + 1, p=max(pd['p'], sc)); seen.add(i); break
                else:
                    pending.append({'a': a, 'n': 1, 'p': sc, 'x': x, 'y': y, 'i': len(path) - 1}); seen.add(len(pending) - 1)
            pending = [pd for i, pd in enumerate(pending) if i in seen]
            conf = [pd for pd in pending if pd['n'] >= self.confirm]
            if conf and len(path) > 1:
                kind = 'intersection'
                pd = conf[0]
                k = max(1, pd['i'])                      # le carrefour proposé est au moins un pas devant
                path = path[:k + 1]; confs = confs[:k]
                dirs = [((h + main[0]) % (2 * math.pi), float(main[1]))] + [(c['a'], float(c['p'])) for c in conf]
                break
            h = h + main[0]
            nx, ny = x + self.step * math.cos(h), y + self.step * math.sin(h)
            if not (0 <= nx < self.img.width and 0 <= ny < self.img.height):
                break
            if n >= 2 and _near_segment(nx, ny, self.segs, 0.75 * self.step, touching):
                path.append((nx, ny)); confs.append(main[1]); kind = 'junction'; break
            extra.append((x, y, nx, ny)); path.append((nx, ny)); confs.append(main[1]); x, y = nx, ny
        if kind == 'normal' and len(path) == 1:
            kind = 'end'
        if kind == 'intersection' and not dirs:
            dirs = []
        ex, ey = path[-1]
        c = min(confs) if confs else (float(max(probs)) if kind != 'end' else 1.0 - float(max(probs)))
        return {'kind': kind, 'x': round(ex, 1), 'y': round(ey, 1), 'conf': round(float(c), 3),
                'path': [[round(px, 1), round(py, 1)] for px, py in path],
                'dirs': [{'deg': round(math.degrees(a) % 360, 1), 'p': round(p, 3)} for a, p in dirs]}

    def propose(self, x, y, heading, dist, branching):
        """Point normal : une proposition dans le cap. Départ/intersection : une proposition par direction."""
        touching = {i for i, s in enumerate(self.segs) if min(math.dist((x, y), s[:2]), math.dist((x, y), s[2:])) < 0.5}
        if not branching:
            return {'branching': False, 'items': [self.follow(x, y, heading, dist, touching)]}
        dirs = self.directions(x, y, heading)
        items = []
        for a, p in dirs:
            it = self.follow(x, y, a, dist, touching)
            it['dir'] = {'deg': round(math.degrees(a) % 360, 1), 'p': round(p, 3)}
            if it['kind'] != 'end':
                items.append(it)
        return {'branching': True, 'items': items}
