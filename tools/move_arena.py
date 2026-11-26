"""Move the arena (characters, players, results) to another PC.

  python tools/move_arena.py export <bundle.zip>     on the old server (stop the server first)
  python tools/move_arena.py import <bundle.zip>     on the new server, after `git clone` (server stopped)

The bundle holds data/arena.json, match logs/traces, uploaded bots and the installed
characters (engine/chars/). It contains players' names and their uploads, so pass it
around privately (USB / a private Drive link), never through git.

Left out on purpose: the admin token (the new server makes its own), server logs,
rejected-upload logs (they hold IP addresses), the original upload archives (their
sha256 is already in arena.json), and any bot that lives outside this folder (a
player's personal bot on the old PC) - that player fights with the engine AI instead.
"""
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from arena import config  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

DB = config.DATA / "arena.json"
KEEP_DATA_DIRS = ("matches", "traces")
STORED = {".sff", ".snd", ".zip", ".rar", ".png", ".ogg", ".mp3", ".wav", ".gz"}   # already compressed


def _rel(p):
    return PurePosixPath(Path(p).resolve().relative_to(ROOT)).as_posix()


def export(bundle):
    db = json.loads(DB.read_text(encoding="utf-8"))
    dropped = []
    for p in db["players"].values():
        bot = p.get("bot")
        if not bot:
            continue
        path = Path(bot["path"])
        path = path if path.is_absolute() else ROOT / path
        try:
            bot["path"] = _rel(path)                 # stored relative; the importer resolves it
        except ValueError:                           # outside the arena folder: personal, not moved
            dropped.append(p["name"])
            p["bot"] = None
    for m in db["matches"].values():
        if m["status"] == "running":
            m["status"] = "scheduled"
    files = []
    for d in KEEP_DATA_DIRS:
        files += [f for f in (config.DATA / d).rglob("*") if f.is_file()]
    if (config.DATA / "settings.json").exists():
        files.append(config.DATA / "settings.json")
    files += [f for f in config.SUBMISSIONS.glob("p*/**/*") if f.is_file()]                  # uploaded bots
    files += [f for f in (config.ENGINE / "chars").rglob("*")
              if f.is_file() and f.relative_to(config.ENGINE / "chars").parts[0] != "kfm"]
    total = sum(f.stat().st_size for f in files)
    print(f"export {len(files)} files ({total / 2**30:.2f} GB) -> {bundle}")
    with zipfile.ZipFile(bundle, "w", allowZip64=True) as z:
        z.writestr("data/arena.json", json.dumps(db, ensure_ascii=False, indent=1))
        z.writestr("BUNDLE.json", json.dumps({"made": time.strftime("%Y-%m-%d %H:%M"), "files": len(files) + 1}))
        for i, f in enumerate(files, 1):
            kind = zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
            z.write(f, _rel(f), compress_type=kind)
            if i % 500 == 0:
                print(f"  {i}/{len(files)}", flush=True)
    print(f"done: {Path(bundle).stat().st_size / 2**30:.2f} GB")
    if dropped:
        print(f"bots not moved (outside this folder, they stay on this PC): {', '.join(dropped)} "
              "- they fight with the engine AI on the new server")


def import_(bundle):
    if DB.exists():
        backup = DB.with_name(f"arena_before_import_{time.strftime('%Y%m%d_%H%M%S')}.json")
        shutil.copy2(DB, backup)
        print(f"this PC already had an arena; its DB was backed up to {backup.name}")
    root = ROOT.resolve()
    with zipfile.ZipFile(bundle) as z:
        if "BUNDLE.json" not in z.namelist():
            raise SystemExit("not an arena bundle (no BUNDLE.json)")
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            ok_top = name.parts and name.parts[0] in ("data", "submissions", "engine")
            dest = (root / Path(*name.parts)).resolve() if name.parts else root
            if not ok_top or root not in dest.parents:
                if info.filename != "BUNDLE.json":
                    print(f"skipped unexpected entry: {info.filename}")
                continue
            if info.is_dir():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    print("imported. start the server with:  python arena.py")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "import"):
        raise SystemExit(__doc__)
    (export if sys.argv[1] == "export" else import_)(sys.argv[2])
