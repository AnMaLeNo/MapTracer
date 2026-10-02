"""Carte synthétique (galeries à double trait + texte parasite) et projet MapTracer correspondant."""
import json, sys
from PIL import Image, ImageDraw, ImageFont

W = 1200
P = {1: (100, 600), 2: (250, 600), 3: (400, 600), 4: (400, 450), 5: (550, 600), 6: (400, 300), 7: (400, 150),
     8: (700, 600), 9: (700, 450), 10: (850, 700), 11: (700, 300), 12: (950, 850), 13: (900, 1000), 14: (500, 1000),
     15: (325, 800), 16: (325, 600)}
edges = [(1, 2), (2, 16), (16, 3), (3, 4), (3, 5), (4, 6), (6, 7), (5, 8), (8, 9), (8, 10), (9, 11), (11, 6),
         (10, 12), (12, 13), (13, 14), (14, 15), (15, 16)]
im = Image.new('RGB', (W, W), (245, 240, 225))
d = ImageDraw.Draw(im)
for a, b in edges:
    d.line([P[a], P[b]], fill=(30, 30, 30), width=12)
for a, b in edges:
    d.line([P[a], P[b]], fill=(245, 240, 225), width=6)
for k in P:
    d.ellipse([P[k][0] - 3, P[k][1] - 3, P[k][0] + 3, P[k][1] + 3], fill=(245, 240, 225))
try:
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
except OSError:
    f = ImageFont.load_default()
d.text((430, 380), 'Rue de la Tombe-Issoire', fill=(120, 20, 20), font=f)
d.text((720, 520), 'Salle Z', fill=(20, 20, 120), font=f)
d.line([(600, 100), (1100, 300)], fill=(200, 60, 60), width=2)   # trait parasite (type « surface »)
im.save(sys.argv[1])

w = 128
ev = [{'t': 'start', 'id': 1, 'x': 100, 'y': 600}]
pl = lambda i, frm, kind='normal': {'t': 'place', 'id': i, 'from': frm, 'x': P[i][0], 'y': P[i][1], 'kind': kind, 'window': w}
ev += [pl(2, 1), {'t': 'advance'}, pl(3, 2, 'intersection'), pl(4, 3), pl(5, 3), {'t': 'advance'},
       pl(6, 4), pl(7, 6), {'t': 'end'},
       pl(8, 5, 'intersection'), pl(9, 8), pl(10, 8), {'t': 'advance'},
       pl(11, 9), {'t': 'join', 'to': 6, 'retype': True},
       pl(12, 10), pl(13, 12), pl(14, 13), pl(15, 14),
       {'t': 'split', 'id': 16, 'from': 2, 'to': 3, 'x': 325, 'y': 600},
       {'t': 'finish'}]
proj = {'format': 'maptracer/1', 'name': 'synth', 'map': {'id': 'synth', 'width': W, 'height': W},
        'settings': {'window': w, 'allowOutside': True}, 'events': ev}
json.dump(proj, open(sys.argv[2], 'w'))
print('ok', len(ev), 'events')
