// Connections: saved data sources, and the add/edit drawer generated from each connector's field list.
import { del, enc, get, post, put } from '../api.js';
import { changed } from '../shell.js';
import { CONNECTOR_ICON, chip, empty, h, icon, mount, plural, skeleton, timeEl } from '../ui.js';
import { busy, confirmDialog, field, overlay, toast, toastError } from '../widgets.js';

const specOf = (specs, name) => specs.find((c) => c.name === name);

function configSummary(conn, spec) {
  const secretKeys = new Set(conn.secrets_set);
  const rows = [];
  for (const [k, v] of Object.entries(conn.config)) {
    const base = k.endsWith('_env') ? k.slice(0, -4) : k;
    if (k.endsWith('_env') && secretKeys.has(base)) continue;
    const f = spec && spec.fields.find((x) => x.key === base);
    rows.push([f ? f.label : base, k.endsWith('_env') ? `from environment: ${v}` : String(v)]);
  }
  conn.secrets_set.forEach((k) => rows.push([(spec && spec.fields.find((x) => x.key === k) || {}).label || k, 'set (hidden)']));
  return h('dl', { class: 'kv' }, rows.map(([k, v]) => h('div', h('dt', k), h('dd', { class: 'mono' }, v))));
}

export default async function connections(root, params, ctx) {
  const list = h('div', { class: 'cards' }, skeleton(4, 40));
  mount(root, h('div', { class: 'page-head' }, h('h1', 'Connections'),
    h('div', { class: 'right' }, h('button', { class: 'btn primary', onClick: () => openConnectionDrawer({ onSaved: load }) }, icon('plus', 15), 'Add connection'))),
  h('p', { class: 'muted lead conn-lead' }, 'Data sources the platform can read. Access is read-only, and passwords are kept on the server and never shown again.'), list);
  let specs = [];

  async function load() {
    try {
      const [c, k] = await Promise.all([get('/connections'), get('/connectors')]);
      specs = k.connectors;
      if (!c.connections.length) {
        mount(list, h('div', { class: 'card span-all' }, empty({ icon: 'db', title: 'No connections yet', text: 'Add a database or a folder of CSV or Parquet files to start.',
          actions: [h('button', { class: 'btn primary', onClick: () => openConnectionDrawer({ onSaved: load }) }, icon('plus', 15), 'Add connection')] })));
        return;
      }
      mount(list, c.connections.map((conn) => card(conn)));
    } catch (e) { mount(list, h('div', { class: 'callout bad span-all' }, e.message)); }
  }

  function card(conn) {
    const spec = specOf(specs, conn.connector);
    const result = h('div', { class: 'small' }, conn.last_test ? [chip(conn.last_test.ok ? 'ok' : 'fail', conn.last_test.ok ? 'Connected' : 'Failed'), ' ', h('span', { class: 'muted' }, conn.last_test.message, ' · ', timeEl(conn.last_test.at))]
      : h('span', { class: 'muted' }, 'Not tested yet'));
    const testBtn = h('button', { class: 'btn sm', onClick: (e) => busy(e.currentTarget, async () => {
      try { const r = await post(`/connections/${enc(conn.id)}/test`); toast(r.message, r.ok ? 'good' : 'bad'); await load(); } catch (err) { toastError(err); }
    }) }, 'Test');
    return h('article', { class: 'card conn-card' },
      h('div', { class: 'row' }, h('span', { class: 'conn-ico' }, icon(CONNECTOR_ICON[conn.connector] || 'db', 20)),
        h('div', { class: 'grow' }, h('h2', conn.name), h('div', { class: 'muted small' }, spec ? spec.label : conn.connector))),
      configSummary(conn, spec), result,
      h('div', { class: 'small' }, conn.used_by.length ? ['Used by ', conn.used_by.map((p, i) => [i ? ', ' : '', h('a', { href: `#/projects/${enc(p)}` }, p)])] : h('span', { class: 'muted' }, 'Not used by any project yet')),
      h('div', { class: 'card-actions' }, testBtn,
        h('button', { class: 'btn sm', onClick: () => openConnectionDrawer({ connection: conn, onSaved: load }) }, icon('edit', 14), 'Edit'),
        h('button', { class: 'btn sm danger right', 'aria-label': `Delete ${conn.name}`, onClick: async () => {
          if (!await confirmDialog({ title: 'Delete connection?', message: `“${conn.name}” and its stored password will be removed.`, confirmLabel: 'Delete', danger: true })) return;
          try { await del(`/connections/${enc(conn.id)}`); toast('Connection deleted', 'good'); changed(); await load(); } catch (err) { toastError(err); }
        } }, icon('trash', 14), 'Delete')));
  }
  await load();
}

export async function openConnectionDrawer({ connection = null, onSaved } = {}) {
  const dlg = overlay({ title: connection ? 'Edit connection' : 'Add connection', kind: 'drawer', body: skeleton(4) });
  let specs;
  try { specs = (await get('/connectors')).connectors; } catch (e) { dlg.setBody(h('div', { class: 'callout bad' }, e.message)); return dlg; }
  const st = { spec: connection ? specOf(specs, connection.connector) : null, values: {}, env: {}, secrets: {}, name: connection ? connection.name : '', errors: {}, test: null, formError: '' };

  function pickConnector() {
    dlg.setTitle('Add connection');
    dlg.setFoot(null);
    dlg.setBody(h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'What kind of data source is it?'),
      h('div', { class: 'picker' }, specs.map((spec) => {
        const tested = spec.verified.startsWith('Passes');
        return h('button', { class: 'pick', disabled: !spec.available, onClick: () => { st.spec = spec; spec.fields.forEach((f) => { if (f.default !== undefined) st.values[f.key] = String(f.default); }); form(); } },
          h('span', { class: 'conn-ico' }, icon(CONNECTOR_ICON[spec.name] || 'db', 20)), h('b', spec.label), h('span', { class: 'small muted' }, spec.description),
          spec.available ? h('span', { class: `chip ${tested ? 's-ok' : 's-warn'}`, 'data-tip': spec.verified }, tested ? 'Contract-tested' : 'Not run against a live server')
            : h('span', { class: 'small' }, 'Driver missing. Install it with ', h('code', spec.install_hint || 'its driver')));
      }))));
  }

  function collect() {
    const config = {}, secrets = {};
    st.spec.fields.forEach((f) => {
      const v = st.values[f.key];
      if (f.type === 'secret') { if (v) secrets[f.key] = v; return; }
      if (v === undefined || v === '') return;
      if (st.env[f.key]) config[`${f.key}_env`] = v; else config[f.key] = f.type === 'number' ? Number(v) : v;
    });
    return { connector: st.spec.name, config, secrets };
  }

  function control(f) {
    const id = `f-${f.key}`, onEnv = !!st.env[f.key];
    const set = (e) => { st.values[f.key] = e.target.value; };
    let input;
    if (f.type === 'select') {
      input = h('select', { id, onChange: set }, f.options.map((o) => h('option', { value: o, selected: (st.values[f.key] ?? f.default) === o }, o)));
    } else if (f.type === 'secret') {
      const isSet = connection && connection.secrets_set.includes(f.key);
      input = h('input', { id, type: 'password', autocomplete: 'new-password', value: st.values[f.key] ?? '', placeholder: isSet ? 'Set. Leave blank to keep it' : 'Stored on the server, never shown', onInput: set });
    } else {
      input = h('input', { id, type: onEnv ? 'text' : f.type === 'number' ? 'number' : 'text', value: st.values[f.key] ?? '', placeholder: onEnv ? 'ENVIRONMENT_VARIABLE_NAME' : f.placeholder || '', onInput: set, 'aria-invalid': st.errors[f.key] ? 'true' : null });
    }
    const toggle = f.env_ok ? h('button', { type: 'button', class: 'linklike small', onClick: () => { st.env[f.key] = !onEnv; st.values[f.key] = ''; form(); } },
      onEnv ? 'Enter a value instead' : 'Read from an environment variable instead') : null;
    return field({ label: onEnv ? `${f.label} (environment variable name)` : f.label, required: f.required, help: f.type === 'secret' ? 'Write-only: the server keeps it and never sends it back.' : f.help, control: h('div', { class: 'stack', style: { gap: '6px' } }, input, toggle), error: st.errors[f.key], id });
  }

  function testBox() {
    const t = st.test;
    if (!t) return null;
    if (t.pending) return h('div', { class: 'callout info' }, icon('refresh', 16, 'spin'), 'Connecting…');
    return h('div', { class: `callout ${t.ok ? 'good' : 'bad'}`, role: 'status' }, t.ok ? chip('ok', 'Connected') : chip('fail', 'Failed'),
      h('div', { class: 'grow' }, h('div', t.message),
        t.ok && t.datasets.length ? h('ul', { class: 'tables' }, t.datasets.slice(0, 40).map((d) => h('li', h('span', icon('table', 14), d.name), h('span', { class: 'muted' }, plural(d.columns, 'column'))))) : null,
        t.ok && t.datasets.length > 40 ? h('div', { class: 'small muted' }, `and ${t.datasets.length - 40} more`) : null));
  }

  function form() {
    const spec = st.spec;
    dlg.setTitle(connection ? `Edit ${connection.name}` : `Add ${spec.label} connection`);
    const nameInput = h('input', { id: 'f-name', type: 'text', value: st.name, placeholder: 'A name you will recognise', onInput: (e) => { st.name = e.target.value; }, 'aria-invalid': st.errors.name ? 'true' : null });
    const result = h('div', { id: 'test-result' }, testBox());
    dlg.setBody(h('form', { class: 'stack', style: { gap: '18px' }, onSubmit: (e) => { e.preventDefault(); save(); } },
      spec.verified.startsWith('Passes') ? null : h('div', { class: 'callout' }, icon('info', 16), spec.verified),
      field({ label: 'Name', required: true, control: nameInput, error: st.errors.name, id: 'f-name' }),
      spec.fields.map(control), st.formError ? h('div', { class: 'callout bad', role: 'alert' }, st.formError) : null, result));
    const testBtn = h('button', { class: 'btn', type: 'button', onClick: (e) => busy(e.currentTarget, runTest) }, 'Test connection');
    const saveBtn = h('button', { class: 'btn primary', type: 'button', onClick: (e) => busy(e.currentTarget, save) }, connection ? 'Save changes' : 'Save connection');
    dlg.setFoot(connection ? null : h('button', { class: 'btn ghost', type: 'button', onClick: () => { st.spec = null; st.values = {}; st.env = {}; pickConnector(); } }, icon('chevL', 14), 'Back'),
      h('span', { class: 'grow' }), testBtn, saveBtn);
  }

  async function runTest() {
    st.errors = {}; st.formError = '';
    const body = collect();
    st.test = { pending: true };
    mount(document.getElementById('test-result'), testBox());
    try {
      st.test = connection && !Object.keys(body.secrets).length ? await post(`/connections/${enc(connection.id)}/test`) : await post('/connections/test', body);
    } catch (e) { st.test = { ok: false, message: e.message, datasets: [] }; if (e.body.field) st.errors[e.body.field] = e.message; }
    form();
  }

  async function save() {
    st.errors = {}; st.formError = '';
    const body = { ...collect(), name: st.name };
    try {
      const saved = connection ? await put(`/connections/${enc(connection.id)}`, body) : await post('/connections', body);
      toast(`Connection “${saved.name}” saved`, 'good');
      changed();
      dlg.close();
      if (onSaved) onSaved(saved);
    } catch (e) {
      if (e.body && e.body.field) st.errors[e.body.field] = e.message; else if (e.status === 409) st.errors.name = e.message; else st.formError = e.message;
      form();
    }
  }

  if (st.spec) {
    const c = connection.config;
    st.spec.fields.forEach((f) => {
      if (f.key in c) st.values[f.key] = String(c[f.key]);
      else if (`${f.key}_env` in c && f.type !== 'secret') { st.values[f.key] = c[`${f.key}_env`]; st.env[f.key] = true; }
    });
    form();
  } else pickConnector();
  return dlg;
}
