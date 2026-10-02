"""Graphe de galeries reconstruit depuis un projet MapTracer + géométrie partagée par oracle.py et trace.py.

Conventions (identiques dans le jeu de données et dans la boucle de suivi) :
  - coordonnées en pixels carte, y vers le bas ; cap θ = atan2(dy, dx) (radians) ;
  - fenêtre tournée « cap vers le haut » : un point à l'angle relatif a (0 = devant, croissant dans le sens horaire à
    l'écran) est à l'angle absolu θ + a ;
  - K secteurs : le secteur k est centré sur l'angle relatif k·360/K, k = 0 devant.
"""
import json, math, random
from PIL import Image, ImageDraw

from export_dataset import replay

Image.MAX_IMAGE_PIXELS = None


class Graph:
    def __init__(self):
        self.nodes = {}      # id -> {'x','y','kind'}
        self.adj = {}        # id -> set(id)
        self.open = set()    # extrémités de degré 1 jamais terminées (amorces en attente) : pas des cul-de-sac
        self.next_id = 1

    # ---- construction -------------------------------------------------------------------------------------------
    def add_node(self, x, y, kind='normal', id_=None):
        if id_ is None:
            id_ = self.next_id
        self.next_id = max(self.next_id, id_ + 1)
        self.nodes[id_] = {'x': float(x), 'y': float(y), 'kind': kind}
        self.adj.setdefault(id_, set())
        return id_

    def add_edge(self, a, b):
        if a == b:
            return False
        if b in self.adj[a]:
            return False
        self.adj[a].add(b); self.adj[b].add(a)
        return True

    def remove_edge(self, a, b):
        self.adj[a].discard(b); self.adj[b].discard(a)

    def split_edge(self, a, b, x, y, kind='intersection'):
        self.remove_edge(a, b)
        n = self.add_node(x, y, kind)
        self.add_edge(a, n); self.add_edge(n, b)
        return n

    @property
    def edges(self):
        return [(a, b) for a in self.adj for b in self.adj[a] if a < b]

    def degree(self, n):
        return len(self.adj[n])

    def xy(self, n):
        p = self.nodes[n]; return p['x'], p['y']

    def length(self, a, b):
        return math.dist(self.xy(a), self.xy(b))

    def total_length(self):
        return sum(self.length(a, b) for a, b in self.edges)

    def lerp(self, a, b, t):
        ax, ay = self.xy(a); bx, by = self.xy(b)
        return ax + (bx - ax) * t, ay + (by - ay) * t

    def bbox(self, margin=0):
        xs = [p['x'] for p in self.nodes.values()]; ys = [p['y'] for p in self.nodes.values()]
        return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin

    # ---- requêtes géométriques ----------------------------------------------------------------------------------
    def project(self, x, y, exclude_edges=()):
        """Point du graphe le plus proche de (x, y) : (dist, a, b, t) sur l'arête a-b, ou None si graphe vide."""
        best = None
        for a, b in self.edges:
            if (a, b) in exclude_edges or (b, a) in exclude_edges:
                continue
            ax, ay = self.xy(a); bx, by = self.xy(b)
            vx, vy = bx - ax, by - ay; L2 = vx * vx + vy * vy
            if L2 == 0:
                continue
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2))
            d = math.hypot(ax + t * vx - x, ay + t * vy - y)
            if best is None or d < best[0]:
                best = (d, a, b, t)
        return best

    def nearest_node(self, x, y, exclude=()):
        best = None
        for n, p in self.nodes.items():
            if n in exclude:
                continue
            d = math.hypot(p['x'] - x, p['y'] - y)
            if best is None or d < best[0]:
                best = (d, n)
        return best

    def lookahead(self, a, b, t, L, step):
        """Depuis la position t sur l'arête a→b (cap vers b), suit le graphe sur une distance géodésique L.

        Renvoie la liste des points atteints (un par branche) : {'x','y','dist','dead'}.
        Un cul-de-sac situé à moins d'un pas donne dead=True et dist < step → aucune direction (fin de galerie).
        """
        out = []
        px, py = self.lerp(a, b, t)
        rem_edge = (1 - t) * self.length(a, b)

        def walk(u, v, used):          # au nœud u, on part vers v ; `used` = distance déjà parcourue
            d = self.length(u, v)
            if d <= 0:
                return
            if used + d >= L:
                x, y = self.lerp(u, v, (L - used) / d)
                out.append({'x': x, 'y': y, 'dist': L, 'dead': False}); return
            nxt = [w for w in self.adj[v] if w != u]
            if not nxt:
                x, y = self.xy(v); out.append({'x': x, 'y': y, 'dist': used + d, 'dead': True, 'open': v in self.open}); return
            for w in nxt:
                walk(v, w, used + d)

        if rem_edge >= L:
            x, y = self.lerp(a, b, t + L / self.length(a, b))
            out.append({'x': x, 'y': y, 'dist': L, 'dead': False})
        else:
            nxt = [w for w in self.adj[b] if w != a]
            if not nxt:
                x, y = self.xy(b); out.append({'x': x, 'y': y, 'dist': rem_edge, 'dead': True, 'open': b in self.open})
            for w in nxt:
                walk(b, w, rem_edge)
        # dédoublonne (boucles très courtes)
        seen, res = set(), []
        for o in out:
            k = (round(o['x'], 1), round(o['y'], 1))
            if k not in seen:
                seen.add(k); res.append(o)
        return res

    def traced_edges_behind(self, a, b, t, radius, rng=None, p_explore=0.6, p_other=0.3, L=0):
        """Arêtes à dessiner dans le canal « déjà tracé » pour une position sur a→b (cap vers b).

        Toujours : le chemin d'arrivée (de la position vers a, puis les chaînes de degré 2). Aux intersections
        derrière nous, chaque autre galerie est incluse avec probabilité p_explore (zones déjà explorées).
        Avec probabilité p_other, une composante déjà tracée sans lien direct, visible dans la fenêtre.
        Renvoie (segments [(x1,y1,x2,y2)], extra:bool).
        """
        rng = rng or random
        px, py = self.lerp(a, b, t)
        segs = [(px, py, *self.xy(a))]
        forward = {n for n, _ in self._nodes_within_geodesic(a, b, t, 2 * L + 1e-6)} if L else set()
        visited = {a}
        frontier = [(a, b, 0.0)]          # (nœud, d'où l'on vient, distance parcourue)
        while frontier:
            u, frm, used = frontier.pop()
            for w in self.adj[u]:
                if w == frm or w in visited or w in forward:
                    continue
                if self.degree(u) > 2 and rng.random() > p_explore:
                    continue
                d = used + self.length(u, w)
                segs.append((*self.xy(u), *self.xy(w)))
                visited.add(w)
                if d < radius:
                    frontier.append((w, u, d))
        extra = False
        if rng.random() < p_other:
            cands = [n for n, p in self.nodes.items() if n not in visited and n not in forward
                     and abs(p['x'] - px) < radius and abs(p['y'] - py) < radius]
            if cands:
                seed = rng.choice(cands); comp = {seed}; fr = [seed]
                while fr:
                    u = fr.pop()
                    for w in self.adj[u]:
                        if w in comp or w in visited or w in forward:
                            continue
                        q = self.nodes[w]
                        if abs(q['x'] - px) > radius or abs(q['y'] - py) > radius:
                            continue
                        segs.append((*self.xy(u), *self.xy(w))); comp.add(w); fr.append(w)
                extra = len(comp) > 1
        return segs, extra

    def _nodes_within_geodesic(self, a, b, t, L):
        """Nœuds situés devant (côté b) à moins de L le long du graphe."""
        res = []
        rem = (1 - t) * self.length(a, b)
        if rem > L:
            return res
        frontier = [(b, a, rem)]; seen = {b}
        while frontier:
            v, frm, used = frontier.pop()
            res.append((v, used))
            for w in self.adj[v]:
                if w == frm or w in seen:
                    continue
                d = used + self.length(v, w)
                if d <= L:
                    seen.add(w); frontier.append((w, v, d))
        return res

    # ---- E/S -----------------------------------------------------------------------------------------------------
    def to_dict(self):
        return {'nodes': [{'id': n, **p} for n, p in self.nodes.items()],
                'edges': [{'from': a, 'to': b} for a, b in self.edges]}

    @classmethod
    def from_dict(cls, d):
        g = cls()
        for n in d['nodes']:
            g.add_node(n['x'], n['y'], n.get('kind', 'normal'), n['id'])
        for e in d['edges']:
            g.add_edge(e['from'], e['to'])
        return g

    def to_geojson(self, georef):
        ll = lambda x, y: [georef['lon'][0] * x + georef['lon'][1], georef['lat'][0] * y + georef['lat'][1]]
        feats = [{'type': 'Feature', 'properties': {},
                  'geometry': {'type': 'LineString', 'coordinates': [ll(*self.xy(a)), ll(*self.xy(b))]}}
                 for a, b in self.edges]
        feats += [{'type': 'Feature', 'properties': {'kind': p['kind'], 'degree': self.degree(n)},
                   'geometry': {'type': 'Point', 'coordinates': ll(p['x'], p['y'])}} for n, p in self.nodes.items()]
        return {'type': 'FeatureCollection', 'features': feats}


def graph_from_project(proj):
    """Graphe non orienté : arêtes parent→enfant (place/split) + jonctions, rejouées depuis `events`."""
    pts, decisions = replay(proj['events'], proj.get('rev', 1))
    g = Graph()
    for p in pts.values():
        g.add_node(p['x'], p['y'], p['kind'], p['id'])
    for p in pts.values():
        if p['parent'] is not None:
            g.add_edge(p['parent'], p['id'])
    for d in decisions:
        if d.get('join_to') is not None:
            g.add_edge(d['point'], d['join_to'])
    ended = {d['point'] for d in decisions if d['terminal'] == 'end'}
    g.open = {n for n in g.nodes if g.degree(n) == 1 and n not in ended}
    return g


def load_project(path):
    proj = json.load(open(path, encoding='utf-8'))
    assert proj.get('format') == 'maptracer/1', 'format inattendu'
    return proj


# ---- fenêtre tournée et secteurs ---------------------------------------------------------------------------------
def to_crop(px, py, heading, W, x, y):
    """Coordonnées carte → coordonnées dans la fenêtre W×W centrée sur (px,py), cap `heading` vers le haut."""
    dx, dy = x - px, y - py
    c, s = math.cos(heading), math.sin(heading)
    fwd = dx * c + dy * s           # composante « devant »
    rgt = -dx * s + dy * c          # composante « droite » (horaire)
    return W / 2 + rgt, W / 2 - fwd


def rel_angle(px, py, heading, x, y):
    """Angle relatif (rad) de (x,y) vu de (px,py) avec le cap `heading` : 0 devant, horaire positif, dans (-π, π]."""
    a = math.atan2(y - py, x - px) - heading
    return (a + math.pi) % (2 * math.pi) - math.pi


def sector_of(angle, K):
    return int(round(angle / (2 * math.pi / K))) % K


def soft_label(angles, K, sigma=0.7):
    lab = [0.0] * K
    for a in angles:
        s = angle_to_sector_float(a, K)
        for k in range(K):
            d = min(abs(k - s), K - abs(k - s))
            lab[k] = max(lab[k], math.exp(-d * d / (2 * sigma * sigma)))
    return [round(v, 3) for v in lab]


def angle_to_sector_float(angle, K):
    return (angle / (2 * math.pi / K)) % K


def crop_rotated(img, px, py, heading, W, resample=Image.BILINEAR):
    """Fenêtre W×W de `img` centrée sur (px,py), tournée pour que le cap pointe vers le haut (hors carte : noir)."""
    # pixel de sortie (u,v) → carte : p + fwd·(W/2 - v) + rgt·(u - W/2), fwd=(cosθ,sinθ), rgt=(-sinθ,cosθ)
    c, s = math.cos(heading), math.sin(heading)
    a, b = -s, -c           # ∂x/∂u, ∂x/∂v
    d, e = c, -s            # ∂y/∂u, ∂y/∂v
    cx = px - a * W / 2 - b * W / 2
    cy = py - d * W / 2 - e * W / 2
    return img.transform((W, W), Image.AFFINE, (a, b, cx, d, e, cy), resample=resample, fillcolor=0)


def render_traced(segs, px, py, heading, W, width):
    """Canal « déjà tracé » (image L) : segments carte dessinés dans le repère de la fenêtre."""
    im = Image.new('L', (W, W), 0)
    dr = ImageDraw.Draw(im)
    for x1, y1, x2, y2 in segs:
        u1, v1 = to_crop(px, py, heading, W, x1, y1); u2, v2 = to_crop(px, py, heading, W, x2, y2)
        dr.line([(u1, v1), (u2, v2)], fill=255, width=width)
    return im


def oracle_directions(g, a, b, t, px, py, heading, L, step, skip_open=False):
    """Directions cibles (angles relatifs, rad) depuis la position réelle (px,py) avec cap `heading`,
    pour un état de référence « sur l'axe » à la position t de l'arête a→b. Renvoie (angles, points).

    Une extrémité « ouverte » (amorce jamais terminée) n'est pas un cul-de-sac : la galerie continue probablement.
    Avec skip_open, l'état est inexploitable comme exemple → (None, None) ; sinon elle compte comme une direction."""
    pts = g.lookahead(a, b, t, L, step)
    if skip_open and any(q['dead'] and q.get('open') for q in pts):
        return None, None
    angles, keep = [], []
    for q in pts:
        if q['dead'] and q['dist'] < step and not q.get('open'):
            continue
        angles.append(rel_angle(px, py, heading, q['x'], q['y'])); keep.append(q)
    return angles, keep


def peaks(probs, K, thr):
    """Composantes connexes circulaires de secteurs > seuil → [(angle relatif rad, score)]."""
    act = [p >= thr for p in probs]
    if all(act):
        return [(0.0, max(probs))]
    start = act.index(False)
    res, i = [], 0
    while i < K:
        k = (start + i) % K
        if act[k]:
            comp = []
            while act[(start + i) % K] and i < K:
                comp.append((start + i) % K); i += 1
            ws = [probs[c] for c in comp]
            k0 = comp[0]
            ang = sum((k0 + j) * w for j, w in enumerate(ws)) / sum(ws)     # indices consécutifs (non modulo)
            a = (ang % K) * 2 * math.pi / K
            res.append(((a + math.pi) % (2 * math.pi) - math.pi, max(ws)))
        else:
            i += 1
    return res
