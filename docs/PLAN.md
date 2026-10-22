# Plan

Progress on [SPEC.md](SPEC.md). `[x]` done and verified, `[ ]` to do.

## Milestone 1 — backend core
- [x] Container: Dockerfile FROM the pinned server image, Python deps (pinned for Ubuntu 22.04's Python 3.10),
      compose file with host networking and a 60 s stop grace period
- [x] Settings, first-run password or `PORTAL_PASSWORD`, sessions (30 days / browser), login rate limiting
- [x] World store: list, info (world_db record + summary file), create, rename, clone, delete to trash, export,
      import (id kept unless taken), players seen (server_db `<playerID>_info`)
- [x] Server processes: start / stop (`/stop`) / restart, console, logs with rotation, crash restart with the
      3-in-10-minutes limit, autostart, stop-all on shutdown, `--no-exit`
- [x] Log parsing from real client sessions: joins, leaves (by player id), `/players` replies, chat
- [x] Lists: commands while running, files while stopped; reload from disk
- [x] World database edits while stopped (name, welcome message, password, PvP) with a backup first
- [x] Backups: scheduled, before risky actions, retention, restore
- [x] Mods: upload, per-server enable via LD_PRELOAD (verified a test mod's constructor runs in the server)
- [x] Stats sampling and history; WebSocket events; in-portal notifications

## Milestone 2 — theme
- [x] Asset extraction from the uploaded APK (images, fonts, sounds, launcher icon, item icons)
- [x] Game-faithful UI from the client's code: menu background, stars, clocks, portals (art by portal level,
      the menu's order), buttons, dialogs, panels, table cells, toggles, font, sounds; plain fallback
- [x] Create World: every rule, sun colour, starting items with icons (the game's picker), raw JSON tab

## Milestone 3 — verification
- [x] Docker end to end: create, console, chat, players, stop, list and world edits, clone, export/import,
      backups and restore, trash, three servers at once, crash restart, docker stop saving every world
- [x] Joined from the port's desktop client: player list, chat both ways, kick, `/players`, leave
- [x] Browser walkthrough (desktop and phone sizes) with no page errors
- [x] README
- [ ] Owner: try it on their server, and with an original-version client if one is handy

## Feedback round 1 (2026-10-22)
- [x] Settings page had no way back: Back button
- [x] Whitelist on/off: the server treats an empty whitelist as off (BHServer -playerIsWhiteListedWithInfo:);
      the toggle keeps the names aside while off and restores them
- [x] Stop took 30 s and pages needed reloads: with --no-exit, /stop saves ("Exiting World.") but leaves the
      process idle; the portal now ends it once that line appears (save finished: -[GameController stop]), and
      server pages redraw their tab when the server's state changes; World tab shows a stop notice with a button
- [x] A deleted server lingered as an id-named portal: only existing (or being-created) worlds are servers;
      "Delete server" (World and Settings tabs) explains it deletes the world; settings purge with the trash;
      an address of a gone server goes home

## Open questions
- The sun colour picker: the game has `colorPicker.png`; the portal uses the browser's colour input.
- Workbench cube icons use the side face at level 0; flax mats and rock fall back to a generic cell.
