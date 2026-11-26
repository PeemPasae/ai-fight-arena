"""Accepting a submission: unpack the archive safely, find and check the character's
.def, copy the character into the shared engine. Bots are stored but never run until
an admin approves them (they are code; characters are only data)."""
import hashlib
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import config, engine, fairness

CHAR_KEYS_REQUIRED = ("sprite", "anim")


class Rejected(Exception):
    pass


# ------------------------------------------------------------------ archives
def _check_member(name, dest):
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or re.match(r"^[a-zA-Z]:", name):
        raise Rejected(f"ไฟล์ในแพ็กมี path อันตราย: {name}")
    if p.suffix.lower() in config.BLOCKED_EXT:
        raise Rejected(f"มีไฟล์โปรแกรมที่ไม่อนุญาต: {p.name}")
    return dest / Path(*p.parts)


def unpack(archive, dest):
    """Extract .zip or .rar into dest (must be new/empty). Raises Rejected."""
    archive, dest = Path(archive), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    ext = archive.suffix.lower()
    if ext == ".zip":
        try:
            zf = zipfile.ZipFile(archive)
        except zipfile.BadZipFile:
            raise Rejected("ไฟล์ zip เสีย")
        with zf:
            infos = zf.infolist()
            if len(infos) > config.MAX_FILES:
                raise Rejected(f"ไฟล์ข้างในเยอะเกิน ({len(infos)})")
            if sum(i.file_size for i in infos) > config.MAX_UNPACKED_MB * 2**20:
                raise Rejected(f"แตกแล้วใหญ่เกิน {config.MAX_UNPACKED_MB} MB")
            for info in infos:
                name = info.filename
                if info.flag_bits & 0x800 == 0 and not name.isascii():
                    try:                                # zips made on Japanese Windows (common for MUGEN)
                        name = name.encode("cp437").decode("cp932")
                    except UnicodeError:
                        pass
                target = _check_member(name, dest)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    elif ext == ".rar":
        if not config.UNRAR.exists():
            raise Rejected("เครื่องเซิร์ฟเวอร์ไม่มี UnRAR ส่งเป็น .zip แทน")
        listing = subprocess.run([str(config.UNRAR), "lb", str(archive)], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
        if listing.returncode != 0:
            raise Rejected("ไฟล์ rar เสียหรือมีรหัสผ่าน")
        names = [n for n in listing.stdout.splitlines() if n.strip()]
        if len(names) > config.MAX_FILES:
            raise Rejected(f"ไฟล์ข้างในเยอะเกิน ({len(names)})")
        for n in names:
            _check_member(n, dest)
        r = subprocess.run([str(config.UNRAR), "x", "-o+", "-inul", "-p-", str(archive), str(dest) + "\\"],
                           capture_output=True)
        if r.returncode != 0:
            raise Rejected("แตกไฟล์ rar ไม่สำเร็จ")
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
        if size > config.MAX_UNPACKED_MB * 2**20:
            raise Rejected(f"แตกแล้วใหญ่เกิน {config.MAX_UNPACKED_MB} MB")
    else:
        raise Rejected("รองรับเฉพาะ .zip หรือ .rar")
    for f in dest.rglob("*"):                       # belt and braces after extraction
        if f.is_file() and f.suffix.lower() in config.BLOCKED_EXT:
            raise Rejected(f"มีไฟล์โปรแกรมที่ไม่อนุญาต: {f.name}")


# ------------------------------------------------------------------ character check
def read_text(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp874", "cp932", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_def(path):
    sections, cur = {}, None
    for line in read_text(path).splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^\[(.+?)\]", line)
        if m:
            cur = m.group(1).strip().lower()
            sections.setdefault(cur, {})
            continue
        if cur and "=" in line:
            k, v = line.split("=", 1)
            sections[cur][k.strip().lower()] = v.strip().strip('"')
    return sections


def _exists_ci(base, rel):
    """Case-insensitive file lookup (MUGEN chars often reference Foo.SFF as foo.sff)."""
    p = base
    for part in Path(rel.replace("\\", "/")).parts:
        if part in (".", ""):
            continue
        if part == "..":
            p = p.parent
            continue
        if not p.is_dir():
            return False
        match = [c for c in p.iterdir() if c.name.lower() == part.lower()]
        if not match:
            return False
        p = match[0]
    return p.is_file()


def find_character(root):
    """Returns (def_path, info) for the best character .def under root. Raises Rejected."""
    cands = []
    for d in Path(root).rglob("*.def"):
        try:
            s = parse_def(d)
        except OSError:
            continue
        files = s.get("files", {})
        if not all(files.get(k) for k in CHAR_KEYS_REQUIRED) or "info" not in s:
            continue
        cands.append((len(d.relative_to(root).parts), d, s))
    if not cands:
        raise Rejected("ไม่พบไฟล์ .def ของตัวละคร (ต้องมี [Info] และ [Files] ที่มี sprite/anim)")
    cands.sort(key=lambda c: (c[0], str(c[1])))
    _, d, s = cands[0]
    files = s["files"]
    missing = []
    for k, v in files.items():
        if not v or k.startswith("pal") or k in ("movelist",):
            continue
        if k in ("sprite", "anim", "cmd", "cns", "sound", "stcommon") or re.fullmatch(r"st\d*", k):
            if not _exists_ci(d.parent, v) and not (k == "stcommon" and v.lower().startswith("common")):
                missing.append(f"{k} = {v}")
    if missing:
        raise Rejected("ไฟล์ที่ .def อ้างถึงหายไป: " + ", ".join(missing[:5]))
    info = s.get("info", {})
    return d, {"char_name": info.get("displayname") or info.get("name") or d.stem,
               "author_credit": info.get("author", ""), "mugenversion": info.get("mugenversion", "")}


def find_bot(root):
    root = Path(root)
    for c in [root / "bot.py"] + sorted(root.glob("*/bot.py")):
        if c.is_file():
            return c
    raise Rejected("ไม่พบ bot.py ในไฟล์บอท (ต้องอยู่ชั้นนอกสุดหรือในโฟลเดอร์เดียว)")


# ------------------------------------------------------------------ roster characters
def sync_select(db):
    engine.write_select_def([c["def_rel"] for c in db["chars"].values()])


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def free_gb():
    return shutil.disk_usage(config.ROOT).free / 2**30


def check_disk(extra_mb=0):
    if free_gb() - extra_mb / 1024 < config.MIN_FREE_GB:
        raise Rejected("พื้นที่เก็บไฟล์ของเซิร์ฟเวอร์ใกล้เต็ม ตอนนี้รับอัปโหลดเพิ่มไม่ได้ (แจ้งแอดมิน)")


def upload_char(store, archive, uploaded_by=""):
    """Roster character from an uploaded .zip/.rar. An archive identical to one already
    uploaded reuses that character instead of storing another copy.
    Returns (char dict, is_new). Raises Rejected."""
    digest = file_sha256(archive)
    with store.lock:
        for ch in store.db["chars"].values():
            if ch.get("sha256") == digest:
                Path(archive).unlink(missing_ok=True)
                return dict(ch), False
    size_mb = Path(archive).stat().st_size / 2**20
    check_disk(extra_mb=size_mb * 4)                 # archive + unpacked + game copy, roughly
    with store.tx() as db:
        cid = store.new_id(db, "char")
    base = config.SUBMISSIONS / cid
    try:
        base.mkdir(parents=True, exist_ok=False)
        keep = base / ("upload" + Path(archive).suffix.lower())
        shutil.move(str(archive), keep)
        unpack(keep, base / "char")
        def_path, info = find_character(base / "char")
        engine.install_char(cid, def_path.parent)
    except Rejected:
        shutil.rmtree(base, ignore_errors=True)
        engine.remove_char(cid)
        raise
    finally:
        # the game copy in engine/chars is the one that is played; keep only the original
        # archive here (enough to reinstall) and drop the extracted duplicate
        shutil.rmtree(base / "char", ignore_errors=True)
    ch = _add_char(store, cid, def_path, info, "upload", uploaded_by)
    with store.tx() as db:
        db["chars"][cid]["sha256"] = digest
    return ch, True


def add_local_char(store, char_dir):
    """Roster character straight from a folder on this PC (house characters)."""
    def_path, info = find_character(Path(char_dir))
    with store.tx() as db:
        cid = store.new_id(db, "char")
    engine.install_char(cid, def_path.parent)
    return _add_char(store, cid, def_path, info, "local", "")


def _add_char(store, cid, def_path, info, source, uploaded_by):
    life_orig = fairness.normalize_life(config.ENGINE / "chars" / cid / def_path.name)
    ch = {"life_orig": life_orig, "id": cid, "char_name": info["char_name"], "credit": info["author_credit"], "def_rel": f"{cid}/{def_path.name}",
          "in_game_name": None, "status": "queued_test", "note": "", "source": source, "uploaded_by": uploaded_by,
          "reserved_for": None, "created": time.time()}
    with store.tx() as db:
        db["chars"][cid] = ch
        sync_select(db)
    return ch


def delete_char(store, cid):
    with store.tx() as db:
        if any(p["char"] == cid for p in db["players"].values()):
            raise Rejected("ยังมีผู้เล่นใช้ตัวนี้อยู่ ลบผู้เล่นก่อน")
        db["chars"].pop(cid, None)
        sync_select(db)
    engine.remove_char(cid)
    shutil.rmtree(config.SUBMISSIONS / cid, ignore_errors=True)


# ------------------------------------------------------------------ players
def _check_name(db, name):
    name = (name or "").strip()
    if not name:
        raise Rejected("ต้องใส่ชื่อของคุณ")
    if any(p["name"].casefold() == name.casefold() for p in db["players"].values()):
        raise Rejected(f"มีผู้เล่นชื่อ “{name}” แล้ว ใช้ชื่ออื่น")
    return name


def join(store, name, char_id=None, char_archive=None, bot_archive=None):
    """A person joins: pick a ready roster character, or upload their own (it joins the
    roster too). An optional bot is stored but only runs after an admin approves it."""
    with store.lock:
        name = _check_name(store.db, name)
        if not char_id and not char_archive:
            raise Rejected("เลือกตัวละครจากรายการ หรืออัปโหลดตัวของคุณเอง")
        if char_id and not char_archive:
            ch = store.db["chars"].get(char_id)
            if not ch:
                raise Rejected("ไม่พบตัวละครที่เลือก")
            if ch.get("reserved_for"):
                raise Rejected("ตัวละครนี้จองไว้แล้ว เลือกตัวอื่น")
            if ch["status"] == "failed":
                raise Rejected("ตัวละครนี้โหลดไม่ผ่าน เลือกตัวอื่น")
            if ch["status"] == "banned":
                raise Rejected("ตัวละครนี้ถูกแบน (ผิดกติกาสนาม) เลือกตัวอื่น")
    if char_archive:
        ch, is_new = upload_char(store, char_archive, uploaded_by=name)
        if not is_new:                               # someone already sent this exact file
            if ch.get("reserved_for"):
                raise Rejected("ตัวละครนี้มีในสนามแล้วและจองไว้ เลือกตัวอื่น")
            if ch["status"] in ("failed", "banned"):
                raise Rejected(f"ไฟล์นี้เคยส่งมาแล้วแต่ใช้ไม่ได้: {ch.get('note', '')}")
        char_id = ch["id"]
    with store.tx() as db:
        pid = store.new_id(db, "player")
    bot = None
    if bot_archive:
        base = config.SUBMISSIONS / pid
        try:
            base.mkdir(parents=True, exist_ok=True)
            keep = base / ("bot_upload" + Path(bot_archive).suffix.lower())
            shutil.move(str(bot_archive), keep)
            unpack(keep, base / "bot")
            bot = {"path": str(find_bot(base / "bot")), "approved": False}
        except Rejected:
            shutil.rmtree(base, ignore_errors=True)
            raise
    return _add_player(store, pid, name, char_id, bot)


def add_local_player(store, name, char_id, bot_path=None, reserve=False):
    """Players set up on this PC (e.g. ภีม + General + our bot): bot is pre-approved."""
    with store.tx() as db:
        name = _check_name(db, name)
        pid = store.new_id(db, "player")
    bot = {"path": str(Path(bot_path).resolve()), "approved": True} if bot_path else None
    p = _add_player(store, pid, name, char_id, bot)
    if reserve:
        with store.tx() as db:
            db["chars"][char_id]["reserved_for"] = pid
    return p


def _add_player(store, pid, name, char_id, bot):
    p = {"id": pid, "name": name, "char": char_id, "bot": bot, "active": True, "created": time.time()}
    with store.tx() as db:
        db["players"][pid] = p
    return p


def delete_player(store, pid):
    with store.tx() as db:
        db["players"].pop(pid, None)
        for c in db["chars"].values():
            if c.get("reserved_for") == pid:
                c["reserved_for"] = None
        for m in list(db["matches"].values()):
            if pid in (m["p1"], m["p2"]) and m["status"] == "scheduled":
                db["matches"].pop(m["id"])
    shutil.rmtree(config.SUBMISSIONS / pid, ignore_errors=True)
