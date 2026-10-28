// The incident lab: one card per real-world incident, with Make it happen / Roll back and presenter notes.
import { get, post } from "../api.js";
import { activeEvents, getState, refreshState } from "../store.js";
import { dayLabel, exactTime, h, icon, int, relTime, spinner, title, toast } from "../ui.js";

const HIDDEN = new Set(["event", "active", "since", "from_day"]);

// Some incidents report the first affected calendar day under "from_day"; "since" is always when the incident began.
const hasTime = (text) => /\d{2}:\d{2}/.test(text || "");

function detailItems(detail) {
  const items = Object.entries(detail || {}).filter(([k]) => !HIDDEN.has(k)).map(([k, v]) =>
    h("div", {}, h("dt", {}, title(k)), h("dd", {}, typeof v === "number" ? int(v) : String(v))));
  if (detail && detail.from_day) {
    items.unshift(h("div", {}, h("dt", {}, "Affects orders from"), h("dd", {}, dayLabel(detail.from_day.slice(0, 10)))));
  }
  return items;
}

export function createLab() {
  const cards = new Map();           // event id -> { root, chip, button, detail, ... }
  const busy = new Map();            // event id -> phase text while an action is running
  const last = new Map();            // event id -> detail of the last trigger / roll back
  let events = [];
  let resetting = false;

  const banner = h("div", { class: "lab-banner", role: "status", hidden: true });
  const list = h("div", { class: "lab-grid" });
  const root = h("section", { class: "lab", "aria-labelledby": "lab-h" },
    h("div", { class: "lab-head" },
      h("div", {}, h("h2", { id: "lab-h", class: "office-title" }, "Incident lab"),
        h("p", { class: "muted" }, "Cause a real-world incident. The pipeline rebuilds, finance sees the effect, and Pipeline Autopsy should explain it."))),
    banner, list);

  function build(ev) {
    const chip = h("span", { class: "state-chip" });
    const detail = h("dl", { class: "detail", hidden: true });
    const button = h("button", { class: "btn", type: "button", onclick: () => act(ev.id) });
    const notes = h("details", { class: "notes" }, h("summary", {}, "Presenter notes"),
      h("p", {}, h("strong", {}, "Autopsy should find: "), ev.expect),
      h("p", {}, h("strong", {}, "Roll back: "), ev.rollback),
      h("p", { class: "muted" }, `Matches seeded scenario ${ev.scenario}.`));
    const root = h("article", { class: "event-card", "data-event": ev.id },
      h("div", { class: "event-top" }, h("h3", {}, ev.title), chip),
      h("p", { class: "story" }, ev.story),
      h("p", { class: "symptom" }, icon("warn", 15), h("span", {}, h("strong", {}, "What people notice: "), ev.symptom)),
      detail, h("div", { class: "event-actions" }, button), notes);
    cards.set(ev.id, { root, chip, detail, button });
    return root;
  }

  function paint() {
    const state = getState();
    const live = (state && state.events) || {};
    for (const ev of events) {
      const card = cards.get(ev.id) || (list.append(build(ev)), cards.get(ev.id));
      const active = ev.id in live;
      const phase = busy.get(ev.id);
      card.root.classList.toggle("active", active);
      const chipKind = active ? "active" : "normal";
      if (card.chip.dataset.kind !== chipKind || active) {
        card.chip.dataset.kind = chipKind;
        const since = active && live[ev.id].since;
        card.chip.replaceChildren(icon(active ? "warn" : "check", 14), active
          ? h("span", { title: hasTime(since) ? exactTime(since) : null }, hasTime(since) ? `Happening since ${relTime(since)}` : "Happening") : "Normal");
      }
      const items = phase ? [] : detailItems(last.get(ev.id) || live[ev.id]);
      card.detail.hidden = items.length === 0 && !phase;
      card.detail.replaceChildren(...items);
      const anyBusy = busy.size > 0 || resetting;
      card.button.disabled = anyBusy;
      card.button.className = `btn ${active ? "" : "primary"}`;
      card.button.replaceChildren(...(phase
        ? [spinner(), phase]
        : active ? [icon("undo", 16), "Roll back"] : [icon("bolt", 16), "Make it happen"]));
      card.button.setAttribute("aria-label", `${active ? "Roll back" : "Make it happen"}: ${ev.title}`);
    }
    const n = Object.keys(live).length;
    banner.hidden = n === 0;
    if (n) {
      const link = document.getElementById("autopsy-link");
      banner.replaceChildren(icon("warn", 18),
        h("span", {}, `${n} incident${n === 1 ? "" : "s"} active. Pipeline Autopsy checks every minute, or press Run checks there.`),
        link && !link.hidden ? h("a", { class: "btn small primary", href: link.href, target: "_blank", rel: "noopener" }, "Open Autopsy", icon("external", 14)) : null);
    }
  }

  async function act(id) {
    const active = id in ((getState() && getState().events) || {});
    const verb = active ? "rollback" : "trigger";
    busy.set(id, active ? "Rolling back…" : "Causing incident…");
    paint();
    try {
      const res = await post(`/api/events/${id}/${verb}`);
      last.set(id, res);
      busy.set(id, "Rebuilding reports…");
      paint();
      await post("/api/pipeline/run");
      const ev = events.find((e) => e.id === id);
      toast(active ? `Rolled back: ${ev.title}. Reports rebuilt.` : `Happening: ${ev.title}. Reports rebuilt, check the Finance tab.`, active ? "ok" : "info");
    } catch (err) {
      last.delete(id);
      toast(err.message, "error");
    } finally {
      busy.delete(id);
      await refresh();
    }
  }

  async function refresh() {
    try {
      const [{ events: list2 }] = await Promise.all([get("/api/events"), refreshState()]);
      events = list2;
      for (const ev of events) if (!ev.active && !busy.has(ev.id) && last.has(ev.id) && last.get(ev.id).active) last.delete(ev.id);
    } catch (err) { /* the shell banner reports an unreachable server */ }
    paint();
  }

  async function reset(button) {
    resetting = true;
    paint();
    button.disabled = true;
    const original = [...button.childNodes];
    button.replaceChildren(spinner(), "Reseeding…");
    try {
      await post("/api/reset");
      last.clear();
      toast("Demo data reset to a healthy state. Pipeline Autopsy keeps its baseline.", "ok");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      resetting = false;
      button.replaceChildren(...original);
      button.disabled = false;
      await refresh();
    }
  }

  return { root, refresh, paint, reset, isBusy: () => busy.size > 0 || resetting, activeCount: () => activeEvents().length };
}
