"""Arena fairness rules (decided by the admin on 2026-11-26):

1. Every character fights with the same max life (config.LIFE, default 1000). The
   arena rewrites `life` in the [Data] section of its own installed copy under
   engine/chars/<id>/ - the uploaded original is left untouched.
2. Cheating characters are banned. Two probe fights vs kfm (engine.smoke_test) measure
   behaviour, not code - code checks misfire because normal characters use NotHitBy /
   LifeAdd / big damage too:
   a. projectile flood: more than config.PROJ_LIMIT projectiles on screen at once
      (normal characters peak at ~15; EGX-Daishinkan put 256 on screen);
   b. one-hit kill: the character's AI takes more than config.OHKO_BURST life from a
      kfm that stands still within one second;
   c. immortal: the character stands still for FAIR_SECONDS while kfm's AI attacks it
      and loses less than config.IMMORTAL_MIN_TAKEN life (net of any regeneration).
      The edited "god mode" Yuta Body Gojo upload (permanent NotHitBy) is the case.
"""
import re
from pathlib import Path

from . import config

FAIR_VERSION = 2          # bump to re-test every character with new rules

DATA_SECTION = re.compile(rb"(?ims)^[ \t]*\[\s*data\s*\][^\r\n]*\r?$(.*?)(?=^[ \t]*\[|\Z)")
LIFE_LINE = re.compile(rb"(?im)^([ \t]*life[ \t]*=[ \t]*)(\d+)")


def _state_files(def_path):
    from .stateindex import char_files          # lazy: stateindex -> submissions -> engine
    _, files = char_files(def_path)
    return [p for _, p in files]


def normalize_life(def_path, life=None):
    """Set [Data] life in the installed character's files. Returns the original life
    (None if no [Data] life was found). Idempotent."""
    life = life or config.LIFE
    original = None
    for f in _state_files(def_path):
        raw = f.read_bytes()
        m = DATA_SECTION.search(raw)
        if not m:
            continue
        body = m.group(1)
        lm = LIFE_LINE.search(body)
        if not lm:
            continue
        original = int(lm.group(2))
        if original != life:
            new_body = body[:lm.start(2)] + str(life).encode() + body[lm.end(2):]
            f.write_bytes(raw[:m.start(1)] + new_body + raw[m.end(1):])
        break                                         # MUGEN uses the first [Data] it reads
    return original


def installed_def(ch):
    return config.ENGINE / "chars" / ch["def_rel"]


def apply_to_roster(store):
    """At server start: equal life for every installed character, and queue a re-test
    for characters not yet checked under the current rules."""
    with store.tx() as db:
        for ch in db["chars"].values():
            d = installed_def(ch)
            if d.exists():
                orig = normalize_life(d)
                if ch.get("life_orig") is None and orig is not None:
                    ch["life_orig"] = orig
            if ch["status"] in ("ready", "failed") and ch.get("fair_v") != FAIR_VERSION \
                    and not ch.get("reserved_for"):
                ch["status"] = "queued_test"


def verdict(stats):
    """(banned?, note) from what the probe fights measured (engine.smoke_test stats)."""
    why = []
    n = stats.get("max_proj") or 0
    if n > config.PROJ_LIMIT:
        why.append(f"ยิงกระสุนค้างบนจอพร้อมกัน {n} ลูก (กติกาไม่เกิน {config.PROJ_LIMIT})")
    burst = stats.get("dealt_burst_1s") or 0
    if burst > config.OHKO_BURST:
        why.append(f"ตีหนักผิดปกติ: ทำดาเมจ {burst} จากเลือด {config.LIFE} ภายใน 1 วินาที "
                   f"(กติกาไม่เกิน {config.OHKO_BURST})")
    if "taken" in stats and not stats.get("taken_ko") and (stats.get("taken_ticks") or 0) >= 600:
        net = (stats["taken"] or 0) - (stats.get("healed") or 0)
        if net < config.IMMORTAL_MIN_TAKEN:
            why.append(f"อมตะ: ยืนเฉย ๆ ให้ KFM ตี {stats['taken_ticks'] // 60} วินาที เลือดลดแค่ {max(net, 0)} "
                       f"(ต้องลดอย่างน้อย {config.IMMORTAL_MIN_TAKEN})")
    if why:
        return True, "แบน: " + " · ".join(why)
    return False, ""
