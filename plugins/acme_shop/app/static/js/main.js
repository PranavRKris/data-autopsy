// Shell: header chips, the offline banner and the state poll that every page shares.
import { startRouter } from "./router.js";
import { activeEvents, loadConfig, onState, refreshState } from "./store.js";
import { h, icon, poll, relTime, setChip } from "./ui.js";

const pipelineChip = document.getElementById("chip-pipeline");
const incidentChip = document.getElementById("chip-incidents");
const banner = document.getElementById("banner");

function paintPipeline(state) {
  const p = state.pipeline || {};
  if (!p.last_run_at) return setChip(pipelineChip, "idle", "Pipeline not run yet", "The pipeline has not run since the shop started");
  const when = relTime(p.last_run_at);
  setChip(pipelineChip, p.ok ? "ok" : "bad", p.ok ? `Pipeline ok · ${when}` : `Pipeline failed · ${when}`,
    `${p.message} (${p.duration_ms} ms)`);
}

function paintIncidents(state) {
  const n = activeEvents(state).length;
  setChip(incidentChip, n ? "warn" : "ok", n ? `${n} incident${n === 1 ? "" : "s"} active` : "No incidents active",
    n ? "Open Operations to see and roll back what is happening" : "Everything is running normally");
}

function paintBanner(failure) {
  if (!failure) { banner.replaceChildren(); return; }
  if (banner.dataset.shown === failure.message) return;
  banner.dataset.shown = failure.message;
  banner.replaceChildren(h("div", { class: "banner-offline" }, icon("warn", 18), h("span", {}, failure.message), " Retrying…"));
}

onState((state, failure) => {
  if (state) { paintPipeline(state); paintIncidents(state); }
  if (!failure) delete banner.dataset.shown;
  paintBanner(failure);
});

loadConfig().then((config) => {
  const link = document.getElementById("autopsy-link");
  if (config.autopsy_url) {
    link.href = config.autopsy_url;
    link.append(icon("external", 14));
    link.hidden = false;
  }
}).catch(() => { /* the banner already says the server is unreachable */ });

poll(refreshState, 4000);
startRouter();
