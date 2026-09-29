import random
import threading
import time
from queue import Queue
from typing import Optional

import pyautogui
import pyperclip

import config
from models import Exercise, BotSettings

# ------------------------------------------------------------
# Карта символов для русской раскладки ЙЦУКЕН.
# Значение: (физическая клавиша для PyAutoGUI, нужен ли Shift).
# ------------------------------------------------------------
_LOWER_MAP = {
    "ё": ("`", False),
    "й": ("q", False),
    "ц": ("w", False),
    "у": ("e", False),
    "к": ("r", False),
    "е": ("t", False),
    "н": ("y", False),
    "г": ("u", False),
    "ш": ("i", False),
    "щ": ("o", False),
    "з": ("p", False),
    "х": ("[", False),
    "ъ": ("]", False),
    "ф": ("a", False),
    "ы": ("s", False),
    "в": ("d", False),
    "а": ("f", False),
    "п": ("g", False),
    "р": ("h", False),
    "о": ("j", False),
    "л": ("k", False),
    "д": ("l", False),
    "ж": (";", False),
    "э": ("'", False),
    "я": ("z", False),
    "ч": ("x", False),
    "с": ("c", False),
    "м": ("v", False),
    "и": ("b", False),
    "т": ("n", False),
    "ь": ("m", False),
    "б": (",", False),
    "ю": (".", False),
    ".": ("/", False),
    ",": ("/", True),
    ";": ("4", True),
    ":": ("6", True),
    "?": ("7", True),
    "!": ("1", True),
    '"': ("2", True),
    "№": ("3", True),
    "%": ("5", True),
    "*": ("8", True),
    "(": ("9", True),
    ")": ("0", True),
    "_": ("-", True),
    "+": ("=", True),
    "-": ("-", False),
    "=": ("=", False),
    "\\": ("\\", False),
    "/": ("\\", True),
    " ": ("space", False),
    "\n": ("enter", False),
    "\t": ("tab", False),
}

CHAR_MAP = dict(_LOWER_MAP)

# Добавляем заглавные буквы.
for lower, (key, shift) in _LOWER_MAP.items():
    if lower.isalpha():
        CHAR_MAP[lower.upper()] = (key, True)

WRONG_CHARS = list("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


def _type_char(char: str) -> None:
    """Нажимает одну клавишу/комбинацию для заданного символа."""
    if char in CHAR_MAP:
        key, need_shift = CHAR_MAP[char]
        if need_shift:
            pyautogui.hotkey("shift", key)
        else:
            pyautogui.press(key)
    else:
        # Для символов вроде « », —, … и т.п. используем буфер обмена.
        pyperclip.copy(char)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)


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

        base_delay = 60.0 / self.settings.cpm
        variation = config.RANDOM_DELAY_VARIATION

        try:
            for ch in text:
                if self.stop_event.is_set():
                    self._put("stopped")
                    return

                # Генерация ошибки.
                if random.random() < self.settings.error_percent / 100.0:
                    wrong = random.choice(WRONG_CHARS)
                    if wrong != ch:
                        _type_char(wrong)
                        time.sleep(0.03)
                        pyautogui.press("backspace")
                        time.sleep(0.03)
                        self.errors += 1
                        self._put("error_count", errors=self.errors)

                _type_char(ch)
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