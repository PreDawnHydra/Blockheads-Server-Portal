# Plan

Progress on [SPEC.md](SPEC.md). `[x]` done and verified, `[~]` in progress, `[ ]` to do.

## Milestone 1 — backend core
- [ ] Container: Dockerfile FROM the pinned server image, Python deps, compose file with host networking
- [ ] Settings, first-run password, login sessions, rate limiting
- [ ] World store: list, read world info (worldv2 / world_db), create, rename, clone, delete to trash, export, import
- [ ] Server process manager: start / stop (`/stop`) / restart, console stdin, log capture and rotation,
      crash restart with crash-loop limit, autostart, shutdown of all servers
- [ ] Log parsing: players online, chat, events
- [ ] Lists (admin / mod / ban / whitelist): commands while running, files while stopped
- [ ] World database edits while stopped (welcome message, max players, password, PvP) with backup first
- [ ] Backups: scheduled, before risky actions, retention, restore
- [ ] Mods upload and per-server enable
- [ ] Stats sampling and history
- [ ] WebSocket: console, players, chat, notifications

## Milestone 2 — theme
- [ ] Asset extraction from the uploaded APK
- [ ] Game-faithful UI (fonts, panels, buttons, background, portal icons, sounds) + fallback skin
- [ ] Create World form with rule pickers, sun colour, starting items with icons, raw JSON tab

## Milestone 3 — verification
- [ ] End-to-end in Docker: create, start, join from the port (desktop and phone), chat, kick, stop, export/import
- [ ] README
