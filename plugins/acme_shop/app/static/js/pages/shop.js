// Storefront: product grid, cart and checkout, and the live "Just placed" feed.
import { get, post } from "../api.js";
import { productArt } from "../art.js";
import { h, icon, int, money, poll, relTime, skeleton, spinner, timeEl, toast } from "../ui.js";

const CHANNELS = [["web", "Web"], ["mobile", "Mobile app"], ["store", "In store"]];
const cart = new Map();        // product id -> quantity; survives switching tabs
const choice = { customer: null, channel: "web" };

export function mount(root) {
  let products = [];
  let checkingOut = false;
  let cartOpen = false;
  const rows = new Map();     // order id -> <tr>
  let firstFeed = true;
  const stops = [];

  // --- layout -------------------------------------------------------------------------------
  const grid = h("div", { class: "product-grid" }, [1, 2, 3, 4].map(() => h("div", { class: "product-card" }, skeleton(4, true))));
  const lines = h("ul", { class: "cart-lines" });
  const empty = h("div", { class: "cart-empty" }, h("strong", {}, "Your cart is empty"), h("span", {}, "Add something nice from the shelf."));
  const totalEl = h("strong", { class: "cart-total-value" }, money(0));
  const countEl = h("span", { class: "cart-count" }, "0");
  const notice = h("div", { class: "cart-notice", role: "status", hidden: true });
  const customerSel = h("select", { id: "customer", onchange: (e) => { choice.customer = Number(e.target.value); } });
  const channelSel = h("select", { id: "channel", onchange: (e) => { choice.channel = e.target.value; } },
    CHANNELS.map(([value, label]) => h("option", { value, selected: value === choice.channel }, label)));
  const checkout = h("button", { class: "btn primary checkout", type: "button", onclick: () => placeOrder() }, "Checkout");
  const cartBar = h("button", { class: "cart-bar btn primary", type: "button", "aria-expanded": "false", "aria-controls": "cart", onclick: () => toggleCart() },
    icon("cart", 18), h("span", { class: "cart-bar-label" }, "View cart"), h("span", { class: "cart-bar-total" }, money(0)));
  const cartEl = h("aside", { class: "cart", id: "cart", "aria-label": "Your cart" },
    h("div", { class: "cart-head" },
      h("h2", {}, icon("cart", 20), "Your cart ", countEl),
      h("button", { class: "icon-btn cart-close", type: "button", "aria-label": "Close cart", onclick: () => toggleCart(false) }, icon("x", 16))),
    empty, lines,
    h("div", { class: "cart-fields" },
      h("label", { class: "field" }, h("span", {}, "Shopping as"), customerSel),
      h("label", { class: "field" }, h("span", {}, "Order from"), channelSel)),
    h("div", { class: "cart-total" }, h("span", {}, "Total"), totalEl),
    notice, checkout);

  const feedBody = h("tbody", {}, h("tr", {}, h("td", { colspan: 5 }, skeleton(2))));
  const feed = h("section", { class: "feed", "aria-labelledby": "feed-h" },
    h("div", { class: "feed-head" }, h("h2", { id: "feed-h" }, "Just placed"), h("span", { class: "live", title: "Updates every 3 seconds" }, h("span", { class: "live-dot" }), "Live")),
    h("div", { class: "table-wrap" },
      h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Order"), h("th", {}, "Customer"), h("th", { class: "num" }, "Amount"), h("th", {}, "Channel"), h("th", {}, "Placed"))),
        feedBody)));

  root.replaceChildren(
    h("section", { class: "hero" },
      h("div", {}, h("h1", {}, "Everyday things, well made."), h("p", {}, "Small-batch homewares and gear for the daily grind. Free returns, shipped the same day.")),
      h("ul", { class: "perks" }, h("li", {}, icon("check", 16), "Ships today"), h("li", {}, icon("check", 16), "Free returns"), h("li", {}, icon("check", 16), "2-year warranty"))),
    h("div", { class: "shop-layout" },
      h("section", { "aria-labelledby": "shelf-h" }, h("h2", { id: "shelf-h", class: "section-title" }, "The shelf"), grid),
      cartEl),
    feed,
    cartBar);

  // --- products and cart ----------------------------------------------------------------------
  const badges = new Map();
  function renderProducts() {
    grid.replaceChildren(...products.map((p) => {
      const badge = h("span", { class: "in-cart", hidden: true });
      badges.set(p.id, badge);
      return h("article", { class: "product-card" },
        h("div", { class: "art-wrap" }, productArt(p), badge),
        h("div", { class: "product-body" },
          h("h3", {}, p.name), h("p", { class: "blurb" }, p.blurb),
          h("div", { class: "product-foot" }, h("strong", { class: "price" }, money(p.price)),
            h("button", { class: "btn small primary add", type: "button", "aria-label": `Add ${p.name} to cart`, onclick: () => add(p.id, 1) }, icon("plus", 14), "Add"))));
    }));
    paintCart();
  }

  function add(id, delta) {
    const next = (cart.get(id) || 0) + delta;
    if (next <= 0) cart.delete(id); else cart.set(id, Math.min(next, 20));
    notice.hidden = true;
    paintCart();
  }

  function paintCart() {
    const byId = new Map(products.map((p) => [p.id, p]));
    let total = 0; let count = 0;
    lines.replaceChildren(...[...cart].filter(([id]) => byId.has(id)).map(([id, qty]) => {
      const p = byId.get(id);
      total += p.price * qty; count += qty;
      return h("li", { class: "cart-line" },
        h("div", { class: "line-name" }, h("span", {}, p.name), h("small", {}, `${money(p.price)} each`)),
        h("div", { class: "stepper", role: "group", "aria-label": `Quantity of ${p.name}` },
          h("button", { class: "icon-btn", type: "button", "aria-label": `One less ${p.name}`, onclick: () => add(id, -1) }, icon("minus", 14)),
          h("output", { "aria-live": "polite" }, String(qty)),
          h("button", { class: "icon-btn", type: "button", "aria-label": `One more ${p.name}`, disabled: qty >= 20, onclick: () => add(id, 1) }, icon("plus", 14))),
        h("strong", { class: "line-total" }, money(p.price * qty)));
    }));
    empty.hidden = count > 0;
    countEl.textContent = String(count);
    totalEl.textContent = money(total);
    cartBar.querySelector(".cart-bar-total").textContent = money(total);
    cartBar.querySelector(".cart-bar-label").textContent = count ? `View cart (${count})` : "View cart";
    checkout.disabled = count === 0 || checkingOut;
    badges.forEach((badge, id) => {
      const qty = cart.get(id) || 0;
      badge.hidden = qty === 0;
      badge.textContent = `${qty} in cart`;
    });
  }

  function toggleCart(open = !cartOpen) {
    cartOpen = open;
    cartEl.dataset.open = String(open);
    cartBar.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("cart-open", open);
  }

  async function placeOrder() {
    if (checkingOut || cart.size === 0) return;
    checkingOut = true;
    checkout.replaceChildren(spinner(), "Placing order…");
    checkout.disabled = true;
    notice.hidden = true;
    try {
      const res = await post("/api/orders", {
        customer_id: choice.customer,
        channel: choice.channel,
        items: [...cart].map(([product_id, qty]) => ({ product_id, qty })),
      });
      cart.clear();
      if (res.status === "queued") {
        const text = `Order accepted for ${money(res.amount)}. It is waiting to be processed and will show up in reports once the system catches up.`;
        notice.className = "cart-notice info";
        notice.replaceChildren(icon("clock", 18), h("span", {}, text));
        notice.hidden = false;
        toast(text, "info", 9000);
      } else {
        toast(`Order #${res.order_id} placed: ${money(res.amount)}. ${res.message}`, "ok");
        toggleCart(false);
      }
      await loadFeed();
    } catch (err) {
      notice.className = "cart-notice error";
      notice.replaceChildren(icon("warn", 18), h("span", {}, err.message));
      notice.hidden = false;
      toast(err.message, "error");
    } finally {
      checkingOut = false;
      checkout.replaceChildren("Checkout");
      paintCart();
    }
  }

  // --- the live feed ---------------------------------------------------------------------------
  async function loadFeed() {
    const { orders } = await get("/api/orders?limit=10");
    const wanted = new Set(orders.map((o) => o.order_id));
    for (const [id] of rows) if (!wanted.has(id)) rows.delete(id);
    const trs = orders.map((o) => {
      let tr = rows.get(o.order_id);
      if (!tr) {
        tr = h("tr", { class: firstFeed ? "" : "is-new" },
          h("td", { class: "mono" }, `#${o.order_id}`),
          h("td", { class: "mono" }, o.customer_id == null ? h("span", {}, "–", h("span", { class: "sr-only" }, " none")) : String(o.customer_id)),
          h("td", { class: "num mono" }, money(o.amount)),
          h("td", {}, o.channel == null ? "–" : String(o.channel)),
          h("td", { class: "when" }));
        rows.set(o.order_id, tr);
      }
      const when = tr.querySelector(".when");
      const label = relTime(o.ordered_at);
      if (!when.firstChild || when.textContent !== label) when.replaceChildren(timeEl(o.ordered_at));
      return tr;
    });
    firstFeed = false;
    if (!trs.length) feedBody.replaceChildren(h("tr", {}, h("td", { colspan: 5, class: "empty" }, "No orders yet. Be the first.")));
    else feedBody.replaceChildren(...trs);
  }

  // --- boot --------------------------------------------------------------------------------------
  Promise.all([get("/api/products"), get("/api/customers")]).then(([p, c]) => {
    products = p.products;
    customerSel.replaceChildren(...c.customers.map((cu) => h("option", { value: cu.customer_id }, `${cu.name} (#${cu.customer_id})`)));
    if (choice.customer == null) choice.customer = c.customers[0] && c.customers[0].customer_id;
    customerSel.value = String(choice.customer);
    renderProducts();
  }).catch((err) => {
    grid.replaceChildren(h("div", { class: "page-error" }, icon("warn", 18), err.message));
  });
  stops.push(poll(() => loadFeed().catch((err) => {
    if (!rows.size) feedBody.replaceChildren(h("tr", {}, h("td", { colspan: 5, class: "empty" }, err.message)));
  }), 3000));
  paintCart();

  return () => { stops.forEach((s) => s()); document.body.classList.remove("cart-open"); };
}
