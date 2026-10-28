// Lineage tab: the dataset graph coloured by the latest check results, with a detail panel.
import { enc, get } from '../../api.js';
import { dag } from '../../dag.js';
import { chip, h, icon, label, mount, skeleton, statusIcon, STATUS, TOOLS, timeEl } from '../../ui.js';
import { go } from '../../router.js';
import { shared } from './shared.js';

export default async function lineage(box, state) {
  mount(box, skeleton(5, 40));
  let data;
  try { data = await get(`/projects/${enc(state.name)}/lineage`); } catch (e) { mount(box, h('div', { class: 'callout bad' }, e.message)); return; }
  let selected = shared.lineageNode && data.nodes.some((n) => n.name === shared.lineageNode) ? shared.lineageNode : null;
  const side = h('aside', { class: 'card side' });
  const graph = h('div', { class: 'card graph' });

  function paint() {
    mount(graph, dag({ nodes: data.nodes, edges: data.edges, selected, onSelect: (n) => { selected = n; shared.lineageNode = n; paint(); } }));
    const node = data.nodes.find((n) => n.name === selected);
    if (!node) { mount(side, h('div', { class: 'empty small' }, h('p', 'Select a dataset to see what it holds and how its checks look.'))); return; }
    const checks = state.detail.status.datasets[node.name] || {};
    const roles = node.roles;
    const roleRow = (name, vals) => (vals && vals.length ? h('div', h('dt', name), h('dd', { class: 'chips' }, vals.map((v) => h('span', { class: 'tag mono' }, v)))) : null);
    mount(side,
      h('div', { class: 'row' }, statusIcon(node.status || 'skipped', 20), h('h2', node.name)),
      h('div', { class: 'small muted mono' }, node.source),
      h('div', { class: 'row wrap', style: { gap: '6px', margin: '10px 0' } }, node.status ? chip(node.status) : null,
        node.business_visible ? h('span', { class: 'chip plain' }, icon('eye', 13), 'Business visible') : null,
        node.incident_root ? h('span', { class: 'chip s-fail' }, 'Root of an open incident') : null),
      h('dl', { class: 'kv' }, roleRow('Event time', roles.event_time ? [roles.event_time] : []), roleRow('Key', roles.key), roleRow('Measures', roles.measure), roleRow('Required', roles.required)),
      h('h3', { class: 'section-h' }, 'Latest checks'),
      Object.keys(checks).length ? h('ul', { class: 'findings' }, TOOLS.filter((t) => checks[t]).map((t) => h('li', { class: 'finding' },
        h('div', { class: 'row' }, statusIcon(checks[t].status, 15), h('b', label(t)), h('span', { class: 'right xs muted' }, timeEl(checks[t].at))), h('p', { class: 'small' }, checks[t].summary))))
        : h('p', { class: 'small muted' }, 'No results yet.'),
      h('div', { class: 'card-actions' }, h('button', { class: 'btn sm', onClick: () => { shared.trendDataset = node.name; go(`/projects/${enc(state.name)}/trends`); } }, icon('bar', 14), 'View trends')));
  }
  paint();
  const legend = h('div', { class: 'legend row wrap' },
    ['ok', 'warn', 'fail', 'error', 'skipped'].map((k) => h('span', { class: 'row', style: { gap: '6px' } }, statusIcon(k, 14), STATUS[k].label)),
    h('span', { class: 'row', style: { gap: '6px' } }, icon('eye', 14), 'Business visible'), h('span', { class: 'row', style: { gap: '6px' } }, icon('arrow', 14), 'Feeds'));
  mount(box, h('div', { class: 'split' }, h('div', { class: 'stack' }, graph, legend), side));
}
