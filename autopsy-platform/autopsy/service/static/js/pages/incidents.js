// Incident list and incident detail (root cause, report, evidence).
import { enc, get, post, qs } from '../api.js';
import { findingsByDataset, incidentItem, openRun, projectUrl, runItem, runNow } from '../components.js';
import { renderMarkdown } from '../md.js';
import { changed } from '../shell.js';
import { chip, empty, fullTime, h, icon, label, mount, plural, sev, skeleton, tickTimes, timeEl, triggerLabel } from '../ui.js';
import { segmented, switchEl, toastError } from '../widgets.js';

export async function incidentsList(root, params, ctx, { project } = {}) {
  const st = { status: 'open', project: project || '' };
  const list = h('div', { class: 'list' }, skeleton(4, 54));
  const projectSel = h('select', { 'aria-label': 'Project', onChange: (e) => { st.project = e.target.value; load(); } }, h('option', { value: '' }, 'All projects'));
  const head = project ? null : h('div', { class: 'page-head' }, h('h1', 'Incidents'));
  const bar = h('div', { class: 'row wrap filter-bar' }, segmented([['open', 'Open'], ['resolved', 'Resolved'], ['all', 'All']], st.status, (v) => { st.status = v; load(); }), project ? null : projectSel);
  mount(root, head, bar, list);
  if (!project) get('/projects').then((d) => d.projects.forEach((p) => projectSel.appendChild(h('option', { value: p.name }, p.name)))).catch(() => {});
  let last = '';
  async function load() {
    try {
      const d = await get(`/incidents${qs({ status: st.status, project: st.project, limit: 200 })}`);
      const sig = JSON.stringify(d);
      if (sig === last) return;
      last = sig;
      mount(list, d.incidents.length ? d.incidents.map((i) => incidentItem(i, { project: !project }))
        : h('div', { class: 'card' }, empty({ icon: 'shield', title: st.status === 'open' ? 'No open incidents' : 'Nothing here', text: st.status === 'open' ? 'Checks are passing, or nobody has run them yet.' : 'No incidents match this filter.' })));
      tickTimes(list);
    } catch (e) { mount(list, h('div', { class: 'callout bad' }, e.message)); }
  }
  await load();
  ctx.every(10000, () => { last = last; load(); });
}

export default function incidentsPage(root, params, ctx) { return incidentsList(root, params, ctx); }

export async function incidentDetail(root, { id }, ctx) {
  mount(root, h('div', { class: 'page-head' }, h('h1', `Incident #${id}`)), skeleton(8));
  let inc;
  try { inc = await get(`/incidents/${id}`); } catch (e) { mount(root, h('div', { class: 'callout bad' }, e.message), h('p', h('a', { href: '#/incidents' }, 'Back to incidents'))); return; }
  const open = inc.status === 'open';
  const run = inc.run;
  const reinvestigate = h('button', { class: 'btn', onClick: async (e) => {
    const r = await runNow(inc.project, e.currentTarget, 'investigation');
    if (r) { ctx.rerender ? ctx.rerender() : incidentDetail(root, { id }, ctx); changed(); }
  } }, icon('refresh', 15), 'Re-investigate');
  const ack = switchEl({ checked: inc.acknowledged, label: 'Acknowledged', onChange: async (v) => {
    try { await post(`/incidents/${id}/ack`, { acknowledged: v }); changed(); } catch (e) { toastError(e); }
  } });
  const failing = run ? run.findings.filter((f) => f.status !== 'ok' && f.status !== 'skipped') : [];
  const passing = run ? run.findings.filter((f) => f.status === 'ok' || f.status === 'skipped') : [];
  mount(root,
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/incidents' }, 'Incidents'), icon('chevR', 14), h('a', { href: projectUrl(inc.project) }, inc.project)),
    h('div', { class: 'page-head' }, h('div', { class: 'grow' },
      h('div', { class: 'row wrap', style: { gap: '10px' } }, sev(inc.severity), open ? chip('fail', 'Open') : chip('ok', 'Resolved')),
      h('h1', { style: { marginTop: '8px' } }, `${inc.root_dataset} / ${label(inc.root_check)}`)),
    h('div', { class: 'right row wrap' }, ack, reinvestigate)),
    h('div', { class: 'card' }, h('p', { class: 'lead' }, inc.summary),
      h('dl', { class: 'facts wide' },
        h('div', h('dt', 'First seen'), h('dd', timeEl(inc.first_seen))), h('div', h('dt', 'Last seen'), h('dd', timeEl(inc.last_seen))),
        h('div', h('dt', open ? 'Seen in' : 'Resolved'), h('dd', open ? plural(inc.occurrences, 'run') : timeEl(inc.resolved_at))),
        h('div', h('dt', 'Project'), h('dd', h('a', { href: projectUrl(inc.project) }, inc.project))))),
    h('div', { class: 'two-col wide-left' },
      h('div', { class: 'stack', style: { gap: '20px' } },
        run && run.report ? h('section', h('h2', { class: 'section-h' }, 'Investigation report'), h('div', { class: 'card report' }, renderMarkdown(run.report))) : null,
        run ? h('section', h('h2', { class: 'section-h' }, 'Evidence'),
          failing.length ? findingsByDataset(failing) : h('p', { class: 'muted' }, 'No failing or warning checks in the latest investigation.'),
          passing.length ? h('details', { class: 'group-card', style: { marginTop: '12px' } }, h('summary', icon('check', 15), h('b', `${plural(passing.length, 'passing check')}`)), findingsByDataset(passing)) : null) : null),
      h('aside', { class: 'stack' },
        h('section', h('h2', { class: 'section-h' }, 'Related investigations'),
          inc.related_runs.length ? h('div', { class: 'list' }, inc.related_runs.map((r) => runItem(r, { project: false }))) : h('p', { class: 'muted small' }, 'No other investigations.')))));
  tickTimes(root);
}
