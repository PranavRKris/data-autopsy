// DOM helpers. Text is only ever added as text nodes, so API data cannot inject markup.
const SVG = "http://www.w3.org/2000/svg";

function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  return el;
}

export function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  return el;
}

const ICONS = {
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  warn: ["M12 4l9 16H3z", "M12 10v4", "M12 17v.5"],
  dash: ["M7 12h10"],
  cart: ["M3 4h2l2.4 11h10.2L20 8H6.2", "M9 20.2v.01", "M17 20.2v.01"],
  plus: ["M12 5v14", "M5 12h14"],
  minus: ["M5 12h14"],
  external: ["M14 4h6v6", "M20 4l-9 9", "M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"],
  play: ["M8 5l11 7-11 7z"],
  refresh: ["M20 11a8 8 0 10-2.3 5.7", "M20 4v7h-7"],
  undo: ["M9 14L4 9l5-5", "M4 9h10a6 6 0 010 12h-3"],
  bolt: ["M13 3L5 14h6l-1 7 8-11h-6z"],
  clock: ["M12 3a9 9 0 100 18 9 9 0 000-18", "M12 7v5l3 2"],
  chevron: ["M9 6l6 6-6 6"],
  up: ["M12 19V6", "M6 12l6-6 6 6"],
  down: ["M12 5v13", "M6 12l6 6 6-6"],
};

export function icon(name, size = 18, label) {
  return s(
    "svg",
    {
      viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": 2,
      "stroke-linecap": "round", "stroke-linejoin": "round", class: "icon",
      "aria-hidden": label ? null : "true", role: label ? "img" : null, "aria-label": label,
    },
    (ICONS[name] || []).map((d) => s("path", { d })),
  );
}

// --- formatting ----------------------------------------------------------------------------
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const USD0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const INT = new Intl.NumberFormat("en-US");
export const money = (n) => (n == null ? "—" : USD.format(n));
export const moneyWhole = (n) => (n == null ? "—" : USD0.format(n));
export const int = (n) => (n == null ? "—" : INT.format(n));

export function parseLocal(text) {
  if (!text) return null;
  const d = new Date(String(text).replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? null : d;
}

export const exactTime = (text) => {
  const d = parseLocal(text);
  return d ? d.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "medium" }) : "";
};

let skew = 0; // server clock minus browser clock, so "3 min ago" is right even when the clocks differ
export const setClockSkew = (ms) => { skew = ms; };
export const nowMs = () => Date.now() + skew;

export function relTime(text) {
  const d = parseLocal(text);
  if (!d) return "—";
  const sec = Math.max(0, Math.round((nowMs() - d.getTime()) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec} s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export function timeEl(text) {
  return h("time", { datetime: text || null, title: exactTime(text) }, relTime(text));
}

export function dayLabel(iso, long = false) {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString("en-US", long ? { weekday: "short", month: "short", day: "numeric" } : { month: "short", day: "numeric" });
}

export const title = (key) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

// --- small components -----------------------------------------------------------------------
export function spinner() {
  return h("span", { class: "spinner", "aria-hidden": "true" });
}

export function skeleton(lines = 3, tall = false) {
  return h("div", { class: "skeleton-block", "aria-hidden": "true" },
    Array.from({ length: lines }, (_, i) => h("span", { class: `skeleton${tall ? " tall" : ""}`, style: `width:${90 - i * 14}%` })));
}

const CHIP_ICON = { ok: "check", bad: "x", warn: "warn", idle: "dash" };
export function setChip(el, kind, text, titleText) {
  el.dataset.kind = kind;
  const iconSlot = el.querySelector(".chip-icon");
  if (iconSlot && iconSlot.dataset.name !== CHIP_ICON[kind]) {
    iconSlot.replaceChildren(icon(CHIP_ICON[kind], 14));
    iconSlot.dataset.name = CHIP_ICON[kind];
  }
  const label = el.querySelector(".chip-text");
  if (label && label.textContent !== text) label.textContent = text;
  if (titleText != null) el.title = titleText;
}

export function chip(kind, text) {
  const el = h("span", { class: "chip" }, h("span", { class: "chip-icon" }), h("span", { class: "chip-text" }));
  setChip(el, kind, text);
  return el;
}

export function toast(message, kind = "ok", ms = 5200) {
  const host = document.getElementById("toasts");
  const node = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" },
    icon(kind === "error" ? "warn" : kind === "info" ? "clock" : "check", 18),
    h("span", { class: "toast-text" }, message),
    h("button", { class: "toast-close", "aria-label": "Dismiss", onclick: () => node.remove() }, icon("x", 14)));
  host.append(node);
  while (host.children.length > 4) host.firstChild.remove();
  if (ms) setTimeout(() => node.remove(), ms);
  return node;
}

export function confirmDialog({ title: heading, body, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const dialog = h("dialog", { class: "dialog", "aria-labelledby": "dlg-title" },
      h("form", { method: "dialog" },
        h("h2", { id: "dlg-title" }, heading),
        h("p", {}, body),
        h("div", { class: "dialog-actions" },
          h("button", { class: "btn", value: "cancel", type: "submit" }, "Cancel"),
          h("button", { class: `btn ${danger ? "danger" : "primary"}`, value: "ok", type: "submit", autofocus: true }, confirmLabel))));
    dialog.addEventListener("close", () => { resolve(dialog.returnValue === "ok"); dialog.remove(); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

// Run `fn` now and then every `ms`, but only while the page is visible. Returns a stop function.
export function poll(fn, ms) {
  let busy = false;
  let stopped = false;
  const tick = async () => {
    if (stopped || busy || document.hidden) return;
    busy = true;
    try { await fn(); } catch (err) { /* the caller shows its own error */ } finally { busy = false; }
  };
  const timer = setInterval(tick, ms);
  const onVisible = () => { if (!document.hidden) tick(); };
  document.addEventListener("visibilitychange", onVisible);
  tick();
  return () => { stopped = true; clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
}

// Run an async action on a button: disabled with a spinner while it works.
export async function withBusy(button, label, action) {
  const original = [...button.childNodes];
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.replaceChildren(spinner(), label);
  try {
    return await action();
  } finally {
    button.replaceChildren(...original);
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

export function switchControl({ label, checked, onchange }) {
  const el = h("button", { class: "switch", role: "switch", type: "button", "aria-checked": String(!!checked), "aria-label": label },
    h("span", { class: "switch-knob" }));
  el.addEventListener("click", () => {
    const next = el.getAttribute("aria-checked") !== "true";
    el.setAttribute("aria-checked", String(next));
    onchange(next);
  });
  return el;
}

export function setSwitch(el, on) {
  el.setAttribute("aria-checked", String(!!on));
}

export function same(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
