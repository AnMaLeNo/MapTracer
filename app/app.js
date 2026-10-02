/* MapTracer — annotation pas-à-pas de galeries pour constituer un jeu d'entraînement.
   Source de vérité : la liste ordonnée `events` (replay → état dérivé). Annuler = retirer le dernier événement. */
'use strict';

const $ = id => document.getElementById(id);
const FORMAT = 'maptracer/1';

/* ---------- persistance (IndexedDB) ---------- */
const idb = {
  db: null,
  open() {
    return new Promise((res, rej) => {
      const r = indexedDB.open('maptracer', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('kv');
      r.onsuccess = () => { this.db = r.result; res(); };
      r.onerror = () => rej(r.error);
    });
  },
  get(k) { return new Promise((res, rej) => { const t = this.db.transaction('kv').objectStore('kv').get(k); t.onsuccess = () => res(t.result); t.onerror = () => rej(t.error); }); },
  set(k, v) { return new Promise((res, rej) => { const t = this.db.transaction('kv', 'readwrite').objectStore('kv').put(v, k); t.onsuccess = () => res(); t.onerror = () => rej(t.error); }); },
  del(k) { return new Promise((res, rej) => { const t = this.db.transaction('kv', 'readwrite').objectStore('kv').delete(k); t.onsuccess = () => res(); t.onerror = () => rej(t.error); }); },
};

/* ---------- projet ---------- */
let project = newProject();
function newProject() {
  return { format: FORMAT, name: '', map: null, settings: { window: 256, allowOutside: true }, events: [] };
}
let img = null;           // ImageBitmap de la carte
let mapIndex = [];        // maps/index.json
let D = derive([]);       // état dérivé
let nextKind = 'normal';  // type du prochain point posé
let hover = null;         // {x,y} coordonnées carte sous la souris
let snapId = null;        // point existant sous la souris (jonction)
let snapEdge = null;      // {from,to,x,y} arête sous la souris (jonction par insertion d'intersection)

/* ---------- dérivation de l'état depuis le journal ---------- */
function derive(events) {
  const S = { points: {}, order: [], edges: [], children: {}, terminal: {}, visited: new Set(),
              current: null, start: null, queue: [], done: false, nextId: 1, visits: [] };
  const addPoint = (id, x, y, kind, parent) => {
    S.points[id] = { id, x, y, kind, parent, order: S.order.length };
    S.order.push(id); S.children[id] = []; S.nextId = Math.max(S.nextId, id + 1);
  };
  const visit = id => { S.current = id; S.visited.add(id); S.visits.push(id); };
  const advance = () => {           // quitte le point courant
    const unv = (S.children[S.current] || []).filter(c => !S.visited.has(c));
    if (unv.length) { S.queue.push(...unv.slice(1)); visit(unv[0]); return true; }
    if (S.queue.length) { visit(S.queue.shift()); return true; }
    if (S.current !== S.start) { visit(S.start); return true; }
    S.done = true; return false;
  };
  for (const ev of events) {
    switch (ev.t) {
      case 'start': addPoint(ev.id, ev.x, ev.y, 'start', null); S.start = ev.id; visit(ev.id); break;
      case 'place':
        addPoint(ev.id, ev.x, ev.y, ev.kind, ev.from);
        S.edges.push({ from: ev.from, to: ev.id, kind: 'trace' });
        S.children[ev.from].push(ev.id);
        if (S.points[ev.from].kind === 'normal') visit(ev.id);
        break;
      case 'advance': S.terminal[S.current] = 'continue'; advance(); break;
      case 'end': S.terminal[S.current] = 'end'; advance(); break;
      case 'join':
        S.edges.push({ from: S.current, to: ev.to, kind: 'join' });
        if (ev.retype) S.points[ev.to].kind = 'intersection';
        S.terminal[S.current] = 'join:' + ev.to; advance(); break;
      case 'split': {       // insère une intersection au milieu d'une arête, puis s'y raccorde
        const e = S.edges.find(x => x.from === ev.from && x.to === ev.to);
        addPoint(ev.id, ev.x, ev.y, 'intersection', ev.from);
        S.visited.add(ev.id);
        S.children[ev.id] = [ev.to];
        S.points[ev.to].parent = ev.id;
        const sib = S.children[ev.from], i = sib.indexOf(ev.to);
        if (i >= 0) sib[i] = ev.id;
        if (e) { e.to = ev.id; S.edges.push({ from: ev.id, to: ev.to, kind: e.kind }); }
        S.edges.push({ from: S.current, to: ev.id, kind: 'join' });
        S.terminal[S.current] = 'join:' + ev.id;
        advance(); break;
      }
      case 'retype': S.points[ev.id].kind = ev.kind; break;
      case 'finish': S.done = true; break;
    }
  }
  return S;
}
function cur() { return D.current == null ? null : D.points[D.current]; }
function unvisitedChildren(id) { return (D.children[id] || []).filter(c => !D.visited.has(c)); }
function isBranching(p) { return p && (p.kind === 'start' || p.kind === 'intersection'); }
function inWindow(x, y, c = cur(), w = project.settings.window) {
  return c && Math.abs(x - c.x) <= w / 2 && Math.abs(y - c.y) <= w / 2;
}

/* ---------- événements utilisateur ---------- */
function push(ev) { ev.ts = Date.now(); project.events.push(ev); refresh(true); }
function placePoint(x, y, kind) {
  if (!img) return warn('Chargez une carte.');
  if (D.done) return warn('Session terminée (annulez pour reprendre).');
  x = Math.round(x); y = Math.round(y);
  if (x < 0 || y < 0 || x >= img.width || y >= img.height) return warn('Hors de la carte.');
  const c = cur();
  if (!c) { push({ t: 'start', id: D.nextId, x, y }); return; }
  if (!project.settings.allowOutside && !inWindow(x, y)) return warn('Point hors de la fenêtre : le modèle ne le verrait pas (zoom/fenêtre, ou cochez « hors fenêtre »).');
  push({ t: 'place', id: D.nextId, from: c.id, x, y, kind, window: project.settings.window });
  nextKind = 'normal';
}
function joinTo(id) {
  const c = cur();
  if (!c || D.done || id === c.id) return;
  if (D.edges.some(e => (e.from === c.id && e.to === id) || (e.from === id && e.to === c.id))) return warn('Déjà relié à ce point.');
  if (isBranching(c) && unvisitedChildren(c.id).length) return warn('Validez d’abord les amorces posées (Espace).');
  push({ t: 'join', to: id, retype: D.points[id].kind === 'normal', window: project.settings.window });
}
function splitEdge(s) {
  const c = cur();
  if (!c || D.done) return;
  if (isBranching(c) && unvisitedChildren(c.id).length) return warn('Validez d’abord les amorces posées (Espace).');
  push({ t: 'split', id: D.nextId, from: s.from, to: s.to, x: Math.round(s.x), y: Math.round(s.y), window: project.settings.window });
}
function doAdvance() {
  const c = cur(); if (!c || D.done) return;
  if (!isBranching(c)) return warn('Point normal : posez simplement le point suivant.');
  if (!unvisitedChildren(c.id).length) return warn('Posez au moins une amorce de branche avant Espace (ou F si cul-de-sac).');
  push({ t: 'advance', window: project.settings.window });
}
function doEnd() {
  const c = cur(); if (!c || D.done) return;
  if (isBranching(c) && unvisitedChildren(c.id).length) return doAdvance();
  push({ t: 'end', window: project.settings.window });
}
function doRetype() {
  const c = cur(); if (!c || D.done || c.kind === 'start') return;
  if (D.children[c.id].length) return warn('Le point a déjà une suite : annulez d’abord.');
  push({ t: 'retype', id: c.id, kind: c.kind === 'normal' ? 'intersection' : 'normal' });
}
function doUndo() { if (project.events.length) { project.events.pop(); refresh(true); } }
function doFinish() {
  if (!cur() || D.done) return;
  if (D.queue.length || unvisitedChildren(D.current).length) { if (!confirm('Des branches restent en attente. Terminer quand même ?')) return; }
  push({ t: 'finish' });
}

/* ---------- vue / rendu ---------- */
const canvas = $('view'), ctx = canvas.getContext('2d');
const view = { s: 1, cx: 0, cy: 0 };
let W = 0, H = 0, dirty = true;
function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  const dpr = devicePixelRatio || 1;
  W = Math.round(r.width); H = Math.round(r.height);
  canvas.width = W * dpr; canvas.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  dirty = true;
}
const toScreen = (x, y) => [(x - view.cx) * view.s + W / 2, (y - view.cy) * view.s + H / 2];
const toMap = (sx, sy) => [(sx - W / 2) / view.s + view.cx, (sy - H / 2) / view.s + view.cy];
function recenter() {
  const c = cur();
  if (c) { view.cx = c.x; view.cy = c.y; view.s = Math.min(W, H) * 0.8 / project.settings.window; }
  else if (img) { view.cx = img.width / 2; view.cy = img.height / 2; view.s = Math.min(W / img.width, H / img.height); }
  dirty = true;
}
function draw() {
  dirty = false;
  ctx.fillStyle = '#0b0d10'; ctx.fillRect(0, 0, W, H);
  if (!img) return;
  // image : rectangle source clampé à la carte
  let [mx0, my0] = toMap(0, 0), [mx1, my1] = toMap(W, H);
  const sx0 = Math.max(0, mx0), sy0 = Math.max(0, my0), sx1 = Math.min(img.width, mx1), sy1 = Math.min(img.height, my1);
  if (sx1 > sx0 && sy1 > sy0) {
    const [dx0, dy0] = toScreen(sx0, sy0), [dx1, dy1] = toScreen(sx1, sy1);
    ctx.imageSmoothingEnabled = view.s < 2;
    ctx.drawImage(img, sx0, sy0, sx1 - sx0, sy1 - sy0, dx0, dy0, dx1 - dx0, dy1 - dy0);
  }
  const c = cur(), w = project.settings.window;
  // fenêtre : assombrir l'extérieur
  if (c) {
    const [ax, ay] = toScreen(c.x - w / 2, c.y - w / 2), [bx, by] = toScreen(c.x + w / 2, c.y + w / 2);
    ctx.fillStyle = 'rgba(0,0,0,.5)';
    ctx.fillRect(0, 0, W, Math.max(0, ay)); ctx.fillRect(0, Math.min(H, by), W, H);
    ctx.fillRect(0, Math.max(0, ay), Math.max(0, ax), Math.min(H, by) - Math.max(0, ay));
    ctx.fillRect(Math.min(W, bx), Math.max(0, ay), W, Math.min(H, by) - Math.max(0, ay));
    ctx.strokeStyle = '#ff7a1a'; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
    ctx.strokeRect(ax, ay, bx - ax, by - ay); ctx.setLineDash([]);
  }
  // arêtes
  ctx.lineWidth = Math.max(1.5, Math.min(4, view.s * 1.2));
  for (const e of D.edges) {
    const a = D.points[e.from], b = D.points[e.to];
    const [x0, y0] = toScreen(a.x, a.y), [x1, y1] = toScreen(b.x, b.y);
    ctx.strokeStyle = e.kind === 'join' ? '#39c47c' : '#4ea1ff';
    ctx.setLineDash(e.kind === 'join' ? [5, 4] : []);
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  }
  ctx.setLineDash([]);
  // aperçu du segment en cours
  if (c && hover && !D.done) {
    const ok = snapId != null || snapEdge || project.settings.allowOutside || inWindow(hover.x, hover.y);
    const t = snapId != null ? D.points[snapId] : snapEdge || hover;
    const [x0, y0] = toScreen(c.x, c.y), [x1, y1] = toScreen(t.x, t.y);
    ctx.strokeStyle = ok ? (snapId != null ? '#39c47c' : snapEdge ? '#ff7a1a' : 'rgba(255,255,255,.7)') : 'rgba(255,77,77,.8)';
    ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]);
    if (snapEdge) {
      const a = D.points[snapEdge.from], b = D.points[snapEdge.to];
      const [ax, ay] = toScreen(a.x, a.y), [bx, by] = toScreen(b.x, b.y);
      ctx.strokeStyle = 'rgba(255,122,26,.7)'; ctx.lineWidth = 6;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      ctx.strokeStyle = '#ff7a1a'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x1, y1, 9, 0, 7); ctx.stroke();
      ctx.lineWidth = Math.max(1.5, Math.min(4, view.s * 1.2));
    }
  }
  // points
  const r = Math.max(3, Math.min(7, view.s * 1.5));
  const showOrder = $('showOrder').checked && view.s > 0.6;
  ctx.font = `${Math.round(11)}px system-ui`; ctx.textBaseline = 'middle';
  for (const id of D.order) {
    const p = D.points[id]; const [x, y] = toScreen(p.x, p.y);
    if (x < -20 || y < -20 || x > W + 20 || y > H + 20) continue;
    const col = p.kind === 'start' ? '#39c47c' : p.kind === 'intersection' ? '#ff7a1a' : '#4ea1ff';
    ctx.beginPath(); ctx.arc(x, y, p.kind === 'normal' ? r : r * 1.4, 0, 7); ctx.fillStyle = col; ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = '#000'; ctx.stroke();
    if (D.queue.includes(id)) { ctx.setLineDash([3, 3]); ctx.strokeStyle = '#fff'; ctx.beginPath(); ctx.arc(x, y, r * 2.2, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
    if ((D.terminal[id] || '').startsWith('end')) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r); ctx.moveTo(x + r, y - r); ctx.lineTo(x - r, y + r); ctx.stroke(); }
    if (id === snapId) { ctx.strokeStyle = '#39c47c'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r * 2.6, 0, 7); ctx.stroke(); }
    if (showOrder) { ctx.fillStyle = '#fff'; ctx.strokeStyle = 'rgba(0,0,0,.8)'; ctx.lineWidth = 3; ctx.strokeText(p.order, x + r + 3, y - r - 2); ctx.fillText(p.order, x + r + 3, y - r - 2); }
  }
  if (c) {
    const [x, y] = toScreen(c.x, c.y);
    ctx.strokeStyle = '#ff4d4d'; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(x, y, r * 2.6, 0, 7); ctx.stroke();
    ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x - r * 4, y); ctx.lineTo(x + r * 4, y); ctx.moveTo(x, y - r * 4); ctx.lineTo(x, y + r * 4); ctx.stroke();
  }
  drawCrop();
}
function drawCrop() {
  const cv = $('crop'), cc = cv.getContext('2d'), c = cur(), w = project.settings.window;
  cc.fillStyle = '#000'; cc.fillRect(0, 0, cv.width, cv.height);
  if (!img || !c) { $('cropInfo').textContent = ''; return; }
  const k = cv.width / w, x0 = c.x - w / 2, y0 = c.y - w / 2;
  const sx = Math.max(0, x0), sy = Math.max(0, y0), ex = Math.min(img.width, x0 + w), ey = Math.min(img.height, y0 + w);
  if (ex > sx && ey > sy) cc.drawImage(img, sx, sy, ex - sx, ey - sy, (sx - x0) * k, (sy - y0) * k, (ex - sx) * k, (ey - sy) * k);
  let n = 0;
  for (const e of D.edges) {
    const a = D.points[e.from], b = D.points[e.to];
    cc.strokeStyle = 'rgba(78,161,255,.9)'; cc.lineWidth = 1.5;
    cc.beginPath(); cc.moveTo((a.x - x0) * k, (a.y - y0) * k); cc.lineTo((b.x - x0) * k, (b.y - y0) * k); cc.stroke();
  }
  for (const id of D.order) {
    const p = D.points[id]; if (!inWindow(p.x, p.y, c, w)) continue; n++;
    cc.fillStyle = id === c.id ? '#ff4d4d' : id === c.parent ? '#ffd166' : p.kind === 'intersection' ? '#ff7a1a' : '#4ea1ff';
    cc.beginPath(); cc.arc((p.x - x0) * k, (p.y - y0) * k, id === c.id ? 5 : 3.5, 0, 7); cc.fill();
  }
  $('cropInfo').textContent = `${w}×${w} px autour du point ${c.order} — ${n} point(s) visibles · rouge = courant, jaune = précédent`;
}
function loop() { if (dirty) draw(); requestAnimationFrame(loop); }

/* ---------- souris / clavier ---------- */
let drag = null;
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('mousedown', e => { drag = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false, btn: e.button }; });
window.addEventListener('mousemove', e => {
  const r = canvas.getBoundingClientRect();
  const [mx, my] = toMap(e.clientX - r.left, e.clientY - r.top);
  hover = { x: mx, y: my };
  if (drag && drag.btn !== 2) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.hypot(dx, dy) > 4) drag.moved = true;
    if (drag.moved) { view.cx = drag.cx - dx / view.s; view.cy = drag.cy - dy / view.s; }
  }
  snapId = null; snapEdge = null;
  const thr = 10 / view.s; let best = thr;
  for (const id of D.order) { const p = D.points[id]; const d = Math.hypot(p.x - mx, p.y - my); if (d < best && id !== D.current) { best = d; snapId = id; } }
  if (snapId == null && cur() && !D.done) {
    let bestE = 8 / view.s, gap = 4 / view.s;
    for (const e of D.edges) {
      if (e.kind !== 'trace' || e.from === D.current || e.to === D.current) continue;
      const a = D.points[e.from], b = D.points[e.to];
      const vx = b.x - a.x, vy = b.y - a.y, L2 = vx * vx + vy * vy;
      if (!L2) continue;
      const t = Math.max(0, Math.min(1, ((mx - a.x) * vx + (my - a.y) * vy) / L2));
      const px = a.x + t * vx, py = a.y + t * vy;
      const d = Math.hypot(px - mx, py - my);
      if (d < bestE && Math.hypot(px - a.x, py - a.y) > gap && Math.hypot(px - b.x, py - b.y) > gap) {
        bestE = d; snapEdge = { from: e.from, to: e.to, x: px, y: py };
      }
    }
  }
  $('hud').textContent = img ? `x ${Math.round(mx)}  y ${Math.round(my)}  ·  zoom ×${view.s.toFixed(2)}` : '';
  dirty = true;
});
window.addEventListener('mouseup', e => {
  if (!drag) return;
  const d = drag; drag = null;
  if (d.moved || e.target !== canvas) return;
  if (snapId != null) { joinTo(snapId); return; }
  if (snapEdge) { splitEdge(snapEdge); return; }
  const kind = (e.button === 2 || e.shiftKey) ? 'intersection' : nextKind;
  placePoint(hover.x, hover.y, kind);
});
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const r = canvas.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
  const [mx, my] = toMap(sx, sy);
  view.s = Math.min(40, Math.max(0.02, view.s * Math.exp(-e.deltaY * 0.0015)));
  view.cx = mx - (sx - W / 2) / view.s; view.cy = my - (sy - H / 2) / view.s;
  dirty = true;
}, { passive: false });
window.addEventListener('keydown', e => {
  if (e.target.matches('input,select,textarea')) return;
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); doUndo(); return; }
  if (e.ctrlKey || e.metaKey) return;
  if (k === ' ') { e.preventDefault(); doAdvance(); }
  else if (k === 'f') doEnd();
  else if (k === 'i') { nextKind = nextKind === 'normal' ? 'intersection' : 'normal'; updateUI(); }
  else if (k === 't') doRetype();
  else if (k === 'c') recenter();
  else if (k === 'escape') { nextKind = 'normal'; updateUI(); }
  else if (k === '+' || k === '=') { view.s *= 1.25; dirty = true; }
  else if (k === '-') { view.s /= 1.25; dirty = true; }
});
window.addEventListener('resize', resize);

/* ---------- UI ---------- */
function warn(msg) { const s = $('status'); s.textContent = msg; s.classList.add('warn'); setTimeout(() => { s.classList.remove('warn'); updateUI(); }, 2500); }
function updateUI() {
  const c = cur();
  const st = $('status');
  if (!img) st.textContent = 'Chargez une carte (liste ou fichier local).';
  else if (!c) st.textContent = 'Cliquez sur la carte pour poser le point de départ.';
  else if (D.done) st.textContent = 'Session terminée. Exportez le projet, ou Ctrl+Z pour reprendre.';
  else if (isBranching(c)) {
    const n = unvisitedChildren(c.id).length;
    st.textContent = `${c.kind === 'start' ? 'Point de départ' : 'Intersection'} n°${c.order} : posez une amorce par direction (${n} posée${n > 1 ? 's' : ''}), puis Espace. F si aucune direction.`;
  } else st.textContent = `Point normal n°${c.order} : cliquez le point suivant (Maj/clic droit = intersection), F = cul-de-sac, clic sur un point ou un segment = jonction.`;
  if (!st.classList.contains('warn')) st.classList.remove('warn');
  const nInter = D.order.filter(id => D.points[id].kind === 'intersection').length;
  const len = D.edges.reduce((s, e) => { const a = D.points[e.from], b = D.points[e.to]; return s + Math.hypot(a.x - b.x, a.y - b.y); }, 0);
  $('stats').innerHTML = `<span>Points <b>${D.order.length}</b></span><span>Segments <b>${D.edges.length}</b></span>` +
    `<span>Intersections <b>${nInter}</b></span><span>Décisions <b>${D.visits.length}</b></span>` +
    `<span>Longueur <b>${Math.round(len)} px</b></span><span>Événements <b>${project.events.length}</b></span>`;
  $('btnKind').innerHTML = `Prochain point : <b>${nextKind}</b>`; $('btnKind').classList.toggle('active', nextKind === 'intersection');
  $('btnAdvance').disabled = !c || D.done || !isBranching(c);
  $('btnEnd').disabled = !c || D.done;
  $('btnRetype').disabled = !c || D.done || c.kind === 'start';
  $('btnUndo').disabled = !project.events.length;
  $('btnFinish').disabled = !c || D.done;
  $('queueCount').textContent = D.queue.length;
  $('queue').innerHTML = D.queue.map(id => { const p = D.points[id]; return `<li data-id="${id}">n°${p.order} (${p.kind}) — ${p.x}, ${p.y}</li>`; }).join('');
  const names = { start: 'départ', place: 'point', advance: 'suivant', end: 'cul-de-sac', join: 'jonction', split: 'jonction sur segment', retype: 'type', finish: 'fin de session' };
  $('log').innerHTML = project.events.slice(-25).reverse().map((ev, i) => {
    const n = project.events.length - i - 1;
    let d = names[ev.t] || ev.t;
    if (ev.t === 'place') d += ` ${ev.kind} (${ev.x}, ${ev.y}) ← ${D.points[ev.from] ? 'n°' + D.points[ev.from].order : ''}`;
    if (ev.t === 'start') d += ` (${ev.x}, ${ev.y})`;
    if (ev.t === 'join') d += ` → n°${D.points[ev.to] ? D.points[ev.to].order : '?'}${ev.retype ? ' (→ intersection)' : ''}`;
    if (ev.t === 'split') d += ` → nouvelle intersection (${ev.x}, ${ev.y})`;
    if (ev.t === 'retype') d += ` → ${ev.kind}`;
    return `<li>#${n} ${d}</li>`;
  }).join('');
  $('mapInfo').textContent = project.map ? `${project.map.name} — ${project.map.width}×${project.map.height} px${project.map.georef ? ' · géoréférencée' : ''}` : 'Aucune carte chargée.';
}
$('queue').addEventListener('click', e => { const li = e.target.closest('li'); if (!li) return; const p = D.points[+li.dataset.id]; view.cx = p.x; view.cy = p.y; dirty = true; });
let saveTimer = null;
function refresh(save) {
  D = derive(project.events);
  snapId = null; snapEdge = null;
  const c = cur();
  if (c && (save || !img)) recenter();
  updateUI(); dirty = true;
  if (save) { clearTimeout(saveTimer); saveTimer = setTimeout(() => idb.set('project', project), 300); }
}
$('winSize').addEventListener('change', () => { project.settings.window = Math.max(32, +$('winSize').value || 256); $('winSize').value = project.settings.window; refresh(true); });
$('allowOutside').addEventListener('change', () => { project.settings.allowOutside = $('allowOutside').checked; refresh(true); });
$('showOrder').addEventListener('change', () => { dirty = true; });
$('projName').addEventListener('change', () => { project.name = $('projName').value; refresh(true); });
$('btnKind').onclick = () => { nextKind = nextKind === 'normal' ? 'intersection' : 'normal'; updateUI(); };
$('btnAdvance').onclick = doAdvance; $('btnEnd').onclick = doEnd; $('btnRetype').onclick = doRetype;
$('btnUndo').onclick = doUndo; $('btnCenter').onclick = recenter; $('btnFinish').onclick = doFinish;
$('btnReset').onclick = async () => {
  if (!confirm('Supprimer tous les points de ce projet ?')) return;
  project.events = []; project.name = ''; $('projName').value = ''; refresh(true);
};

/* ---------- export / import ---------- */
function exportJSON() {
  const out = { ...project, exported: new Date().toISOString(),
    derived: { points: D.order.map(id => ({ ...D.points[id], terminal: D.terminal[id] || null })), edges: D.edges, visits: D.visits } };
  if (project.map && project.map.georef) {
    const g = project.map.georef;
    out.derived.points.forEach(p => { p.lon = g.lon[0] * p.x + g.lon[1]; p.lat = g.lat[0] * p.y + g.lat[1]; });
  }
  const blob = new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = `${(project.name || (project.map && project.map.id) || 'maptracer').replace(/[^\w.-]+/g, '_')}.maptracer.json`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
$('btnExport').onclick = exportJSON;
$('importFile').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const p = JSON.parse(await f.text());
    if (p.format !== FORMAT) throw new Error('format inconnu');
    if (project.events.length && !confirm('Remplacer le projet courant ?')) return;
    project = { format: FORMAT, name: p.name || '', map: p.map || null, settings: { window: 256, allowOutside: true, ...p.settings }, events: p.events || [] };
    syncSettingsUI();
    if (project.map) {
      const entry = mapIndex.find(m => m.id === project.map.id);
      if (entry) await loadMapEntry(entry, true);
      else if (!img || (project.map.hash && img.hash !== project.map.hash)) warn(`Ouvrez l'image « ${project.map.name} » (fichier local) pour afficher ce projet.`);
    }
    refresh(true);
  } catch (err) { warn('Import impossible : ' + err.message); }
  e.target.value = '';
});
function syncSettingsUI() { $('winSize').value = project.settings.window; $('allowOutside').checked = project.settings.allowOutside; $('projName').value = project.name || ''; }

/* ---------- chargement des cartes ---------- */
async function sha(blob) { const h = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()); return [...new Uint8Array(h)].slice(0, 8).map(b => b.toString(16).padStart(2, '0')).join(''); }
async function setImage(blob, meta) {
  const bmp = await createImageBitmap(blob);
  img = bmp; img.hash = await sha(blob);
  const m = { id: meta.id, name: meta.name, width: bmp.width, height: bmp.height, hash: img.hash, georef: meta.georef || null };
  if (project.map && project.events.length && project.map.hash && project.map.hash !== m.hash) {
    if (!confirm(`Cette image diffère de celle du projet (« ${project.map.name} »). Garder les points existants ?`)) project.events = [];
  }
  project.map = m;
  refresh(true);
  if (!cur()) recenter();
}
async function loadMapEntry(entry, keepProject) {
  $('status').textContent = 'Chargement de la carte…';
  const blob = await (await fetch(entry.url)).blob();
  let georef = null;
  if (entry.georef) { try { georef = await (await fetch(entry.georef)).json(); } catch (_) {} }
  if (!keepProject && project.map && project.map.id !== entry.id && project.events.length && !confirm('Changer de carte : conserver les points du projet ?')) project.events = [];
  await setImage(blob, { id: entry.id, name: entry.name, georef });
  await idb.del('mapBlob');
}
async function loadLocalFile(f) {
  if (!f || !f.type.startsWith('image/')) return;
  await setImage(f, { id: 'local:' + f.name, name: f.name, georef: null });
  await idb.set('mapBlob', f);
  $('mapSelect').value = '';
}
$('mapSelect').addEventListener('change', e => { const m = mapIndex.find(x => x.id === e.target.value); if (m) loadMapEntry(m); });
$('mapFile').addEventListener('change', e => loadLocalFile(e.target.files[0]));
const main = $('main');
main.addEventListener('dragover', e => { e.preventDefault(); main.classList.add('dragover'); });
main.addEventListener('dragleave', () => main.classList.remove('dragover'));
main.addEventListener('drop', e => { e.preventDefault(); main.classList.remove('dragover'); loadLocalFile(e.dataTransfer.files[0]); });

/* ---------- démarrage ---------- */
(async function init() {
  resize(); loop();
  await idb.open();
  try { mapIndex = await (await fetch('../maps/index.json')).json(); } catch (_) { mapIndex = []; }
  mapIndex.forEach(m => { m.url = '../' + m.url; if (m.georef) m.georef = '../' + m.georef; });
  $('mapSelect').innerHTML += mapIndex.map(m => `<option value="${m.id}">${m.name}</option>`).join('');
  const saved = await idb.get('project');
  if (saved && saved.format === FORMAT) { project = { ...newProject(), ...saved, settings: { ...newProject().settings, ...saved.settings } }; }
  syncSettingsUI();
  if (project.map) {
    const entry = mapIndex.find(m => m.id === project.map.id);
    const blob = entry ? null : await idb.get('mapBlob');
    if (entry) { $('mapSelect').value = entry.id; await loadMapEntry(entry, true); }
    else if (blob) await setImage(blob, { id: project.map.id, name: project.map.name, georef: project.map.georef });
  }
  refresh(false);
})();
