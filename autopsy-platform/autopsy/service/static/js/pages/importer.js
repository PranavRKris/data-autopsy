// Import a manifest file: paste or pick a file, the service creates the connection and the project.
import { post } from '../api.js';
import { go } from '../router.js';
import { changed } from '../shell.js';
import { chip, h, icon, mount } from '../ui.js';
import { busy, field, overlay, toast } from '../widgets.js';

export function openImport() {
  const text = h('textarea', { id: 'imp-yaml', rows: 12, placeholder: 'project: my_project\nconnector: duckdb\nconnection:\n  path_env: DB_PATH\ndatasets:\n  - name: …', spellcheck: 'false', 'aria-label': 'Manifest YAML' });
  const connName = h('input', { id: 'imp-conn', type: 'text', placeholder: 'Optional: defaults to the project name' });
  const result = h('div', { 'aria-live': 'polite' });
  const file = h('input', { type: 'file', accept: '.yaml,.yml,.txt', class: 'sr-only', id: 'imp-file', onChange: (e) => {
    const f = e.target.files[0];
    if (f) f.text().then((t) => { text.value = t; });
  } });
  const dlg = overlay({
    title: 'Import a manifest', kind: 'modal',
    body: h('div', { class: 'stack' },
      h('p', { class: 'muted' }, 'A manifest describes one project: its connection, datasets, roles and lineage. The connection is saved so you can reuse it. Secrets cannot be inside a manifest; it names environment variables instead.'),
      h('div', { class: 'row' }, h('label', { class: 'btn', for: 'imp-file', tabindex: 0, onKeydown: (e) => { if (e.key === 'Enter') file.click(); } }, icon('upload', 15), 'Choose a file…'), file, h('span', { class: 'muted small' }, 'or paste it below')),
      field({ label: 'Manifest YAML', control: text, id: 'imp-yaml' }),
      field({ label: 'Connection name', control: connName, id: 'imp-conn' }), result),
    footer: [h('button', { class: 'btn', onClick: () => dlg.close() }, 'Cancel'),
      h('button', { class: 'btn primary', onClick: (e) => busy(e.currentTarget, run) }, 'Import')],
  });

  async function run() {
    mount(result, null);
    if (!text.value.trim()) { mount(result, h('div', { class: 'callout bad' }, 'Paste a manifest or choose a file first.')); return; }
    try {
      const res = await post('/projects/import', { yaml: text.value, connection_name: connName.value.trim() || undefined });
      const v = res.validation;
      changed();
      mount(result, h('div', { class: `callout ${v.ok ? 'good' : ''}` }, v.ok ? chip('ok', 'Matches the database') : chip('warn', 'Imported, needs attention'),
        h('div', h('b', `Project “${res.project.name}” imported.`), h('div', v.message),
          v.issues.length ? h('ul', { class: 'issues' }, v.issues.map((i) => h('li', h('span', { class: 'tag' }, i.dataset), ' ', i.message))) : null)));
      dlg.setFoot(h('button', { class: 'btn', onClick: () => dlg.close() }, 'Close'),
        h('button', { class: 'btn primary', onClick: () => { dlg.close(); go(`/projects/${encodeURIComponent(res.project.name)}`); } }, 'Open project'));
      toast(`Imported ${res.project.name}`, 'good');
    } catch (e) { mount(result, h('div', { class: 'callout bad', role: 'alert' }, e.message)); }
  }
}
