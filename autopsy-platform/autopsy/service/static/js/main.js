// Entry point: build the shell, register routes, keep relative times fresh.
import { startRouter } from './router.js';
import { buildShell, markNav, registerAction } from './shell.js';
import { empty, h, icon, mount, tickTimes } from './ui.js';
import { initTooltips } from './widgets.js';
import connections, { openConnectionDrawer } from './pages/connections.js';
import { openImport } from './pages/importer.js';
import incidents, { incidentDetail } from './pages/incidents.js';
import overview from './pages/overview.js';
import project from './pages/project.js';
import runs from './pages/runs.js';
import wizard from './pages/wizard.js';

function notFound(root) {
  mount(root, h('div', { class: 'card' }, empty({ icon: 'search', title: 'Page not found', text: 'That address does not match anything here.', actions: [h('a', { class: 'btn primary', href: '#/' }, 'Go to the overview')] })), h('h1', { class: 'sr-only' }, 'Not found'));
}

initTooltips();
const main = buildShell(document.getElementById('app'));
registerAction('addConnection', () => openConnectionDrawer({ onSaved: () => window.dispatchEvent(new HashChangeEvent('hashchange')) }));
registerAction('importManifest', openImport);

startRouter({
  root: main,
  onRoute: (path) => { markNav(path); const t = { '/': 'Overview', '/connections': 'Connections', '/incidents': 'Incidents', '/runs': 'Runs' }[path]; document.title = `${t || 'Pipeline Autopsy'} · Pipeline Autopsy`; },
  routes: [
    ['/', overview], ['/connections', connections], ['/projects/new', wizard], ['/projects/:name/edit', wizard], ['/projects/:name/:tab?', project],
    ['/incidents', incidents], ['/incidents/:id', incidentDetail], ['/runs', runs], ['/__notfound', notFound],
  ],
});
setInterval(() => tickTimes(), 30000);
void icon;
