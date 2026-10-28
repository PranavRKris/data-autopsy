// Operations back office: the pipeline, the simulated customers, the data counts and the incident lab.
import { get, post, put } from "../api.js";
import { getState, onState, loadConfig } from "../store.js";
import { chip, confirmDialog, exactTime, h, icon, int, poll, relTime, setChip, setSwitch, skeleton, switchControl, toast, withBusy } from "../ui.js";
import { createLab } from "./lab.js";

const INTERVALS = [15, 30, 60, 120];
const RATES = [5, 10, 30, 60];

function selectWith(values, current, label, onchange, unit) {
  const all = values.includes(current) ? values : [...values, current].sort((a, b) => a - b);
  const el = h("select", { "aria-label": label, onchange: (e) => onchange(Number(e.target.value)) },
    all.map((v) => h("option", { value: v }, `${v} ${unit}`)));
  el.value = String(current);
  return el;
}

export function mount(root) {
  const stops = [];
  const lab = createLab();
  let settings = null;
  let saving = false;

  // --- pipeline card -----------------------------------------------------------------------------
  const resultChip = chip("idle", "Not run yet");
  const facts = h("dl", { class: "facts" });
  const warnings = h("div", { class: "warnings" });
  const runBtn = h("button", { class: "btn primary", type: "button", onclick: () => runNow() }, icon("play", 15), "Run now");
  const pipelineControls = h("div", { class: "controls" });
  const pipelineCard = h("section", { class: "card ops-card", "aria-labelledby": "pipe-h" },
    h("div", { class: "card-head" }, h("h2", { id: "pipe-h", class: "office-title" }, "Pipeline"), resultChip),
    facts, warnings, h("div", { class: "card-actions" }, runBtn), pipelineControls);

  function paintPipeline(state) {
    const p = state.pipeline || {};
    const kind = p.last_run_at ? (p.ok ? "ok" : "bad") : "idle";
    setChip(resultChip, kind, p.last_run_at ? (p.ok ? "Last run ok" : "Last run failed") : "Not run yet");
    facts.replaceChildren(
      h("div", {}, h("dt", {}, "Last run"), h("dd", { title: exactTime(p.last_run_at) }, p.last_run_at ? relTime(p.last_run_at) : "—")),
      h("div", {}, h("dt", {}, "Duration"), h("dd", {}, p.duration_ms == null ? "—" : `${(p.duration_ms / 1000).toFixed(1)} s`)),
      h("div", {}, h("dt", {}, "Log length"), h("dd", {}, p.log_lines ? `${int(p.log_lines)} lines` : "—")),
      h("div", {}, h("dt", {}, "Message"), h("dd", {}, p.message || "—")));
    const lines = p.warnings || [];
    warnings.replaceChildren(lines.length
      ? h("ul", { class: "warn-list mono", "aria-label": "Warnings from the last run" }, lines.map((l) => h("li", {}, icon("warn", 14), h("span", {}, l))))
      : h("p", { class: "muted small" }, p.last_run_at ? "No warnings in the last run." : "Nothing to show until the pipeline runs."));
  }

  async function runNow() {
    await withBusy(runBtn, "Running…", async () => {
      try {
        const res = await post("/api/pipeline/run");
        toast(res.ok ? `Pipeline finished in ${(res.duration_ms / 1000).toFixed(1)} s.` : `Pipeline failed: ${res.message}`, res.ok ? "ok" : "error");
      } catch (err) { toast(err.message, "error"); }
    });
    await lab.refresh();
  }

  // --- settings (pipeline timer and simulated customers) --------------------------------------------
  const autoSwitch = switchControl({ label: "Run the pipeline automatically", checked: false, onchange: (on) => save({ pipeline: { enabled: on } }) });
  const trafficSwitch = switchControl({ label: "Simulate customers placing orders", checked: false, onchange: (on) => save({ traffic: { enabled: on } }) });
  let intervalSel = h("select", { "aria-label": "Pipeline interval" });
  let rateSel = h("select", { "aria-label": "Orders per minute" });
  const autoRow = h("div", { class: "control-row" }, h("div", {}, h("strong", {}, "Run automatically"), h("p", { class: "muted small" }, "Like a scheduled job in production.")), h("div", { class: "control-ctl" }, intervalSel, autoSwitch));
  pipelineControls.append(autoRow);
  const trafficRow = h("div", { class: "control-row" }, h("div", {}, h("strong", {}, "Simulate customers"), h("p", { class: "muted small" }, "Random orders arrive while you demo.")), h("div", { class: "control-ctl" }, rateSel, trafficSwitch));
  const trafficCard = h("section", { class: "card ops-card", "aria-labelledby": "cust-h" },
    h("div", { class: "card-head" }, h("h2", { id: "cust-h", class: "office-title" }, "Customers")), trafficRow);

  function paintSettings() {
    if (!settings) return;
    const { pipeline, traffic } = settings;
    setSwitch(autoSwitch, pipeline.enabled);
    setSwitch(trafficSwitch, traffic.enabled);
    if (document.activeElement !== intervalSel && (Number(intervalSel.value) !== pipeline.interval_seconds || !intervalSel.options.length)) {
      const next = selectWith(INTERVALS, pipeline.interval_seconds, "Pipeline interval", (v) => save({ pipeline: { interval_seconds: v } }), "s");
      intervalSel.replaceWith(next); intervalSel = next;
    }
    if (document.activeElement !== rateSel && (Number(rateSel.value) !== traffic.per_minute || !rateSel.options.length)) {
      const next = selectWith(RATES, traffic.per_minute, "Orders per minute", (v) => save({ traffic: { per_minute: v } }), "/min");
      rateSel.replaceWith(next); rateSel = next;
    }
  }

  async function save(patch) {
    saving = true;
    try {
      settings = await put("/api/background", patch);
      toast("Saved.", "ok", 1800);
    } catch (err) {
      toast(err.message, "error");
      settings = (await loadConfig(true)).background;
    } finally {
      saving = false;
      paintSettings();
    }
  }

  async function loadSettings() {
    if (saving) return;
    settings = (await loadConfig(true)).background;
    paintSettings();
  }

  // --- data card ------------------------------------------------------------------------------------
  const counts = h("dl", { class: "facts counts" });
  const columns = h("ul", { class: "columns mono", "aria-label": "Columns of the orders table" });
  const dataCard = h("section", { class: "card ops-card", "aria-labelledby": "data-h" },
    h("div", { class: "card-head" }, h("h2", { id: "data-h", class: "office-title" }, "Data")),
    counts, h("p", { class: "small muted" }, "Columns in the orders table right now"), columns);
  let countSig = "";

  function paintData(state) {
    const c = state.counts;
    const sig = JSON.stringify([c, state.orders_columns]);
    if (sig === countSig) return;
    countSig = sig;
    counts.replaceChildren(
      ...[["Raw orders", c.raw_orders], ["Orders today", c.orders_today], ["Staged orders", c.staged_orders], ["Queued orders", c.queued_orders]]
        .map(([label, value]) => h("div", {}, h("dt", {}, label), h("dd", {}, int(value)))));
    columns.replaceChildren(...(state.orders_columns || []).map((name) => h("li", {}, name)));
  }

  // --- reset ----------------------------------------------------------------------------------------
  const resetBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    const ok = await confirmDialog({
      title: "Reset demo data?",
      body: "This reseeds a healthy database that runs up to now and rebuilds the reports. Pipeline Autopsy keeps its baseline, so it will show the shop as healthy again after its next check.",
      confirmLabel: "Reset data", danger: true });
    if (ok) await lab.reset(resetBtn);
  } }, icon("refresh", 15), "Reset demo data");

  root.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Operations"), h("p", {}, "The pipeline, the customers and the things that go wrong."))),
    h("div", { class: "ops-grid" }, pipelineCard, h("div", { class: "ops-col" }, trafficCard, dataCard)),
    lab.root,
    h("div", { class: "reset-row" }, resetBtn, h("span", { class: "muted small" }, "Reseeds healthy data. Autopsy keeps its baseline.")));

  facts.append(skeleton(3));

  stops.push(onState((state) => { paintPipeline(state); paintData(state); lab.paint(); }));
  stops.push(poll(() => lab.refresh(), 4000));
  stops.push(poll(loadSettings, 6000));
  return () => stops.forEach((s) => typeof s === "function" && s());
}
