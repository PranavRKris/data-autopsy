// Toasts, tooltips, drawers/modals, confirm dialogs, small form controls.
import { h, icon, mount, statusIcon } from './ui.js';

// ---------- toast ----------
export function toast(message, kind = 'info') {
  const host = document.getElementById('toasts');
  const el = h('div', { class: `toast ${kind === 'bad' ? 'bad' : ''}`, role: kind === 'bad' ? 'alert' : 'status' },
    kind === 'bad' ? statusIcon('fail', 16) : kind === 'good' ? statusIcon('ok', 16) : icon('info', 16), h('span', message));
  host.appendChild(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 8000 : 4500);
}
export const toastError = (e) => toast(e && e.message ? e.message : String(e), 'bad');

// ---------- tooltip (event delegation on [data-tip]) ----------
export function initTooltips() {
  const tip = document.getElementById('tip');
  let current = null;
  const show = (target, x, y) => {
    const text = target.getAttribute('data-tip');
    if (!text) return hide();
    current = target;
    tip.textContent = '';
    text.split('\n').forEach((line, i) => {
      if (i) tip.appendChild(document.createElement('br'));
      if (i === 0 && text.includes('\n')) { const b = document.createElement('b'); b.textContent = line; tip.appendChild(b); }
      else tip.appendChild(document.createTextNode(line));
    });
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    const tr = target.getBoundingClientRect();
    let left = x === undefined ? tr.left + tr.width / 2 - r.width / 2 : x + 12;
    let top = y === undefined ? tr.top - r.height - 8 : y + 14;
    if (top < 4) top = (y === undefined ? tr.bottom : y) + 14;
    left = Math.max(8, Math.min(left, window.innerWidth - r.width - 8));
    top = Math.max(4, Math.min(top, window.innerHeight - r.height - 4));
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const hide = () => { current = null; tip.hidden = true; };
  document.addEventListener('mouseover', (e) => { const t = e.target.closest && e.target.closest('[data-tip]'); if (t) show(t, e.clientX, e.clientY); else if (current) hide(); });
  document.addEventListener('mousemove', (e) => { if (current && !tip.hidden && current.contains(e.target)) show(current, e.clientX, e.clientY); });
  document.addEventListener('focusin', (e) => { const t = e.target.closest && e.target.closest('[data-tip]'); if (t) show(t); });
  document.addEventListener('focusout', hide);
  document.addEventListener('scroll', hide, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
}

// ---------- overlays ----------
const stack = [];
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function overlay({ title, kind = 'drawer', size = '', body, footer, onClose, label }) {
  const opener = document.activeElement;
  const titleId = `ov-${Math.random().toString(36).slice(2, 8)}`;
  const bodyEl = h('div', { class: 'panel-body' });
  const footEl = h('div', { class: 'panel-foot' });
  const closeBtn = h('button', { class: 'btn ghost icon sm', 'aria-label': 'Close', onClick: () => api.close() }, icon('x', 18));
  const headTitle = h('h2', { id: titleId }, title);
  const panel = h('section', { class: `panel ${size}`, role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId, 'aria-label': label },
    h('header', { class: 'panel-head' }, headTitle, closeBtn), bodyEl, footEl);
  const scrim = h('div', { class: `scrim ${kind}`, onMousedown: (e) => { if (e.target === scrim) api.close(); } }, panel);
  const api = {
    el: panel, body: bodyEl, foot: footEl,
    setTitle: (t) => mount(headTitle, t),
    setBody: (...k) => mount(bodyEl, ...k),
    setFoot: (...k) => { mount(footEl, ...k); footEl.hidden = !k.filter(Boolean).length; },
    close: () => {
      if (!scrim.isConnected) return;
      scrim.remove();
      stack.splice(stack.indexOf(api), 1);
      if (!stack.length) document.body.classList.remove('locked');
      document.removeEventListener('keydown', onKey, true);
      if (onClose) onClose();
      if (opener && opener.focus && opener.isConnected) opener.focus();
    },
  };
  const onKey = (e) => {
    if (stack[stack.length - 1] !== api) return;
    if (e.key === 'Escape') { e.stopPropagation(); api.close(); }
    if (e.key === 'Tab') {
      const items = [...panel.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  if (body) api.setBody(body);
  api.setFoot(footer);
  document.body.appendChild(scrim);
  document.body.classList.add('locked');
  document.addEventListener('keydown', onKey, true);
  stack.push(api);
  requestAnimationFrame(() => { const f = bodyEl.querySelector(FOCUSABLE) || closeBtn; f.focus(); });
  return api;
}

export function confirmDialog({ title, message, confirmLabel = 'Confirm', danger = false, typed = null }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } dlg.close(); };
    const input = typed ? h('input', { type: 'text', 'aria-label': `Type ${typed} to confirm`, autocomplete: 'off', onInput: () => { ok.disabled = input.value !== typed; } }) : null;
    const ok = h('button', { class: `btn ${danger ? 'danger solid' : 'primary'}`, disabled: !!typed, onClick: () => finish(true) }, confirmLabel);
    const dlg = overlay({
      title, kind: 'modal', size: 'sm', onClose: () => { if (!done) { done = true; resolve(false); } },
      body: h('div', { class: 'stack' }, h('p', message), typed ? h('p', { class: 'small muted' }, 'Type ', h('b', typed), ' to confirm.') : null, input),
      footer: [h('button', { class: 'btn', onClick: () => finish(false) }, 'Cancel'), ok],
    });
    if (input) input.focus();
  });
}

// ---------- clipboard ----------
export async function copyText(text, what = 'Copied') {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = h('textarea', { style: { position: 'fixed', opacity: 0 } });
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (err) { /* ignore */ }
    ta.remove();
  }
  toast(what, 'good');
}

// ---------- form controls ----------
export function switchEl({ checked = false, label, onChange, id }) {
  const input = h('input', { type: 'checkbox', checked, id, onChange: (e) => onChange && onChange(e.target.checked) });
  return h('label', { class: 'switch' }, input, h('span', { class: 'track' }), label ? h('span', label) : null);
}

export function field({ label, required, help, control, error, id }) {
  return h('div', { class: 'field' },
    label ? h('label', { for: id }, label, required ? h('span', { class: 'req', 'aria-hidden': 'true' }, '*') : null) : null,
    control, help ? h('div', { class: 'help' }, help) : null, error ? h('div', { class: 'err', role: 'alert' }, error) : null);
}

export function segmented(options, value, onChange) {
  const wrap = h('div', { class: 'seg', role: 'group' });
  const paint = (v) => options.forEach(([val], i) => wrap.children[i].setAttribute('aria-pressed', String(val === v)));
  options.forEach(([val, text]) => wrap.appendChild(h('button', { type: 'button', onClick: () => { paint(val); onChange(val); } }, text)));
  paint(value);
  return wrap;
}

// run an async action on a button: spinner + disabled, restores afterwards
export async function busy(btn, fn) {
  if (btn.disabled) return undefined;
  const prev = [...btn.childNodes];
  const text = btn.textContent;
  btn.disabled = true;
  mount(btn, icon('refresh', 15, 'spin'), text);
  try { return await fn(); }
  finally { btn.disabled = false; mount(btn, prev); }
}
