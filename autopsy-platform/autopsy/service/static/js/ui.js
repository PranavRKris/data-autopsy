// DOM builder, icons, status vocabulary and formatting. Everything is built with createElement/textContent,
// so API text can never become markup.
const SVG_NS = 'http://www.w3.org/2000/svg';
const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'indeterminate', 'open', 'hidden']);

function apply(el, attrs, isSvg) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') isSvg ? el.setAttribute('class', v) : (el.className = v);
    else if (k === 'text') el.textContent = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (!isSvg && PROPS.has(k)) el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
}

function append(el, kids) {
  for (const kid of kids) {
    if (kid === null || kid === undefined || kid === false) continue;
    if (Array.isArray(kid)) append(el, kid);
    else if (kid.nodeType) el.appendChild(kid);
    else el.appendChild(document.createTextNode(String(kid)));
  }
}

const isChild = (x) => x && (x.nodeType || typeof x === 'string' || typeof x === 'number' || Array.isArray(x));

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (isChild(attrs)) { kids.unshift(attrs); attrs = null; }
  apply(el, attrs, false);
  append(el, kids);
  return el;
}

export function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  if (isChild(attrs)) { kids.unshift(attrs); attrs = null; }
  apply(el, attrs, true);
  append(el, kids);
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function mount(el, ...kids) { clear(el); append(el, kids); return el; }

// ---------- icons ----------
const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  chevR: '<path d="m9 6 6 6-6 6"/>',
  chevD: '<path d="m6 9 6 6 6-6"/>',
  chevL: '<path d="m15 6-6 6 6 6"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  download: '<path d="M12 4v11m-4-4 4 4 4-4M5 20h14"/>',
  upload: '<path d="M12 16V5m-4 4 4-4 4 4M5 20h14"/>',
  db: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
  dbfile: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 13h6M10 17h6"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  server: '<rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/><path d="M8 7h.01M8 17h.01"/>',
  table: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M10 10v9"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
  alert: '<path d="M12 4 3 20h18z"/><path d="M12 10v4m0 3h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  lineage: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="12" r="2.5"/><path d="M8.5 6H11a3 3 0 0 1 3 3v.5M8.5 18H11a3 3 0 0 0 3-3v-.5"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8m-3 3 3 3"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
  zap: '<path d="M13 3 5 13h6l-1 8 8-10h-6z"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4m8-4v4"/>',
  shield: '<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  bar: '<path d="M5 20V10m7 10V4m7 16v-7"/>',
  cmd: '<path d="M8 3H6a3 3 0 1 0 3 3zm0 0h8m-8 0v18m8-18h2a3 3 0 1 1-3 3zm0 0v18M8 21H6a3 3 0 1 1 3-3zm8 0h2a3 3 0 1 0-3-3z"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
};

export function icon(name, size = 16, cls = '') {
  const el = s('svg', { viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor',
    'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: cls });
  el.innerHTML = Object.hasOwn(ICONS, name) ? ICONS[name] : ICONS.info;   // static, trusted markup only
  return el;
}

export function logo(size = 18) {
  return s('svg', { viewBox: '0 0 32 32', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 2.6,
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' },
    s('path', { d: 'M3 17h6l4-9 6 17 4-8h6' }));
}

export const CONNECTOR_ICON = { duckdb: 'db', sqlite: 'dbfile', files: 'folder', postgres: 'server' };

// ---------- status vocabulary ----------
export const STATUS = {
  ok: { label: 'Passing', word: 'ok' },
  warn: { label: 'Warning', word: 'warning' },
  fail: { label: 'Failing', word: 'failing' },
  error: { label: 'Could not run', word: 'error' },
  skipped: { label: 'Skipped', word: 'skipped' },
  running: { label: 'Running', word: 'running' },
};

const GLYPHS = {
  ok: '<circle cx="8" cy="8" r="7" fill="var(--ok)"/><path d="m4.8 8.2 2.2 2.2 4.2-4.6" stroke="#fff" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
  warn: '<path d="M8 1.6 15 14H1z" fill="var(--warn)" stroke="var(--warn)" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.2v3.4M8 11.7v.1" stroke="#0b0b0b" stroke-width="1.6" stroke-linecap="round"/>',
  fail: '<rect x="1.2" y="1.2" width="13.6" height="13.6" rx="3.6" fill="var(--fail)"/><path d="m5.4 5.4 5.2 5.2m0-5.2-5.2 5.2" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>',
  error: '<path d="M8 .9 15.1 8 8 15.1.9 8z" fill="var(--error)" stroke="var(--error)" stroke-width="1" stroke-linejoin="round"/><path d="M8 4.9v3.6M8 10.7v.1" stroke="#0b0b0b" stroke-width="1.6" stroke-linecap="round"/>',
  skipped: '<circle cx="8" cy="8" r="6.3" fill="none" stroke="var(--skip)" stroke-width="1.4" stroke-dasharray="2.3 2"/><path d="M5.6 8h4.8" stroke="var(--skip)" stroke-width="1.6" stroke-linecap="round"/>',
  running: '<circle cx="8" cy="8" r="6" fill="none" stroke="var(--line-2)" stroke-width="2"/><path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round"/>',
};

export function statusIcon(status, size = 16) {
  const kind = Object.hasOwn(GLYPHS, status) ? status : 'skipped';
  const el = s('svg', { viewBox: '0 0 16 16', width: size, height: size, 'aria-hidden': 'true', class: kind === 'running' ? 'spin' : '' });
  el.innerHTML = GLYPHS[kind];
  return el;
}

export function chip(status, label) {
  const kind = Object.hasOwn(STATUS, status) ? status : 'skipped';
  return h('span', { class: `chip s-${kind}` }, statusIcon(kind, 14), label ?? STATUS[kind].label);
}

export function sev(severity) {
  return severity ? h('span', { class: `sev sev-${severity}`, 'data-tip': SEV_HELP[severity] || '' }, severity) : null;
}
const SEV_HELP = {
  SEV1: 'Wrong values reach a business-visible dataset, with a large error',
  SEV2: 'Wrong values with a partial effect, or only in datasets no business user sees',
  SEV3: 'Data is late or missing, but the values present are correct',
  SEV4: 'Quality warning with no measurable effect yet',
};

export const TOOLS = ['check_freshness', 'check_volume', 'check_schema', 'profile_dataset', 'find_duplicates'];
export const TOOL_LABEL = { check_freshness: 'Freshness', check_volume: 'Volume', check_schema: 'Schema', profile_dataset: 'Profile', find_duplicates: 'Duplicates' };
export const TOOL_HELP = {
  check_freshness: 'Is the newest event recent enough?',
  check_volume: 'Are daily row counts inside the usual band?',
  check_schema: 'Do the columns still match what was learned?',
  profile_dataset: 'Null rates, value ranges and medians against normal',
  find_duplicates: 'Does any key value appear more than once?',
};
export const label = (tool) => TOOL_LABEL[tool] || tool;

// compact donut: failing / error / warning / passing shares, with a gap between segments
export function ring(counts, overall, size = 48) {
  const parts = [['fail', 'var(--fail)'], ['error', 'var(--error)'], ['warn', 'var(--warn)'], ['ok', 'var(--ok)']]
    .map(([k, c]) => [k, c, (counts && counts[k]) || 0]);
  const total = parts.reduce((a, p) => a + p[2], 0);
  const r = 18, C = 2 * Math.PI * r;
  const svg = s('svg', { viewBox: '0 0 48 48', width: size, height: size, role: 'img',
    'aria-label': total ? parts.filter((p) => p[2]).map((p) => `${p[2]} ${STATUS[p[0]].word}`).join(', ') : 'no checks yet' });
  svg.appendChild(s('circle', { cx: 24, cy: 24, r, fill: 'none', stroke: total ? 'var(--surface-3)' : 'var(--line-2)', 'stroke-width': 6, 'stroke-dasharray': total ? null : '3 4' }));
  let offset = 0;
  const gap = parts.filter((p) => p[2]).length > 1 ? 2 : 0;
  for (const [, color, n] of parts) {
    if (!n) continue;
    const len = Math.max(0.5, (n / total) * C - gap);
    svg.appendChild(s('circle', { cx: 24, cy: 24, r, fill: 'none', stroke: color, 'stroke-width': 6, 'stroke-dasharray': `${len} ${C - len}`,
      'stroke-dashoffset': -offset, transform: 'rotate(-90 24 24)' }));
    offset += (n / total) * C;
  }
  const mid = s('svg', { x: 15, y: 15, width: 18, height: 18, viewBox: '0 0 16 16' });
  mid.innerHTML = Object.hasOwn(GLYPHS, overall) ? GLYPHS[overall] : GLYPHS.skipped;
  svg.appendChild(mid);
  return svg;
}

// ---------- formatting ----------
const NF = new Intl.NumberFormat('en-US');
export const fmtNum = (n) => (n === null || n === undefined || Number.isNaN(n) ? '–' : NF.format(n));
export const fmtPct = (x, digits = 1) => (x === null || x === undefined ? '–' : `${(x * 100).toFixed(digits).replace(/\.0+$/, '')}%`);
export function fmtCompact(n) {
  if (n === null || n === undefined) return '–';
  const a = Math.abs(n);
  if (a >= 1e9) return `${+(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${+(n / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${+(n / 1e3).toFixed(1)}k`;
  return NF.format(+n.toFixed(a < 10 ? 2 : 0));
}
export const parseTime = (iso) => (iso ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`) : null);

export function ago(iso) {
  const d = parseTime(iso);
  if (!d || Number.isNaN(d)) return '–';
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < -45) return `in ${spanText(-sec)}`;
  if (sec < 45) return 'just now';
  return `${spanText(sec)} ago`;
}
function spanText(sec) {
  const m = Math.round(sec / 60);
  if (m < 60) return `${Math.max(m, 1)} min`;
  const hr = Math.round(m / 60);
  if (hr < 48) return `${hr} h`;
  const day = Math.round(hr / 24);
  return `${day} d`;
}
export const fullTime = (iso) => {
  const d = parseTime(iso);
  return d && !Number.isNaN(d) ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' }) : '';
};
export const shortDay = (iso) => {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};
export function timeEl(iso) {
  if (!iso) return h('span', { class: 'muted' }, '–');
  return h('time', { datetime: iso, title: fullTime(iso), 'data-ago': iso }, ago(iso));
}
export function tickTimes(root = document) {
  root.querySelectorAll('time[data-ago]').forEach((t) => { const v = ago(t.dataset.ago); if (t.textContent !== v) t.textContent = v; });
}
export const duration = (ms) => (ms === null || ms === undefined ? '–' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`);
export const plural = (n, one, many) => `${fmtNum(n)} ${n === 1 ? one : many || `${one}s`}`;
export const kindLabel = { monitor: 'Monitor', investigation: 'Investigation', baseline: 'Baseline', validate: 'Validate' };
export const triggerLabel = { manual: 'manual', schedule: 'scheduled', auto: 'automatic' };

export function scheduleText(sch) {
  if (!sch || !sch.enabled) return 'Manual only';
  const m = sch.interval_minutes;
  return m % 1440 === 0 ? `Every ${m / 1440 === 1 ? 'day' : `${m / 1440} days`}` : m % 60 === 0 ? `Every ${m / 60 === 1 ? 'hour' : `${m / 60} hours`}` : `Every ${m} min`;
}

export function skeleton(lines = 3, height = 16) {
  return h('div', { class: 'stack', 'aria-busy': 'true', 'aria-label': 'Loading' },
    Array.from({ length: lines }, (_, i) => h('div', { class: 'skeleton', style: { height: `${height}px`, width: `${100 - (i % 3) * 14}%` } })));
}

export function empty({ icon: name = 'info', title, text, actions = [] }) {
  return h('div', { class: 'empty' }, h('div', { class: 'art' }, icon(name, 26)), h('h2', title),
    text ? h('p', text) : null, actions.length ? h('div', { class: 'row wrap', style: { justifyContent: 'center' } }, actions) : null);
}

export function jsonDetails(obj, summary = 'Evidence') {
  return h('details', { class: 'ev' }, h('summary', summary), h('pre', { class: 'code' }, JSON.stringify(obj, null, 2)));
}

export function toYaml(value, indent = 0) {
  const pad = '  '.repeat(indent);
  const scalar = (v) => (typeof v === 'string' ? (/^[A-Za-z0-9_./-][A-Za-z0-9_ ./-]*$/.test(v) && !/^(true|false|null|\d+)$/.test(v) ? v : JSON.stringify(v)) : String(v));
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v !== 'object' || v === null)) return `[${value.map(scalar).join(', ')}]`;
    return value.map((v) => {
      const body = toYaml(v, indent + 1).split('\n');
      return `${pad}- ${body[0].trimStart()}${body.length > 1 ? `\n${body.slice(1).join('\n')}` : ''}`;
    }).join('\n');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).filter(([, v]) => v !== undefined && v !== null && !(Array.isArray(v) && !v.length)
      && !(typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length)).map(([k, v]) => {
      if (v && typeof v === 'object' && !(Array.isArray(v) && v.every((x) => typeof x !== 'object'))) return `${pad}${k}:\n${toYaml(v, indent + 1)}`;
      return `${pad}${k}: ${toYaml(v, indent + 1)}`;
    }).join('\n');
  }
  return scalar(value);
}
