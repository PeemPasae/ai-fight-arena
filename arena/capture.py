"""Grabs the arena's Ikemen window ~CAPTURE_FPS times a second as JPEG for the live
MJPEG stream. Only captures the window of the process the worker launched."""
import io
import threading
import time

from PIL import Image, ImageDraw, ImageFont, ImageGrab

from . import config, win


def _placeholder(text):
    w, h = config.CAPTURE_WIDTH, config.CAPTURE_WIDTH * 9 // 16
    img = Image.new("RGB", (w, h), (14, 16, 24))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("tahoma.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), text, font=font)
    d.text(((w - box[2]) / 2, (h - box[3]) / 2), text, fill=(150, 160, 190), font=font)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


class Capture(threading.Thread):
    def __init__(self, worker):
        super().__init__(daemon=True, name="arena-capture")
        self.worker = worker
        self.frame = _placeholder("ARENA IDLE - waiting for the next match")
        self.seq = 0
        self.cond = threading.Condition()
        self.idle_img = self.frame
        self.viewers = 0

    def run(self):
        hwnd, pid = None, None
        while True:
            t0 = time.time()
            live = self.worker.live_snapshot()
            frame = None
            if live.get("pid") and self.viewers > 0:
                if live["pid"] != pid:
                    pid, hwnd = live["pid"], None
                hwnd = hwnd or win.window_of(pid)
                box = win.client_box(hwnd)
                if box:
                    try:
                        img = ImageGrab.grab(bbox=box, all_screens=True)
                        h = round(img.height * config.CAPTURE_WIDTH / img.width)
                        img = img.resize((config.CAPTURE_WIDTH, h), Image.BILINEAR)
                        buf = io.BytesIO()
                        img.save(buf, "JPEG", quality=72)
                        frame = buf.getvalue()
                    except OSError:
                        frame = None
            elif not live.get("pid"):
                pid, hwnd = None, None
            if frame is None and not live.get("pid"):
                frame = self.idle_img
            if frame is not None:
                with self.cond:
                    self.frame = frame
                    self.seq += 1
                    self.cond.notify_all()
            time.sleep(max(0.0, 1 / config.CAPTURE_FPS - (time.time() - t0)))

    def wait_frame(self, last_seq, timeout=2.0):
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            return self.seq, self.frame
