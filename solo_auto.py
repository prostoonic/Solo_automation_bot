"""
SOLO AUTO - всё в одном файле. Только Windows.

Запуск:            py solo_auto.py
Проверка чтения:   py solo_auto.py --test     (ничего не печатает, только показывает,
                                               что скрипт видит в выбранной области)
Остановка - клавиша Esc.

ВАЖНО: перед стартом включи в Solo нужную раскладку (русскую для русского текста).
"""

# ============ НАСТРОЙКИ (меняй только это) ============

MIN_DELAY = 0.05        # мин. пауза между нажатиями, сек
MAX_DELAY = 0.18        # макс. пауза между нажатиями, сек
ERROR_RATE = 0.0        # процент опечаток: 0.03 = 3% (0 - без ошибок). Сначала оставь 0!
ERROR_BACKSPACE = False # после опечатки нажимать Backspace (в Solo обычно не нужно)
FORCE_LOWERCASE = True  # приводить распознанный текст к строчным (OCR путает р/Р, а/А)
NEWLINE_AS = "none"     # как склеивать строки текста: "none" (без ничего), "space" (пробел) или "enter" (Enter)
MAX_ROUNDS = 1          # сколько упражнений пройти подряд (для проверки 1)
ROUND_PAUSE = 2.5       # пауза между упражнениями, сек
STARTUP_DELAY = 6       # секунд на то, чтобы кликнуть в поле ввода Solo
REGION_DELAY = 8        # секунд на наведение мыши при выборе области
WINDOW_TITLE_RE = r".*(Соло|Solo).*"   # как называется окно тренажёра

# ======================================================

import ctypes
import importlib
import os
import random
import re
import shutil
import site
import subprocess
import sys
import time
import urllib.request
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REGION_FILE = os.path.join(HERE, "region.json")
TESSDATA_DIR = os.path.join(HERE, "tessdata")
DEBUG_IMG = os.path.join(HERE, "debug_ocr.png")


# ---------- 1. автоустановка библиотек ----------

def ensure_packages():
    needed = {
        "pynput": "pynput",
        "pywinauto": "pywinauto",
        "pyautogui": "pyautogui",
        "PIL": "pillow",
        "pytesseract": "pytesseract",
        "mss": "mss",
    }
    missing = []
    for module, pip_name in needed.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"Устанавливаю библиотеки: {', '.join(missing)} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.append(user_site)
        importlib.invalidate_caches()
        print("Готово. Запусти скрипт ещё раз, если дальше появится ошибка импорта.\n")


ensure_packages()

import json  # noqa: E402

import mss  # noqa: E402
import pyautogui  # noqa: E402
import pytesseract  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402
from pynput import keyboard as kb  # noqa: E402
from pynput.keyboard import Controller, Key  # noqa: E402
from pywinauto import Desktop  # noqa: E402

stop_flag = False
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def on_press(key):
    global stop_flag
    if key == Key.esc:
        stop_flag = True
        return False


# ---------- 0. контроль фокуса окна и раскладки ----------

def get_fg():
    return user32.GetForegroundWindow()


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def focus(hwnd):
    """Возвращает фокус на окно. True, если получилось."""
    try:
        if user32.IsIconic(hwnd):       # разворачиваем только свёрнутое окно
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)
    if get_fg() == hwnd:
        return True
    try:  # запасной вариант, если Windows не дал сменить окно
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)
    return get_fg() == hwnd


def get_lang(hwnd):
    """'ru', 'en' или 'other' - текущая раскладка в окне."""
    try:
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        lid = user32.GetKeyboardLayout(tid) & 0xFFFF
        return {0x419: "ru", 0x409: "en"}.get(lid, "other")
    except Exception:
        return "other"


# ---------- 2. чтение текста из окна (UI Automation) ----------

def find_window():
    for backend in ("uia", "win32"):
        try:
            win = Desktop(backend=backend).window(title_re=WINDOW_TITLE_RE)
            win.wait("exists", timeout=3)
            return win
        except Exception:
            continue
    return None


def element_texts(ctrl):
    texts = []
    for getter in (lambda: ctrl.window_text(), lambda: ctrl.get_value()):
        try:
            v = getter()
            if v:
                texts.append(v)
        except Exception:
            pass
    try:
        lp = ctrl.legacy_properties()
        for k in ("Value", "Name"):
            if lp.get(k):
                texts.append(lp[k])
    except Exception:
        pass
    return [t.strip() for t in dict.fromkeys(texts) if t and t.strip()]


def uia_read(win):
    """Ищет в окне самый длинный текст (кроме полей ввода)."""
    best = ""
    try:
        controls = win.descendants()
    except Exception:
        return ""
    for c in controls:
        try:
            info = c.element_info
            if "Edit" in str(getattr(info, "control_type", "")) or "Edit" in str(getattr(info, "class_name", "")):
                continue
        except Exception:
            pass
        for t in element_texts(c):
            if len(t) > len(best):
                best = t
    return best if len(best) >= 15 else ""


# ---------- 3. резервный способ: OCR ----------

def find_tesseract():
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for p in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ):
        if os.path.exists(p):
            return p
    return None


def ensure_tesseract():
    exe = find_tesseract()
    if not exe:
        print("Tesseract OCR не найден. Пробую установить через winget (может появиться окно подтверждения)...")
        try:
            subprocess.call(
                ["winget", "install", "-e", "--id", "UB-Mannheim.TesseractOCR",
                 "--accept-package-agreements", "--accept-source-agreements"]
            )
        except FileNotFoundError:
            pass
        exe = find_tesseract()
    if not exe:
        print("\nНе удалось установить Tesseract автоматически.")
        print("Скачай и установи вручную: https://github.com/UB-Mannheim/tesseract/wiki")
        print("Потом запусти скрипт снова.")
        sys.exit(1)

    os.makedirs(TESSDATA_DIR, exist_ok=True)
    for lang in ("rus", "eng"):
        path = os.path.join(TESSDATA_DIR, f"{lang}.traineddata")
        if not os.path.exists(path):
            print(f"Скачиваю языковой пакет '{lang}' ...")
            urllib.request.urlretrieve(
                f"https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata", path
            )
    pytesseract.pytesseract.tesseract_cmd = exe


def countdown(label, seconds):
    print(label)
    for i in range(seconds, 0, -1):
        if stop_flag:
            return False
        print(f"  ...{i}")
        time.sleep(1)
    return True


def load_region():
    if os.path.exists(REGION_FILE):
        with open(REGION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    print("\n=== Выбор области с текстом упражнения ===")
    print("Выделяй ТОЛЬКО одну строку с текстом, который надо печатать.")
    print("Не захватывай рамку, курсор слева и соседние надписи.")
    print("Переключись в Solo (Alt+Tab) и не кликай - только наводи мышь.")
    countdown(f"Наведи мышь на ЛЕВЫЙ ВЕРХНИЙ угол текста упражнения ({REGION_DELAY} сек):", REGION_DELAY)
    x1, y1 = pyautogui.position()
    print(f"Левый верхний угол записан: {x1}, {y1}\n")
    countdown(f"Теперь наведи мышь на ПРАВЫЙ НИЖНИЙ угол текста ({REGION_DELAY} сек):", REGION_DELAY)
    x2, y2 = pyautogui.position()
    print(f"Правый нижний угол записан: {x2}, {y2}\n")
    region = {
        "left": min(x1, x2), "top": min(y1, y2),
        "width": abs(x2 - x1), "height": abs(y2 - y1),
    }
    if region["width"] < 10 or region["height"] < 10:
        print("Область слишком маленькая, попробуй ещё раз.")
        return load_region()
    with open(REGION_FILE, "w", encoding="utf-8") as f:
        json.dump(region, f)
    print("Область сохранена (чтобы выбрать заново - удали файл region.json).\n")
    return region


def clean_text(text):
    """Убирает мусор OCR: рамки, палки, лишние символы."""
    sep = {"enter": "\n", "space": " ", "none": ""}.get(NEWLINE_AS, "")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n+", "\n", text).strip("\n")
    text = text.replace("\n", sep)
    text = re.sub(r"[^0-9A-Za-zА-Яа-яЁё .,!?;:\-()\"'\n]", "", text)
    text = re.sub(r" {2,}", " ", text)
    text = text.strip()
    if FORCE_LOWERCASE:
        text = text.lower()
    return text


def ocr_read(region, save_debug=False):
    with mss.mss() as sct:
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    img = ImageOps.grayscale(img)
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    if sum(img.getdata()) / (img.width * img.height) < 110:
        img = ImageOps.invert(img)
    if save_debug:
        img.save(DEBUG_IMG)
    os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
    psm = 7 if region["height"] < 45 else 6   # 7 = одна строка текста
    text = pytesseract.image_to_string(img, lang="rus+eng", config=f"--psm {psm}")
    return clean_text(text)


# ---------- 4. ввод как физическая клавиатура (скан-коды) ----------

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short), ("wParamH", ctypes.c_ushort)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SC_SHIFT, SC_SPACE, SC_BACKSPACE = 0x2A, 0x39, 0x0E


def _send(sc, up=False, vk=0):
    flags = (0 if vk else KEYEVENTF_SCANCODE) | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=1, u=_INPUTUNION(ki=KEYBDINPUT(vk, sc, flags, 0, None)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap_vk(vk, sc):
    """Нажатие как обычной клавиши (код клавиши + скан-код) - для пробела и Enter."""
    _send(sc, False, vk)
    time.sleep(random.uniform(0.035, 0.06))
    _send(sc, True, vk)


def tap(sc, shift=False):
    if shift:
        _send(SC_SHIFT)
        time.sleep(0.01)
    _send(sc)
    time.sleep(random.uniform(0.012, 0.03))
    _send(sc, True)
    if shift:
        time.sleep(0.01)
        _send(SC_SHIFT, True)


def _row(chars, start):
    return {c: start + i for i, c in enumerate(chars)}


RU_KEYS = {}
RU_KEYS.update(_row("йцукенгшщзхъ", 0x10))
RU_KEYS.update(_row("фывапролджэ", 0x1E))
RU_KEYS["ё"] = 0x29
RU_KEYS.update(_row("ячсмитьбю", 0x2C))

EN_KEYS = {}
EN_KEYS.update(_row("qwertyuiop", 0x10))
EN_KEYS.update(_row("asdfghjkl", 0x1E))
EN_KEYS.update(_row("zxcvbnm", 0x2C))

PUNCT_RU = {".": (0x35, False), ",": (0x35, True), "?": (0x08, True), "!": (0x02, True),
            ";": (0x05, True), ":": (0x07, True), "-": (0x0C, False), '"': (0x03, True),
            "(": (0x0A, True), ")": (0x0B, True)}
PUNCT_EN = {".": (0x34, False), ",": (0x33, False), "?": (0x35, True), "!": (0x02, True),
            ";": (0x27, False), ":": (0x27, True), "-": (0x0C, False), '"': (0x28, True),
            "'": (0x28, False), "(": (0x0A, True), ")": (0x0B, True)}


def char_to_key(ch, lang):
    """(скан-код, shift) или None, если символ нельзя набрать в текущей раскладке."""
    if ch == " ":
        return (SC_SPACE, False)
    if ch.isdigit() and ch.isascii():
        return (0x0B if ch == "0" else 0x01 + int(ch), False)
    low = ch.lower()
    shift = ch != low
    table = RU_KEYS if lang == "ru" else EN_KEYS
    if low in table:
        return (table[low], shift)
    return (PUNCT_RU if lang == "ru" else PUNCT_EN).get(ch)


NEARBY = {
    "а": "оыпр", "б": "юьл", "в": "аыуц", "г": "нртш", "д": "лорп",
    "е": "нргш", "ж": "здлэ", "з": "хжьэ", "и": "тьмс", "й": "цукф",
    "к": "уеалв", "л": "дбож", "м": "иьст", "н": "гешо", "о": "рапл",
    "п": "адрго", "р": "птгед", "с": "мивуч", "т": "иьгре", "у": "квцй",
    "ф": "йцяч", "х": "зжю", "ц": "йфув", "ч": "сяхф", "ш": "гещ",
    "щ": "шзй", "ъ": "хэ", "ы": "авфп", "ь": "лбим", "э": "жзъ",
    "ю": "бьл", "я": "фчус",
    "a": "sqwz", "b": "vghn", "c": "xdfv", "d": "sfer", "e": "wrd",
    "f": "dgrt", "g": "fhty", "h": "gjyu", "i": "uok", "j": "hkui",
    "k": "jlio", "l": "kop", "m": "nj", "n": "bhjm", "o": "ipl",
    "p": "ol", "q": "wa", "r": "etf", "s": "adwx", "t": "ryg",
    "u": "yij", "v": "cfb", "w": "qes", "x": "zsc", "y": "tuh", "z": "xas",
}


def wrong_char(ch):
    if random.random() >= ERROR_RATE:
        return None
    pool = NEARBY.get(ch.lower())
    if not pool:
        return None
    w = random.choice(pool)
    return w.upper() if ch.isupper() else w


def press_char(ctl, ch, lang):
    if ch == " ":
        tap_vk(0x20, 0x39)
        return
    if ch == "\n":
        tap_vk(0x0D, 0x1C)
        return
    key = char_to_key(ch, lang)
    if key:
        tap(key[0], key[1])
    else:
        ctl.type(ch)  # запасной вариант: Unicode-ввод


def type_text(ctl, text, target, lang):
    """Печатает текст, но только пока активно нужное окно."""
    for idx, ch in enumerate(text):
        if stop_flag:
            return False
        if get_fg() != target:
            now = get_fg()
            print(f"\nФокус ушёл из Solo на символе №{idx} ('{text[idx - 1] if idx else ''}' было напечатано последним).")
            print(f"Сейчас активно окно: '{window_title(now)}'")
            if not focus(target):
                print("Вернуть фокус не удалось. Останавливаюсь, чтобы не печатать в чужое окно.")
                return False
        w = wrong_char(ch)
        if w:
            press_char(ctl, w, lang)
            time.sleep(0.08)
            if ERROR_BACKSPACE:
                tap(SC_BACKSPACE)
                time.sleep(random.uniform(0.03, 0.08))
        press_char(ctl, ch, lang)
        d = random.uniform(MIN_DELAY, MAX_DELAY)
        if ch in " .,!?":
            d += random.uniform(0.05, 0.25)
        time.sleep(d)
    return True


# ---------- 5. главная логика ----------

def main():
    test_mode = "--test" in sys.argv
    print("=== SOLO AUTO ===" + ("  [РЕЖИМ ПРОВЕРКИ: ничего не печатается]" if test_mode else ""))
    win = find_window()
    reader = None

    if win is not None and not test_mode:
        print("Окно Solo найдено, пробую прочитать текст напрямую...")
        if uia_read(win):
            print("Текст читается напрямую из окна - режим UIA.\n")
            reader = lambda: uia_read(win)  # noqa: E731

    if reader is None:
        print("Использую распознавание с экрана (OCR).")
        ensure_tesseract()
        region = load_region()
        reader = lambda: ocr_read(region, save_debug=test_mode)  # noqa: E731

    kb.Listener(on_press=on_press, daemon=True).start()

    if test_mode:
        print("\nПереключись в Solo (Alt+Tab), пусть упражнение будет на экране.")
        countdown(f"Читаю через {STARTUP_DELAY} сек:", STARTUP_DELAY)
        for i in range(1, 4):
            print(f"Чтение {i}: {reader()!r}")
            time.sleep(1)
        print(f"\nКартинка, которую видит OCR, сохранена: {DEBUG_IMG}")
        print("Если текст распознан неверно - удали region.json и выбери область точнее (одна строка, без рамок).")
        return

    ctl = Controller()
    print("\nСейчас перейди в Solo (Alt+Tab), включи нужную раскладку и КЛИКНИ в поле ввода. Остановка - Esc.")
    if not countdown(f"Старт через {STARTUP_DELAY} сек:", STARTUP_DELAY):
        return

    target = get_fg()
    console = kernel32.GetConsoleWindow()
    if target == console or not target:
        print("\nАктивно окно консоли, а не Solo. Ты не успел переключиться и кликнуть в Solo.")
        print("Запусти скрипт снова и увеличь STARTUP_DELAY в настройках.")
        return

    lang = get_lang(target)
    print(f"Печатать буду в окно: '{window_title(target)}'  (раскладка: {lang})\n")

    ok = True
    for n in range(1, MAX_ROUNDS + 1):
        if stop_flag:
            break
        if get_fg() != target and not focus(target):
            print("Не удалось вернуть фокус на окно Solo, остановка.")
            ok = False
            break
        text = reader()
        if not text:
            print(f"Раунд {n}: текст не найден, остановка.")
            ok = False
            break

        has_cyr = bool(re.search(r"[А-Яа-яЁё]", text))
        lang = get_lang(target)
        if has_cyr and lang != "ru":
            print(f"Текст русский, а в Solo сейчас раскладка '{lang}'.")
            print("Включи русскую раскладку (Alt+Shift или Win+Пробел) и запусти скрипт снова.")
            ok = False
            break

        print(f"Раунд {n}: {len(text)} симв., пробелов: {text.count(' ')}, переносов: {text.count(chr(10))}")
        print(f"Текст: {text[:80]!r}")
        print("Печатаю...")
        if not type_text(ctl, text, target, lang):
            ok = False
            break
        time.sleep(ROUND_PAUSE)

    if stop_flag:
        print("Остановлено.")
    else:
        print("Готово." if ok else "Завершено досрочно (см. сообщения выше).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
