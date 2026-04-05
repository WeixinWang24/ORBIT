from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

_MAX_CONSOLE_MESSAGES = 100
_MAX_CONSOLE_TEXT = 500

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - dependency may be absent in some environments
    sync_playwright = None


class BrowserManager:
    """Reusable browser manager for ORBIT browser capabilities.

    Current first-slice posture:
    - one browser runtime
    - one context
    - one active page
    - bounded snapshot/local interaction model
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._console_messages: list[dict[str, Any]] = []
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="orbit-browser")
        self._lock = Lock()

    def _artifact_dir(self) -> Path:
        path = self.workspace_root / ".orbit_browser"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _run(self, fn, *args, **kwargs):
        future = self._executor.submit(fn, *args, **kwargs)
        return future.result()

    def ensure_started(self) -> None:
        self._run(self._ensure_started_impl)

    def _ensure_started_impl(self) -> None:
        with self._lock:
            if sync_playwright is None:
                raise RuntimeError(
                    "Playwright is not available. Install the 'playwright' Python package and browser binaries before using browser tools."
                )
            if self._page is not None:
                return
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.on("console", self._handle_console_message)

    def _handle_console_message(self, message: Any) -> None:
        text = str(getattr(message, "text", "")() if callable(getattr(message, "text", None)) else getattr(message, "text", ""))
        level = str(getattr(message, "type", "")() if callable(getattr(message, "type", None)) else getattr(message, "type", "log"))
        record = {
            "level": level,
            "text": text[:_MAX_CONSOLE_TEXT],
        }
        self._console_messages.append(record)
        if len(self._console_messages) > _MAX_CONSOLE_MESSAGES:
            self._console_messages = self._console_messages[-_MAX_CONSOLE_MESSAGES:]

    def open(self, url: str) -> dict[str, Any]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")
        return self._run(self._open_impl, url)

    def _open_impl(self, url: str) -> dict[str, Any]:
        self._ensure_started_impl()
        assert self._page is not None
        self._page.goto(url, wait_until="load", timeout=10000)
        return {
            "url": self._page.url,
            "title": self._page.title(),
        }

    def snapshot(self) -> dict[str, Any]:
        return self._run(self._snapshot_impl)

    def _snapshot_impl(self) -> dict[str, Any]:
        self._ensure_started_impl()
        assert self._page is not None
        elements = self._page.evaluate(
            """
            () => {
              const candidates = Array.from(document.querySelectorAll('button, a, input, textarea, select, h1, h2, h3, h4, h5, h6, [role], [data-orbit-observe]'));
              const visible = candidates.filter((el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 0 && rect.height >= 0;
              });
              return visible.slice(0, 100).map((el, index) => {
                const orbitId = `e${index + 1}`;
                el.setAttribute('data-orbit-id', orbitId);
                const tag = (el.tagName || '').toLowerCase();
                const isTypeable = ['input', 'textarea'].includes(tag) || el.isContentEditable;
                const isClickable = ['button', 'a'].includes(tag) || el.getAttribute('role') === 'button' || !!el.onclick;
                return {
                  id: orbitId,
                  tag,
                  role: el.getAttribute('role') || '',
                  text: (el.innerText || el.textContent || '').trim().slice(0, 200),
                  label: el.getAttribute('aria-label') || '',
                  placeholder: el.getAttribute('placeholder') || '',
                  value: typeof el.value === 'string' ? el.value.slice(0, 200) : '',
                  visible: true,
                  enabled: !el.hasAttribute('disabled'),
                  clickable: isClickable,
                  typeable: isTypeable,
                };
              });
            }
            """
        )
        return {
            "url": self._page.url,
            "title": self._page.title(),
            "element_count": len(elements),
            "elements": elements,
        }

    def click(self, element_id: str) -> dict[str, Any]:
        if not isinstance(element_id, str) or not element_id.strip():
            raise ValueError("element_id must be a non-empty string")
        return self._run(self._click_impl, element_id)

    def _click_impl(self, element_id: str) -> dict[str, Any]:
        self._ensure_started_impl()
        assert self._page is not None
        locator = self._page.locator(f'[data-orbit-id="{element_id}"]').first
        if locator.count() == 0:
            raise ValueError("element_id not found in current snapshot")
        locator.click(timeout=5000)
        self._page.wait_for_load_state("load", timeout=5000)
        return {
            "element_id": element_id,
            "url": self._page.url,
            "title": self._page.title(),
        }

    def type(self, element_id: str, text: str) -> dict[str, Any]:
        if not isinstance(element_id, str) or not element_id.strip():
            raise ValueError("element_id must be a non-empty string")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return self._run(self._type_impl, element_id, text)

    def _type_impl(self, element_id: str, text: str) -> dict[str, Any]:
        self._ensure_started_impl()
        assert self._page is not None
        locator = self._page.locator(f'[data-orbit-id="{element_id}"]').first
        if locator.count() == 0:
            raise ValueError("element_id not found in current snapshot")
        locator.fill(text, timeout=5000)
        return {
            "element_id": element_id,
            "text_length": len(text),
            "url": self._page.url,
            "title": self._page.title(),
        }

    def console(self) -> dict[str, Any]:
        return self._run(self._console_impl)

    def _console_impl(self) -> dict[str, Any]:
        self._ensure_started_impl()
        return {
            "message_count": len(self._console_messages),
            "messages": list(self._console_messages),
        }

    def screenshot(self) -> dict[str, Any]:
        return self._run(self._screenshot_impl)

    def _screenshot_impl(self) -> dict[str, Any]:
        self._ensure_started_impl()
        assert self._page is not None
        filename = f"browser_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}.png"
        target = self._artifact_dir() / filename
        self._page.screenshot(path=str(target), full_page=True)
        return {
            "url": self._page.url,
            "title": self._page.title(),
            "path": str(target),
        }
