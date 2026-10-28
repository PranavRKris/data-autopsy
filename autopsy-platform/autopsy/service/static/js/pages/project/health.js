// Health tab: datasets (rows) by check type (columns), newest result per cell, expandable evidence.
import { get } from '../../api.js';
import { h, icon, jsonDetails, mount, plural, STATUS, statusIcon, timeEl, TOOLS, TOOL_HELP, TOOL_LABEL, empty, skeleton } from '../../ui.js';
import { openRun } from '../../components.js';

const runCache = new Map();
async function finding(runId, dataset, tool) {
  if (!runCache.has(runId)) runCache.set(runId, get(`/runs/${runId}`));
  const run = await runCache.get(runId);
  return { run, f: run.findings.find((x) => x.dataset === dataset && x.tool === tool) };
}

const NA = { check_freshness: 'needs an event_time column', check_volume: 'needs an event_time column', check_schema: 'always available',
  profile_dataset: 'needs measure or required columns', find_duplicates: 'needs a key column' };

export default function health(box, state) {
  const d = state.detail, st = d.status;
  if (!Object.keys(st.datasets).length) {
    mount(box, h('div', { class: 'card' }, empty({ icon: 'shield', title: 'No results yet', text: 'Run the checks once to see the state of every dataset.' })));
    return;
  }
  let open = null;                         // "dataset|tool" of the expanded cell
  const body = h('tbody');

  async function expand(row, dataset, tool, cell) {
    const key = `${dataset}|${tool}`;
    body.querySelectorAll('tr.expand').forEach((r) => r.remove());
    body.querySelectorAll('button.cell[aria-expanded="true"]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
    if (open === key) { open = null; return; }
    open = key;
    cell.setAttribute('aria-expanded', 'true');
    const area = h('td', { colspan: TOOLS.length + 1 }, skeleton(2));
    const tr = h('tr', { class: 'expand' }, area);
    row.after(tr);
    try {
      const { run, f } = await finding(st.datasets[dataset][tool].run_id, dataset, tool);
      const data = f ? f.finding : {};
      mount(area, h('div', { class: 'expand-in' },
        h('div', { class: 'row wrap' }, statusIcon(f.status, 18), h('b', `${dataset} · ${TOOL_LABEL[tool]}`), h('span', { class: 'muted small' }, 'from ', h('button', { class: 'linklike', onClick: () => openRun(run.id) }, `run #${run.id}`), ' ', timeEl(f.at || run.finished_at))),
        h('p', f.summary),
        data.evidence && Object.keys(data.evidence).length ? jsonDetails(data.evidence) : null,
        data.next_checks && data.next_checks.length ? h('p', { class: 'small muted' }, 'Worth checking next: ', data.next_checks.map((n, i) => [i ? ', ' : '', h('code', n)])) : null,
        data.error ? jsonDetails(data, 'Details') : null));
    } catch (e) { mount(area, h('div', { class: 'callout bad' }, e.message)); }
  }

  mount(body, d.datasets.map((ds) => {
    const checks = st.datasets[ds.name] || {};
    const row = h('tr');
    mount(row, h('th', { scope: 'row', class: 'ds-name' }, h('div', { class: 'row', style: { gap: '8px' } }, statusIcon(st.per_dataset[ds.name] || 'skipped', 16),
      h('div', h('b', ds.name), h('div', { class: 'xs muted mono' }, ds.source), ds.business_visible ? h('span', { class: 'tag vis' }, icon('eye', 11), 'business visible') : null))),
    TOOLS.map((tool) => {
      const c = checks[tool];
      if (!c) return h('td', { class: 'na', 'data-tip': `Not applicable: ${NA[tool]}` }, h('span', { 'aria-label': 'not applicable' }, '–'));
      const btn = h('button', { class: `cell s-${c.status}`, type: 'button', 'aria-expanded': 'false', 'aria-label': `${ds.name} ${TOOL_LABEL[tool]}: ${STATUS[c.status].label}. Show details`,
        'data-tip': c.summary, onClick: () => expand(row, ds.name, tool, btn) }, statusIcon(c.status, 15), h('span', STATUS[c.status].label));
      return h('td', btn);
    }));
    return row;
  }));

  mount(box,
    h('div', { class: 'card flat' }, h('div', { class: 'table-wrap' }, h('table', { class: 't matrix' },
      h('thead', h('tr', h('th', { scope: 'col' }, 'Dataset'), TOOLS.map((tool) => h('th', { scope: 'col', 'data-tip': TOOL_HELP[tool], tabindex: 0 }, TOOL_LABEL[tool])))),
      body))),
    h('p', { class: 'small muted', style: { marginTop: '12px' } }, `${plural(d.datasets.length, 'dataset')} · latest result for each check · `, st.checked_at ? ['last checked ', timeEl(st.checked_at)] : '',
      ' · select a result to see its evidence'));
}
