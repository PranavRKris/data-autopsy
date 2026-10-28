// Hash router: #/shop (default), #/finance, #/operations. Each page module exports mount(root) -> unmount().
const PAGES = {
  shop: () => import("./pages/shop.js"),
  finance: () => import("./pages/finance.js"),
  operations: () => import("./pages/operations.js"),
};
const AREA = { shop: "shop", finance: "office", operations: "office" };

let current = null;
let token = 0;

function routeName() {
  const name = location.hash.replace(/^#\/?/, "").split("/")[0];
  return PAGES[name] ? name : "shop";
}

async function show(first) {
  const name = routeName();
  const mine = ++token;
  const main = document.getElementById("main");
  if (current) { try { current.unmount && current.unmount(); } catch (err) { /* leaving anyway */ } current = null; }
  document.body.dataset.area = AREA[name];
  document.querySelectorAll(".tabs a").forEach((a) => {
    if (a.dataset.tab === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = `${{ shop: "Shop", finance: "Finance", operations: "Operations" }[name]} · Acme Shop`;
  main.replaceChildren();
  try {
    const page = await PAGES[name]();
    if (mine !== token) return;
    const unmount = page.mount(main);
    current = { unmount };
  } catch (err) {
    const box = document.createElement("div");
    box.className = "page-error";
    box.textContent = `This page failed to load: ${err.message}`;
    main.replaceChildren(box);
  }
  if (!first) { window.scrollTo({ top: 0 }); main.focus({ preventScroll: true }); }
}

export function startRouter() {
  window.addEventListener("hashchange", () => show(false));
  if (!location.hash) history.replaceState(null, "", "#/shop");
  return show(true);
}
