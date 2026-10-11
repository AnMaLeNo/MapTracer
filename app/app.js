/* MapTracer — annotation pas-à-pas de galeries pour constituer un jeu d'entraînement.
   Source de vérité : la liste ordonnée `events` (replay → état dérivé). Annuler = retirer le dernier événement. */
'use strict';

const $ = id => document.getElementById(id);
const FORMAT = 'maptracer/1';
const REV = 2;            // 2 : une jonction sur une amorce jamais visitée la dépasse au lieu de nous y ramener

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
  return { format: FORMAT, rev: REV, name: '', map: null, settings: { window: 256, allowOutside: true, assist: false, proposeDist: 32, model: '' }, events: [] };
}
let img = null;           // ImageBitmap de la carte
let mapIndex = [];        // maps/index.json
let D = derive([], REV);       // état dérivé
let nextKind = 'normal';  // type du prochain point posé
let hover = null;         // {x,y} coordonnées carte sous la souris
let snapId = null;        // point existant sous la souris (jonction)
let snapEdge = null;      // {from,to,x,y} arête sous la souris (jonction par insertion d'intersection)
let prop = null;          // proposition du modèle pour le point courant : {branching, items:[{kind,x,y,conf,path,dirs}]}
let propSeq = 0;          // numéro de la dernière requête (ignore les réponses périmées)
let modelInfo = null;     // réponse de /api/model
let mode = ['auto', 'wand'].includes(localStorage.getItem('mt-mode')) ? localStorage.getItem('mt-mode') : 'trace';   // 'trace' (manuel/assisté) | 'auto' (auto.js)

/* ---------- dérivation de l'état depuis le journal ---------- */
function derive(events, rev) {
  const S = { points: {}, order: [], edges: [], children: {}, terminal: {}, visited: new Set(),
              current: null, start: null, queue: [], done: false, nextId: 1, visits: [], preJoined: new Set() };
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
      case 'join': {
        // Amorce normale jamais visitée : avec la jonction elle n'a que 2 liens, c'est un simple point
        // de passage, pas une intersection. On la dépasse (sinon on y revient, déjà reliée, sans rien à y faire).
        const fresh = !S.visited.has(ev.to) && S.points[ev.to].kind === 'normal';
        S.edges.push({ from: S.current, to: ev.to, kind: 'join' });
        if (fresh && rev >= 2) { S.visited.add(ev.to); S.queue = S.queue.filter(q => q !== ev.to); }
        else {
          if (fresh) S.preJoined.add(ev.to);
          if (ev.retype) S.points[ev.to].kind = 'intersection';
        }
        S.terminal[S.current] = 'join:' + ev.to; advance(); break;
      }
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

/* ---------- migration des projets créés avant rev 2 ---------- */
// Avant rev 2, une amorce jointe depuis l'autre côté restait en file d'attente : on y revenait, déjà reliée,
// et le seul moyen d'en sortir était F (cul-de-sac enregistré à tort). On retire ces F ; tout autre cas
// (action réelle depuis ce point) ou tout écart du graphe → on garde le projet tel quel en rev 1.
function migrateEvents(events) {
  if (!derive(events, 1).preJoined.size) return { events, changed: false };
  const kept = [];
  for (let i = 0; i < events.length; i++) {
    const ev = events[i], S = derive(events.slice(0, i), 1);
    const stale = S.current != null && S.preJoined.has(S.current) && !S.children[S.current].length && !S.terminal[S.current];
    if (stale && ev.t === 'end') continue;
    if (stale && ev.t !== 'finish') return null;
    kept.push(ev);
  }
  const A = derive(events, 1), B = derive(kept, 2);
  const shape = S => JSON.stringify([S.order.map(id => [id, S.points[id].x, S.points[id].y, S.points[id].parent]), S.edges]);
  return shape(A) === shape(B) ? { events: kept, changed: true } : null;
}
function migrateProject(p) {
  if (p.rev >= REV) return { project: p, status: 'ok' };
  const m = migrateEvents(p.events || []);
  if (!m) return { project: { ...p, rev: 1 }, status: 'kept' };
  return { project: { ...p, rev: REV, events: m.events }, status: m.changed ? 'migrated' : 'ok' };
}

/* ---------- événements utilisateur ---------- */
function push(ev) { ev.ts = Date.now(); project.events.push(ev); refresh(true); }
/* ---------- mode assisté ---------- */
function propSummary(items) {
  return items.map(it => ({ kind: it.kind, x: Math.round(it.x), y: Math.round(it.y), conf: it.conf }));
}
function withProp(ev, accepted) {          // journalise la proposition en vigueur et si elle a été suivie
  if (prop && prop.items.length) { ev.prop = propSummary(prop.items); ev.accepted = accepted; }
  return ev;
}
function currentHeading(c) {
  const p = c.parent != null ? D.points[c.parent] : null;
  return p ? Math.atan2(c.y - p.y, c.x - p.x) : null;
}
async function requestProposal() {
  const c = cur();
  prop = null; dirty = true;
  if ((mode === 'auto' || mode === 'wand') || !project.settings.assist || !img || !c || D.done) return updateAssistInfo();
  if (!project.map || project.map.id.startsWith('local:')) return updateAssistInfo('Carte locale : le serveur ne la connaît pas (choisissez-la dans la liste).');
  const entry = mapIndex.find(m => m.id === project.map.id);
  if (!entry) return updateAssistInfo('Carte inconnue du serveur.');
  const seq = ++propSeq;
  const w = project.settings.window, R = Math.max(w, 2 * project.settings.proposeDist) + 64;
  const segs = D.edges.map(e => [D.points[e.from], D.points[e.to]])
    .filter(([a, b]) => Math.min(Math.hypot(a.x - c.x, a.y - c.y), Math.hypot(b.x - c.x, b.y - c.y)) < R)
    .map(([a, b]) => [a.x, a.y, b.x, b.y]);
  updateAssistInfo('Le modèle réfléchit…');
  try {
    const r = await fetch('../api/predict', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ map: entry.url.replace(/^\.\.\//, ''), x: c.x, y: c.y, heading: currentHeading(c), branching: isBranching(c),
                             dist: project.settings.proposeDist, segs, model: project.settings.model || undefined }) });
    const res = await r.json();
    if (seq !== propSeq) return;
    if (!r.ok) return updateAssistInfo('Modèle indisponible : ' + (res.error || r.status));
    if (res.branching) {        // n'écarte que les directions déjà couvertes par une amorce posée
      const kids = (D.children[c.id] || []).map(id => Math.atan2(D.points[id].y - c.y, D.points[id].x - c.x));
      res.items = res.items.filter(it => kids.every(k => { const d = Math.abs((((it.dir.deg * Math.PI / 180) - k) + 3 * Math.PI) % (2 * Math.PI) - Math.PI); return d > Math.PI / 9; }));
    }
    prop = res; dirty = true; updateAssistInfo();
  } catch (err) { if (seq === propSeq) updateAssistInfo('Erreur : ' + err.message); }
}
function currentModel() {
  const list = (modelInfo && modelInfo.models || []).filter(m => !m.error);
  return list.find(m => m.name === project.settings.model) || list[0] || null;
}
function syncModelUI() {
  const list = (modelInfo && modelInfo.models || []);
  $('modelSelect').innerHTML = list.length ? list.map(m => `<option value="${m.name}"${m.error ? ' disabled' : ''}>${m.name}${m.title ? ' — ' + m.title : ''}${m.error ? ' (erreur)' : ''}</option>`).join('')
                                           : '<option value="">(aucun)</option>';
  const cm = currentModel(); $('modelSelect').value = cm ? cm.name : '';
}
function updateAssistInfo(msg) {
  const el = $('assistInfo');
  if (msg) { el.textContent = msg; return; }
  const cm = currentModel();
  if ((mode === 'auto' || mode === 'wand') || !project.settings.assist) { el.textContent = cm ? `Modèle ${cm.name} prêt (${modelInfo.device}${cm.meta ? `, pas ${cm.meta.step} px, fenêtre ${cm.meta.window}, ${cm.meta.sectors} secteurs` : ''}).` : 'Mode manuel.'; return; }
  if (!prop) { el.textContent = cm ? 'Aucune proposition.' : 'Modèle indisponible : dossier models/ vide ou server.py --model …'; return; }
  const names = { normal: 'point normal', intersection: 'intersection', end: 'cul-de-sac', junction: 'jonction' };
  if (!prop.items.length) { el.textContent = 'Le modèle ne voit aucune direction nouvelle (F si cul-de-sac).'; return; }
  el.innerHTML = prop.items.map(it => `<span class="prop">${names[it.kind]} <b>${Math.round(it.conf * 100)} %</b>` +
    (it.dir ? ` · ${it.dir.deg}°` : '') + (it.kind === 'intersection' && it.dirs.length ? ` · ${it.dirs.length} directions` : '') + '</span>').join(' ');
}
function acceptProposal(only) {
  const c = cur();
  if (!prop || !c || D.done) return;
  const items = only ? [only] : prop.items;
  if (!items.length) return warn('Aucune proposition à accepter.');
  const summary = propSummary(prop.items);
  for (const it of items) {
    if (it.kind === 'end') { push({ t: 'end', window: project.settings.window, prop: summary, accepted: true }); break; }
    const x = Math.round(it.x), y = Math.round(it.y);
    if (x < 0 || y < 0 || x >= img.width || y >= img.height) continue;
    const kind = it.kind === 'intersection' ? 'intersection' : 'normal';
    project.events.push({ t: 'place', id: derive(project.events, project.rev).nextId, from: c.id, x, y, kind, window: project.settings.window,
                          prop: summary, accepted: true, ts: Date.now() });
  }
  refresh(true);
}
function proposalAt(mx, my) {
  if (!prop) return null;
  const r = 10 / view.s;
  return prop.items.find(it => it.kind !== 'end' && Math.hypot(it.x - mx, it.y - my) < r) || null;
}
function placePoint(x, y, kind) {
  if (!img) return warn('Chargez une carte.');
  if (D.done) return warn('Session terminée (annulez pour reprendre).');
  x = Math.round(x); y = Math.round(y);
  if (x < 0 || y < 0 || x >= img.width || y >= img.height) return warn('Hors de la carte.');
  const c = cur();
  if (!c) { push({ t: 'start', id: D.nextId, x, y }); return; }
  if (!project.settings.allowOutside && !inWindow(x, y)) return warn('Point hors de la fenêtre : le modèle ne le verrait pas (zoom/fenêtre, ou cochez « hors fenêtre »).');
  push(withProp({ t: 'place', id: D.nextId, from: c.id, x, y, kind, window: project.settings.window }, false));
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
  push(withProp({ t: 'end', window: project.settings.window }, !!(prop && prop.items.length === 1 && prop.items[0].kind === 'end')));
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
  if ((mode === 'auto' || mode === 'wand')) return Auto.recenter();
  const c = cur();
  if (c) { view.cx = c.x; view.cy = c.y; view.s = Math.min(W, H) * 0.8 / project.settings.window; }
  else if (img) { view.cx = img.width / 2; view.cy = img.height / 2; view.s = Math.min(W / img.width, H / img.height); }
  updateHover();
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
  if ((mode === 'auto' || mode === 'wand')) return Auto.draw();
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
  // propositions du modèle
  if (c && prop && !D.done) {
    ctx.strokeStyle = '#d46cff'; ctx.fillStyle = '#d46cff'; ctx.lineWidth = Math.max(1.5, Math.min(3, view.s));
    ctx.font = '12px system-ui, sans-serif'; ctx.textBaseline = 'bottom';
    for (const it of prop.items) {
      const pts = [[c.x, c.y], ...it.path.slice(1)];
      ctx.setLineDash([3, 3]); ctx.beginPath();
      pts.forEach(([x, y], i) => { const [sx, sy] = toScreen(x, y); i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy); });
      ctx.stroke(); ctx.setLineDash([]);
      const [ex, ey] = toScreen(it.x, it.y);
      if (it.kind !== 'end') {
        ctx.beginPath(); ctx.arc(ex, ey, 7, 0, 7); ctx.stroke();
        if (it.kind === 'intersection') { ctx.beginPath(); ctx.arc(ex, ey, 3, 0, 7); ctx.fill(); }
        if (it.kind === 'intersection') for (const d of it.dirs) {
          const a = d.deg * Math.PI / 180;
          ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(ex + 18 * Math.cos(a), ey + 18 * Math.sin(a)); ctx.stroke();
        }
      }
      const label = `${it.kind === 'end' ? 'cul-de-sac' : it.kind === 'junction' ? 'jonction' : it.kind === 'intersection' ? 'intersection' : ''} ${Math.round(it.conf * 100)} %`.trim();
      ctx.fillText(label, ex + 10, ey - 8);
    }
    if (!prop.items.length) { const [sx, sy] = toScreen(c.x, c.y); ctx.fillText('aucune direction ?', sx + 10, sy - 8); }
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
  Audit.draw();
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
canvas.addEventListener('mousedown', e => {
  if ((mode === 'auto' || mode === 'wand') && Auto.down(e)) return;
  drag = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false, btn: e.button };
});
// Recalcule hover/snap depuis la dernière position écran de la souris : la vue peut avoir
// bougé (recentrage après un clic, molette) sans que la souris ait bougé.
let mouse = null;
function updateHover() {
  if (!mouse) return;
  const r = canvas.getBoundingClientRect();
  const [mx, my] = toMap(mouse.x - r.left, mouse.y - r.top);
  hover = { x: mx, y: my };
  snapId = null; snapEdge = null;
  if ((mode === 'auto' || mode === 'wand')) return typeof Auto !== 'undefined' && Auto.hover(mx, my);
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
}
window.addEventListener('mousemove', e => {
  mouse = { x: e.clientX, y: e.clientY };
  if (drag && drag.btn !== 2) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.hypot(dx, dy) > 4) drag.moved = true;
    if (drag.moved) { view.cx = drag.cx - dx / view.s; view.cy = drag.cy - dy / view.s; }
  }
  if ((mode === 'auto' || mode === 'wand') && typeof Auto !== 'undefined') Auto.move(e);
  updateHover();
});
window.addEventListener('mouseup', e => {
  if ((mode === 'auto' || mode === 'wand') && Auto.up(e)) { drag = null; updateHover(); return; }
  if (!drag) return;
  const d = drag; drag = null;
  if (d.moved || e.target !== canvas) return;
  mouse = { x: e.clientX, y: e.clientY };
  updateHover();
  if ((mode === 'auto' || mode === 'wand')) return Auto.click(e);
  if (snapId != null) { joinTo(snapId); return; }
  if (snapEdge) { splitEdge(snapEdge); return; }
  const hit = e.button === 0 && !e.shiftKey && proposalAt(hover.x, hover.y);
  if (hit) { acceptProposal(hit); return; }
  const kind = (e.button === 2 || e.shiftKey) ? 'intersection' : nextKind;
  placePoint(hover.x, hover.y, kind);
});
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const r = canvas.getBoundingClientRect(), sx = e.clientX - r.left, sy = e.clientY - r.top;
  const [mx, my] = toMap(sx, sy);
  view.s = Math.min(40, Math.max(0.02, view.s * Math.exp(-e.deltaY * 0.0015)));
  view.cx = mx - (sx - W / 2) / view.s; view.cy = my - (sy - H / 2) / view.s;
  mouse = { x: e.clientX, y: e.clientY };
  updateHover();
}, { passive: false });
window.addEventListener('keydown', e => {
  if (e.target.matches('input,select,textarea')) return;
  const k = e.key.toLowerCase();
  if ((mode === 'auto' || mode === 'wand') && Auto.key(e)) return;
  if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); doUndo(); return; }
  if (e.ctrlKey || e.metaKey) return;
  if (k === ' ') { e.preventDefault(); doAdvance(); }
  else if (k === 'enter') { e.preventDefault(); acceptProposal(); }
  else if (k === 'a') { project.settings.assist = !project.settings.assist; syncSettingsUI(); refresh(true); }
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
function setMode(m) {
  mode = m; localStorage.setItem('mt-mode', m); document.body.dataset.mode = m;
  document.querySelectorAll('#modeSeg button').forEach(b => b.classList.toggle('active', b.dataset.mode === m));
  $('main').classList.remove('arm');
  refresh(false); Audit.ui();
}
document.querySelectorAll('#modeSeg button').forEach(b => b.onclick = () => setMode(b.dataset.mode));
function updateUI() {
  const c = cur();
  const st = $('status');
  $('mapInfo').textContent = project.map ? `${project.map.name} — ${project.map.width}×${project.map.height} px${project.map.georef ? ' · géoréférencée' : ''}` : 'Aucune carte chargée.';
  updateAssistInfo();
  if ((mode === 'auto' || mode === 'wand')) return Auto.ui();
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
    `<span>Longueur <b>${Math.round(len)} px</b></span><span>Événements <b>${project.events.length}</b></span>` +
    `<span>Propositions suivies <b>${project.events.filter(ev => ev.prop && ev.accepted).length}</b></span><span>corrigées <b>${project.events.filter(ev => ev.prop && !ev.accepted).length}</b></span>`;
  $('btnKind').innerHTML = `Prochain point : <b>${nextKind}</b>`; $('btnKind').classList.toggle('active', nextKind === 'intersection');
  $('btnAdvance').disabled = !c || D.done || !isBranching(c);
  $('btnAccept').disabled = !c || D.done || !prop || !prop.items.length;
  $('btnAccept').classList.toggle('active', !!(prop && prop.items.length));
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
    if (ev.prop) d += ev.accepted ? ' ✓ proposé' : ' ✗ corrigé';
    return `<li>#${n} ${d}</li>`;
  }).join('');
  $('hud').textContent = '';
}
$('queue').addEventListener('click', e => { const li = e.target.closest('li'); if (!li) return; const p = D.points[+li.dataset.id]; view.cx = p.x; view.cy = p.y; updateHover(); });
let saveTimer = null;
function refresh(save) {
  D = derive(project.events, project.rev || 1);
  const c = cur();
  if (mode === 'trace' && c && (save || !img)) recenter();
  updateHover();
  updateUI(); dirty = true;
  requestProposal();
  if (save) { clearTimeout(saveTimer); saveTimer = setTimeout(() => idb.set('project', project), 300); }
}
$('assist').addEventListener('change', () => { project.settings.assist = $('assist').checked; refresh(true); });
$('modelSelect').addEventListener('change', () => { project.settings.model = $('modelSelect').value; refresh(true); });
$('proposeDist').addEventListener('change', () => { project.settings.proposeDist = Math.max(8, +$('proposeDist').value || 32); $('proposeDist').value = project.settings.proposeDist; refresh(true); });
$('btnAccept').onclick = () => acceptProposal();
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
    const mig = migrateProject({ format: FORMAT, rev: p.rev, name: p.name || '', map: p.map || null, settings: { window: 256, allowOutside: true, ...p.settings }, events: p.events || [] });
    project = mig.project;
    if (mig.status === 'migrated') warn('Projet importé réparé : des « cul-de-sac » enregistrés à tort ont été retirés.');
    if (mig.status === 'kept') warn('Projet ancien conservé tel quel (comportement d’avant la correction des jonctions).');
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
function syncSettingsUI() {
  $('winSize').value = project.settings.window; $('allowOutside').checked = project.settings.allowOutside; $('projName').value = project.name || '';
  $('assist').checked = !!project.settings.assist; $('proposeDist').value = project.settings.proposeDist || 32;
  syncModelUI();
}

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
  document.body.dataset.mode = mode;
  resize(); loop();
  await idb.open();
  try { mapIndex = await (await fetch('../maps/index.json')).json(); } catch (_) { mapIndex = []; }
  try { const r = await fetch('../api/model'); modelInfo = await r.json(); } catch (_) { modelInfo = null; }
  mapIndex.forEach(m => { m.url = '../' + m.url; if (m.georef) m.georef = '../' + m.georef; });
  $('mapSelect').innerHTML += mapIndex.map(m => `<option value="${m.id}">${m.name}</option>`).join('');
  const saved = await idb.get('project');
  if (saved && saved.format === FORMAT) {
    const mig = migrateProject({ ...newProject(), ...saved, rev: saved.rev, settings: { ...newProject().settings, ...saved.settings } });
    project = mig.project;
    if (mig.status !== 'ok') {
      if (!(await idb.get('projectBackup'))) await idb.set('projectBackup', saved);   // copie intacte avant réparation
      await idb.set('project', project);
      warn(mig.status === 'migrated' ? 'Projet réparé : des « cul-de-sac » enregistrés à tort ont été retirés (sauvegarde gardée).'
                                     : 'Projet ancien conservé tel quel (comportement d’avant la correction des jonctions).');
    }
  }
  syncSettingsUI();
  document.querySelectorAll('#modeSeg button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  await Auto.init(); await Audit.load();
  if (project.map) {
    const entry = mapIndex.find(m => m.id === project.map.id);
    const blob = entry ? null : await idb.get('mapBlob');
    if (entry) { $('mapSelect').value = entry.id; await loadMapEntry(entry, true); }
    else if (blob) await setImage(blob, { id: project.map.id, name: project.map.name, georef: project.map.georef });
  }
  refresh(false);
  if ((mode === 'auto' || mode === 'wand')) recenter();
})();
