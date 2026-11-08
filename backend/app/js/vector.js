/* Local, sanitized SVG assets. All animation derives solely from page time. */
(() => {
  const { Builder, h, clamp } = PV;
  /** P.vector(name, x, y, w, h, {at, dur}) → handle.hide(at, duration)
   * name is the uploaded filename including .svg; duration defaults to 2 seconds.
   * Strokes draw in document order, fills and text fade in. No external requests.
   */
  Builder.prototype.vector = function (name, x, y, w, height, o = {}) {
    const raw = (window.BTV_VECTORS || {})[name];
    if (!raw) throw new Error('SVG 素材不存在：' + name);
    const parsed = new DOMParser().parseFromString(raw, 'image/svg+xml');
    const svg = document.importNode(parsed.documentElement, true);
    const el = h('div', 'btv-vector', null, this.html);
    Object.assign(el.style, { position: 'absolute', left: x + 'px', top: y + 'px',
      width: w + 'px', height: height + 'px', overflow: 'hidden' });
    svg.setAttribute('width', '100%'); svg.setAttribute('height', '100%');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    el.appendChild(svg);
    const items = [...svg.querySelectorAll('path,rect,circle,ellipse,line,polyline,polygon,text')].map(n => {
      const css = getComputedStyle(n);
      let len = 0;
      try { len = n.getTotalLength(); } catch (_) { /* text fades */ }
      return { n, len: Number.isFinite(len) ? len : 0, stroke: css.stroke !== 'none',
        fill: Number.parseFloat(css.fillOpacity) || 0, opacity: Number.parseFloat(css.opacity) || 0 };
    });
    const at = Number.isFinite(o.at) ? o.at : 0;
    const dur = Number.isFinite(o.dur) ? Math.max(0.05, o.dur) : 2;
    let hideAt = Infinity, hideDur = 0.3;
    this.tick(t => {
      el.style.opacity = String(t < at ? 0 : 1 - clamp((t - hideAt) / hideDur));
      items.forEach((it, i) => {
        const k = clamp((t - at - dur * 0.35 * i / Math.max(1, items.length - 1)) / (dur * 0.65));
        if (it.stroke && it.len > 0) {
          it.n.style.strokeDasharray = `${it.len} ${it.len}`;
          it.n.style.strokeDashoffset = String(it.len * (1 - k));
          it.n.style.fillOpacity = String(it.fill * clamp((k - 0.5) * 2));
        } else {
          it.n.style.opacity = String(it.opacity * k);
        }
      });
    });
    return { el, svg, hide(t, duration = 0.3) {
      hideAt = t; hideDur = Math.max(0.01, duration); return this;
    } };
  };
})();
