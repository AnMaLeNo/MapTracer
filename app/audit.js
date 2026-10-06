/* Anomalies d'annotation : un modèle déjà entraîné rejoue chaque point annoté (projet du mode Tracer ou zones du mode Auto)
   et ses désaccords remontent dans une liste à valider ou corriger. Le modèle n'est pas la vérité : « OK » = l'annotation
   est juste (et l'exemple est précieux), « À corriger » = je m'en occupe. Rien n'est modifié automatiquement.
   Dépend des globales d'app.js / auto.js (img, view, toScreen, canvas, ctx, $, idb, project, D, mode, auto, currentModel, mapUrl, warn). */
'use strict';

const AUDIT_TYPES = {
  end_missed: { label: 'cul-de-sac oublié ?', color: '#ff4d4d', help: 'extrémité sans F ; le modèle ne voit aucune suite' },
  false_end: { label: 'F contestable', color: '#ff5ce0', help: 'cul-de-sac annoté ; le modèle voit la galerie continuer' },
  branch_missed: { label: 'branche non annotée ?', color: '#ffd23c', help: 'le modèle voit une galerie que rien n’annote' },
  direction_missed: { label: 'galerie annotée invisible', color: '#39d8ff', help: 'le modèle ne voit pas la galerie annotée (point hors axe ? autre étage ?)' },
};

let audit = { job: null, items: [], status: {}, model: '', scope: '', filter: '', hide: false };
const AU = { sel: null, poll: null };

function auditKey(r) { return `${r.type}@${r.x},${r.y}`; }
function auditSave() { return idb.set('audit', audit); }

function traceGraph() {           // projet courant (mode Tracer) → graphe {nodes, edges} au format des zones
  const deg = {};
  for (const e of D.edges) { deg[e.from] = (deg[e.from] || 0) + 1; deg[e.to] = (deg[e.to] || 0) + 1; }
  const nodes = D.order.map(id => {
    const p = D.points[id];
    const ended = D.terminal[id] === 'end';
    return { id, x: p.x, y: p.y, kind: ended && (deg[id] || 0) <= 1 ? 'end' : (p.kind === 'start' ? 'normal' : p.kind), open: !ended && (deg[id] || 0) <= 1 };
  });
  return { name: project.name || 'projet', nodes, edges: D.edges.map(e => [e.from, e.to]) };
}
function auditGraphs() {
  if (mode === 'auto') return auto.zones.filter(z => z.edges.length).map(z => ({ name: `zone ${z.id}`, nodes: z.nodes, edges: z.edges }));
  return D.edges.length ? [traceGraph()] : [];
}

async function startAudit() {
  if (!img) return warn('Chargez une carte.');
  const url = mapUrl(); if (!url) return warn('Carte locale : le serveur ne la connaît pas (choisissez-la dans la liste).');
  const cm = currentModel(); if (!cm) return warn('Aucun modèle disponible.');
  if (audit.job && audit.job.status === 'running') return warn('Une vérification est déjà en cours.');
  const graphs = auditGraphs();
  if (!graphs.length) return warn(mode === 'auto' ? 'Aucune zone annotée à vérifier.' : 'Aucun segment annoté à vérifier.');
  try {
    const r = await fetch('../api/audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ map: url, model: cm.name, graphs }) });
    const res = await r.json();
    if (!r.ok) return warn('Vérification impossible : ' + (res.error || r.status));
    audit.job = { id: res.id, status: res.status, done: 0, total: 0 }; audit.model = cm.name; audit.scope = mode;
    audit.items = []; AU.sel = null;
    auditSave(); pollAudit(); Audit.ui();
  } catch (err) { warn('Erreur : ' + err.message); }
}
function pollAudit() {
  clearTimeout(AU.poll);
  if (!audit.job || audit.job.status !== 'running') return;
  AU.poll = setTimeout(async () => {
    try {
      const r = await fetch(`../api/audit/${audit.job.id}`);
      const res = await r.json();
      if (!r.ok) { audit.job.status = 'lost'; audit.job.error = res.error; auditSave(); Audit.ui(); return; }
      Object.assign(audit.job, { status: res.status, done: res.done, total: res.total, error: res.error, elapsed_s: res.elapsed_s });
      if (res.status !== 'running') {
        audit.items = res.anomalies || [];
        const keep = {}; for (const it of audit.items) { const k = auditKey(it); if (audit.status[k]) keep[k] = audit.status[k]; }
        audit.status = keep; dirty = true;
      }
      auditSave(); Audit.ui();
    } catch (err) { audit.job.status = 'lost'; audit.job.error = err.message; auditSave(); Audit.ui(); return; }
    pollAudit();
  }, 700);
}
async function stopAudit() {
  if (!audit.job || audit.job.status !== 'running') return;
  try { await fetch(`../api/audit/${audit.job.id}/stop`, { method: 'POST' }); } catch (_) { /* le poll constatera */ }
}
function auditVisible() {
  return audit.items.filter(it => (!audit.filter || it.type === audit.filter) && !(audit.hide && audit.status[auditKey(it)]));
}
function auditGoto(i) {
  const it = audit.items[i]; if (!it) return;
  AU.sel = i; view.cx = it.x; view.cy = it.y; if (view.s < 3) view.s = 3;
  dirty = true; Audit.ui();
}
function auditMark(i, st) {
  const it = audit.items[i]; if (!it) return;
  const k = auditKey(it);
  if (audit.status[k] === st) delete audit.status[k]; else audit.status[k] = st;
  auditSave(); dirty = true; Audit.ui();
}

const Audit = {
  async load() {
    const saved = await idb.get('audit');
    if (saved && saved.items) audit = { ...audit, ...saved };
    if (audit.job && audit.job.status === 'running') pollAudit();
    $('auditFilter').innerHTML = '<option value="">toutes les anomalies</option>' + Object.entries(AUDIT_TYPES).map(([k, t]) => `<option value="${k}">${t.label}</option>`).join('');
    $('auditFilter').value = audit.filter || ''; $('auditHide').checked = !!audit.hide;
    Audit.ui();
  },
  draw() {
    if (!audit.items.length || audit.scope !== mode) return;
    const vis = audit.hide ? auditVisible() : audit.items.filter(it => !audit.filter || it.type === audit.filter);
    for (const it of vis) {
      const [x, y] = toScreen(it.x, it.y);
      if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
      const st = audit.status[auditKey(it)], t = AUDIT_TYPES[it.type] || { color: '#fff' };
      const selected = audit.items[AU.sel] === it;
      ctx.save();
      ctx.globalAlpha = st === 'ok' ? 0.35 : 1;
      ctx.strokeStyle = st === 'fix' ? '#ff7a1a' : t.color; ctx.lineWidth = selected ? 3 : 2;
      ctx.setLineDash(st === 'ok' ? [3, 3] : []);
      const r = selected ? 14 : 10;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke();
      if (it.model_deg != null) {        // direction que le modèle voit (ou conteste)
        const a = it.model_deg * Math.PI / 180;
        ctx.beginPath(); ctx.moveTo(x + r * Math.cos(a), y + r * Math.sin(a)); ctx.lineTo(x + (r + 16) * Math.cos(a), y + (r + 16) * Math.sin(a)); ctx.stroke();
      }
      if (selected) { ctx.setLineDash([]); ctx.beginPath(); ctx.arc(x, y, r + 7, 0, 7); ctx.stroke(); }
      ctx.restore();
    }
  },
  ui() {
    const j = audit.job, info = $('auditInfo');
    const running = j && j.status === 'running';
    $('btnAudit').disabled = !!running; $('btnAuditStop').disabled = !running;
    const scopeTxt = audit.scope ? (audit.scope === 'auto' ? 'zones du mode Auto' : 'projet du mode Tracer') : '';
    if (running) info.textContent = `Vérification avec ${audit.model}… ${j.done || 0}/${j.total || '?'} états`;
    else if (j && j.status === 'error') info.textContent = 'Erreur : ' + j.error;
    else if (j && j.status === 'lost') info.textContent = 'Tâche perdue (serveur redémarré ?) : ' + (j.error || '');
    else if (j) info.textContent = `${audit.items.length} anomalie(s) — ${scopeTxt}, modèle ${audit.model}${j.elapsed_s ? `, ${j.elapsed_s} s` : ''}${j.status === 'stopped' ? ' (interrompu)' : ''}` +
      (audit.scope !== mode ? ` — affichées en mode ${audit.scope === 'auto' ? 'Auto' : 'Tracer'}` : '');
    else info.textContent = '';
    const vis = auditVisible();
    const nDone = audit.items.filter(it => audit.status[auditKey(it)]).length;
    $('auditCount').textContent = audit.items.length ? `${audit.items.length - nDone}/${audit.items.length}` : '0';
    $('auditList').innerHTML = vis.map(it => {
      const i = audit.items.indexOf(it), st = audit.status[auditKey(it)] || '', t = AUDIT_TYPES[it.type] || { label: it.type, color: '#fff' };
      return `<li data-i="${i}" class="${i === AU.sel ? 'active' : ''} st-${st}" title="${it.why}">` +
        `<span class="dot" style="background:${t.color}"></span><b>${Math.round(it.score * 100)}</b> ${t.label}` +
        `${it.n > 1 ? ` <span class="pill">×${it.n}</span>` : ''}${it.source && audit.scope === 'auto' ? ` <span class="muted">${it.source}</span>` : ''}` +
        `<span class="acts"><button data-st="ok" class="${st === 'ok' ? 'active' : ''}" title="L’annotation est juste : garder">OK</button>` +
        `<button data-st="fix" class="${st === 'fix' ? 'active' : ''}" title="À corriger">À corriger</button></span></li>`;
    }).join('');
  },
};

$('btnAudit').onclick = startAudit;
$('btnAuditStop').onclick = stopAudit;
$('auditFilter').addEventListener('change', () => { audit.filter = $('auditFilter').value; auditSave(); dirty = true; Audit.ui(); });
$('auditHide').addEventListener('change', () => { audit.hide = $('auditHide').checked; auditSave(); dirty = true; Audit.ui(); });
$('auditList').addEventListener('click', e => {
  const li = e.target.closest('li'); if (!li) return;
  const i = +li.dataset.i, b = e.target.closest('button');
  if (b) return auditMark(i, b.dataset.st);
  auditGoto(i);
});
$('btnAuditClear').onclick = () => { if (!audit.items.length || confirm('Effacer la liste des anomalies ?')) { audit = { ...audit, job: null, items: [], status: {} }; AU.sel = null; auditSave(); dirty = true; Audit.ui(); } };
