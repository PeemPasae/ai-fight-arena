"""Background thread that owns the engine: load-tests new entries, then (while the
league is running) plays scheduled matches one at a time."""
import json
import threading
import time
import traceback

from . import config, engine, fairness, league

MAX_TRIES = 3


class Worker(threading.Thread):
    def __init__(self, store):
        super().__init__(daemon=True, name="arena-worker")
        self.store = store
        self.live = {"phase": "idle", "match": None, "frame": None, "rounds": [], "hp_max": [1, 1]}
        self.live_lock = threading.Lock()
        self.stop_match = threading.Event()     # aborts the current match only
        self.quit = threading.Event()

    # live view shared with the web server
    def live_update(self, **kw):
        with self.live_lock:
            self.live.update(kw)

    def live_snapshot(self):
        with self.live_lock:
            return dict(self.live)

    class _LiveProxy(dict):
        def __init__(self, w):
            super().__init__()
            self.w = w

        def update(self, **kw):           # engine.run_match calls live.update(...)
            self.w.live_update(**kw)

        def get(self, k, default=None):
            return self.w.live_snapshot().get(k, default)

    def run(self):
        proxy = self._LiveProxy(self)
        while not self.quit.is_set():
            try:
                if self._smoke_one(proxy) or self._match_one(proxy):
                    continue
            except Exception:
                traceback.print_exc()
            self.live_update(phase="idle", match=None, title=None)
            self.quit.wait(1.0)

    def _smoke_one(self, live):
        db = self.store.read()
        todo = [c for c in db["chars"].values() if c["status"] == "queued_test"]
        if not todo:
            return False
        c = sorted(todo, key=lambda x: x["created"])[0]
        with self.store.tx() as d:
            d["chars"][c["id"]]["status"] = "testing"
        self.stop_match.clear()
        self.live_update(match=None, title=f"ทดสอบโหลดตัวละคร: {c['char_name']}",
                         names=[c["char_name"], "kfm (คู่ทดสอบ)"], entries=None)
        ok, note, shown, stats = engine.smoke_test(c, live, self.stop_match, f"test_{c['id']}")
        status = "ready" if ok else "failed"
        if ok:
            banned, why = fairness.verdict(stats)
            if banned:
                status, note = "banned", why
        with self.store.tx() as d:
            if c["id"] in d["chars"]:
                d["chars"][c["id"]].update(status=status, note=note, probe=stats,
                                           fair_v=fairness.FAIR_VERSION if not self.stop_match.is_set() else None,
                                           in_game_name=shown or d["chars"][c["id"]].get("in_game_name"))
        return True

    @staticmethod
    def side(db, pid):
        """What the engine needs for one slot: the player's character + the player's bot."""
        p = db["players"][pid]
        ch = db["chars"][p["char"]]
        return {**ch, "name": p["name"], "bot": p.get("bot")}

    def _match_one(self, live):
        db = self.store.read()
        m = league.next_match(db)
        if not m:
            return False
        p1, p2 = self.side(db, m["p1"]), self.side(db, m["p2"])
        with self.store.tx() as d:
            d["matches"][m["id"]].update(status="running", started=time.time())
        self.stop_match.clear()
        label = lambda s: f"{s['name']} ({s['char_name']})"
        self.live_update(match=m["id"], title=f"{label(p1)} vs {label(p2)}", names=[label(p1), label(p2)],
                         entries=[m["p1"], m["p2"]])
        res = engine.run_match(p1, p2, live, self.stop_match, m["id"])
        timeline = res.pop("timeline", [])
        res["ended"] = time.time()
        res["winner"] = {1: m["p1"], 2: m["p2"]}.get(res.get("winner_slot"))
        (config.DATA / "matches").mkdir(parents=True, exist_ok=True)
        (config.DATA / "matches" / f"{m['id']}.json").write_text(
            json.dumps({"timeline": timeline}, separators=(",", ":")), encoding="utf-8")
        with self.store.tx() as d:
            mm = d["matches"].get(m["id"])
            if mm is None:
                return True
            mm["tries"] = mm.get("tries", 0) + 1
            if self.stop_match.is_set() and res["status"] != "done":
                mm.update(status="cancelled", result=res, note="หยุดโดยแอดมิน")
            elif res["status"] == "done":
                mm.update(status="done", result=res, note="")
            elif mm["tries"] < MAX_TRIES and res["status"] == "invalid":
                mm.update(status="scheduled", note=f"แข่งใหม่ ({res['note']})")
            else:
                mm.update(status=res["status"], result=res, note=res["note"])
        return True
