#!/usr/bin/env python3
"""Boucle de suivi de galeries à pas fixe (RoadTracer-like), avec un modèle interchangeable.

À chaque pas le modèle reçoit l'état (position, cap, fenêtre tournée, canal déjà tracé) et renvoie K probabilités
de secteurs ; la boucle :
  - avance d'un pas fixe dans le secteur le plus proche du cap (continuation) ;
  - garde en attente les autres secteurs ; s'ils sont vus 2 pas de suite, le nœud courant devient une intersection et
    une branche (position, cap) est mise en file ;
  - termine la branche si aucun secteur n'est actif (cul-de-sac), si le pas atterrit sur le graphe déjà tracé
    (jonction : raccord au nœud le plus proche ou insertion d'un nœud sur l'arête), ou en sortie de carte.

Le modèle par défaut (`--model oracle`) lit les directions dans le tracé manuel du projet : c'est un « faux modèle »
qui valide la mécanique (intersections, boucles, jonctions, fins) indépendamment de l'apprentissage. `--noise-deg` et
`--drop` dégradent ses réponses pour tester la robustesse. Le résultat est comparé au tracé manuel (couverture,
précision, intersections retrouvées) et rendu dans debug.png (bleu = manuel, rouge = suivi).

Exemple : python3 tools/trace.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o suivi/ --step 4
"""
import argparse, json, math, os, random, sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
import mt_graph as G
try:
    from model import LearnedModel
except ImportError:                     # torch absent : seul le faux modèle oracle est disponible
    LearnedModel = None

Image.MAX_IMAGE_PIXELS = None


class OracleModel:
    """Faux modèle : renvoie les secteurs calculés depuis le graphe de référence, comme oracle.py."""
    needs_image = False

    def __init__(self, ref, step, lookahead, K, snap, noise_deg=0.0, drop=0.0, rng=None):
        self.ref, self.step, self.L, self.K, self.snap = ref, step, lookahead, K, snap
        self.noise, self.drop, self.rng = math.radians(noise_deg), drop, rng or random.Random(0)

    def predict(self, x, y, heading, crops=None):
        best = None                          # arête orientée la mieux alignée avec le cap parmi celles à portée
        for a, b in self.ref.edges:
            ax, ay = self.ref.xy(a); bx, by = self.ref.xy(b)
            vx, vy = bx - ax, by - ay; L2 = vx * vx + vy * vy
            if not L2:
                continue
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2))
            d = math.hypot(ax + t * vx - x, ay + t * vy - y)
            if d > self.snap:
                continue
            for u, v, tt, ang in ((a, b, t, math.atan2(vy, vx)), (b, a, 1 - t, math.atan2(-vy, -vx))):
                score = math.cos(ang - heading) - d / self.snap
                if best is None or score > best[0]:
                    best = (score, u, v, tt)
        if best is None:
            return [0.0] * self.K
        _, a, b, t = best
        angles, _ = G.oracle_directions(self.ref, a, b, t, x, y, heading, self.L, self.step, near=3 * self.step)
        angles = [an + self.rng.gauss(0, self.noise) for an in angles if self.rng.random() >= self.drop]
        return G.soft_label(angles, self.K)


class StopTrace(Exception):
    """Levée par le `hook` d'un Tracer pour interrompre le suivi (le graphe produit jusque-là est conservé)."""


class Tracer:
    def __init__(self, model, step, K, thr=0.5, img=None, window=128, trace_width=3, map_size=None,
                 max_steps=200000, max_branch_steps=20000, side_sep_deg=20, confirm=2, coast=2, grace=2, verbose=False,
                 bounds=None, hook=None):
        self.model, self.step, self.K, self.thr = model, step, K, thr
        self.bounds = bounds        # (x0, y0, x1, y1) : le suivi s'arrête en sortant de la zone
        self.hook = hook            # appelé à chaque pas avec le Tracer (progression) ; peut lever StopTrace
        self.img, self.W, self.trace_width, self.map_size = img, window, trace_width, map_size
        self.max_steps, self.max_branch_steps = max_steps, max_branch_steps
        self.side_sep, self.confirm, self.coast, self.grace, self.verbose = math.radians(side_sep_deg), confirm, coast, grace, verbose
        self.r_join = 0.75 * step
        self.out = G.Graph()
        self.queue = deque()
        self.branches = []          # rapport par branche
        self.steps = 0

    # ---- modèle --------------------------------------------------------------------------------------------------
    def crops(self, x, y, heading):
        if not self.model.needs_image:
            return None
        segs = [(*self.out.xy(a), *self.out.xy(b)) for a, b in self.out.edges]
        return (G.crop_rotated(self.img, x, y, heading, self.W),
                G.render_traced(segs, x, y, heading, self.W, self.trace_width))

    def peaks(self, probs):
        return G.peaks(probs, self.K, self.thr)
    # ---- graphe de sortie -----------------------------------------------------------------------------------------
    def has_edge_toward(self, node, angle, radius, tol=None):
        tol = 0.75 * self.side_sep if tol is None else tol
        x, y = self.out.xy(node)
        for m, p in self.out.nodes.items():
            if math.hypot(p['x'] - x, p['y'] - y) > radius:
                continue
            for w in self.out.adj[m]:
                q = self.out.nodes[w]
                a = math.atan2(q['y'] - p['y'], q['x'] - p['x'])
                if abs((a - angle + math.pi) % (2 * math.pi) - math.pi) < tol:
                    return True
        return False

    def spawn(self, node, angle):
        if self.has_edge_toward(node, angle, 2 * self.step):
            return False
        self.out.nodes[node]['kind'] = 'intersection'
        self.queue.append((node, angle))
        return True

    def junction(self, x, y, node, hist):
        """Si (x,y) tombe sur le graphe déjà tracé (hors nœuds/arêtes récents de la branche), raccorde et renvoie le nœud."""
        recent = set(hist[-3:])
        excl = {(hist[i], hist[i + 1]) for i in range(max(0, len(hist) - 4), len(hist) - 1)}
        if len(hist) == 1:                                  # départ de branche : ignore le voisinage (2 pas) du nœud d'origine
            near = {node} | self.out.adj[node]
            near |= {w for m in list(near) for w in self.out.adj[m]}
            recent |= near; excl |= {(m, w) for m in near for w in self.out.adj[m]}
        nn = self.out.nearest_node(x, y, exclude=recent)
        if nn and nn[0] <= self.r_join:
            self.out.add_edge(node, nn[1]); return nn[1]
        pr = self.out.project(x, y, exclude_edges=excl)
        if pr and pr[0] <= self.r_join:
            d, a, b, t = pr
            if t < 0.05:
                self.out.add_edge(node, a); return a
            if t > 0.95:
                self.out.add_edge(node, b); return b
            jx, jy = self.out.lerp(a, b, t)
            n = self.out.split_edge(a, b, jx, jy)
            self.out.add_edge(node, n); return n
        return None

    # ---- boucle --------------------------------------------------------------------------------------------------
    def seed(self, x, y, heading=None):
        n = self.out.add_node(x, y, 'start')
        headings = [heading] if heading is not None else [0.0, math.pi]
        dirs = []
        for h in headings:
            for rel, _ in self.peaks(self.model.predict(x, y, h, self.crops(x, y, h))):
                a = (h + rel) % (2 * math.pi)
                if all(abs((a - d + math.pi) % (2 * math.pi) - math.pi) > math.radians(20) for d in dirs):
                    dirs.append(a)
        for a in dirs:
            self.queue.append((n, a))
        return n, dirs

    def run(self):
        try:
            while self.queue and self.steps < self.max_steps:
                node, heading = self.queue.popleft()
                x, y = self.out.xy(node)
                x1, y1 = x + self.step * math.cos(heading), y + self.step * math.sin(heading)
                if self.junction(x1, y1, node, [node]) is not None:        # galerie déjà tracée entre-temps
                    self.branches.append({'steps': 0, 'reason': 'junction', 'end_xy': [round(x1, 1), round(y1, 1)]})
                    continue
                self.follow(node, heading)
        except StopTrace:
            pass
        return self.out

    def follow(self, node, heading):
        x, y = self.out.xy(node)
        hist = [node]
        pending = []                                   # {'angle': abs, 'count', 'node'}
        reason, n_steps, coasting = 'max_steps', 0, 0
        while n_steps < self.max_branch_steps and self.steps < self.max_steps:
            if self.hook:
                self.hook(self)
            probs = self.model.predict(x, y, heading, self.crops(x, y, heading))
            pk = [p for p in self.peaks(probs) if abs(p[0]) < math.radians(135)]
            if not pk:
                if coasting >= self.coast:
                    reason = 'end' if max(probs) < 1e-6 else 'low_confidence'
                    for _ in range(coasting):                    # retire les pas faits « à l'aveugle »
                        if len(hist) > 1:
                            self.out.remove_edge(hist[-2], hist[-1]); del self.out.nodes[hist[-1]]
                            del self.out.adj[hist[-1]]; hist.pop(); node = hist[-1]; x, y = self.out.xy(node)
                    if reason == 'end' and self.out.degree(node) == 1 and self.out.nodes[node]['kind'] == 'normal':
                        self.out.nodes[node]['kind'] = 'end'        # cul-de-sac annoncé par le modèle (à vérifier)
                    break
                coasting += 1; pk = [(0.0, 0.0)]
            else:
                coasting = 0
            main = min(pk, key=lambda p: abs(p[0]))
            sides = [p for p in pk if p is not main and
                     abs((p[0] - main[0] + math.pi) % (2 * math.pi) - math.pi) >= self.side_sep]
            # suivi des directions latérales : une branche s'ouvre quand une direction vue ≥ `confirm` fois disparaît
            # (`grace` pas sans la voir tolérés) ou à la fin de la branche
            seen = set()
            for rel, _ in sides:
                a = (heading + rel) % (2 * math.pi)
                for i, pd in enumerate(pending):          # même direction, vue aux pas précédents (pas un autre carrefour plus loin)
                    if i not in seen and abs((a - pd['angle'] + math.pi) % (2 * math.pi) - math.pi) < math.radians(75) \
                            and math.dist((x, y), self.out.xy(pd['node'])) <= (pd['miss'] + 1) * self.step * 1.25:
                        pd['angle'], pd['node'], pd['count'], pd['miss'] = a, node, pd['count'] + 1, 0; seen.add(i); break
                else:
                    pending.append({'angle': a, 'node': node, 'count': 1, 'miss': 0}); seen.add(len(pending) - 1)
            keep = []                                        # le carrefour est posé là où la direction latérale a été vue en dernier
            for i, pd in enumerate(pending):
                if i in seen:
                    keep.append(pd)
                elif pd['miss'] < self.grace:
                    pd['miss'] += 1; keep.append(pd)
                elif pd['count'] >= self.confirm:
                    self.spawn(pd['node'], pd['angle'])
                elif self.verbose:
                    print(f"    latérale vue {pd['count']}× abandonnée à {tuple(round(v) for v in self.out.xy(pd['node']))} ({math.degrees(pd['angle']):.0f}°)")
            pending = keep
            # avance d'un pas
            heading = heading + main[0]
            nx, ny = x + self.step * math.cos(heading), y + self.step * math.sin(heading)
            self.steps += 1; n_steps += 1
            if self.map_size and not (0 <= nx < self.map_size[0] and 0 <= ny < self.map_size[1]):
                reason = 'out_of_map'; break
            if self.bounds and not (self.bounds[0] <= nx <= self.bounds[2] and self.bounds[1] <= ny <= self.bounds[3]):
                reason = 'out_of_zone'; break
            j = self.junction(nx, ny, node, hist)
            if j is not None:
                reason = 'junction'; break
            n = self.out.add_node(nx, ny)
            self.out.add_edge(node, n)
            node, x, y = n, nx, ny
            hist.append(n)
        for pd in pending:                                # direction latérale vue juste avant la fin
            if pd['count'] >= self.confirm:
                self.spawn(pd['node'], pd['angle'])
        self.branches.append({'steps': n_steps, 'reason': reason, 'end_xy': [round(x, 1), round(y, 1)]})
        if self.verbose:
            print(f"  branche {len(self.branches)}: {n_steps} pas, {reason} à ({x:.0f},{y:.0f}), file {len(self.queue)}")


# ---- évaluation ----------------------------------------------------------------------------------------------------
def sample_edges(g, every=1.0):
    pts = []
    for a, b in g.edges:
        L = g.length(a, b); n = max(1, int(L / every))
        for i in range(n + 1):
            pts.append(g.lerp(a, b, i / n))
    return np.array(pts) if pts else np.zeros((0, 2))


def dist_to_segments(P, g):
    if len(P) == 0 or not g.edges:
        return np.full(len(P), np.inf)
    S = np.array([[*g.xy(a), *g.xy(b)] for a, b in g.edges])
    A, B = S[:, :2], S[:, 2:]
    V = B - A; L2 = np.maximum((V ** 2).sum(1), 1e-9)
    out = np.empty(len(P))
    for i in range(0, len(P), 2000):
        p = P[i:i + 2000]
        t = np.clip(((p[:, None, :] - A[None]) * V[None]).sum(2) / L2[None], 0, 1)
        Q = A[None] + t[..., None] * V[None]
        out[i:i + 2000] = np.sqrt(((p[:, None, :] - Q) ** 2).sum(2)).min(1)
    return out


def clip_graph(g, bbox):
    """Sous-graphe des nœuds dans bbox (x0,y0,x1,y1) ; les arêtes coupant la frontière sont perdues."""
    x0, y0, x1, y1 = bbox
    c = G.Graph()
    keep = {n for n, p in g.nodes.items() if x0 <= p['x'] <= x1 and y0 <= p['y'] <= y1}
    for n in keep:
        c.add_node(*g.xy(n), g.nodes[n]['kind'], n)
    for a, b in g.edges:
        if a in keep and b in keep:
            c.add_edge(a, b)
    c.open = {n for n in g.open if n in keep}
    return c


def default_seed(ref, nodes=None):
    """Nœud de degré 2 le plus central parmi `nodes` (défaut : tout le graphe de référence)."""
    nodes = list(nodes) if nodes is not None else list(ref.nodes)
    xs = [ref.nodes[n]['x'] for n in nodes]; ys = [ref.nodes[n]['y'] for n in nodes]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    cands = [n for n in nodes if ref.degree(n) == 2] or nodes
    return min(cands, key=lambda n: math.dist(ref.xy(n), (cx, cy)))


def components(ref):
    """Composantes connexes (listes de nœuds) comptant au moins une arête."""
    seen, comps = set(), []
    for s in ref.nodes:
        if s in seen or ref.degree(s) == 0:
            continue
        comp, stack = [], [s]; seen.add(s)
        while stack:
            n = stack.pop(); comp.append(n)
            for m in ref.adj[n]:
                if m not in seen:
                    seen.add(m); stack.append(m)
        comps.append(comp)
    return comps


def farthest_uncovered(ref, out, min_dist):
    """Nœud de degré 2 de la référence le plus éloigné du tracé produit (None si tout est à moins de `min_dist`)."""
    nodes = [n for n in ref.nodes if ref.degree(n) == 2]
    if not nodes:
        return None
    d = dist_to_segments(np.array([ref.xy(n) for n in nodes]), out)
    i = int(d.argmax())
    return nodes[i] if d[i] >= min_dist else None


def compare(ref, out, tol, ref_full=None, bbox=None, extra_tols=(3.0, 6.0)):
    """Couverture / précision à `tol` px (et à chaque tolérance de `extra_tols` dans `at_tol`), carrefours retrouvés
    (à 3×tol) et écart médian entre un carrefour de référence et le carrefour posé le plus proche.
    La précision ne juge que les points produits dans `bbox` et les confronte à `ref_full` (toute l'annotation, pas
    seulement la zone) : ce qui est tracé hors zone n'a pas de référence et n'est pas noté."""
    Pr, Po = sample_edges(ref), sample_edges(out)
    in_zone = 1.0
    if bbox is not None and len(Po):
        x0, y0, x1, y1 = bbox
        keep = (Po[:, 0] >= x0) & (Po[:, 0] <= x1) & (Po[:, 1] >= y0) & (Po[:, 1] <= y1)
        in_zone = float(keep.mean()); Po = Po[keep]
    d_ref = dist_to_segments(Pr, out) if len(Pr) else None
    d_out = dist_to_segments(Po, ref_full if ref_full is not None else ref) if len(Po) else None
    cov = lambda t: float((d_ref <= t).mean()) if d_ref is not None else 0.0
    prec = lambda t: float((d_out <= t).mean()) if d_out is not None else 0.0
    ref_i = [n for n in ref.nodes if ref.degree(n) >= 3]
    out_i = [n for n in out.nodes if out.degree(n) >= 3]
    gaps = sorted(min((math.dist(ref.xy(n), out.xy(m)) for m in out_i), default=math.inf) for n in ref_i)
    matched = sum(1 for g in gaps if g <= 3 * tol)
    return {'tolerance_px': tol, 'coverage': round(cov(tol), 4), 'precision': round(prec(tol), 4),
            'at_tol': {str(t): {'coverage': round(cov(t), 4), 'precision': round(prec(t), 4)} for t in extra_tols},
            'ref_length_px': round(ref.total_length(), 1), 'out_length_px': round(out.total_length(), 1),
            'out_length_in_zone_px': round(out.total_length() * in_zone, 1),
            'ref_intersections': len(ref_i), 'out_intersections': len(out_i), 'intersections_matched': matched,
            'junction_gap_median_px': round(gaps[len(gaps) // 2], 2) if gaps and gaps[len(gaps) // 2] < math.inf else None}


def render(img, ref, out, path, margin=40, scale=1):
    x0, y0, x1, y1 = ref.bbox(margin)
    bx = out.bbox(margin) if out.nodes else (x0, y0, x1, y1)
    x0, y0, x1, y1 = int(min(x0, bx[0])), int(min(y0, bx[1])), int(max(x1, bx[2])), int(max(y1, bx[3]))
    im = img.crop((x0, y0, x1, y1)).convert('RGB')
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)
    T = lambda x, y: ((x - x0) * scale, (y - y0) * scale)
    for a, b in ref.edges:
        dr.line([T(*ref.xy(a)), T(*ref.xy(b))], fill=(40, 90, 255), width=3 * scale)
    for a, b in out.edges:
        dr.line([T(*out.xy(a)), T(*out.xy(b))], fill=(255, 40, 40), width=max(1, scale))
    for n, p in out.nodes.items():
        if out.degree(n) >= 3 or p['kind'] != 'normal':
            u, v = T(p['x'], p['y']); r = 4 * scale
            dr.ellipse([u - r, v - r, u + r, v + r], outline=(255, 160, 0), width=scale)
    im.save(path)


def load_reference(path, zone=None, margin=0.0):
    """Référence d'un projet maptracer/1 (graphe complet) ou d'un fichier maptracer-zones/1 (graphes corrigés à la main,
    bords = extrémités ouvertes). Renvoie (dict du fichier, graphe, bbox par défaut ou None)."""
    d = json.load(open(path, encoding='utf-8'))
    if d.get('format') != G.ZONES_FORMAT:
        return d, G.graph_from_project(G.load_project(path)), None
    zones = d.get('zones', [])
    if zone is not None:
        zs = [zones[zone]]
        b = zs[0]['bbox']
        bbox = [b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin]
    else:
        zs, bbox = zones, None
    g = G.Graph(); g.open = set(); off = 0
    for z in zs:
        zg = G.graph_from_zone(z)
        for n, p in zg.nodes.items():
            g.add_node(p['x'], p['y'], p['kind'], n + off)
        for a, b in zg.edges:
            g.add_edge(a + off, b + off)
        g.open |= {n + off for n in zg.open}
        off += (max(zg.nodes) if zg.nodes else 0) + 1
    return d, g, bbox


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project'); ap.add_argument('image')
    ap.add_argument('-o', '--out', default='trace_out')
    ap.add_argument('--model', default='oracle', help="'oracle' (faux modèle lu dans le tracé manuel) ou chemin d’un model.pt de train.py")
    ap.add_argument('--bbox', help='x0,y0,x1,y1 : limiter le suivi et la comparaison à cette zone (ex. zone de validation)')
    ap.add_argument('--zone', type=int, help='fichier maptracer-zones/1 : index (0…) de la zone corrigée servant de référence '
                    '(bbox = celui de la zone, élargi de --zone-margin) ; sans --zone, toutes les zones forment la référence')
    ap.add_argument('--zone-margin', type=float, default=0.0, help='marge (px) ajoutée autour du bbox de la zone (--zone)')
    ap.add_argument('--device', help='cuda / cpu pour le modèle appris')
    ap.add_argument('--step', type=float, default=4); ap.add_argument('--lookahead', type=float, help='défaut 4×pas')
    ap.add_argument('--sectors', type=int, default=32); ap.add_argument('--window', type=int, default=128)
    ap.add_argument('--thr', type=float, default=0.5, help='seuil d’activation d’un secteur')
    ap.add_argument('--side-sep', type=float, default=20, help='écart min (°) entre la continuation et une direction latérale')
    ap.add_argument('--confirm', type=int, default=2, help='observations consécutives avant d’ouvrir une branche latérale')
    ap.add_argument('--coast', type=int, default=2, help='pas tout droit tolérés sans réponse avant de conclure à une fin')
    ap.add_argument('--seed', action='append', help="x,y[,cap_deg] (répétable ; défaut : point de départ du projet) "
                    "ou 'auto' : un départ par composante connexe de la référence (utile avec --bbox)")
    ap.add_argument('--reseed', type=int, default=0, help='après le suivi, repartir jusqu’à N fois du point de la '
                    'référence le plus loin du tracé (mesure la couverture selon le nombre de départs)')
    ap.add_argument('--noise-deg', type=float, default=0.0, help='bruit gaussien sur les directions de l’oracle')
    ap.add_argument('--drop', type=float, default=0.0, help='probabilité d’oublier une direction (oracle)')
    ap.add_argument('--snap', type=float, help='oracle : distance max à l’axe avant d’être « perdu » (défaut 2×pas)')
    ap.add_argument('--render-scale', type=int, default=1)
    ap.add_argument('--rng', type=int, default=0)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()
    L = args.lookahead or 4 * args.step
    rng = random.Random(args.rng)

    proj, ref_full, zone_bbox = load_reference(args.project, args.zone, args.zone_margin)
    img = Image.open(args.image).convert('RGB')
    bbox = [float(v) for v in args.bbox.split(',')] if args.bbox else zone_bbox
    ref = clip_graph(ref_full, bbox) if bbox else ref_full
    trace_width = 3
    if args.model == 'oracle':
        model = OracleModel(ref_full, args.step, L, args.sectors, args.snap or 2 * args.step, args.noise_deg, args.drop, rng)
    else:
        if LearnedModel is None:
            raise SystemExit('PyTorch est requis pour un modèle appris (pip install torch torchvision)')
        model = LearnedModel(args.model, args.device)
        mt = model.meta
        args.step, args.sectors, args.window, trace_width = mt['step'], mt['sectors'], mt['window'], mt['trace_width']
        L = mt['lookahead']
        print(f"modèle {args.model} : fenêtre {args.window}, pas {args.step}, {args.sectors} secteurs, "
              f"époque {mt.get('epoch')}, appareil {model.device}")
    tr = Tracer(model, args.step, args.sectors, args.thr, img, args.window, trace_width=trace_width, map_size=img.size,
                coast=args.coast, side_sep_deg=args.side_sep, confirm=args.confirm, verbose=args.verbose, bounds=bbox)

    seeds = []
    for s in args.seed or []:
        if s == 'auto':
            seeds += [(*ref.xy(default_seed(ref, c)), None) for c in components(ref)]
            continue
        v = [float(t) for t in s.split(',')]
        seeds.append((v[0], v[1], math.radians(v[2]) if len(v) > 2 else None))
    if not seeds:
        st = next((n for n, p in ref.nodes.items() if p['kind'] == 'start' and ref.degree(n) > 0), None)
        if st is None:
            st = default_seed(ref)
        seeds.append((*ref.xy(st), None))
    for x, y, h in seeds:
        tr.seed(x, y, h)
    out = tr.run()
    tol = 1.5 * args.step
    cov_by_seed = [compare(ref, out, tol, ref_full, bbox)['coverage']]
    for _ in range(args.reseed):
        n = farthest_uncovered(ref, out, 6 * args.step)
        if n is None:
            break
        tr.seed(*ref.xy(n), None); seeds.append((*ref.xy(n), None))
        out = tr.run()
        cov_by_seed.append(compare(ref, out, tol, ref_full, bbox)['coverage'])

    os.makedirs(args.out, exist_ok=True)
    json.dump(out.to_dict(), open(os.path.join(args.out, 'trace_graph.json'), 'w'))
    g = (proj.get('map') or {}).get('georef')
    if g:
        json.dump(out.to_geojson(g), open(os.path.join(args.out, 'trace_graph.geojson'), 'w'))
    rep = compare(ref, out, tol, ref_full, bbox)
    reasons = {}
    for b in tr.branches:
        reasons[b['reason']] = reasons.get(b['reason'], 0) + 1
    rep.update({'steps': tr.steps, 'branches': len(tr.branches), 'branch_ends': reasons, 'branch_list': tr.branches,
                'seeds': [[round(x, 1), round(y, 1)] for x, y, _ in seeds], 'coverage_by_seed': cov_by_seed,
                'params': {k: v for k, v in vars(args).items() if k not in ('project', 'image', 'out')}})
    json.dump(rep, open(os.path.join(args.out, 'report.json'), 'w'), indent=1, ensure_ascii=False)
    render(img, ref, out, os.path.join(args.out, 'debug.png'), scale=args.render_scale)
    print(f"{tr.steps} pas, {len(tr.branches)} branches {reasons} ; {len(seeds)} départ(s) "
          f"(couverture par départ {[round(c, 3) for c in cov_by_seed]}) ; couverture {rep['coverage']:.1%}, "
          f"précision {rep['precision']:.1%}, intersections {rep['intersections_matched']}/{rep['ref_intersections']} "
          f"(trouvées {rep['out_intersections']}) → {args.out}/")


if __name__ == '__main__':
    main()
