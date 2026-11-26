"""AI Fight Arena - a shared Ikemen GO tournament server with a live web view.

  python arena.py                 start the server (http://<this PC>:8080)
  python arena.py setup           (re)build the shared engine from ikemen/
  python arena.py add-local --name "General Bot" --char ..\\lkemon\\chars\\general --bot ..\\bot\\general_bot.py
  python arena.py list            show entries
"""
import argparse
import socket
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):           # Thai messages on a cp1252 console
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
from arena import config, engine, fairness, submissions, win  # noqa: E402
from arena.store import Store  # noqa: E402


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith(("127.", "169.254.")))


def cmd_run(args):
    from aiohttp import web
    from arena.capture import Capture
    from arena.web import admin_token, make_app
    from arena.worker import Worker

    win.dpi_aware()
    engine.setup()
    killed = engine.cleanup_orphans()
    if killed:
        print(f"ปิดเกม/บอทที่ค้างจากรอบก่อน: {', '.join(killed)}")
    store = Store()
    with store.tx() as db:                      # recover from a crash mid-match
        for m in db["matches"].values():
            if m["status"] == "running":
                m["status"] = "scheduled"
        for c in db["chars"].values():
            if c["status"] == "testing":
                c["status"] = "queued_test"
        submissions.sync_select(db)
    fairness.apply_to_roster(store)             # equal life + re-test under the current rules
    worker = Worker(store)
    worker.start()
    capture = Capture(worker)
    capture.start()
    port = args.port or config.PORT
    print("=" * 60)
    print(" AI Fight Arena")
    print(f"   เครื่องนี้:     http://localhost:{port}")
    for ip in lan_ips():
        print(f"   เพื่อนในวงแลน: http://{ip}:{port}")
    print(f"   รหัสแอดมิน:   {admin_token()}   (อยู่ใน data/admin_token.txt)")
    print("   ระหว่างแมตช์ที่มีบอท ห้ามใช้เครื่องนี้ (บอทกดคีย์บอร์ดจริง)")
    print("=" * 60, flush=True)
    try:
        web.run_app(make_app(store, worker, capture), host=config.HOST, port=port, print=None)
    finally:
        worker.quit.set()
        worker.stop_match.set()


def cmd_setup(args):
    engine.setup(force=True)
    submissions.sync_select(Store().read())
    print(f"engine ready at {config.ENGINE}")


def cmd_add_char(args):
    engine.setup()
    c = submissions.add_local_char(Store(), args.folder)
    print(f"added character {c['id']}: {c['char_name']} - load-tested when the server runs")


def cmd_add_player(args):
    store = Store()
    cid = args.char
    if cid not in store.read()["chars"]:
        engine.setup()
        cid = submissions.add_local_char(store, cid)["id"]
    p = submissions.add_local_player(store, args.name, cid, args.bot, args.reserve)
    print(f"added player {p['id']}: {p['name']} with {cid} bot={'yes' if p['bot'] else 'engine AI'}"
          f"{' (character reserved)' if args.reserve else ''}")


def cmd_list(args):
    db = Store().read()
    print("characters:")
    for c in sorted(db["chars"].values(), key=lambda c: c["id"]):
        owner = db["players"].get(c.get("reserved_for") or "", {}).get("name")
        print(f"  {c['id']}  {c['status']:<11} {c['char_name']:<24} {'reserved: ' + owner if owner else ''} {c.get('note','')}")
    print("players:")
    for p in sorted(db["players"].values(), key=lambda p: p["id"]):
        bot = "-" if not p.get("bot") else ("bot" if p["bot"]["approved"] else "bot(pending)")
        print(f"  {p['id']}  {p['name']:<16} {db['chars'].get(p['char'],{}).get('char_name','?'):<24} {bot}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--port", type=int)
    sub.add_parser("setup")
    c = sub.add_parser("add-char")
    c.add_argument("folder", help="character folder (has the .def)")
    a = sub.add_parser("add-player")
    a.add_argument("--name", required=True)
    a.add_argument("--char", required=True, help="roster id (c001) or a character folder")
    a.add_argument("--bot", help="bot script: python <bot> --player N --game-dir <engine>")
    a.add_argument("--reserve", action="store_true", help="nobody else may pick this character")
    sub.add_parser("list")
    args = ap.parse_args()
    {"run": cmd_run, None: cmd_run, "setup": cmd_setup, "add-char": cmd_add_char,
     "add-player": cmd_add_player, "list": cmd_list}[args.cmd](
        args if args.cmd else argparse.Namespace(port=None))


if __name__ == "__main__":
    main()
