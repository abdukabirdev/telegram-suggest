"""ctypes declarations shared by the Windows-specific modules.

Only prototypes, structures and constants live here: no logic.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HKL = ctypes.c_void_p
HHOOK = ctypes.c_void_p
HMONITOR = ctypes.c_void_p

# Tag put into dwExtraInfo of every event we inject, so the hook can tell
# our own synthetic keystrokes from everything else.
INJECT_TAG = 0x54475347  # "TGSG"

# ---- constants ---------------------------------------------------------------

WH_KEYBOARD_LL = 13
HC_ACTION = 0

WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_HOTKEY = 0x0312
WM_APP = 0x8000

LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_PAUSE = 0x13
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_SNAPSHOT = 0x2C
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D
VK_F1 = 0x70
VK_F24 = 0x87
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_PACKET = 0xE7

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200

MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ALREADY_EXISTS = 183

# ---- structures --------------------------------------------------------------


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

# ---- prototypes --------------------------------------------------------------


def _proto(func, restype, *argtypes):
    func.restype = restype
    func.argtypes = argtypes
    return func


SetWindowsHookExW = _proto(user32.SetWindowsHookExW, HHOOK,
                           ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
UnhookWindowsHookEx = _proto(user32.UnhookWindowsHookEx, wintypes.BOOL, HHOOK)
CallNextHookEx = _proto(user32.CallNextHookEx, LRESULT,
                        HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
GetMessageW = _proto(user32.GetMessageW, ctypes.c_int,
                     ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
PostThreadMessageW = _proto(user32.PostThreadMessageW, wintypes.BOOL,
                            wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
RegisterHotKey = _proto(user32.RegisterHotKey, wintypes.BOOL,
                        wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
UnregisterHotKey = _proto(user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int)

GetForegroundWindow = _proto(user32.GetForegroundWindow, wintypes.HWND)
GetWindowThreadProcessId = _proto(user32.GetWindowThreadProcessId, wintypes.DWORD,
                                  wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
GetKeyboardLayout = _proto(user32.GetKeyboardLayout, HKL, wintypes.DWORD)
GetKeyboardLayoutList = _proto(user32.GetKeyboardLayoutList, ctypes.c_int,
                               ctypes.c_int, ctypes.POINTER(HKL))
ToUnicodeEx = _proto(user32.ToUnicodeEx, ctypes.c_int,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte),
                     wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, HKL)
GetAsyncKeyState = _proto(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
GetKeyState = _proto(user32.GetKeyState, ctypes.c_short, ctypes.c_int)
SendInput = _proto(user32.SendInput, wintypes.UINT,
                   wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)

GetWindowRect = _proto(user32.GetWindowRect, wintypes.BOOL,
                       wintypes.HWND, ctypes.POINTER(wintypes.RECT))
GetClientRect = _proto(user32.GetClientRect, wintypes.BOOL,
                       wintypes.HWND, ctypes.POINTER(wintypes.RECT))
ClientToScreen = _proto(user32.ClientToScreen, wintypes.BOOL,
                        wintypes.HWND, ctypes.POINTER(wintypes.POINT))
IsWindow = _proto(user32.IsWindow, wintypes.BOOL, wintypes.HWND)
IsIconic = _proto(user32.IsIconic, wintypes.BOOL, wintypes.HWND)
GetGUIThreadInfo = _proto(user32.GetGUIThreadInfo, wintypes.BOOL,
                          wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
GetCursorPos = _proto(user32.GetCursorPos, wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
SetWindowPos = _proto(user32.SetWindowPos, wintypes.BOOL,
                      wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                      ctypes.c_int, ctypes.c_int, wintypes.UINT)
GetWindowLongPtrW = _proto(user32.GetWindowLongPtrW, ctypes.c_ssize_t,
                           wintypes.HWND, ctypes.c_int)
SetWindowLongPtrW = _proto(user32.SetWindowLongPtrW, ctypes.c_ssize_t,
                           wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
MonitorFromPoint = _proto(user32.MonitorFromPoint, HMONITOR, wintypes.POINT, wintypes.DWORD)
GetMonitorInfoW = _proto(user32.GetMonitorInfoW, wintypes.BOOL,
                         HMONITOR, ctypes.POINTER(MONITORINFO))
GetDpiForWindow = _proto(user32.GetDpiForWindow, wintypes.UINT, wintypes.HWND)

OpenProcess = _proto(kernel32.OpenProcess, wintypes.HANDLE,
                     wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
QueryFullProcessImageNameW = _proto(kernel32.QueryFullProcessImageNameW, wintypes.BOOL,
                                    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                    ctypes.POINTER(wintypes.DWORD))
CloseHandle = _proto(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
GetCurrentThreadId = _proto(kernel32.GetCurrentThreadId, wintypes.DWORD)
GetModuleHandleW = _proto(kernel32.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
CreateMutexW = _proto(kernel32.CreateMutexW, wintypes.HANDLE,
                      ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
LCIDToLocaleName = _proto(kernel32.LCIDToLocaleName, ctypes.c_int,
                          wintypes.DWORD, wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD)


def key_down(vk: int) -> bool:
    """Is the key held right now (asynchronous, system-wide state)."""
    return GetAsyncKeyState(vk) < 0
