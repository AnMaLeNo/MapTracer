#!/usr/bin/env python3
"""Vérifie la cohérence d'un export MapTracer avec les définitions du graphe :
  - intersection = nœud relié à au moins 3 nœuds distincts ; cul-de-sac = nœud relié à un seul nœud ;
  - le type posé dans l'outil (« intersection » = pense-bête pour revenir) peut différer, on le signale.
Usage : python3 tools/check_graph.py mon_projet.maptracer.json
"""
import json, sys, collections


def main():
    proj = json.load(open(sys.argv[1], encoding='utf-8'))
    d = proj['derived']; pts = {p['id']: p for p in d['points']}
    nb = collections.defaultdict(set); seen = set()
    for e in d['edges']:
        a, b = e['from'], e['to']
        if a == b: print(f'  boucle sur le point {a}'); continue
        if (min(a, b), max(a, b)) in seen: print(f'  arête en double {a}-{b}')
        seen.add((min(a, b), max(a, b))); nb[a].add(b); nb[b].add(a)
    out = collections.defaultdict(list)
    for p in d['points']:
        i, deg, term, kind = p['id'], len(nb[p['id']]), p.get('terminal') or '', p['kind']
        tag = f"n°{p['order']} (id {i}, {p['x']},{p['y']}) degré {deg} type={kind} terminal={term or '—'}"
        if deg == 0: out['isolé'].append(tag)
        if kind == 'intersection' and deg < 3: out['marqué intersection mais degré < 3'].append(tag)
        if kind != 'intersection' and deg >= 3: out['degré ≥ 3 mais pas marqué intersection'].append(tag)
        if term.startswith('end') and deg != 1: out['« cul-de-sac » (F) mais degré ≠ 1'].append(tag)
        if deg == 1 and p['kind'] != 'start' and not term.startswith('end') and not term.startswith('join') and term != '':
            out['degré 1 sans F'].append(tag)
        if deg == 1 and not term: out['degré 1, jamais quitté (en attente ?)'].append(tag)
    n = collections.Counter(len(nb[i]) for i in pts)
    print(f"{len(pts)} points, {len(seen)} segments ; répartition des degrés : {dict(sorted(n.items()))}")
    for k, v in out.items():
        print(f'\n{k} : {len(v)}'); [print('  ', t) for t in v]
    if not out: print('Aucune incohérence.')


if __name__ == '__main__':
    main()
