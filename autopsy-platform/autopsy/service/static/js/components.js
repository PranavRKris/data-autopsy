// Pieces used on several pages: run drawer, incident rows, project cards, the "run now" action.
import { enc, get, post } from './api.js';
import { stackedBar } from './charts.js';
import { renderMarkdown } from './md.js';
import { changed } from './shell.js';
import {
  CONNECTOR_ICON, STATUS, TOOL_LABEL, ago, chip, duration, h, icon, jsonDetails, kindLabel, label, plural, ring, scheduleText,
  sev, skeleton, statusIcon, timeEl, triggerLabel,
} from './ui.js';
import { busy, overlay, toast, toastError } from './widgets.js';

export const projectUrl = (name, tab) => `#/projects/${enc(name)}${tab ? `/${tab}` : ''}`;

// Run monitor/investigation now. Resolves with the run, or null when the service refused.
export function runNow(project, btn, kind = 'monitor', dataset) {
  return busy(btn, async () => {
    try {
      const run = await post(`/projects/${enc(project)}/runs`, { kind, dataset });
      toast(kind === 'monitor' ? `Checks finished: ${run.summary}` : `Investigation finished: ${run.summary}`, run.status === 'ok' ? 'good' : 'info');
      changed();
      return run;
    } catch (e) {
      toastError(e);
      return null;
    }
  });
}

export function statusCounts(counts) {
  return stackedBar([
    { label: 'failing', value: counts.fail || 0, color: 'var(--fail)' }, { label: 'could not run', value: counts.error || 0, color: 'var(--error)' },
    { label: 'warning', value: counts.warn || 0, color: 'var(--warn)' }, { label: 'passing', value: counts.ok || 0, color: 'var(--ok)' },
    { label: 'skipped', value: counts.skipped || 0, color: 'var(--line-2)' }]);
}

function findingRow(f) {
  const evidence = f.finding && f.finding.evidence;
  return h('li', { class: 'finding' },
    h('div', { class: 'row' }, chip(f.status, f.status === 'ok' ? 'Passing' : undefined), h('b', label(f.tool))),
    h('p', { class: 'small' }, f.summary),
    evidence && Object.keys(evidence).length ? jsonDetails(evidence) : (f.status === 'error' ? jsonDetails(f.finding, 'Details') : null));
}

export function findingsByDataset(findings) {
  const groups = new Map();
  findings.forEach((f) => groups.set(f.dataset, [...(groups.get(f.dataset) || []), f]));
  return h('div', { class: 'stack' }, [...groups].map(([dataset, list]) => {
    const worst = ['fail', 'error', 'warn', 'ok', 'skipped'].find((st) => list.some((f) => f.status === st));
    return h('details', { class: 'group-card', open: worst === 'fail' || worst === 'error' || worst === 'warn' },
      h('summary', statusIcon(worst, 16), h('b', dataset), h('span', { class: 'muted small' }, plural(list.length, 'check'))),
      h('ul', { class: 'findings' }, list.map(findingRow)));
  }));
}

export async function openRun(id) {
  const dlg = overlay({ title: `Run #${id}`, kind: 'drawer', size: 'wide', body: skeleton(5) });
  try {
    const run = await get(`/runs/${id}`);
    const body = [
      h('div', { class: 'row wrap' }, chip(run.status), h('span', { class: 'tag' }, kindLabel[run.kind] || run.kind),
        h('span', { class: 'muted small' }, triggerLabel[run.trigger] || run.trigger), h('span', { class: 'muted small' }, 'started ', timeEl(run.started_at)),
        run.duration_ms !== null ? h('span', { class: 'muted small' }, `took ${duration(run.duration_ms)}`) : null),
      h('p', { class: 'lead' }, run.summary || ''),
      run.counts ? h('div', { class: 'stack', style: { gap: '8px' } }, statusCounts(run.counts), h('div', { class: 'legend' }, ['fail', 'error', 'warn', 'ok', 'skipped']
        .filter((k) => run.counts[k]).map((k) => h('span', { class: 'row', style: { gap: '6px' } }, statusIcon(k, 13), `${run.counts[k]} ${STATUS[k].word}`)))) : null,
      run.root_dataset ? h('div', { class: 'callout bad' }, icon('alert', 18), h('div', h('b', `${run.root_dataset} / ${label(run.root_check)}`), ' ', sev(run.severity), h('div', { class: 'small' }, 'Root cause found by this investigation.'))) : null,
      run.report ? h('section', h('h3', { class: 'section-h' }, 'Report'), h('div', { class: 'report' }, renderMarkdown(run.report))) : null,
      run.findings.length ? h('section', h('h3', { class: 'section-h' }, 'Findings'), findingsByDataset(run.findings)) : null,
    ];
    dlg.setTitle(`Run #${id} · ${run.project}`);
    dlg.setBody(h('div', { class: 'stack', style: { gap: '20px' } }, body));
  } catch (e) {
    dlg.setBody(h('div', { class: 'callout bad' }, e.message));
  }
  return dlg;
}

export function incidentItem(inc, { project = true } = {}) {
  const open = inc.status === 'open';
  return h('a', { class: 'list-item', href: `#/incidents/${inc.id}` },
    h('div', { class: 'row wrap' }, sev(inc.severity), h('b', `${inc.root_dataset} / ${label(inc.root_check)}`),
      project ? h('span', { class: 'tag' }, inc.project) : null,
      open ? chip('fail', 'Open') : chip('ok', 'Resolved'), inc.acknowledged ? h('span', { class: 'tag' }, 'Acknowledged') : null,
      h('span', { class: 'right muted small' }, open ? ['last seen ', timeEl(inc.last_seen)] : ['resolved ', timeEl(inc.resolved_at)])),
    h('p', { class: 'small muted clamp' }, inc.summary || ''),
    inc.occurrences > 1 ? h('span', { class: 'xs muted' }, `Seen in ${inc.occurrences} runs since `, timeEl(inc.first_seen)) : null);
}

export function runItem(run, { project = true } = {}) {
  return h('button', { class: 'list-item btn-reset', type: 'button', onClick: () => openRun(run.id) },
    h('div', { class: 'row wrap' }, statusIcon(run.status, 16), h('b', kindLabel[run.kind] || run.kind),
      project ? h('span', { class: 'tag' }, run.project) : null, h('span', { class: 'muted xs' }, triggerLabel[run.trigger] || run.trigger),
      h('span', { class: 'right muted small' }, timeEl(run.finished_at || run.started_at))),
    h('p', { class: 'small muted clamp' }, run.summary || (run.status === 'running' ? 'Running…' : '')));
}

export function projectCard(p) {
  const run = h('button', { class: 'btn sm', 'aria-label': `Run checks for ${p.name}`, onClick: async (e) => { const r = await runNow(p.name, e.currentTarget); if (r && p.onRan) p.onRan(); } }, icon('play', 14), 'Run checks');
  const checked = p.counts.ok + p.counts.warn + p.counts.fail + p.counts.error;
  return h('article', { class: 'card project-card' },
    h('div', { class: 'row', style: { alignItems: 'flex-start' } }, ring(p.counts, p.status || 'skipped', 52),
      h('div', { class: 'grow' }, h('h2', h('a', { class: 'stretch', href: projectUrl(p.name) }, p.name)),
        h('div', { class: 'row wrap small muted', style: { gap: '6px 12px', marginTop: '2px' } },
          h('span', { class: 'row', style: { gap: '5px' } }, icon(CONNECTOR_ICON[p.connector] || 'db', 14), p.connector),
          h('span', plural(p.datasets, 'dataset'))))),
    h('div', { class: 'row wrap', style: { gap: '6px' } },
      p.status ? chip(p.status) : h('span', { class: 'chip plain' }, 'Not checked yet'),
      p.open_incidents ? h('span', { class: 'chip s-fail' }, icon('alert', 13), plural(p.open_incidents, 'open incident'), ' ', sev(p.worst_severity)) : null,
      h('span', { class: 'chip plain', 'data-tip': p.schedule.enabled && p.schedule.next_run_at ? `Next run ${ago(p.schedule.next_run_at)}` : 'Checks run only when you start them' },
        icon('clock', 13), scheduleText(p.schedule))),
    h('dl', { class: 'facts' },
      h('div', h('dt', 'Passing'), h('dd', checked ? `${p.counts.ok} of ${checked}` : '–')),
      h('div', h('dt', 'Baseline'), h('dd', p.baseline_at ? timeEl(p.baseline_at) : h('span', { class: 'warn-text' }, 'Not learned'))),
      h('div', h('dt', 'Last run'), h('dd', p.last_run ? timeEl(p.last_run.finished_at || p.last_run.started_at) : '–'))),
    p.last_run ? h('p', { class: 'small muted clamp' }, p.last_run.summary) : h('p', { class: 'small muted' }, 'No runs yet.'),
    h('div', { class: 'card-actions' }, run));
}
