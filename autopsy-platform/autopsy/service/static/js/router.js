// Hash router. A page is `(root, params, ctx) => cleanup | void`; ctx.every() polls only while the tab is visible.
const compile = (pattern) => {
  const names = [];
  const rx = pattern.replace(/\/:([a-z]+)(\?)?/g, (_, name, opt) => { names.push(name); return opt ? '(?:/([^/]+))?' : '/([^/]+)'; });
  return { rx: new RegExp(`^${rx}/?$`), names };
};

export const here = () => (location.hash.slice(1) || '/').split('?')[0];
export const go = (path) => { location.hash = path; };

export function startRouter({ routes, root, onRoute }) {
  const table = routes.map(([pattern, page]) => ({ ...compile(pattern), page }));
  let cleanups = [];
  let token = 0;

  const dispose = () => { cleanups.forEach((fn) => { try { fn(); } catch (e) { /* page already gone */ } }); cleanups = []; };

  async function render() {
    const my = ++token;
    dispose();
    const path = here();
    const hit = table.map((r) => [r, r.rx.exec(path)]).find(([, m]) => m);
    const [route, match] = hit || [table[table.length - 1], []];
    const params = {};
    route.names.forEach((n, i) => { params[n] = match[i + 1] ? decodeURIComponent(match[i + 1]) : undefined; });
    const ctx = {
      path, params,
      onCleanup: (fn) => cleanups.push(fn),
      every(ms, fn) {
        const id = setInterval(() => { if (!document.hidden && my === token) fn(); }, ms);
        cleanups.push(() => clearInterval(id));
      },
      isCurrent: () => my === token,
    };
    onRoute && onRoute(path);
    root.textContent = '';
    try {
      const result = await route.page(root, params, ctx);
      if (typeof result === 'function') { if (my === token) cleanups.push(result); else result(); }
    } catch (e) {
      console.error(e);
    }
    if (my === token) { window.scrollTo(0, 0); const t = root.querySelector('h1'); if (t) { t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); } }
  }
  window.addEventListener('hashchange', render);
  render();
  return render;
}
