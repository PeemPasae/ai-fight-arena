"""Web server: pages, public API, live telemetry (SSE), live video (MJPEG), joining
(pick a roster character or upload one), and the token-protected admin API where
the admin sets up who fights whom."""
import asyncio
import json
import secrets
import time
import uuid
from pathlib import Path

from aiohttp import web

from . import config, exports, league, stateindex, submissions

TOKEN_FILE = config.DATA / "admin_token.txt"


def admin_token():
    if not TOKEN_FILE.exists():
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(secrets.token_urlsafe(18), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def public_char(c, db):
    owner = db["players"].get(c.get("reserved_for") or "", {}).get("name")
    users = [p["name"] for p in db["players"].values() if p["char"] == c["id"]]
    return {"id": c["id"], "char_name": c["char_name"], "credit": c.get("credit", ""), "status": c["status"],
            "note": c.get("note", ""), "source": c.get("source"), "uploaded_by": c.get("uploaded_by", ""),
            "reserved_by": owner, "used_by": users, "in_game_name": c.get("in_game_name")}


def public_player(p, db):
    ch = db["chars"].get(p["char"], {})
    bot = p.get("bot")
    return {"id": p["id"], "name": p["name"], "char": p["char"], "char_name": ch.get("char_name", "?"),
            "char_status": ch.get("status"), "active": p["active"], "created": p.get("created"),
            "bot": None if not bot else ("approved" if bot.get("approved") else "pending")}


def public_match(m):
    r = m.get("result") or {}
    return {"id": m["id"], "p1": m["p1"], "p2": m["p2"], "status": m["status"], "note": m.get("note", ""),
            "wins": r.get("wins"), "winner": r.get("winner"), "rounds": r.get("rounds"),
            "duration": r.get("duration"), "ended": r.get("ended"), "started": m.get("started")}


REJECT_LOG = config.DATA / "rejections.jsonl"


def log_rejection(ip, fields, err):
    """Remember why a sign-up was refused, so the admin can see it and help."""
    entry = {"t": time.time(), "ip": ip, "name": fields.get("name"), "mode": fields.get("mode"),
             "file": fields.get("char_file_name"), "bot": fields.get("bot_name"), "error": str(err)}
    with open(REJECT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recent_rejections(n=20):
    if not REJECT_LOG.exists():
        return []
    lines = REJECT_LOG.read_text(encoding="utf-8").splitlines()[-n:]
    return [json.loads(x) for x in reversed(lines) if x.strip()]


def make_app(store, worker, capture):
    token = admin_token()
    last_submit = {}
    app = web.Application(client_max_size=(config.MAX_UPLOAD_MB * 2 + 5) * 2**20)

    async def index(_):
        return web.FileResponse(config.WEB / "index.html", headers={"Cache-Control": "no-cache"})

    async def state(_):
        db = store.read()
        live = worker.live_snapshot()
        return web.json_response({
            "chars": [{**public_char(c, db), "logs": len(exports.matches_of(db, c["id"]))}
                      for c in sorted(db["chars"].values(), key=lambda c: c["id"])],
            "logs_total": len(exports.matches_of(db)),
            "players": [public_player(p, db) for p in sorted(db["players"].values(), key=lambda p: p["id"])],
            "matches": [public_match(m) for m in sorted(db["matches"].values(), key=lambda m: m["id"])],
            "standings": league.standings(db),
            "now": {"match": live.get("match"), "title": live.get("title"), "phase": live.get("phase")},
            "rules": {"rounds": config.ROUNDS, "ai_level": config.AI_LEVEL, "stage": config.STAGE,
                      "max_upload_mb": config.MAX_UPLOAD_MB, "life": config.LIFE, "proj_limit": config.PROJ_LIMIT,
                      "ohko_burst": config.OHKO_BURST, "immortal_min": config.IMMORTAL_MIN_TAKEN,
                      "fair_seconds": config.FAIR_SECONDS},
        })

    def live_payload():
        lv = worker.live_snapshot()
        f = lv.get("frame") or {}
        players = []
        for k, slot in (("p1", 0), ("p2", 1)):
            p = f.get(k) or {}
            hp_max = max((lv.get("hp_max") or [1, 1])[slot], p.get("hp") or 0, 1)
            players.append({"name": p.get("name"), "hp": p.get("hp"), "hp_max": hp_max,
                            "power": p.get("power"), "state": p.get("state_no"), "move": p.get("move_type")})
        rounds = lv.get("rounds") or []
        return {"phase": lv.get("phase"), "match": lv.get("match"), "title": lv.get("title"),
                "names": lv.get("names"), "entries": lv.get("entries"), "elapsed": lv.get("elapsed"),
                "round_no": f.get("round_no"), "round_state": f.get("round_state"), "players": players,
                "wins": [sum(1 for r in rounds if r["winner"] == s) for s in (1, 2)], "test": lv.get("test")}

    async def live_sse(request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})
        await resp.prepare(request)
        last = None
        try:
            while True:
                msg = json.dumps(live_payload(), ensure_ascii=False)
                if msg != last:
                    await resp.write(f"data: {msg}\n\n".encode("utf-8"))
                    last = msg
                await asyncio.sleep(1 / 15)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    async def mjpeg(request):
        resp = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame",
                                           "Cache-Control": "no-cache"})
        await resp.prepare(request)
        loop = asyncio.get_running_loop()
        seq = -1
        capture.viewers += 1
        try:
            while True:
                seq, jpg = await loop.run_in_executor(None, capture.wait_frame, seq)
                await resp.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            capture.viewers -= 1
        return resp

    async def match_detail(request):
        mid = request.match_info["mid"]
        db = store.read()
        m = db["matches"].get(mid)
        if not m:
            raise web.HTTPNotFound()
        tl = config.DATA / "matches" / f"{mid}.json"
        timeline = json.loads(tl.read_text(encoding="utf-8"))["timeline"] if tl.exists() else []
        return web.json_response({**public_match(m), "timeline": timeline})

    async def save_part(part):
        name = part.filename or ""
        ext = Path(name).suffix.lower()
        if ext not in (".zip", ".rar"):
            raise submissions.Rejected(f"ไฟล์ {name or '?'}: รองรับเฉพาะ .zip หรือ .rar")
        submissions.check_disk()
        tmp = config.DATA / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        path = tmp / f"{uuid.uuid4().hex}{ext}"
        size, limit = 0, config.MAX_UPLOAD_MB * 2**20
        with open(path, "wb") as f:
            while chunk := await part.read_chunk(1 << 20):
                size += len(chunk)
                if size > limit:
                    f.close()
                    path.unlink(missing_ok=True)
                    raise submissions.Rejected(f"ไฟล์ใหญ่เกิน {config.MAX_UPLOAD_MB} MB")
                f.write(chunk)
        return path

    async def join(request):
        ip = request.remote or "?"
        if time.time() - last_submit.get(ip, 0) < 15:
            return web.json_response({"ok": False, "error": "ส่งถี่เกินไป รอ 15 วินาทีแล้วลองใหม่"}, status=429)
        fields, files = {}, {}
        try:
            reader = await request.multipart()
            while part := await reader.next():
                if part.name in ("char_file", "bot") and part.filename:
                    fields[part.name + "_name"] = part.filename[:80]
                    files[part.name] = await save_part(part)
                elif part.name in ("name", "char_id", "mode"):
                    fields[part.name] = (await part.text()).strip()[:40]
            upload = fields.get("mode") == "upload"
            if upload and "char_file" not in files:
                raise submissions.Rejected("แนบไฟล์ตัวละคร (.zip/.rar) ด้วย")
            last_submit[ip] = time.time()
            loop = asyncio.get_running_loop()
            player = await loop.run_in_executor(None, lambda: submissions.join(
                store, fields.get("name"), None if upload else fields.get("char_id"),
                files.get("char_file") if upload else None, files.get("bot")))
            return web.json_response({"ok": True, "player": public_player(player, store.read())})
        except submissions.Rejected as e:
            log_rejection(ip, fields, e)
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        finally:
            for p in files.values():
                Path(p).unlink(missing_ok=True)

    async def admin(request):
        if not secrets.compare_digest(request.headers.get("X-Admin-Token", ""), token):
            return web.json_response({"ok": False, "error": "รหัสแอดมินไม่ถูกต้อง"}, status=403)
        action = request.match_info["action"]
        body = await request.json() if request.can_read_body else {}
        oid = body.get("id")
        loop = asyncio.get_running_loop()
        msg = "ok"
        try:
            if action == "check":
                pass
            elif action == "rejections":
                return web.json_response({"ok": True, "msg": "ok", "items": recent_rejections()})
            elif action == "create_match":
                ids = league.create_match(store, body.get("p1"), body.get("p2"), body.get("count", 1),
                                          bool(body.get("swap")))
                msg = f"เข้าคิวแล้ว {len(ids)} แมตช์ ({', '.join(ids)})"
            elif action == "cancel_match":
                with store.tx() as db:
                    m = db["matches"].get(oid)
                    if m and m["status"] == "scheduled":
                        m.update(status="cancelled", note="ยกเลิกโดยแอดมิน")
            elif action == "rematch":
                with store.tx() as db:
                    m = db["matches"].get(oid)
                if not m:
                    raise web.HTTPNotFound()
                msg = f"เข้าคิวแล้ว {league.create_match(store, m['p1'], m['p2'])[0]}"
            elif action == "stop_match":
                worker.stop_match.set()
            elif action == "approve_bot":
                with store.tx() as db:
                    p = db["players"].get(oid)
                    if p and p.get("bot"):
                        p["bot"]["approved"] = bool(body.get("approved", True))
            elif action == "toggle_active":
                with store.tx() as db:
                    p = db["players"].get(oid)
                    if p:
                        p["active"] = not p["active"]
            elif action == "retest_char":
                with store.tx() as db:
                    c = db["chars"].get(oid)
                    if c:
                        c.update(status="queued_test", note="")
            elif action == "ban_char":                 # manual ban, e.g. an edited "god mode" upload
                with store.tx() as db:
                    c = db["chars"].get(oid)
                    if c and not c.get("reserved_for"):
                        c.update(status="banned", note=body.get("note") or "แบนโดยแอดมิน: ผิดกติกาสนาม")
                        uses = lambda pid: db["players"].get(pid, {}).get("char") == oid
                        for m in db["matches"].values():
                            if m["status"] == "scheduled" and (uses(m["p1"]) or uses(m["p2"])):
                                m.update(status="cancelled", note="ยกเลิก: ตัวละครถูกแบน")
                        if any(uses(pid) for pid in (worker.live_snapshot().get("entries") or [])):
                            worker.stop_match.set()        # its match is on screen right now
            elif action == "delete_player":
                await loop.run_in_executor(None, submissions.delete_player, store, oid)
            elif action == "delete_char":
                await loop.run_in_executor(None, submissions.delete_char, store, oid)
            elif action == "reset_results":
                with store.tx() as db:
                    db["matches"] = {}
                msg = "ล้างผลแมตช์ทั้งหมดแล้ว"
            else:
                raise web.HTTPNotFound()
        except (league.BadMatch, submissions.Rejected) as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        return web.json_response({"ok": True, "msg": msg})

    async def export_states(request):
        cid, fmt = request.match_info["cid"], request.match_info["fmt"]
        db = store.read()
        if cid not in db["chars"] or fmt not in ("md", "csv", "json"):
            raise web.HTTPNotFound()
        path = exports.char_def(cid, db)
        name = exports._safe(db["chars"][cid]["char_name"])
        fn = {"md": lambda: stateindex.as_markdown(path, db["chars"][cid]["char_name"]),
              "csv": lambda: stateindex.as_csv(path), "json": lambda: stateindex.as_json(path)}[fmt]
        body = await asyncio.get_running_loop().run_in_executor(None, fn)
        ctype = {"md": "text/markdown", "csv": "text/csv", "json": "application/json"}[fmt]
        return web.Response(text=body, content_type=ctype, charset="utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{name}_states.{fmt}"'})

    async def export_zip(request):
        what = request.match_info["what"]
        db = store.read()
        loop = asyncio.get_running_loop()
        if what == "all":
            data = await loop.run_in_executor(None, exports.all_zip, db)
            fname = f"arena_training_data_{exports.stamp()}.zip"
        elif what in db["chars"]:
            data = await loop.run_in_executor(None, exports.char_zip, db, what)
            fname = f"{exports._safe(db['chars'][what]['char_name'])}_training_data.zip"
        else:
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type="application/zip",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    app.router.add_get("/api/export/{cid}/states.{fmt}", export_states)
    app.router.add_get("/api/export/{what}.zip", export_zip)
    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/live", live_sse)
    app.router.add_get("/api/match/{mid}", match_detail)
    app.router.add_get("/stream.mjpg", mjpeg)
    app.router.add_post("/api/join", join)
    app.router.add_post("/api/admin/{action}", admin)
    app.router.add_static("/static/", config.WEB)
    return app
