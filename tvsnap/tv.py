"""TradingView snapshots via the already opened Chrome (CDP)."""
import logging
import re
import time
from typing import Callable, Optional

import pyperclip
from playwright.sync_api import Page, sync_playwright

log = logging.getLogger("tvsnap.tv")

SNAPSHOT_RE = re.compile(r"https://www\.tradingview\.com/x/[A-Za-z0-9]+/?")

# Internal TV API; used only to read/verify the current interval, never to change it.
JS_GET_RESOLUTION = """
() => {
  try { return window.TradingViewApi.activeChart().resolution(); } catch (e) {}
  try {
    const b = document.querySelector('#header-toolbar-intervals button[aria-checked="true"]');
    if (b) return b.getAttribute('data-value') || b.textContent.trim();
  } catch (e) {}
  return null;
}
"""

JS_BLUR_INPUTS = """
() => {
  const el = document.activeElement;
  if (el && /^(INPUT|TEXTAREA)$/.test(el.tagName)) el.blur();
}
"""

JS_IS_VISIBLE = "() => document.visibilityState === 'visible'"


class TVError(Exception):
    pass


# Status callback: (tf, state, detail). state: "working" | "ok" | "fail"
StatusCb = Callable[[str, str, str], None]


def normalize_tf(tf: Optional[str]) -> str:
    """'1W'/'W' -> 'W', '1D'/'D' -> 'D', '240' -> '240'."""
    if not tf:
        return ""
    tf = str(tf).strip().upper()
    m = re.fullmatch(r"1([A-Z])", tf)
    return m.group(1) if m else tf


def typed_tf(tf: str) -> str:
    """TV opens the interval dialog only on a digit; a leading letter would open symbol search."""
    tf = str(tf).strip()
    return tf if tf[:1].isdigit() else "1" + tf


def find_chart_page(browser) -> Page:
    pages = [p for ctx in browser.contexts for p in ctx.pages
             if "tradingview.com/chart" in (p.url or "")]
    if not pages:
        raise TVError("Нет открытой вкладки tradingview.com/chart в Chrome")
    for p in pages:
        try:
            if p.evaluate(JS_IS_VISIBLE):
                return p
        except Exception:
            continue
    return pages[0]


def _wait_clipboard_link(timeout: float) -> Optional[str]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            text = pyperclip.paste() or ""
        except Exception:
            text = ""
        m = SNAPSHOT_RE.search(text)
        if m:
            return m.group(0)
        time.sleep(0.2)
    return None


class TVSnapper:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _resolution(self, page: Page) -> Optional[str]:
        try:
            return page.evaluate(JS_GET_RESOLUTION)
        except Exception:
            return None

    def _set_tf(self, page: Page, tf: str) -> None:
        tf = typed_tf(tf)
        page.evaluate(JS_BLUR_INPUTS)
        page.keyboard.type(tf, delay=60)
        time.sleep(0.4)
        page.keyboard.press("Enter")
        # Verify switch when the internal API is available; otherwise just rely on the delay.
        target = normalize_tf(tf)
        end = time.monotonic() + 3
        while time.monotonic() < end:
            cur = self._resolution(page)
            if cur is None or normalize_tf(cur) == target:
                break
            time.sleep(0.2)
        else:
            log.warning("TF %s: график показывает %s после переключения", tf, self._resolution(page))
        time.sleep(float(self.cfg.get("load_delay_sec", 2)))

    def _snapshot(self, page: Page) -> Optional[str]:
        timeout = float(self.cfg.get("snapshot_timeout_sec", 10))
        attempts = 1 + int(self.cfg.get("snapshot_retries", 1))
        for attempt in range(1, attempts + 1):
            pyperclip.copy("")
            page.evaluate(JS_BLUR_INPUTS)
            page.keyboard.press("Alt+s")
            link = _wait_clipboard_link(timeout)
            if link:
                return link
            log.warning("Снапшот: нет ссылки в буфере (попытка %d/%d)", attempt, attempts)
            page.keyboard.press("Escape")
        return None

    def run(self, on_status: Optional[StatusCb] = None) -> dict:
        """Returns {tf: link}; failed TFs are absent."""
        on_status = on_status or (lambda *a: None)
        results: dict = {}
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(self.cfg["cdp_url"])
            except Exception as e:
                raise TVError(f"Не удалось подключиться к Chrome ({self.cfg['cdp_url']}). "
                              f"Запусти chrome_tv.bat. {e}") from e
            page = find_chart_page(browser)
            log.info("Вкладка: %s", page.url)

            # Pretend the page is focused so TV can write to the clipboard while our window is active.
            cdp = page.context.new_cdp_session(page)
            try:
                cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            except Exception as e:
                log.warning("Focus emulation недоступна: %s", e)
            try:
                page.bring_to_front()
            except Exception:
                pass

            original = self._resolution(page)
            log.info("Исходный ТФ: %s", original)
            try:
                for item in self.cfg["timeframes"]:
                    tf = item["tf"]
                    on_status(tf, "working", "")
                    try:
                        self._set_tf(page, tf)
                        link = self._snapshot(page)
                    except Exception as e:
                        log.exception("TF %s: ошибка", tf)
                        on_status(tf, "fail", str(e))
                        continue
                    if link:
                        results[tf] = link
                        log.info("TF %s: %s", tf, link)
                        on_status(tf, "ok", link)
                    else:
                        on_status(tf, "fail", "нет ссылки")
            finally:
                if original:
                    try:
                        self._set_tf(page, str(original))
                        log.info("Вернул ТФ %s", original)
                    except Exception:
                        log.exception("Не удалось вернуть исходный ТФ")
                else:
                    log.warning("Исходный ТФ не определён — не возвращаю")
                try:
                    cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": False})
                    cdp.detach()
                except Exception:
                    pass
            # Leaving the context manager disconnects without closing the user's Chrome.
        return results
