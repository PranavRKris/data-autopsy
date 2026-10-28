// The one shared copy of /api/state, refreshed by the shell and read by every page.
import { get } from "./api.js";
import { parseLocal, setClockSkew } from "./ui.js";

let state = null;
let failed = null;
const listeners = new Set();

export const getState = () => state;
export const lastError = () => failed;

export function onState(fn) {
  listeners.add(fn);
  if (state) fn(state, null);
  return () => listeners.delete(fn);
}

export async function refreshState() {
  try {
    const next = await get("/api/state");
    const server = parseLocal(next.now);
    if (server) setClockSkew(server.getTime() - Date.now());
    state = next;
    failed = null;
  } catch (err) {
    failed = err;
  }
  listeners.forEach((fn) => fn(state, failed));
  return state;
}

export const activeEvents = (s = state) => Object.keys((s && s.events) || {});

let config = null;
export async function loadConfig(force = false) {
  if (!config || force) config = await get("/api/config");
  return config;
}
