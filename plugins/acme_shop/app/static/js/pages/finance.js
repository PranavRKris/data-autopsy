// Finance back office: KPIs, a stacked revenue chart and the last 14 days as a table. Reads the pipeline's mart.
import { get } from "../api.js";
import { channelStyle, legend, stackedBars, swatch } from "../charts.js";
import { dayLabel, exactTime, h, icon, int, money, moneyWhole, poll, relTime, same, skeleton } from "../ui.js";
import { getState, onState } from "../store.js";

const sum = (list) => list.reduce((a, b) => a + b, 0);

function kpi(label, value, sub, extra) {
  return h("div", { class: "kpi" }, h("span", { class: "kpi-label" }, label), h("strong", { class: "kpi-value" }, value),
    h("span", { class: "kpi-sub" }, extra, sub));
}

function delta(now, before) {
  if (!(before > 0)) return null;
  const pct = ((now - before) / before) * 100;
  const up = pct >= 0;
  const text = Math.abs(pct) >= 1000 ? `${int(Math.round(Math.abs(pct)))}%` : `${Math.abs(pct).toFixed(1)}%`;
  return h("span", { class: `delta ${up ? "up" : "down"}` }, icon(up ? "up" : "down", 13), `${text} vs previous 7 days `);
}

export function mount(root) {
  let revenue = null;
  let avgOrder = null;
  let drawn = null;
  let kpiSig = "";
  const stops = [];

  const kpis = h("div", { class: "kpis" }, [1, 2, 3, 4].map(() => h("div", { class: "kpi" }, skeleton(2))));
  const chartHost = h("div", { class: "chart-host" }, skeleton(4, true));
  const legendHost = h("div", { class: "legend-host" });
  const tableHost = h("div", { class: "table-wrap" }, h("div", { class: "empty" }, skeleton(3)));
  const foot = h("p", { class: "footnote" });

  root.replaceChildren(
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Finance"), h("p", {}, "Revenue by day and sales channel, from the daily revenue report."))),
    kpis,
    h("section", { class: "card chart-card", "aria-labelledby": "chart-h" },
      h("div", { class: "card-head" }, h("h2", { id: "chart-h" }, "Daily revenue"), legendHost), chartHost),
    h("section", { class: "table-section", "aria-labelledby": "table-h" }, h("h2", { id: "table-h", class: "office-title" }, "Last 14 days"), tableHost),
    foot);

  function paintKpis(state) {
    const days = revenue.days;
    const last7 = days.slice(-7);
    const prior7 = days.slice(-14, -7);
    const rev7 = sum(last7.map((d) => d.total));
    const byChannel = {};
    last7.forEach((d) => Object.entries(d.by_channel).forEach(([c, v]) => { byChannel[c] = (byChannel[c] || 0) + v; }));
    const best = Object.entries(byChannel).sort((a, b) => b[1] - a[1])[0];
    const sig = JSON.stringify([rev7, best, avgOrder, state && state.counts.orders_today, sum(prior7.map((d) => d.total))]);
    if (sig === kpiSig) return;
    kpiSig = sig;
    kpis.replaceChildren(
      kpi("Revenue, last 7 days", moneyWhole(rev7), "", delta(rev7, sum(prior7.map((d) => d.total)))),
      kpi("Orders today", state ? int(state.counts.orders_today) : "—", "placed since midnight"),
      kpi("Best channel", best ? best[0] : "—", best ? `${moneyWhole(best[1])} in 7 days` : "no revenue yet"),
      kpi("Average order value", avgOrder == null ? "—" : money(avgOrder), "latest 100 orders"));
  }

  function paintChart() {
    const key = { days: revenue.days, channels: revenue.channels, w: chartHost.clientWidth };
    if (same(drawn, key)) return;
    drawn = key;
    legendHost.replaceChildren(legend(revenue.channels));
    stackedBars(chartHost, revenue);
    const cols = revenue.channels;
    tableHost.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Day"), cols.map((c) => h("th", { class: "num" }, h("span", { class: "th-chan" }, swatch(channelStyle(c, cols)), c))), h("th", { class: "num" }, "Total"))),
      h("tbody", {}, revenue.days.slice().reverse().map((d) => h("tr", {},
        h("td", {}, dayLabel(d.day, true)),
        cols.map((c) => h("td", { class: "num" }, d.by_channel[c] ? money(d.by_channel[c]) : h("span", { class: "muted" }, "—"))),
        h("td", { class: "num strong" }, d.total ? money(d.total) : h("span", { class: "muted" }, "—")))))));
  }

  function paintFoot(state) {
    const p = state && state.pipeline;
    foot.replaceChildren(p && p.last_run_at
      ? h("span", {}, "Rebuilt from the pipeline output; last run ", h("time", { title: exactTime(p.last_run_at) }, relTime(p.last_run_at)), ".")
      : "Rebuilt from the pipeline output; it has not run since the shop started.");
  }

  function paintEmpty() {
    drawn = null;
    kpiSig = "";
    kpis.replaceChildren();
    legendHost.replaceChildren();
    chartHost.replaceChildren(h("div", { class: "empty" }, h("h3", {}, "No reports yet"),
      h("p", {}, "The daily revenue report has not been built. Run the pipeline from Operations."),
      h("a", { class: "btn primary", href: "#/operations", style: "margin-top:12px" }, "Go to Operations")));
    tableHost.replaceChildren();
  }

  async function load() {
    try {
      const [rev, orders] = await Promise.all([get("/api/revenue?days=14"), get("/api/orders?limit=100")]);
      revenue = rev;
      avgOrder = orders.orders.length ? sum(orders.orders.map((o) => o.amount)) / orders.orders.length : null;
      if (!rev.built || !rev.days.length) paintEmpty();
      else { paintKpis(getState()); paintChart(); }
      paintFoot(getState());
    } catch (err) {
      if (!revenue) chartHost.replaceChildren(h("div", { class: "page-error" }, icon("warn", 18), err.message));
    }
  }

  stops.push(poll(load, 5000));
  stops.push(onState((state) => { if (revenue && revenue.built) paintKpis(state); paintFoot(state); }));
  let resizeTimer = null;
  const onResize = () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (revenue && revenue.built) paintChart(); }, 150); };
  window.addEventListener("resize", onResize);

  return () => { stops.forEach((s) => (typeof s === "function" ? s() : null)); window.removeEventListener("resize", onResize); clearTimeout(resizeTimer); };
}
