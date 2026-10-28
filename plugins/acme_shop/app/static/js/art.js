// Product pictures drawn in SVG from each product's hue. No image files.
import { s } from "./ui.js";

const SHAPES = {
  mug: (c) => [
    s("path", { d: "M30 26h34v26a9 9 0 01-9 9H39a9 9 0 01-9-9z", fill: c.main }),
    s("path", { d: "M64 32h5a8 8 0 010 16h-5", fill: "none", stroke: c.main, "stroke-width": 5, "stroke-linecap": "round" }),
    s("path", { d: "M30 34h34", stroke: c.light, "stroke-width": 3, opacity: ".6" }),
    s("path", { d: "M40 18q3-4 0-8M50 18q3-4 0-8", fill: "none", stroke: c.dark, "stroke-width": 2, "stroke-linecap": "round", opacity: ".5" }),
  ],
  tote: (c) => [
    s("path", { d: "M26 32h48l4 32H22z", fill: c.main }),
    s("path", { d: "M38 32v-6a12 12 0 0124 0v6", fill: "none", stroke: c.dark, "stroke-width": 4, "stroke-linecap": "round" }),
    s("rect", { x: 40, y: 44, width: 20, height: 10, rx: 3, fill: c.light, opacity: ".7" }),
  ],
  notebook: (c) => [
    s("rect", { x: 28, y: 10, width: 44, height: 56, rx: 5, fill: c.main }),
    s("rect", { x: 28, y: 10, width: 8, height: 56, rx: 3, fill: c.dark }),
    s("path", { d: "M44 24h20M44 32h20M44 40h14", stroke: c.light, "stroke-width": 3, "stroke-linecap": "round" }),
  ],
  hoodie: (c) => [
    s("path", { d: "M38 14C40 20 44 23 50 23S60 20 62 14L80 24 90 46 78 50 74 42V68H26V42L22 50 10 46 20 24Z", fill: c.main }),
    s("path", { d: "M41 16C44 28 56 28 59 16", fill: "none", stroke: c.dark, "stroke-width": 3, "stroke-linecap": "round" }),
    s("path", { d: "M38 52h24v12H38z", fill: c.dark, opacity: ".35" }),
  ],
  sneakers: (c) => [
    s("path", { d: "M12 56V38c10 0 16-4 20-10l10 8c8 6 20 5 32 9 8 3 12 6 12 12v3H12z", fill: c.main }),
    s("path", { d: "M12 58h76", stroke: c.dark, "stroke-width": 6, "stroke-linecap": "round" }),
    s("path", { d: "M36 36l5 4M43 40l5 4", stroke: c.light, "stroke-width": 3, "stroke-linecap": "round" }),
  ],
  lamp: (c) => [
    s("path", { d: "M34 68h32", stroke: c.dark, "stroke-width": 6, "stroke-linecap": "round" }),
    s("path", { d: "M50 66V42l14-16", fill: "none", stroke: c.main, "stroke-width": 4, "stroke-linecap": "round", "stroke-linejoin": "round" }),
    s("path", { d: "M54 14l26 11-8 14-26-11z", fill: c.main }),
    s("path", { d: "M60 40l10 8", stroke: c.light, "stroke-width": 3, "stroke-linecap": "round", opacity: ".8" }),
  ],
  headphones: (c) => [
    s("path", { d: "M26 48V42a24 24 0 0148 0v6", fill: "none", stroke: c.main, "stroke-width": 6, "stroke-linecap": "round" }),
    s("rect", { x: 19, y: 44, width: 14, height: 24, rx: 6, fill: c.dark }),
    s("rect", { x: 67, y: 44, width: 14, height: 24, rx: 6, fill: c.dark }),
    s("rect", { x: 22, y: 50, width: 8, height: 12, rx: 4, fill: c.light, opacity: ".6" }),
  ],
  backpack: (c) => [
    s("path", { d: "M34 20v-4a16 16 0 0132 0v4", fill: "none", stroke: c.dark, "stroke-width": 4, "stroke-linecap": "round" }),
    s("path", { d: "M30 28a20 20 0 0140 0v38a7 7 0 01-7 7H37a7 7 0 01-7-7z", fill: c.main }),
    s("rect", { x: 38, y: 48, width: 24, height: 18, rx: 4, fill: c.dark, opacity: ".35" }),
    s("path", { d: "M38 38h24", stroke: c.light, "stroke-width": 3, "stroke-linecap": "round" }),
  ],
};

export function productArt(product) {
  const hue = product.hue ?? 20;
  const colors = {
    main: `hsl(${hue} 52% 44%)`, dark: `hsl(${hue} 55% 30%)`, light: `hsl(${hue} 70% 92%)`,
  };
  const gid = `art-${product.id}`;
  const draw = SHAPES[product.id] || SHAPES.tote;
  return s("svg", { viewBox: "0 0 100 80", class: "art", role: "img", "aria-label": product.name, preserveAspectRatio: "xMidYMid slice" },
    s("defs", {},
      s("linearGradient", { id: gid, x1: 0, y1: 0, x2: 1, y2: 1 },
        s("stop", { offset: "0", "stop-color": `hsl(${hue} 80% 94%)` }),
        s("stop", { offset: "1", "stop-color": `hsl(${hue} 62% 83%)` }))),
    s("rect", { width: 100, height: 80, fill: `url(#${gid})` }),
    s("circle", { cx: 78, cy: 16, r: 26, fill: `hsl(${hue} 80% 97%)`, opacity: ".55" }),
    s("ellipse", { cx: 50, cy: 72, rx: 30, ry: 4, fill: `hsl(${hue} 45% 35%)`, opacity: ".12" }),
    draw(colors));
}
