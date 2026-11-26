"""Training-data downloads for friends: per character a state index (md/csv/json) and
the per-frame telemetry logs of every arena match the character fought in."""
import io
import json
import re
import time
import zipfile
from pathlib import Path

from . import config, stateindex

TELEMETRY_README = """# ข้อมูลฝึกบอทจาก AI Fight Arena

## มีอะไรบ้าง
- `<ตัวละคร>/states.md` (.csv / .json) : รายการ state ของตัวละคร สร้างอัตโนมัติจากไฟล์ตัวละคร
  ชื่อ/คอมเมนต์ · ท่าทาง (ยืน/ย่อ/อากาศ) · ประเภท (โจมตี/เฉย ๆ/โดนตี) · ปุ่มที่กดออกท่า · ดาเมจ · ทุ่ม · ยิงกระสุน
  · ซุปเปอร์และเกจที่ใช้ · ช่วงอมตะ/สวนกลับ · state ที่ไปต่อ
- `<ตัวละคร>/STATE_INDEX_by_author.md` : ถ้าเจ้าของตัวละครเขียนไว้เอง (แม่นกว่าแบบอัตโนมัติ)
- `matches/<id>.jsonl.gz` : log แมตช์ทุกเฟรม (1 บรรทัด = 1 เฟรม, 60 เฟรม/วินาที) เปิดด้วย Python:
  ```python
  import gzip, json
  rows = [json.loads(l) for l in gzip.open("matches/m0012.jsonl.gz", "rt", encoding="utf-8")]
  ```
- `matches/<id>.json` : ใครแข่งกับใคร ใช้ตัวอะไร อยู่ฝั่งไหน ผลรายยก

## ฟิลด์ในแต่ละเฟรม
| ฟิลด์ | ความหมาย |
|---|---|
| tick | เลขเฟรม |
| round_no / round_state | ยกที่ / 0-1 = intro, 2 = กำลังสู้, 3+ = จบยก |
| p1 / p2 | ข้อมูลผู้เล่นแต่ละฝั่ง (ข้างล่าง) |
| state_no | เลข state ตอนนั้น (เทียบกับ states.md ของตัวนั้น) |
| time / anim_time | เฟรมที่อยู่ใน state นี้มาแล้ว / เหลืออีกกี่เฟรมจบแอนิเมชัน (ติดลบ = ยังไม่จบ) |
| ctrl | ควบคุมได้ไหม (true = ออกท่าใหม่ได้) |
| state_type / move_type | S ยืน, C ย่อ, A อากาศ, L นอน / A โจมตี, I เฉย ๆ, H โดนตี |
| hp / power | เลือด / เกจซุปเปอร์ |
| y, vx, vy, facing | ความสูง, ความเร็ว, หันขวา(1)/ซ้าย(-1) |
| body_dist_x / body_dist_y | ระยะห่างตัวถึงตัวคู่ต่อสู้ (บวก = อยู่ข้างหน้า) |
| in_guard_dist | มีท่าโจมตีอยู่ในระยะที่ต้องกัน |
| front_edge / back_edge | ระยะถึงขอบจอด้านหน้า/หลัง |
| move_hit / move_contact / move_guarded | ท่าตัวเองโดน / ชน / ถูกกัน |
| hit_pause | เฟรมหยุดค้างตอนโดน |
| num_proj | จำนวนกระสุนที่ยิงอยู่ |
| name / ai_level | ชื่อตัวละคร / 0 = คนหรือบอทคุม, >0 = AI ของเกม |

## ใช้กับบอทยังไง
บอทอ่านไฟล์ `general_bot_telemetry.json` (รูปแบบเดียวกับบรรทัดใน log) จาก mod `general_bot_telemetry.lua`
แล้วกดปุ่มตามคีย์ของ P1/P2 ใน `save/config.ini` · ตัวอย่างโค้ดดูได้จากบอทของ ภีม (General)
"""


def _safe(name):
    return re.sub(r"[^\w\-. ]+", "_", name or "char").strip()[:40] or "char"


def char_def(cid, db):
    c = db["chars"][cid]
    return config.ENGINE / "chars" / c["def_rel"]


def matches_of(db, cid=None):
    """Finished matches (with a trace file) involving a player who used character cid."""
    out = []
    for m in sorted(db["matches"].values(), key=lambda m: m["id"]):
        if m["status"] != "done":
            continue
        chars = [db["players"].get(m[k], {}).get("char") for k in ("p1", "p2")]
        if cid and cid not in chars:
            continue
        if (config.DATA / "traces" / f"{m['id']}.jsonl.gz").exists():
            out.append(m)
    return out


def _match_meta(db, m):
    side = {}
    for k in ("p1", "p2"):
        p = db["players"].get(m[k], {})
        side[k] = {"player": p.get("name"), "char": db["chars"].get(p.get("char"), {}).get("char_name")}
    r = m.get("result") or {}
    return {"id": m["id"], **side, "rounds": r.get("rounds"), "wins": r.get("wins"),
            "winner_side": r.get("winner_slot"), "duration_s": r.get("duration")}


def _add_char(z, db, cid, prefix):
    c = db["chars"][cid]
    path = char_def(cid, db)
    z.writestr(f"{prefix}states.md", stateindex.as_markdown(path, c["char_name"]))
    z.writestr(f"{prefix}states.csv", stateindex.as_csv(path))
    z.writestr(f"{prefix}states.json", stateindex.as_json(path))
    for f in path.parent.glob("*.md"):
        if "state" in f.name.lower():
            z.write(f, f"{prefix}STATE_INDEX_by_author.md")
            break


def _add_matches(z, db, ms, prefix="matches/"):
    for m in ms:
        z.write(config.DATA / "traces" / f"{m['id']}.jsonl.gz", f"{prefix}{m['id']}.jsonl.gz", zipfile.ZIP_STORED)
        z.writestr(f"{prefix}{m['id']}.json", json.dumps(_match_meta(db, m), ensure_ascii=False, indent=1))


def char_zip(db, cid):
    buf = io.BytesIO()
    c = db["chars"][cid]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", TELEMETRY_README)
        _add_char(z, db, cid, f"{_safe(c['char_name'])}/")
        _add_matches(z, db, matches_of(db, cid))
    return buf.getvalue()


def all_zip(db):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", TELEMETRY_README)
        for cid, c in sorted(db["chars"].items()):
            if c["status"] == "ready":
                _add_char(z, db, cid, f"{cid}_{_safe(c['char_name'])}/")
        _add_matches(z, db, matches_of(db))
    return buf.getvalue()


def stamp():
    return time.strftime("%Y%m%d")
