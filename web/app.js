/* Wirely in the browser.
 *
 * The circuit editing, drawing and simulation are Wirely's own Python code (the same files as the desktop app),
 * running in the browser with Pyodide. This file is the page around it: it loads Python, passes on mouse and
 * keyboard events, replays the drawing commands Python records onto the canvas, and provides the toolbar,
 * gallery, menus, dialogs, graph panel, files and sound.
 */
"use strict";

const PYODIDE_VERSION = "314.0.7";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const SANS = '"Inter", "Segoe UI", "Helvetica Neue", "Noto Sans", Roboto, Arial, "Hiragino Sans", "Yu Gothic UI", "Meiryo", "Noto Sans JP", sans-serif';
const MONO = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo", monospace';
const ZOOM_MIN = 0.2, ZOOM_MAX = 8.0;
const QT_SHIFT = 0x2000000, QT_CTRL = 0x4000000;
const GRID = 10;
const TOOL_ICONS = ["new", "open", "save", "undo", "redo", "select", "wire", "rotate", "rotate_ccw", "flip", "delete",
  "play", "pause", "stop", "volts", "flow", "readings", "sound", "graph", "zoom_in", "zoom_out", "zoom_fit", "export", "bom", "grid",
  "theme"];
const ICON_FOR = { dark: "theme" };

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

let py = null;            // Pyodide
let app = null;           // wirely_web.App (Python)
let ready = false;
let colours = {};
let ui = {};              // last App.state()
let numpyKind = "";

// ============================================================================================ language
/* Every word the page shows goes through tr(): the English is the key into locale/<code>.json (the same
   catalogues the Python side reads), and anything without a translation simply shows in English. Saved
   circuits never hold translated text, so a circuit made in one language opens in any other. */
const LANGS = [["en", "English"], ["es", "Español"], ["de", "Deutsch"], ["ja", "日本語"]];
const HTML_LANG = { en: "en-GB", es: "es", de: "de", ja: "ja" };
let lang = "en";
let catalog = {};
function tr(text, vars) {
  let s = Object.prototype.hasOwnProperty.call(catalog, text) ? catalog[text] : text;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return s;
}
function trn(one, other, n) { return tr(n === 1 ? one : other, { n }); }
function savedLanguage() {
  const asked = params.get("lang");
  if (asked && LANGS.some(([c]) => c === asked)) return asked;
  try { const s = localStorage.getItem("wirely-language"); if (LANGS.some(([c]) => c === s)) return s; } catch (e) { /* storage off */ }
  return "en";
}
async function loadCatalog(code) {
  if (code === "en") return {};
  try {
    const r = await fetch(`locale/${code}.json`);
    return r.ok ? await r.json() : {};
  } catch (e) { console.warn("no translations for", code, e); return {}; }
}
// the page's own fixed text (index.html): remember the English once, then show it in any language
const domTexts = [];
function collectDom() {
  const attrs = ["title", "placeholder", "aria-label", "alt"];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const en = n.nodeValue.trim();
    if (en && !["SCRIPT", "STYLE"].includes(n.parentNode.nodeName)) domTexts.push({ node: n, en, pad: n.nodeValue });
  }
  document.querySelectorAll("body *").forEach((el) => {
    for (const a of attrs) if (el.hasAttribute(a)) domTexts.push({ el, attr: a, en: el.getAttribute(a) });
  });
  const title = document.querySelector("title");
  if (title && title.firstChild) domTexts.push({ node: title.firstChild, en: title.textContent.trim(), pad: title.textContent, head: true });
  const meta = document.querySelector('meta[name="description"]');
  if (meta) domTexts.push({ el: meta, attr: "content", en: meta.getAttribute("content"), head: true });
}
function applyDom() {
  for (const d of domTexts) {
    if (d.node) {
      if (d.head || d.node.isConnected) d.node.nodeValue = d.pad.replace(d.en, tr(d.en));
    } else if (d.head || d.el.isConnected) d.el.setAttribute(d.attr, tr(d.en));
  }
  document.documentElement.lang = HTML_LANG[lang] || "en";
}

// ============================================================================================ text measuring
const measureCtx = document.createElement("canvas").getContext("2d");
function fontCss(px, bold, mono) {
  return `${bold ? "bold " : ""}${px}px ${mono ? MONO : SANS}`;
}
// Python's label layout calls this to measure text with the real fonts
window.wirelyMeasure = function (text, px, bold, mono) {
  measureCtx.font = fontCss(px, bold, mono);
  return measureCtx.measureText(text).width;
};

// ============================================================================================ replaying drawings
/* Python's stand-in QPainter (web/py/qtshim.py) records what Qt would have painted; this draws it on a canvas.
   Qt and the canvas draw in almost the same way, so this is mostly a translation of names. */
function replay(ctx, ops, outerAlpha = 1) {
  let pen = null, brush = null, font = fontCss(13, false, false);
  const stack = [];
  const applyPen = () => {
    ctx.strokeStyle = pen.c;
    const w = pen.w > 0 ? pen.w : 1 / Math.max(0.01, Math.hypot(ctx.getTransform().a, ctx.getTransform().b));
    ctx.lineWidth = w;
    ctx.lineCap = pen.cap || "square";
    ctx.lineJoin = pen.join || "bevel";
    if (pen.style === 2) ctx.setLineDash([4 * w, 2 * w]);
    else if (pen.style === 3) ctx.setLineDash([w, 2 * w]);
    else ctx.setLineDash([]);
  };
  const applyBrush = () => {
    if (typeof brush === "string") { ctx.fillStyle = brush; return; }
    let g;
    if (brush[0] === "rg") {
      g = ctx.createRadialGradient(brush[1], brush[2], 0, brush[1], brush[2], Math.max(0.01, brush[3]));
      for (const [t, c] of brush[4]) g.addColorStop(Math.max(0, Math.min(1, t)), c);
    } else {
      g = ctx.createLinearGradient(brush[1], brush[2], brush[3], brush[4]);
      for (const [t, c] of brush[5]) g.addColorStop(Math.max(0, Math.min(1, t)), c);
    }
    ctx.fillStyle = g;
  };
  const finish = (fill, rule) => {
    if (fill && brush) { applyBrush(); ctx.fill(rule || "nonzero"); }
    if (pen) { applyPen(); ctx.stroke(); }
  };
  for (const op of ops) {
    switch (op[0]) {
      case "save": stack.push([pen, brush, font]); ctx.save(); break;
      case "restore": if (stack.length) { [pen, brush, font] = stack.pop(); ctx.restore(); } break;
      case "tr": ctx.translate(op[1], op[2]); break;
      case "rot": ctx.rotate(op[1] * Math.PI / 180); break;
      case "sc": ctx.scale(op[1], op[2]); break;
      case "alpha": ctx.globalAlpha = outerAlpha * op[1]; break;
      case "clip": ctx.beginPath(); ctx.rect(op[1], op[2], op[3], op[4]); ctx.clip(); break;
      case "pen":
        pen = op.length > 1 ? { c: op[1], w: op[2], style: op[3], cap: op[4], join: op[5] } : null;
        break;
      case "brush": brush = op.length > 1 ? op[1] : null; break;
      case "font": font = fontCss(op[1], op[2], op[3]); break;
      case "line":
        if (!pen) break;
        ctx.beginPath(); ctx.moveTo(op[1], op[2]); ctx.lineTo(op[3], op[4]); applyPen(); ctx.stroke();
        break;
      case "rect": ctx.beginPath(); ctx.rect(op[1], op[2], op[3], op[4]); finish(true); break;
      case "rrect": {
        ctx.beginPath();
        const r = Math.max(0, Math.min(op[5], op[3] / 2, op[4] / 2));
        if (ctx.roundRect) ctx.roundRect(op[1], op[2], op[3], op[4], r); else ctx.rect(op[1], op[2], op[3], op[4]);
        finish(true);
        break;
      }
      case "ell":
        ctx.beginPath(); ctx.ellipse(op[1], op[2], Math.abs(op[3]), Math.abs(op[4]), 0, 0, 2 * Math.PI);
        finish(true);
        break;
      case "arc": {
        if (!pen) break;
        ctx.beginPath();
        const a0 = -op[5] * Math.PI / 180, a1 = -(op[5] + op[6]) * Math.PI / 180;
        ctx.ellipse(op[1], op[2], Math.abs(op[3]), Math.abs(op[4]), 0, a0, a1, op[6] > 0);
        applyPen(); ctx.stroke();
        break;
      }
      case "poly": {
        const p = op[2];
        if (p.length < 4) break;
        ctx.beginPath(); ctx.moveTo(p[0], p[1]);
        for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i], p[i + 1]);
        if (op[1]) ctx.closePath();
        finish(!!op[1], "evenodd");
        break;
      }
      case "path": {
        const cuts = op[1].filter((c) => c[0] === "X");
        if (cuts.length) {             // a shape with holes cut out (QPainterPath.subtracted): clip them away
          ctx.save();
          ctx.beginPath();
          ctx.rect(-1e5, -1e5, 2e5, 2e5);
          for (const cut of cuts) tracePath(ctx, cut[1]);
          ctx.clip("evenodd");
          ctx.beginPath();
          tracePath(ctx, op[1]);
          finish(true, "evenodd");
          ctx.restore();
          break;
        }
        ctx.beginPath();
        tracePath(ctx, op[1]);
        finish(true, "evenodd");
        break;
      }
      case "points": {
        if (!pen) break;
        const p = op[1];
        const w = pen.w > 0 ? pen.w : 1;
        ctx.fillStyle = pen.c;
        ctx.beginPath();
        for (let i = 0; i < p.length; i += 2) { ctx.moveTo(p[i] + w / 2, p[i + 1]); ctx.arc(p[i], p[i + 1], w / 2, 0, 2 * Math.PI); }
        ctx.fill();
        break;
      }
      case "text": drawText(ctx, op, pen, font); break;
    }
  }
  while (stack.length) { stack.pop(); ctx.restore(); }
}

function tracePath(ctx, cmds) {
  for (const c of cmds) {
    switch (c[0]) {
      case "M": ctx.moveTo(c[1], c[2]); break;
      case "L": ctx.lineTo(c[1], c[2]); break;
      case "Q": ctx.quadraticCurveTo(c[1], c[2], c[3], c[4]); break;
      case "C": ctx.bezierCurveTo(c[1], c[2], c[3], c[4], c[5], c[6]); break;
      case "Z": ctx.closePath(); break;
      case "E": ctx.moveTo(c[1] + c[3], c[2]); ctx.ellipse(c[1], c[2], c[3], c[4], 0, 0, 2 * Math.PI); break;
      case "A": {
        const a0 = -c[5] * Math.PI / 180, a1 = -(c[5] + c[6]) * Math.PI / 180;
        ctx.ellipse(c[1], c[2], Math.abs(c[3]), Math.abs(c[4]), 0, a0, a1, c[6] > 0);
        break;
      }
    }
  }
}

function drawText(ctx, op, pen, font) {
  if (!pen) return;
  const [, x, y, w, h, flags, text] = op;
  ctx.font = font;
  ctx.fillStyle = pen.c;
  const px = parseFloat(font.replace("bold ", "")) || 13;
  if (flags === -1) {                 // at a point, on the baseline
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    ctx.fillText(text, x, y);
    return;
  }
  const lines = String(text).split("\n");
  const lh = px * 1.25;
  let xa, align;
  if (flags & 0x2) { xa = x + w; align = "right"; }
  else if (flags & 0x4) { xa = x + w / 2; align = "center"; }
  else { xa = x; align = "left"; }
  let top;
  if (flags & 0x40) top = y + h - lines.length * lh;
  else if (flags & 0x80) top = y + h / 2 - lines.length * lh / 2;
  else top = y;
  ctx.textAlign = align;
  ctx.textBaseline = "middle";
  for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i], xa, top + lh * (i + 0.5) + px * 0.06);
}

// a small canvas showing recorded ops (gallery tiles, toolbar icons, dialogs)
function opsCanvas(canvas, ops, w, h, scale = 1) {
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
  ctx.clearRect(0, 0, w, h);
  replay(ctx, ops);
}

// ============================================================================================ loading Python
function setProgress(f, text) {
  $("progressBar").style.width = Math.round(f * 100) + "%";
  if (text) $("loadText").textContent = text;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(tr("couldn't load {src}", { src })));
    document.head.appendChild(s);
  });
}

async function setLanguage(code) {
  if (!LANGS.some(([c]) => c === code)) code = "en";
  lang = code;
  catalog = await loadCatalog(code);
  try { localStorage.setItem("wirely-language", code); } catch (e) { /* storage is off: it just isn't remembered */ }
  if (app) app.set_language(code);
  applyDom();
  if (ready) {
    refreshTexts();
    refreshUI();
    requestDraw();
  }
}

// the pieces of the page whose words come from Python (or were built from text): write them again
function refreshTexts() {
  setupGallery();
  const q = $("filter");
  if (q.value) q.dispatchEvent(new Event("input"));
  const sp = $("speed");
  J(app.speeds()).forEach(([label], i) => { if (sp.options[i]) sp.options[i].textContent = label; });
  const ch = J(app.graph_choices());
  for (const [id, list] of [["tbox", ch.time], ["vbox", ch.volts]]) {
    list.forEach((name, i) => { const o = $(id).options[i]; if (o) o.textContent = name; });
  }
  if (graphShown()) drawGraph();
}

async function boot() {
  try {
    lang = savedLanguage();
    catalog = await loadCatalog(lang);
    collectDom();
    applyDom();
    setProgress(0.05, tr("Loading Python (the first time takes a little while)…"));
    let base = "pyodide/";
    try {
      await loadScript(base + "pyodide.js");
    } catch (e) {
      base = PYODIDE_CDN;
      await loadScript(base + "pyodide.js");
    }
    setProgress(0.35, tr("Starting Python…"));
    py = await loadPyodide({ indexURL: base, stdout: (s) => console.log(s), stderr: (s) => console.warn(s) });
    setProgress(0.55, tr("Loading the maths library…"));
    let haveNumpy = false;
    if (params.get("numpy") !== "lite") {
      try {
        await py.loadPackage("numpy", { messageCallback: () => {}, errorCallback: (m) => console.warn(m) });
        py.runPython("import numpy");
        haveNumpy = true;
      } catch (e) {
        console.warn("numpy didn't load; using Wirely's built-in fallback", e);
      }
    }
    numpyKind = haveNumpy ? "numpy" : "built-in maths";
    setProgress(0.75, tr("Loading Wirely…"));
    const zipResp = await fetch("wirely-py.zip", { cache: "no-cache" });
    if (!zipResp.ok) throw new Error(tr("couldn't load wirely-py.zip ({status})", { status: zipResp.status }));
    py.unpackArchive(await zipResp.arrayBuffer(), "zip", { extractDir: "/home/pyodide/wirely_app" });
    py.runPython(`
import sys
sys.path.insert(0, "/home/pyodide/wirely_app")
if ${haveNumpy ? "False" : "True"}:
    sys.path.insert(0, "/home/pyodide/wirely_app/fallback")
`);
    setProgress(0.9, tr("Getting the parts ready…"));
    app = py.runPython("import wirely_web\nwirely_web.App()");
    app.set_language(lang);
    $("ver").textContent = "v" + app.version();
    await setupUI();
    ready = true;
    $("app").classList.remove("loading");
    await openStartCircuit();
    refreshUI();
    requestDraw();
  } catch (e) {
    console.error(e);
    $("loadText").classList.add("error");
    $("loadText").innerHTML = escapeHtml(tr("Sorry — Wirely couldn't start in this browser.")) + "<br>" + escapeHtml(String(e && e.message || e)) +
      "<br><br>" + escapeHtml(tr("Try reloading the page. Wirely works in recent versions of Chrome, Edge, Firefox and Safari.")) +
      ' <a href="https://github.com/wirely-app/wirely-app.github.io/releases/latest">' + escapeHtml(tr("You can also download the desktop app.")) + "</a>";
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const J = (s) => JSON.parse(s);

// ============================================================================================ the sheet view
const sheet = $("sheet");
const sctx = sheet.getContext("2d");
const view = { zoom: 1.6, cx: 0, cy: 0, w: 800, h: 600, dpr: 1 };
const defs = new Map();
let dirty = true;
let lastFrame = null;

function requestDraw() { dirty = true; }

function toSheet(sx, sy) {
  return [(sx - view.w / 2) / view.zoom + view.cx, (sy - view.h / 2) / view.zoom + view.cy];
}
function toScreen(x, y) {
  return [(x - view.cx) * view.zoom + view.w / 2, (y - view.cy) * view.zoom + view.h / 2];
}

function resize() {
  const r = sheet.getBoundingClientRect();
  view.dpr = Math.max(1, window.devicePixelRatio || 1);
  view.w = Math.max(50, r.width);
  view.h = Math.max(50, r.height);
  sheet.width = Math.round(view.w * view.dpr);
  sheet.height = Math.round(view.h * view.dpr);
  if (app) app.set_view(view.zoom, view.w, view.h);
  requestDraw();
  drawGraphSoon();
}

function setZoom(z, anchorX, anchorY) {
  z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
  if (anchorX === undefined) { anchorX = view.w / 2; anchorY = view.h / 2; }
  const [ax, ay] = toSheet(anchorX, anchorY);
  view.zoom = z;
  // keep the point under the anchor still
  view.cx = ax - (anchorX - view.w / 2) / z;
  view.cy = ay - (anchorY - view.h / 2) / z;
  if (app) app.set_view(view.zoom, view.w, view.h);
  $("zoomLabel").textContent = Math.round(z * 100 / 1.6) + "%";
  requestDraw();
}

function zoomFit(maxZoom) {
  let b = app ? J(app.bounds()) : null;
  let x, y, w, h;
  if (!b) { x = -200; y = -150; w = 400; h = 300; maxZoom = maxZoom || 1.6; }
  else { [x, y, w, h] = b; }
  x -= 40; y -= 40; w += 80; h += 80;
  const z = Math.max(ZOOM_MIN, Math.min(maxZoom || 2.2, Math.min(view.w / w, view.h / h)));
  view.zoom = z;
  view.cx = x + w / 2;
  view.cy = y + h / 2;
  if (app) app.set_view(view.zoom, view.w, view.h);
  $("zoomLabel").textContent = Math.round(z * 100 / 1.6) + "%";
  requestDraw();
}

function circuitInView() {
  const b = app ? J(app.bounds()) : null;
  if (!b) return false;
  const [x0, y0] = toSheet(0, 0), [x1, y1] = toSheet(view.w, view.h);
  return b[0] >= x0 && b[1] >= y0 && b[0] + b[2] <= x1 && b[1] + b[3] <= y1;
}

let gridCache = null, gridKey = "";
function drawGrid(ctx) {
  // the dots only change when you pan, zoom, resize or change theme: keep a ready-drawn copy
  const key = [view.cx, view.cy, view.zoom, view.w, view.h, view.dpr, sheet.width, sheet.height,
               colours.GRID_DOT, colours.GRID_DOT_MAJOR].join(",");
  if (key !== gridKey || !gridCache) {
    if (!gridCache) gridCache = document.createElement("canvas");
    gridCache.width = sheet.width;
    gridCache.height = sheet.height;
    const g = gridCache.getContext("2d");
    g.clearRect(0, 0, gridCache.width, gridCache.height);
    paintGrid(g);
    gridKey = key;
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(gridCache, 0, 0);
}

function paintGrid(ctx) {
  // the same dots as the desktop sheet (CircuitScene.drawBackground)
  const s = view.zoom;
  const step = s >= 0.9 ? GRID : s >= 0.45 ? GRID * 2 : GRID * 5;
  const [x0s, y0s] = toSheet(0, 0), [x1s, y1s] = toSheet(view.w, view.h);
  const x0 = Math.floor(x0s / step) * step, y0 = Math.floor(y0s / step) * step;
  const minorR = (s >= 0.9 ? 1.6 : 1.3) / 2, majorR = 2.4 / 2;
  const d = view.dpr;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = colours.GRID_DOT;
  const major = [];
  ctx.beginPath();
  for (let y = y0; y <= y1s; y += step) {
    const py = ((y - view.cy) * s + view.h / 2) * d;
    for (let x = x0; x <= x1s; x += step) {
      const px = ((x - view.cx) * s + view.w / 2) * d;
      if (x % 100 === 0 && y % 100 === 0) { major.push(px, py); continue; }
      ctx.rect(px - minorR * d, py - minorR * d, 2 * minorR * d, 2 * minorR * d);
    }
  }
  ctx.fill();
  ctx.fillStyle = colours.GRID_DOT_MAJOR;
  ctx.beginPath();
  for (let i = 0; i < major.length; i += 2) {
    ctx.moveTo(major[i] + majorR * d, major[i + 1]);
    ctx.arc(major[i], major[i + 1], majorR * d, 0, 2 * Math.PI);
  }
  ctx.fill();
}

function draw() {
  if (!app) return;
  const ctx = sctx;
  const [x0, y0] = toSheet(0, 0), [x1, y1] = toSheet(view.w, view.h);
  const f = J(app.frame(x0, y0, x1, y1));
  lastFrame = f;
  if (f.reset) defs.clear();
  if (f.defs) for (const k in f.defs) defs.set(+k, f.defs[k]);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.fillStyle = colours.CANVAS;
  ctx.fillRect(0, 0, sheet.width, sheet.height);
  if (ui.grid !== false) drawGrid(ctx);
  const d = view.dpr, z = view.zoom;
  const base = new DOMMatrix([d * z, 0, 0, d * z, d * (view.w / 2 - view.cx * z), d * (view.h / 2 - view.cy * z)]);
  for (const it of f.draw) {
    const ops = it[0] ? defs.get(it[0]) : it[4];
    if (!ops) continue;
    ctx.setTransform(base);
    ctx.translate(it[1], it[2]);
    ctx.globalAlpha = it[3];
    replay(ctx, ops, it[3]);
  }
  ctx.setTransform(base);
  ctx.globalAlpha = 1;
  replay(ctx, f.fg);
  if (f.band) {                       // rubber-band selection
    ctx.setTransform(base);
    ctx.fillStyle = hexAlpha(colours.ACCENT, 0.12);
    ctx.strokeStyle = colours.ACCENT;
    ctx.lineWidth = 1 / z;
    ctx.setLineDash([]);
    ctx.fillRect(...f.band);
    ctx.strokeRect(...f.band);
  }
  updateBubble(f.bubble);
  $("emptyHint").hidden = !(ui.empty && ui.mode !== "place");
}

function hexAlpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function updateBubble(b) {
  const el = $("bubble");
  if (!b) { el.hidden = true; return; }
  const [x, y, title, lines] = b;
  el.innerHTML = `<b>${escapeHtml(title)}</b>` + lines.map((t) => `<div>${escapeHtml(t)}</div>`).join("");
  el.hidden = false;
  const [sx, sy] = toScreen(x, y);
  const w = el.offsetWidth, h = el.offsetHeight;
  let left = sx + 16, top = sy + 16;
  if (left + w > view.w - 4) left = sx - 12 - w;
  if (top + h > view.h - 4) top = sy - 12 - h;
  el.style.left = Math.max(2, left) + "px";
  el.style.top = Math.max(2, top) + "px";
}

// ============================================================================================ the main loop
let lastTick = 0, lastUi = 0;
function loop(t) {
  if (ready) {
    if (ui.sim === "running" && t - lastTick >= 30) {
      lastTick = t;
      if (app.tick()) dirty = true;     // false when nothing on the sheet looks any different
      afterTick();
    }
    if (dirty) {
      dirty = false;
      try { draw(); } catch (e) { console.error(e); }
    }
    if (ui.running && t - lastUi > 400) { lastUi = t; refreshUI(); }
  }
  requestAnimationFrame(loop);
}

function afterTick() {
  const info = J(app.sim_info());
  showToasts();
  if (!info) { refreshUI(); return; }
  $("timeLabel").textContent = info.time;
  $("timeLabel").title = info.behind ? tr("This circuit is too busy to simulate in real time, so it runs slower.")
    : tr("Simulated time since you pressed Run");
  updateLegend(info);
  Sound.update(info.sound, info.clicks);
  if (graphShown()) drawGraph();
}

let legendVmax = null;
function updateLegend(info) {
  const el = $("legend");
  const show = info && info.volts;
  el.hidden = !show;
  if (!show || legendVmax === info.vmax) return;
  legendVmax = info.vmax;
  const stops = J(app.volt_stops(info.vmax));
  $("legendBar").style.background = `linear-gradient(to right, ${stops.map((c, i) => `${c} ${i * 10}%`).join(", ")})`;
  $("legendMid").textContent = fmtV(info.vmax / 2);
  $("legendMax").textContent = fmtV(info.vmax);
}
function fmtV(v) {
  return py.globals.get("wirely_web").fmt(v, "V");
}

// ============================================================================================ mouse, touch and keys
const BUTTON = { 0: 1, 1: 4, 2: 2 };
let pan = null;                 // {x, y, cx, cy} while panning
let spaceDown = false;
let lastDown = null;            // for spotting double clicks
const touches = new Map();      // pointerId -> {x, y}
let pinch = null;

function mods(e) { return (e.shiftKey ? QT_SHIFT : 0) | (e.ctrlKey || e.metaKey ? QT_CTRL : 0); }
function localXY(e) { const r = sheet.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function handleReply(s) {
  const r = J(s);
  sheet.style.cursor = pan ? "grabbing" : spaceDown ? "grab" : (r.cursor || "default");
  if (r.edit) setTimeout(() => editPart(r.edit), 0);
}

sheet.addEventListener("contextmenu", (e) => e.preventDefault());

sheet.addEventListener("pointerdown", (e) => {
  if (!ready) return;
  sheet.focus({ preventScroll: true });
  closeMenus();
  Sound.unlock();
  const [lx, ly] = localXY(e);
  if (e.pointerType === "touch") {
    touches.set(e.pointerId, { x: lx, y: ly });
    if (touches.size === 2) {           // two fingers: pinch to zoom and pan
      app.escape();
      const [a, b] = [...touches.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, zoom: view.zoom };
      pan = null;
      requestDraw();
      return;
    }
  }
  sheet.setPointerCapture(e.pointerId);
  const [x, y] = toSheet(lx, ly);
  if (e.button === 1 || (e.button === 0 && spaceDown) ||
      (e.pointerType === "touch" && app.hit(x, y) === "none" && !ui.wiring && ui.mode !== "place")) {
    pan = { x: lx, y: ly, cx: view.cx, cy: view.cy };
    sheet.style.cursor = "grabbing";
    e.preventDefault();
    return;
  }
  if (e.button === 2) {
    const busy = ui.wiring || ui.mode === "place";
    app.press(x, y, 2, e.buttons, mods(e), lx, ly);
    if (!busy) { showContextMenu(x, y, e.clientX, e.clientY); e.stopPropagation(); }
    refreshUI();
    requestDraw();
    return;
  }
  const now = performance.now();
  const dbl = lastDown && now - lastDown.t < 400 && Math.hypot(lx - lastDown.x, ly - lastDown.y) < 6 && e.button === 0;
  lastDown = dbl ? null : { t: now, x: lx, y: ly };
  if (dbl) handleReply(app.dblclick(x, y, mods(e), lx, ly));
  else handleReply(app.press(x, y, BUTTON[e.button] || 1, e.buttons, mods(e), lx, ly));
  refreshUI();
  requestDraw();
});

sheet.addEventListener("pointermove", (e) => {
  if (!ready) return;
  const [lx, ly] = localXY(e);
  if (e.pointerType === "touch" && touches.has(e.pointerId)) {
    touches.set(e.pointerId, { x: lx, y: ly });
    if (pinch && touches.size >= 2) {
      const [a, b] = [...touches.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      setZoom(pinch.zoom * d / Math.max(1, pinch.d), mx, my);
      view.cx -= (mx - pinch.mx) / view.zoom;
      view.cy -= (my - pinch.my) / view.zoom;
      pinch.mx = mx; pinch.my = my;
      requestDraw();
      return;
    }
  }
  if (pan) {
    view.cx = pan.cx - (lx - pan.x) / view.zoom;
    view.cy = pan.cy - (ly - pan.y) / view.zoom;
    requestDraw();
    return;
  }
  const [x, y] = toSheet(lx, ly);
  handleReply(app.move(x, y, e.buttons, mods(e), lx, ly));
  if (e.buttons) refreshStatus();
  requestDraw();
});

function endPointer(e) {
  if (!ready) return;
  const [lx, ly] = localXY(e);
  if (e.pointerType === "touch") {
    touches.delete(e.pointerId);
    if (pinch) { if (touches.size < 2) pinch = null; return; }
  }
  if (pan) {
    pan = null;
    sheet.style.cursor = spaceDown ? "grab" : "default";
    return;
  }
  if (e.type === "pointercancel") { app.escape(); refreshUI(); requestDraw(); return; }
  const [x, y] = toSheet(lx, ly);
  handleReply(app.release(x, y, BUTTON[e.button] || 1, e.buttons, mods(e), lx, ly));
  refreshUI();
  requestDraw();
}
sheet.addEventListener("pointerup", endPointer);
sheet.addEventListener("pointercancel", endPointer);
sheet.addEventListener("pointerleave", (e) => {
  if (ready && !e.buttons) { app.leave(); requestDraw(); }
});

sheet.addEventListener("wheel", (e) => {
  if (!ready) return;
  e.preventDefault();
  const [lx, ly] = localXY(e);
  const [x, y] = toSheet(lx, ly);
  if (!e.ctrlKey && app.wheel_slider(x, y, -e.deltaY)) { requestDraw(); return; }
  // a mouse wheel zooms (like the desktop app); a touchpad's two-finger scroll pans and its pinch zooms
  const mouseWheel = e.deltaMode === 1 || (e.deltaX === 0 && Math.abs(e.deltaY) >= 50 && Number.isInteger(e.deltaY));
  if (e.ctrlKey || mouseWheel) {
    const k = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaY;
    setZoom(view.zoom * Math.pow(1.18, -k / (e.ctrlKey && !mouseWheel ? 40 : 120)), lx, ly);
  } else {
    view.cx += (e.shiftKey ? e.deltaY : e.deltaX) / view.zoom;
    view.cy += (e.shiftKey ? 0 : e.deltaY) / view.zoom;
  }
  requestDraw();
}, { passive: false });

function typing(e) {
  const t = e.target;
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

window.addEventListener("keydown", (e) => {
  if (!ready) return;
  if (!$("modal").hidden) {
    if (e.key === "Escape") { closeDialog(); e.preventDefault(); }
    return;
  }
  if (typing(e)) return;
  const ctrl = e.ctrlKey || e.metaKey, k = e.key;
  let act = null;
  if (k === " " && !e.repeat && ui.mode !== "place") {
    spaceDown = true; sheet.style.cursor = "grab"; e.preventDefault(); return;
  }
  if (ctrl) {
    const m = { z: e.shiftKey ? "redo" : "undo", y: "redo", x: "cut", c: "copy", v: "paste", d: "duplicate", a: "select_all",
      s: e.shiftKey ? "save_as" : "save", o: "open", e: "export", g: "graph", 0: "zoom_fit", "=": "zoom_in", "+": "zoom_in",
      "-": "zoom_out" };
    act = m[k.toLowerCase()];
    if (k === "C" && e.shiftKey) act = "copy_picture";
  } else if (e.altKey) {
    return;
  } else {
    const m = { Escape: "escape", Delete: "delete", Backspace: "delete", Enter: "props", w: "wire", W: "wire",
      f: "flip", F: "flip", g: "grid", G: "grid", "+": "zoom_in", "=": "zoom_in", "-": "zoom_out", F1: "help",
      F5: e.shiftKey ? "stop" : "play", F6: "pause", F7: "stop" };
    act = m[k];
    if (k === "r" || k === "R") act = e.shiftKey ? "rotate_ccw" : "rotate";
  }
  if (act) { e.preventDefault(); doAction(act); }
});
window.addEventListener("keyup", (e) => {
  if (e.key === " ") { spaceDown = false; if (!pan) sheet.style.cursor = "default"; }
});
window.addEventListener("blur", () => { spaceDown = false; });

// ============================================================================================ actions
const ACTIONS = {
  new: () => confirmDiscard(() => { app.new(); Files.handle = null; afterOpen(); }),
  open: () => confirmDiscard(() => Files.open()),
  save: () => Files.save(false),
  save_as: () => Files.save(true),
  export: () => exportPicture(false),
  copy_picture: () => exportPicture(true),
  bom: () => showBom(),
  share: () => shareLink(),
  help: () => showHelp(),
  about: () => showAbout(),
  zoom_in: () => setZoom(view.zoom * 1.25),
  zoom_out: () => setZoom(view.zoom * 0.8),
  zoom_fit: () => zoomFit(),
  fit: () => zoomFit(),
  escape: () => app.escape(),
  dark: () => setTheme(ui.dark ? "light" : "dark"),
  us_symbols: () => setSymbols(ui.us ? "uk" : "us"),
  props: () => { const cid = app.action("props"); if (cid) editPart(cid); },
  copy: () => { const t = app.action("copy"); if (t) clipboardWrite(t); },
  copy_readings: () => {
    const t = app.action("copy_readings");
    if (t) { clipboardWrite(t); toast(tr("Readings copied — paste them into a spreadsheet or document."), "ok", null, 3000); }
    else toast(tr("Press Run first — then copy the readings."), "info");
  },
  cut: () => { const t = app.action("cut"); if (t) clipboardWrite(t); },
  paste: () => pasteFromClipboard(),
  play: () => { Sound.unlock(); const err = app.run(); if (err) console.warn(err); afterRunChange(); },
  stop: () => { app.stop(); afterRunChange(); },
  pause: () => { app.action("pause"); afterRunChange(); },
  graph: () => { app.action("graph"); refreshUI(); drawGraphSoon(); },
};

function doAction(name) {
  if (!ready) return;
  closeMenus();
  const fn = ACTIONS[name];
  if (fn) fn(); else app.action(name);
  showToasts();
  refreshUI();
  requestDraw();
}

function afterRunChange() {
  refreshUI();
  if (ui.sim === "stopped") {
    $("timeLabel").textContent = "";
    $("legend").hidden = true;
    legendVmax = null;
    clearToasts();
    Sound.stopAll();
  } else {
    afterTick();
  }
  drawGraphSoon();
  requestDraw();
}

function clipboardWrite(text) {
  try { navigator.clipboard && navigator.clipboard.writeText(text).catch(() => {}); } catch (e) { /* not allowed */ }
}
async function pasteFromClipboard() {
  let text = null;
  try { if (navigator.clipboard && navigator.clipboard.readText) text = await navigator.clipboard.readText(); } catch (e) { /* not allowed */ }
  if (text && text.trim().startsWith("{") && text.includes('"components"')) {
    if (app.paste_text(text)) { refreshUI(); requestDraw(); return; }
  }
  app.action("paste");
  refreshUI();
  requestDraw();
}

// ============================================================================================ toolbar, menus, status
const toolButtons = {};
function setupToolbar() {
  const icons = J(app.toolbar_icons(JSON.stringify(TOOL_ICONS)));
  document.querySelectorAll("#toolbar .tool").forEach((b) => {
    const name = b.dataset.act;
    toolButtons[name] = b;
    const icon = icons[ICON_FOR[name] || name];
    if (icon) {
      const c = document.createElement("canvas");
      b.prepend(c);
      opsCanvas(c, icon, 24, 24, 0.75);
    }
    b.addEventListener("click", () => { doAction(name); sheet.focus({ preventScroll: true }); });
  });
  const sp = $("speed");
  for (const [label, v] of J(app.speeds())) {
    const o = document.createElement("option");
    o.textContent = label; o.value = v;
    if (v === 1) o.selected = true;
    sp.appendChild(o);
  }
  sp.addEventListener("change", () => app.set_speed(parseFloat(sp.value)));
  opsCanvas($("logoMark"), J(app.logo_ops()), 26, 26, 26 / 32);
  opsCanvas($("splashMark"), J(app.logo_ops()), 96, 96, 3);
}

function refreshUI() {
  if (!app) return;
  ui = J(app.state());
  const tb = toolButtons;
  const running = ui.running, stopped = ui.sim === "stopped";
  const en = (name, on) => { if (tb[name]) tb[name].disabled = !on; };
  const chk = (name, on) => { if (tb[name]) tb[name].classList.toggle("checked", !!on); };
  en("new", !running); en("open", !running); en("undo", ui.undo); en("redo", ui.redo);
  en("select", !running); en("wire", !running);
  chk("select", ui.mode !== "wire"); chk("wire", ui.mode === "wire");
  en("rotate", (ui.comps > 0 || ui.mode === "place") && !running);
  en("flip", (ui.comps > 0 || ui.mode === "place") && !running);
  en("delete", ui.sel && !running);
  en("play", ui.sim !== "running"); en("pause", ui.sim === "running"); en("stop", !stopped);
  tb.play.title = (ui.sim === "paused" ? tr("Resume") : tr("Run the circuit — watch it work")) + "  (F5)";
  tb.play.querySelector(".label").textContent = ui.sim === "paused" ? tr("Resume") : tr("Run");
  chk("volts", ui.volts); chk("flow", ui.flow); chk("readings", ui.readings); chk("sound", ui.sound); chk("graph", ui.graph); chk("dark", ui.dark);
  $("gallery").classList.toggle("disabled", !stopped);
  $("hint").textContent = ui.status;
  $("counts").textContent = ui.counts;
  $("docname").textContent = ui.name + (ui.dirty ? "  •" : "");
  document.title = `${ui.name}${ui.dirty ? " *" : ""} – Wirely`;
  document.querySelectorAll(".tile").forEach((t) => t.classList.toggle("armed", t.dataset.kind === ui.place));
  $("graphPanel").hidden = !ui.graph;
  if (!ui.graph !== graphWasHidden) {
    // the graph panel opened or closed: if the whole circuit was in view, keep it all in view
    graphWasHidden = !ui.graph;
    const wasAll = circuitInView();
    resize();
    if (wasAll && !circuitInView()) zoomFit();
  }
  $("emptyHint").hidden = !(ui.empty && ui.mode !== "place");
}
let graphWasHidden = true;
function refreshStatus() {
  if (!app) return;
  const s = J(app.state());
  $("hint").textContent = s.status;
}

const MENUS = {
  file: () => [
    ["New circuit", "new", "", !ui.running],
    ["Open…", "open", "Ctrl+O", !ui.running],
    ["Open example", "examples", "▸", !ui.running],
    null,
    ["Save", "save", "Ctrl+S"],
    ["Save as…", "save_as", "Ctrl+Shift+S"],
    null,
    ["Save picture (PNG)…", "export", "Ctrl+E"],
    ["Copy picture", "copy_picture", "Ctrl+Shift+C"],
    ["Copy a link to this circuit", "share", ""],
    ["Bill of materials…", "bom", ""],
  ],
  edit: () => [
    ["Undo", "undo", "Ctrl+Z", ui.undo], ["Redo", "redo", "Ctrl+Y", ui.redo], null,
    ["Cut", "cut", "Ctrl+X", ui.sel && !ui.running], ["Copy", "copy", "Ctrl+C", ui.sel],
    ["Paste", "paste", "Ctrl+V", !ui.running], ["Duplicate", "duplicate", "Ctrl+D", ui.sel && !ui.running],
    ["Delete", "delete", "Del", ui.sel && !ui.running], ["Select all", "select_all", "Ctrl+A", !ui.running], null,
    ["Rotate", "rotate", "R", ui.comps > 0 && !ui.running], ["Rotate anticlockwise", "rotate_ccw", "Shift+R", ui.comps > 0 && !ui.running],
    ["Flip", "flip", "F", ui.comps > 0 && !ui.running], ["Properties…", "props", "Enter", ui.comps === 1],
  ],
  simulate: () => [
    [ui.sim === "paused" ? "Resume" : "Run", "play", "F5", ui.sim !== "running"], ["Pause", "pause", "F6", ui.sim === "running"],
    ["Stop", "stop", "F7", ui.sim !== "stopped"], null,
    [check(ui.volts) + "Voltage colours", "volts", ""], [check(ui.flow) + "Current flow", "flow", ""],
    [check(ui.readings) + "Readings", "readings", ""], ["Copy readings", "copy_readings", "", ui.sim !== "stopped"],
    [check(ui.graph) + "Graph", "graph", "Ctrl+G"], [check(ui.sound) + "Sound", "sound", ""],
  ],
  view: () => [
    ["Zoom in", "zoom_in", "+"], ["Zoom out", "zoom_out", "−"], ["Zoom to fit", "zoom_fit", "Ctrl+0"], null,
    [check(ui.grid) + "Show grid", "grid", "G"], [check(ui.dark) + "Dark theme", "dark", ""],
    [check(ui.us) + "US symbols", "us_symbols", ""],
  ],
  language: () => LANGS.map(([code, name]) => [check(code === lang) + name, "lang:" + code, ""]),
  help: () => [
    ["Mouse and keyboard…", "help", "F1"],
    ["Get the desktop app", "desktop", ""],
    ["Wirely on GitHub", "github", ""],
    null,
    ["About Wirely", "about", ""],
  ],
};
function check(on) { return on ? "✓ " : " "; }
// menu text is written in English above; show it in the chosen language (keeping the tick in front)
function trItems(items) {
  return items.map((it) => {
    if (it === null) return null;
    if (typeof it === "string") return tr(it);
    const pre = /^(✓ |\u2003)/.exec(it[0]);
    const p = pre ? pre[0] : "";
    return [p + tr(it[0].slice(p.length)), ...it.slice(1)];
  });
}

let openMenu = null;
function closeMenus() {
  $("menuPopup").hidden = true;
  document.querySelectorAll(".menuBtn.open").forEach((b) => b.classList.remove("open"));
  openMenu = null;
}

function showPopup(items, x, y, onPick) {
  const pop = $("menuPopup");
  pop.innerHTML = "";
  for (const it of items) {
    if (it === null) { pop.appendChild(document.createElement("hr")); continue; }
    if (typeof it === "string") {
      const h = document.createElement("div"); h.className = "heading"; h.textContent = it; pop.appendChild(h); continue;
    }
    const [label, act, key, enabled = true] = it;
    const b = document.createElement("button");
    b.innerHTML = `<span>${escapeHtml(label)}</span>${key ? `<span class="key">${escapeHtml(key)}</span>` : ""}`;
    b.disabled = !enabled;
    b.addEventListener("click", (e) => { e.stopPropagation(); onPick(act, b); });
    pop.appendChild(b);
  }
  pop.hidden = false;
  const r = pop.getBoundingClientRect();
  pop.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 4)) + "px";
  pop.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) + "px";
}

function pickMenu(act) {
  if (act.startsWith("lang:")) { closeMenus(); setLanguage(act.slice(5)); return; }
  if (act === "examples") { showExamplesMenu(); return; }
  if (act === "desktop") { window.open("https://github.com/wirely-app/wirely-app.github.io/releases/latest", "_blank", "noopener"); closeMenus(); return; }
  if (act === "github") { window.open("https://github.com/wirely-app/wirely-app.github.io", "_blank", "noopener"); closeMenus(); return; }
  doAction(act);
}

document.querySelectorAll(".menuBtn").forEach((b) => {
  const open = () => {
    if (!ready) return;
    closeMenus();
    refreshUI();
    openMenu = b.dataset.menu;
    b.classList.add("open");
    const r = b.getBoundingClientRect();
    const items = MENUS[openMenu]();
    showPopup(openMenu === "language" ? items : trItems(items), r.left, r.bottom + 2, pickMenu);
  };
  b.addEventListener("click", (e) => { e.stopPropagation(); if (openMenu === b.dataset.menu) closeMenus(); else open(); });
  b.addEventListener("mouseenter", () => { if (openMenu && openMenu !== b.dataset.menu) open(); });
});
document.addEventListener("pointerdown", (e) => {
  if (!$("menuPopup").contains(e.target) && !e.target.classList.contains("menuBtn")) closeMenus();
});

function showContextMenu(x, y, cx, cy) {
  const items = J(app.context(x, y)).map((it) => it && [it[0], it[1], it[2], true]);
  if (!items.length) return;
  requestDraw();
  refreshUI();
  showPopup(items, cx, cy, (act) => doAction(act));
}

// ============================================================================================ gallery
function setupGallery() {
  const list = $("galleryList");
  list.innerHTML = "";
  const cats = J(app.gallery());
  for (const cat of cats) {
    const head = document.createElement("button");
    head.className = "catHeader";
    head.textContent = cat.name;
    const tiles = document.createElement("div");
    tiles.className = "tiles";
    head.addEventListener("click", () => { tiles.hidden = !tiles.hidden; head.classList.toggle("closed", tiles.hidden); });
    for (const p of cat.parts) {
      const t = document.createElement("div");
      t.className = "tile";
      t.dataset.kind = p.key;
      t.dataset.search = (p.name + " " + p.tile + " " + p.keywords + " " + cat.search).toLowerCase();
      t.title = `${p.name}\n${p.description}\n${tr("Click, then click on the sheet — or drag it there.")}`;
      const c = document.createElement("canvas");
      opsCanvas(c, p.icon, 62, 40);
      const s = document.createElement("span");
      s.textContent = p.tile;
      t.append(c, s);
      tileDrag(t, p.key);
      tiles.appendChild(t);
    }
    list.append(head, tiles);
  }
}

$("filter").addEventListener("input", () => {
  const q = $("filter").value.trim().toLowerCase();
  document.querySelectorAll("#galleryList .tiles").forEach((tiles) => {
    let any = false;
    tiles.querySelectorAll(".tile").forEach((t) => {
      const show = !q || q.split(/\s+/).every((w) => t.dataset.search.includes(w));
      t.hidden = !show;
      any = any || show;
    });
    tiles.hidden = !any && !!q;
    tiles.previousSibling.hidden = !any && !!q;
    if (!q) { tiles.hidden = tiles.previousSibling.classList.contains("closed"); }
  });
});

function tileDrag(tile, kind) {
  // click a tile then click the sheet, or drag the tile onto the sheet (mouse or finger)
  tile.addEventListener("pointerdown", (e) => {
    if (!ready || ui.running || e.button !== 0) return;
    e.preventDefault();
    const sx = e.clientX, sy = e.clientY;
    let dragging = false;
    tile.setPointerCapture(e.pointerId);
    const move = (ev) => {
      if (!dragging && Math.hypot(ev.clientX - sx, ev.clientY - sy) > 6) {
        dragging = true;
        app.start_placing(kind, false);
        refreshUI();
      }
      if (dragging) {
        const r = sheet.getBoundingClientRect();
        const inside = ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
        if (inside) {
          const lx = ev.clientX - r.left, ly = ev.clientY - r.top;
          const [x, y] = toSheet(lx, ly);
          app.move(x, y, 0, 0, lx, ly);
        } else {
          app.leave();
        }
        requestDraw();
      }
    };
    const up = (ev) => {
      tile.removeEventListener("pointermove", move);
      tile.removeEventListener("pointerup", up);
      tile.removeEventListener("pointercancel", up);
      if (!dragging) {                       // a click: pick it up, place it with the next click on the sheet
        app.start_placing(kind, ev.shiftKey);
        refreshUI();
        sheet.focus({ preventScroll: true });
        return;
      }
      const r = sheet.getBoundingClientRect();
      const inside = ev.type === "pointerup" && ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
      if (inside) {
        const lx = ev.clientX - r.left, ly = ev.clientY - r.top;
        const [x, y] = toSheet(lx, ly);
        app.move(x, y, 0, 0, lx, ly);
        app.press(x, y, 1, 1, 0, lx, ly);
        app.release(x, y, 1, 0, 0, lx, ly);
      } else {
        app.escape();
      }
      refreshUI();
      requestDraw();
      sheet.focus({ preventScroll: true });
    };
    tile.addEventListener("pointermove", move);
    tile.addEventListener("pointerup", up);
    tile.addEventListener("pointercancel", up);
  });
}

$("galleryToggle").addEventListener("click", () => { $("app").classList.add("noGallery"); $("showGallery").hidden = false; resize(); });
$("showGallery").addEventListener("click", () => { $("app").classList.remove("noGallery"); $("showGallery").hidden = true; resize(); });

// ============================================================================================ toasts
const toastBox = $("toasts");
function toast(text, kind = "warn", buttons = null, life = 7000) {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = text;
  if (buttons) for (const [label, fn] of buttons) {
    const b = document.createElement("button");
    b.textContent = label;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(); remove(); });
    t.appendChild(b);
  }
  const remove = () => { t.classList.add("fade"); setTimeout(() => t.remove(), 350); };
  t.addEventListener("click", remove);
  toastBox.appendChild(t);
  while (toastBox.children.length > 4) toastBox.firstChild.remove();
  if (life) setTimeout(remove, life);
  return t;
}
function clearToasts() { toastBox.innerHTML = ""; }
function showToasts() {
  for (const [text, kind] of J(app.take_toasts())) toast(text, kind);
}

// ============================================================================================ dialogs
function openDialog(html, onReady) {
  const d = $("dialog");
  d.innerHTML = html;
  $("modal").hidden = false;
  if (onReady) onReady(d);
  const f = d.querySelector("[autofocus]") || d.querySelector("input, select, textarea, button");
  if (f) setTimeout(() => f.focus({ preventScroll: true }), 0);
  d.scrollTop = 0;
}
function closeDialog() {
  $("modal").hidden = true;
  $("dialog").innerHTML = "";
  sheet.focus({ preventScroll: true });
  refreshUI();
  requestDraw();
}
$("modal").addEventListener("pointerdown", (e) => { if (e.target === $("modal")) closeDialog(); });

function editPart(cid) {
  const form = J(app.part_form(cid));
  if (!form) return;
  let html = `<div class="dlgTop"><canvas id="dlgIcon"></canvas><div><div class="dlgTitle">${escapeHtml(form.name)}</div>
    <div class="hint">${escapeHtml(form.description)}</div></div></div><div class="form">
    <label for="f__ref">${escapeHtml(tr("Label"))}</label><input type="text" id="f__ref" value="${escapeHtml(form.ref)}" title="${escapeHtml(tr("The label on the diagram, e.g. R1"))}">`;
  for (const f of form.fields) {
    const id = "f_" + f.key;
    html += `<label for="${id}">${escapeHtml(f.label)}</label>`;
    if (f.kind === "bool") html += `<div><input type="checkbox" id="${id}" ${f.value ? "checked" : ""}></div>`;
    else if (f.kind === "text") html += `<textarea id="${id}">${escapeHtml(f.value)}</textarea>`;
    else if (f.kind === "choice") {
      // the value that is saved stays English; only the words shown are translated
      const opts = f.choices.map((c, i) => `<option value="${escapeHtml(c)}" ${c === f.value ? "selected" : ""} title="${escapeHtml((f.info && f.info[c]) || "")}">${escapeHtml(f.choice_labels ? f.choice_labels[i] : c)}</option>`).join("");
      if (f.colours) html += `<div class="swatchRow"><span class="swatch" id="${id}_sw"></span><select id="${id}">${opts}</select></div>`;
      else html += `<select id="${id}">${opts}</select>`;
      if (f.info) html += `<div class="hint info" id="${id}_info"></div>`;
    } else if (f.units) {           // the number, with its size beside it: Ω / kΩ / MΩ, pF / nF / µF …
      const opts = f.units.map((u) => `<option ${u === f.unit ? "selected" : ""}>${escapeHtml(u)}</option>`).join("");
      html += `<div class="unitRow"><input type="text" id="${id}" value="${escapeHtml(f.value)}" placeholder="${escapeHtml(f.placeholder || "")}" title="${escapeHtml(f.help || "")}" spellcheck="false" autocomplete="off" inputmode="decimal"><select id="${id}__unit" title="${escapeHtml(tr("Ω, kΩ (thousand), MΩ (million) … or pF, nF, µF …"))}">${opts}</select></div>`;
    } else {
      html += `<input type="text" id="${id}" value="${escapeHtml(f.value)}" placeholder="${escapeHtml(f.placeholder || "")}" title="${escapeHtml(f.help || "")}" spellcheck="false" autocomplete="off">`;
    }
  }
  html += `</div><div class="dlgError" id="dlgError"></div>
    <div class="dlgButtons"><button class="btn" id="dlgCancel">${escapeHtml(tr("Cancel"))}</button><button class="btn primary" id="dlgOk">${escapeHtml(tr("OK"))}</button></div>`;
  openDialog(html, (d) => {
    opsCanvas(d.querySelector("#dlgIcon"), form.icon, 76, 50);
    const read = () => {
      const v = { _ref: d.querySelector("#f__ref").value };
      for (const f of form.fields) {
        const el = d.querySelector("#f_" + f.key);
        v[f.key] = f.kind === "bool" ? el.checked : el.value;
        if (f.units) v[f.key + "__unit"] = d.querySelector("#f_" + f.key + "__unit").value;
      }
      return v;
    };
    const validate = () => {
      const r = J(app.check_form(cid, JSON.stringify(read())));
      d.querySelectorAll(".invalid").forEach((el) => el.classList.remove("invalid"));
      for (const k of r.bad) { const el = d.querySelector(k === "_ref" ? "#f__ref" : "#f_" + k); if (el) el.classList.add("invalid"); }
      d.querySelector("#dlgError").textContent = r.error;
      d.querySelector("#dlgOk").disabled = !!r.error;
    };
    const ok = () => {
      const err = app.apply_form(cid, JSON.stringify(read()));
      if (err) { d.querySelector("#dlgError").textContent = err; return; }
      closeDialog();
    };
    for (const f of form.fields) {
      const el = d.querySelector("#f_" + f.key);
      el.addEventListener("input", validate);
      el.addEventListener("change", validate);
      if (f.units) {
        const box = d.querySelector("#f_" + f.key + "__unit");
        box.addEventListener("change", validate);
        // typed the whole value (4k7, 100n)? show it as a number and its size in the box
        el.addEventListener("blur", () => {
          if (/^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$/.test(el.value)) return;
          const t = J(app.tidy_value(cid, f.key, el.value, box.value));
          if (t) { el.value = t[0]; box.value = t[1]; validate(); }
        });
      }
      if (f.colours) {
        const sw = d.querySelector(`#f_${f.key}_sw`);
        const upd = () => { sw.style.background = f.colours[el.value] || "transparent"; };
        el.addEventListener("change", upd); upd();
      }
      if (f.info) {
        const info = d.querySelector(`#f_${f.key}_info`);
        const upd = () => { info.textContent = f.info[el.value] || ""; };
        el.addEventListener("change", upd); upd();
      }
    }
    d.querySelector("#f__ref").addEventListener("input", validate);
    d.querySelector("#dlgCancel").addEventListener("click", closeDialog);
    d.querySelector("#dlgOk").addEventListener("click", ok);
    d.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && !d.querySelector("#dlgOk").disabled) { e.preventDefault(); ok(); }
    });
    const first = form.fields.find((f) => f.kind === "number" || f.kind === "text");
    const fe = first ? d.querySelector("#f_" + first.key) : null;
    if (fe) { setTimeout(() => { fe.focus(); if (fe.select) fe.select(); }, 0); }
  });
}

function showBom() {
  const rows = J(app.bom());
  const n = rows.reduce((a, r) => a + r.qty, 0);
  const body = rows.map((r) => `<tr><td>${r.qty}</td><td>${escapeHtml(r.description)}</td><td>${escapeHtml(r.refs.join(", "))}</td></tr>`).join("");
  openDialog(`<div class="dlgTitle">${escapeHtml(tr("Parts list — {n} parts", { n }))}</div>
    <table class="bom"><tr><th>${escapeHtml(tr("Qty"))}</th><th>${escapeHtml(tr("Part"))}</th><th>${escapeHtml(tr("Labels"))}</th></tr>${body}</table>
    <div class="dlgButtons"><button class="btn" id="bomCopy">${escapeHtml(tr("Copy"))}</button><button class="btn" id="bomCsv">${escapeHtml(tr("Save as CSV…"))}</button>
    <span class="spacer"></span><button class="btn primary" id="bomClose">${escapeHtml(tr("Close"))}</button></div>`, (d) => {
    d.querySelector("#bomClose").addEventListener("click", closeDialog);
    d.querySelector("#bomCopy").addEventListener("click", () => {
      clipboardWrite([tr("Qty"), tr("Part"), tr("Labels")].join("\t") + "\n" + rows.map((r) => `${r.qty}\t${r.description}\t${r.refs.join(", ")}`).join("\n"));
      toast(tr("Parts list copied."), "ok", null, 2500);
    });
    d.querySelector("#bomCsv").addEventListener("click", () => download(new Blob([app.bom_csv()], { type: "text/csv" }), tr("parts list") + ".csv"));
  });
}

function showHelp() {
  const rows = J(py.runPython(`
import json
from wirely.ui.dialogs import SHORTCUTS
json.dumps(SHORTCUTS)`));
  const web = [["On a Chromebook or touchpad", "Two-finger scroll pans; pinch (or Ctrl + scroll) zooms"],
    ["On a touch screen", "Drag the sheet with one finger to pan, pinch to zoom; double-tap a part to change it"],
    ["Save your work", "Ctrl+S saves a .wirely file you can open again here or in the desktop app"]];
  const html = rows.concat(web).map(([a, b]) => `<b>${escapeHtml(tr(a))}</b><span>${escapeHtml(tr(b))}</span>`).join("");
  openDialog(`<div class="dlgTitle">${escapeHtml(tr("Mouse and keyboard"))}</div><div class="keys">${html}</div>
    <div class="dlgButtons"><button class="btn primary" id="hClose">${escapeHtml(tr("Close"))}</button></div>`,
    (d) => d.querySelector("#hClose").addEventListener("click", closeDialog));
}

function showAbout() {
  const v = app.version();
  openDialog(`<div class="about"><div class="dlgTop"><canvas id="abMark"></canvas><div><div class="dlgTitle">${escapeHtml(tr("Wirely {version} — web version", { version: v }))}</div>
    <div class="hint">${escapeHtml(tr("Draw a circuit, press play, watch it work."))}</div></div></div>
    <p>${escapeHtml(tr("Free and open source under the GNU GPL v3. By Richard Willmott, built with help from Claude."))}</p>
    <p>${escapeHtml(tr("This is the same Wirely as the desktop app — the same parts, drawings and simulator — running in your browser with"))}
    <a href="https://pyodide.org" target="_blank" rel="noopener">Pyodide</a> ${escapeHtml(tr("(Python for the web). Nothing is uploaded: your circuits stay on your computer."))}</p>
    <p><a href="https://github.com/wirely-app/wirely-app.github.io" target="_blank" rel="noopener">${escapeHtml(tr("Wirely on GitHub"))}</a> ·
    <a href="https://github.com/wirely-app/wirely-app.github.io/releases/latest" target="_blank" rel="noopener">${escapeHtml(tr("Desktop app for Windows, Mac and Linux"))}</a></p>
    <p class="hint">${escapeHtml(tr("Maths: {kind}", { kind: numpyKind }))}</p></div>
    <div class="dlgButtons"><button class="btn primary" id="aClose">${escapeHtml(tr("Close"))}</button></div>`, (d) => {
    opsCanvas(d.querySelector("#abMark"), J(app.logo_ops()), 50, 50, 50 / 32);
    d.querySelector("#aClose").addEventListener("click", closeDialog);
  });
}

function confirmDiscard(then) {
  if (!ui.dirty || ui.empty) { then(); return; }
  openDialog(`<div class="dlgTitle">${escapeHtml(tr("Save changes to this circuit first?"))}</div>
    <p class="hint">${escapeHtml(tr("If you don't save, your changes to “{name}” will be lost.", { name: ui.name }))}</p>
    <div class="dlgButtons"><button class="btn" id="cdDiscard">${escapeHtml(tr("Don't save"))}</button><span class="spacer"></span>
    <button class="btn" id="cdCancel">${escapeHtml(tr("Cancel"))}</button><button class="btn primary" id="cdSave">${escapeHtml(tr("Save"))}</button></div>`, (d) => {
    d.querySelector("#cdCancel").addEventListener("click", closeDialog);
    d.querySelector("#cdDiscard").addEventListener("click", () => { closeDialog(); then(); });
    d.querySelector("#cdSave").addEventListener("click", async () => {
      closeDialog();
      if (await Files.save(false)) then();
    });
  });
}

// ============================================================================================ files
function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function safeName(s) { return (s || "circuit").replace(/[\\/:*?"<>|]+/g, "-").trim() || "circuit"; }
function baseName(s) { return s.replace(/\.(wirely|spark|json)$/i, ""); }

const Files = {
  handle: null,                  // file handle (Chrome / Edge): Save writes back to the same file
  async open() {
    if (window.showOpenFilePicker) {
      try {
        const [h] = await window.showOpenFilePicker({ types: [{ description: tr("Wirely circuit"), accept: { "application/json": [".wirely", ".spark"] } }] });
        const file = await h.getFile();
        if (this.load(await file.text(), file.name)) this.handle = h;
        return;
      } catch (e) {
        if (e && e.name === "AbortError") return;
      }
    }
    $("fileInput").value = "";
    $("fileInput").click();
  },
  load(text, filename) {
    const err = app.load(text, baseName(filename));
    if (err) { toast(err, "error"); return false; }
    this.handle = null;
    afterOpen();
    return true;
  },
  async save(asNew) {
    const name = safeName(ui.untitled ? "circuit" : ui.name) + ".wirely";
    const text = app.save_text();
    if (window.showSaveFilePicker) {
      try {
        if (!this.handle || asNew) {
          this.handle = await window.showSaveFilePicker({ suggestedName: name,
            types: [{ description: tr("Wirely circuit"), accept: { "application/json": [".wirely"] } }] });
        }
        const w = await this.handle.createWritable();
        await w.write(text);
        await w.close();
        app.mark_saved(baseName(this.handle.name));
        Autosave.clear();
        refreshUI();
        toast(tr("Saved {name}", { name: this.handle.name }), "ok", null, 2500);
        return true;
      } catch (e) {
        if (e && e.name === "AbortError") return false;
        console.warn(e);
        this.handle = null;
      }
    }
    download(new Blob([text], { type: "application/json" }), name);
    app.mark_saved();
    Autosave.clear();
    refreshUI();
    toast(tr("Saved {name} to your Downloads.", { name }), "ok", null, 3500);
    return true;
  },
};
$("fileInput").addEventListener("change", async () => {
  const f = $("fileInput").files[0];
  if (f) Files.load(await f.text(), f.name);
});
// drop a .wirely file onto the page to open it
document.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
document.addEventListener("drop", async (e) => {
  const f = e.dataTransfer && e.dataTransfer.files[0];
  if (!f) return;
  e.preventDefault();
  confirmDiscard(async () => Files.load(await f.text(), f.name));
});

function afterOpen() {
  refreshUI();
  resize();
  zoomFit();
  clearToasts();
  drawGraphSoon();
}

let examples = [];
async function loadExampleList() {
  try {
    const r = await fetch("examples/index.json");
    examples = r.ok ? await r.json() : [];
  } catch (e) { examples = []; }
}
function showExamplesMenu() {
  const pop = $("menuPopup");
  const r = pop.getBoundingClientRect();
  const items = [tr("Examples")].concat(examples.map((name) => [tr(name), name, ""]));
  showPopup(items, r.left, r.top, (name) => { closeMenus(); confirmDiscard(() => openExample(name)); });
}
async function openExample(name) {
  try {
    const r = await fetch("examples/" + encodeURIComponent(name + ".wirely"));
    if (!r.ok) throw new Error(r.status);
    const err = app.load(await r.text(), name);
    if (err) { toast(err, "error"); return; }
    Files.handle = null;
    afterOpen();
  } catch (e) {
    toast(tr("Couldn't open the example “{name}”.", { name }), "error");
  }
}

// ---- links that carry a circuit: …/#c=<compressed circuit>
async function compress(text) {
  const cs = new CompressionStream("deflate-raw");
  const buf = await new Response(new Blob([text]).stream().pipeThrough(cs)).arrayBuffer();
  let s = "";
  const b = new Uint8Array(buf);
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function decompress(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(s);
  const b = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) b[i] = bin.charCodeAt(i);
  const ds = new DecompressionStream("deflate-raw");
  return await new Response(new Blob([b]).stream().pipeThrough(ds)).text();
}
async function shareLink() {
  if (ui.empty) { toast(tr("Draw a circuit first — then you can share a link to it."), "info"); return; }
  try {
    const d = JSON.parse(app.save_text());
    const text = JSON.stringify(d);
    const code = await compress(text);
    const name = encodeURIComponent(ui.name || "circuit");
    const url = location.origin + location.pathname + "#n=" + name + "&c=" + code;
    clipboardWrite(url);
    openDialog(`<div class="dlgTitle">${escapeHtml(tr("A link to this circuit"))}</div>
      <p class="hint">${escapeHtml(tr("Anyone who opens this link sees a copy of your circuit in Wirely (the circuit is inside the link itself — nothing is uploaded). It has been copied: paste it into Google Classroom, Teams or an email."))}</p>
      <div class="form" style="grid-template-columns:1fr"><input type="text" id="shareUrl" readonly value="${escapeHtml(url)}"></div>
      <div class="dlgButtons"><button class="btn" id="shCopy">${escapeHtml(tr("Copy again"))}</button><button class="btn primary" id="shClose">${escapeHtml(tr("Close"))}</button></div>`, (d) => {
      const inp = d.querySelector("#shareUrl");
      setTimeout(() => inp.select(), 0);
      d.querySelector("#shCopy").addEventListener("click", () => { inp.select(); clipboardWrite(url); toast(tr("Link copied."), "ok", null, 2000); });
      d.querySelector("#shClose").addEventListener("click", closeDialog);
    });
  } catch (e) {
    toast(tr("Sorry — this browser can't make circuit links."), "error");
  }
}

// open the circuit carried in the link (…/#n=name&c=…). Returns true if it did.
async function openLinkCircuit() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (!h.get("c")) return false;
  try {
    const text = await decompress(h.get("c"));
    const err = app.load(text, h.get("n") || tr("Shared circuit"));
    if (!err) { app.mark_saved(); Files.handle = null; afterOpen(); return true; }
    toast(err, "error");
  } catch (e) {
    toast(tr("That circuit link looks damaged — it couldn't be opened. Check the whole link was copied."), "error");
  }
  return false;
}

// a new circuit link pasted into a tab that already has Wirely open only changes the part after the #,
// so the page doesn't reload by itself: open the new circuit here
window.addEventListener("hashchange", () => {
  if (!ready || !new URLSearchParams(location.hash.slice(1)).get("c")) return;
  app.stop();
  afterRunChange();
  confirmDiscard(() => openLinkCircuit());
});

// Wirely used to live at richiewillmott.github.io/Wirely. The page left there forwards people here and brings
// along any unsaved work it had kept (…#carry=…), which goes into this address's own autosave and is offered as usual.
async function takeCarriedAutosave() {
  const h = new URLSearchParams(location.hash.slice(1));
  const carry = h.get("carry");
  if (!carry) return;
  try {
    const d = JSON.parse(await decompress(carry));
    let mine = null;
    try { mine = JSON.parse(localStorage.getItem(Autosave.key) || "null"); } catch (e) { mine = null; }
    if (d && d.text && (!mine || !mine.t || mine.t < d.t)) localStorage.setItem(Autosave.key, JSON.stringify(d));
  } catch (e) { /* damaged or storage off: nothing to bring across */ }
  h.delete("carry");
  const rest = h.toString();
  history.replaceState(null, "", location.pathname + location.search + (rest ? "#" + rest : ""));
}

async function openStartCircuit() {
  await loadExampleList();
  if (launchFile) {
    if (Files.load(launchFile.text, launchFile.name)) Files.handle = launchFile.h;
    launchFile = null;
    return;
  }
  await takeCarriedAutosave();
  if (await openLinkCircuit()) return;
  const ex = params.get("example");
  if (ex && examples.includes(ex)) { await openExample(ex); return; }
  afterOpen();
  Autosave.offer();
}

// ---- keep a copy in the browser in case the tab is closed
const Autosave = {
  key: "wirely-autosave",
  save() {
    if (!ready || !ui.dirty || ui.empty) return;
    try { localStorage.setItem(this.key, JSON.stringify({ name: ui.name, text: app.save_text(), t: Date.now() })); } catch (e) { /* storage off */ }
  },
  clear() { try { localStorage.removeItem(this.key); } catch (e) { /* storage off */ } },
  offer() {
    let d = null;
    try { d = JSON.parse(localStorage.getItem(this.key) || "null"); } catch (e) { d = null; }
    if (!d || !d.text) return;
    const when = new Date(d.t).toLocaleString(HTML_LANG[lang]);
    toast(tr("Wirely kept a copy of “{name}” from {when} that wasn't saved.", { name: d.name, when }), "info", [
      [tr("Open it"), () => { if (!app.load(d.text, d.name)) { afterOpen(); app.action("noop"); refreshUI(); } }],
      [tr("No thanks"), () => this.clear()],
    ], 0);
  },
};
setInterval(() => Autosave.save(), 5000);
window.addEventListener("beforeunload", (e) => {
  if (ready && ui.dirty && !ui.empty) { Autosave.save(); e.preventDefault(); e.returnValue = ""; }
});

// ---- pictures of the diagram
async function exportPicture(toClipboard) {
  if (ui.empty) { toast(tr("There's nothing to save yet — add some parts first."), "info"); return; }
  const f = J(app.export_frame());
  const [x, y, w, h] = f.rect;
  const scale = 3;
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.setTransform(scale, 0, 0, scale, -x * scale, -y * scale);
  replay(ctx, f.ops);
  const blob = await new Promise((res) => c.toBlob(res, "image/png"));
  if (toClipboard) {
    try {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      toast(tr("Picture copied — paste it into your document."), "ok", null, 3000);
      return;
    } catch (e) { toast(tr("This browser won't copy pictures, so it has been saved instead."), "info"); }
  }
  download(blob, safeName(ui.untitled ? "circuit" : ui.name) + ".png");
}

// ============================================================================================ the graph
const plot = $("plot");
let plotMouse = null;
function graphShown() { return ui.graph && !$("graphPanel").hidden; }
function setupGraph() {
  const ch = J(app.graph_choices());
  for (const [id, list] of [["tbox", ch.time], ["vbox", ch.volts]]) {
    const s = $(id);
    list.forEach((name, i) => { const o = document.createElement("option"); o.value = i; o.textContent = name; s.appendChild(o); });
    s.addEventListener("change", drawGraph);
  }
  $("graphClear").addEventListener("click", () => { app.graph_clear(); drawGraph(); });
  $("graphClose").addEventListener("click", () => doAction("graph"));
  $("graphPic").addEventListener("click", () => plot.toBlob((b) => download(b, "graph.png"), "image/png"));
  $("graphCsv").addEventListener("click", () => {
    const csv = app.graph_csv();
    if (!csv) { toast(tr("No readings yet — put a graph probe on a wire and press Run."), "info"); return; }
    download(new Blob([csv], { type: "text/csv" }), "graph readings.csv");
  });
  plot.addEventListener("pointermove", (e) => { const r = plot.getBoundingClientRect(); plotMouse = [e.clientX - r.left, e.clientY - r.top]; drawGraph(); });
  plot.addEventListener("pointerleave", () => { plotMouse = null; drawGraph(); });
}
let graphTimer = null;
function drawGraphSoon() { clearTimeout(graphTimer); graphTimer = setTimeout(drawGraph, 30); }
function drawGraph() {
  if (!app || !graphShown()) return;
  const r = plot.getBoundingClientRect();
  if (r.width < 10 || r.height < 10) return;
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  if (plot.width !== Math.round(r.width * dpr) || plot.height !== Math.round(r.height * dpr)) {
    plot.width = Math.round(r.width * dpr);
    plot.height = Math.round(r.height * dpr);
  }
  const g = J(app.graph_ops(r.width, r.height, plotMouse ? plotMouse[0] : -1, plotMouse ? plotMouse[1] : -1,
    +$("tbox").value, +$("vbox").value));
  const ctx = plot.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, r.width, r.height);
  replay(ctx, g.ops);
  if (g.chips) $("chips").innerHTML = g.chips;
}

// ============================================================================================ sound
/* Buzzers, speakers, motors and relays: the simulator says what each should sound like (frequency, loudness,
   shape) and this plays it with Web Audio. */
const Sound = {
  ctx: null, voices: new Map(), clicks: 0, master: null,
  unlock() {
    if (this.ctx || !window.AudioContext) { if (this.ctx && this.ctx.state === "suspended") this.ctx.resume(); return; }
    try {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.5;
      const comp = this.ctx.createDynamicsCompressor();
      this.master.connect(comp);
      comp.connect(this.ctx.destination);
    } catch (e) { this.ctx = null; }
  },
  update(list, clicks) {
    if (!this.ctx) { this.clicks = clicks; return; }
    const now = this.ctx.currentTime;
    const seen = new Set();
    for (const [key, freq, loud, shape] of list) {
      seen.add(key);
      let v = this.voices.get(key);
      const type = shape >= 1.5 ? "sawtooth" : shape >= 0.5 ? "square" : "sine";
      if (!v) {
        const osc = this.ctx.createOscillator(), gain = this.ctx.createGain();
        gain.gain.value = 0;
        osc.connect(gain); gain.connect(this.master);
        osc.start();
        v = { osc, gain };
        this.voices.set(key, v);
      }
      if (v.osc.type !== type) v.osc.type = type;
      v.osc.frequency.setTargetAtTime(Math.max(20, Math.min(16000, freq)), now, 0.01);
      const level = loud * (type === "square" ? 0.35 : type === "sawtooth" ? 0.5 : 0.8);
      v.gain.gain.setTargetAtTime(level, now, 0.02);
    }
    for (const [key, v] of this.voices) if (!seen.has(key)) v.gain.gain.setTargetAtTime(0, now, 0.02);
    if (clicks > this.clicks) for (let i = 0; i < Math.min(3, clicks - this.clicks); i++) this.click(i * 0.015);
    this.clicks = clicks;
  },
  click(delay) {
    const n = Math.round(this.ctx.sampleRate * 0.012);
    const buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (0.003 * this.ctx.sampleRate)) * 0.8;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.master);
    src.start(this.ctx.currentTime + (delay || 0));
  },
  stopAll() {
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    for (const v of this.voices.values()) v.gain.gain.setTargetAtTime(0, now, 0.02);
  },
};

// ============================================================================================ theme
function applyColours(c) {
  colours = c;
  const root = document.documentElement;
  for (const k in c) root.style.setProperty("--" + k, c[k]);
  root.dataset.theme = ui.dark ? "dark" : "light";
}
function setTheme(mode) {
  applyColours(J(app.set_theme(mode)));
  ui.dark = mode === "dark";
  document.documentElement.dataset.theme = mode;
  try { localStorage.setItem("wirely-theme", mode); } catch (e) { /* storage off */ }
  setupGallery();
  rebuildToolIcons();
  requestDraw();
  drawGraphSoon();
}
function setSymbols(style) {
  ui.us = app.set_symbols(style) === "us";
  try { localStorage.setItem("wirely-symbols", ui.us ? "us" : "uk"); } catch (e) { /* storage off */ }
  setupGallery();
  requestDraw();
}
function rebuildToolIcons() {
  const icons = J(app.toolbar_icons(JSON.stringify(TOOL_ICONS)));
  for (const name in toolButtons) {
    const c = toolButtons[name].querySelector("canvas");
    const icon = icons[ICON_FOR[name] || name];
    if (c && icon) opsCanvas(c, icon, 24, 24, 0.75);
  }
}

async function setupUI() {
  let mode = "light";
  try { mode = localStorage.getItem("wirely-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); } catch (e) { /* storage off */ }
  applyColours(J(app.set_theme(mode)));
  document.documentElement.dataset.theme = mode;
  try { ui.us = app.set_symbols(localStorage.getItem("wirely-symbols") || "uk") === "us"; } catch (e) { /* storage off */ }
  setupToolbar();
  setupGallery();
  setupGraph();
  new ResizeObserver(resize).observe($("sheetWrap"));
  new ResizeObserver(drawGraphSoon).observe(plot);
  resize();
  if (window.innerWidth < 760) { $("app").classList.add("noGallery"); $("showGallery").hidden = false; }
}

// ============================================================================================ start
// opening a .wirely file with the installed app (Chromebook "Open with Wirely")
let launchFile = null;
if ("launchQueue" in window) {
  window.launchQueue.setConsumer(async (p) => {
    if (!p.files || !p.files.length) return;
    const h = p.files[0];
    const f = await h.getFile();
    if (ready) { if (Files.load(await f.text(), f.name)) Files.handle = h; }
    else launchFile = { h, text: await f.text(), name: f.name };
  });
}

if ("serviceWorker" in navigator && !params.has("nosw") &&
    (location.protocol === "https:" || location.hostname === "localhost")) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch((e) => console.warn(e)));
  // a new version has just been fetched in the background and taken over: switch to it straight away if nothing
  // would be lost, otherwise offer it (before, it only showed up on the next visit)
  const hadController = !!navigator.serviceWorker.controller;
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController || reloading) return;          // the very first visit: nothing older to replace
    const safe = !ready || ((!ui.dirty || ui.empty) && ui.sim === "stopped");
    if (safe) { reloading = true; location.reload(); return; }
    toast(tr("A new version of Wirely is ready."), "info", [[tr("Reload"), () => { reloading = true; location.reload(); }]], 0);
  });
}

requestAnimationFrame(loop);
boot();
