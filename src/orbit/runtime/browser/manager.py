from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - dependency may be absent in some environments
    sync_playwright = None


class BrowserManager:
    """Minimal runtime-local browser holder for ORBIT Browser Slice 0.1.

    First slice posture:
    - one browser runtime
    - one context
    - one active page
    - verification-oriented surface only (open / snapshot / screenshot)
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _artifact_dir(self) -> Path:
        path = self.workspace_root / ".orbit_browser"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_started(self) -> None:
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

    def open(self, url: str) -> dict[str, Any]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")
        self.ensure_started()
        assert self._page is not None
        self._page.goto(url, wait_until="load", timeout=10000)
        return {
            "url": self._page.url,
            "title": self._page.title(),
        }

    def snapshot(self) -> dict[str, Any]:
        self.ensure_started()
        assert self._page is not None
        elements = self._page.evaluate(
            """
            () => {
              const candidates = Array.from(document.querySelectorAll('button, a, input, textarea, select, h1, h2, h3, h4, h5, h6, [role]'));
              const visible = candidates.filter((el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.display !== 'none' && style.visibility !== 'hidden' && rect.width >= 0 && rect.height >= 0;
              });
              return visible.slice(0, 100).map((el, index) => ({
                id: `e${index + 1}`,
                tag: (el.tagName || '').toLowerCase(),
                role: el.getAttribute('role') || '',
                text: (el.innerText || el.textContent || '').trim().slice(0, 200),
                label: el.getAttribute('aria-label') || '',
                placeholder: el.getAttribute('placeholder') || '',
                visible: true,
                enabled: !el.hasAttribute('disabled'),
              }));
            }
            """
        )
        return {
            "url": self._page.url,
            "title": self._page.title(),
            "element_count": len(elements),
            "elements": elements,
        }

    def screenshot(self) -> dict[str, Any]:
        self.ensure_started()
        assert self._page is not None
        filename = f"browser_{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}.png"
        target = self._artifact_dir() / filename
        self._page.screenshot(path=str(target), full_page=True)
        return {
            "url": self._page.url,
            "title": self._page.title(),
            "path": str(target),
        }
