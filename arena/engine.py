"""The shared Ikemen GO engine: setup (copied once from the course install), character
install, and running one match while streaming telemetry to the live view."""
import gzip
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config, win

COPY_DIRS = ("data", "font", "sound", "stages", "lib", "video")
BUILTIN_CHARS = ("kfm",)          # kept for the motif and the load test opponent


# ------------------------------------------------------------------ setup
def setup(force=False):
    eng, src = config.ENGINE, config.ENGINE_SRC
    if (eng / "Ikemen_GO.exe").exists() and not force:
        write_select_def([])
        return eng
    if not (src / "Ikemen_GO.exe").exists():
        raise SystemExit(f"Ikemen GO not found at {src} (set ENGINE_SRC in arena/config.py)")
    eng.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "Ikemen_GO.exe", eng / "Ikemen_GO.exe")
    for name in ("LICENSES.txt", "README.md"):
        if (src / name).exists():
            shutil.copy2(src / name, eng / name)
    for d in COPY_DIRS:
        if (src / d).exists():
            shutil.copytree(src / d, eng / d, dirs_exist_ok=True)
    for c in BUILTIN_CHARS:
        if (src / "chars" / c).exists():
            shutil.copytree(src / "chars" / c, eng / "chars" / c, dirs_exist_ok=True)
    # engine scripts, shaders, icons, controller db - but only the arena's telemetry mod
    shutil.copytree(src / "external", eng / "external", dirs_exist_ok=True,
                    ignore=lambda d, names: names if Path(d).name == "mods" and Path(d).parent.name == "external" else [])
    mods = eng / "external" / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    src_mod = src / "external" / "mods" / config.TELEMETRY_MOD
    if src_mod.exists():                       # else: the copy kept in git (engine/external/mods/)
        shutil.copy2(src_mod, mods / config.TELEMETRY_MOD)
    elif not (mods / config.TELEMETRY_MOD).exists():
        raise SystemExit(f"{config.TELEMETRY_MOD} not found in {src_mod.parent} or {mods}")
    (eng / "save").mkdir(exist_ok=True)
    shutil.copy2(src / "save" / "config.ini", eng / "save" / "config.ini")
    write_select_def([])
    return eng


def write_select_def(char_defs):
    """[Characters] = builtin chars + every arena entry; other sections kept from the source."""
    src = (config.ENGINE_SRC / "data" / "select.def").read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"(?im)^(\[\w[^\]]*\])", src)
    out, i = [parts[0]], 1
    while i < len(parts):
        head, body = parts[i], parts[i + 1]
        if head.strip().lower() == "[characters]":
            lines = [f"{c}, {config.STAGE}" for c in BUILTIN_CHARS]
            lines += [f"{d}, {config.STAGE}" for d in char_defs]
            body = "\n" + "\n".join(lines) + "\n\n"
        out += [head, body]
        i += 2
    (config.ENGINE / "data" / "select.def").write_text("".join(out), encoding="utf-8")


TEXT_EXT = {".def", ".cns", ".st", ".cmd", ".air", ".zss"}
FULLWIDTH_SPACE = "\u3000"


def sanitize_char(folder):
    """Old WinMUGEN characters often contain Japanese full-width spaces (U+3000) in
    their code files. MUGEN ignores them; Ikemen GO stops with "Invalid data" and the
    game closes. Replace them with normal spaces (UTF-8 or Shift-JIS files).
    Returns the names of the files that were changed."""
    fixed = []
    for f in Path(folder).rglob("*"):
        if not f.is_file() or f.suffix.lower() not in TEXT_EXT:
            continue
        raw = f.read_bytes()
        new = None
        if b"\xe3\x80\x80" in raw:
            try:
                new = raw.decode("utf-8").replace(FULLWIDTH_SPACE, " ").encode("utf-8")
            except UnicodeDecodeError:
                new = None
        if new is None and b"\x81\x40" in raw:
            try:
                text = raw.decode("cp932")
                if FULLWIDTH_SPACE in text:
                    new = text.replace(FULLWIDTH_SPACE, " ").encode("cp932")
            except (UnicodeDecodeError, UnicodeEncodeError):
                new = None
        if new is not None and new != raw:
            f.write_bytes(new)
            fixed.append(f.name)
    return fixed


def install_char(entry_id, char_dir):
    dest = config.ENGINE / "chars" / entry_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(char_dir, dest)
    sanitize_char(dest)
    return dest


def remove_char(entry_id):
    dest = config.ENGINE / "chars" / entry_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def cleanup_orphans():
    """Kill Ikemen / bot processes left by a previous arena run (only ones tied to
    this arena's engine folder - a player's own Ikemen elsewhere is untouched)."""
    eng = str(config.ENGINE).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process | Where-Object { "
          f"($_.Name -eq 'Ikemen_GO.exe' -and $_.ExecutablePath -like '{eng}*') -or "
          f"($_.Name -like 'python*' -and $_.CommandLine -like '*--game-dir*{eng}*') }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
        return [x for x in r.stdout.split() if x.isdigit()]
    except (OSError, subprocess.TimeoutExpired):
        return []


# ------------------------------------------------------------------ one match
class Side:
    """One player slot: an arena entry, played by its approved bot or by the engine AI."""

    def __init__(self, slot, entry):
        self.slot = slot
        self.entry = entry
        bot = entry.get("bot") or {}
        self.bot_path = bot.get("path") if bot.get("approved") else None
        self.proc = None
        self.log = None

    @property
    def char(self):
        return entry_char(self.entry)

    def start_bot(self, log_dir, tag):
        if not self.bot_path:
            return
        bot = Path(self.bot_path)
        if not bot.is_absolute():                  # moved arenas store bots relative to the arena folder
            bot = config.ROOT / bot
        self.log = open(log_dir / f"{tag}_p{self.slot}_bot.log", "w", encoding="utf-8")
        cmd = [sys.executable, str(bot), "--player", str(self.slot), "--game-dir", str(config.ENGINE)]
        self.proc = subprocess.Popen(cmd, cwd=bot.parent, stdout=self.log, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.log:
            self.log.close()


def entry_char(entry):
    return entry["def_rel"] if "def_rel" in entry else entry["char"]


def read_telemetry():
    try:
        d = json.loads((config.ENGINE / config.TELEMETRY_FILE).read_text(encoding="utf-8"))
        return d if "p1" in d and "p2" in d else None
    except (OSError, ValueError):
        return None


def run_match(p1, p2, live, stop, tag, rounds=None, max_seconds=None):
    """Play p1 vs p2 (entry dicts). `live` is a dict the web server streams; `stop` a
    threading.Event. Returns a result dict; result["status"] is done/invalid/error."""
    rounds = rounds or config.ROUNDS
    max_seconds = max_seconds or config.MATCH_TIMEOUT
    sides = [Side(1, p1), Side(2, p2)]
    eng = config.ENGINE
    tel = eng / config.TELEMETRY_FILE
    try:
        tel.unlink()
    except OSError:
        pass
    cmd = [str(eng / "Ikemen_GO.exe"), "-p1", sides[0].char, "-p2", sides[1].char,
           "-s", config.STAGE, "-rounds", str(rounds), "-loadmotif"]
    for s in sides:
        if not s.bot_path:
            cmd += [f"-p{s.slot}.ai", str(config.AI_LEVEL)]
    logs = config.DATA / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    game_log = open(logs / f"{tag}_ikemen.log", "w", encoding="utf-8")
    game = subprocess.Popen(cmd, cwd=eng, stdout=game_log, stderr=subprocess.STDOUT)
    traces = config.DATA / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    trace = gzip.open(traces / f"{tag}.jsonl.gz", "wt", encoding="utf-8")   # every frame, for bot training
    live.update(pid=game.pid, phase="loading", rounds=[], hp_max=[1, 1], frame=None)
    bots = any(s.bot_path for s in sides)
    result = {"status": "error", "note": "", "rounds": [], "timeline": []}
    start = time.time()
    hwnd, last_tick, last_rs, unfocused, got_tel = None, None, None, 0.0, False
    hp_max = [1, 1]
    try:
        time.sleep(1.5)
        if bots:
            for _ in range(20):
                hwnd = hwnd or win.window_of(game.pid)
                if hwnd and win.focus(hwnd):
                    break
                time.sleep(0.25)
            for s in sides:
                s.start_bot(logs, tag)
        last_frame_t = time.time()
        while True:
            if stop.is_set():
                result.update(status="invalid", note="หยุดโดยแอดมิน")
                break
            if game.poll() is not None:
                break
            now = time.time()
            if now - start > max_seconds:
                result.update(status="invalid", note=f"เกินเวลา {max_seconds} วินาที")
                break
            if not got_tel and now - start > config.LOAD_TIMEOUT:
                result.update(status="error", note="เกมไม่ส่ง telemetry (ตัวละครอาจโหลดไม่ผ่าน)")
                break
            hwnd = hwnd or win.window_of(game.pid)
            d = read_telemetry()
            if not d or d["tick"] == last_tick:
                if got_tel and now - last_frame_t > 15:
                    result.update(status="error", note="เกมค้าง (telemetry หยุด 15 วิ)")
                    break
                time.sleep(0.004)
                continue
            got_tel, last_frame_t, last_tick = True, now, d["tick"]
            trace.write(json.dumps(d, separators=(",", ":")) + "\n")
            rs = d.get("round_state")
            a, b = d["p1"], d["p2"]
            hp_max = [max(hp_max[0], a["hp"] or 0), max(hp_max[1], b["hp"] or 0)]
            if bots and rs == 2:
                if win.has_focus(hwnd):
                    unfocused = 0.0
                else:
                    unfocused += 1 / 60
                    win.focus(hwnd)
                    if unfocused > config.FOCUS_GRACE:
                        result.update(status="invalid", note="หน้าต่างเกมหลุดโฟกัส (มีคนใช้เครื่อง?) บอทกดปุ่มไม่ได้")
                        break
            if last_rs == 2 and rs is not None and rs >= 3:
                w = 1 if a["hp"] > b["hp"] else 2 if b["hp"] > a["hp"] else 0
                result["rounds"].append({"round": d.get("round_no"), "hp": [a["hp"], b["hp"]],
                                         "hp_max": list(hp_max), "winner": w})
            last_rs = rs
            if d["tick"] % 4 == 0 and rs == 2:
                result["timeline"].append([round(now - start, 2), d.get("round_no"), a["hp"], b["hp"]])
            live.update(phase="fight" if rs == 2 else "between", frame=d, hp_max=list(hp_max),
                        rounds=list(result["rounds"]), elapsed=round(now - start, 1))
            wins = [sum(1 for r in result["rounds"] if r["winner"] == k) for k in (1, 2)]
            if max(wins) >= rounds:
                # let the KO / win pose play a moment for viewers, then close
                t_end = time.time() + 3
                while time.time() < t_end and game.poll() is None and not stop.is_set():
                    d = read_telemetry()
                    if d:
                        live.update(frame=d, phase="between")
                    time.sleep(0.05)
                break
        wins = [sum(1 for r in result["rounds"] if r["winner"] == k) for k in (1, 2)]
        if result["status"] == "error" and not result["note"]:
            if max(wins) >= rounds:
                result["status"] = "done"
            elif result["rounds"]:
                result.update(status="invalid", note="เกมปิดก่อนแข่งจบ")
            else:
                result["note"] = "เกมปิดก่อนเริ่มยก (ตัวละครอาจ crash)"
        result["wins"] = wins
        result["winner_slot"] = 1 if wins[0] > wins[1] else 2 if wins[1] > wins[0] else 0
        result["hp_diff"] = sum((r["hp"][0] - r["hp"][1]) for r in result["rounds"])
        result["duration"] = round(time.time() - start, 1)
        result["names"] = _names(live)
        return result
    finally:
        for s in sides:
            s.stop()
        if game.poll() is None:
            game.terminate()
            try:
                game.wait(5)
            except subprocess.TimeoutExpired:
                game.kill()
        game_log.close()
        trace.close()
        live.update(pid=None, phase="idle")


def _names(live):
    f = live.get("frame") or {}
    return [(f.get("p1") or {}).get("name"), (f.get("p2") or {}).get("name")]


def _panic_reason(log_path):
    """The engine's own error line (e.g. "Invalid data: ...") from an Ikemen log."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for i, line in enumerate(lines):
        if line.startswith("Panic:"):
            detail = " ".join(x.strip() for x in lines[i:i + 2])
            return detail.replace("Panic: external/script/main.lua:1162: ", "")[:200]
    return ""


def _probe(entry, live, stop, tag, p1_ai, p2_ai):
    """One probe fight: the tested character (P1) vs kfm (P2) for FAIR_SECONDS of real
    fighting or until the round ends. ai=None leaves that side with no input at all,
    so it stands still and never blocks. Returns a dict of what happened."""
    eng = config.ENGINE
    try:
        (eng / config.TELEMETRY_FILE).unlink()
    except OSError:
        pass
    cmd = [str(eng / "Ikemen_GO.exe"), "-p1", entry_char(entry), "-p2", "kfm",
           "-s", config.STAGE, "-rounds", "1", "-loadmotif"]
    for slot, ai in ((1, p1_ai), (2, p2_ai)):
        if ai:
            cmd += [f"-p{slot}.ai", str(ai)]
    logs = config.DATA / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{tag}_ikemen.log"
    deadline = config.LOAD_TIMEOUT + config.FAIR_SECONDS + 25          # ~70 s
    probe_ticks = config.FAIR_SECONDS * 60
    r = {"max_proj": 0, "fight_ticks": 0, "ended": False, "crashed": False, "seen": False, "name": None,
         "hp": [[], []], "log": log_path}            # hp: (game tick, life) while fighting
    with open(log_path, "w", encoding="utf-8") as game_log:
        game = subprocess.Popen(cmd, cwd=eng, stdout=game_log, stderr=subprocess.STDOUT)
        live.update(pid=game.pid, phase="loading", rounds=[], hp_max=[1, 1], frame=None, test=True)
        start, last_tick = time.time(), None
        try:
            while time.time() - start < deadline and not stop.is_set():
                if game.poll() is not None:
                    r["crashed"] = True
                    break
                d = read_telemetry()
                if d and d["tick"] != last_tick:
                    last_tick, r["seen"] = d["tick"], True
                    r["name"] = d["p1"].get("name") or r["name"]
                    live.update(frame=d, phase="fight" if d.get("round_state") == 2 else "between")
                    rs = d.get("round_state")
                    if rs == 2 or (r["fight_ticks"] and rs is not None and rs >= 3):
                        for i, k in enumerate(("p1", "p2")):
                            if isinstance(d[k].get("hp"), (int, float)):
                                r["hp"][i].append((d["tick"], d[k]["hp"]))
                    if rs == 2:
                        r["fight_ticks"] += 1
                        r["max_proj"] = max(r["max_proj"], d["p1"].get("num_proj") or 0)
                    elif r["fight_ticks"] and rs is not None and rs >= 3:
                        r["ended"] = True                       # KO / time over: probe is done
                if r["ended"] or r["fight_ticks"] >= probe_ticks:
                    break
                time.sleep(0.008)
        finally:
            if game.poll() is None:
                game.terminate()
                try:
                    game.wait(5)
                except subprocess.TimeoutExpired:
                    game.kill()
            live.update(pid=None, phase="idle", test=False)
    return r


def _life_stats(series, window=60):
    """From [(tick, life)]: damage taken, life regained, the most life lost inside any
    `window` ticks (60 = 1 s), and ticks from the first sample until life hit 0."""
    taken = healed = burst = 0
    ko_ticks = None
    j = 0
    for i, (t, hp) in enumerate(series):
        if i:
            delta = hp - series[i - 1][1]
            taken += max(0, -delta)
            healed += max(0, delta)
        while series[j][0] < t - window:
            j += 1
        burst = max(burst, max(h for _, h in series[j:i + 1]) - hp)
        if hp <= 0 and ko_ticks is None:
            ko_ticks = t - series[0][0]
    return {"taken": round(taken), "healed": round(healed), "burst_1s": round(burst), "ko_ticks": ko_ticks}


def smoke_test(entry, live, stop, tag):
    """Load test + fairness probes (see fairness.py), each vs kfm:
      A. the character (engine AI) attacks a kfm that stands still: loads?, projectile
         flood?, how hard does one hit / one second of offence hurt?
      B. the character stands still while kfm (engine AI) attacks it: does it lose
         life at all?
    Passes when it has fought, or - for characters with long intros / slow loading -
    when the game is still running fine at the deadline. Fails when the game closes
    (crash) or never shows the match.
    Returns (ok, note, in-game name, stats) - stats feed fairness.verdict()."""
    a = _probe(entry, live, stop, tag, config.AI_LEVEL, None)
    hit = _life_stats(a["hp"][1])
    stats = {"max_proj": a["max_proj"], "fight_ticks": a["fight_ticks"],
             "dealt_burst_1s": hit["burst_1s"], "dealt_ko_ticks": hit["ko_ticks"], "dealt": hit["taken"]}
    name = a["name"]
    if stop.is_set():
        return False, "หยุดโดยแอดมิน", name, stats
    if a["crashed"] and not a["ended"]:
        why = _panic_reason(a["log"])
        return False, ("เกมปิดตัวเองระหว่างเทส" + (f": {why}" if why else " (ตัวละครอาจต้องใช้ MUGEN เวอร์ชันอื่น)")), name, stats
    if not a["seen"]:
        return False, "เกมไม่เริ่มแมตช์ภายในเวลาเทส (โหลดไม่ผ่านหรือค้าง)", name, stats
    if a["fight_ticks"] < 120:
        return True, "ผ่าน (ไม่ crash) แต่ intro ยาวหรือโหลดช้า ยังไม่เห็นเริ่มสู้ภายในเวลาเทส", name, stats
    b = _probe(entry, live, stop, tag + "_b", None, config.AI_LEVEL)
    if stop.is_set():
        return False, "หยุดโดยแอดมิน", name, stats
    took = _life_stats(b["hp"][0])
    stats.update(taken=took["taken"], healed=took["healed"], taken_ticks=b["fight_ticks"],
                 taken_ko=took["ko_ticks"] is not None)
    return True, "", name, stats
