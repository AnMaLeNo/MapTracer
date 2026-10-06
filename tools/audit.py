#!/usr/bin/env python3
"""Détecteur d'anomalies d'annotation : un modèle déjà entraîné rejoue chaque point annoté et signale ses désaccords.

    python3 tools/audit.py PROJET_OU_ZONES… IMAGE --model models/v5-z6-g1/model.pt [-o audit.json] [--thr 0.5] [--device cuda]

Le modèle n'est pas la vérité : un désaccord est soit une erreur d'annotation (cul-de-sac oublié, galerie annotée à côté
de l'axe, branche non annotée), soit un endroit où le modèle a justement besoin de l'exemple. C'est à l'humain de trancher
dans l'app (onglet « Anomalies ») ; rien n'est corrigé automatiquement.

Pour chaque état « sur l'axe » (position régulière le long de chaque arête, dans les deux sens, canal « déjà tracé » = chemin
d'arrivée uniquement, sans tirage aléatoire) on compare les directions du modèle aux directions de l'oracle :

  end_missed       extrémité non marquée F (ouverte) où le modèle ne voit aucune suite → cul-de-sac probablement oublié
  false_end        cul-de-sac (F) où le modèle voit une suite nette → F posé trop tôt, ou galerie réelle à vérifier
  branch_missed    direction vue par le modèle qu'aucune galerie annotée n'explique → branche oubliée ou faux positif
  direction_missed galerie annotée que le modèle ne voit pas du tout → point hors axe, trait d'un autre étage, ou vrai manque
                   d'apprentissage (classe la plus bruyante : près de carrefours serrés la visée traverse deux nœuds et vise
                   des branches que le modèle n'a pas à voir ; on ne la garde que si deux états consécutifs la confirment)

Score ∈ [0,1] = confiance du modèle dans le désaccord. Les anomalies d'un même type à moins de `--cluster` px sont
regroupées (score max). Sortie : {anomalies: [...], stats: {...}} ; l'app lit le même JSON via /api/audit."""
import argparse, json, math, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mt_graph as G

TYPES = ('end_missed', 'false_end', 'branch_missed', 'direction_missed')
BEHIND = math.radians(135)      # une direction « derrière » n'est jamais une continuation


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def states(g, spacing):
    """(a, b, t) à positions régulières le long de chaque arête, dans les deux sens, phase nulle (déterministe)."""
    for a, b in g.edges:
        L = g.length(a, b)
        if L <= 0:
            continue
        n = max(1, int(L // spacing))
        for u, v in ((a, b), (b, a)):
            for i in range(n):
                yield u, v, (i * (L / n)) / L


def end_states(g, step):
    """Pour chaque nœud de degré 1 : l'état arrivant dessus (cap vers le nœud, à moins d'un pas) → (a, b, t, nœud)."""
    for n in g.nodes:
        if g.degree(n) != 1:
            continue
        a = next(iter(g.adj[n]))
        L = g.length(a, n)
        if L <= 0:
            continue
        t = max(0.0, 1 - min(step * 0.5, L) / L)
        yield a, n, t, n


class Batcher:
    """Accumule des états et appelle le réseau par lots (le GPU ou le CPU y gagnent beaucoup)."""

    def __init__(self, model, img, batch=64):
        import torch
        from model import to_tensor, normalize
        self.torch, self.to_tensor, self.normalize = torch, to_tensor, normalize
        self.model, self.img, self.batch = model, img, batch
        self.W, self.tw = model.meta['window'], model.meta['trace_width']
        self.items = []

    def add(self, px, py, heading, segs, payload):
        crop = G.crop_rotated(self.img, px, py, heading, self.W)
        traced = G.render_traced(segs, px, py, heading, self.W, self.tw)
        self.items.append((self.to_tensor(crop, traced), payload))

    def flush(self):
        out = []
        torch = self.torch
        with torch.no_grad():
            for i in range(0, len(self.items), self.batch):
                chunk = self.items[i:i + self.batch]
                x = self.normalize(torch.stack([c for c, _ in chunk]).to(self.model.device))
                probs = torch.sigmoid(self.model.net(x)).cpu().tolist()
                out += [(p, pl) for p, (_, pl) in zip(probs, chunk)]
        self.items = []
        return out


def peaks_fwd(probs, K, thr):
    return [(rel, sc) for rel, sc in G.peaks(probs, K, thr) if abs(rel) < BEHIND]


def sector_prob(probs, angle, K, halo=1):
    """Probabilité max dans le secteur de `angle` et ses `halo` voisins."""
    s = G.sector_of(angle, K)
    return max(probs[(s + d) % K] for d in range(-halo, halo + 1))


def audit_graph(g, img, model, thr=0.5, spacing=None, cluster=8.0, match_deg=30.0, weak=0.15, hook=None, source=''):
    """Anomalies d'un graphe annoté (projet ou zone) : voir l'en-tête du module. `hook(done, total)` pour l'avancement."""
    mt = model.meta
    K, step, L = mt['sectors'], mt['step'], mt['lookahead']
    near = mt.get('dataset', {}).get('near') or 3 * step
    spacing = spacing or 2 * step
    match = math.radians(match_deg)
    bt = Batcher(model, img)
    plan = []
    for a, b, t in states(g, spacing):
        plan.append(('edge', a, b, t, None))
    for a, b, t, n in end_states(g, step):
        plan.append(('end', a, b, t, n))
    total, done = len(plan), 0
    raw = []
    for i, (what, a, b, t, n) in enumerate(plan):
        px, py = g.lerp(a, b, t)
        ax, ay = g.xy(a); bx, by = g.xy(b)
        heading = math.atan2(by - ay, bx - ax)
        segs, _ = g.traced_edges_behind(a, b, t, mt['window'], p_explore=1.0, p_other=0.0, L=L)
        if what == 'edge':
            angles, pts = G.oracle_directions(g, a, b, t, px, py, heading, L, step, skip_open=False, near=near)
            bt.add(px, py, heading, segs, ('edge', a, b, t, px, py, heading, angles, pts))
        else:
            bt.add(px, py, heading, segs, ('end', a, b, t, px, py, heading, n, n in g.open))
        if len(bt.items) >= bt.batch or i == total - 1:
            for probs, pl in bt.flush():
                raw += _judge(probs, pl, K, thr, match, weak, g)
            done = i + 1
            if hook:
                hook(done, total)
    anomalies = [r for r in _cluster(raw, cluster) if r['type'] != 'direction_missed' or r['n'] >= 2]
    anomalies.sort(key=lambda r: -r['score'])
    for r in anomalies:
        r['source'] = source
    stats = {'states': total, 'anomalies': len(anomalies)} | {k: sum(1 for r in anomalies if r['type'] == k) for k in TYPES}
    return anomalies, stats


def _judge(probs, pl, K, thr, match, weak, g):
    out = []
    if pl[0] == 'end':
        _, a, b, t, px, py, heading, n, is_open = pl
        pk = peaks_fwd(probs, K, thr)
        p_fwd = max([sc for _, sc in pk], default=max(probs[s] for s in range(K) if abs(_wrap(2 * math.pi * s / K)) < BEHIND))
        if is_open and not pk:
            out.append({'type': 'end_missed', 'x': g.xy(n)[0], 'y': g.xy(n)[1], 'score': 1 - p_fwd, 'node': n,
                        'heading_deg': math.degrees(heading) % 360, 'model_deg': None,
                        'why': f'extrémité ouverte (pas de F) ; le modèle ne voit aucune suite (p max {p_fwd:.2f})'})
        elif not is_open and pk:
            rel, sc = max(pk, key=lambda p: p[1])
            out.append({'type': 'false_end', 'x': g.xy(n)[0], 'y': g.xy(n)[1], 'score': sc, 'node': n,
                        'heading_deg': math.degrees(heading) % 360, 'model_deg': math.degrees(heading + rel) % 360,
                        'why': f'cul-de-sac (F) ; le modèle voit une suite à {math.degrees(rel):+.0f}° (p {sc:.2f})'})
        return out
    _, a, b, t, px, py, heading, angles, pts = pl
    pk = peaks_fwd(probs, K, thr)
    targets = [an for an in (angles or []) if abs(an) < BEHIND]
    # branches vues par le modèle sans galerie annotée correspondante
    for rel, sc in pk:
        if all(abs(_wrap(rel - an)) > match for an in targets):
            if not targets and angles is not None and abs(rel) < math.radians(45):   # juste avant un F : c'est le F qu'on conteste
                out.append({'type': 'false_end', 'x': px, 'y': py, 'score': sc, 'node': None,
                            'heading_deg': math.degrees(heading) % 360, 'model_deg': math.degrees(heading + rel) % 360,
                            'why': f'cul-de-sac annoté juste devant ; le modèle voit la galerie continuer (p {sc:.2f})'})
                continue
            out.append({'type': 'branch_missed', 'x': px, 'y': py, 'score': sc, 'node': None,
                        'heading_deg': math.degrees(heading) % 360, 'model_deg': math.degrees(heading + rel) % 360,
                        'why': f'le modèle voit une galerie à {math.degrees(rel):+.0f}° (p {sc:.2f}) ; rien d\'annoté dans cette direction'})
    # galeries annotées que le modèle ne voit pas du tout
    for an, q in zip(angles or [], pts or []):
        if abs(an) >= BEHIND or (q.get('dead') and q.get('open')):
            continue
        p = sector_prob(probs, an, K)
        if p < weak:
            out.append({'type': 'direction_missed', 'x': px, 'y': py, 'score': 1 - p, 'node': None,
                        'heading_deg': math.degrees(heading) % 360, 'model_deg': math.degrees(heading + an) % 360,
                        'why': f'galerie annotée à {math.degrees(an):+.0f}° ; le modèle n\'y voit rien (p {p:.2f})'})
    return out


def _cluster(raw, radius):
    """Regroupe les anomalies de même type proches (score max, position de la meilleure, effectif)."""
    out = []
    for r in sorted(raw, key=lambda r: -r['score']):
        for o in out:
            if o['type'] == r['type'] and math.hypot(o['x'] - r['x'], o['y'] - r['y']) <= radius and \
                    (o['model_deg'] is None or r['model_deg'] is None or abs(_wrap(math.radians(o['model_deg'] - r['model_deg']))) < math.radians(45)):
                o['n'] += 1
                break
        else:
            out.append({**r, 'n': 1})
    for o in out:
        o['x'], o['y'], o['score'] = round(o['x'], 1), round(o['y'], 1), round(float(o['score']), 3)
        o['heading_deg'] = round(o['heading_deg'], 1)
        if o['model_deg'] is not None:
            o['model_deg'] = round(o['model_deg'], 1)
    return out


def audit_files(paths, img, model, **kw):
    """Audit de plusieurs fichiers (projets / zones) : anomalies concaténées, source = `fichier` ou `fichier#zone`."""
    anomalies, stats = [], {}
    for p in paths:
        _, graphs = G.load_graphs(p)
        for name, g, _ in graphs:
            an, st = audit_graph(g, img, model, source=name, **kw)
            anomalies += an; stats[name] = st
    anomalies.sort(key=lambda r: -r['score'])
    return anomalies, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+', metavar='FICHIER… IMAGE', help='projets .maptracer.json / zones .mapzones.json puis l’image')
    ap.add_argument('--model', required=True)
    ap.add_argument('-o', '--out', default='audit.json')
    ap.add_argument('--thr', type=float, default=0.5, help='seuil d’activation d’une direction')
    ap.add_argument('--weak', type=float, default=0.15, help='en dessous : le modèle « ne voit pas » la galerie annotée')
    ap.add_argument('--spacing', type=float, help='distance entre états le long des arêtes (défaut 2×pas)')
    ap.add_argument('--cluster', type=float, default=8.0, help='rayon (px) de regroupement des anomalies de même type')
    ap.add_argument('--device')
    args = ap.parse_args()
    from PIL import Image
    from model import LearnedModel
    img = Image.open(args.inputs[-1]).convert('RGB')
    model = LearnedModel(args.model, args.device)
    t0 = time.time()
    anomalies, stats = audit_files(args.inputs[:-1], img, model, thr=args.thr, weak=args.weak, spacing=args.spacing,
                                   cluster=args.cluster, hook=lambda d, t: print(f'\r  {d}/{t} états', end='', flush=True))
    print()
    doc = {'format': 'maptracer-audit/1', 'model': os.path.basename(os.path.dirname(os.path.abspath(args.model))),
           'thr': args.thr, 'weak': args.weak, 'inputs': args.inputs[:-1], 'anomalies': anomalies, 'stats': stats,
           'elapsed_s': round(time.time() - t0, 1)}
    json.dump(doc, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    tot = {k: sum(1 for r in anomalies if r['type'] == k) for k in TYPES}
    print(f'{len(anomalies)} anomalies ({", ".join(f"{k} {v}" for k, v in tot.items())}) sur '
          f'{sum(s["states"] for s in stats.values())} états, {time.time() - t0:.0f} s → {args.out}')
    for r in anomalies[:15]:
        print(f'  {r["score"]:.2f} {r["type"]:17s} ({r["x"]:.0f}, {r["y"]:.0f}) ×{r["n"]} {r["source"]} — {r["why"]}')


if __name__ == '__main__':
    main()
