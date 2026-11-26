"""Arena settings. Edit here (or data/settings.json overrides the UPPERCASE names)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_SRC = ROOT / "ikemen"                 # Ikemen GO kept in git; engine/ is built from it on first run
ENGINE = ROOT / "engine"                     # the one shared engine every match runs on
DATA = ROOT / "data"
SUBMISSIONS = ROOT / "submissions"
WEB = ROOT / "web"
UNRAR = Path(r"C:\Program Files\WinRAR\UnRAR.exe")

HOST = "0.0.0.0"          # reachable from other devices on the same network
PORT = 8080

ROUNDS = 2                # rounds needed to win a match
AI_LEVEL = 8              # engine AI level for entries without an approved bot
STAGE = "stages/kfm.def"
BOTH_SIDES = True         # every pair plays twice, swapping P1/P2
MATCH_TIMEOUT = 480       # seconds before a match is called invalid
LOAD_TIMEOUT = 25         # seconds for a match to show telemetry after launch
SMOKE_SECONDS = 15        # load test length for a new entry
FAIR_SECONDS = 20         # probe fight length (s of real fighting) for the cheat check
PROJ_LIMIT = 40           # max projectiles on screen at once; more = banned (see fairness.py)
OHKO_BURST = 600          # most life a character may take from a still kfm in 1 s (one-hit kill)
IMMORTAL_MIN_TAKEN = 50   # least life a still character must lose to kfm's AI in FAIR_SECONDS
LIFE = 1000               # every character fights with this max life
FOCUS_GRACE = 2.0         # seconds a bot match may run without window focus

MAX_UPLOAD_MB = 150
MAX_FILES = 6000
MAX_UNPACKED_MB = 600
MIN_FREE_GB = 5            # stop taking uploads when the arena's drive has less free space
BLOCKED_EXT = {".exe", ".dll", ".bat", ".com", ".scr", ".ps1", ".vbs", ".msi", ".jar", ".lnk",
               ".cpl", ".hta", ".wsf", ".reg", ".sys"}
TELEMETRY_FILE = "general_bot_telemetry.json"
TELEMETRY_MOD = "general_bot_telemetry.lua"

CAPTURE_FPS = 12
CAPTURE_WIDTH = 768

_overrides = DATA / "settings.json"
if _overrides.exists():
    for _k, _v in json.loads(_overrides.read_text(encoding="utf-8")).items():
        if _k.isupper() and _k in globals():
            globals()[_k] = _v
