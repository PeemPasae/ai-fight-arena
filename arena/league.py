"""Matches the admin sets up (who vs who), the queue order, and the standings table."""
import time

ELO_START, ELO_K = 1000, 32


class BadMatch(Exception):
    pass


def player_ready(db, pid):
    p = db["players"].get(pid)
    return bool(p) and db["chars"].get(p["char"], {}).get("status") == "ready"


def create_match(store, p1, p2, count=1, swap=False):
    """Queue p1 vs p2 `count` times; with swap=True every other game swaps sides."""
    with store.tx() as db:
        for pid in (p1, p2):
            if pid not in db["players"]:
                raise BadMatch("ไม่พบผู้เล่น")
        if p1 == p2:
            raise BadMatch("เลือกผู้เล่นคนละคน")
        ids = []
        for i in range(max(1, min(int(count), 10))):
            a, b = (p2, p1) if swap and i % 2 else (p1, p2)
            mid = store.new_id(db, "match")
            db["matches"][mid] = {"id": mid, "p1": a, "p2": b, "status": "scheduled", "created": time.time(),
                                  "result": None, "note": "", "tries": 0}
            ids.append(mid)
    return ids


def next_match(db):
    """Oldest queued match whose two characters are ready (others wait for their load test)."""
    todo = sorted((m for m in db["matches"].values() if m["status"] == "scheduled"), key=lambda m: m["id"])
    for m in todo:
        if player_ready(db, m["p1"]) and player_ready(db, m["p2"]):
            return m
    return None


def hp_pct_diff(result):
    """Sum over rounds of (P1 life % left - P2 life % left): fair between characters
    with different max life (e.g. 1000 vs 1500)."""
    total = 0
    for rd in result.get("rounds", []):
        m1, m2 = (rd.get("hp_max") or [1000, 1000])
        total += round(100 * rd["hp"][0] / max(m1, 1)) - round(100 * rd["hp"][1] / max(m2, 1))
    return total


def standings(db):
    rows = {}
    for pid, p in db["players"].items():
        ch = db["chars"].get(p["char"], {})
        rows[pid] = {"id": pid, "name": p["name"], "char_name": ch.get("char_name", "?"),
                     "bot": bool(p.get("bot") and p["bot"].get("approved")), "played": 0, "w": 0, "l": 0, "d": 0,
                     "rw": 0, "rl": 0, "hp": 0, "elo": ELO_START, "form": []}
    done = sorted((m for m in db["matches"].values() if m["status"] == "done" and m["result"]),
                  key=lambda m: m["result"].get("ended", 0))
    for m in done:
        a, b = rows.get(m["p1"]), rows.get(m["p2"])
        if not a or not b:
            continue
        r = m["result"]
        w1, w2 = r["wins"]
        a["played"] += 1
        b["played"] += 1
        a["rw"], a["rl"], b["rw"], b["rl"] = a["rw"] + w1, a["rl"] + w2, b["rw"] + w2, b["rl"] + w1
        pct = hp_pct_diff(r)
        a["hp"] += pct
        b["hp"] -= pct
        score = 1.0 if w1 > w2 else 0.0 if w2 > w1 else 0.5
        for x, s in ((a, score), (b, 1 - score)):
            x["w" if s == 1 else "l" if s == 0 else "d"] += 1
            x["form"].append("W" if s == 1 else "L" if s == 0 else "D")
        exp = 1 / (1 + 10 ** ((b["elo"] - a["elo"]) / 400))
        a["elo"] += ELO_K * (score - exp)
        b["elo"] -= ELO_K * (score - exp)
    out = list(rows.values())
    for r in out:
        r["elo"] = round(r["elo"])
        r["pts"] = 3 * r["w"] + r["d"]
        r["form"] = r["form"][-5:]
    out.sort(key=lambda r: (-r["pts"], -(r["rw"] - r["rl"]), -r["hp"], -r["elo"], r["name"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out
