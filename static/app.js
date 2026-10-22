// Blockheads Server Portal: the pages.
"use strict";

const app = $("#app");
const state = { servers: [], assets: { ready: false }, view: null, listeners: new Set() };

// ---- Live events -------------------------------------------------------------------------------------------------
let socket = null;
function connect() {
  if (socket && socket.readyState <= 1) return;
  socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  socket.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === "status" || e.type === "players") {
      const s = state.servers.find((x) => x.id === e.server);
      if (s) Object.assign(s, e.type === "status" ? { status: e.status, pid: e.pid, lastError: e.lastError, startedAt: e.startedAt, players: e.players } : { players: e.players });
    }
    if (e.type === "notify") notify(e);
    for (const fn of state.listeners) fn(e);
  };
  socket.onclose = (e) => { if (e.code !== 4401) setTimeout(connect, 2000); };
}
function listen(fn) { state.listeners.add(fn); return () => state.listeners.delete(fn); }
function notify(e) {
  Sound.play(e.kind === "crash" || e.kind === "giveUp" || e.kind === "backupFailed" ? "badPath" : "click");
  toast(e.text, e.kind);
  if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification("Blockheads Server Portal", { body: e.text });
}

async function refreshServers() { state.servers = await api("GET", "/api/servers"); return state.servers; }

// ---- Router ------------------------------------------------------------------------------------------------------
let cleanup = [];  // undo functions for the current page (listeners, timers)
async function route() {
  cleanup.forEach((f) => f()); cleanup = [];
  const st = await api("GET", "/api/state");
  state.assets = st.assets;
  document.body.classList.toggle("plain", !st.assets.ready);
  const [, page = "", id, tab] = location.hash.split("/");
  $("#topbar").hidden = !st.signedIn;
  if (!st.configured) return viewSetup();
  if (!st.signedIn) return viewLogin();
  connect();
  if (page === "assets") return viewAssets(false);
  if (!st.assets.ready && !sessionStorage.getItem("bh-skip-assets")) return viewAssets(true);
  if (page === "server" && id) return viewServer(id, tab || "overview");
  if (page === "create") return viewCreate();
  if (page === "settings") return viewSettings();
  return viewHome();
}
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); guard(route); });
$("#settings-button").onclick = () => (location.hash = "#/settings");
$("#sound-button").onclick = () => Sound.toggle();
$("#sound-icon").src = `/game/GameResources/${Sound.on ? "speakerOn" : "speakerOff"}.png`;

function mount(...nodes) { app.replaceChildren(...nodes); }

// ---- Setup and login ---------------------------------------------------------------------------------------------
function viewSetup() {
  const pw = h("input", { type: "password", autocomplete: "new-password", placeholder: "Password" });
  const pw2 = h("input", { type: "password", autocomplete: "new-password", placeholder: "Again" });
  const go = () => guard(async () => {
    if (pw.value !== pw2.value) throw new ApiError("The passwords do not match.");
    await api("POST", "/api/setup/password", { password: pw.value });
    location.hash = "#/assets"; route();
  });
  mount(h("div", { class: "page", style: "max-width:440px;padding-top:12vh" },
    h("div", { class: "alert wide" }, h("h2", { class: "label" }, "Welcome"),
      h("p", {}, "Choose the admin password for this portal (at least 8 characters)."),
      pw, h("div", { style: "height:8px" }), pw2,
      h("div", { class: "buttons", style: "margin:12px 0" }, h("button", { class: "green wide", onclick: go }, "Continue")))));
  pw.focus();
  pw2.addEventListener("keydown", (e) => e.key === "Enter" && go());
}

function viewLogin() {
  const pw = h("input", { type: "password", autocomplete: "current-password", placeholder: "Password" });
  const remember = h("button", { class: "toggle on", onclick: () => remember.classList.toggle("on"), "aria-label": "Remember me" });
  const go = () => guard(async () => {
    await api("POST", "/api/login", { password: pw.value, remember: remember.classList.contains("on") });
    location.hash = "#/"; route();
  });
  mount(h("div", { class: "page", style: "max-width:440px;padding-top:14vh" },
    h("div", { class: "alert wide" }, h("h2", { class: "label" }, "Blockheads Server Portal"),
      pw, h("div", { class: "row", style: "justify-content:space-between;margin:12px 0" }, h("span", { class: "label" }, "Remember me"), remember),
      h("div", { class: "buttons", style: "margin-bottom:12px" }, h("button", { class: "green wide", onclick: go }, "Sign in")))));
  pw.focus();
  pw.addEventListener("keydown", (e) => e.key === "Enter" && go());
}

function viewAssets(firstRun) {
  const file = h("input", { type: "file", accept: ".apk", style: "display:none" });
  const status = h("p", { class: "hint" });
  file.onchange = () => guard(async () => {
    if (!file.files[0]) return;
    status.textContent = "Extracting the game's art…";
    const fd = new FormData(); fd.append("file", file.files[0]);
    await api("POST", "/api/assets", fd);
    status.textContent = "";
    location.hash = "#/"; location.reload();
  }).finally(() => (status.textContent = ""));
  mount(h("div", { class: "page", style: "max-width:520px;padding-top:10vh" },
    h("div", { class: "alert wide" }, h("h2", { class: "label" }, "Game art"),
      h("p", {}, "The portal dresses itself in The Blockheads' own buttons, fonts, portals and sounds. They come from your own copy of the game: upload The Blockheads APK (Android). Nothing from it leaves this server."),
      status,
      h("div", { class: "buttons", style: "margin-bottom:12px" },
        firstRun ? h("button", { class: "blue", onclick: () => { sessionStorage.setItem("bh-skip-assets", "1"); location.hash = "#/"; route(); } }, "Later") : h("button", { class: "blue", onclick: () => history.back() }, "Back"),
        h("button", { class: "green", onclick: () => file.click() }, "Upload APK")), file)));
}

// ---- Home: the worlds as the main menu's portals -----------------------------------------------------------------------
async function viewHome() {
  await refreshServers();
  // As the game's menu: worlds on the left (newest next to Join World), then Join World (here: Import), then
  // Create World on the right (MainMenuUI: x of portal i = scroll - spacing·(i+1), create -2, join -1, worlds 0..).
  const byNewest = [...state.servers].sort((a, b) => (b.created || "").localeCompare(a.created || ""));
  const entries = [...byNewest.reverse().map((s) => ({ kind: "world", server: s, name: s.name })),
    { kind: "join", name: "Import World" }, { kind: "create", name: "Create World" }];
  const stored = sessionStorage.getItem("bh-portal-id");
  let current = entries.findIndex((e) => (e.server?.id || e.kind) === stored);
  if (current < 0) current = Math.max(0, entries.length - 3);  // the newest world, else Import
  const strip = h("div", { class: "portals" });
  const info = h("div", { class: "selected-world" });
  const actions = h("div", { class: "buttons", style: "width:min(470px,100%);padding:0 12px" });
  const importer = h("input", { type: "file", accept: ".zip", style: "display:none" });
  importer.onchange = () => guard(async () => {
    if (!importer.files[0]) return;
    const fd = new FormData(); fd.append("file", importer.files[0]);
    const s = await api("POST", "/api/worlds/import", fd);
    toast(`Imported ${s.name}.`);
    sessionStorage.setItem("bh-portal-id", s.id);
    viewHome();
  });
  const slots = entries.map((e, i) => {
    const portal = h("div", { class: "portal", style: `background-position:${portalPosition(e.kind, e.server?.portalLevel)}` });
    const slot = h("button", { class: "portal-slot", onclick: () => select(i, true) }, portal,
      h("div", { class: "portal-name" }, e.kind === "world" ? h("span", { class: "status-dot " + e.server.status }) : null, e.name));
    slot._portal = portal;
    return slot;
  });
  strip.append(...slots);

  function renderSelected() {
    const e = entries[current];
    slots.forEach((s, i) => s.classList.toggle("current", i === current));
    sessionStorage.setItem("bh-portal-id", e.server?.id || e.kind);
    if (e.kind === "create") {
      info.replaceChildren(h("h1", { class: "label" }, "Create World"), h("div", { class: "sub" }, "A new world and its server"));
      actions.replaceChildren(h("button", { class: "green wide", onclick: () => (location.hash = "#/create") }, "Create World"));
    } else if (e.kind === "join") {
      info.replaceChildren(h("h1", { class: "label" }, "Import World"), h("div", { class: "sub" }, "From an exported .zip"));
      actions.replaceChildren(h("button", { class: "green wide", onclick: () => importer.click() }, "Import .zip"), importer);
    } else {
      const s = state.servers.find((x) => x.id === e.server.id) || e.server;
      const players = (s.players || []).length;
      info.replaceChildren(h("h1", { class: "label" }, s.name),
        h("div", { class: "sub" }, h("span", { class: "status-dot " + s.status }), `${s.status} · ${s.status === "running" ? `${players}/${s.config.maxPlayers} players · ` : ""}port ${s.config.port}`),
        s.lastError ? h("div", { class: "sub", style: "color:#ffb0b0;text-transform:none" }, s.lastError) : null);
      const running = s.status === "running" || s.status === "starting";
      actions.replaceChildren(
        h("button", { class: "blue wide", onclick: () => (location.hash = `#/server/${s.id}`) }, "Options..."),
        running ? h("button", { class: "red wide", disabled: s.status === "stopping", onclick: () => guard(() => api("POST", `/api/servers/${s.id}/stop`)) }, "Stop")
          : h("button", { class: "green wide", onclick: () => guard(async () => { await api("POST", `/api/servers/${s.id}/start`); Sound.play("portal"); }) }, "Start"));
    }
  }
  function select(i, scroll) {
    current = Math.max(0, Math.min(entries.length - 1, i));
    renderSelected();
    if (scroll) slots[current].scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }
  let scrollTimer;
  strip.addEventListener("scroll", () => {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const mid = strip.getBoundingClientRect().left + strip.clientWidth / 2;
      let best = 0, bestD = Infinity;
      slots.forEach((s, i) => { const r = s.getBoundingClientRect(); const d = Math.abs(r.left + r.width / 2 - mid); if (d < bestD) [best, bestD] = [i, d]; });
      if (best !== current) select(best, false);
    }, 80);
  });
  const keys = (ev) => { if (ev.key === "ArrowLeft") select(current - 1, true); if (ev.key === "ArrowRight") select(current + 1, true); };
  document.addEventListener("keydown", keys);
  cleanup.push(() => document.removeEventListener("keydown", keys));

  // World portals animate: 8 frames, one every 0.2 s.
  let frame = 0;
  const anim = setInterval(() => {
    frame = (frame + 1) % 8;
    slots.forEach((s, i) => { if (entries[i].kind === "world") s._portal.style.backgroundPosition = portalPosition("world", entries[i].server.portalLevel, frame); });
  }, 200);
  cleanup.push(() => clearInterval(anim));
  cleanup.push(listen((e) => {
    if (e.type === "status" || e.type === "players") {
      renderSelected();
      slots.forEach((s, i) => { if (entries[i].kind === "world") s.querySelector(".status-dot").className = "status-dot " + (state.servers.find((x) => x.id === entries[i].server.id)?.status || ""); });
    }
  }));

  mount(h("div", { class: "home" }, strip, info, actions,
    state.servers.length === 0 ? h("p", { class: "hint", style: "margin-top:24px" }, "No worlds yet: create one, or import an exported world.") : null));
  requestAnimationFrame(() => select(current, false) || slots[current].scrollIntoView({ inline: "center", block: "nearest" }));
}

// ---- Server page -------------------------------------------------------------------------------------------------
const TABS = [["overview", "Overview"], ["console", "Console"], ["players", "Players"], ["chat", "Chat"], ["world", "World"],
  ["lists", "Lists"], ["backups", "Backups"], ["stats", "Stats"], ["settings", "Settings"]];

async function viewServer(id, tab) {
  let s;
  try { s = await api("GET", `/api/servers/${id}`); } catch (e) {
    toast("That server no longer exists.");
    location.hash = "#/";
    return;
  }
  const header = h("div", { class: "row", style: "flex-wrap:wrap;justify-content:center;gap:10px;margin-top:6px" });
  const body = h("div");
  function renderHeader(st) {
    const running = st.status === "running" || st.status === "starting";
    header.replaceChildren(
      h("button", { class: "blue", onclick: () => (location.hash = "#/") }, "Back"),
      h("h1", { class: "label", style: "margin:0 8px;font-size:24px;flex:1 1 auto;text-align:center" }, h("span", { class: "status-dot " + st.status }), s.name),
      running ? h("button", { class: "red", disabled: st.status === "stopping", onclick: () => guard(() => api("POST", `/api/servers/${id}/stop`)) }, "Stop")
        : h("button", { class: "green", onclick: () => guard(async () => { await api("POST", `/api/servers/${id}/start`); Sound.play("portal"); }) }, "Start"),
      h("button", { class: "blue", disabled: !running, onclick: () => guard(() => api("POST", `/api/servers/${id}/restart`)) }, "Restart"));
  }
  renderHeader(s);
  // When the server changes state (stopped, running...), the tab is drawn again from fresh data so what can be
  // done now (e.g. editing the welcome message once stopped) is available straight away.
  const views = { overview: tabOverview, console: tabConsole, players: tabPlayers, chat: tabChat, world: tabWorld,
    lists: tabLists, backups: tabBackups, stats: tabStats, settings: tabSettings };
  let tabCleanup = [];
  async function renderTab(fresh) {
    tabCleanup.forEach((f) => f());
    const outer = cleanup;
    cleanup = [];
    try { await (views[tab] || tabOverview)(id, fresh, body); } finally { tabCleanup = cleanup; cleanup = outer; }
  }
  cleanup.push(() => tabCleanup.forEach((f) => f()));
  cleanup.push(listen((e) => {
    if (e.server !== id || e.type !== "status") return;
    const changed = e.status !== s.status;
    Object.assign(s, e);
    renderHeader(s);
    if (changed && tab !== "console" && ["running", "stopped", "crashed"].includes(e.status))
      api("GET", `/api/servers/${id}`).then((fresh) => { Object.assign(s, fresh); return renderTab(s); }).catch(() => {});
  }));
  const tabs = h("div", { class: "tabs" }, TABS.map(([k, label]) =>
    h("button", { class: k === tab ? "green" : "blue", onclick: () => (location.hash = `#/server/${id}/${k}`) }, label)));
  mount(h("div", { class: "page" }, header, tabs, body));
  await renderTab(s);
}

const running = (s) => s.status === "running";

async function tabOverview(id, s, body) {
  const w = s.world || {};
  const players = h("div");
  const renderPlayers = (list) => players.replaceChildren(list.length ? h("div", {}, list.map((p) => h("div", {}, p.name))) : h("span", { class: "muted" }, "Nobody online"));
  renderPlayers(s.players || []);
  cleanup.push(listen((e) => { if (e.server === id && e.type === "players") renderPlayers(e.players); }));
  const diag = h("pre", { class: "console", style: "height:auto;max-height:260px", hidden: true });
  body.replaceChildren(h("div", { class: "grid" },
    h("div", { class: "panel" }, h("h2", { class: "label" }, "World"),
      h("div", { class: "kv" },
        "Name", w.name, "Size", w.size, "Mode", w.expert ? "Expert" : "Normal", "Day", w.day ?? "—", "Seed", String(w.seed ?? "—"),
        "Custom rules", w.customRules ? Object.keys(w.customRules).length + " set" : "None", "Created", fmtTime(w.created),
        "Last saved", fmtTime(w.saved), "On disk", w.diskBytes ? fmtBytes(w.diskBytes) : "—", "World ID", h("span", { class: "mono small" }, id))),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Server"),
      h("div", { class: "kv" }, "Status", s.status, "Port", String(s.config.port) + " (UDP)", "Max players", String(s.config.maxPlayers),
        "Save every", s.config.saveDelay + " s", "Password", w.passwordSet ? "Set" : "None", "PvP", w.pvp ? "On" : "Off",
        "Start with portal", s.config.autostart ? "Yes" : "No", "Restart on crash", s.config.autorestart ? "Yes" : "No"),
      s.lastError ? h("p", { class: "hint", style: "color:#ffb0b0" }, s.lastError) : null),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Online"), players,
      h("div", { class: "buttons", style: "margin-top:12px" },
        h("button", { class: "blue", disabled: !running(s), onclick: () => guard(async () => {
          const r = await api("POST", `/api/servers/${id}/diagnostics`);
          diag.hidden = false; diag.textContent = r.lines.join("\n");
        }) }, "Diagnostics")), diag)));
}

function consoleLine(line) {
  const cls = line.startsWith("[portal]") ? "portal-line" : line.startsWith("[console]") ? "cmd" : /error|failed|exception/i.test(line) ? "err" : "";
  return h("div", { class: cls }, line);
}
async function tabConsole(id, s, body) {
  const out = h("div", { class: "console" });
  const { lines } = await api("GET", `/api/servers/${id}/console`);
  out.append(...lines.map(consoleLine));
  const stick = () => out.scrollHeight - out.scrollTop - out.clientHeight < 40;
  cleanup.push(listen((e) => {
    if (e.server !== id || e.type !== "log") return;
    const atBottom = stick();
    out.append(consoleLine(e.line));
    while (out.childElementCount > 2000) out.firstChild.remove();
    if (atBottom) out.scrollTop = out.scrollHeight;
  }));
  const input = h("input", { type: "text", placeholder: "/help, /players, or chat as SERVER", autocomplete: "off" });
  const send = () => guard(async () => { if (!input.value.trim()) return; await api("POST", `/api/servers/${id}/command`, { line: input.value }); input.value = ""; });
  input.addEventListener("keydown", (e) => e.key === "Enter" && send());
  body.replaceChildren(h("div", { class: "panel" }, h("h2", { class: "label" }, "Console"), out,
    h("div", { class: "row", style: "margin-top:10px" }, input, h("button", { class: "green", onclick: send }, "Send")),
    h("p", { class: "hint" }, "Commands run with the owner's rights. A line without / is chat from SERVER."),
    h("div", { class: "buttons" }, h("button", { class: "blue", onclick: () => (location.href = `/api/servers/${id}/logs`) }, "Download logs"))));
  out.scrollTop = out.scrollHeight;
  input.focus();
}

const PLAYER_ACTIONS = [["kick", "Kick", "blue"], ["ban", "Ban", "red"], ["ban-no-device", "Ban name only", "red"],
  ["mod", "Mod", "green"], ["admin", "Admin", "green"], ["whitelist", "Whitelist", "green"]];
async function tabPlayers(id, s, body) {
  const list = h("div");
  const render = (players) => list.replaceChildren(players.length ? players.map((p) => h("div", { class: "player" },
    h("div", { class: "who" }, p.name, h("small", {}, `${p.ip} · online ${p.since ? fmtAgo(p.since) : ""}`)),
    PLAYER_ACTIONS.map(([action, label, kind]) => h("button", { class: kind, onclick: () => guard(async () => {
      if ((action === "ban" || action === "ban-no-device") && !(await confirmBox(label, `${label} ${p.name}?` + (action === "ban" ? " This also bans their device." : ""), label, "red"))) return;
      await api("POST", `/api/servers/${id}/players/${encodeURIComponent(p.name)}/${action}`);
      toast(`${label}: ${p.name}`);
    }) }, label)))) : h("p", { class: "muted" }, running(s) ? "Nobody online." : "The server is stopped."));
  render(s.players || []);
  cleanup.push(listen((e) => { if (e.server === id && e.type === "players") render(e.players); }));
  const seen = s.world?.playersSeen || [];
  const recent = h("div", { class: "panel", style: "margin-top:14px" }, h("h2", { class: "label" }, "Players seen"),
    seen.length ? seen.map((p) => h("div", { class: "player" },
      h("div", { class: "who" }, p.name, h("small", {}, `${p.ip || ""} · last seen ${fmtTime(p.lastSeen)}`)),
      PLAYER_ACTIONS.filter(([a]) => a !== "kick").map(([action, label, kind]) => h("button", { class: kind, onclick: () => guard(async () => {
        if ((action === "ban" || action === "ban-no-device") && !(await confirmBox(label, `${label} ${p.name}?`, label, "red"))) return;
        await api("POST", `/api/servers/${id}/players/${encodeURIComponent(p.name)}/${action}`);
        toast(`${label}: ${p.name}`);
      }) }, label)))) : h("p", { class: "muted" }, "Nobody has joined yet."),
    h("p", { class: "hint" }, running(s) ? "Uses the server's commands." : "The server is stopped: these change its list files."));
  body.replaceChildren(recent);
  body.prepend(h("div", { class: "panel" }, h("h2", { class: "label" }, "Players online"), list,
    h("div", { class: "buttons", style: "margin-top:12px" },
      h("button", { class: "blue", disabled: !running(s), onclick: () => guard(() => api("POST", `/api/servers/${id}/command`, { line: "/players" })) }, "Refresh"),
      h("button", { class: "blue", onclick: () => guard(async () => {
        const name = await promptBox("Unban", { message: "Name or IP address to unban:" });
        if (name) await api("POST", `/api/servers/${id}/players/${encodeURIComponent(name.trim())}/unban`);
      }) }, "Unban..."))));
}

async function tabChat(id, s, body) {
  const out = h("div", { class: "console", style: "font-family:inherit;font-size:15px" });
  const line = (m) => h("div", { class: "chat-line" }, h("span", { class: "muted small" }, new Date(m.t * 1000).toLocaleTimeString() + " "), h("b", {}, m.name + ": "), m.text);
  out.append(...(await api("GET", `/api/servers/${id}/chat`)).map(line));
  cleanup.push(listen((e) => { if (e.server === id && e.type === "chat") { out.append(line(e)); out.scrollTop = out.scrollHeight; } }));
  const input = h("input", { type: "text", placeholder: "Message as SERVER", maxlength: 400 });
  const send = () => guard(async () => { if (!input.value.trim()) return; await api("POST", `/api/servers/${id}/chat`, { line: input.value }); input.value = ""; });
  input.addEventListener("keydown", (e) => e.key === "Enter" && send());
  body.replaceChildren(h("div", { class: "panel" }, h("h2", { class: "label" }, "Chat"), out,
    h("div", { class: "row", style: "margin-top:10px" }, input, h("button", { class: "green", disabled: !running(s), onclick: send }, "Send"))));
  out.scrollTop = out.scrollHeight;
}

async function tabWorld(id, s, body) {
  const w = s.world || {};
  const isRunning = s.status !== "stopped" && s.status !== "crashed";
  const name = h("input", { type: "text", value: w.name || "", maxlength: 32, disabled: isRunning });
  const welcome = h("textarea", { maxlength: 500, disabled: isRunning }, w.welcomeMessage || "");
  const pvp = h("button", { class: "toggle" + (w.pvp ? " on" : ""), onclick: () => pvp.classList.toggle("on") });
  const save = () => guard(async () => {
    const body = { pvp: pvp.classList.contains("on") };
    if (!isRunning) Object.assign(body, { name: name.value.trim(), welcomeMessage: welcome.value });
    await api("PATCH", `/api/servers/${id}/world`, body);
    toast("Saved."); route();
  });
  const setPassword = () => guard(async () => {
    const pw = await promptBox("Server password", { message: "Players must type this to join (16 characters at most). Leave empty to remove it.", type: "text", maxlength: 16 });
    if (pw === null) return;
    await api("PATCH", `/api/servers/${id}/world`, { password: pw });
    toast(pw ? "Password set." : "Password removed."); route();
  });
  const notice = isRunning ? h("div", { class: "alert wide", style: "margin:0 auto 14px;animation:none" }, h("h2", { class: "label" }, "Server " + s.status),
    h("p", {}, "The name and welcome message can only be changed while the server is stopped. Password and PvP can be changed now."),
    h("div", { class: "buttons", style: "margin-bottom:10px" }, h("button", { class: "red", disabled: s.status !== "running", onclick: () => guard(() => api("POST", `/api/servers/${id}/stop`)) }, "Stop server"))) : null;
  body.replaceChildren(notice, h("div", { class: "grid" },
    h("div", { class: "panel" }, h("h2", { class: "label" }, "World settings"),
      h("label", { class: "field" }, h("span", {}, "Name"), name),
      h("label", { class: "field" }, h("span", {}, "Welcome message"), welcome),
      h("div", { class: "row", style: "justify-content:space-between;margin:12px 0" }, h("span", {}, "PvP"), pvp),
      h("div", { class: "row", style: "justify-content:space-between;margin:12px 0" }, h("span", {}, "Password: " + (w.passwordSet ? "set" : "none")),
        h("button", { class: "blue", onclick: setPassword }, "Change...")),
      h("div", { class: "buttons" }, h("button", { class: "green wide", onclick: save }, "Save")),
      !isRunning ? h("p", { class: "hint" }, "Changes to a stopped world are written to its save; a backup is taken first.") : null),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "World"),
      h("div", { class: "table" },
        h("button", { class: "cell", onclick: () => (location.href = `/api/servers/${id}/export`) }, h("span", { class: "name" }, "Export .zip"), h("span", { class: "arrow" })),
        h("button", { class: "cell", onclick: () => guard(async () => {
          const n = await promptBox("Clone world", { message: "Name of the copy:", value: (w.name || "") + " COPY", maxlength: 32 });
          if (n === null) return;
          const c = await api("POST", `/api/servers/${id}/clone`, { name: n });
          toast(`Cloned as ${c.name}.`); location.hash = `#/server/${c.id}`;
        }) }, h("span", { class: "name" }, "Clone"), h("span", { class: "arrow" })),
        h("button", { class: "cell", disabled: isRunning || !!w.customRules, onclick: () => guard(async () => {
          if (!(await confirmBox("Custom rules", "Convert this world to a custom rules world the next time it starts? A backup is taken first. This cannot be undone except by restoring that backup.", "Convert"))) return;
          const r = await api("POST", `/api/servers/${id}/convert-custom-rules`); toast(r.note);
        }) }, h("span", { class: "name" }, "Convert to custom rules"), h("span", { class: "value" }, w.customRules ? "Custom" : "Vanilla")),
        h("button", { class: "cell", onclick: () => deleteServer(id, s) }, h("span", { class: "name", style: "color:#ffb0b0" }, "Delete server"), h("span", { class: "arrow" }))),
      w.customRules ? h("div", { style: "margin-top:12px" }, h("h3", { class: "label", style: "font-size:15px" }, "Custom rules"),
        h("div", { class: "kv small" }, Object.entries(w.customRules).filter(([k]) => k !== "spawnItemSlots").flatMap(([k, v]) => [k, String(v)]))) : null)));
}

// A server and its world are one: deleting removes both (backed up, then kept in the trash for 7 days).
async function deleteServer(id, s) {
  if (!(await confirmBox("Delete server", `Delete the server ${s.name} and its world? It is backed up first, then kept in the trash (Settings) for 7 days, where you can restore it.`, "Delete", "red"))) return;
  await guard(async () => {
    await api("DELETE", `/api/servers/${id}`);
    toast(`${s.name} moved to the trash.`);
    sessionStorage.removeItem("bh-portal-id");
    location.hash = "#/";
  });
}

const LIST_INFO = { adminlist: ["Admins", "Can use every server command and remove any object."], modlist: ["Mods", "Can use most server commands."],
  blacklist: ["Banned", "Names or IP addresses that cannot connect."], whitelist: ["Whitelist", ""] };
async function tabLists(id, s, body) {
  const isRunning = running(s);
  const panels = Object.entries(LIST_INFO).map(([key, [title, hint]]) => {
    const area = h("textarea", { class: "mono", spellcheck: "false" }, (s.lists?.[key] || []).join("\n"));
    if (key === "whitelist") return whitelistPanel(id, s, title, area);
    return h("div", { class: "panel list-editor" }, h("h2", { class: "label" }, title), h("p", { class: "hint" }, hint + " One per line."), area,
      h("div", { class: "buttons", style: "margin-top:10px" }, h("button", { class: "green", onclick: () => guard(async () => {
        const r = await api("PUT", `/api/servers/${id}/lists/${key}`, { entries: area.value.split("\n") });
        area.value = r.entries.join("\n"); toast(`${title} saved.`);
      }) }, "Save")));
  });
  body.replaceChildren(
    h("p", { class: "hint", style: "text-align:center" }, isRunning ? "The server is running: changes are made with its own commands." : "The server is stopped: changes are written to its list files."),
    h("div", { class: "grid" }, panels),
    h("div", { class: "buttons", style: "margin-top:14px" }, h("button", { class: "blue", disabled: !isRunning, onclick: () => guard(async () => {
      await api("POST", `/api/servers/${id}/lists/reload`); toast("Lists reloaded from disk.");
    }) }, "Reload lists from disk")));
}

// The whitelist is on when it lists anyone (the server lets everyone in while it is empty). Turning it off keeps
// the names aside in the portal so turning it on again restores them.
function whitelistPanel(id, s, title, area) {
  let on = (s.lists?.whitelist || []).length > 0;
  let stash = s.whitelistStash || [];
  const toggle = h("button", { class: "toggle" });
  const status = h("p", { class: "hint" });
  const save = h("button", { class: "green" }, "Save");
  function show() {
    toggle.classList.toggle("on", on);
    status.textContent = on ? "On: only the players listed here (and mods) can join."
      : stash.length ? "Off: anyone can join. The names below are kept for when you turn it back on."
      : "Off: anyone can join. Add names, then save, to turn it on.";
    if (!on && stash.length) area.value = stash.join("\n");
    area.disabled = !on && stash.length > 0;
    save.disabled = area.disabled;
  }
  toggle.onclick = () => guard(async () => {
    if (!on && !stash.length && !area.value.trim()) throw new ApiError("Add at least one name or IP address first, then save.");
    const r = await api("POST", `/api/servers/${id}/whitelist`, { enabled: !on });
    on = r.entries.length > 0; stash = r.stash;
    if (on) area.value = r.entries.join("\n");
    show(); toast(on ? "Whitelist on." : "Whitelist off: anyone can join.");
  });
  save.onclick = () => guard(async () => {
    const r = await api("PUT", `/api/servers/${id}/lists/whitelist`, { entries: area.value.split("\n") });
    area.value = r.entries.join("\n"); on = r.entries.length > 0; show(); toast(`${title} saved.`);
  });
  show();
  return h("div", { class: "panel list-editor" }, h("h2", { class: "label" }, title),
    h("div", { class: "row", style: "justify-content:space-between;margin-bottom:6px" }, h("span", {}, "Whitelist"), toggle),
    status, area, h("div", { class: "buttons", style: "margin-top:10px" }, save));
}

async function tabBackups(id, s, body) {
  const list = await api("GET", `/api/servers/${id}/backups`);
  const cfg = s.config.backup;
  const enabled = h("button", { class: "toggle" + (cfg.enabled ? " on" : ""), onclick: () => enabled.classList.toggle("on") });
  const every = h("input", { type: "number", min: 1, value: cfg.intervalHours });
  const keep = h("input", { type: "number", min: 1, value: cfg.keep });
  const REASONS = { scheduled: "Scheduled", manual: "Manual", "before-delete": "Before delete", "before-edit": "Before edit", "before-rules": "Before rule change", "before-restore": "Before restore" };
  body.replaceChildren(h("div", { class: "grid" },
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Backups"),
      list.length ? h("div", { class: "table" }, list.map((b) => h("div", { class: "player" },
        h("div", { class: "who" }, fmtTime(b.time), h("small", {}, `${REASONS[b.reason] || b.reason} · ${fmtBytes(b.bytes)}`)),
        h("button", { class: "blue", onclick: () => (location.href = `/api/servers/${id}/backups/${b.file}`) }, "Download"),
        h("button", { class: "green", disabled: s.status !== "stopped" && s.status !== "crashed", onclick: () => guard(async () => {
          if (!(await confirmBox("Restore", `Replace the world with the backup from ${fmtTime(b.time)}? The current state is backed up first.`, "Restore", "red"))) return;
          await api("POST", `/api/servers/${id}/backups/${b.file}/restore`); toast("Restored."); route();
        }) }, "Restore"),
        h("button", { class: "red", onclick: () => guard(async () => {
          if (!(await confirmBox("Delete backup", `Delete the backup from ${fmtTime(b.time)}?`, "Delete", "red"))) return;
          await api("DELETE", `/api/servers/${id}/backups/${b.file}`); route();
        }) }, "Delete")))) : h("p", { class: "muted" }, "No backups yet."),
      h("div", { class: "buttons", style: "margin-top:12px" }, h("button", { class: "green", onclick: () => guard(async () => {
        await api("POST", `/api/servers/${id}/backups`); toast("Backup taken."); route();
      }) }, "Back up now")),
      s.status !== "stopped" ? h("p", { class: "hint" }, "Stop the server to restore a backup.") : null),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Schedule"),
      h("div", { class: "row", style: "justify-content:space-between;margin-bottom:10px" }, h("span", {}, "Scheduled backups"), enabled),
      h("label", { class: "field" }, h("span", {}, "Every (hours)"), every),
      h("label", { class: "field" }, h("span", {}, "Keep the newest"), keep),
      h("div", { class: "buttons" }, h("button", { class: "green", onclick: () => guard(async () => {
        await api("PATCH", `/api/servers/${id}/config`, { backup: { enabled: enabled.classList.contains("on"), intervalHours: +every.value, keep: +keep.value } });
        toast("Schedule saved.");
      }) }, "Save")),
      h("p", { class: "hint" }, "A backup is also taken before every delete, restore, rule change and world edit; those are kept for 30 days."))));
}

async function tabStats(id, s, body) {
  let range = "24h";
  const charts = h("div", { class: "grid" });
  async function draw() {
    const data = await api("GET", `/api/servers/${id}/stats?range=${range}`);
    charts.replaceChildren(...[["players", "Players online", (v) => v], ["cpu", "CPU %", (v) => v], ["rss", "Memory (MB)", (v) => v / 1048576]].map(([key, title, f]) => {
      const c = h("canvas", { class: "chart" });
      const panel = h("div", { class: "panel" }, h("h2", { class: "label" }, title), c);
      requestAnimationFrame(() => chart(c, data.map((d) => [d.t, f(d[key])]), range));
      return panel;
    }));
    if (!data.length) charts.append(h("p", { class: "hint" }, "Samples are taken every 30 s while the server runs."));
  }
  const pick = (r, label) => h("button", { class: r === range ? "green" : "blue", onclick: (e) => { range = r; $$("button", e.target.parentNode).forEach((b) => (b.className = b === e.target ? "green" : "blue")); draw(); } }, label);
  body.replaceChildren(h("div", { class: "buttons", style: "margin-bottom:12px" }, pick("24h", "24 hours"), pick("7d", "7 days")), charts);
  await draw();
}
function chart(canvas, points, range) {
  const dpr = window.devicePixelRatio || 1, W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
  const now = Date.now() / 1000, span = range === "7d" ? 7 * 86400 : 86400, t0 = now - span;
  const max = Math.max(1, ...points.map((p) => p[1])) * 1.1;
  ctx.strokeStyle = "rgba(255,255,255,.15)"; ctx.fillStyle = "#ababab"; ctx.font = "11px sans-serif";
  for (let i = 0; i <= 4; i++) { const y = 8 + (H - 24) * (i / 4); ctx.beginPath(); ctx.moveTo(30, y); ctx.lineTo(W - 4, y); ctx.stroke(); ctx.fillText(String(Math.round(max * (1 - i / 4) * 10) / 10), 2, y + 4); }
  ctx.strokeStyle = "#7fd17f"; ctx.lineWidth = 2; ctx.beginPath();
  let gap = true;
  for (const [t, v] of points) {
    const x = 30 + (W - 34) * ((t - t0) / span), y = 8 + (H - 24) * (1 - v / max);
    gap ? ctx.moveTo(x, y) : ctx.lineTo(x, y); gap = false;
  }
  ctx.stroke();
  ctx.fillStyle = "#ababab"; ctx.fillText(range === "7d" ? "7 days ago" : "24 h ago", 30, H - 4); ctx.fillText("now", W - 28, H - 4);
}

async function tabSettings(id, s, body) {
  const c = s.config;
  const num = (v, min, max) => h("input", { type: "number", min, max, value: v });
  const port = num(c.port, 1024, 65535), maxPlayers = num(c.maxPlayers, 1, 32), saveDelay = num(c.saveDelay, 1, 3600);
  const toggle = (on) => { const t = h("button", { class: "toggle" + (on ? " on" : "") }); t.onclick = () => t.classList.toggle("on"); return t; };
  const autostart = toggle(c.autostart), autorestart = toggle(c.autorestart);
  const NOTIFY = [["crash", "Crash"], ["giveUp", "Crash loop (gave up restarting)"], ["backupFailed", "Backup failed"], ["join", "Player joins"], ["leave", "Player leaves"]];
  const notifyToggles = Object.fromEntries(NOTIFY.map(([k]) => [k, toggle(c.notify[k])]));
  const mods = await api("GET", "/api/mods");
  const modToggles = Object.fromEntries(mods.map((m) => [m.name, toggle(c.mods.includes(m.name))]));
  const on = (t) => t.classList.contains("on");
  const line = (label, el) => h("div", { class: "row", style: "justify-content:space-between;margin:10px 0;gap:12px" }, h("span", {}, label), el);
  body.replaceChildren(h("div", { class: "grid" },
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Server"),
      h("label", { class: "field" }, h("span", {}, "UDP port"), port),
      h("label", { class: "field" }, h("span", {}, "Max players (1-32)"), maxPlayers),
      h("label", { class: "field" }, h("span", {}, "Save every (seconds)"), saveDelay),
      line("Start with the portal", autostart), line("Restart after a crash", autorestart),
      h("p", { class: "hint" }, "Port, players and save interval apply the next time the server starts. After 3 crashes in 10 minutes it is not restarted again.")),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Notifications"), NOTIFY.map(([k, label]) => line(label, notifyToggles[k])),
      h("p", { class: "hint" }, "Shown in the portal, and as browser notifications when allowed in Settings.")),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Mods"),
      mods.length ? mods.map((m) => line(m.name, modToggles[m.name])) : h("p", { class: "muted" }, "No mods uploaded. Add them in Settings."),
      h("p", { class: "hint" }, "Mods are native code loaded into the server process (LD_PRELOAD). Only enable mods you trust."))),
    h("div", { class: "buttons", style: "margin-top:14px" }, h("button", { class: "green wide", onclick: () => guard(async () => {
      await api("PATCH", `/api/servers/${id}/config`, {
        port: +port.value, maxPlayers: +maxPlayers.value, saveDelay: +saveDelay.value, autostart: on(autostart), autorestart: on(autorestart),
        notify: Object.fromEntries(NOTIFY.map(([k]) => [k, on(notifyToggles[k])])),
        mods: mods.filter((m) => on(modToggles[m.name])).map((m) => m.name),
      });
      toast(running(s) ? "Saved. Restart the server to apply port, players and mods." : "Saved.");
    }) }, "Save")),
    h("div", { class: "panel", style: "margin-top:14px" }, h("h2", { class: "label" }, "Delete"),
      h("p", { class: "hint" }, "Deleting the server deletes its world too (each server runs one world). It is backed up first and kept in the trash for 7 days."),
      h("div", { class: "buttons" }, h("button", { class: "red wide", onclick: () => deleteServer(id, s) }, "Delete server"))));
}

// ---- Create World ---------------------------------------------------------------------------------------------------
const SIZES = [["1/16", "1/16 size"], ["1/4", "1/4 size"], ["1", "Normal size"], ["4", "4x size"], ["16", "16x size"]];
async function viewCreate() {
  const [schema, catalog] = await Promise.all([api("GET", "/api/rules"), api("GET", "/api/items")]);
  const items = Object.fromEntries(catalog.items.map((i) => [i.id, i]));
  const f = { name: "", size: "1", expert: false, custom: false, rules: {}, seedValue: "", sun: [127, 127, 127],
    slots: Array.from({ length: schema.spawnSlots }, () => ({ type: 2, count: 1 })), maxPlayers: 16, saveDelay: 10, port: "", autostart: false, start: true };
  const defaults = () => Object.fromEntries(schema.rules.map((r) => [r.name, f.expert ? r.expertDefault : r.default]));
  f.rules = defaults();

  const name = h("input", { type: "text", maxlength: 32, placeholder: "World name" });
  const root = h("div");
  const toggle = (key, after) => { const t = h("button", { class: "toggle" + (f[key] ? " on" : ""), onclick: () => { f[key] = !f[key]; t.classList.toggle("on", f[key]); after?.(); } }); return t; };
  const cell = (label, value, onclick) => h("button", { class: "cell", onclick }, h("span", { class: "name" }, label), h("span", { class: "value" }, value), h("span", { class: "arrow" }));

  function customRules() {
    const out = { ...f.rules };
    if (out.seed === "custom") out.custom_seed_value = f.seedValue;
    schema.sun.keys.forEach((k, i) => (out[k] = f.sun[i]));
    out.spawnItemSlots = f.slots.map((s) => ({ ...s }));
    return out;
  }
  function slotView(s, i) {
    const item = items[s.type];
    const content = s.type === 2 ? h("span", { class: "tag" }, "Default") : s.type === 5 ? h("span", { class: "tag" }, "Empty")
      : [item?.icon ? h("img", { src: item.icon, alt: item.name, title: item.name }) : h("span", { class: "tag" }, item?.name || s.type), s.count > 1 ? h("span", { class: "count" }, s.count) : null];
    return h("button", { class: "slot", title: s.type === 2 ? "Default" : s.type === 5 ? "Empty" : item?.name, onclick: () => pickSlot(i) }, content);
  }
  async function pickSlot(i) {
    const choice = await choose(`Starting slot ${i + 1}`, [{ value: "default", label: "Default" }, { value: "empty", label: "Empty" }, { value: "item", label: "Choose an item..." }]);
    if (choice === "default") f.slots[i] = { type: 2, count: 1 };
    else if (choice === "empty") f.slots[i] = { type: 5, count: 1 };
    else if (choice === "item") {
      const type = await pickItem();
      if (type == null) return;
      let count = 1;
      if (![1, 12].includes(type)) {
        const c = await promptBox("How many?", { message: items[type]?.name, value: "1", type: "number" });
        if (c === null) return;
        count = Math.max(1, Math.min(99, Math.round(+c) || 1));
      }
      f.slots[i] = { type, count };
    }
    render();
  }
  function pickItem() {
    // CustomGameRulesUI's picker: its categories, in its order.
    return new Promise((resolve) => {
      let picked = null;
      const grid = h("div", { class: "item-grid" });
      const cats = h("div", { class: "tabs" });
      const show = (ci) => {
        $$("button", cats).forEach((b, j) => (b.className = j === ci ? "green" : "blue"));
        grid.replaceChildren(...catalog.menu[ci].items.filter((id) => items[id]).map((id) => h("button", { class: "slot", title: items[id].name,
          onclick: () => { picked = id; $(".dim:last-of-type .buttons button")?.click(); } },
          items[id].icon ? h("img", { src: items[id].icon, alt: items[id].name }) : h("span", { class: "tag" }, items[id].name))));
      };
      cats.append(...catalog.menu.map((c, ci) => h("button", { class: "blue", onclick: () => show(ci) }, c.category)));
      dialog({ title: "Choose an item", wide: true, body: h("div", {}, cats, grid), buttons: [{ label: "Cancel", kind: "blue", value: null }] })
        .then(() => resolve(picked));
      if (catalog.menu.length) show(0);
    });
  }
  const raw = h("textarea", { class: "mono", spellcheck: "false", style: "min-height:260px" });
  function render() {
    const sunHex = "#" + f.sun.map((v) => v.toString(16).padStart(2, "0")).join("");
    const sun = h("input", { type: "color", class: "swatch", value: sunHex, title: "Sun colour" });
    sun.oninput = () => { const v = sun.value; f.sun = [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)); };
    raw.value = JSON.stringify(customRules(), null, 2);
    root.replaceChildren(h("div", { class: "grid" },
      h("div", { class: "panel" }, h("h2", { class: "label" }, "New world"),
        h("label", { class: "field" }, h("span", {}, "World name"), name),
        h("div", { class: "table", style: "margin:10px 0" },
          cell("World size", SIZES.find((x) => x[0] === f.size)[1], async () => { const v = await choose("World size", SIZES.map(([value, label]) => ({ value, label })), f.size); if (v) { f.size = v; render(); } })),
        h("div", { class: "row", style: "justify-content:space-between;margin:10px 0" }, h("span", {}, "Expert mode"), toggle("expert", () => { f.rules = { ...defaults(), ...Object.fromEntries(Object.entries(f.rules).filter(([k, v]) => v !== schema.rules.find((r) => r.name === k)[f.expert ? "default" : "expertDefault"])) }; render(); })),
        h("div", { class: "row", style: "justify-content:space-between;margin:10px 0" }, h("span", {}, "Custom rules"), toggle("custom", render)),
        h("p", { class: "hint" }, "World size, expert mode and custom rules are fixed once the world is created.")),
      h("div", { class: "panel" }, h("h2", { class: "label" }, "Server"),
        h("label", { class: "field" }, h("span", {}, "UDP port (empty: next free)"), h("input", { type: "number", min: 1024, max: 65535, value: f.port, oninput: (e) => (f.port = e.target.value) })),
        h("label", { class: "field" }, h("span", {}, "Max players (1-32)"), h("input", { type: "number", min: 1, max: 32, value: f.maxPlayers, oninput: (e) => (f.maxPlayers = +e.target.value) })),
        h("label", { class: "field" }, h("span", {}, "Save every (seconds)"), h("input", { type: "number", min: 1, max: 3600, value: f.saveDelay, oninput: (e) => (f.saveDelay = +e.target.value) })),
        h("div", { class: "row", style: "justify-content:space-between;margin:10px 0" }, h("span", {}, "Start with the portal"), toggle("autostart")),
        h("div", { class: "row", style: "justify-content:space-between;margin:10px 0" }, h("span", {}, "Start now"), toggle("start")))),
      f.custom ? h("div", { class: "grid", style: "margin-top:14px" },
        h("div", { class: "panel" }, h("h2", { class: "label" }, "Custom rules"),
          h("div", { class: "table" }, schema.rules.map((r) => cell(r.name, f.rules[r.name] === "custom" && r.name === "seed" ? `custom: ${f.seedValue}` : f.rules[r.name], async () => {
            const v = await choose(r.name, r.options, f.rules[r.name]);
            if (v === undefined) return;
            f.rules[r.name] = v;
            if (r.name === "seed" && v === "custom") {
              const s = await promptBox("Seed", { message: "A number, or any text (it is hashed).", value: f.seedValue });
              if (!s) f.rules.seed = "random"; else f.seedValue = s;
            }
            render();
          })))),
        h("div", {},
          h("div", { class: "panel" }, h("h2", { class: "label" }, "Starting items"), h("div", { class: "slots" }, f.slots.map(slotView)),
            h("p", { class: "hint" }, "What each new blockhead starts with. Default keeps the game's usual item for that slot.")),
          h("div", { class: "panel", style: "margin-top:14px" }, h("h2", { class: "label" }, "Sun colour"),
            h("div", { class: "row", style: "justify-content:center" }, sun, h("button", { class: "blue", onclick: () => { f.sun = [127, 127, 127]; render(); } }, "Default"))),
          h("div", { class: "panel", style: "margin-top:14px" }, h("h2", { class: "label" }, "Raw JSON"), raw,
            h("div", { class: "buttons", style: "margin-top:10px" }, h("button", { class: "blue", onclick: () => guard(async () => {
              let o;
              try { o = JSON.parse(raw.value); } catch (e) { throw new ApiError("That is not valid JSON: " + e.message); }
              for (const r of schema.rules) if (r.name in o) f.rules[r.name] = o[r.name];
              if (o.custom_seed_value) f.seedValue = String(o.custom_seed_value);
              if (schema.sun.keys.every((k) => k in o)) f.sun = schema.sun.keys.map((k) => o[k]);
              if (Array.isArray(o.spawnItemSlots)) f.slots = o.spawnItemSlots;
              render(); toast("Applied (checked when you create the world).");
            }) }, "Apply JSON")),
            h("p", { class: "hint" }, "The same rules as the form above, as the server receives them.")))) : null,
      h("div", { class: "buttons", style: "margin-top:16px" },
        h("button", { class: "blue wide", onclick: () => (location.hash = "#/") }, "Cancel"),
        h("button", { class: "green wide", onclick: create }, "Create World")));
  }
  const create = () => guard(async () => {
    if (!name.value.trim()) throw new ApiError("Give the world a name.");
    const s = await api("POST", "/api/servers", {
      name: name.value.trim(), size: f.size, expert: f.expert, customRules: f.custom ? customRules() : null,
      port: f.port ? +f.port : null, maxPlayers: f.maxPlayers, saveDelay: f.saveDelay, autostart: f.autostart, start: f.start,
    });
    Sound.play("portal");
    location.hash = `#/server/${s.id}/console`;
  });
  render();
  mount(h("div", { class: "page" }, h("h1", { class: "label", style: "text-align:center" }, "Create World"), root));
  name.focus();
}

// ---- Settings ------------------------------------------------------------------------------------------------------
async function viewSettings() {
  const [st, mods, trash] = await Promise.all([api("GET", "/api/state"), api("GET", "/api/mods"), api("GET", "/api/trash")]);
  const modFile = h("input", { type: "file", accept: ".so", style: "display:none" });
  modFile.onchange = () => guard(async () => {
    if (!modFile.files[0]) return;
    if (!(await confirmBox("Upload mod", "Mods are native code that runs inside the game server with full access to this container. Only upload mods you trust.", "Upload", "red"))) return;
    const fd = new FormData(); fd.append("file", modFile.files[0]);
    await api("POST", "/api/mods", fd); toast("Mod uploaded."); route();
  });
  const changePassword = () => guard(async () => {
    const cur = h("input", { type: "password", placeholder: "Current password", autocomplete: "current-password" });
    const n1 = h("input", { type: "password", placeholder: "New password", autocomplete: "new-password" });
    const n2 = h("input", { type: "password", placeholder: "New password again", autocomplete: "new-password" });
    const ok = await dialog({ title: "Change password", body: h("div", {}, cur, h("div", { style: "height:8px" }), n1, h("div", { style: "height:8px" }), n2),
      buttons: [{ label: "Cancel", kind: "blue", value: false }, { label: "Change", kind: "green", value: true }] });
    if (!ok) return;
    if (n1.value !== n2.value) throw new ApiError("The new passwords do not match.");
    await api("POST", "/api/password", { current: cur.value, new: n1.value });
    toast("Password changed. Other devices are signed out.");
  });
  const notif = "Notification" in window ? Notification.permission : "unsupported";
  mount(h("div", { class: "page" },
    h("div", { class: "row", style: "margin-top:6px" }, h("button", { class: "blue", onclick: () => (location.hash = "#/") }, "Back"),
      h("h1", { class: "label", style: "flex:1;text-align:center;margin:0" }, "Settings"), h("span", { style: "width:88px" })),
    h("div", { class: "grid", style: "margin-top:14px" },
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Portal"), h("div", { class: "table" },
      st.passwordFromEnvironment ? h("div", { class: "cell" }, h("span", { class: "name" }, "Password"), h("span", { class: "value" }, "Set by PORTAL_PASSWORD"))
        : h("button", { class: "cell", onclick: changePassword }, h("span", { class: "name" }, "Change password"), h("span", { class: "arrow" })),
      h("button", { class: "cell", onclick: () => { Sound.toggle(); route(); } }, h("span", { class: "name" }, "Sounds"), h("span", { class: "value" }, Sound.on ? "On" : "Off")),
      h("button", { class: "cell", disabled: notif !== "default", onclick: () => Notification.requestPermission().then(route) }, h("span", { class: "name" }, "Browser notifications"),
        h("span", { class: "value" }, { granted: "Allowed", denied: "Blocked in the browser", default: "Ask", unsupported: "Not supported" }[notif])),
      h("button", { class: "cell", onclick: () => (location.hash = "#/assets") }, h("span", { class: "name" }, "Game art"), h("span", { class: "value" }, st.assets.ready ? "From " + (st.assets.source || "APK") : "Not uploaded")),
      h("button", { class: "cell", onclick: () => guard(async () => { await api("POST", "/api/logout"); location.hash = "#/login"; route(); }) }, h("span", { class: "name" }, "Sign out"), h("span", { class: "arrow" })))),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Mods"),
      mods.length ? mods.map((m) => h("div", { class: "player" }, h("div", { class: "who" }, m.name, h("small", {}, `${fmtBytes(m.bytes)} · used by ${m.servers.length} server(s)`)),
        h("button", { class: "red", onclick: () => guard(async () => {
          if (!(await confirmBox("Delete mod", `Delete ${m.name}? It is turned off on every server.`, "Delete", "red"))) return;
          await api("DELETE", `/api/mods/${encodeURIComponent(m.name)}`); route();
        }) }, "Delete"))) : h("p", { class: "muted" }, "No mods."),
      h("div", { class: "buttons", style: "margin-top:12px" }, h("button", { class: "green", onclick: () => modFile.click() }, "Upload .so"), modFile),
      h("p", { class: "hint" }, "Enable a mod per server in that server's Settings tab.")),
    h("div", { class: "panel" }, h("h2", { class: "label" }, "Trash"),
      trash.length ? trash.map((t) => h("div", { class: "player" }, h("div", { class: "who" }, t.name, h("small", {}, `Deleted ${fmtTime(t.deleted)} · purged ${fmtTime(t.purge)}`)),
        h("button", { class: "green", onclick: () => guard(async () => { await api("POST", `/api/trash/${t.key}/restore`); toast(`${t.name} restored.`); route(); }) }, "Restore"),
        h("button", { class: "red", onclick: () => guard(async () => {
          if (!(await confirmBox("Delete forever", `Delete ${t.name} for good? Its backups are kept.`, "Delete", "red"))) return;
          await api("DELETE", `/api/trash/${t.key}`); route();
        }) }, "Delete"))) : h("p", { class: "muted" }, "The trash is empty."),
      h("p", { class: "hint" }, "Deleted worlds stay here for 7 days.")))));
}

guard(route);
