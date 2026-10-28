// History tab: one column per recent monitor run, one row per dataset and check, shape plus color per cell.
import { enc, get } from '../../api.js';
import { openRun } from '../../components.js';
import { ago, empty, h, mount, shortDay, skeleton, statusIcon, STATUS, TOOL_LABEL, parseTime } from '../../ui.js';

export default async function history(box, state) {
  mount(box, skeleton(5, 30));
  let data;
  try { data = await get(`/projects/${enc(state.name)}/history?limit=40`); } catch (e) { mount(box, h('div', { class: 'callout bad' }, e.message)); return; }
  if (!data.runs.length) { mount(box, h('div', { class: 'card' }, empty({ icon: 'grid', title: 'No history yet', text: 'Each check run adds a column here, so you can see when something started to fail.' }))); return; }
  const n = data.runs.length;
  const grid = h('div', { class: 'heat', style: { gridTemplateColumns: `minmax(170px, 230px) repeat(${n}, 24px)` } });
  grid.appendChild(h('div', { class: 'heat-corner' }, 'Check'));
  let prevDay = '';
  data.runs.forEach((r) => {
    const day = (r.started_at || '').slice(0, 10);
    grid.appendChild(h('button', { class: 'heat-head', type: 'button', 'aria-label': `Run ${r.id}, ${STATUS[r.status] ? STATUS[r.status].label : r.status}, ${ago(r.started_at)}. Open run`,
      'data-tip': `Run #${r.id}\n${STATUS[r.status] ? STATUS[r.status].label : r.status}, ${r.trigger === 'schedule' ? 'scheduled' : 'manual'}\n${parseTime(r.started_at).toLocaleString()}`, onClick: () => openRun(r.id) },
    statusIcon(r.status, 14), h('span', { class: 'heat-day' }, day !== prevDay ? shortDay(day) : '')));
    prevDay = day;
  });
  let lastDs = '';
  data.cells.forEach((cell) => {
    if (cell.dataset !== lastDs) {
      lastDs = cell.dataset;
      grid.appendChild(h('div', { class: 'heat-group' }, cell.dataset));
    }
    grid.appendChild(h('div', { class: 'heat-label' }, TOOL_LABEL[cell.tool] || cell.tool));
    cell.statuses.forEach((st, i) => grid.appendChild(h('div', { class: `heat-cell ${st ? '' : 'none'}`, role: 'img',
      'aria-label': `${cell.dataset} ${TOOL_LABEL[cell.tool]}, run ${data.runs[i].id}: ${st ? STATUS[st].label : 'not run'}`,
      'data-tip': `${cell.dataset} · ${TOOL_LABEL[cell.tool]}\nRun #${data.runs[i].id}: ${st ? STATUS[st].label : 'not run'}` }, st ? statusIcon(st, 13) : null)));
  });
  mount(box, h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', 'Check results over time'), h('span', { class: 'muted small' }, `Last ${n} check ${n === 1 ? 'run' : 'runs'}, oldest on the left. Select a column to open that run.`)),
    h('div', { class: 'table-wrap' }, grid),
    h('div', { class: 'legend row wrap', style: { marginTop: '14px' } }, ['ok', 'warn', 'fail', 'error', 'skipped'].map((k) => h('span', { class: 'row', style: { gap: '6px' } }, statusIcon(k, 14), STATUS[k].label)))));
}
