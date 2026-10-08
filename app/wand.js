/* Baguette magique (preuve de concept) : remplissage flou depuis un point (serveur : /api/wand → tools/wand.py), sélection en
   surimpression, centre suggéré, courbe aire(tolérance). Le point suivi est le point courant du pas à pas, le point d'annotation
   sélectionné, ou un point sondé (W). Rien n'est enregistré. */
const Wand = {
  target: null, res: null, sweep: null, sweepKey: null, proposed: null, jump: null, mask: null,
  tol: +(localStorage.getItem('mt-wand-tol') || 32), busy: false, queued: null, timer: null, error: null,
  follow() { return $('wandFollow').checked; },
  radius() { return +$('wandRadius').value || 192; },
  init() {
    $('wandTol').value = this.tol; $('wandTolVal').textContent = this.tol;
    $('wandTol').addEventListener('input', () => { this.setTol(+$('wandTol').value, true); });
    $('wandRadius').addEventListener('change', () => { this.sweepKey = null; this.request(true); });
    $('btnWandProposed').onclick = () => { if (this.proposed != null) this.setTol(this.proposed); };
    $('wandFollow').addEventListener('change', () => { if (typeof Auto !== 'undefined') Auto.ui(); });
    this.ui();
  },
  setTol(t, debounce = false) {
    this.tol = Math.max(0, Math.min(128, Math.round(t)));
    $('wandTol').value = this.tol; $('wandTolVal').textContent = this.tol; localStorage.setItem('mt-wand-tol', this.tol);
    clearTimeout(this.timer);
    if (debounce) this.timer = setTimeout(() => this.request(false), 120); else this.request(false);
    this.curve();
  },
  nudge(d) { this.setTol(this.tol + d); },
  at(x, y, src) {
    x = Math.round(x); y = Math.round(y);
    if (this.target && this.target.x === x && this.target.y === y) return;
    this.target = { x, y, src }; this.request(true);
  },
  clear() { this.target = null; this.res = null; this.mask = null; this.sweep = null; this.sweepKey = null; dirty = true; this.ui(); },
  async request(sweep) {
    if (!this.target || !img) return;
    const url = mapUrl(); if (!url) return;
    if (this.busy) { this.queued = this.queued || sweep; return; }
    this.busy = true;
    const { x, y } = this.target, radius = this.radius(), key = `${x},${y},${radius}`;
    sweep = sweep || key !== this.sweepKey;
    try {
      const r = await fetch('../api/wand', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ map: url, x, y, tol: this.tol, radius, sweep }) });
      const res = await r.json();
      if (!r.ok) { this.error = res.error || r.status; }
      else {
        this.error = null; this.res = res;
        if (res.sweep) { this.sweep = res.sweep; this.proposed = res.proposed; this.jump = res.jump; this.sweepKey = key; }
        if (res.mask) { const im = new Image(); im.onload = () => { this.mask = im; dirty = true; }; im.src = res.mask; }
        else this.mask = null;
      }
      dirty = true; this.ui();
    } catch (e) { this.error = e.message; this.ui(); }
    finally { this.busy = false; if (this.queued != null) { const q = this.queued; this.queued = null; this.request(q); } }
  },
  /* surimpression sur la carte (appelée par Auto.draw avant le tracé) */
  draw() {
    const res = this.res, t = this.target;
    if (!t) return;
    if (res && res.origin) {
      const [ox, oy] = res.origin, [w, h] = res.size;
      const [sx, sy] = toScreen(ox, oy), [ex, ey] = toScreen(ox + w, oy + h);
      ctx.setLineDash([4, 6]); ctx.strokeStyle = 'rgba(0,200,255,.35)'; ctx.lineWidth = 1; ctx.strokeRect(sx, sy, ex - sx, ey - sy); ctx.setLineDash([]);
      if (this.mask && res.tol === this.tol) {
        ctx.globalAlpha = 0.45; ctx.imageSmoothingEnabled = false;
        ctx.drawImage(this.mask, sx, sy, ex - sx, ey - sy);
        ctx.globalAlpha = 1;
      }
      const st = res.stats || {};
      if (st.center) {
        const [cx, cy] = toScreen(st.center[0] + 0.5, st.center[1] + 0.5);
        ctx.strokeStyle = 'rgba(255,209,102,.8)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(cx, cy, Math.max(2, st.center[2] * view.s), 0, 7); ctx.stroke();
        ctx.fillStyle = '#ffd166'; ctx.beginPath(); ctx.arc(cx, cy, 4, 0, 7); ctx.fill();
        const [tx, ty] = toScreen(t.x + 0.5, t.y + 0.5);
        ctx.strokeStyle = '#ffd166'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(cx, cy); ctx.stroke();
      }
      if (res.seed_used && (res.seed_used[0] !== t.x || res.seed_used[1] !== t.y)) {
        const [ux, uy] = toScreen(res.seed_used[0] + 0.5, res.seed_used[1] + 0.5);
        ctx.strokeStyle = '#0cf'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(ux, uy, 4, 0, 7); ctx.stroke();
      }
    }
    const [tx, ty] = toScreen(t.x + 0.5, t.y + 0.5);
    ctx.strokeStyle = '#0cf'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(tx - 7, ty); ctx.lineTo(tx + 7, ty); ctx.moveTo(tx, ty - 7); ctx.lineTo(tx, ty + 7); ctx.stroke();
  },
  /* rose des 32 directions au point courant du pas à pas (secteur i = cap + i·2π/K) */
  drawCursor(c, thr = 0.5) {
    if (!c || !c.probs) return;
    const K = c.probs.length, [x, y] = toScreen(c.x, c.y);
    const R0 = 10, R1 = 42;
    for (let i = 0; i < K; i++) {
      const p = c.probs[i], a = c.heading + i * 2 * Math.PI / K;
      const r = R0 + (R1 - R0) * p;
      ctx.strokeStyle = p >= thr ? 'rgba(57,196,124,.95)' : `rgba(255,255,255,${0.15 + 0.5 * p})`; ctx.lineWidth = p >= thr ? 3 : 1.5;
      ctx.beginPath(); ctx.moveTo(x + R0 * Math.cos(a), y + R0 * Math.sin(a)); ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a)); ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, R0, 0, 7); ctx.stroke();
    ctx.strokeStyle = '#ff4d4d'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + R0 * Math.cos(c.heading), y + R0 * Math.sin(c.heading)); ctx.stroke();
  },
  /* courbe aire(tolérance) (échelle log) + largeur estimée */
  curve() {
    const cv = $('wandCurve'); if (!cv) return;
    const g = cv.getContext('2d'), Wc = cv.width, Hc = cv.height;
    g.clearRect(0, 0, Wc, Hc);
    const sw = this.sweep; if (!sw || !sw.length) return;
    const X = t => 8 + (Wc - 16) * t / 128;
    const maxA = Math.max(...sw.map(r => r.area), 1), maxW = Math.max(...sw.map(r => r.width), 1);
    const YA = a => Hc - 6 - (Hc - 12) * Math.log10(a + 1) / Math.log10(maxA + 1);
    const YW = w => Hc - 6 - (Hc - 12) * w / maxW;
    g.strokeStyle = 'rgba(255,255,255,.08)'; g.lineWidth = 1;
    for (const t of [32, 64, 96]) { g.beginPath(); g.moveTo(X(t), 0); g.lineTo(X(t), Hc); g.stroke(); }
    g.strokeStyle = 'rgba(255,209,102,.7)'; g.setLineDash([2, 3]); g.beginPath();
    sw.forEach((r, i) => { const x = X(r.tol), y = YW(r.width); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.setLineDash([]);
    g.strokeStyle = '#0cf'; g.lineWidth = 2; g.beginPath();
    sw.forEach((r, i) => { const x = X(r.tol), y = YA(r.area); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
    for (const r of sw) if (r.border) { g.fillStyle = '#ff4d4d'; g.beginPath(); g.arc(X(r.tol), YA(r.area), 2.5, 0, 7); g.fill(); }
    if (this.jump != null) { g.strokeStyle = 'rgba(255,77,77,.8)'; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(X(this.jump), 0); g.lineTo(X(this.jump), Hc); g.stroke(); g.setLineDash([]); }
    g.strokeStyle = '#fff'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(X(this.tol), 0); g.lineTo(X(this.tol), Hc); g.stroke();
    g.fillStyle = '#8d97a5'; g.font = '10px system-ui, sans-serif'; g.textBaseline = 'top';
    g.fillText(`aire max ${maxA} px² (bleu, log) · largeur max ${maxW} px (jaune) · rouge = touche le bord`, 8, 2);
  },
  ui() {
    const el = $('wandInfo'); if (!el) return;
    $('btnWandProposed').textContent = this.proposed != null ? `proposée : ${this.proposed}` : 'proposée';
    $('btnWandProposed').disabled = this.proposed == null;
    this.curve();
    if (!this.target) { el.innerHTML = 'Aucun point : lancez un départ pas à pas, sélectionnez un point d\u2019annotation, ou <b>W</b> puis cliquez sur la carte.'; return; }
    const t = this.target, res = this.res;
    let s = `Point <b>${t.x}, ${t.y}</b> (${t.src})${this.busy ? ' · calcul…' : ''}`;
    if (this.error) s += `<br><span class="warn">${this.error}</span>`;
    if (res && res.stats) {
      const st = res.stats, dx = st.center ? st.center[0] - t.x : 0, dy = st.center ? st.center[1] - t.y : 0;
      s += `<br>Tolérance ${res.tol} : ` + (st.area ? `aire <b>${st.area}</b> px² · rectangle ${st.bbox[2] - st.bbox[0]}×${st.bbox[3] - st.bbox[1]} px (rempli ${Math.round(st.fill * 100)} %) · largeur ≈ <b>${st.width}</b> px · allongement ${st.elong}` +
        (st.border ? ' · <b>touche le bord du rayon</b>' : '') + (st.n_components_holes ? ` · ${st.n_components_holes} trou(s)` : '') +
        `<br>Au point : mur le plus proche à ${st.half_width_at_seed} px ; centre suggéré à ${Math.round(Math.hypot(dx, dy))} px (${dx >= 0 ? '+' : ''}${dx}, ${dy >= 0 ? '+' : ''}${dy}), rayon libre ${st.center ? st.center[2] : '?'} px.` : 'rien de sélectionné (point sur un trait ? tolérance trop basse ?)');
      s += `<br>Couleur de référence ${res.ref.join(',')}` + (res.seed_px.join() !== res.ref.join() ? ` (pixel cliqué ${res.seed_px.join(',')})` : '') +
        (res.seed_used && (res.seed_used[0] !== t.x || res.seed_used[1] !== t.y) ? ` · départ déplacé en ${res.seed_used.join(', ')}` : '');
      if (this.sweep) s += `<br>Balayage : ${this.jump != null ? `bond d'aire entre ${this.proposed} et ${this.jump}` : 'aucun bond net jusqu\u2019à 128'} (heuristique : ×2,5 d'un cran à l'autre).`;
    }
    el.innerHTML = s;
  },
};
