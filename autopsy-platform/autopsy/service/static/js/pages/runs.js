// Runs: every check sweep, investigation and baseline, filterable.
import { get, qs } from '../api.js';
import { openRun } from '../components.js';
import { chip, duration, empty, h, kindLabel, mount, skeleton, tickTimes, timeEl, triggerLabel } from '../ui.js';

export default async function runsPage(root, params, ctx) {
  const st = { project: '', kind: '', status: '' };
  const body = h('div', { class: 'card flat' }, skeleton(5, 30));
  const sel = (label, key, options) => h('select', { 'aria-label': label, onChange: (e) => { st[key] = e.target.value; last = ''; load(); } },
    h('option', { value: '' }, `All ${label.toLowerCase()}s`), options.map(([v, t]) => h('option', { value: v }, t)));
  const projectSel = sel('Project', 'project', []);
  mount(root, h('div', { class: 'page-head' }, h('h1', 'Runs')),
    h('div', { class: 'row wrap filter-bar' }, projectSel,
      sel('Kind', 'kind', [['monitor', 'Monitor'], ['investigation', 'Investigation'], ['baseline', 'Baseline']]),
      sel('Status', 'status', [['ok', 'Passing'], ['warn', 'Warning'], ['fail', 'Failing'], ['error', 'Could not run'], ['running', 'Running']])), body);
  get('/projects').then((d) => d.projects.forEach((p) => projectSel.appendChild(h('option', { value: p.name }, p.name)))).catch(() => {});
  let last = '';
  async function load() {
    try {
      const { runs } = await get(`/runs${qs({ project: st.project, kind: st.kind, limit: 200 })}`);
      const rows = st.status ? runs.filter((r) => r.status === st.status) : runs;
      const sig = JSON.stringify(rows);
      if (sig === last) return;
      last = sig;
      mount(body, rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 't' },
        h('thead', h('tr', ['Run', 'Project', 'Kind', 'Status', 'Summary', 'Trigger', 'Took', 'When'].map((c) => h('th', { scope: 'col' }, c)))),
        h('tbody', rows.map((r) => h('tr', { class: 'click', tabindex: 0, onClick: () => openRun(r.id), onKeydown: (e) => { if (e.key === 'Enter') openRun(r.id); } },
          h('td', { class: 'num muted' }, `#${r.id}`), h('td', h('b', r.project)), h('td', kindLabel[r.kind] || r.kind), h('td', chip(r.status)),
          h('td', { class: 'clamp-cell' }, r.summary || ''), h('td', { class: 'muted' }, triggerLabel[r.trigger] || r.trigger),
          h('td', { class: 'num muted' }, duration(r.duration_ms)), h('td', timeEl(r.finished_at || r.started_at)))))))
        : empty({ icon: 'activity', title: 'No runs match', text: 'Run checks from a project page, or change the filters.' }));
      tickTimes(body);
    } catch (e) { mount(body, h('div', { class: 'callout bad', style: { margin: '16px' } }, e.message)); }
  }
  await load();
  ctx.every(10000, load);
}
