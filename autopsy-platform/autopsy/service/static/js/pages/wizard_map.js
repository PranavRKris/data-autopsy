// Wizard steps 3 and 4: what each column means, and which dataset feeds which.
import { computeLevels, dag, wouldCycle } from '../dag.js';
import { fmtNum, h, icon, mount } from '../ui.js';
import { field, switchEl } from '../widgets.js';

export const NAME_RX = /^[A-Za-z0-9_.-]+$/;

export function defaultName(source, taken) {
  const base = (source.split('.').pop() || 'dataset').toLowerCase().replace(/[^A-Za-z0-9_.-]/g, '_');
  let name = base, n = 1;
  while (taken.has(name)) { n += 1; name = `${base}_${n}`; }
  return name;
}

export function applySuggestion(entry, sug) {
  if (!sug || sug.error) { entry.suggestion = null; return; }
  entry.suggestion = sug;
  entry.rows = sug.rows;
  entry.roles = { event_time: sug.event_time || null, key: [...sug.key], measure: [...sug.measure], required: [...sug.required] };
}

const ROLES = [
  { key: 'event_time', label: 'Event time', single: true, kinds: ['temporal'], help: 'When each row happened. Turns on the freshness and volume checks.' },
  { key: 'key', label: 'Key', kinds: ['numeric', 'text'], help: 'Should be different on every row. Turns on the duplicate check.' },
  { key: 'measure', label: 'Measures', kinds: ['numeric'], help: 'Numbers to watch for shifts in size or unit.' },
  { key: 'required', label: 'Required', kinds: null, help: 'Columns that should never be empty.' },
];

const colLabel = (c) => `${c.name}  ·  ${c.type.toLowerCase()}`;

function rolePicker(entry, role, columns, onChange) {
  const note = entry.suggestion && entry.suggestion.notes[role.key];
  const value = entry.roles[role.key];
  const same = entry.suggestion && JSON.stringify(value) === JSON.stringify(role.single ? entry.suggestion[role.key] || null : entry.suggestion[role.key]);
  const allowed = columns.filter((c) => !role.kinds || role.kinds.includes(c.kind));
  const id = `r-${entry.source}-${role.key}`.replace(/[^A-Za-z0-9_-]/g, '_');
  let control;
  if (role.single) {
    control = h('select', { id, onChange: (e) => { entry.roles.event_time = e.target.value || null; onChange(); } },
      h('option', { value: '' }, 'None'), allowed.map((c) => h('option', { value: c.name, selected: c.name === value }, colLabel(c))));
  } else {
    const chosen = value.map((n) => columns.find((c) => c.name === n) || { name: n, type: 'missing' });
    const remaining = allowed.filter((c) => !value.includes(c.name));
    control = h('div', { class: 'stack', style: { gap: '8px' } },
      chosen.length ? h('div', { class: 'chips' }, chosen.map((c) => h('span', { class: 'pill' }, h('span', { class: 'mono' }, c.name), h('span', { class: 'xs muted' }, c.type.toLowerCase()),
        h('button', { type: 'button', 'aria-label': `Remove ${c.name}`, onClick: () => { entry.roles[role.key] = value.filter((n) => n !== c.name); onChange(); } }, icon('x', 12))))) : null,
      remaining.length ? h('select', { id, 'aria-label': `Add a ${role.label.toLowerCase()} column`, onChange: (e) => { if (e.target.value) { entry.roles[role.key] = [...value, e.target.value]; onChange(); } } },
        h('option', { value: '' }, chosen.length ? 'Add another column…' : 'Add a column…'), remaining.map((c) => h('option', { value: c.name }, colLabel(c)))) : h('span', { class: 'xs muted' }, allowed.length ? 'Every suitable column is already chosen.' : 'No suitable column in this table.'));
  }
  return field({ label: role.label, id, control, help: [role.help, note && same ? h('span', { class: 'why' }, ` Suggested: ${note}.`) : null] });
}

export function mappingStep(st, onChange) {
  const wrap = h('div', { class: 'stack', style: { gap: '16px' } });
  const taken = () => new Set(st.datasets.map((d) => d.name));
  st.datasets.forEach((entry) => {
    const table = st.schema.datasets.find((d) => d.name === entry.source);
    const columns = table ? table.columns : [];
    const nameErr = !NAME_RX.test(entry.name) ? 'Use letters, digits, _ - and .'
      : st.datasets.filter((d) => d.name === entry.name).length > 1 ? 'Another dataset already has this name' : '';
    const rerender = () => { mount(card, inner()); onChange && onChange(); };
    const inner = () => [
      h('div', { class: 'row wrap map-head' }, icon('table', 18), h('div', { class: 'grow' }, h('h3', { class: 'mono' }, entry.source),
        h('div', { class: 'xs muted' }, entry.rows !== undefined ? `${fmtNum(entry.rows)} rows · ` : '', `${columns.length} columns`)),
      switchEl({ checked: entry.business_visible, label: 'Business visible', onChange: (v) => { entry.business_visible = v; onChange && onChange(); } })),
      h('div', { class: 'grid2' },
        field({ label: 'Dataset name', required: true, id: `n-${entry.source}`, help: 'How this dataset appears everywhere in the platform.', error: nameErr,
          control: h('input', { id: `n-${entry.source}`, type: 'text', value: entry.name, 'aria-invalid': nameErr ? 'true' : null, onChange: (e) => {
            const old = entry.name, next = e.target.value.trim();
            st.datasets.forEach((d) => { d.feeds = d.feeds.map((f) => (f === old ? next : f)); });
            entry.name = next; rerender();
          } }) }),
        h('div')),
      h('div', { class: 'grid2' }, ROLES.map((r) => rolePicker(entry, r, columns, rerender))),
      h('details', { class: 'adv' }, h('summary', 'Limits for this dataset (optional)'),
        h('div', { class: 'grid2', style: { marginTop: '10px' } },
          field({ label: 'Oldest allowed data, in hours', id: `a-${entry.source}`, help: 'Freshness fails when the newest row is older than this.', control: h('input', { id: `a-${entry.source}`, type: 'number', min: 0, step: 'any', value: entry.expected.max_age_hours ?? '', onChange: (e) => { entry.expected.max_age_hours = e.target.value; } }) }),
          field({ label: 'Most empty values allowed (0 to 1)', id: `z-${entry.source}`, help: 'For example 0.05 allows 5% empty.', control: h('input', { id: `z-${entry.source}`, type: 'number', min: 0, max: 1, step: 'any', value: entry.expected.max_null_rate ?? '', onChange: (e) => { entry.expected.max_null_rate = e.target.value; } }) }))),
    ];
    const card = h('section', { class: 'card map-card' }, inner());
    wrap.appendChild(card);
  });
  void taken;
  return wrap;
}

export const edgesOf = (datasets) => datasets.flatMap((d) => d.feeds.map((to) => ({ from: d.name, to })));

export function lineageStep(st) {
  const preview = h('div', { class: 'card graph' });
  const msg = h('div', { role: 'alert', 'aria-live': 'assertive' });
  const paint = () => {
    const edges = edgesOf(st.datasets), names = st.datasets.map((d) => d.name), level = computeLevels(names, edges);
    mount(preview, dag({ nodes: st.datasets.map((d) => ({ name: d.name, source: d.source, level: level[d.name], status: null, business_visible: d.business_visible })), edges, compact: false }));
  };
  const rows = st.datasets.map((d) => {
    const others = st.datasets.filter((o) => o !== d);
    return h('fieldset', { class: 'card feeds' }, h('legend', h('b', d.name), h('span', { class: 'muted small' }, ' feeds…')),
      others.length ? h('div', { class: 'chips' }, others.map((o) => {
        const input = h('input', { type: 'checkbox', checked: d.feeds.includes(o.name), onChange: (e) => {
          if (e.target.checked) {
            if (wouldCycle(edgesOf(st.datasets), d.name, o.name)) {
              e.target.checked = false;
              mount(msg, h('div', { class: 'callout bad' }, icon('alert', 16), `${d.name} cannot feed ${o.name}: ${o.name} already feeds ${d.name}, directly or through other datasets, and a loop would make “upstream” meaningless.`));
              return;
            }
            d.feeds = [...d.feeds, o.name];
          } else d.feeds = d.feeds.filter((x) => x !== o.name);
          mount(msg, null); paint();
        } });
        return h('label', { class: 'check pill-check' }, input, h('span', o.name));
      })) : h('p', { class: 'small muted' }, 'There is no other dataset to feed.'));
  });
  paint();
  return h('div', { class: 'stack', style: { gap: '16px' } },
    h('p', { class: 'muted' }, 'Tell the platform which dataset feeds which. When something looks wrong, it walks upstream along these links to find where the problem started. Skip this if the datasets are independent.'),
    preview, msg, h('div', { class: 'grid2' }, rows));
}
