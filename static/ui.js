// Shared pieces: the API, sounds, the game's dialogs, toasts, small DOM helpers.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  // In a key/value grid every child must be its own element (adjacent text nodes would merge into one cell).
  const wrap = /\bkv\b/.test(attrs?.class || "");
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : wrap ? h("span", {}, String(c)) : document.createTextNode(c));
  }
  return el;
}
// replaceChildren with the same leniency as h(): skip null / false instead of printing them.
const nativeReplaceChildren = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function (...children) {
  return nativeReplaceChildren.apply(this, children.flat().filter((c) => c != null && c !== false));
};

// ---- API ---------------------------------------------------------------------------------------------------------
class ApiError extends Error {}
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["content-type"] = "application/json"; }
  const r = await fetch(path, opts);
  if (r.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/password")) {
    location.hash = "#/login";
    throw new ApiError("Please sign in.");
  }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) {
    const d = data?.detail;
    throw new ApiError(Array.isArray(d) ? d.map((e) => e.msg).join(" ") : d || `Request failed (${r.status}).`);
  }
  return data;
}

// ---- Sounds: the game's clickDown on press, click on release (MJControl); portal and badPath for start / errors ---
const Sound = {
  on: (() => { try { return localStorage.getItem("bh-sound") !== "off"; } catch { return true; } })(),
  cache: {},
  play(name) {
    if (!this.on || document.body.classList.contains("plain")) return;
    const src = `/game/GameResources/${name}.wav`;
    const a = (this.cache[src] ||= new Audio(src));
    try { a.currentTime = 0; a.play().catch(() => {}); } catch {}
  },
  toggle() {
    this.on = !this.on;
    try { localStorage.setItem("bh-sound", this.on ? "on" : "off"); } catch {}
    $("#sound-icon").src = `/game/GameResources/${this.on ? "speakerOn" : "speakerOff"}.png`;
  },
};
document.addEventListener("pointerdown", (e) => { if (e.target.closest("button:not(:disabled)")) Sound.play("clickDown"); });
document.addEventListener("click", (e) => { if (e.target.closest("button:not(:disabled)")) Sound.play("click"); });

// ---- Dialogs (BlockAlertView: green for actions, blue for cancel, red for destructive) ------------------------------
function dialog({ title, message, body, buttons = [{ label: "OK", kind: "green", value: true }], wide, onOpen }) {
  return new Promise((resolve) => {
    const close = (v) => { dim.remove(); resolve(v); };
    const box = h("div", { class: "alert" + (wide ? " wide" : "") },
      title ? h("h2", { class: "label" }, title) : null,
      message ? h("p", {}, message) : null,
      body || null,
      h("div", { class: "buttons", style: "margin-bottom:10px" },
        buttons.map((b) => h("button", { class: b.kind || "", onclick: () => close(typeof b.value === "function" ? b.value() : b.value) }, b.label))));
    const dim = h("div", { class: "dim", onclick: (e) => { if (e.target === dim) close(undefined); } }, box);
    document.body.append(dim);
    const first = box.querySelector("input, textarea, select");
    (first || box.querySelector("button"))?.focus();
    box.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close(undefined);
      if (e.key === "Enter" && e.target.tagName === "INPUT") box.querySelector(".buttons button.green")?.click();
    });
    onOpen?.(box, close);
  });
}
const alertBox = (title, message) => dialog({ title, message });
const confirmBox = (title, message, label = "OK", kind = "green") =>
  dialog({ title, message, buttons: [{ label: "Cancel", kind: "blue", value: false }, { label, kind, value: true }] });
async function promptBox(title, { message, value = "", type = "text", label = "OK", maxlength } = {}) {
  const input = h("input", { type, value, maxlength });
  const ok = await dialog({ title, message, body: input,
    buttons: [{ label: "Cancel", kind: "blue", value: false }, { label, kind: "green", value: true }] });
  return ok ? input.value : null;
}
// TableSelectionAlertView: a list of options as table cells.
function choose(title, options, current) {
  return new Promise((resolve) => {
    let done = false;
    const table = h("div", { class: "table", style: "max-height:55vh;overflow-y:auto;margin-bottom:10px" },
      options.map((o) => {
        const value = typeof o === "object" ? o.value : o, label = typeof o === "object" ? o.label : o;
        return h("button", { class: "cell" + (value === current ? " selected" : ""), onclick: () => { done = true; $(".dim:last-of-type")?.remove(); resolve(value); } },
          h("span", { class: "name" }, label));
      }));
    dialog({ title, body: table, buttons: [{ label: "Cancel", kind: "blue", value: undefined }] }).then((v) => { if (!done) resolve(v); });
  });
}

function toast(text, kind = "") {
  const t = h("div", { class: "alert toast " + kind }, h("p", { style: "margin:4px 0 10px" }, text));
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 6000);
}
async function guard(fn) {
  try { return await fn(); } catch (e) { Sound.play("badPath"); await alertBox("Error", e.message); }
}

// ---- Formatting --------------------------------------------------------------------------------------------------
const fmtBytes = (n) => n >= 1 << 30 ? (n / (1 << 30)).toFixed(1) + " GB" : n >= 1 << 20 ? (n / (1 << 20)).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
const fmtTime = (t) => t ? new Date(typeof t === "number" ? t * 1000 : t).toLocaleString() : "—";
function fmtAgo(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`;
}

// The world's portal frame in TileMap.png (16x32 px frames, shown at 40x80, i.e. x2.5): world portals by level
// (1-5) animate through 8 frames at 0.2 s; Create World and Join World are fixed (MainMenuUI -render:).
function portalPosition(kind, level = 0, frame = 0) {
  let x, y;
  if (kind === "create") [x, y] = [48, 48];
  else if (kind === "join") [x, y] = [480, 0];
  else if (level >= 1 && level <= 5) [x, y] = [256 + 16 * frame, 320 - 32 * (level - 1)];
  else [x, y] = [64 + 16 * frame, 32];
  return `-${x * 2.5}px -${y * 2.5}px`;
}
