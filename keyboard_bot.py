import ctypes
import random
import threading
import time
from queue import Queue
from typing import Optional

import pyautogui
from pynput.keyboard import Controller

import config
from models import Exercise, BotSettings

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_SC_SHIFT = 0x2A
_SC_SPACE = 0x39


def _send_key(scan_code: int, key_up: bool = False, virtual_key: int = 0) -> None:
    flags = (0 if virtual_key else _KEYEVENTF_SCANCODE) | (
        _KEYEVENTF_KEYUP if key_up else 0
    )
    event = _INPUT(
        type=1,
        u=_INPUTUNION(ki=_KEYBDINPUT(virtual_key, scan_code, flags, 0, 0)),
    )
    if not ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)):
        raise ctypes.WinError()


def _tap_virtual_key(virtual_key: int, scan_code: int) -> None:
    _send_key(scan_code, virtual_key=virtual_key)
    time.sleep(0.04)
    _send_key(scan_code, key_up=True, virtual_key=virtual_key)


def _tap_scan_code(scan_code: int, shift: bool = False) -> None:
    if shift:
        _send_key(_SC_SHIFT)
        time.sleep(0.01)
    _send_key(scan_code)
    time.sleep(0.02)
    _send_key(scan_code, key_up=True)
    if shift:
        time.sleep(0.01)
        _send_key(_SC_SHIFT, key_up=True)


def _key_row(chars: str, first_scan_code: int) -> dict[str, int]:
    return {char: first_scan_code + offset for offset, char in enumerate(chars)}


_RU_KEYS: dict[str, int] = {}
_RU_KEYS.update(_key_row("йцукенгшщзхъ", 0x10))
_RU_KEYS.update(_key_row("фывапролджэ", 0x1E))
_RU_KEYS["ё"] = 0x29
_RU_KEYS.update(_key_row("ячсмитьбю", 0x2C))

_EN_KEYS: dict[str, int] = {}
_EN_KEYS.update(_key_row("qwertyuiop", 0x10))
_EN_KEYS.update(_key_row("asdfghjkl", 0x1E))
_EN_KEYS.update(_key_row("zxcvbnm", 0x2C))

_RU_PUNCTUATION = {
    ".": (0x35, False), ",": (0x35, True), "?": (0x08, True),
    "!": (0x02, True), ";": (0x05, True), ":": (0x07, True),
    "-": (0x0C, False), '"': (0x03, True), "(": (0x0A, True),
    ")": (0x0B, True), "№": (0x04, True), "%": (0x06, True),
    "*": (0x09, True), "_": (0x0C, True), "+": (0x0D, True),
    "=": (0x0D, False), "\\": (0x2B, False), "/": (0x2B, True),
}
_EN_PUNCTUATION = {
    ".": (0x34, False), ",": (0x33, False), "?": (0x35, True),
    "!": (0x02, True), ";": (0x27, False), ":": (0x27, True),
    "-": (0x0C, False), '"': (0x28, True), "'": (0x28, False),
    "(": (0x0A, True), ")": (0x0B, True), "_": (0x0C, True),
    "+": (0x0D, True), "=": (0x0D, False), "\\": (0x2B, False),
    "/": (0x35, False),
}


def _char_to_key(char: str, language: str) -> tuple[int, bool] | None:
    if char == " ":
        return _SC_SPACE, False
    if char.isdigit() and char.isascii():
        return (0x0B if char == "0" else 0x01 + int(char)), False

    lowercase = char.lower()
    shift = char != lowercase
    keys = _RU_KEYS if language == "ru" else _EN_KEYS
    if lowercase in keys:
        return keys[lowercase], shift

    punctuation = _RU_PUNCTUATION if language == "ru" else _EN_PUNCTUATION
    return punctuation.get(char)


def _type_char(char: str, language: str, controller: Controller) -> None:
    if char == "\n":
        _tap_virtual_key(0x0D, 0x1C)
        return
    if char == "\t":
        _tap_virtual_key(0x09, 0x0F)
        return

    key = _char_to_key(char, language)
    if key is None:
        controller.type(char)
        return
    if char == " ":
        _tap_virtual_key(0x20, _SC_SPACE)
        return
    _tap_scan_code(*key)


def _keyboard_language() -> str:
    user32 = ctypes.windll.user32
    window = user32.GetForegroundWindow()
    if not window:
        return "other"
    thread_id = user32.GetWindowThreadProcessId(window, None)
    language_id = user32.GetKeyboardLayout(thread_id) & 0xFFFF
    return {0x419: "ru", 0x409: "en"}.get(language_id, "other")


def _sleep_interruptible(seconds: float, stop_event: threading.Event) -> bool:
    """Спит, но прерывается, если выставлен stop_event."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_event.is_set():
            return False
        time.sleep(min(0.05, max(0.0, end - time.time())))
    return True


class KeyboardBot:
    def __init__(self, exercise: Exercise, settings: BotSettings, queue: Queue):
        self.exercise = exercise
        self.settings = settings
        self.queue = queue
        self.stop_event = threading.Event()
        self.typed = 0
        self.errors = 0
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _put(self, msg_type: str, **kwargs) -> None:
        self.queue.put((msg_type, kwargs))

    def _run(self) -> None:
        pyautogui.FAILSAFE = True

        self._put("status", text="Запуск")

        # Задержка, чтобы пользователь успел переключиться на окно «Соло».
        if not _sleep_interruptible(config.START_DELAY, self.stop_event):
            self._put("stopped")
            return

        self._put("status", text="Выполняется")

        text = self.exercise.text
        total = len(text)
        self._put("progress", typed=0, total=total)

        language = _keyboard_language()
        has_cyrillic = any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in text)
        has_latin = any(char.isascii() and char.isalpha() for char in text)
        if (has_cyrillic and language != "ru") or (
            not has_cyrillic and has_latin and language != "en"
        ):
            self._put(
                "error_msg",
                text=f"В Solo выбрана раскладка '{language}', проверьте раскладку для текста урока.",
            )
            self._put("status", text="Ошибка")
            return

        controller = Controller()

        base_delay = 60.0 / self.settings.cpm
        variation = config.RANDOM_DELAY_VARIATION

        try:
            for ch in text:
                if self.stop_event.is_set():
                    self._put("stopped")
                    return

                _type_char(ch, language, controller)
                self.typed += 1
                self._put("progress", typed=self.typed, total=total)

                delay = base_delay * random.uniform(1.0 - variation, 1.0 + variation)
                if not _sleep_interruptible(delay, self.stop_event):
                    self._put("stopped")
                    return

            self._put("finished")

        except pyautogui.FailSafeException:
            self._put(
                "error_msg",
                text="PyAutoGUI FAILSAFE: выполнение прервано (курсор в углу экрана).",
            )
            self._put("stopped")
        except Exception as exc:
            self._put("error_msg", text=f"Ошибка: {exc}")
            self._put("status", text="Ошибка")