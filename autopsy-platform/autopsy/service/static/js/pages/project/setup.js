// Setup tab: schedule, baseline, validation, mapping, the manifest file, Bob configuration, delete.
import { del, enc, get, post, put } from '../../api.js';
import { go } from '../../router.js';
import { changed } from '../../shell.js';
import { chip, fmtNum, h, icon, mount, plural, scheduleText, skeleton, timeEl } from '../../ui.js';
import { busy, confirmDialog, copyText, field, switchEl, toast, toastError } from '../../widgets.js';

const INTERVALS = [[5, 'Every 5 minutes'], [15, 'Every 15 minutes'], [60, 'Every hour'], [360, 'Every 6 hours'], [1440, 'Every day']];

function section(title, text, ...body) {
  return h('section', { class: 'card setup-card' }, h('div', { class: 'card-head', style: { marginBottom: '4px' } }, h('h2', title)), text ? h('p', { class: 'muted small', style: { marginBottom: '14px' } }, text) : null, ...body);
}

function codeBlock(text, name) {
  return h('div', { class: 'stack', style: { gap: '8px' } },
    h('div', { class: 'row' }, h('button', { class: 'btn sm', onClick: () => copyText(text, 'Copied to the clipboard') }, icon('copy', 14), 'Copy'), name ? name : null),
    h('pre', { class: 'code', tabindex: 0 }, text));
}

export default async function setup(box, state) {
  const d = state.detail, name = state.name;
  const sch = d.schedule;
  const known = INTERVALS.some(([m]) => m === sch.interval_minutes);
  const sched = { enabled: sch.enabled, minutes: sch.interval_minutes, custom: !known, auto: sch.auto_investigate };
  const intervalSel = h('select', { id: 'sch-int', 'aria-label': 'How often', onChange: (e) => { sched.custom = e.target.value === 'custom'; if (!sched.custom) sched.minutes = Number(e.target.value); paintCustom(); } },
    INTERVALS.map(([m, t]) => h('option', { value: m, selected: !sched.custom && sched.minutes === m }, t)), h('option', { value: 'custom', selected: sched.custom }, 'Custom…'));
  const customIn = h('input', { type: 'number', min: 1, max: 10080, value: sched.minutes, 'aria-label': 'Minutes between runs', style: { maxWidth: '120px' }, onInput: (e) => { sched.minutes = Number(e.target.value); } });
  const customRow = h('div', { class: 'row' });
  const paintCustom = () => mount(customRow, sched.custom ? [customIn, h('span', { class: 'muted small' }, 'minutes')] : null);
  paintCustom();
  const nextRun = h('span', { class: 'small muted' }, sch.enabled && sch.next_run_at ? ['Next run ', timeEl(sch.next_run_at)] : scheduleText(sch));
  const saveSched = h('button', { class: 'btn primary', onClick: (e) => busy(e.currentTarget, async () => {
    try { const r = await put(`/projects/${enc(name)}/schedule`, { enabled: sched.enabled, interval_minutes: sched.minutes, auto_investigate: sched.auto }); toast('Schedule saved', 'good'); mount(nextRun, r.enabled ? ['Next run ', timeEl(r.next_run_at)] : 'Manual only'); changed(); } catch (err) { toastError(err); }
  }) }, 'Save schedule');
  const scheduleCard = section('Schedule', 'Run all checks on a timer. When one fails, an investigation starts by itself and opens an incident.',
    h('div', { class: 'stack' }, switchEl({ checked: sched.enabled, label: 'Run checks on a schedule', onChange: (v) => { sched.enabled = v; } }),
      h('div', { class: 'row wrap' }, intervalSel, customRow),
      switchEl({ checked: sched.auto, label: 'Investigate automatically when a check fails', onChange: (v) => { sched.auto = v; } }),
      h('div', { class: 'row wrap' }, saveSched, nextRun)));

  // baseline
  const since = h('input', { type: 'date', id: 'bl-since' }), until = h('input', { type: 'date', id: 'bl-until' });
  const baseRows = d.baseline ? Object.entries(d.baseline.datasets) : [];
  const learn = h('button', { class: `btn ${d.baseline ? '' : 'primary'}`, onClick: async (e) => {
    if (d.baseline && !await confirmDialog({ title: 'Replace the baseline?', message: 'The current baseline will be replaced by what the data looks like now. Do this only when the data is healthy.', confirmLabel: 'Learn baseline' })) return;
    await busy(e.currentTarget, async () => { try { await post(`/projects/${enc(name)}/baseline`, { since: since.value || undefined, until: until.value || undefined }); toast('Baseline learned', 'good'); await state.reload(); } catch (err) { toastError(err); } });
  } }, d.baseline ? 'Learn again' : 'Learn baseline');
  const baselineCard = section('Baseline', 'What “normal” means for each dataset: columns, empty rates, value ranges and daily row counts.',
    d.baseline ? h('p', { class: 'small' }, chip('ok', 'Learned'), ' ', timeEl(d.baseline.created_at)) : h('div', { class: 'callout', style: { marginBottom: '12px' } }, icon('alert', 16), 'No baseline yet. Volume, profile and freshness checks have little to compare with.'),
    baseRows.length ? h('div', { class: 'table-wrap', style: { marginBottom: '14px' } }, h('table', { class: 't' }, h('thead', h('tr', h('th', 'Dataset'), h('th', 'Rows learned from'), h('th', 'Columns'))),
      h('tbody', baseRows.map(([n, i]) => h('tr', h('td', h('b', n)), h('td', { class: 'num' }, fmtNum(i.rows)), h('td', { class: 'num' }, fmtNum(i.columns))))))) : null,
    h('div', { class: 'callout', style: { marginBottom: '14px' } }, icon('info', 16), 'Learn the baseline while the data is healthy. A baseline learned from broken data makes the breakage look normal. To use only part of the history, choose a period.'),
    h('div', { class: 'row wrap' }, field({ label: 'From (optional)', control: since, id: 'bl-since' }), field({ label: 'Until (optional)', control: until, id: 'bl-until' }), h('div', { style: { alignSelf: 'flex-end' } }, learn)));

  // validate
  const vOut = h('div', { style: { marginTop: '12px' } });
  const validateCard = section('Check the mapping', 'Confirms every mapped column still exists in the database with the right type.',
    h('button', { class: 'btn', onClick: (e) => busy(e.currentTarget, async () => {
      try {
        const r = await post(`/projects/${enc(name)}/validate`);
        mount(vOut, h('div', { class: `callout ${r.ok ? 'good' : 'bad'}`, role: 'status' }, r.ok ? chip('ok', 'Matches') : chip('fail', 'Problems'), h('div', h('b', r.message),
          r.issues.length ? h('ul', { class: 'issues' }, r.issues.map((i) => h('li', chip(i.level === 'error' ? 'fail' : 'skipped', i.level === 'error' ? 'Error' : 'Note'), ' ', h('span', { class: 'tag' }, i.dataset), ' ', i.message))) : null)));
      } catch (err) { toastError(err); }
    }) }, icon('check', 15), 'Validate now'), vOut);

  // mapping
  const mappingCard = section('Mapping', `${plural(d.datasets.length, 'dataset')} in this project. Change which tables are included, what each column means, or the lineage.`,
    h('div', { class: 'table-wrap', style: { marginBottom: '14px' } }, h('table', { class: 't' }, h('thead', h('tr', ['Dataset', 'Source', 'Event time', 'Key', 'Measures', 'Feeds'].map((c) => h('th', c)))),
      h('tbody', d.datasets.map((ds) => h('tr', h('td', h('b', ds.name), ds.business_visible ? h('span', { class: 'tag', style: { marginLeft: '6px' } }, 'visible') : null), h('td', { class: 'mono' }, ds.source),
        h('td', { class: 'mono' }, (ds.roles || {}).event_time || '–'), h('td', { class: 'mono' }, ((ds.roles || {}).key || []).join(', ') || '–'),
        h('td', { class: 'mono' }, ((ds.roles || {}).measure || []).join(', ') || '–'), h('td', (ds.feeds || []).join(', ') || '–')))))),
    h('button', { class: 'btn', onClick: () => go(`/projects/${enc(name)}/edit`) }, icon('edit', 15), 'Edit mapping'));

  const manifestOut = h('div', skeleton(4));
  const bobOut = h('div', skeleton(4));
  get(`/projects/${enc(name)}/manifest`).then((m) => mount(manifestOut, codeBlock(m.yaml, h('a', { class: 'btn sm', href: `api/projects/${enc(name)}/manifest.yaml`, download: `${name}.yaml` }, icon('download', 14), 'Download')))).catch((e) => mount(manifestOut, h('div', { class: 'callout bad' }, e.message)));
  get(`/projects/${enc(name)}/mcp-config`).then((m) => mount(bobOut,
    h('p', { class: 'small muted', style: { marginBottom: '10px' } }, 'Add this MCP server to Bob so it investigates this project with the same tools. Manifest file: ', h('code', m.manifest_path)),
    codeBlock(JSON.stringify({ mcpServers: m.mcpServers }, null, 2)), h('p', { class: 'xs muted', style: { marginTop: '8px' } }, m.note))).catch((e) => mount(bobOut, h('div', { class: 'callout bad' }, e.message)));
  const manifestCard = section('Manifest', 'The plain-text file behind this project. The command line and Bob read the same file.', manifestOut);
  const bobCard = section('Use with Bob', null, bobOut);

  const danger = section('Delete project', 'Removes the project, its run history, incidents and baseline. The connection and your data are not touched.',
    h('button', { class: 'btn danger', onClick: async () => {
      if (!await confirmDialog({ title: `Delete ${name}?`, message: 'This cannot be undone.', confirmLabel: 'Delete project', danger: true, typed: name })) return;
      try { await del(`/projects/${enc(name)}`); toast(`Deleted ${name}`, 'good'); changed(); go('/'); } catch (err) { toastError(err); }
    } }, icon('trash', 15), 'Delete project'));
  danger.classList.add('danger-zone');

  mount(box, h('div', { class: 'setup stack', style: { gap: '20px' } }, scheduleCard, baselineCard, validateCard, mappingCard, manifestCard, bobCard, danger));
}
