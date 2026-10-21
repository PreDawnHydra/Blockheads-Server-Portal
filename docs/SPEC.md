# Blockheads Server Portal — specification

Agreed with the owner on 2026-10-21. A self-hosted web UI, run in Docker, that manages any number of
The Blockheads 1.7.1 dedicated servers, themed with the game's own art.

## Deployment

- One container, built `FROM theblockheads/server` pinned by digest (`sha256:cdd0d5fc…`), x86-64 only. The server
  binary comes from that image (Majic Jungle published the 1.7.1 Linux server for free); if the image disappears,
  rebuild it from the archived 1.7.1 server the same way the image does.
- `network_mode: host`. The web UI listens on `PORTAL_PORT` (default 8080). Game servers claim UDP ports at runtime
  (next free from 15151, or one typed in); the portal checks a port is free before using it.
- Volumes: `/data` (worlds, trash, mods, assets, settings, stats, logs); optional `/backups` (used if mounted).
- `stop_grace_period: 60s`. On shutdown the portal sends `/stop` to every server and kills any still running after
  30 s.
- Reachable on the LAN by default; meant to sit behind the user's reverse proxy for HTTPS. No TLS of its own.

## First run and login

- Admin password from `PORTAL_PASSWORD` if set, else a setup page asks for one.
- Setup then asks for the user's own APK. The portal extracts the theme (buttons, panels, fonts, backgrounds,
  portal and item icons, UI sounds) into `/data/assets`. No game file is ever in the image or the repo. Until then a
  plain fallback skin is shown.
- One admin password; login attempts rate-limited; sessions 30 days with "remember me", else until the browser
  closes; password changeable in Settings. Auth is structured so roles can be added later.

## Look

- The game's own fonts, 9-slice blue panels and buttons, starry clock background, portal icons for worlds; works on
  phone browsers.
- Click, start and error sounds on by default; a speaker toggle always in the top bar, remembered per browser.

## Servers

One server process per world, driven through its stdin console (console commands run with owner rights).

- Create, start, stop, restart, delete. Stop is always `/stop` and waiting for exit (the server ignores signals;
  killing it loses progress since the last save).
- Per server: start with the portal; restart after a crash, giving up after 3 crashes in 10 minutes.
- Every launch flag passed explicitly: port, max players (1–32, default 16), save delay (default 10 s), world size
  (1/16, 1/4, 1, 4, 16), expert mode, custom rules, convert to custom rules.
- Live console (last 1000 lines, then streaming; raw commands), live player list (from the log's join/leave lines
  and `/players`) with kick / ban / ban without device / mod / admin / whitelist, chat read and send (as SERVER),
  a Diagnostics panel (`/debug-log`).
- Buttons for every mod / admin / owner command; the cloud-only commands (`/set-privacy`, `/set-owner`,
  `/set-credit`, `/remove-owner`, `/set-salt`, `/reset-owner`) are hidden.
- Admin / mod / ban / whitelist lists: through commands while running, files while stopped, plus "reload lists
  from disk" (`/load-lists`). The server rewrites all four files on any change and reads them only at load.
- Password and PvP: commands while running, world database while stopped. Welcome message and max players: world
  database only while stopped, with an automatic backup first.
- Logs rotated at 5 MB, 5 kept, downloadable.

## Worlds

- Create World: game-style pickers for every custom rule, a sun colour picker, seven starting-item slots with the
  real item icons, and a raw JSON tab validated against the known rules.
- World page: name, ID, size, expert, seed, custom rules, created and last-saved dates, in-game days, port, max
  players, password set, PvP, welcome message, recent players.
- Export (.zip of the save folder), import (keeps the ID unless taken, then a new ID and " (2)" on the name), clone
  (always a new ID), rename, delete (to a trash emptied after 7 days).
- Not in v1: moving worlds to or from the game's offline saves.

## Backups

Scheduled per server with retention; automatic before every delete, import, rule change and world database edit;
one-click restore.

## Mods

`.so` upload, admin only, with a warning; enabled per server, off by default; loaded through the image's `MODS`
(`LD_PRELOAD`).

## Stats and notifications

- Player count and CPU/RAM every 30 s, kept 7 days in SQLite; 24 h and 7 d graphs.
- Notifications in the UI only (toasts, browser notifications while a tab is open), configurable per server: crash,
  crash-loop give-up and backup failure on by default; join and leave off.

## Testing

Log formats and cross-play verified by joining portal servers from the Blockheads port (phone and desktop); the
owner tries an original client if available.

## Server facts this relies on (1.7.1, researched 2026-10-21)

- stdin is a console: `/command` lines run as the owner; other lines are chat from SERVER. `/stop` saves, logs
  `Exiting World.` and exits 0. No signal handlers.
- Log: NSLog lines `YYYY-MM-DD HH:MM:SS.mmm blockheads_server171[pid:tid] message`; `WORLD - Player Connected
  ALIAS | IP | PLAYERID`, `WORLD - Player Disconnected ALIAS`, chat `ALIAS: message`, `World load complete.`,
  `Failed to start server. Perhaps port %@ is already in use?`.
- Save folder `<id>/`: `worldv2` (XML plist), `world_db`, `server_db`, `lightBlocks` (LMDB), and
  `{adminlist,modlist,blacklist,whitelist}.txt` (first line a comment, then one name or IP per line).
- `world_db` named db `main`, key `worldv2` (plist): worldName, saveID, worldWidthMacro, expertMode,
  customRulesDict, creationDate, saveDate, randomSeed, worldTime, hostPort, maxPlayers, serverPassword,
  pvpDisabled, welcomeMessage, …
- Real defaults differ from `--help`: save delay 10, max players 32 — hence every flag is always passed.
