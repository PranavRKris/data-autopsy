// New project wizard (also used to edit a project's mapping): connection, tables, mapping, lineage, review, launch.
import { enc, get, post, put } from '../api.js';
import { dag, computeLevels } from '../dag.js';
import { go } from '../router.js';
import { changed } from '../shell.js';
import { CONNECTOR_ICON, chip, empty, fmtNum, h, icon, mount, plural, skeleton, statusIcon, toYaml } from '../ui.js';
import { busy, field, toast, toastError } from '../widgets.js';
import { openConnectionDrawer } from './connections.js';
import { openImport } from './importer.js';
import { NAME_RX, applySuggestion, defaultName, edgesOf, lineageStep, mappingStep } from './wizard_map.js';

const num = (v) => (v === '' || v === undefined || v === null || Number.isNaN(Number(v)) ? undefined : Number(v));

export function payloadOf(st) {
  const thresholds = {};
  Object.entries(st.thresholds).forEach(([k, v]) => { if (num(v) !== undefined) thresholds[k] = num(v); });
  return {
    name: st.name, connection_id: st.connectionId, thresholds,
    datasets: st.datasets.map((d) => ({
      name: d.name, source: d.source, business_visible: d.business_visible, feeds: d.feeds,
      roles: { event_time: d.roles.event_time || undefined, key: d.roles.key, measure: d.roles.measure, required: d.roles.required },
      expected: { ...(d.expectedRaw || {}), max_age_hours: num(d.expected.max_age_hours), max_null_rate: num(d.expected.max_null_rate) },
    })),
  };
}

export default async function wizard(root, params, ctx) {
  const editing = Boolean(params.name);
  const STEPS = editing ? ['Tables', 'Mapping', 'Lineage', 'Review'] : ['Connection', 'Tables', 'Mapping', 'Lineage', 'Review'];
  const st = { name: params.name || '', connectionId: null, connections: [], schema: null, selected: new Set(), datasets: [], thresholds: {}, since: '', until: '',
    peek: {}, issues: [], error: '', suggestionsLoaded: new Set(), search: '' };
  let step = 0;
  const stepper = h('ol', { class: 'stepper', 'aria-label': 'Progress' });
  const body = h('div', { class: 'wiz-body' });
  const foot = h('div', { class: 'wiz-foot' });
  mount(root, h('div', { class: 'page-head' }, h('h1', editing ? `Edit mapping: ${params.name}` : 'New project'),
    editing ? null : h('div', { class: 'right' }, h('button', { class: 'btn', onClick: openImport }, icon('upload', 15), 'Import a manifest instead'))), stepper, body, foot);
  mount(body, skeleton(5, 40));

  if (editing) {
    try {
      const d = await get(`/projects/${enc(params.name)}`);
      st.connectionId = d.connection.id;
      st.thresholds = { ...d.thresholds };
      st.datasets = d.datasets.map((x) => ({ source: x.source, name: x.name, business_visible: !!x.business_visible, feeds: [...(x.feeds || [])],
        roles: { event_time: (x.roles || {}).event_time || null, key: [...((x.roles || {}).key || [])], measure: [...((x.roles || {}).measure || [])], required: [...((x.roles || {}).required || [])] },
        expected: { max_age_hours: (x.expected || {}).max_age_hours ?? '', max_null_rate: (x.expected || {}).max_null_rate ?? '' },
        expectedRaw: (x.expected || {}).value_range ? { value_range: x.expected.value_range } : undefined, suggestion: null }));
      d.datasets.forEach((x) => st.selected.add(x.source));
      st.datasets.forEach((x) => st.suggestionsLoaded.add(x.source));
    } catch (e) { mount(body, h('div', { class: 'callout bad' }, e.message)); return; }
  } else {
    try { st.connections = (await get('/connections')).connections; } catch (e) { mount(body, h('div', { class: 'callout bad' }, e.message)); return; }
  }

  const key = () => STEPS[step];
  const go2 = (n) => { step = Math.max(0, Math.min(STEPS.length - 1, n)); paint(); };
  function paintStepper() {
    mount(stepper, STEPS.map((t, i) => h('li', { class: i < step ? 'done' : i === step ? 'now' : '', 'aria-current': i === step ? 'step' : null },
      h('button', { type: 'button', disabled: i > step, onClick: () => go2(i) }, h('span', { class: 'dotn' }, i < step ? icon('check', 13) : i + 1), h('span', { class: 'lbl' }, t)))));
  }

  // ---- step: connection ----
  function stepConnection() {
    const cards = st.connections.map((c) => h('label', { class: `pick sel ${st.connectionId === c.id ? 'on' : ''}` },
      h('input', { type: 'radio', name: 'conn', class: 'sr-only', checked: st.connectionId === c.id, onChange: () => { st.connectionId = c.id; st.schema = null; st.selected.clear(); st.datasets = []; paint(); } }),
      h('span', { class: 'conn-ico' }, icon(CONNECTOR_ICON[c.connector] || 'db', 20)), h('b', c.name), h('span', { class: 'small muted' }, c.connector),
      c.last_test ? chip(c.last_test.ok ? 'ok' : 'fail', c.last_test.ok ? 'Connected' : 'Failed') : h('span', { class: 'xs muted' }, 'Not tested')));
    const add = () => openConnectionDrawer({ onSaved: async (saved) => { st.connections = (await get('/connections')).connections; st.connectionId = saved.id; st.schema = null; paint(); } });
    return st.connections.length ? h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'Where does the data live?'), h('div', { class: 'picker' }, cards, h('button', { class: 'pick add', type: 'button', onClick: add }, icon('plus', 20), h('b', 'Add a connection'), h('span', { class: 'small muted' }, 'Test and save a new data source'))))
      : empty({ icon: 'db', title: 'Add a connection first', text: 'A connection tells the platform where to read from. It is saved, so you only do this once per data source.', actions: [h('button', { class: 'btn primary', onClick: add }, icon('plus', 15), 'Add connection')] });
  }

  // ---- step: tables ----
  async function loadSchema() {
    if (st.schema) return;
    try { st.schema = await get(`/connections/${enc(st.connectionId)}/schema`); } catch (e) { st.error = e.message; }
  }
  function stepTables() {
    if (!st.schema) { loadSchema().then(paint); return skeleton(6, 36); }
    if (st.error) return h('div', { class: 'callout bad' }, st.error);
    const list = h('div', { class: 'list tables-pick' });
    const paintList = () => {
      const q = st.search.toLowerCase();
      const shown = st.schema.datasets.filter((d) => d.name.toLowerCase().includes(q));
      mount(list, shown.length ? shown.map((d) => {
        const peek = h('div', { class: 'peek', hidden: !st.peek[d.name] });
        const fill = () => { const p = st.peek[d.name]; mount(peek, !p ? null : p.loading ? skeleton(3, 14) : p.error ? h('div', { class: 'small err' }, p.error) : h('div', { class: 'table-wrap' }, h('table', { class: 't' }, h('thead', h('tr', p.columns.map((c) => h('th', c)))), h('tbody', p.rows.map((r) => h('tr', p.columns.map((c) => h('td', { class: 'mono' }, r[c] === null ? '∅' : String(r[c])))))))));
          peek.hidden = !p; };
        fill();
        return h('div', { class: 'tbl-row' }, h('div', { class: 'row' },
          h('label', { class: 'check grow' }, h('input', { type: 'checkbox', checked: st.selected.has(d.name), onChange: (e) => { if (e.target.checked) st.selected.add(d.name); else st.selected.delete(d.name); paintCount(); } }),
            h('span', { class: 'mono' }, d.name), h('span', { class: 'muted small' }, plural(d.columns.length, 'column'))),
          h('button', { class: 'btn sm ghost', type: 'button', 'aria-expanded': String(!!st.peek[d.name]), onClick: async () => {
            if (st.peek[d.name]) { delete st.peek[d.name]; fill(); return; }
            st.peek[d.name] = { loading: true }; fill();
            try { const r = await post(`/connections/${enc(st.connectionId)}/sample`, { source: d.name, n: 5 }); st.peek[d.name] = { columns: r.columns, rows: r.rows }; } catch (e) { st.peek[d.name] = { error: e.message }; }
            fill();
          } }, icon('eye', 14), 'Peek')), peek);
      }) : h('p', { class: 'muted', style: { padding: '16px' } }, 'No table matches the search.'));
    };
    const count = h('span', { class: 'muted small', 'aria-live': 'polite' });
    const paintCount = () => { count.textContent = `${st.selected.size} selected`; nextBtn && (nextBtn.disabled = !st.selected.size); };
    const search = h('input', { type: 'search', placeholder: 'Search tables…', 'aria-label': 'Search tables', value: st.search, onInput: (e) => { st.search = e.target.value; paintList(); } });
    paintList(); paintCount();
    return h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'Choose the tables to watch. Each becomes a dataset.'),
      h('div', { class: 'row wrap' }, h('div', { class: 'grow', style: { maxWidth: '360px' } }, search), count,
        h('button', { class: 'btn sm ghost', onClick: () => { st.schema.datasets.forEach((d) => st.selected.add(d.name)); paintList(); paintCount(); } }, 'Select all'),
        h('button', { class: 'btn sm ghost', onClick: () => { st.selected.clear(); paintList(); paintCount(); } }, 'Clear')),
      st.schema.truncated ? h('div', { class: 'callout info' }, icon('info', 16), `Showing the first ${st.schema.datasets.length} of ${st.schema.total} tables.`) : null,
      h('div', { class: 'card flat' }, list));
  }

  // ---- step: mapping ----
  function syncDatasets() {
    const keep = st.datasets.filter((d) => st.selected.has(d.source));
    const have = new Set(keep.map((d) => d.source));
    st.schema.datasets.filter((t) => st.selected.has(t.name) && !have.has(t.name)).forEach((t) => {
      keep.push({ source: t.name, name: defaultName(t.name, new Set(keep.map((d) => d.name))), business_visible: false, feeds: [],
        roles: { event_time: null, key: [], measure: [], required: [] }, expected: { max_age_hours: '', max_null_rate: '' }, suggestion: null });
    });
    st.datasets = keep;
  }
  function stepMapping() {
    syncDatasets();
    const need = st.datasets.filter((d) => !st.suggestionsLoaded.has(d.source)).map((d) => d.source);
    if (need.length) {
      post(`/connections/${enc(st.connectionId)}/suggest`, { sources: need }).then((r) => {
        need.forEach((src) => { const e = st.datasets.find((d) => d.source === src); if (e) applySuggestion(e, r.suggestions[src]); st.suggestionsLoaded.add(src); });
        if (key() === 'Mapping') paint();
      }).catch((e) => { need.forEach((s) => st.suggestionsLoaded.add(s)); toastError(e); if (key() === 'Mapping') paint(); });
      return h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'Reading each table to suggest what its columns mean…'), skeleton(6, 36));
    }
    return h('div', { class: 'stack', style: { gap: '16px' } }, h('p', { class: 'muted' }, 'Confirm what each column means. The suggestions come from column types and the data itself; change anything that is wrong.'),
      h('div', { class: 'callout info' }, icon('info', 16), 'These roles switch checks on: an event time enables freshness and volume, a key enables duplicates, measures and required columns enable the profile check.'),
      mappingStep(st));
  }

  // ---- step: review ----
  function stepReview() {
    const computeProblems = () => {
      const out = [];
      if (!editing && !NAME_RX.test(st.name)) out.push('Give the project a name (letters, digits, _ - and .).');
      const names = st.datasets.map((d) => d.name);
      st.datasets.forEach((d) => { if (!NAME_RX.test(d.name)) out.push(`Dataset “${d.name}” needs a valid name.`); });
      if (new Set(names).size !== names.length) out.push('Dataset names must be different from each other.');
      return out;
    };
    const nameIn = h('input', { id: 'pj-name', type: 'text', value: st.name, readonly: editing, placeholder: 'A short name for this project', onInput: (e) => { st.name = e.target.value.trim(); refresh(); } });
    const th = (k, label, help, step = 'any') => field({ label, help, id: `th-${k}`, control: h('input', { id: `th-${k}`, type: 'number', min: 0, step, value: st.thresholds[k] ?? '', onInput: (e) => { st.thresholds[k] = e.target.value; refresh(); } }) });
    const yaml = h('pre', { class: 'code' });
    const issues = h('div');
    const probs = h('ul', { class: 'issues' });
    function refresh() {
      const p = payloadOf(st);
      yaml.textContent = toYaml({ project: p.name || '(name)', datasets: p.datasets.map((d) => ({ name: d.name, source: d.source, roles: d.roles, business_visible: d.business_visible || undefined, feeds: d.feeds })), thresholds: p.thresholds });
      mount(probs, computeProblems().map((x) => h('li', x)));
      const bad = (!editing && !NAME_RX.test(st.name));
      if (nextBtn) nextBtn.disabled = bad;
    }
    mount(issues, st.issues.length ? h('div', { class: 'callout bad', role: 'alert' }, icon('alert', 18), h('div', h('b', st.error), h('ul', { class: 'issues' }, st.issues.map((i) => h('li', chip(i.level === 'error' ? 'fail' : 'skipped', i.level === 'error' ? 'Error' : 'Note'), ' ', h('span', { class: 'tag' }, i.dataset), ' ', i.message))),
      h('button', { class: 'btn sm', onClick: () => go2(STEPS.indexOf('Mapping')) }, 'Fix the mapping'))) : st.error ? h('div', { class: 'callout bad', role: 'alert' }, st.error) : null);
    setTimeout(refresh, 0);
    return h('div', { class: 'stack', style: { gap: '18px' } },
      issues,
      h('div', { class: 'grid2' }, field({ label: editing ? 'Project' : 'Project name', required: !editing, id: 'pj-name', control: nameIn, help: editing ? 'A project keeps its name.' : 'Used in the address of the project page and in its manifest file.' }), h('div')),
      h('details', { class: 'card adv', open: Object.keys(st.thresholds).length > 0 }, h('summary', 'Limits for the whole project (optional)'),
        h('p', { class: 'small muted', style: { margin: '8px 0 12px' } }, 'Leave empty to use what was learned from the baseline.'),
        h('div', { class: 'grid2' }, th('max_age_hours', 'Oldest allowed data, in hours', 'Freshness fails beyond this.'), th('max_null_rate', 'Most empty values allowed (0 to 1)', 'Applies to every watched column.'),
          th('volume_change_ratio', 'Allowed change in daily rows', 'For example 0.5 allows half or double.'), th('median_shift_factor', 'Allowed shift in typical values', 'For example 5 flags a value five times its normal size.'))),
      editing ? null : h('div', { class: 'card' }, h('h2', { class: 'section-h', style: { marginTop: 0 } }, 'Baseline'),
        h('div', { class: 'callout', style: { marginBottom: '12px' } }, icon('alert', 16), 'After the project is created, the platform learns what “normal” looks like from the data as it is now. Make sure the data is healthy; a baseline learned from broken data makes the breakage look normal. Limit it to a healthy period if you know one.'),
        h('div', { class: 'grid2' }, field({ label: 'From (optional)', id: 'bl-s', control: h('input', { id: 'bl-s', type: 'date', value: st.since, onChange: (e) => { st.since = e.target.value; } }) }),
          field({ label: 'Until (optional)', id: 'bl-u', control: h('input', { id: 'bl-u', type: 'date', value: st.until, onChange: (e) => { st.until = e.target.value; } }) }))),
      h('details', { class: 'card adv' }, h('summary', `What will be saved (${plural(st.datasets.length, 'dataset')})`), yaml), probs);
  }

  // ---- launch ----
  async function launch() {
    const items = [['create', 'Project created'], ['baseline', 'Learning the baseline'], ['checks', 'Running the first checks']];
    const state = Object.fromEntries(items.map(([k]) => [k, 'pending']));
    const msgs = {};
    const view = h('div', { class: 'launch card' });
    const paintL = () => mount(view, h('h2', 'Setting up your project'), h('ul', { class: 'launch-list' }, items.map(([k, label]) => h('li', { class: state[k] },
      statusIcon(state[k] === 'done' ? 'ok' : state[k] === 'running' ? 'running' : state[k] === 'failed' ? 'fail' : 'skipped', 20), h('div', h('b', label), msgs[k] ? h('div', { class: 'small muted' }, msgs[k]) : null)))));
    mount(body, view); mount(foot, null); paintL();
    const open = () => go(`/projects/${enc(st.name)}`);
    state.create = 'done'; paintL();
    state.baseline = 'running'; paintL();
    try { await post(`/projects/${enc(st.name)}/baseline`, { since: st.since || undefined, until: st.until || undefined }); state.baseline = 'done'; msgs.baseline = 'Normal values and daily volumes recorded.'; }
    catch (e) { state.baseline = 'failed'; msgs.baseline = `${e.message} You can learn it later from the Setup tab.`; }
    paintL();
    state.checks = 'running'; paintL();
    try { const r = await post(`/projects/${enc(st.name)}/runs`, { kind: 'monitor' }); state.checks = 'done'; msgs.checks = r.summary; }
    catch (e) { state.checks = 'failed'; msgs.checks = e.message; }
    paintL(); changed();
    const failed = Object.values(state).includes('failed');
    mount(foot, h('span', { class: 'grow' }), h('button', { class: 'btn primary', onClick: open }, 'Open project', icon('arrow', 15)));
    if (!failed) setTimeout(() => { if (ctx.isCurrent()) open(); }, 1500);
  }

  async function submit() {
    st.error = ''; st.issues = [];
    const p = payloadOf(st);
    try {
      if (editing) {
        await put(`/projects/${enc(params.name)}`, { connection_id: p.connection_id, datasets: p.datasets, thresholds: p.thresholds });
        toast('Mapping saved. Learn the baseline again if columns or tables changed.', 'good'); changed(); go(`/projects/${enc(params.name)}/setup`);
      } else {
        await post('/projects', p); changed(); await launch();
      }
    } catch (e) {
      st.error = e.message; st.issues = (e.body && e.body.issues) || [];
      paint();
    }
  }

  let nextBtn = null;
  function paint() {
    paintStepper();
    const k = key();
    const view = { Connection: stepConnection, Tables: stepTables, Mapping: stepMapping, Lineage: () => lineageStep(st), Review: stepReview }[k]();
    mount(body, h('div', { class: 'wiz-card' }, view));
    const last = step === STEPS.length - 1;
    nextBtn = h('button', { class: 'btn primary', onClick: (e) => (last ? busy(e.currentTarget, submit) : go2(step + 1)) },
      last ? (editing ? 'Save mapping' : 'Create project') : 'Continue', last ? null : icon('arrow', 15));
    nextBtn.disabled = (k === 'Connection' && !st.connectionId) || (k === 'Tables' && !st.selected.size) || (k === 'Mapping' && st.datasets.some((d) => !NAME_RX.test(d.name)));
    mount(foot, step > 0 ? h('button', { class: 'btn', onClick: () => go2(step - 1) }, icon('chevL', 15), 'Back') : h('a', { class: 'btn ghost', href: editing ? `#/projects/${enc(params.name)}/setup` : '#/' }, 'Cancel'),
      h('span', { class: 'grow' }), nextBtn);
    if (k === 'Review') nextBtn.disabled = !editing && !NAME_RX.test(st.name);
  }
  paint();
}
