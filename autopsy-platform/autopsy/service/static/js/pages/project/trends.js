// Trends tab: daily volume against the learned band, then per-column null rate and median.
import { enc, get } from '../../api.js';
import { lineChart, volumeChart } from '../../charts.js';
import { empty, fmtCompact, fmtNum, fmtPct, h, icon, mount, shortDay, skeleton } from '../../ui.js';

const pctTick = (v) => fmtPct(v, (v * 100) % 1 ? 1 : 0);
import { segmented } from '../../widgets.js';
import { shared } from './shared.js';

const swatch = (cls) => h('span', { class: `sw ${cls}`, 'aria-hidden': 'true' });
const legendItem = (cls, text) => h('span', { class: 'row', style: { gap: '6px' } }, swatch(cls), text);

export default async function trends(box, state) {
  const names = state.detail.datasets.map((d) => d.name);
  let dataset = names.includes(shared.trendDataset) ? shared.trendDataset : (state.detail.datasets.find((d) => d.roles && d.roles.event_time) || state.detail.datasets[0]).name;
  const out = h('div', { class: 'stack', style: { gap: '20px' } });
  const pick = h('select', { 'aria-label': 'Dataset', onChange: (e) => { dataset = e.target.value; shared.trendDataset = dataset; load(); } },
    names.map((n) => h('option', { value: n, selected: n === dataset }, n)));
  mount(box, h('div', { class: 'row wrap filter-bar' }, h('label', { class: 'muted small', for: 'tr-ds' }, 'Dataset'), Object.assign(pick, { id: 'tr-ds' }),
    segmented([[14, '14 days'], [30, '30 days'], [90, '90 days']], shared.trendDays, (v) => { shared.trendDays = v; load(); })), out);

  async function load() {
    mount(out, skeleton(5, 40));
    let t;
    try { t = await get(`/projects/${enc(state.name)}/datasets/${enc(dataset)}/trend?days=${shared.trendDays}`); } catch (e) { mount(out, h('div', { class: 'callout bad' }, e.message)); return; }
    if (!t.event_time) { mount(out, h('div', { class: 'card' }, empty({ icon: 'bar', title: 'No trend for this dataset', text: 'Trends are drawn per day, so the dataset needs an event_time column in its mapping.' }))); return; }
    const vol = t.baseline && t.baseline.volume;
    const band = vol ? { min: vol.min, max: vol.max, median: vol.median } : null;
    const outside = band ? t.volume.filter((v, i) => t.days[i] !== t.today && (v > band.max || v < band.min)).length : 0;
    const volumeCard = h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', 'Rows per day'), outside ? h('span', { class: 'chip s-fail' }, icon('alert', 13), `${outside} ${outside === 1 ? 'day' : 'days'} outside the usual range`) : (band ? h('span', { class: 'chip s-ok' }, 'Inside the usual range') : null)),
      volumeChart({ days: t.days, values: t.volume, today: t.today, band }),
      h('div', { class: 'legend row wrap' }, legendItem('bar', 'Rows'), band ? legendItem('band', `Usual range ${fmtNum(band.min)} to ${fmtNum(band.max)}`) : null,
        band ? legendItem('ref', `Median ${fmtNum(band.median)}`) : null, legendItem('hatch', 'Today, still filling'), legendItem('flag', 'Outside the range')),
      band ? null : h('p', { class: 'small muted' }, 'No baseline yet, so there is no usual range to compare with. Learn one from the Setup tab.'));
    const cols = Object.entries(t.columns);
    const grid = h('div', { class: 'small-multiples' }, cols.map(([col, c]) => {
      const base = (t.baseline && t.baseline.columns && t.baseline.columns[col]) || null;
      const roles = (state.detail.datasets.find((d) => d.name === dataset) || {}).roles || {};
      const numeric = (roles.measure || []).includes(col) && c.points.some((p) => p.median !== null);
      return h('section', { class: 'card' },
        h('div', { class: 'card-head' }, h('h3', { class: 'mono' }, col), h('span', { class: 'tag' }, numeric ? 'measure' : 'required')),
        h('div', { class: 'xs muted' }, 'Share of rows where it is empty'),
        lineChart({ days: t.days, today: t.today, values: c.points.map((p) => p.null_rate), ref: base ? base.null_rate : undefined, fmt: pctTick, tipFmt: (v) => `${fmtPct(v, 1)} empty`, minTop: 0.05,
          flag: base ? (v) => v > base.null_rate + 0.05 : undefined }),
        numeric ? [h('div', { class: 'xs muted', style: { marginTop: '8px' } }, 'Typical value (median)'),
          lineChart({ days: t.days, today: t.today, values: c.points.map((p) => p.median), ref: base && base.median !== undefined ? base.median : undefined, floor: null,
            tipFmt: (v) => `median ${fmtCompact(v)}`, flag: base && base.median ? (v) => v > base.max || v < base.min || v >= base.median * 2 || v <= base.median / 2 : undefined })] : null,
        base ? h('div', { class: 'xs muted' }, 'Dashed line: learned baseline') : null);
    }));
    const table = h('details', { class: 'card tableview' }, h('summary', 'View as a table'),
      h('div', { class: 'table-wrap' }, h('table', { class: 't' }, h('thead', h('tr', h('th', 'Day'), h('th', 'Rows'), cols.map(([c]) => h('th', { class: 'mono' }, `${c} empty`)))),
        h('tbody', t.days.map((d, i) => h('tr', h('td', shortDay(d) + (d === t.today ? ' (today)' : '')), h('td', { class: 'num' }, fmtNum(t.volume[i])),
          cols.map(([, c]) => h('td', { class: 'num' }, c.points[i].null_rate === null ? '–' : fmtPct(c.points[i].null_rate)))))))));
    mount(out, volumeCard, cols.length ? h('h2', { class: 'section-h' }, 'Columns') : null, cols.length ? grid : null, table);
  }
  await load();
}
