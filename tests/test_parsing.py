"""Log parsing and rule validation, against lines captured from the real 1.7.1 server with a real client."""
import os
import tempfile

os.environ.setdefault("PORTAL_DATA", tempfile.mkdtemp())

from portal import config, rules  # noqa: E402
from portal.servers import Server  # noqa: E402

P = "2026-10-21 23:57:23.378 blockheads_server171[19:19] "
JOIN = P + "UI DESKTOP - Player Connected IPAD | 127.0.0.1 | 09401fded433c34709fd1f1872728162"
CLIENT_GONE = P + "UI DESKTOP - Client disconnected:09401fded433c34709fd1f1872728162"
PLAYER_GONE = P + "UI DESKTOP - Player Disconnected IPAD"


def server():
    config.ensure_dirs()
    return Server("0123456789abcdef0123456789abcdef")


def test_join_and_leave_by_player_id():
    s = server()
    s._handle(JOIN)
    assert list(s.players) == ["IPAD"] and s.players["IPAD"]["ip"] == "127.0.0.1"
    s._handle(CLIENT_GONE)
    assert s.players == {}
    s._handle(PLAYER_GONE)  # the second leave line for the same player is harmless
    assert s.players == {}


def test_world_names_with_dashes():
    s = server()
    s._handle(P + "MY - WORLD - Player Connected BOB | 10.0.0.2 | abc")
    assert "BOB" in s.players


def test_players_reply_rebuilds_the_list():
    s = server()
    s._handle(JOIN)
    s._handle(P + "SERVER: There are 2 players connected:")
    s._handle("IPAD | 127.0.0.1 | 09401fded433c34709fd1f1872728162")
    s._handle("ALICE | 10.0.0.5 | ffff")
    assert sorted(s.players) == ["ALICE", "IPAD"]


def test_chat_and_command_replies():
    s = server()
    s._handle(JOIN)
    s._handle(P + "IPAD: hello portal")
    assert [m["text"] for m in s.chat] == ["hello portal"]
    s._last_command_at = __import__("time").time()  # a console command was just sent
    s._handle(P + "SERVER: Adminlist:")
    assert len(s.chat) == 1


def test_rules_validation():
    assert rules.validate({"temperature": "very hot"}) == []
    assert rules.validate({"temperature": "boiling"})
    assert rules.validate({"bogus": "x"})
    assert rules.validate({"seed": "custom"})
    assert rules.validate({"seed": "custom", "custom_seed_value": "12345"}) == []
    slots = [{"type": 2, "count": 1}] * 7
    assert rules.validate({"spawnItemSlots": slots}) == []
    assert rules.validate({"spawnItemSlots": slots[:6]})
    assert rules.validate({"spawnItemSlots": [{"type": 12, "count": 5}] + slots[1:]})  # basket: 1 only
    assert rules.validate({"spawnItemSlots": [{"type": 8, "count": 100}] + slots[1:]})
