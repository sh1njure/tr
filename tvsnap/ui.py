import logging
import queue
import threading
import webbrowser
from typing import Optional

import customtkinter as ctk

from .config import load_config, notion_token
from .notion_db import NotionDB, NotionError, Record
from .tv import TVError, TVSnapper

log = logging.getLogger("tvsnap.ui")

ANY_PAIR = "Любая"
COLORS = {"working": "#d6a100", "ok": "#2e9d4f", "fail": "#d04545", "idle": "gray60"}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title("TV Snapshot → Notion")
        self.geometry("620x560")
        self.q: queue.Queue = queue.Queue()
        self.db: Optional[NotionDB] = None
        self.record: Optional[Record] = None
        self.links: dict = {}

        pad = {"padx": 12, "pady": 6}

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", **pad)
        ctk.CTkLabel(top, text="Пара:").pack(side="left")
        self.pair = ctk.CTkSegmentedButton(top, values=list(self.cfg["pairs"]) + [ANY_PAIR])
        self.pair.set(self.cfg["pairs"][0] if self.cfg["pairs"] else ANY_PAIR)
        self.pair.pack(side="left", padx=8)
        self.run_btn = ctk.CTkButton(top, text="Снять и записать", command=self.on_run)
        self.run_btn.pack(side="right")

        self.tf_frame = ctk.CTkFrame(self)
        self.tf_frame.pack(fill="x", **pad)
        self.tf_labels = {}
        for i, item in enumerate(self.cfg["timeframes"]):
            ctk.CTkLabel(self.tf_frame, text=f"{item['tf']} → {item['column']}", width=90,
                         anchor="w").grid(row=i, column=0, sticky="w", padx=8, pady=2)
            lbl = ctk.CTkLabel(self.tf_frame, text="—", anchor="w", text_color=COLORS["idle"])
            lbl.grid(row=i, column=1, sticky="w", padx=8, pady=2)
            self.tf_labels[item["tf"]] = lbl

        prev = ctk.CTkFrame(self)
        prev.pack(fill="x", **pad)
        ctk.CTkLabel(prev, text="Запись в Notion:", anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.preview = ctk.CTkLabel(prev, text="—", anchor="w", justify="left", wraplength=580)
        self.preview.pack(fill="x", padx=8, pady=4)
        btns = ctk.CTkFrame(prev, fg_color="transparent")
        btns.pack(fill="x", padx=8, pady=(0, 8))
        self.confirm_btn = ctk.CTkButton(btns, text="Подтвердить", state="disabled", command=self.on_confirm)
        self.confirm_btn.pack(side="left")
        self.cancel_btn = ctk.CTkButton(btns, text="Отмена", state="disabled", fg_color="gray40",
                                        command=self.on_cancel)
        self.cancel_btn.pack(side="left", padx=8)

        self.link_lbl = ctk.CTkLabel(self, text="", text_color="#4a90e2", cursor="hand2", anchor="w")
        self.link_lbl.pack(fill="x", **pad)
        self.link_lbl.bind("<Button-1>", lambda e: self.link_lbl.cget("text") and
                           webbrowser.open(self.link_lbl.cget("text")))

        self.status = ctk.CTkTextbox(self, height=140, wrap="word")
        self.status.pack(fill="both", expand=True, **pad)

        self.after(100, self._poll)
        self._bg(self._startup_check)

    # ---------- thread plumbing ----------
    def _bg(self, fn, *args):
        def wrap():
            try:
                fn(*args)
            except Exception as e:
                log.exception("Ошибка")
                self._ui(self._set_status, f"Ошибка: {e}")
                self._ui(self._finish)
        threading.Thread(target=wrap, daemon=True).start()

    def _ui(self, fn, *args, **kwargs):
        self.q.put((fn, args, kwargs))

    def _poll(self):
        try:
            while True:
                fn, args, kwargs = self.q.get_nowait()
                fn(*args, **kwargs)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ---------- UI helpers (main thread) ----------
    def _set_status(self, text: str):
        self.status.delete("1.0", "end")
        self.status.insert("end", text)

    def _set_tf(self, tf: str, state: str, detail: str):
        text = {"working": "снимаю…", "ok": detail, "fail": f"пропущен: {detail}"}.get(state, detail)
        self.tf_labels[tf].configure(text=text, text_color=COLORS.get(state, COLORS["idle"]))

    def _finish(self):
        self.run_btn.configure(state="normal")
        self.confirm_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")

    def _get_db(self) -> NotionDB:
        if self.db is None:
            self.db = NotionDB(notion_token(), self.cfg)
        return self.db

    # ---------- workers ----------
    def _startup_check(self):
        db = self._get_db()
        problems = db.check_columns()
        if problems:
            self._ui(self._set_status,
                     "Колонки скринов не готовы:\n  " + "\n  ".join(problems) +
                     "\n\nСхема базы:\n" + db.schema_text())
        else:
            self._ui(self._set_status, "Готово. Notion OK.")

    def _run_worker(self, pair: Optional[str]):
        db = self._get_db()
        db._schema = None  # re-read schema in case columns were just created
        self._ui(self._set_status, "Ищу запись в Notion…")
        try:
            rec = db.find_latest(pair)
        except NotionError as e:
            self._ui(self._set_status, f"{e}\n\nСхема базы:\n{db.schema_text()}")
            self._ui(self._finish)
            return
        if not rec:
            self._ui(self._set_status, "Нет записи с пустыми колонками скринов" + (f" для {pair}" if pair else ""))
            self._ui(self._finish)
            return
        self.record = rec
        self._ui(self.preview.configure, text=rec.summary())
        self._ui(self._set_status, "Снимаю снапшоты…")
        try:
            links = TVSnapper(self.cfg).run(lambda tf, st, d: self._ui(self._set_tf, tf, st, d))
        except TVError as e:
            self._ui(self._set_status, str(e))
            self._ui(self._finish)
            return
        self.links = links
        missed = [t["tf"] for t in self.cfg["timeframes"] if t["tf"] not in links]
        if not links:
            self._ui(self._set_status, "Ни одного снапшота не получено — в Notion ничего не пишу.")
            self._ui(self._finish)
            return
        msg = f"Снято {len(links)}/{len(self.cfg['timeframes'])}."
        if missed:
            msg += f" Пропущены: {', '.join(missed)}."
        msg += "\nПроверь запись и нажми «Подтвердить»."
        self._ui(self._set_status, msg)
        self._ui(self.preview.configure, text=f"{rec.summary()}\n{rec.url}")
        self._ui(self.confirm_btn.configure, state="normal")
        self._ui(self.cancel_btn.configure, state="normal")

    def _write_worker(self):
        rec, links = self.record, self.links
        by_col = {t["column"]: links[t["tf"]] for t in self.cfg["timeframes"] if t["tf"] in links}
        written, skipped = self._get_db().write_links(rec.id, by_col)
        missed = [t["tf"] for t in self.cfg["timeframes"] if t["tf"] not in links]
        msg = f"Записано: {', '.join(written) or '—'}."
        if skipped:
            msg += f"\nНе перезаписаны (уже заполнены): {', '.join(skipped)}."
        if missed:
            msg += f"\nПропущенные ТФ: {', '.join(missed)}."
        self._ui(self._set_status, msg)
        self._ui(self.link_lbl.configure, text=rec.url)
        self._ui(self._finish)

    # ---------- handlers ----------
    def on_run(self):
        self.run_btn.configure(state="disabled")
        self.confirm_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.link_lbl.configure(text="")
        self.preview.configure(text="—")
        self.record, self.links = None, {}
        for tf in self.tf_labels:
            self._set_tf(tf, "idle", "—")
        pair = self.pair.get()
        self._bg(self._run_worker, None if pair == ANY_PAIR else pair)

    def on_confirm(self):
        self.confirm_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self._set_status("Пишу в Notion…")
        self._bg(self._write_worker)

    def on_cancel(self):
        self._set_status("Отменено, в Notion ничего не записано.")
        self._finish()
