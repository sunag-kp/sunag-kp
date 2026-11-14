/* Scroll scene engine. No dependencies, no scroll hijacking.
   [data-scene]            tall section with a sticky .stage; gets --p (0..1)
   [data-at="a,b"]         child gets --t: eased 0..1 while scene progress runs a..b
   [data-out="a,b"]        child gets --o: 1..0 while scene progress runs a..b
   [data-pan]              child is translated left by its overflow width, over data-at range
   Only custom properties and transforms are written; layout is never touched per frame. */
(() => {
  const root = document.documentElement;
  if (!root.classList.contains('motion')) return;

  const clamp = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
  const EASE = {
    linear: (t) => t,
    in: (t) => t * t * t,
    out: (t) => 1 - Math.pow(1 - t, 3),
    inout: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  };
  const range = (s) => s.split(',').map(Number);

  const scenes = [...document.querySelectorAll('[data-scene]')].map((el) => ({
    el,
    label: el.dataset.label || '',
    p: null,
    target: 0,
    top: 0,
    span: 1,
    height: 0,
    parts: [...el.querySelectorAll('[data-at],[data-out]')].map((n) => ({
      n,
      at: n.dataset.at ? range(n.dataset.at) : null,
      out: n.dataset.out ? range(n.dataset.out) : null,
      ease: EASE[n.dataset.ease || 'inout'],
      pan: n.hasAttribute('data-pan'),
      panDist: 0,
      t: -1,
      o: -1,
    })),
  }));

  const hudLabel = document.querySelector('[data-hud-label]');
  const hudIndex = document.querySelector('[data-hud-index]');
  const hudTime = document.querySelector('[data-hud-time]');
  const totalEl = document.querySelector('[data-total]');
  const RUNTIME_FRAMES = Number(root.dataset.runtime || 240) * 24;
  let vh = innerHeight;
  let docSpan = 1;
  let current = -1;
  let scrolled = false;

  function measure() {
    vh = innerHeight;
    root.style.setProperty('--line', String(3 / innerWidth));
    for (const s of scenes) {
      const r = s.el.getBoundingClientRect();
      s.top = r.top + scrollY;
      s.height = r.height;
      s.span = Math.max(1, r.height - vh);
      for (const part of s.parts) {
        if (part.pan) part.panDist = Math.max(0, part.n.scrollWidth - part.n.parentElement.clientWidth);
      }
      s.p = null;
    }
    docSpan = Math.max(1, root.scrollHeight - vh);
    request();
  }

  function write(s) {
    s.el.style.setProperty('--p', clamp(s.p).toFixed(4));
    for (const part of s.parts) {
      if (part.at) {
        const t = part.ease(clamp((s.p - part.at[0]) / (part.at[1] - part.at[0])));
        const r = Math.round(t * 2000) / 2000;
        if (r !== part.t) {
          part.t = r;
          part.n.style.setProperty('--t', r);
          if (part.pan) part.n.style.transform = `translate3d(${(-part.panDist * r).toFixed(1)}px,0,0)`;
        }
      }
      if (part.out) {
        const o = 1 - EASE.in(clamp((s.p - part.out[0]) / (part.out[1] - part.out[0])));
        const r = Math.round(o * 2000) / 2000;
        if (r !== part.o) {
          part.o = r;
          part.n.style.setProperty('--o', r);
        }
      }
    }
  }

  let raf = 0;
  function frame() {
    raf = 0;
    const y = scrollY;
    let unsettled = false;
    let active = current;
    for (let i = 0; i < scenes.length; i++) {
      const s = scenes[i];
      // progress may run negative while the stage is still scrolling in, so a scene
      // can start its entrance before it pins (no dead frames between scenes)
      const raw = (y - s.top) / s.span;
      s.target = raw > 1 ? 1 : raw < -vh / s.span ? -vh / s.span : raw;
      if (y + vh * 0.5 >= s.top) active = i;
      const near = y > s.top - vh * 1.5 && y < s.top + s.height + vh * 0.5;
      if (s.p === null || !near) {
        if (s.p !== s.target) { s.p = s.target; write(s); }
        continue;
      }
      const d = s.target - s.p;
      if (Math.abs(d) < 0.0004) {
        if (d !== 0) { s.p = s.target; write(s); }
      } else {
        s.p += d * 0.16;
        write(s);
        unsettled = true;
      }
    }
    if (active !== current && active >= 0) {
      current = active;
      if (hudLabel) hudLabel.innerHTML = scenes[active].el.dataset.label || '';
      if (hudIndex) hudIndex.textContent = String(active + 1).padStart(2, '0');
    }
    const sc = y > 24;
    if (sc !== scrolled) { scrolled = sc; root.classList.toggle('scrolled', sc); }
    if (totalEl) totalEl.style.transform = `scaleX(${clamp(y / docSpan).toFixed(4)})`;
    if (hudTime) {
      const f = Math.round(clamp(y / docSpan) * RUNTIME_FRAMES);
      const pad = (n) => String(n).padStart(2, '0');
      hudTime.textContent = `${pad(Math.floor(f / 86400))}:${pad(Math.floor(f / 1440) % 60)}:${pad(Math.floor(f / 24) % 60)}:${pad(f % 24)}`;
    }
    if (unsettled) request();
  }
  function request() { if (!raf) raf = requestAnimationFrame(frame); }

  addEventListener('scroll', request, { passive: true });
  addEventListener('resize', measure, { passive: true });
  addEventListener('load', measure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
  measure();
  requestAnimationFrame(() => root.classList.add('ready'));
})();
