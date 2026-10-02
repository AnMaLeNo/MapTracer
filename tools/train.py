"""Entraîne le suiveur de galeries (ResNet-18 à 4 canaux, 32 secteurs multi-label) sur un dossier produit par oracle.py.

    python3 tools/train.py oracle/ -o runs/v1 --epochs 15 --bs 64 --lr 3e-4

Données : oracle/samples.jsonl (train) et oracle/samples_val.jsonl (validation, zone --holdout de oracle.py), images
map/ et trace/. Tout est chargé en RAM en uint8 (≈ 65 ko par exemple à 128 px).
Perte   : BCE sur les étiquettes douces (une probabilité par secteur).
Augment.: miroir gauche↔droite (étiquette miroir), gigue de luminosité/contraste sur les canaux RGB.
Métriques (validation, seuil --thr) : les secteurs actifs sont regroupés en directions (comme trace.py) et comparés aux
directions cibles à ±--tol-deg → précision/rappel des directions, exactitude « cul-de-sac », rappel aux intersections
(≥ 2 cibles), erreur angulaire moyenne des directions appariées. Le meilleur modèle (F1 directions) est sauvegardé dans
<out>/model.pt, l'historique dans <out>/history.json.
"""
import argparse, json, math, os, random, sys, time

import torch
import torch.nn.functional as F
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M                      # noqa: E402
import mt_graph as G                   # noqa: E402


def load_split(root, name, limit=None):
    path = os.path.join(root, name)
    if not os.path.exists(path):
        return [], None, None
    rows = [json.loads(l) for l in open(path, encoding='utf-8')]
    if limit:
        rows = rows[:limit]
    if not rows:
        return [], None, None
    K, W = rows[0]['sectors_k'], rows[0]['window']
    X = torch.empty((len(rows), 4, W, W), dtype=torch.uint8)
    Y = torch.empty((len(rows), K), dtype=torch.float32)
    for i, r in enumerate(rows):
        X[i] = M.to_tensor(Image.open(os.path.join(root, r['image'])), Image.open(os.path.join(root, r['trace'])))
        Y[i] = torch.tensor(r['label'])
    return rows, X, Y


def augment(x, y, K, rng):
    """x uint8 B×4×W×W, y B×K → (float normalisé, y) avec miroir et gigue photométrique par exemple."""
    B = x.shape[0]
    flip = torch.rand(B, device=x.device) < 0.5
    x = torch.where(flip.view(B, 1, 1, 1), x.flip(-1), x)
    y = torch.where(flip.view(B, 1), M.mirror_label(y, K), y)
    x = M.normalize(x)
    gain = (1 + 0.3 * (torch.rand(B, 1, 1, 1, device=x.device) - 0.5))
    bias = 0.3 * (torch.rand(B, 1, 1, 1, device=x.device) - 0.5)
    x = torch.cat([x[:, :3] * gain + bias, x[:, 3:]], 1)
    return x, y


def direction_metrics(rows, probs, K, thr, tol_deg):
    tp = fp = fn = 0
    end_ok = n_end = 0
    inter_tp = inter_n = 0
    errs = []
    tol = math.radians(tol_deg)
    for r, p in zip(rows, probs):
        pred = [a for a, _ in G.peaks(p, K, thr)]
        tgt = [math.radians(t['angle_deg']) for t in r['targets']]
        used = set()
        matched = 0
        for a in tgt:
            best = None
            for j, b in enumerate(pred):
                if j in used:
                    continue
                d = abs((a - b + math.pi) % (2 * math.pi) - math.pi)
                if d <= tol and (best is None or d < best[0]):
                    best = (d, j)
            if best:
                used.add(best[1]); matched += 1; errs.append(best[0])
        tp += matched; fn += len(tgt) - matched; fp += len(pred) - matched
        if r['end']:
            n_end += 1; end_ok += not pred
        if len(tgt) >= 2:
            inter_n += len(tgt); inter_tp += matched
    prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
    return {'dir_precision': round(prec, 4), 'dir_recall': round(rec, 4),
            'dir_f1': round(2 * prec * rec / max(1e-9, prec + rec), 4),
            'end_accuracy': round(end_ok / n_end, 4) if n_end else None, 'n_end': n_end,
            'intersection_recall': round(inter_tp / inter_n, 4) if inter_n else None,
            'mean_angle_err_deg': round(math.degrees(sum(errs) / len(errs)), 2) if errs else None, 'n': len(rows)}


@torch.no_grad()
def evaluate(net, X, Y, rows, K, dev, bs, thr, tol):
    net.eval()
    loss, probs = 0.0, []
    for i in range(0, len(X), bs):
        xb = M.normalize(X[i:i + bs].to(dev)); yb = Y[i:i + bs].to(dev)
        out = net(xb)
        loss += F.binary_cross_entropy_with_logits(out, yb, reduction='sum').item() / K
        probs.extend(torch.sigmoid(out).cpu().tolist())
    m = direction_metrics(rows, probs, K, thr, tol)
    m['bce'] = round(loss / len(X), 5)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data', help='dossier produit par oracle.py')
    ap.add_argument('-o', '--out', default='runs/v1')
    ap.add_argument('--epochs', type=int, default=15)
    ap.add_argument('--bs', type=int, default=64)
    ap.add_argument('--lr', type=float, default=3e-4)
    ap.add_argument('--wd', type=float, default=1e-4)
    ap.add_argument('--thr', type=float, default=0.5)
    ap.add_argument('--tol-deg', type=float, default=17.0, help='tolérance d’appariement des directions (1,5 secteur)')
    ap.add_argument('--device', help='cuda / cpu (défaut : cuda si dispo)')
    ap.add_argument('--no-pretrained', action='store_true')
    ap.add_argument('--no-aug', action='store_true')
    ap.add_argument('--limit', type=int, help='n’utiliser que les N premiers exemples (test rapide)')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed); random.seed(a.seed)
    dev = M.pick_device(a.device)
    t0 = time.time()
    rows_tr, Xtr, Ytr = load_split(a.data, 'samples.jsonl', a.limit)
    rows_va, Xva, Yva = load_split(a.data, 'samples_val.jsonl', a.limit)
    if not rows_tr:
        raise SystemExit('aucun exemple d’entraînement')
    K, W = rows_tr[0]['sectors_k'], rows_tr[0]['window']
    meta_ds = json.load(open(os.path.join(a.data, 'meta.json')))['params']
    print(f"{len(rows_tr)} train, {len(rows_va)} val, fenêtre {W}, {K} secteurs, chargés en {time.time() - t0:.0f}s ; "
          f"appareil {dev}", flush=True)

    net = M.build_net(K, pretrained=not a.no_pretrained).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=a.wd)
    steps = a.epochs * math.ceil(len(Xtr) / a.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps, pct_start=0.15)
    os.makedirs(a.out, exist_ok=True)
    meta = {'sectors': K, 'window': W, 'step': meta_ds['step'], 'lookahead': meta_ds['lookahead'],
            'trace_width': meta_ds['trace_width'], 'thr': a.thr, 'train_args': vars(a), 'dataset': meta_ds}
    hist, best = [], None
    rng = torch.Generator(device='cpu').manual_seed(a.seed)
    for ep in range(1, a.epochs + 1):
        net.train(); t1 = time.time(); tot = 0.0
        perm = torch.randperm(len(Xtr), generator=rng)
        for i in range(0, len(perm), a.bs):
            idx = perm[i:i + a.bs]
            xb, yb = Xtr[idx].to(dev, non_blocking=True), Ytr[idx].to(dev)
            if a.no_aug:
                xb = M.normalize(xb)
            else:
                xb, yb = augment(xb, yb, K, rng)
            loss = F.binary_cross_entropy_with_logits(net(xb), yb)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step(); sched.step()
            tot += loss.item() * len(idx)
        rec = {'epoch': ep, 'train_bce': round(tot / len(Xtr), 5), 'time_s': round(time.time() - t1, 1)}
        if rows_va:
            rec['val'] = evaluate(net, Xva, Yva, rows_va, K, dev, a.bs, a.thr, a.tol_deg)
            score = rec['val']['dir_f1']
        else:
            score = -rec['train_bce']
        hist.append(rec)
        if best is None or score > best:
            best = score
            M.save_checkpoint(os.path.join(a.out, 'model.pt'), net, {**meta, 'epoch': ep, 'val': rec.get('val')})
            rec['saved'] = True
        json.dump(hist, open(os.path.join(a.out, 'history.json'), 'w'), indent=1)
        v = rec.get('val')
        print(f"ép {ep:2d}  train bce {rec['train_bce']:.4f}  " +
              (f"val bce {v['bce']:.4f}  dir P {v['dir_precision']:.3f} R {v['dir_recall']:.3f} F1 {v['dir_f1']:.3f}  "
               f"fin {v['end_accuracy']}  inter R {v['intersection_recall']}  err {v['mean_angle_err_deg']}°  " if v else '') +
              f"{rec['time_s']}s" + ('  *' if rec.get('saved') else ''), flush=True)
    print(f"meilleur score {best:.4f} → {a.out}/model.pt")


if __name__ == '__main__':
    main()
