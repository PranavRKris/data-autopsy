// Overview: what needs attention across all projects.
import { get } from '../api.js';
import { incidentItem, projectCard, runItem } from '../components.js';
import { openImport } from './importer.js';
import { openConnectionDrawer } from './connections.js';
import { go } from '../router.js';
import { ago, empty, fmtNum, h, icon, mount, plural, skeleton, tickTimes, timeEl } from '../ui.js';

function stat(label, value, sub, tone) {
  return h('div', { class: `stat ${tone || ''}` }, h('div', { class: 'stat-label' }, label), h('div', { class: 'stat-value num' }, value), h('div', { class: 'stat-sub' }, sub));
}

function onboarding() {
  const step = (n, title, text, action) => h('li', { class: 'step-card' }, h('span', { class: 'step-n' }, n), h('div', h('h3', title), h('p', { class: 'small muted' }, text)), action);
  return h('section', { class: 'card hero' },
    h('h1', 'Find out why a pipeline’s output is wrong'),
    h('p', { class: 'lead muted' }, 'Point Pipeline Autopsy at a database or a folder of files. It learns what normal looks like, watches your datasets, and when something breaks it works upstream to the dataset where the problem started.'),
    h('ol', { class: 'steps' },
      step(1, 'Add a connection', 'Pick a database or folder. Access is read-only.', h('button', { class: 'btn primary', onClick: () => openConnectionDrawer({ onSaved: () => go('/projects/new') }) }, icon('plus', 15), 'Add connection')),
      step(2, 'Map your datasets', 'Choose tables, confirm what each column means, and draw which dataset feeds which.', h('button', { class: 'btn', onClick: () => go('/projects/new') }, 'New project')),
      step(3, 'Watch', 'Health, trends and incidents with root-cause reports appear here.', h('button', { class: 'btn', onClick: openImport }, icon('upload', 15), 'Import a manifest'))));
}

export default async function overview(root, params, ctx) {
  const content = h('div', { class: 'stack', style: { gap: '24px' } });
  mount(root, h('div', { class: 'page-head' }, h('h1', 'Overview'),
    h('div', { class: 'right row' }, h('button', { class: 'btn', onClick: openImport }, icon('upload', 15), 'Import manifest'),
      h('button', { class: 'btn primary', onClick: () => go('/projects/new') }, icon('plus', 15), 'New project'))), content);
  mount(content, skeleton(6, 60));
  let last = '';

  async function load(first) {
    let data;
    try { data = await get('/overview'); } catch (e) { if (first) mount(content, h('div', { class: 'callout bad' }, e.message)); return; }
    const sig = JSON.stringify(data);
    if (sig === last) return;
    last = sig;
    if (!data.projects.length) { mount(content, onboarding()); return; }
    const ps = data.projects;
    const ok = ps.reduce((a, p) => a + p.counts.ok, 0);
    const all = ps.reduce((a, p) => a + p.counts.ok + p.counts.warn + p.counts.fail + p.counts.error, 0);
    const open = data.open_incidents;
    const lastRun = data.recent_runs.find((r) => r.status !== 'running');
    const onRan = () => load(false);
    mount(content,
      h('div', { class: 'stats' },
        stat('Projects', fmtNum(ps.length), plural(ps.reduce((a, p) => a + p.datasets, 0), 'dataset')),
        stat('Open incidents', fmtNum(open.length), open.length ? `worst: ${open[0].severity}` : 'nothing is broken right now', open.length ? 'bad' : 'good'),
        stat('Checks passing', all ? `${ok} of ${all}` : '–', all ? `${Math.round((ok / all) * 100)}% of the latest results` : 'run checks to see results', all && ok === all ? 'good' : ''),
        stat('Last run', lastRun ? ago(lastRun.finished_at || lastRun.started_at) : '–', lastRun ? `${lastRun.project}: ${lastRun.status}` : 'no runs yet')),
      h('section', h('div', { class: 'section-head' }, h('h2', 'Projects')),
        h('div', { class: 'cards' }, ps.map((p) => projectCard({ ...p, onRan })))),
      h('div', { class: 'two-col' },
        h('section', h('div', { class: 'section-head' }, h('h2', 'Open incidents'), h('a', { class: 'right small', href: '#/incidents' }, 'All incidents')),
          open.length ? h('div', { class: 'list' }, open.slice(0, 6).map((i) => incidentItem(i)))
            : h('div', { class: 'card' }, empty({ icon: 'shield', title: 'No open incidents', text: 'When a check fails, the investigation and its root cause show up here.' }))),
        h('section', h('div', { class: 'section-head' }, h('h2', 'Recent runs'), h('a', { class: 'right small', href: '#/runs' }, 'All runs')),
          data.recent_runs.length ? h('div', { class: 'list' }, data.recent_runs.slice(0, 8).map((r) => runItem(r))) : h('div', { class: 'card' }, empty({ icon: 'activity', title: 'No runs yet', text: 'Open a project and run checks.' })))));
    tickTimes(content);
  }
  await load(true);
  ctx.every(10000, () => load(false));
}
