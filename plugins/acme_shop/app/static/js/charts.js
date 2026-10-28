// Stacked daily bars drawn in SVG. Channels are told apart by colour AND texture; "unknown" gets its own loud treatment.
import { dayLabel, h, money, moneyWhole, s } from "./ui.js";

const KNOWN = {
  web: { fill: "#1b6560", texture: null },
  mobile: { fill: "#d08a14", texture: "pat-stripes" },
  store: { fill: "#5666ad", texture: "pat-dots" },
};
const SPARE = [{ fill: "#8a4f9e", texture: "pat-stripes" }, { fill: "#4d8a35", texture: "pat-dots" }];
const UNKNOWN = { fill: "#fbdcd8", texture: "pat-cross", stroke: "#b3261e" };

export function channelStyle(name, all) {
  if (name === "unknown") return UNKNOWN;
  if (KNOWN[name]) return KNOWN[name];
  const others = all.filter((c) => c !== "unknown" && !KNOWN[c]);
  return SPARE[others.indexOf(name) % SPARE.length];
}

export function swatch(style) {
  return s("svg", { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true", class: "swatch" },
    s("rect", { x: 1, y: 1, width: 14, height: 14, rx: 3, fill: style.fill, stroke: style.stroke || "none", "stroke-width": 1.5 }),
    style.texture ? s("rect", { x: 1, y: 1, width: 14, height: 14, rx: 3, fill: `url(#${style.texture})` }) : null);
}

export function niceTicks(max, want = 5) {
  if (!(max > 0)) return { step: 1, top: 4, ticks: [0, 1, 2, 3, 4] };
  const raw = max / (want - 1);
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((c) => c >= raw);
  const top = Math.ceil(max / step) * step;
  return { step, top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) };
}

function axisLabel(v) {
  if (v >= 1e6) return `$${+(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${+(v / 1e3).toFixed(v % 1000 ? 1 : 0)}k`;
  return `$${v}`;
}

export function legend(channels) {
  return h("ul", { class: "legend", "aria-label": "Channels" }, channels.map((c) =>
    h("li", {}, swatch(channelStyle(c, channels)), h("span", {}, c))));
}

export function stackedBars(host, { days, channels }) {
  host.replaceChildren();
  const width = Math.max(host.clientWidth, 300);
  const compact = width < 560;
  const height = compact ? 250 : 300;
  const pad = { l: compact ? 44 : 56, r: 12, t: 14, b: 30 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const { top, ticks } = niceTicks(Math.max(...days.map((d) => d.total), 0));
  const y = (v) => pad.t + innerH - (v / top) * innerH;
  const slot = innerW / days.length;
  const barW = Math.max(6, Math.min(40, slot * 0.66));
  const order = channels.slice();

  const tip = h("div", { class: "chart-tip", role: "tooltip", hidden: true });
  const svg = s("svg", { width, height, viewBox: `0 0 ${width} ${height}`, class: "chart", role: "group",
    "aria-label": `Revenue per day for the last ${days.length} days, stacked by channel` });

  ticks.forEach((t) => {
    svg.append(
      s("line", { x1: pad.l, x2: width - pad.r, y1: y(t), y2: y(t), class: "grid" }),
      s("text", { x: pad.l - 8, y: y(t) + 4, "text-anchor": "end", class: "axis" }, axisLabel(t)));
  });

  const showTip = (group, d, cx) => {
    tip.replaceChildren(
      h("strong", {}, dayLabel(d.day, true)),
      d.total > 0
        ? h("ul", {}, order.filter((c) => d.by_channel[c]).map((c) => h("li", {}, swatch(channelStyle(c, channels)), h("span", {}, c), h("b", {}, money(d.by_channel[c])))))
        : h("p", {}, "No revenue recorded"),
      d.total > 0 ? h("div", { class: "tip-total" }, h("span", {}, "Total"), h("b", {}, money(d.total))) : null);
    tip.hidden = false;
    const w = tip.offsetWidth;
    tip.style.left = `${Math.min(Math.max(cx - w / 2, 4), width - w - 4)}px`;
    tip.style.top = `${Math.max(y(d.total) - tip.offsetHeight - 10, 0)}px`;
    host.querySelectorAll("g.day.active").forEach((g) => g.classList.remove("active"));
    group.classList.add("active");
  };
  const hideTip = () => { tip.hidden = true; host.querySelectorAll("g.day.active").forEach((g) => g.classList.remove("active")); };

  days.forEach((d, i) => {
    const cx = pad.l + slot * i + slot / 2;
    const group = s("g", { class: "day", tabindex: 0, role: "img",
      "aria-label": d.total > 0 ? `${dayLabel(d.day, true)}: ${money(d.total)} total` : `${dayLabel(d.day, true)}: no revenue recorded` });
    group.append(s("rect", { x: cx - slot / 2, y: pad.t, width: slot, height: innerH, class: "hit" }));
    if (d.total > 0) {
      let acc = 0;
      order.forEach((c) => {
        const v = d.by_channel[c] || 0;
        if (!v) return;
        const style = channelStyle(c, channels);
        const y1 = y(acc + v);
        const hgt = y(acc) - y1;
        group.append(s("rect", { x: cx - barW / 2, y: y1, width: barW, height: Math.max(hgt, 1), fill: style.fill, stroke: style.stroke || "#fff", "stroke-width": style.stroke ? 1.2 : 0.8 }));
        if (style.texture) group.append(s("rect", { x: cx - barW / 2, y: y1, width: barW, height: Math.max(hgt, 1), fill: `url(#${style.texture})` }));
        acc += v;
      });
    } else {
      group.append(s("line", { x1: cx - barW / 2, x2: cx + barW / 2, y1: y(0) - 1, y2: y(0) - 1, class: "gap" }),
        s("text", { x: cx, y: y(0) - 8, "text-anchor": "middle", class: "gap-text" }, "–"));
    }
    if (compact ? i % 2 === (days.length - 1) % 2 : true) {
      svg.append(s("text", { x: cx, y: height - 9, "text-anchor": "middle", class: "axis" }, dayLabel(d.day)));
    }
    group.addEventListener("pointerenter", () => showTip(group, d, cx));
    group.addEventListener("pointerleave", hideTip);
    group.addEventListener("focus", () => showTip(group, d, cx));
    group.addEventListener("blur", hideTip);
    group.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
    svg.append(group);
  });
  svg.append(s("line", { x1: pad.l, x2: width - pad.r, y1: y(0), y2: y(0), class: "baseline" }));
  host.append(svg, tip);
}

export { moneyWhole };
