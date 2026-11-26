"""Win32 helpers by process id, so the arena only ever touches the Ikemen window it
launched itself (a player may have another Ikemen open on the same PC)."""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def dpi_aware():
    """Physical-pixel coordinates for window rects and screen grabs."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def window_of(pid):
    found = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def client_box(hwnd):
    """(left, top, right, bottom) of the window's client area on screen, or None."""
    if not hwnd or user32.IsIconic(hwnd):
        return None
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)) or r.right < 50 or r.bottom < 50:
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def has_focus(hwnd):
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def focus(hwnd):
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)
    user32.keybd_event(0x12, 0, 0, 0)          # Alt tap lets SetForegroundWindow through
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)
    return has_focus(hwnd)
