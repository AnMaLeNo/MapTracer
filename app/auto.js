/* MapTracer — mode « Auto » : le modèle trace tout depuis un point de départ, l'humain annote à la main là où il voit
   des erreurs (clic n'importe où sur la carte), et exporte ces groupes de points — les « zones », dont le rectangle est
   calculé autour des points — comme mini-datasets d'exemples difficiles.
   Dépend des globales d'app.js (img, view, toScreen/toMap, canvas, ctx, $, idb, mapIndex, project, currentModel, warn). */
'use strict';

const ZFORMAT = 'maptracer-zones/1';
let auto = newAuto();
function newAuto() {
  return { format: ZFORMAT, rev: 1, name: '', map: null, graph: { nodes: [], edges: [] }, seeds: [], zones: [], job: null, budget: 20000 };
}
// état d'interaction (non sauvegardé)
const A = { idx: null, idxOf: null, active: null, sel: null, hNode: null, hEdge: null, ndrag: null, arm: false,
            poll: null, undo: [], hover: null, hZone: null };
const ZMARGIN = 32;                      // rectangle d'une zone = ses points ± cette marge (contexte du modèle gardé, rapport, trace.py --zone)

/* ---------- graphe du tracé automatique ---------- */
function autoIndex() {
  if (A.idxOf === auto.graph && A.idx) return A.idx;
  const node = new Map(), adj = new Map();
  for (const n of auto.graph.nodes) { node.set(n.id, n); adj.set(n.id, new Set()); }
  for (const e of auto.graph.edges) { if (adj.has(e.from) && adj.has(e.to)) { adj.get(e.from).add(e.to); adj.get(e.to).add(e.from); } }
  A.idx = { node, adj }; A.idxOf = auto.graph;
  return A.idx;
}
function inBox(b, x, y) { return x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]; }
function clipToBox(b, p, q) {           // point de sortie du segment p(dedans)→q(dehors) sur le bord du rectangle
  let t = 1;
  const dx = q.x - p.x, dy = q.y - p.y;
  if (q.x > b[2]) t = Math.min(t, (b[2] - p.x) / dx);
  if (q.x < b[0]) t = Math.min(t, (b[0] - p.x) / dx);
  if (q.y > b[3]) t = Math.min(t, (b[3] - p.y) / dy);
  if (q.y < b[1]) t = Math.min(t, (b[1] - p.y) / dy);
  return { x: p.x + t * dx, y: p.y + t * dy };
}
const r1 = v => Math.round(v * 10) / 10;

/* ---------- zones ---------- */
function zoneDegrees(z) {
  const d = new Map(z.nodes.map(n => [n.id, 0]));
  for (const [a, b] of z.edges) { d.set(a, (d.get(a) || 0) + 1); d.set(b, (d.get(b) || 0) + 1); }
  return d;
}
function zoneBBox(z) {
  if (!z.nodes.length) return z.bbox;
  const xs = z.nodes.map(n => n.x), ys = z.nodes.map(n => n.y);
  z.bbox = [Math.min(...xs) - ZMARGIN, Math.min(...ys) - ZMARGIN, Math.max(...xs) + ZMARGIN, Math.max(...ys) + ZMARGIN].map(r1);
  return z.bbox;
}
function autoContext(bbox) {             // tracé du modèle dans le rectangle (gardé pour mémoire dans z.auto, affiché en rouge)
  const { node } = autoIndex();
  const ctxG = { nodes: [], edges: [] }, map = new Map();
  let nid = 1;
  const add = (x, y, kind) => { const n = { id: nid++, x: r1(x), y: r1(y), kind }; ctxG.nodes.push(n); return n.id; };
  for (const n of auto.graph.nodes) if (inBox(bbox, n.x, n.y)) map.set(n.id, add(n.x, n.y, n.kind === 'start' ? 'normal' : n.kind));
  for (const e of auto.graph.edges) {
    const p = node.get(e.from), q = node.get(e.to);
    if (!p || !q) continue;
    const ip = map.has(e.from), iq = map.has(e.to);
    if (ip && iq) ctxG.edges.push([map.get(e.from), map.get(e.to)]);
    else if (ip || iq) { const inn = ip ? p : q, out = ip ? q : p, c = clipToBox(bbox, inn, out); ctxG.edges.push([map.get(inn.id), add(c.x, c.y, 'normal')]); }
  }
  return ctxG;
}
function createZone(x, y, kind = 'normal') {   // nouveau groupe de points, démarré par un clic dans le vide
  const z = { id: (auto.zones.reduce((m, q) => Math.max(m, q.id), 0) || 0) + 1, bbox: [x, y, x, y], nodes: [], edges: [],
              auto: { nodes: [], edges: [] }, model: project.settings.model || (auto.job && auto.job.model) || '', created: new Date().toISOString(), nextId: 1, edits: 0 };
  auto.zones.push(z);
  A.active = auto.zones.length - 1; A.sel = null; A.undo = [];
  addNode(x, y, null, kind);
}
function activate(i) {
  if (A.active !== i) { A.active = i; A.sel = null; A.undo = []; }
}
function touch() {                       // après chaque modification : rectangle recalculé, groupe vide supprimé
  const z = zone(); if (!z) return;
  if (!z.nodes.length) { auto.zones.splice(A.active, 1); A.active = null; A.sel = null; A.undo = []; }
  else zoneBBox(z);
}
function mergeZones(i, j) {              // relier deux groupes : j rejoint i (ids renumérotés), renvoie la correspondance des ids de j
  const a = auto.zones[i], b = auto.zones[j], map = new Map();
  for (const n of b.nodes) { map.set(n.id, a.nextId); a.nodes.push({ ...n, id: a.nextId++ }); }
  for (const [u, v] of b.edges) a.edges.push([map.get(u), map.get(v)]);
  a.edits += b.edits + 1;
  auto.zones.splice(j, 1);
  A.active = auto.zones.indexOf(a); zoneBBox(a);
  return map;
}
function zone() { return A.active == null ? null : auto.zones[A.active]; }
function zNode(z, id) { return z.nodes.find(n => n.id === id); }
function snapshot() {
  const z = zone(); if (!z) return;
  A.undo.push(JSON.stringify({ nodes: z.nodes, edges: z.edges, nextId: z.nextId }));
  if (A.undo.length > 200) A.undo.shift();
  z.edits++;
}
function zoneUndo() {
  const z = zone(); if (!z || !A.undo.length) return;
  Object.assign(z, JSON.parse(A.undo.pop()));
  if (A.sel != null && !zNode(z, A.sel)) A.sel = null;
  touch(); autoSave(); dirty = true; Auto.ui();
}
function hasEdge(z, a, b) { return z.edges.some(([u, v]) => (u === a && v === b) || (u === b && v === a)); }
function addNode(x, y, connectTo, kind = 'normal') {
  const z = zone(); snapshot();
  const n = { id: z.nextId++, x: r1(x), y: r1(y), kind, open: false };
  z.nodes.push(n);
  if (connectTo != null && zNode(z, connectTo)) z.edges.push([connectTo, n.id]);
  A.sel = n.id; touch(); autoSave(); dirty = true; Auto.ui();
}
function deleteNode(id) {
  const z = zone(); if (!z || !zNode(z, id)) return; snapshot();
  z.nodes = z.nodes.filter(n => n.id !== id); z.edges = z.edges.filter(([a, b]) => a !== id && b !== id);
  if (A.sel === id) A.sel = null;
  touch(); autoSave(); dirty = true; Auto.ui();
}
function toggleEdge(a, b) {
  const z = zone(); if (!z || a === b) return; snapshot();
  if (hasEdge(z, a, b)) z.edges = z.edges.filter(([u, v]) => !((u === a && v === b) || (u === b && v === a)));
  else z.edges.push([a, b]);
  autoSave(); dirty = true; Auto.ui();
}
function splitZoneEdge(h) {
  const z = zone(); snapshot();
  z.edges = z.edges.filter(([u, v]) => !(u === h.a && v === h.b));
  const n = { id: z.nextId++, x: r1(h.x), y: r1(h.y), kind: 'normal', open: false };
  z.nodes.push(n); z.edges.push([h.a, n.id], [n.id, h.b]);
  A.sel = n.id; touch(); autoSave(); dirty = true; Auto.ui();
}
function toggleEnd(id) {
  const z = zone(); const n = z && zNode(z, id); if (!n) return;
  if ((zoneDegrees(z).get(id) || 0) > 1) return warn('Un cul-de-sac est une extrémité (un seul segment).');
  snapshot(); n.kind = n.kind === 'end' ? 'normal' : 'end'; n.open = false;
  autoSave(); dirty = true; Auto.ui();
}
function toggleKind(id) {
  const z = zone(); const n = z && zNode(z, id); if (!n) return;
  snapshot(); n.kind = n.kind === 'intersection' ? 'normal' : 'intersection';
  autoSave(); dirty = true; Auto.ui();
}
function nodeAt(z, mx, my) {
  let best = 9 / view.s, hit = null;
  for (const n of z.nodes) { const d = Math.hypot(n.x - mx, n.y - my); if (d < best) { best = d; hit = n.id; } }
  return hit;
}
function findNode(mx, my) {              // point le plus proche, toutes zones confondues
  let best = null;
  auto.zones.forEach((z, zi) => { const id = nodeAt(z, mx, my); if (id != null) { const n = zNode(z, id), d = Math.hypot(n.x - mx, n.y - my); if (!best || d < best.d) best = { zi, id, d }; } });
  return best;
}
function findEdge(mx, my) {
  let best = null;
  auto.zones.forEach((z, zi) => { const h = edgeAt(z, mx, my); if (h) { const d = Math.hypot(h.x - mx, h.y - my); if (!best || d < best.d) best = { zi, h, d }; } });
  return best;
}
function edgeAt(z, mx, my) {
  let best = 7 / view.s, hit = null; const gap = 4 / view.s;
  for (const [a, b] of z.edges) {
    const p = zNode(z, a), q = zNode(z, b); if (!p || !q) continue;
    const vx = q.x - p.x, vy = q.y - p.y, L2 = vx * vx + vy * vy; if (!L2) continue;
    const t = Math.max(0, Math.min(1, ((mx - p.x) * vx + (my - p.y) * vy) / L2));
    const x = p.x + t * vx, y = p.y + t * vy, d = Math.hypot(x - mx, y - my);
    if (d < best && Math.hypot(x - p.x, y - p.y) > gap && Math.hypot(x - q.x, y - q.y) > gap) { best = d; hit = { a, b, x, y }; }
  }
  return hit;
}

/* ---------- suivi automatique (serveur) ---------- */
function mapUrl() {
  if (!project.map || project.map.id.startsWith('local:')) return null;
  const entry = mapIndex.find(m => m.id === project.map.id);
  return entry ? entry.url.replace(/^\.\.\//, '') : null;
}
async function startTrace(x, y) {
  if (!img) return warn('Chargez une carte.');
  const url = mapUrl(); if (!url) return warn('Carte locale : le serveur ne la connaît pas (choisissez-la dans la liste).');
  const cm = currentModel(); if (!cm) return warn('Aucun modèle disponible (dossier models/ vide ou server.py --model …).');
  if (auto.job && auto.job.status === 'running') return warn('Un suivi est déjà en cours (arrêtez-le d’abord).');
  x = Math.round(x); y = Math.round(y);
  if (x < 0 || y < 0 || x >= img.width || y >= img.height) return warn('Hors de la carte.');
  A.arm = false; $('main').classList.remove('arm');
  try {
    const body = { map: url, model: cm.name, x, y, max_steps: auto.budget, graph: auto.graph.nodes.length ? auto.graph : undefined };
    const r = await fetch('../api/trace', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const res = await r.json();
    if (!r.ok) return warn('Suivi impossible : ' + (res.error || r.status));
    auto.map = project.map; auto.seeds.push([x, y]); auto.job = { id: res.id, status: res.status, model: res.model };
    autoSave(true); pollJob(); Auto.ui();
  } catch (err) { warn('Erreur : ' + err.message); }
}
function pollJob() {
  clearTimeout(A.poll);
  if (!auto.job || auto.job.status !== 'running') return;
  A.poll = setTimeout(async () => {
    try {
      const r = await fetch(`../api/trace/${auto.job.id}`);
      const res = await r.json();
      if (!r.ok) { auto.job.status = 'lost'; auto.job.error = res.error; autoSave(); Auto.ui(); return; }
      auto.graph = res.graph || auto.graph; A.idxOf = null;
      Object.assign(auto.job, { status: res.status, steps: res.steps, branches: res.branches, queue: res.queue, reasons: res.reasons,
                                elapsed: res.elapsed_s, error: res.error, model: res.model });
      dirty = true; Auto.ui();
      if (res.status === 'running') pollJob(); else autoSave(true);
    } catch (err) { pollJob(); }
  }, 700);
}
async function stopTrace() {
  if (!auto.job || auto.job.status !== 'running') return;
  try { await fetch(`../api/trace/${auto.job.id}/stop`, { method: 'POST' }); } catch (_) {}
}

/* ---------- persistance / export ---------- */
let autoSaveTimer = null;
function autoSave(now) {           // différé pendant les glisser-déposer ; immédiat pour les changements de structure
  clearTimeout(autoSaveTimer);
  if (now) return idb.set('auto', auto);
  autoSaveTimer = setTimeout(() => idb.set('auto', auto), 300);
}
window.addEventListener('pagehide', () => { if (autoSaveTimer) { clearTimeout(autoSaveTimer); autoSaveTimer = null; idb.set('auto', auto); } });
function normalizedZone(z) {       // `open` cohérent avec le graphe : toute extrémité (degré ≤ 1) qui n'est pas un cul-de-sac
  const deg = zoneDegrees(z);
  const nodes = z.nodes.map(n => ({ ...n, open: n.kind !== 'end' && (deg.get(n.id) || 0) <= 1 }));
  const bbox = zoneBBox(z);
  const ctx = auto.graph.nodes.length ? autoContext(bbox) : z.auto;   // ce que le modèle avait tracé là, pour mémoire
  return { ...z, bbox, nodes, auto: ctx, open_ends: nodes.filter(n => n.open).length, ends: nodes.filter(n => n.kind === 'end').length };
}
function zonesExport() {
  if (!auto.zones.length) return warn('Rien à exporter : cliquez sur la carte pour poser des points là où le modèle se trompe.');
  const j = auto.job || {};
  const out = { format: ZFORMAT, rev: 1, name: auto.name || project.name || '', map: auto.map || project.map, exported: new Date().toISOString(),
                // provenance, pour qui entraîne : d'où viennent ces zones et ce que le modèle avait tracé
                provenance: { mode: 'auto', app: { commit: (modelInfo && modelInfo.commit) || null, url: location.href.split('?')[0], userAgent: navigator.userAgent },
                              model: j.model || project.settings.model || null, server: modelInfo ? { device: modelInfo.device, commit: modelInfo.commit || null } : null,
                              budget: auto.budget, job: j.id ? { status: j.status, steps: j.steps, branches: j.branches, reasons: j.reasons, elapsed_s: j.elapsed } : null,
                              zones_models: [...new Set(auto.zones.map(z => z.model).filter(Boolean))] },
                seeds: auto.seeds, trace: { nodes: auto.graph.nodes, edges: auto.graph.edges }, zones: auto.zones.map(normalizedZone) };
  const blob = new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = `${(out.name || (out.map && out.map.id) || 'zones').replace(/[^\w.-]+/g, '_')}.mapzones.json`;
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
async function zonesImport(f) {
  try {
    const p = JSON.parse(await f.text());
    if (p.format !== ZFORMAT || !Array.isArray(p.zones)) throw new Error('format inconnu');
    if (project.map && p.map && p.map.id !== project.map.id && !confirm(`Ces zones viennent de la carte « ${p.map.name} », pas de la carte ouverte. Importer quand même ?`)) return;
    const replace = auto.zones.length ? confirm('OK = remplacer les zones actuelles, Annuler = les ajouter à la suite.') : true;
    const zs = p.zones.map(z => ({ auto: { nodes: [], edges: [] }, edits: 0, nextId: z.nodes.reduce((m, n) => Math.max(m, n.id), 0) + 1, ...z }));
    auto.zones = replace ? zs : auto.zones.concat(zs);
    auto.zones.forEach((z, i) => { z.id = i + 1; });
    if (replace) { auto.name = p.name || auto.name; if (p.seeds) auto.seeds = p.seeds; if (p.map) auto.map = p.map; }
    if (p.trace && Array.isArray(p.trace.nodes) && (replace || !auto.graph.nodes.length)) { auto.graph = { nodes: p.trace.nodes, edges: p.trace.edges || [] }; A.idxOf = null; }
    A.active = null; A.sel = null; A.undo = [];
    await autoSave(true); dirty = true; Auto.ui();
  } catch (err) { warn('Import impossible : ' + err.message); }
}

/* ---------- interface ---------- */
const Auto = {
  async init() {
    const saved = await idb.get('auto');
    if (saved && saved.format === ZFORMAT) auto = { ...newAuto(), ...saved };
    $('autoBudget').value = auto.budget;
    if (auto.job && auto.job.status === 'running') pollJob();
    $('autoBudget').addEventListener('change', () => { auto.budget = Math.max(100, +$('autoBudget').value || 20000); $('autoBudget').value = auto.budget; autoSave(); });
    $('btnAutoSeed').onclick = () => { A.arm = !A.arm; $('main').classList.toggle('arm', A.arm); Auto.ui(); };
    $('btnAutoStop').onclick = stopTrace;
    $('btnAutoClear').onclick = async () => {
      if (!confirm('Effacer le tracé automatique, les départs et toutes les zones ?')) return;
      await stopTrace(); auto = { ...newAuto(), budget: auto.budget }; A.active = null; A.sel = null; A.undo = []; A.idxOf = null;
      autoSave(true); dirty = true; Auto.ui();
    };
    $('btnZoneDelete').onclick = () => { const z = zone(); if (!z || !confirm(`Supprimer la zone ${z.id} et ses corrections ?`)) return; auto.zones.splice(A.active, 1); A.active = null; A.sel = null; A.undo = []; autoSave(true); dirty = true; Auto.ui(); };
    $('btnZoneUndo').onclick = zoneUndo;
    $('btnZoneDone').onclick = () => { A.active = null; A.sel = null; A.undo = []; dirty = true; Auto.ui(); };
    $('btnZonesExport').onclick = zonesExport;
    $('zonesImport').addEventListener('change', e => { if (e.target.files[0]) zonesImport(e.target.files[0]); e.target.value = ''; });
    $('zones').addEventListener('click', e => {
      const li = e.target.closest('li'); if (!li) return;
      const i = +li.dataset.i; const z = auto.zones[i]; if (!z) return;
      if (A.active !== i) { A.active = i; A.sel = null; A.undo = []; }
      view.cx = (z.bbox[0] + z.bbox[2]) / 2; view.cy = (z.bbox[1] + z.bbox[3]) / 2;
      view.s = Math.min(W, H) * 0.8 / Math.max(32, z.bbox[2] - z.bbox[0], z.bbox[3] - z.bbox[1]);
      dirty = true; Auto.ui();
    });
    Auto.ui();
  },
  recenter() {
    const z = zone();
    if (z) { view.cx = (z.bbox[0] + z.bbox[2]) / 2; view.cy = (z.bbox[1] + z.bbox[3]) / 2; view.s = Math.min(W, H) * 0.8 / Math.max(32, z.bbox[2] - z.bbox[0], z.bbox[3] - z.bbox[1]); }
    else if (auto.seeds.length) { const [x, y] = auto.seeds[auto.seeds.length - 1]; view.cx = x; view.cy = y; view.s = Math.max(view.s, 1); }
    else if (img) { view.cx = img.width / 2; view.cy = img.height / 2; view.s = Math.min(W / img.width, H / img.height); }
    dirty = true;
  },
  hover(mx, my) {
    A.hover = { x: mx, y: my }; A.hNode = null; A.hEdge = null; A.hZone = null;
    const n = findNode(mx, my);
    if (n) { A.hNode = n.id; A.hZone = n.zi; }
    else { const h = findEdge(mx, my); if (h) { A.hEdge = h.h; A.hZone = h.zi; } }
    dirty = true;
  },
  down(e) {
    const r = canvas.getBoundingClientRect(), [mx, my] = toMap(e.clientX - r.left, e.clientY - r.top);
    if (e.button !== 0) return false;
    const hit = findNode(mx, my);
    if (!hit) return false;
    const n = zNode(auto.zones[hit.zi], hit.id);
    A.ndrag = { zi: hit.zi, id: hit.id, sx: e.clientX, sy: e.clientY, moved: false, ox: n.x, oy: n.y };
    return true;
  },
  move(e) {
    const r = canvas.getBoundingClientRect(), [mx, my] = toMap(e.clientX - r.left, e.clientY - r.top);
    if (A.ndrag) {
      if (!A.ndrag.moved && Math.hypot(e.clientX - A.ndrag.sx, e.clientY - A.ndrag.sy) > 3) { A.ndrag.moved = true; activate(A.ndrag.zi); snapshot(); }
      if (A.ndrag.moved) { const n = zNode(zone(), A.ndrag.id); if (n) { n.x = r1(mx); n.y = r1(my); dirty = true; } }
    }
  },
  up(e) {
    if (A.ndrag) {
      const d = A.ndrag; A.ndrag = null;
      if (d.moved) { touch(); autoSave(); Auto.ui(); }
      else if (e.ctrlKey && A.sel != null && A.active != null && !(d.zi === A.active && A.sel === d.id)) {
        let id = d.id;
        if (d.zi !== A.active) { snapshot(); id = mergeZones(A.active, d.zi).get(d.id); }   // relier deux groupes = les fusionner
        toggleEdge(A.sel, id);
      }
      else { activate(d.zi); A.sel = d.id; dirty = true; Auto.ui(); }
      return true;
    }
    return false;
  },
  click(e) {
    const r = canvas.getBoundingClientRect(), [mx, my] = toMap(e.clientX - r.left, e.clientY - r.top);
    const hit = findNode(mx, my);
    if (e.button === 2) {                // clic droit : carrefour (nouveau point relié au point courant, ou bascule du type d'un point existant)
      if (hit) { activate(hit.zi); toggleKind(hit.id); A.sel = hit.id; dirty = true; Auto.ui(); return; }
      if (A.sel != null && zone()) return addNode(mx, my, A.sel, 'intersection');
      return createZone(mx, my, 'intersection');
    }
    if (e.button !== 0) return;
    if (A.arm || (!auto.graph.nodes.length && !(auto.job && auto.job.status === 'running') && !auto.zones.length)) return startTrace(mx, my);
    if (hit) { activate(hit.zi); A.sel = hit.id; dirty = true; Auto.ui(); return; }
    const eh = findEdge(mx, my);
    if (eh) { activate(eh.zi); return splitZoneEdge(eh.h); }
    if (A.sel != null && zone()) return addNode(mx, my, A.sel);   // point suivant, relié au point courant
    return createZone(mx, my);                                     // clic dans le vide sans point courant : nouveau groupe
  },
  key(e) {
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); zoneUndo(); return true; }
    if (e.ctrlKey || e.metaKey) return false;
    if (k === 'delete' || k === 'backspace') { if (A.sel != null) { e.preventDefault(); deleteNode(A.sel); } return true; }
    if (k === 'f') { if (A.sel != null) toggleEnd(A.sel); return true; }
    if (k === 'i') { if (A.sel != null) toggleKind(A.sel); return true; }
    if (k === 'escape') {
      if (A.arm) { A.arm = false; $('main').classList.remove('arm'); }
      else if (A.sel != null) A.sel = null;
      else if (A.active != null) { A.active = null; A.undo = []; }
      dirty = true; Auto.ui(); return true;
    }
    if (k === 'c') { Auto.recenter(); return true; }
    return [' ', 'enter', 'a', 't'].includes(k);
  },
  draw() {
    const z = zone(), s = view.s;
    const vis = (x, y) => x > -30 && y > -30 && x < W + 30 && y < H + 30;
    // tracé automatique
    const { node } = autoIndex();
    const dim = z ? 'rgba(255,77,77,.55)' : 'rgba(255,77,77,.9)';
    // si le tracé global a été effacé (ou zones importées), le contexte gardé dans la zone active prend le relais
    const G = (!auto.graph.nodes.length && z && z.auto && z.auto.nodes.length)
      ? { nodes: z.auto.nodes, edges: z.auto.edges.map(([a, b]) => ({ from: a, to: b })), node: new Map(z.auto.nodes.map(n => [n.id, n])) }
      : { nodes: auto.graph.nodes, edges: auto.graph.edges, node };
    ctx.lineWidth = Math.max(1, Math.min(3, s));
    for (const e of G.edges) {
      const a = G.node.get(e.from), b = G.node.get(e.to); if (!a || !b) continue;
      const [x0, y0] = toScreen(a.x, a.y), [x1, y1] = toScreen(b.x, b.y);
      if (!vis(x0, y0) && !vis(x1, y1)) continue;
      ctx.strokeStyle = dim;
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    }
    const r = Math.max(2.5, Math.min(6, s * 1.3));
    for (const n of G.nodes) {
      const [x, y] = toScreen(n.x, n.y); if (!vis(x, y)) continue;
      if (n.kind === 'intersection') { ctx.strokeStyle = '#ff7a1a'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y, r * 1.3, 0, 7); ctx.stroke(); }
      else if (n.kind === 'end') { ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r); ctx.moveTo(x + r, y - r); ctx.lineTo(x - r, y + r); ctx.stroke(); }
      else if (n.kind === 'start') { ctx.fillStyle = '#39c47c'; ctx.beginPath(); ctx.arc(x, y, r * 1.4, 0, 7); ctx.fill(); }
      else if (s > 2.5) { ctx.fillStyle = dim; ctx.beginPath(); ctx.arc(x, y, Math.min(2.5, s * 0.5), 0, 7); ctx.fill(); }
    }
    // zones : étiquette au coin du rectangle calculé autour des points (pas de rectangle dessiné), graphes corrigés
    ctx.font = '12px system-ui, sans-serif'; ctx.textBaseline = 'bottom';
    auto.zones.forEach((q, i) => {
      const act = i === A.active;
      const [x0, y0] = toScreen(q.bbox[0], q.bbox[1]);
      if (vis(x0, y0)) { ctx.fillStyle = act ? '#ffd166' : 'rgba(255,209,102,.6)'; ctx.fillText(`zone ${q.id}${q.edits ? ' · ' + q.edits + ' modif.' : ''}`, x0 + 2, y0 - 3); }
      const deg = zoneDegrees(q);
      const lw = Math.max(1.5, Math.min(4, s * 1.2));
      for (const [a, b] of q.edges) {
        const p = zNode(q, a), w = zNode(q, b); if (!p || !w) continue;
        const [ax, ay] = toScreen(p.x, p.y), [bx, by] = toScreen(w.x, w.y);
        if (!vis(ax, ay) && !vis(bx, by)) continue;
        const hl = act && A.hEdge && A.hZone === i && A.hEdge.a === a && A.hEdge.b === b;
        ctx.strokeStyle = hl ? '#ff7a1a' : act ? '#4ea1ff' : 'rgba(78,161,255,.6)'; ctx.lineWidth = hl ? 5 : lw;
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      }
      const rz = Math.max(3.5, Math.min(7, s * 1.5));
      for (const n of q.nodes) {
        const [x, y] = toScreen(n.x, n.y); if (!vis(x, y)) continue;
        const d = deg.get(n.id) || 0;
        ctx.globalAlpha = act ? 1 : 0.65;
        ctx.fillStyle = n.kind === 'intersection' ? '#ff7a1a' : n.kind === 'end' ? '#9aa7b5' : '#4ea1ff';
        ctx.beginPath(); ctx.arc(x, y, n.kind === 'intersection' ? rz * 1.4 : rz, 0, 7); ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = '#000'; ctx.stroke();
        if (n.kind === 'end') { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - rz, y - rz); ctx.lineTo(x + rz, y + rz); ctx.moveTo(x + rz, y - rz); ctx.lineTo(x - rz, y + rz); ctx.stroke(); }
        else if (d <= 1) { ctx.setLineDash([3, 3]); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y, rz * 2, 0, 7); ctx.stroke(); ctx.setLineDash([]); }
        ctx.globalAlpha = 1;
        if (A.hZone === i && n.id === A.hNode) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, rz * 2.4, 0, 7); ctx.stroke(); }
        if (act && n.id === A.sel) { ctx.strokeStyle = '#ff4d4d'; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(x, y, rz * 2.6, 0, 7); ctx.stroke(); }
      }
    });
    if (z) {
      if (A.hEdge && A.hZone === A.active) { const [x, y] = toScreen(A.hEdge.x, A.hEdge.y); ctx.strokeStyle = '#ff7a1a'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 8, 0, 7); ctx.stroke(); }
      if (A.sel != null && A.hover && A.hNode == null && !A.hEdge && !A.ndrag) {   // aperçu du prochain segment
        const p = zNode(z, A.sel);
        if (p) { const [x0, y0] = toScreen(p.x, p.y), [x1, y1] = toScreen(A.hover.x, A.hover.y); ctx.strokeStyle = 'rgba(255,255,255,.6)'; ctx.lineWidth = 1.5; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]); }
      }
    }
    // départs
    for (const [x, y] of auto.seeds) { const [sx, sy] = toScreen(x, y); if (!vis(sx, sy)) continue; ctx.strokeStyle = '#39c47c'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx, sy, 9, 0, 7); ctx.moveTo(sx - 13, sy); ctx.lineTo(sx + 13, sy); ctx.moveTo(sx, sy - 13); ctx.lineTo(sx, sy + 13); ctx.stroke(); }
    Audit.draw();
  },
  ui() {
    if (typeof mode !== 'undefined' && mode !== 'auto') { $('hud').textContent = ''; return; }
    const j = auto.job, z = zone(), st = $('status');
    $('stats').innerHTML = `<span>Tracé auto <b>${auto.graph.nodes.length}</b> pts</span><span>Départs <b>${auto.seeds.length}</b></span>` +
      `<span>Zones <b>${auto.zones.length}</b></span><span>Points corrigés <b>${auto.zones.reduce((n, q) => n + q.nodes.length, 0)}</b></span>`;
    const running = j && j.status === 'running';
    const names = { running: 'en cours', done: 'terminé (plus rien à suivre)', budget: 'arrêté : budget de pas atteint', stopped: 'arrêté à la main', error: 'erreur', lost: 'perdu (serveur redémarré ?)' };
    const reasons = r => r ? Object.entries(r).map(([k, v]) => `${{ end: 'culs-de-sac', junction: 'jonctions', low_confidence: 'perdu', out_of_map: 'bord de carte', max_steps: 'budget' }[k] || k} ${v}`).join(', ') : '';
    $('autoInfo').innerHTML = j ? `Suivi ${names[j.status] || j.status} — modèle <b>${j.model || ''}</b>${j.steps != null ? ` · ${j.steps} pas, ${j.branches} branches, ${j.queue} en file, ${j.elapsed || 0} s` : ''}` +
      (j.reasons ? `<br>Fins de branches : ${reasons(j.reasons)}` : '') + (j.error ? `<br>${j.error}` : '') : 'Aucun tracé : choisissez un modèle et cliquez un point de départ sur une galerie.';
    $('btnAutoStop').disabled = !running;
    $('btnAutoSeed').classList.toggle('active', A.arm);
    $('btnAutoSeed').textContent = A.arm ? 'Cliquez sur la carte… (Échap pour annuler)' : 'Nouveau départ : cliquer sur la carte';
    $('zoneCount').textContent = auto.zones.length;
    $('zones').innerHTML = auto.zones.map((q, i) => `<li data-i="${i}" class="${i === A.active ? 'active' : ''}">zone ${q.id} — ${q.nodes.length} pts, ${q.edges.length} seg., ${q.edits} modif. (${Math.round(q.bbox[2] - q.bbox[0])}×${Math.round(q.bbox[3] - q.bbox[1])} px)</li>`).join('');
    $('btnZoneDelete').disabled = !z; $('btnZoneDone').disabled = !z; $('btnZoneUndo').disabled = !z || !A.undo.length;
    if (z) {
      const deg = zoneDegrees(z);
      const ends = z.nodes.filter(n => n.kind === 'end').length, open = z.nodes.filter(n => (deg.get(n.id) || 0) <= 1 && n.kind !== 'end').length;
      $('zoneInfo').textContent = `Zone ${z.id} : ${z.nodes.length} points, ${z.edges.length} segments, ${ends} cul(s)-de-sac, ${open} extrémité(s) ouverte(s) (ignorées à l'entraînement), ${z.edits} modification(s) ; rectangle ${Math.round(z.bbox[2] - z.bbox[0])}×${Math.round(z.bbox[3] - z.bbox[1])} px autour des points.`;
    } else $('zoneInfo').textContent = '';
    if (!img) st.textContent = 'Chargez une carte (liste).';
    else if (A.arm) st.textContent = 'Cliquez le nouveau point de départ sur une galerie.';
    else if (!auto.graph.nodes.length && !running) st.textContent = 'Cliquez un point de départ sur une galerie : le modèle trace tout ce qu’il peut.';
    else if (z) st.textContent = A.sel != null ? `Zone ${z.id}, point ${A.sel} : clic = point suivant · clic droit = carrefour · F = cul-de-sac · Échap = finir cette branche (puis cliquez un point pour en repartir, ou dans le vide pour un nouveau groupe).`
                                               : `Zone ${z.id} : cliquez un de ses points pour continuer depuis là, ou dans le vide pour commencer un autre groupe.`;
    else st.textContent = running ? 'Le modèle trace… repérez les erreurs ; cliquez sur la carte pour annoter là où il se trompe.' : 'Inspectez le tracé rouge ; cliquez là où il se trompe et annotez comme en mode manuel (clic = point suivant, clic droit = carrefour, F = cul-de-sac).';
    $('hud').textContent = running ? `suivi : ${j.steps || 0} pas · ${j.branches || 0} branches · ${j.queue || 0} en file` : (z ? `zone ${z.id}` : '');
  },
};
