// App shell: top bar, navigation, service health, theme toggle, command palette, offline banner.
import { get, onOnline } from './api.js';
import { go, here } from './router.js';
import { h, icon, logo, mount, ago } from './ui.js';
import { overlay, toast } from './widgets.js';

const NAV = [['/', 'Overview'], ['/connections', 'Connections'], ['/incidents', 'Incidents'], ['/runs', 'Runs']];
let badgeEl, healthDot, healthText, navLinks = [], themeBtn, bannerHost;
const actions = {};

export const registerAction = (name, fn) => { actions[name] = fn; };

function effectiveTheme() {
  const set = document.documentElement.dataset.theme;
  return set || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
}
function paintTheme() {
  const dark = effectiveTheme() === 'dark';
  mount(themeBtn, icon(dark ? 'sun' : 'moon', 18));
  themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
}
function toggleTheme() {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('autopsy-theme', next); } catch (e) { /* private mode */ }
  paintTheme();
}

export function buildShell(root) {
  badgeEl = h('span', { class: 'count-badge', hidden: true, 'aria-label': 'open incidents' });
  navLinks = NAV.map(([path, text]) => {
    const a = h('a', { href: `#${path}`, 'data-path': path }, text, path === '/incidents' ? badgeEl : null);
    return a;
  });
  healthDot = h('span', { class: 'dot' });
  healthText = h('span', 'Service');
  themeBtn = h('button', { class: 'btn ghost icon', onClick: toggleTheme }, icon('moon', 18));
  const search = h('button', { class: 'search-btn', 'aria-label': 'Open command palette', onClick: openPalette },
    icon('search', 16), h('span', 'Search or jump to…'), h('kbd', navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'));
  const health = h('div', { class: 'health', 'data-tip': 'Checking the service…', tabindex: 0, role: 'status' }, healthDot, healthText);
  bannerHost = h('div');
  const header = h('header', { class: 'topbar' },
    h('div', { class: 'topbar-in' },
      h('a', { class: 'brand', href: '#/' }, h('span', { class: 'brand-mark' }, logo(18)), 'Pipeline Autopsy'),
      h('nav', { class: 'nav', 'aria-label': 'Main' }, navLinks),
      h('div', { class: 'topbar-end' }, search, health, themeBtn)));
  const main = h('main', { id: 'main' });
  mount(root, header, bannerHost, main);
  paintTheme();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paintTheme);

  onOnline((up) => {
    mount(bannerHost, up ? null : h('div', { class: 'banner', role: 'alert' }, icon('alert', 18),
      'Cannot reach the service. Data on screen may be out of date; it will refresh when the service is back.'));
    if (up) refreshChrome();
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
  });
  const setHealth = (data) => {
    healthDot.className = `dot ${data ? (data.scheduler.running ? 'on' : '') : 'off'}`;
    healthText.textContent = data ? (data.scheduler.running ? 'Scheduler on' : 'Scheduler off') : 'Offline';
    health.setAttribute('data-tip', data
      ? `Service ${data.version}\n${data.scheduler.running ? `Scheduler running${data.scheduler.last_tick ? `, last tick ${ago(data.scheduler.last_tick)}` : ''}` : 'Scheduler not running: scheduled checks will not fire'}`
      : 'The service did not answer');
  };
  async function refreshChrome() {
    get('/health').then(setHealth).catch(() => setHealth(null));
    get('/incidents?status=open&limit=200').then((d) => {
      const n = d.incidents.length;
      badgeEl.hidden = n === 0;
      badgeEl.textContent = n > 99 ? '99+' : String(n);
    }).catch(() => {});
  }
  refreshChrome();
  setInterval(() => { if (!document.hidden) refreshChrome(); }, 10000);
  window.addEventListener('autopsy:changed', refreshChrome);
  return main;
}

export function markNav(path) {
  navLinks.forEach((a) => {
    const p = a.dataset.path;
    const on = p === '/' ? path === '/' : path === p || path.startsWith(`${p}/`);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
}

export const changed = () => window.dispatchEvent(new Event('autopsy:changed'));

// ---------- command palette ----------
async function openPalette() {
  let items = [
    ['Pages', 'Overview', 'Projects and what needs attention', 'grid', () => go('/')],
    ['Pages', 'Connections', 'Databases and folders the platform can read', 'db', () => go('/connections')],
    ['Pages', 'Incidents', 'Root causes found by investigations', 'alert', () => go('/incidents')],
    ['Pages', 'Runs', 'Every check, investigation and baseline', 'activity', () => go('/runs')],
    ['Actions', 'Add connection', 'Test and save a new data source', 'plus', () => actions.addConnection && actions.addConnection()],
    ['Actions', 'New project', 'Map datasets to roles and lineage', 'plus', () => go('/projects/new')],
    ['Actions', 'Import manifest', 'Bring in an existing manifest file', 'upload', () => actions.importManifest && actions.importManifest()],
    ['Actions', 'Toggle theme', 'Switch between light and dark', 'moon', toggleTheme],
  ].map(([group, label, hint, ic, run]) => ({ group, label, hint, ic, run }));
  const input = h('input', { type: 'text', class: 'palette-in', placeholder: 'Type a page, project or action…', 'aria-label': 'Search', role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'pal-list', autocomplete: 'off' });
  const list = h('ul', { class: 'palette-list', id: 'pal-list', role: 'listbox' });
  let shown = [], sel = 0;
  const dlg = overlay({ title: 'Command palette', kind: 'modal', body: h('div', { style: { margin: '-24px', display: 'block' } }, input, list), label: 'Command palette' });
  dlg.el.querySelector('.panel-head').hidden = true;
  dlg.foot.hidden = true;
  const run = (it) => { dlg.close(); setTimeout(() => { try { it.run(); } catch (e) { toast(e.message, 'bad'); } }, 0); };
  const paint = () => {
    const q = input.value.trim().toLowerCase();
    shown = items.filter((it) => !q || `${it.label} ${it.hint}`.toLowerCase().includes(q));
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    let lastGroup = '';
    mount(list, shown.length ? shown.map((it, i) => {
      const parts = [];
      if (it.group !== lastGroup) { lastGroup = it.group; parts.push(h('li', { class: 'group', role: 'presentation' }, it.group)); }
      parts.push(h('li', { role: 'option', 'aria-selected': String(i === sel), onClick: () => run(it), onMousemove: () => { if (sel !== i) { sel = i; paint(); } } },
        icon(it.ic, 16), h('span', { class: 'grow' }, h('b', it.label), ' ', h('span', { style: { opacity: .7 } }, it.hint))));
      return parts;
    }) : h('li', { class: 'group' }, 'Nothing matches'));
    const cur = list.querySelector('[aria-selected="true"]');
    if (cur) cur.scrollIntoView({ block: 'nearest' });
  };
  input.addEventListener('input', () => { sel = 0; paint(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
    else if (e.key === 'Enter' && shown[sel]) { e.preventDefault(); run(shown[sel]); }
  });
  paint();
  input.focus();
  try {
    const { projects } = await get('/projects');
    items = [...items, ...projects.map((p) => ({ group: 'Projects', label: p.name, hint: `${p.datasets} datasets`, ic: 'layers', run: () => go(`/projects/${encodeURIComponent(p.name)}`) }))];
    paint();
  } catch (e) { /* palette still works without projects */ }
}
export { here };
