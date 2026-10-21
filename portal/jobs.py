"""Background jobs: stats sampling, scheduled backups, trash purge."""
import asyncio
import time

from . import backups, config, db, worlds
from .servers import manager, server_config


async def stats_loop() -> None:
    while True:
        for world_id, s in list(manager.servers.items()):
            if s.pid:
                cpu, rss = s.usage()
                db.add_stat(world_id, len(s.players), cpu, rss)
        db.prune_stats(time.time() - config.STATS_KEEP_DAYS * 86400)
        await asyncio.sleep(config.STATS_INTERVAL)


async def backup_loop() -> None:
    while True:
        for world_id in worlds.all_ids():
            cfg = server_config(world_id)["backup"]
            if not cfg["enabled"]:
                continue
            last = next((b["time"] for b in backups.listing(world_id) if b["reason"] == "scheduled"), 0)
            if time.time() - last >= cfg["intervalHours"] * 3600:
                await asyncio.to_thread(backups.safe_create, world_id, "scheduled")
                await asyncio.to_thread(backups.prune, world_id, cfg["keep"])
        worlds.empty_trash(older_than=time.time() - config.TRASH_DAYS * 86400)
        await asyncio.sleep(300)
