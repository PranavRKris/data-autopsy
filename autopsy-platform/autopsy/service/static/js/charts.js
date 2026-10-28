// Hand-written SVG charts: volume bars, line small multiples, stacked bar. Thin marks, hairline grid, shape + color for anomalies.
import { h, s, mount, fmtCompact, fmtNum, shortDay } from './ui.js';

// Render `draw(width)` into a box and redraw when the box is resized.
export function chartBox(draw, cls = '') {
  const box = h('div', { class: `chart ${cls}` });
  let width = 0;
  const paint = () => {
    const w = Math.floor(box.clientWidth);
    if (w < 200 || w === width) return;
    width = w;
    mount(box, draw(w));
  };
  new ResizeObserver(paint).observe(box);
  requestAnimationFrame(paint);
  return box;
}

export function niceMax(v) {
  if (!(v > 0)) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  const f = v / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pow;
}

// round axis: step 1/2/2.5/5 x 10^n so the ticks read as plain numbers
export function niceScale(v, parts = 4) {
  if (!(v > 0)) return { max: 1, ticks: [0, 0.5, 1] };
  const raw = v / parts, pow = 10 ** Math.floor(Math.log10(raw)), f = raw / pow;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pow;
  const n = Math.ceil(v / step - 1e-9);
  return { max: step * n, ticks: Array.from({ length: n + 1 }, (_, i) => +(step * i).toPrecision(12)) };
}

const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

function roving(nodes) {
  nodes.forEach((n, i) => n.setAttribute('tabindex', i === 0 ? '0' : '-1'));
  nodes.forEach((n, i) => n.addEventListener('keydown', (e) => {
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: nodes.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const t = nodes[Math.max(0, Math.min(nodes.length - 1, next))];
    nodes.forEach((x) => x.setAttribute('tabindex', x === t ? '0' : '-1'));
    t.focus();
  }));
}

function frame(width, height, m) {
  const svg = s('svg', { viewBox: `0 0 ${width} ${height}`, width, height, class: 'chart-svg', role: 'img' });
  return { svg, iw: width - m.l - m.r, ih: height - m.t - m.b };
}

function yAxis(svg, y, ticks, m, iw, fmt) {
  for (const t of ticks) {
    svg.appendChild(s('line', { x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t), class: t === 0 ? 'ax-base' : 'ax-grid' }));
    svg.appendChild(s('text', { x: m.l - 8, y: y(t) + 4, class: 'ax-text', 'text-anchor': 'end' }, fmt(t)));
  }
}

function xLabels(svg, days, xc, m, ih, iw, today) {
  const step = Math.max(1, Math.ceil(days.length / Math.max(2, Math.floor(iw / 64))));
  days.forEach((d, i) => {
    if ((days.length - 1 - i) % step !== 0) return;
    svg.appendChild(s('text', { x: xc(i), y: m.t + ih + 18, class: 'ax-text', 'text-anchor': 'middle' }, d === today ? 'today' : shortDay(d)));
  });
}

/* ---- daily volume ---- */
export function volumeChart({ days, values, today, band, height = 240 }) {
  return chartBox((width) => {
    const m = { l: 46, r: 10, t: 14, b: 26 };
    const { svg, iw, ih } = frame(width, height, m);
    const { max, ticks } = niceScale(Math.max(1, ...values, band ? band.max : 0) * 1.04);
    const y = lin(0, max, m.t + ih, m.t);
    const n = days.length, slot = iw / n, bw = Math.max(3, Math.min(30, slot * 0.66));
    const xc = (i) => m.l + slot * (i + 0.5);
    svg.appendChild(s('defs', s('pattern', { id: 'hatch', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
      s('rect', { width: 6, height: 6, fill: 'var(--surface)' }), s('rect', { width: 2.4, height: 6, fill: 'var(--series)' }))));
    yAxis(svg, y, ticks, m, iw, fmtCompact);
    if (band) {
      svg.appendChild(s('rect', { x: m.l, y: y(band.max), width: iw, height: Math.max(1, y(band.min) - y(band.max)), class: 'band' }));
      svg.appendChild(s('line', { x1: m.l, x2: m.l + iw, y1: y(band.median), y2: y(band.median), class: 'ref-line' }));
    }
    const hits = [];
    days.forEach((d, i) => {
      const v = values[i], isToday = d === today;
      const out = band && !isToday ? (v > band.max ? 'above' : v < band.min ? 'below' : null) : null;
      const top = y(v), x = xc(i) - bw / 2, r = Math.min(4, bw / 2, Math.max(0, ih - (top - m.t)));
      if (v > 0) {
        svg.appendChild(s('path', {
          d: `M${x},${m.t + ih} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${m.t + ih} Z`,
          fill: isToday ? 'url(#hatch)' : out ? 'var(--fail)' : 'var(--series)', stroke: isToday ? 'var(--series)' : 'none', 'stroke-width': 1,
        }));
      }
      if (out || (v === 0 && !isToday)) {
        const my = v > 0 ? top - 11 : m.t + ih - 14, down = out === 'below' || v === 0;
        svg.appendChild(s('path', { d: down ? `M${xc(i) - 6},${my - 5} h12 l-6,11 z` : `M${xc(i) - 6},${my + 6} h12 l-6,-11 z`, fill: 'var(--fail)', stroke: 'var(--surface)', 'stroke-width': 1.5 }));
      }
      const note = isToday ? 'Today, still filling (not compared)' : out === 'above' ? 'Above the baseline range' : out === 'below' ? 'Below the baseline range' : v === 0 ? 'No rows' : '';
      const hit = s('rect', { x: m.l + slot * i, y: m.t, width: slot, height: ih + 6, class: 'hit', 'data-tip': `${shortDay(d)}\n${fmtNum(v)} rows${note ? `\n${note}` : ''}${band && !isToday ? `\nBaseline ${fmtNum(band.min)} to ${fmtNum(band.max)}, median ${fmtNum(band.median)}` : ''}`,
        'aria-label': `${shortDay(d)}: ${fmtNum(v)} rows. ${note}` });
      hits.push(hit);
    });
    xLabels(svg, days, xc, m, ih, iw, today);
    hits.forEach((x) => svg.appendChild(x));
    roving(hits);
    return svg;
  });
}

/* ---- one small-multiple line ---- */
export function lineChart({ days, values, today, band, ref, fmt = fmtCompact, tipFmt = fmt, flag, height = 130, floor = 0, label = '', minTop = 0 }) {
  return chartBox((width) => {
    const m = { l: 46, r: 10, t: 10, b: 22 };
    const { svg, iw, ih } = frame(width, height, m);
    const present = values.filter((v) => v !== null && v !== undefined);
    const hi = Math.max(...present, band ? band[1] : -Infinity, ref ?? -Infinity, floor + 1e-9);
    const lo = Math.min(...present, band ? band[0] : Infinity, floor === null ? Infinity : floor);
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.12;
    const sc = floor === 0 ? niceScale(Math.max(hi * 1.1, minTop), 2) : null;
    const top = sc ? sc.max : hi + pad, bottom = sc ? 0 : lo - pad;
    const y = lin(bottom, top, m.t + ih, m.t);
    const slot = iw / days.length, xc = (i) => m.l + slot * (i + 0.5);
    yAxis(svg, y, sc ? sc.ticks : [0, 1, 2].map((k) => bottom + ((top - bottom) * k) / 2), m, iw, fmt);
    if (band) svg.appendChild(s('rect', { x: m.l, y: y(band[1]), width: iw, height: Math.max(1, y(band[0]) - y(band[1])), class: 'band' }));
    if (ref !== undefined && ref !== null) svg.appendChild(s('line', { x1: m.l, x2: m.l + iw, y1: y(ref), y2: y(ref), class: 'ref-line' }));
    // gaps (days without rows) are shaded so a missing day never looks like a zero
    values.forEach((v, i) => { if (v === null || v === undefined) svg.appendChild(s('rect', { x: m.l + slot * i, y: m.t, width: slot, height: ih, class: 'gap' })); });
    let seg = [];
    const flush = () => {
      if (seg.length > 1) svg.appendChild(s('path', { d: seg.map(([i, v], k) => `${k ? 'L' : 'M'}${xc(i)},${y(v)}`).join(' '), class: 'line' }));
      seg = [];
    };
    values.forEach((v, i) => { if (v === null || v === undefined) flush(); else seg.push([i, v]); });
    flush();
    const hits = [];
    values.forEach((v, i) => {
      const bad = v !== null && v !== undefined && flag && flag(v, i);
      const isLast = i === values.length - 1 || (i === values.length - 2 && days[values.length - 1] === today);
      if (v !== null && v !== undefined && (bad || (isLast && !bad) || seg.length === 0 && values.filter((x) => x !== null).length === 1)) {
        svg.appendChild(bad
          ? s('path', { d: `M${xc(i)},${y(v) - 7} l7,7 l-7,7 l-7,-7 z`, fill: 'var(--fail)', stroke: 'var(--surface)', 'stroke-width': 1.5 })
          : s('circle', { cx: xc(i), cy: y(v), r: 4, class: 'dot-mark' }));
      }
      const noteText = v === null || v === undefined ? 'No rows that day' : bad ? 'Outside the baseline' : '';
      hits.push(s('rect', { x: m.l + slot * i, y: m.t, width: slot, height: ih, class: 'hit',
        'data-tip': `${shortDay(days[i])}\n${v === null || v === undefined ? 'no data' : `${label}${tipFmt(v)}`}${noteText ? `\n${noteText}` : ''}`,
        'aria-label': `${shortDay(days[i])}: ${v === null || v === undefined ? 'no data' : tipFmt(v)}. ${noteText}` }));
    });
    xLabels(svg, days, xc, m, ih, iw, today);
    hits.forEach((x) => svg.appendChild(x));
    roving(hits);
    return svg;
  }, 'chart-sm');
}

/* ---- stacked proportion bar (run counts) ---- */
export function stackedBar(parts, total) {
  const sum = total || parts.reduce((a, p) => a + p.value, 0);
  if (!sum) return h('div', { class: 'stack-bar empty-bar', 'aria-hidden': 'true' });
  return h('div', { class: 'stack-bar', role: 'img', 'aria-label': parts.filter((p) => p.value).map((p) => `${p.value} ${p.label}`).join(', ') },
    parts.filter((p) => p.value).map((p) => h('span', { style: { flexGrow: p.value, background: p.color }, 'data-tip': `${p.value} ${p.label}` })));
}
