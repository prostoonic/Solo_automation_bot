import queue
import tkinter as tk
from tkinter import ttk, messagebox

import config
from keyboard_bot import KeyboardBot
from models import BotSettings
from parser import load_exercises


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Соло на клавиатуре Bot")
        self.exercises = []
        self.bot: KeyboardBot | None = None
        self.queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._load_exercises()
        self._poll_queue()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        ttk.Label(main, text="Урок:").grid(row=0, column=0, sticky="w", pady=2)
        self.lesson_combobox = ttk.Combobox(main, state="readonly", width=60)
        self.lesson_combobox.grid(row=0, column=1, sticky="ew", pady=2)
        self.lesson_combobox.bind("<<ComboboxSelected>>", self._on_lesson_selected)

        ttk.Label(main, text="Скорость (CPM):").grid(row=1, column=0, sticky="w", pady=2)
        self.speed_var = tk.StringVar(value=str(config.DEFAULT_SPEED))
        ttk.Entry(main, textvariable=self.speed_var, width=15).grid(
            row=1, column=1, sticky="w", pady=2
        )

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
        self.start_btn = ttk.Button(btn_frame, text="Старт", command=self._on_start)
        self.start_btn.grid(row=0, column=0, padx=5)
        self.stop_btn = ttk.Button(
            btn_frame, text="Стоп", command=self._on_stop, state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, padx=5)

        ttk.Label(main, text="Статус:").grid(row=3, column=0, sticky="w", pady=2)
        self.status_label = ttk.Label(main, text="Готово")
        self.status_label.grid(row=3, column=1, sticky="w", pady=2)

        ttk.Label(main, text="Прогресс:").grid(row=4, column=0, sticky="w", pady=2)
        self.progress_bar = ttk.Progressbar(main, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=4, column=1, sticky="ew", pady=2)

        self.typed_label = ttk.Label(main, text="Символов: 0 / 0")
        self.typed_label.grid(row=5, column=1, sticky="w", pady=2)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_exercises(self) -> None:
        try:
            self.exercises = load_exercises(config.XML_PATH)
            if not self.exercises:
                raise ValueError("В XML не найдено ни одного упражнения.")
            self.lesson_combobox["values"] = [ex.display_name for ex in self.exercises]
            self.lesson_combobox.current(0)
            self._on_lesson_selected()
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось загрузить XML: {exc}")
            self.status_label.config(text="Ошибка")

    def _on_lesson_selected(self, event=None) -> None:
        idx = self.lesson_combobox.current()
        if 0 <= idx < len(self.exercises):
            ex = self.exercises[idx]
            self.progress_bar["maximum"] = len(ex.text)
            self.progress_bar["value"] = 0
            self.typed_label.config(text=f"Символов: 0 / {len(ex.text)}")

    def _on_start(self) -> None:
        if self.bot and self.bot.thread and self.bot.thread.is_alive():
            return

        idx = self.lesson_combobox.current()
        if idx < 0:
            messagebox.showwarning("Внимание", "Выберите урок.")
            return

        ex = self.exercises[idx]
        if not ex.text.strip():
            messagebox.showerror("Ошибка", "Выбранный урок пуст.")
            return

        try:
            cpm = float(self.speed_var.get())
            if cpm <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Некорректная скорость.")
            return

        settings = BotSettings(cpm=cpm)
        self.bot = KeyboardBot(ex, settings, self.queue)
        self.bot.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress_bar["maximum"] = len(ex.text)
        self.progress_bar["value"] = 0
        self.typed_label.config(text=f"Символов: 0 / {len(ex.text)}")
        self.status_label.config(text="Запуск")

    def _on_stop(self) -> None:
        if self.bot:
            self.bot.stop()
            self.status_label.config(text="Остановлено")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")

    def _poll_queue(self) -> None:
        while True:
            try:
                msg, data = self.queue.get_nowait()
            except queue.Empty:
                break

            if msg == "status":
                self.status_label.config(text=data["text"])
            elif msg == "progress":
                self.progress_bar["value"] = data["typed"]
                self.typed_label.config(
                    text=f"Символов: {data['typed']} / {data['total']}"
                )
            elif msg == "finished":
                self.status_label.config(text="Завершено")
                self.start_btn.config(state="normal")
                self.stop_btn.config(state="disabled")
            elif msg == "stopped":
                self.status_label.config(text="Остановлено")
                self.start_btn.config(state="normal")
                self.stop_btn.config(state="disabled")
            elif msg == "error_msg":
                messagebox.showerror("Ошибка", data["text"])

        self.root.after(100, self._poll_queue)

    def _on_close(self) -> None:
        if self.bot:
            self.bot.stop()
        self.root.destroy()