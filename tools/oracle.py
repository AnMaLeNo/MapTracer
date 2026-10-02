#!/usr/bin/env python3
"""Générateur d'exemples « oracle » : le tracé manuel est la vérité, on en déduit des milliers d'états (position, cap)
et, pour chacun, la fenêtre tournée cap-vers-le-haut, le canal « déjà tracé » et les directions où la galerie continue.

Pour chaque arête du graphe, dans les deux sens, une position tous les --spacing px ; chaque position est dupliquée
--aug fois avec un décalage latéral (±--offset px) et une erreur de cap (±--heading-noise °), pour apprendre au modèle à
se recentrer. Cible : secteurs (K=--sectors) contenant un point de l'axe situé à --lookahead px le long du graphe,
une branche = un secteur ; aucun secteur actif ⇔ cul-de-sac à moins d'un pas (--step).

Sortie : <out>/map/NNNNNN.png (RGB, fenêtre tournée), <out>/trace/NNNNNN.png (L, déjà tracé), <out>/samples.jsonl,
<out>/meta.json, <out>/graph.json ; avec --holdout x0,y0,x1,y1 les états dont l'axe tombe dans ce rectangle vont dans
samples_val.jsonl (découpage spatial, pas aléatoire).

Exemple : python3 tools/oracle.py projet.maptracer.json maps/nexus_alkhemia_2011.jpg -o oracle/ --window 128 --step 4
"""
import argparse, json, math, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
import mt_graph as G

Image.MAX_IMAGE_PIXELS = None


def iter_states(g, spacing, rng):
    """(a, b, t) pour chaque arête dans les deux sens, positions régulières avec une phase aléatoire."""
    for a, b in g.edges:
        L = g.length(a, b)
        if L <= 0:
            continue
        for u, v in ((a, b), (b, a)):
            n = max(1, int(L // spacing))
            phase = rng.random() * (L / n)
            for i in range(n):
                d = phase + i * (L / n)
                if d >= L:
                    continue
                yield u, v, d / L


def make_sample(g, img, a, b, t, args, rng, perturb):
    ax, ay = g.lerp(a, b, t)
    bx, by = g.xy(b); ax0, ay0 = g.xy(a)
    heading0 = math.atan2(by - ay0, bx - ax0)
    off = rng.uniform(-args.offset, args.offset) if perturb else 0.0
    dh = math.radians(rng.uniform(-args.heading_noise, args.heading_noise)) if perturb else 0.0
    px = ax - math.sin(heading0) * off; py = ay + math.cos(heading0) * off     # décalage latéral (droite = +)
    heading = heading0 + dh
    angles, pts = G.oracle_directions(g, a, b, t, px, py, heading, args.lookahead, args.step, skip_open=True,
                                      near=args.near, bend_deg=args.bend_deg)
    if angles is None:
        return None
    W = args.window
    crop = G.crop_rotated(img, px, py, heading, W)
    segs, extra = g.traced_edges_behind(a, b, t, W, rng, L=args.lookahead)
    traced = G.render_traced(segs, px, py, heading, W, args.trace_width)
    sectors = sorted({G.sector_of(an, args.sectors) for an in angles})
    row = {
        'window': W, 'step': args.step, 'lookahead': args.lookahead, 'sectors_k': args.sectors,
        'map_pos': [round(px, 2), round(py, 2)], 'axis_pos': [round(ax, 2), round(ay, 2)],
        'heading_deg': round(math.degrees(heading) % 360, 2), 'offset_px': round(off, 2),
        'heading_noise_deg': round(math.degrees(dh), 2),
        'edge': [a, b], 't': round(t, 4),
        'targets': [{'x': round(q['x'], 2), 'y': round(q['y'], 2), 'angle_deg': round(math.degrees(an), 2),
                     'dead_end': q['dead']} for q, an in zip(pts, angles)],
        'sectors': sectors, 'label': G.soft_label(angles, args.sectors), 'end': not sectors,
        'traced_extra': extra,
    }
    return crop, traced, row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project'); ap.add_argument('image')
    ap.add_argument('-o', '--out', default='oracle')
    ap.add_argument('--window', type=int, default=128, help='taille de la fenêtre (px carte)')
    ap.add_argument('--step', type=float, default=4, help='pas fixe du suivi (px) : cul-de-sac si fin < 1 pas')
    ap.add_argument('--lookahead', type=float, help='distance de visée (px, défaut 4×pas)')
    ap.add_argument('--near', type=float, help='rayon (px) autour d’un carrefour / virage serré où la visée le traverse (défaut 3×pas)')
    ap.add_argument('--bend-deg', type=float, default=45, help='virage considéré comme serré (°) : la visée s’y arrête')
    ap.add_argument('--sectors', type=int, default=32)
    ap.add_argument('--spacing', type=float, help='distance entre positions le long des arêtes (défaut = pas)')
    ap.add_argument('--aug', type=int, default=2, help='copies perturbées par position (en plus de la copie exacte)')
    ap.add_argument('--offset', type=float, help='décalage latéral max (px, défaut 0,75×pas)')
    ap.add_argument('--heading-noise', type=float, default=25, help='erreur de cap max (°)')
    ap.add_argument('--trace-width', type=int, default=3, help='épaisseur du canal déjà tracé (px)')
    ap.add_argument('--holdout', help='x0,y0,x1,y1 (px carte) : zone de validation')
    ap.add_argument('--no-images', action='store_true', help='n’écrire que le JSONL')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    args.lookahead = args.lookahead or 4 * args.step
    args.spacing = args.spacing or args.step
    args.near = args.near if args.near is not None else 3 * args.step
    args.offset = args.offset if args.offset is not None else 0.75 * args.step
    rng = random.Random(args.seed)

    proj = G.load_project(args.project)
    g = G.graph_from_project(proj)
    img = Image.open(args.image).convert('RGB')
    if proj.get('map') and (img.width, img.height) != (proj['map']['width'], proj['map']['height']):
        raise SystemExit(f"image {img.size} ≠ carte du projet {proj['map']['width']}×{proj['map']['height']}")
    hold = [float(v) for v in args.holdout.split(',')] if args.holdout else None
    os.makedirs(args.out, exist_ok=True)
    if not args.no_images:
        os.makedirs(os.path.join(args.out, 'map'), exist_ok=True)
        os.makedirs(os.path.join(args.out, 'trace'), exist_ok=True)
    f_tr = open(os.path.join(args.out, 'samples.jsonl'), 'w', encoding='utf-8')
    f_va = open(os.path.join(args.out, 'samples_val.jsonl'), 'w', encoding='utf-8') if hold else None
    n = {'train': 0, 'val': 0, 'end': 0, 'multi': 0, 'skipped_open': 0}
    i = 0
    for a, b, t in iter_states(g, args.spacing, rng):
        for k in range(1 + args.aug):
            smp = make_sample(g, img, a, b, t, args, rng, perturb=k > 0)
            if smp is None:
                n['skipped_open'] += 1; continue
            crop, traced, row = smp
            row['sample'] = i
            if not args.no_images:
                name = f'{i:06d}.png'
                crop.save(os.path.join(args.out, 'map', name)); traced.save(os.path.join(args.out, 'trace', name))
                row['image'] = f'map/{name}'; row['trace'] = f'trace/{name}'
            ax, ay = row['axis_pos']
            val = hold and hold[0] <= ax <= hold[2] and hold[1] <= ay <= hold[3]
            (f_va if val else f_tr).write(json.dumps(row, ensure_ascii=False) + '\n')
            n['val' if val else 'train'] += 1
            n['end'] += row['end']; n['multi'] += len(row['sectors']) > 1
            i += 1
    f_tr.close()
    if f_va:
        f_va.close()
    json.dump({'params': vars(args), 'graph_length_px': round(g.total_length(), 1), 'counts': n,
               'conventions': 'secteur 0 = devant, horaire ; angle absolu = cap + angle relatif ; end ⇔ aucun secteur'},
              open(os.path.join(args.out, 'meta.json'), 'w'), indent=1, ensure_ascii=False)
    json.dump(g.to_dict(), open(os.path.join(args.out, 'graph.json'), 'w'))
    print(f"{i} exemples (train {n['train']}, val {n['val']}) ; {n['end']} fins, {n['multi']} multi-directions ; "
          f"{n['skipped_open']} états ignorés (amorces en attente) ; graphe {g.total_length():.0f} px, {len(g.edges)} arêtes → {args.out}/")


if __name__ == '__main__':
    main()
