// Project page: header with actions, tab bar (kept in the hash), and one module per tab.
import { enc, get } from '../api.js';
import { incidentItem, projectUrl, runNow } from '../components.js';
import { go } from '../router.js';
import { CONNECTOR_ICON, chip, h, icon, mount, plural, sev, skeleton, tickTimes, timeEl, label } from '../ui.js';
import { changed } from '../shell.js';
import health from './project/health.js';
import history from './project/history.js';
import lineage from './project/lineage.js';
import setup from './project/setup.js';
import trends from './project/trends.js';
import { incidentsList } from './incidents.js';

const TABS = [
  ['health', 'Health', 'shield', health], ['lineage', 'Lineage', 'lineage', lineage], ['trends', 'Trends', 'bar', trends],
  ['history', 'History', 'grid', history], ['incidents', 'Incidents', 'alert', incidentsTab], ['setup', 'Setup', 'settings', setup],
];

function incidentsTab(box, state, ctx) { return incidentsList(box, {}, ctx, { project: state.name }); }

export default async function project(root, { name, tab }, ctx) {
  const current = TABS.find((t) => t[0] === tab) || TABS[0];
  if (tab && !TABS.some((t) => t[0] === tab)) { go(`/projects/${enc(name)}`); return; }
  mount(root, h('div', { class: 'page-head' }, h('h1', name)), skeleton(6, 40));
  const state = { name, detail: null };
  const head = h('div'), tabs = h('nav', { class: 'tabs', 'aria-label': 'Project sections' }), box = h('div', { class: 'tab-box' });
  let tabCleanup = null, last = '';

  async function fetchDetail() { state.detail = await get(`/projects/${enc(name)}`); return state.detail; }
  state.reload = async () => { await fetchDetail(); paintHead(); await paintTab(); changed(); };

  function paintHead() {
    const d = state.detail;
    const run = h('button', { class: 'btn primary', onClick: async (e) => { if (await runNow(name, e.currentTarget)) state.reload(); } }, icon('play', 15), 'Run checks');
    const inv = h('button', { class: 'btn', 'data-tip': 'Check every dataset upstream of the ones that look wrong and name the root cause', onClick: async (e) => { if (await runNow(name, e.currentTarget, 'investigation')) state.reload(); } }, icon('zap', 15), 'Investigate');
    const st = d.status;
    mount(head,
      h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/' }, 'Overview'), icon('chevR', 14), h('span', name)),
      h('div', { class: 'page-head' }, h('div', { class: 'grow' }, h('h1', name),
        h('div', { class: 'row wrap small muted', style: { gap: '6px 14px', marginTop: '6px' } },
          h('span', { class: 'row', style: { gap: '5px' } }, icon(CONNECTOR_ICON[d.connection.connector] || 'db', 14), h('a', { href: '#/connections' }, d.connection.name), `(${d.connection.connector})`),
          h('span', plural(d.datasets.length, 'dataset')),
          h('span', 'Last run ', d.last_run ? timeEl(d.last_run.finished_at || d.last_run.started_at) : '–'),
          h('span', 'Baseline ', d.baseline ? ['learned ', timeEl(d.baseline.created_at)] : h('b', { class: 'warn-text' }, 'not learned yet')))),
        h('div', { class: 'right row wrap' }, st.overall ? chip(st.overall) : h('span', { class: 'chip plain' }, 'Not checked yet'), inv, run)),
      d.open_incidents.length ? h('a', { class: 'callout bad incident-banner', href: `#/incidents/${d.open_incidents[0].id}` }, icon('alert', 18),
        h('div', { class: 'grow' }, h('b', plural(d.open_incidents.length, 'open incident')), ': ', `${d.open_incidents[0].root_dataset} / ${label(d.open_incidents[0].root_check)} `, sev(d.open_incidents[0].severity)),
        h('span', { class: 'row' }, 'Open report', icon('arrow', 15))) : null);
    tickTimes(head);
  }

  async function paintTab(first) {
    if (tabCleanup) { tabCleanup(); tabCleanup = null; }
    const [key, , , fn] = current;
    const result = await fn(box, state, ctx, first);
    if (typeof result === 'function') tabCleanup = result;
    tickTimes(box);
  }

  try { await fetchDetail(); } catch (e) {
    mount(root, h('div', { class: 'callout bad' }, e.message), h('p', h('a', { href: '#/' }, 'Back to the overview')));
    return;
  }
  last = JSON.stringify(state.detail);
  mount(tabs, TABS.map(([key, text, ic]) => h('a', { href: projectUrl(name, key === 'health' ? '' : key), 'aria-current': key === current[0] ? 'page' : null }, icon(ic, 15), text,
    key === 'incidents' && state.detail.open_incidents.length ? h('span', { class: 'count-badge' }, state.detail.open_incidents.length) : null)));
  mount(root, head, tabs, box);
  paintHead();
  await paintTab(true);
  ctx.onCleanup(() => { if (tabCleanup) tabCleanup(); });
  ctx.every(10000, async () => {
    try { await fetchDetail(); } catch (e) { return; }
    const sig = JSON.stringify(state.detail);
    if (sig === last) return;
    last = sig;
    paintHead();
    if (['health', 'lineage'].includes(current[0])) await paintTab();
  });
}
