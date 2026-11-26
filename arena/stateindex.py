"""Builds a state index (STATE_INDEX) for any MUGEN/Ikemen character automatically:
every [Statedef] with its type, the button command that starts it, damage, throws,
projectiles, supers (power cost), invincibility/counters, and where it goes next.
Used for the "training data" downloads friends use to build their own bots."""
import csv
import io
import json
import re
from pathlib import Path

from .submissions import parse_def, read_text

STANDARD = {
    0: "Stand", 10: "Stand to crouch", 11: "Crouching", 12: "Crouch to stand", 20: "Walk",
    40: "Jump start", 45: "Air jump start", 50: "Jump up", 51: "Jump down", 52: "Jump land",
    100: "Run forward", 105: "Hop backward", 106: "Hop backward (land)",
    120: "Guard (start)", 130: "Stand guard", 131: "Crouch guard", 132: "Air guard", 140: "Guard (end)",
    150: "Stand guard hit (shaking)", 151: "Stand guard hit (knocked back)",
    152: "Crouch guard hit (shaking)", 153: "Crouch guard hit (knocked back)",
    154: "Air guard hit (shaking)", 155: "Air guard hit (knocked away)",
    170: "Lose (time over)", 175: "Draw game", 180: "Win pose", 181: "Win pose 1", 182: "Win pose 2",
    190: "Pre-intro", 191: "Intro", 5000: "Stand get-hit (shaking)", 5001: "Stand get-hit (knocked back)",
    5010: "Crouch get-hit (shaking)", 5011: "Crouch get-hit (knocked back)", 5020: "Air get-hit (shaking)",
    5030: "Air get-hit (knocked away)", 5035: "Air get-hit (transition)", 5040: "Air get-hit (recovering)",
    5050: "Air get-hit (falling)", 5070: "Tripped get-hit (shaking)", 5071: "Tripped get-hit (knocked away)",
    5080: "Downed get-hit (shaking)", 5081: "Downed get-hit (knocked back)",
    5100: "Downed (hit ground)", 5101: "Downed (bounce)", 5110: "Downed (lying down)", 5120: "Get up",
    5150: "Downed (defeated)", 5200: "Fall recovery (ground)", 5201: "Fall recovery (ground)",
    5210: "Fall recovery (air)", 5500: "Continue screen", 5900: "Round start (initialize)",
}
TYPE = {"S": "ยืน", "C": "ย่อ", "A": "อากาศ", "L": "นอน", "U": "-"}
MOVE = {"A": "โจมตี", "I": "เฉย ๆ", "H": "โดนตี", "U": "-"}

HEADER = re.compile(r"^\s*\[\s*statedef\s+(-?\d+)\s*(?:,\s*([^\]]*))?\]\s*(?:;\s*(.*))?$", re.I)
STATE_HDR = re.compile(r"^\s*\[\s*state\s+[^\]]*\]", re.I)
KV = re.compile(r"^\s*([a-z0-9_.]+)\s*=\s*(.*)$", re.I)


def _resolve(base, rel):
    """Case-insensitive path inside the character folder."""
    p = base
    for part in Path(rel.replace("\\", "/")).parts:
        if part in (".", ""):
            continue
        if part == "..":
            p = p.parent
            continue
        if not p.is_dir():
            return None
        hit = [c for c in p.iterdir() if c.name.lower() == part.lower()]
        if not hit:
            return None
        p = hit[0]
    return p if p.is_file() else None


def char_files(def_path):
    d = parse_def(def_path)
    files = d.get("files", {})
    base = Path(def_path).parent
    order = ["cmd", "cns", "st"] + [f"st{i}" for i in range(10)] + ["stcommon"]
    out, seen = [], set()
    for k in order:
        v = files.get(k)
        p = _resolve(base, v) if v else None
        if p and p not in seen:
            seen.add(p)
            out.append((k, p))
    return d, out


def _strip(v):
    return v.split(";", 1)[0].strip().strip('"')


def _first_num(v):
    m = re.match(r"\s*(-?\d+)", v or "")
    return int(m.group(1)) if m else None


def parse_states(def_path):
    """{state_no: info} for every [Statedef] in the character's files, plus
    {command name: command string}."""
    info, commands, minus1 = {}, {}, []
    d, files = char_files(def_path)
    for key, path in files:
        text = read_text(path).splitlines()
        cur, ctrl_type, prev_comments, block = None, None, [], None
        cmd_block = None
        for raw in text:
            line = raw.rstrip()
            s = line.strip()
            if s.startswith(";"):
                c = s.lstrip(";").strip(" -=*_#")
                if c:
                    prev_comments = (prev_comments + [c])[-2:]
                continue
            if not s:
                prev_comments = prev_comments if cur is None else prev_comments
                continue
            if re.match(r"^\[\s*command\s*\]", s, re.I):
                cmd_block, cur = {}, None
                continue
            m = HEADER.match(s)
            if m:
                cmd_block = None
                no = int(m.group(1))
                name = (m.group(3) or m.group(2) or "").strip() or (prev_comments[-1] if prev_comments else "")
                cur = info.setdefault(no, {"state": no, "file": path.name, "name": name, "type": "", "movetype": "",
                                           "physics": "", "anim": "", "ctrl": "", "poweradd": "", "damage": [],
                                           "guardflag": "", "throw": False, "projectile": False, "helper": False,
                                           "super": False, "invincible": False, "counter": False, "next": set(),
                                           "commands": set()})
                if not cur["name"] and name:
                    cur["name"] = name
                ctrl_type, block, prev_comments = None, "head", []
                continue
            if STATE_HDR.match(s):
                ctrl_type, block = None, "ctrl"
                if cur is not None and cur["state"] == -1:
                    minus1.append({"value": None, "cmds": set()})
                prev_comments = []
                continue
            if s.startswith("["):
                cur, cmd_block = None, None
                continue
            kv = KV.match(s)
            if not kv:
                continue
            k, rawv = kv.group(1).lower(), kv.group(2).split(";", 1)[0]
            v = rawv.strip().strip('"')
            if cmd_block is not None:
                cmd_block[k] = v
                if "name" in cmd_block and "command" in cmd_block:
                    commands.setdefault(cmd_block["name"], cmd_block["command"])
                continue
            if cur is None:
                continue
            if block == "head":
                if k in ("type", "movetype", "physics", "anim", "ctrl"):
                    cur[k] = v
                elif k == "poweradd":                 # header poweradd = meter gained by the move
                    n = _first_num(v)
                    if n is not None and n < 0:
                        cur["poweradd"] = str(n)
                continue
            if k == "type":
                ctrl_type = v.lower()
                if ctrl_type == "projectile":
                    cur["projectile"] = True
                elif ctrl_type == "helper":
                    cur["helper"] = True
                elif ctrl_type == "superpause":
                    cur["super"] = True
                elif ctrl_type in ("nothitby", "hitby"):
                    cur["invincible"] = True
                elif ctrl_type in ("hitoverride", "reversaldef"):
                    cur["counter"] = True
                continue
            if cur["state"] == -1 and minus1:
                if k == "value" and ctrl_type == "changestate":
                    n = _first_num(v)
                    if n is not None:
                        minus1[-1]["value"] = n
                for cm in re.findall(r'command\s*=\s*"([^"]+)"', rawv, re.I):
                    minus1[-1]["cmds"].add(cm)
                continue
            if ctrl_type == "hitdef":
                if k == "damage":
                    n = _first_num(v)
                    if n is not None:
                        cur["damage"].append(n)
                elif k == "guardflag":
                    cur["guardflag"] = v
                elif k == "p2stateno":
                    cur["throw"] = True
            elif ctrl_type == "poweradd" and k == "value":
                n = _first_num(v)
                if n is not None and n < 0:
                    cur["poweradd"] = str(n)
            elif ctrl_type == "changestate" and k == "value":
                n = _first_num(v)
                if n is not None:
                    cur["next"].add(n)
    for blk in minus1:
        if blk["value"] is not None and blk["value"] in info and blk["cmds"]:
            info[blk["value"]]["commands"] |= blk["cmds"]
    info.pop(-1, None)
    info.pop(-2, None)
    info.pop(-3, None)
    return d, info, commands


def rows(def_path):
    d, info, commands = parse_states(def_path)
    out = []
    for no in sorted(info):
        s = info[no]
        tags = []
        if s["damage"]:
            tags.append("ดาเมจ " + "/".join(str(x) for x in s["damage"][:4]))
        if s["throw"]:
            tags.append("ทุ่ม/จับ")
        if s["projectile"]:
            tags.append("ยิงกระสุน")
        if s["helper"]:
            tags.append("helper")
        if s["super"]:
            tags.append("ซุปเปอร์ (หยุดจอ)")
        if s["poweradd"]:
            tags.append(f"ใช้เกจ {s['poweradd']}")
        if s["invincible"]:
            tags.append("อมตะบางช่วง")
        if s["counter"]:
            tags.append("สวนกลับ/HitOverride")
        if s["guardflag"] == "" and s["damage"] and not s["throw"]:
            tags.append("กันไม่ได้?")
        name = s["name"] or STANDARD.get(no, "")
        cmd = sorted(s["commands"])
        out.append({
            "state": no, "name": name, "type": TYPE.get(s["type"][:1].upper(), s["type"]),
            "movetype": MOVE.get(s["movetype"][:1].upper(), s["movetype"]), "anim": s["anim"],
            "commands": ", ".join(f"{c} ({commands.get(c, '?')})" for c in cmd),
            "tags": ", ".join(tags), "next": ", ".join(str(n) for n in sorted(s["next"])[:8]), "file": s["file"],
        })
    return d, out


COLS = [("state", "State"), ("name", "ชื่อ/คอมเมนต์"), ("type", "ท่าทาง"), ("movetype", "ประเภท"),
        ("commands", "ปุ่มที่กด (command)"), ("tags", "รายละเอียด"), ("next", "ไปต่อ state"), ("file", "ไฟล์")]


def as_markdown(def_path, title=None):
    d, rs = rows(def_path)
    info = d.get("info", {})
    name = title or info.get("displayname") or info.get("name") or Path(def_path).stem
    lines = [f"# State index: {name}", "",
             f"สร้างอัตโนมัติจากไฟล์ตัวละคร ({Path(def_path).name}) · ผู้สร้างตัวละคร: {info.get('author', '-')}",
             "ชื่อมาจากคอมเมนต์ในไฟล์ (ถ้ามี) หรือชื่อมาตรฐานของ MUGEN · \"ปุ่มที่กด\" มาจาก [Statedef -1] ใน .cmd",
             "\"กันไม่ได้?\" = HitDef ไม่มี guardflag (เดาจากไฟล์ ควรเช็กในเกม)", "",
             "| " + " | ".join(h for _, h in COLS) + " |", "|" + "---|" * len(COLS)]
    for r in rs:
        lines.append("| " + " | ".join(str(r[k]).replace("|", "/") for k, _ in COLS) + " |")
    return "\n".join(lines) + "\n"


def as_csv(def_path):
    _, rs = rows(def_path)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[k for k, _ in COLS], extrasaction="ignore")
    w.writeheader()
    w.writerows(rs)
    return "﻿" + buf.getvalue()          # BOM so Excel shows Thai correctly


def as_json(def_path):
    d, rs = rows(def_path)
    return json.dumps({"character": d.get("info", {}), "states": rs}, ensure_ascii=False, indent=1)
