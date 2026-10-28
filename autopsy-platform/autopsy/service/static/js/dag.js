// Layered left-to-right lineage graph. Used by the Lineage tab and as the live preview in the project wizard.
import { h, s, STATUS } from './ui.js';

const GLYPH_PATHS = {
  ok: ['<circle cx="8" cy="8" r="7" fill="var(--ok)"/><path d="m4.8 8.2 2.2 2.2 4.2-4.6" stroke="#fff" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'],
  warn: ['<path d="M8 1.6 15 14H1z" fill="var(--warn)" stroke="var(--warn)" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.2v3.4M8 11.7v.1" stroke="#0b0b0b" stroke-width="1.6" stroke-linecap="round"/>'],
  fail: ['<rect x="1.2" y="1.2" width="13.6" height="13.6" rx="3.6" fill="var(--fail)"/><path d="m5.4 5.4 5.2 5.2m0-5.2-5.2 5.2" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'],
  error: ['<path d="M8 .9 15.1 8 8 15.1.9 8z" fill="var(--error)" stroke="var(--error)" stroke-width="1" stroke-linejoin="round"/><path d="M8 4.9v3.6M8 10.7v.1" stroke="#0b0b0b" stroke-width="1.6" stroke-linecap="round"/>'],
  skipped: ['<circle cx="8" cy="8" r="6.3" fill="none" stroke="var(--skip)" stroke-width="1.4" stroke-dasharray="2.3 2"/><path d="M5.6 8h4.8" stroke="var(--skip)" stroke-width="1.6" stroke-linecap="round"/>'],
};

// level = longest path from a source; computed here when the caller does not have it
export function computeLevels(names, edges) {
  const level = Object.fromEntries(names.map((n) => [n, 0]));
  for (let pass = 0; pass < names.length; pass += 1) {
    for (const e of edges) if (level[e.to] < level[e.from] + 1) level[e.to] = level[e.from] + 1;
  }
  return level;
}

// would adding from -> to make a cycle? (true when `to` already reaches `from`)
export function wouldCycle(edges, from, to) {
  if (from === to) return true;
  const seen = new Set();
  const walk = (n) => {
    if (n === from) return true;
    if (seen.has(n)) return false;
    seen.add(n);
    return edges.some((e) => e.from === n && walk(e.to));
  };
  return walk(to);
}

const W = 196, H = 58, GX = 76, GY = 22, PAD = 14;

export function dag({ nodes, edges, selected, onSelect, compact = false }) {
  const byLevel = new Map();
  nodes.forEach((n) => { const l = n.level ?? 0; byLevel.set(l, [...(byLevel.get(l) || []), n]); });
  const levels = [...byLevel.keys()].sort((a, b) => a - b);
  const maxRows = Math.max(1, ...[...byLevel.values()].map((v) => v.length));
  const width = PAD * 2 + levels.length * W + (levels.length - 1) * GX;
  const height = PAD * 2 + maxRows * H + (maxRows - 1) * GY;
  const pos = {};
  levels.forEach((l, col) => {
    const col_nodes = byLevel.get(l), colH = col_nodes.length * H + (col_nodes.length - 1) * GY;
    col_nodes.forEach((n, i) => { pos[n.name] = { x: PAD + col * (W + GX), y: PAD + (height - PAD * 2 - colH) / 2 + i * (H + GY) }; });
  });

  const svg = s('svg', { viewBox: `0 0 ${width} ${height}`, width, height, class: 'dag', role: 'group', 'aria-label': 'Dataset lineage' });
  svg.appendChild(s('defs', s('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
    s('path', { d: 'M1,1 L9,5 L1,9 z', fill: 'var(--ink-3)' }))));
  for (const e of edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x - 2, y2 = b.y + H / 2, dx = Math.max(24, (x2 - x1) / 2);
    const hot = selected && (e.from === selected || e.to === selected);
    svg.appendChild(s('path', { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, class: `edge ${hot ? 'hot' : ''}`, 'marker-end': 'url(#arrow)' }));
  }
  for (const n of nodes) {
    const p = pos[n.name];
    const st = n.status || 'skipped';
    const g = s('g', { transform: `translate(${p.x},${p.y})`, class: `node st-${st} ${selected === n.name ? 'sel' : ''}`,
      role: onSelect ? 'button' : 'img', tabindex: onSelect ? 0 : null,
      'aria-label': `${n.name}: ${STATUS[st] ? STATUS[st].label : st}${n.incident_root ? ', root of an open incident' : ''}${n.business_visible ? ', business visible' : ''}` });
    if (n.incident_root) g.appendChild(s('rect', { x: -4, y: -4, width: W + 8, height: H + 8, rx: 14, class: 'pulse' }));
    g.appendChild(s('rect', { width: W, height: H, rx: 11, class: 'node-box' }));
    g.appendChild(s('rect', { x: 0, y: 12, width: 4, height: H - 24, rx: 2, class: 'node-bar' }));
    const glyph = s('svg', { x: 14, y: 14, width: 18, height: 18, viewBox: '0 0 16 16' });
    glyph.innerHTML = (Object.hasOwn(GLYPH_PATHS, st) ? GLYPH_PATHS[st] : GLYPH_PATHS.skipped)[0];
    g.appendChild(glyph);
    g.appendChild(s('text', { x: 42, y: 25, class: 'node-name' }, n.name.length > 20 ? `${n.name.slice(0, 19)}…` : n.name));
    g.appendChild(s('text', { x: 42, y: 43, class: 'node-sub' }, compact ? (n.sub || '') : (n.source.length > 26 ? `${n.source.slice(0, 25)}…` : n.source)));
    if (n.business_visible) {
      g.appendChild(s('g', { transform: `translate(${W - 26},8)`, 'data-tip': 'Business visible: people rely on this dataset' },
        s('rect', { width: 18, height: 18, rx: 5, class: 'vis-badge' }),
        s('path', { d: 'M3 9s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4z', transform: 'translate(0,0) scale(.98)', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.3, class: 'vis-ico' }),
        s('circle', { cx: 9, cy: 9, r: 1.6, class: 'vis-dot' })));
    }
    if (onSelect) {
      g.addEventListener('click', () => onSelect(n.name));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(n.name); } });
    }
    svg.appendChild(g);
  }
  return h('div', { class: 'dag-wrap' }, svg);
}
