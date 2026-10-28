// A small Markdown renderer for incident reports. It builds DOM nodes (no innerHTML), so text can never become markup.
import { h } from './ui.js';

function inline(text) {
  const out = [];
  const rx = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  for (const m of text.matchAll(rx)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    out.push(tok.startsWith('`') ? h('code', tok.slice(1, -1)) : h('strong', tok.slice(2, -2)));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function renderMarkdown(source) {
  const root = h('div', { class: 'md' });
  let para = [], list = null;
  const flushPara = () => { if (para.length) { root.appendChild(h('p', inline(para.join(' ')))); para = []; } };
  const flushList = () => { if (list) { root.appendChild(list); list = null; } };
  for (const raw of String(source || '').split('\n')) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flushPara(); flushList(); }
    else if ((m = /^(#{1,4})\s+(.*)$/.exec(line))) {
      flushPara(); flushList();
      root.appendChild(h(`h${Math.min(m[1].length + 1, 5)}`, inline(m[2])));
    } else if ((m = /^\s*(\d+)\.\s+(.*)$/.exec(line))) {
      flushPara();
      if (!list || list.tagName !== 'OL') { flushList(); list = h('ol'); }
      list.appendChild(h('li', inline(m[2])));
    } else if ((m = /^\s*[-*]\s+(.*)$/.exec(line))) {
      flushPara();
      if (!list || list.tagName !== 'UL') { flushList(); list = h('ul'); }
      list.appendChild(h('li', inline(m[1])));
    } else { flushList(); para.push(line.trim()); }
  }
  flushPara(); flushList();
  return root;
}
