/* Mode « Baguette magique » (preuve de concept). Clic sur la carte = sonde : remplissage flou depuis ce point
   (serveur : /api/wand → tools/magic_wand.py), sélection colorée en surimpression, centre suggéré, courbe aire(tolérance).
   Entrée lance le modèle depuis le point sondé, N le fait avancer d'un pas (auto.js : startTrace(step) / stepTrace) ; la
   baguette suit alors le point courant du modèle. Rien n'est enregistré ni transmis au modèle. */
const Wand = {
  target: null, res: null, sweep: null, sweepKey: null, proposed: null, jump: null, mask: null, tinted: null, tintKey: '',
  tol: +(localStorage.getItem('mt-wand-tol') || 32), auto: localStorage.getItem('mt-wand-auto') !== '0',
  busy: false, queued: null, timer: null, error: null,
  radius() { return +$('wandRadius').value || 192; },
  alpha() { return (+$('wandAlpha').value || 60) / 100; },
  color() { return $('wandColor').value || '0,200,255'; },
  stepping() { return auto.job && auto.job.status === 'running' && auto.job.step; },
  init() {
    $('wandTol').value = this.tol; $('wandTolVal').textContent = this.tol; $('wandAuto').checked = this.auto;
    $('wandTol').addEventListener('input', () => { this.setTol(+$('wandTol').value, true, true); });
    $('wandAuto').addEventListener('change', () => { this.auto = $('wandAuto').checked; localStorage.setItem('mt-wand-auto', this.auto ? '1' : '0'); if (this.auto && this.proposed != null) this.setTol(this.proposed); this.ui(); });
    $('wandRadius').addEventListener('change', () => { this.sweepKey = null; this.request(true); });
    $('wandAlpha').addEventListener('input', () => { dirty = true; });
    $('wandColor').addEventListener('change', () => { dirty = true; });
    $('btnWandStart').onclick = () => this.start();
    $('btnWandStop').onclick = () => stopTrace();
    $('btnStepNext').onclick = () => stepTrace(Math.max(1, +$('stepN').value || 1));
    $('btnStepRun').onclick = () => stepTrace(0);
    this.ui();
  },
  setTol(t, debounce = false, manual = false) {
    this.tol = Math.max(0, Math.min(128, Math.round(t)));
    if (manual && this.auto) { this.auto = false; $('wandAuto').checked = false; localStorage.setItem('mt-wand-auto', '0'); }
    $('wandTol').value = this.tol; $('wandTolVal').textContent = this.tol; localStorage.setItem('mt-wand-tol', this.tol);
    clearTimeout(this.timer);
    if (debounce) this.timer = setTimeout(() => this.request(false), 120); else this.request(false);
    dirty = true; this.ui();
  },
  at(x, y, src) {
    x = Math.round(x); y = Math.round(y);
    if (this.target && this.target.x === x && this.target.y === y) return;
    this.target = { x, y, src }; this.request(true); dirty = true; this.ui();
  },
  clear() { this.target = null; this.res = null; this.mask = null; this.tinted = null; this.sweep = null; this.sweepKey = null; this.proposed = null; this.jump = null; dirty = true; this.ui(); },
  start() {
    if (!this.target) return warn('Cliquez d’abord un point sur une galerie.');
    if (this.stepping()) return warn('Un pas à pas est déjà en cours (« Arrêter le modèle » d’abord).');
    startTrace(this.target.x, this.target.y, true);
  },
  click(e, mx, my) {
    if (e.button !== 0) return;
    if (!img) return warn('Chargez une carte (liste).');
    this.at(mx, my, 'clic');
  },
  key(e) {
    const k = e.key.toLowerCase();
    if (e.ctrlKey || e.metaKey) return false;
    if (k === 'n') { stepTrace(Math.max(1, +$('stepN').value || 1)); return true; }
    if (k === 'enter') { e.preventDefault(); this.start(); return true; }
    if (k === '[' || k === ']') { this.setTol(this.tol + (k === '[' ? -4 : 4), false, true); return true; }
    if (k === 'escape') { this.clear(); return true; }
    if (k === 'c') { if (this.target) { view.cx = this.target.x; view.cy = this.target.y; view.s = Math.max(view.s, 3); dirty = true; } return true; }
    return [' ', 'a', 't', 'f', 'i'].includes(k);
  },
  async request(sweep) {
    if (!this.target || !img) return;
    const url = mapUrl(); if (!url) { this.error = 'Carte locale : le serveur ne la connaît pas (choisissez-la dans la liste).'; this.ui(); return; }
    if (this.busy) { this.queued = this.queued || sweep; return; }
    this.busy = true; this.ui();
    const { x, y } = this.target, radius = this.radius(), key = `${x},${y},${radius}`;
    sweep = sweep || key !== this.sweepKey;
    try {
      const r = await fetch('../api/wand', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ map: url, x, y, tol: this.tol, radius, sweep }) });
      const res = await r.json();
      if (!r.ok) this.error = res.error || String(r.status);
      else {
        this.error = null;
        if (res.sweep) { this.sweep = res.sweep; this.proposed = res.proposed; this.jump = res.jump; this.sweepKey = key; }
        if (sweep && this.auto && res.proposed != null && res.proposed !== this.tol) {   // tolérance automatique : on recalcule au cran proposé
          this.tol = res.proposed; $('wandTol').value = this.tol; $('wandTolVal').textContent = this.tol; localStorage.setItem('mt-wand-tol', this.tol);
          this.queued = false;
        } else {
          this.res = res;
          if (res.mask) { const im = new Image(); im.onload = () => { this.mask = im; this.tinted = null; dirty = true; }; im.src = res.mask; }
          else { this.mask = null; this.tinted = null; }
        }
      }
    } catch (e) { this.error = e.message; }
    finally {
      this.busy = false; dirty = true; this.ui();
      if (this.queued != null) { const q = this.queued; this.queued = null; this.request(q); }
    }
  },
  /* masque recoloré (le PNG du serveur est cyan opaque ; on teinte via un canvas hors écran) */
  tint() {
    const key = this.color();
    if (this.tinted && this.tintKey === key) return this.tinted;
    const c = document.createElement('canvas'); c.width = this.mask.width; c.height = this.mask.height;
    const g = c.getContext('2d'); g.drawImage(this.mask, 0, 0);
    g.globalCompositeOperation = 'source-in'; g.fillStyle = `rgb(${key})`; g.fillRect(0, 0, c.width, c.height);
    this.tinted = c; this.tintKey = key; return c;
  },
  draw() {
    const res = this.res, t = this.target;
    if (!t) return;
    if (res && res.origin) {
      const [ox, oy] = res.origin, [w, h] = res.size;
      const [sx, sy] = toScreen(ox, oy), [ex, ey] = toScreen(ox + w, oy + h);
      ctx.setLineDash([4, 6]); ctx.strokeStyle = 'rgba(255,255,255,.25)'; ctx.lineWidth = 1; ctx.strokeRect(sx, sy, ex - sx, ey - sy); ctx.setLineDash([]);
      if (this.mask && res.tol === this.tol) {
        const im = this.tint();
        ctx.imageSmoothingEnabled = false;
        ctx.globalAlpha = Math.min(1, this.alpha() + 0.3);          // liseré : le masque décalé d'un pixel écran dans 4 directions
        for (const [dx, dy] of [[-1.5, 0], [1.5, 0], [0, -1.5], [0, 1.5]]) ctx.drawImage(im, sx + dx, sy + dy, ex - sx, ey - sy);
        ctx.globalAlpha = this.alpha();
        ctx.drawImage(im, sx, sy, ex - sx, ey - sy);
        ctx.globalAlpha = 1;
      }
      const st = res.stats || {};
      if (st.center) {
        const [cx, cy] = toScreen(st.center[0] + 0.5, st.center[1] + 0.5);
        ctx.strokeStyle = 'rgba(255,209,102,.9)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(cx, cy, Math.max(2, st.center[2] * view.s), 0, 7); ctx.stroke();
        ctx.fillStyle = '#ffd166'; ctx.beginPath(); ctx.arc(cx, cy, 4, 0, 7); ctx.fill();
        const [tx, ty] = toScreen(t.x + 0.5, t.y + 0.5);
        ctx.strokeStyle = '#ffd166'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(cx, cy); ctx.stroke();
      }
    }
    const [tx, ty] = toScreen(t.x + 0.5, t.y + 0.5);
    ctx.strokeStyle = '#000'; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(tx - 8, ty); ctx.lineTo(tx + 8, ty); ctx.moveTo(tx, ty - 8); ctx.lineTo(tx, ty + 8); ctx.stroke();
    ctx.strokeStyle = `rgb(${this.color()})`; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(tx - 8, ty); ctx.lineTo(tx + 8, ty); ctx.moveTo(tx, ty - 8); ctx.lineTo(tx, ty + 8); ctx.stroke();
  },
  /* rose des 32 directions au point courant du modèle (secteur i = cap + i·2π/K) */
  drawCursor(c, thr = 0.5) {
    if (!c || !c.probs) return;
    const K = c.probs.length, [x, y] = toScreen(c.x, c.y), R0 = 10, R1 = 42;
    for (let i = 0; i < K; i++) {
      const p = c.probs[i], a = c.heading + i * 2 * Math.PI / K, r = R0 + (R1 - R0) * p;
      ctx.strokeStyle = p >= thr ? 'rgba(57,196,124,.95)' : `rgba(255,255,255,${0.15 + 0.5 * p})`; ctx.lineWidth = p >= thr ? 3 : 1.5;
      ctx.beginPath(); ctx.moveTo(x + R0 * Math.cos(a), y + R0 * Math.sin(a)); ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a)); ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, R0, 0, 7); ctx.stroke();
    ctx.fillStyle = '#ff4d4d'; ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.fill();
    ctx.strokeStyle = '#ff4d4d'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + R0 * Math.cos(c.heading), y + R0 * Math.sin(c.heading)); ctx.stroke();
  },
  curve() {
    const cv = $('wandCurve'); if (!cv) return;
    const g = cv.getContext('2d'), Wc = cv.width, Hc = cv.height;
    g.clearRect(0, 0, Wc, Hc);
    g.fillStyle = '#8d97a5'; g.font = '10px system-ui, sans-serif'; g.textBaseline = 'top';
    const sw = this.sweep;
    if (!sw || !sw.length) { g.fillText('Courbe aire(tolérance) : cliquez un point.', 8, 4); return; }
    const X = t => 8 + (Wc - 16) * t / 128;
    const maxA = Math.max(...sw.map(r => r.area), 1), maxW = Math.max(...sw.map(r => r.width), 1);
    const YA = a => Hc - 16 - (Hc - 30) * Math.log10(a + 1) / Math.log10(maxA + 1);
    const YW = w => Hc - 16 - (Hc - 30) * w / maxW;
    g.strokeStyle = 'rgba(255,255,255,.08)'; g.lineWidth = 1;
    for (const t of [32, 64, 96]) { g.beginPath(); g.moveTo(X(t), 14); g.lineTo(X(t), Hc - 16); g.stroke(); g.fillText(String(t), X(t) - 6, Hc - 12); }
    g.fillText('0', X(0), Hc - 12); g.fillText('128', X(128) - 16, Hc - 12);
    g.strokeStyle = 'rgba(255,209,102,.8)'; g.setLineDash([2, 3]); g.beginPath();
    sw.forEach((r, i) => { const x = X(r.tol), y = YW(r.width); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.setLineDash([]);
    g.strokeStyle = `rgb(${this.color()})`; g.lineWidth = 2; g.beginPath();
    sw.forEach((r, i) => { const x = X(r.tol), y = YA(r.area); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
    for (const r of sw) if (r.border) { g.fillStyle = '#ff4d4d'; g.beginPath(); g.arc(X(r.tol), YA(r.area), 2.5, 0, 7); g.fill(); }
    if (this.jump != null) { g.strokeStyle = 'rgba(255,77,77,.8)'; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(X(this.jump), 14); g.lineTo(X(this.jump), Hc - 16); g.stroke(); g.setLineDash([]); }
    g.strokeStyle = '#fff'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(X(this.tol), 14); g.lineTo(X(this.tol), Hc - 16); g.stroke();
    g.fillStyle = '#8d97a5';
    g.fillText(`aire sélectionnée (log, max ${maxA} px²) · pointillé jaune : largeur (max ${maxW} px) · rouge : touche le bord · blanc : tolérance courante`, 8, 2);
  },
  verdict(st) {
    if (!st || !st.area) return ['warn', 'Rien de sélectionné : le point est sur un trait, ou la tolérance est trop basse (montez-la, ou cliquez bien dans le blanc).'];
    if (st.area < 150) return ['warn', `Sélection minuscule (${st.area} px²) : tolérance trop basse pour le JPEG, ou point coincé entre deux traits — montez la tolérance.`];
    if (st.width < 6) return ['ok', `Galerie fine : vide de ≈ ${st.width} px de large, très allongée (×${st.elong}).${st.border ? ' La sélection file jusqu’au bord du rayon : elle suit la galerie.' : ''}`];
    if (st.width < 25 && st.elong >= 2) return ['ok', `Ressemble à une galerie : ≈ ${st.width} px de large, allongée ×${st.elong}${st.border ? ', jusqu’au bord du rayon' : ''}.`];
    if (st.border && st.fill > 0.5) return ['warn', `Débordement probable : ≈ ${st.width} px de large, rectangle rempli à ${Math.round(st.fill * 100)} %, jusqu’au bord du rayon — le fond est inondé, baissez la tolérance.`];
    return ['info', `Salle ou zone large : ≈ ${st.width} px de large, peu allongée (×${st.elong})${st.n_components_holes ? `, ${st.n_components_holes} trou(s) (piliers, textes)` : ''}.`];
  },
  ui() {
    const el = $('wandInfo'); if (!el) return;
    const t = this.target, res = this.res, j = auto.job, stepping = this.stepping();
    const guide = $('wandGuide');
    if (!img) guide.innerHTML = '<b>Chargez une carte</b> dans la liste en haut.';
    else if (!t) guide.innerHTML = '<b>① Cliquez dans le blanc d’une galerie.</b> La baguette colore tout le vide relié à ce point. Zoomez (molette) sur les galeries fines.';
    else if (!stepping) guide.innerHTML = '<b>② Regardez la sélection colorée</b> et jouez avec la tolérance (curseur, <kbd>[</kbd> <kbd>]</kbd>) : où déborde-t-elle ? Cliquez ailleurs pour sonder un autre point.<br><b>③ <kbd>Entrée</kbd></b> lance le modèle depuis ce point, puis <kbd>N</kbd> = un pas.';
    else guide.innerHTML = j.paused ? '<b>Le modèle est au point rouge.</b> <kbd>N</kbd> ou « Pas suivant » = un pas de plus ; la baguette suit. La rose montre ses directions (vert = retenue). Cliquez ailleurs pour sonder sans bouger le modèle.' : '<b>Le modèle calcule…</b>';
    $('wandProposed').textContent = this.proposed != null ? `proposée : ${this.proposed}` : '';
    $('btnWandStart').disabled = !t || stepping; $('btnWandStop').disabled = !stepping;
    $('btnStepNext').disabled = !(stepping && j.paused); $('btnStepRun').disabled = !(stepping && j.paused);
    this.curve();
    const v = $('wandVerdict');
    if (!t) { v.textContent = ''; v.className = 'verdict'; }
    else if (this.error) { v.textContent = 'Erreur : ' + this.error; v.className = 'verdict warn'; }
    else if (this.busy && !res) { v.textContent = 'Calcul…'; v.className = 'verdict'; }
    else if (res) { const [cls, txt] = this.verdict(res.stats); v.innerHTML = `<b>Lecture (heuristique)</b> — ${txt}`; v.className = 'verdict ' + cls; }
    let s = '';
    if (t) {
      s = `Point <b>${t.x}, ${t.y}</b> (${t.src})${this.busy ? ' · calcul…' : ''}`;
      if (res && res.stats) {
        const st = res.stats, dx = st.center ? st.center[0] - t.x : 0, dy = st.center ? st.center[1] - t.y : 0;
        if (st.area) s += `<br>Tolérance ${res.tol} : aire <b>${st.area}</b> px² · rectangle ${st.bbox[2] - st.bbox[0]}×${st.bbox[3] - st.bbox[1]} px (rempli ${Math.round(st.fill * 100)} %) · largeur ≈ <b>${st.width}</b> px · allongement ×${st.elong}${st.border ? ' · <b>touche le bord du rayon</b>' : ''}${st.n_components_holes ? ` · ${st.n_components_holes} trou(s)` : ''}` +
          `<br>Au point : mur le plus proche à ${st.half_width_at_seed} px ; centre suggéré (jaune) à ${Math.round(Math.hypot(dx, dy))} px (${dx >= 0 ? '+' : ''}${dx}, ${dy >= 0 ? '+' : ''}${dy}), rayon libre ${st.center ? st.center[2] : '?'} px.`;
        s += `<br>Couleur de référence ${res.ref.join(',')}` + (res.seed_px.join() !== res.ref.join() ? ` (pixel cliqué ${res.seed_px.join(',')} : sur un trait, ton clair du voisinage pris)` : '') +
          (res.seed_used && (res.seed_used[0] !== t.x || res.seed_used[1] !== t.y) ? ` · départ déplacé en ${res.seed_used.join(', ')}` : '');
        if (this.sweep) s += `<br>Balayage 0…128 : ${this.jump != null ? `bond d'aire entre ${this.proposed} et ${this.jump}` : 'aucun bond net'} (heuristique : ×2,5 d'un cran au suivant).`;
      }
    }
    el.innerHTML = s;
    if (stepping && j.cursor) {
      const c = j.cursor, K = c.probs.length, thr = 0.5;
      const top = c.probs.map((p, i) => [p, i]).filter(([p]) => p >= 0.1).sort((a, b) => b[0] - a[0]).slice(0, 5)
        .map(([p, i]) => { const d = (i * 360 / K + 180) % 360 - 180; return `${d > 0 ? '+' : ''}${Math.round(d)}° ${Math.round(p * 100)} %`; });
      $('stepInfo').innerHTML = `Modèle <b>${j.model || ''}</b> au point <b>${Math.round(c.x)}, ${Math.round(c.y)}</b>, cap ${Math.round((c.heading * 180 / Math.PI + 360) % 360)}° · ${j.steps} pas, ${j.branches} branche(s) finie(s), ${j.queue} en file.<br>Directions vues (relatives au cap, seuil ${thr}) : ${top.length ? top.join(' · ') : 'aucune (fin probable)'}.`;
    } else $('stepInfo').innerHTML = stepping ? 'Calcul du premier pas…' : (j && j.step && j.status !== 'running' ? `Dernier pas à pas : ${j.status === 'done' ? 'terminé' : j.status === 'stopped' ? 'arrêté' : j.status} après ${j.steps} pas${j.error ? ' — ' + j.error : ''}${j.reasons && j.reasons.low_confidence ? ' — <b>fin par manque de confiance</b> : le modèle ne voit aucune direction nette ici (point mal placé, galerie atypique, ou cap de départ mal deviné) ; essayez un autre point ou un autre modèle' : ''}. Le tracé rouge reste affiché (« Effacer le tracé » dans le mode Auto).` : 'Aucun modèle lancé : cliquez un point puis <kbd>Entrée</kbd>.');
    $('stats').innerHTML = `<span>Tracé du modèle <b>${auto.graph.nodes.length}</b> pts</span><span>Tolérance <b>${this.tol}</b></span>`;
    $('status').textContent = !img ? 'Chargez une carte (liste).' : !t ? 'Mode Baguette : cliquez dans le blanc d’une galerie.' : stepping ? (j.paused ? 'N = pas suivant · [ ] tolérance · Échap efface la sonde · C recentre' : 'Le modèle calcule…') : 'Entrée = lancer le modèle ici · [ ] tolérance · clic ailleurs = autre sonde · C recentre';
    $('hud').textContent = t ? `baguette ${t.x},${t.y} · tol ${this.tol}${res && res.stats ? ` · ${res.stats.area} px²` : ''}` : '';
  },
};
