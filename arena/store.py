"""Tiny JSON database shared by the web server and the match worker thread.

  chars    roster of characters (house characters + ones people uploaded); anyone may
           pick a ready one unless it is reserved for a player
  players  people: name + the character they fight with (+ their own bot, optional)
  matches  set up by the admin (who vs who), played in order by the worker

Every change goes through `tx()`, which holds a lock and writes the file atomically."""
import json
import threading
import time
from contextlib import contextmanager

from . import config

EMPTY = {"chars": {}, "players": {}, "matches": {}, "seq": {"char": 0, "player": 0, "match": 0}}
PREFIX = {"char": "c", "player": "p", "match": "m"}


class Store:
    def __init__(self, path=None):
        self.path = path or (config.DATA / "arena.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        if self.path.exists():
            self.db = json.loads(self.path.read_text(encoding="utf-8"))
            if "entries" in self.db:
                self.db = migrate_v1(self.db)
            for k, v in EMPTY.items():
                self.db.setdefault(k, json.loads(json.dumps(v)))
            for k in EMPTY["seq"]:
                self.db["seq"].setdefault(k, 0)
        else:
            self.db = json.loads(json.dumps(EMPTY))
        self._save()

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.db, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    @contextmanager
    def tx(self):
        with self.lock:
            yield self.db
            self._save()

    def read(self):
        with self.lock:
            return json.loads(json.dumps(self.db))

    @staticmethod
    def new_id(db, kind):
        db["seq"][kind] += 1
        n = db["seq"][kind]
        return f"{PREFIX[kind]}{n:04d}" if kind == "match" else f"{PREFIX[kind]}{n:03d}"


def migrate_v1(old):
    """v1 had one 'entries' table (entry = character). General (our bot) becomes the
    player ภีม; every entry becomes a roster character. Old v1 results are dropped
    (they were between characters, not players)."""
    db = json.loads(json.dumps(EMPTY))
    for eid in sorted(old["entries"]):
        e = old["entries"][eid]
        cid = Store.new_id(db, "char")
        db["chars"][cid] = {
            "id": cid, "char_name": e.get("char_name") or e["name"], "def_rel": e["def_rel"],
            "credit": e.get("author_credit", ""), "in_game_name": e.get("in_game_name"),
            "status": e["status"], "note": e.get("note", ""), "source": e.get("source", "local"),
            "uploaded_by": "", "reserved_for": None, "created": e.get("created", time.time()),
        }
        if e.get("bot"):
            pid = Store.new_id(db, "player")
            name = "ภีม" if (e.get("char_name") or "").lower() == "general" else e["name"]
            db["players"][pid] = {"id": pid, "name": name, "char": cid, "bot": e["bot"], "active": True,
                                  "created": e.get("created", time.time())}
            db["chars"][cid]["reserved_for"] = pid
    return db
