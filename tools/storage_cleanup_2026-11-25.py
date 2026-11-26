"""One-off cleanup (run with the server stopped):
  1. record the sha256 of every uploaded archive (duplicate detection from now on)
  2. merge characters uploaded twice with identical archives into one
  3. delete submissions/<cid>/char (extracted copies; the game copy in engine/chars is used)
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from arena import config, engine, submissions  # noqa: E402
from arena.store import Store  # noqa: E402

store = Store()
freed = 0


def size(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) if Path(p).exists() else 0


with store.tx() as db:
    # 1. fingerprints
    for cid, ch in sorted(db["chars"].items()):
        ups = list((config.SUBMISSIONS / cid).glob("upload.*"))
        if ups and not ch.get("sha256"):
            ch["sha256"] = submissions.file_sha256(ups[0])
    # 2. merge identical uploads into the oldest one
    first = {}
    for cid in sorted(db["chars"]):
        h = db["chars"][cid].get("sha256")
        if not h:
            continue
        if h not in first:
            first[h] = cid
            continue
        keep = first[h]
        moved = [p["name"] for p in db["players"].values() if p["char"] == cid]
        for p in db["players"].values():
            if p["char"] == cid:
                p["char"] = keep
        freed += size(config.ENGINE / "chars" / cid) + size(config.SUBMISSIONS / cid)
        engine.remove_char(cid)
        shutil.rmtree(config.SUBMISSIONS / cid, ignore_errors=True)
        db["chars"].pop(cid)
        print(f"merged {cid} into {keep} (players moved: {', '.join(moved) or '-'})")
    submissions.sync_select(db)

# 3. extracted copies
for d in sorted(config.SUBMISSIONS.glob("c*/char")):
    freed += size(d)
    shutil.rmtree(d, ignore_errors=True)
    print(f"removed {d.relative_to(ROOT)}")
print(f"freed {freed / 2**20:.0f} MB")
print(json.dumps({c: ch.get("sha256", "")[:12] for c, ch in store.read()["chars"].items()}, indent=0))
