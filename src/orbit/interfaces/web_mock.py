"""Mock-driven ORBIT web workbench shell.

This module is intentionally isolated from the current runtime and from the
existing `orbit.web_inspector` implementation.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .mock_adapter import MockOrbitInterfaceAdapter

CSS = """
:root {
  --bg: #0b0e17;
  --panel: #151a26;
  --border: #283245;
  --text: #dbe7ff;
  --muted: #8ca0c6;
  --accent: #7ce2ff;
  --accent2: #b690ff;
  --ok: #67e8a5;
  --warn: #ffcf70;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, system-ui, sans-serif; background: var(--bg); color: var(--text); }
.layout { display: grid; grid-template-columns: 280px 1fr 360px; gap: 14px; min-height: 100vh; padding: 14px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }
.title { margin: 0 0 12px; color: var(--accent); letter-spacing: .08em; text-transform: uppercase; font-size: 14px; }
.session { display: block; text-decoration: none; color: var(--text); border: 1px solid var(--border); border-radius: 12px; padding: 10px; margin-bottom: 8px; }
.session.active { border-color: var(--accent); }
.meta { color: var(--muted); font-size: 13px; }
.message { border: 1px solid var(--border); border-radius: 12px; padding: 12px; margin-bottom: 10px; }
.message .role { color: var(--accent2); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }
pre { white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, monospace; font-size: 13px; }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tab { text-decoration: none; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 8px 12px; }
.tab.active { color: var(--text); border-color: var(--accent); }
.badge { display: inline-block; padding: 4px 8px; border-radius: 999px; border: 1px solid var(--border); font-size: 12px; color: var(--muted); }
.badge.ok { color: var(--ok); }
.badge.warn { color: var(--warn); }
.smallblock { border: 1px solid var(--border); border-radius: 12px; padding: 12px; margin-bottom: 10px; }
.empty { color: var(--muted); font-style: italic; }
"""


def _render_page(session_id: str | None, tab: str) -> str:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    current = adapter.get_session(session_id) if session_id else (sessions[0] if sessions else None)
    if current is None:
        session_links = '<div class="empty">No sessions.</div>'
        main = '<div class="empty">No session selected.</div>'
        side = '<div class="empty">No details.</div>'
    else:
        session_links = "".join(
            f'<a class="session {"active" if s.session_id == current.session_id else ""}" href="/?session_id={escape(s.session_id)}&tab={escape(tab)}">'
            f'<div>{escape(s.session_id)}</div><div class="meta">{escape(s.status)} · {escape(s.updated_at.isoformat())}</div></a>'
            for s in sessions
        )
        tabs = ["transcript", "events", "tool_calls", "artifacts"]
        tab_html = "".join(
            f'<a class="tab {"active" if name == tab else ""}" href="/?session_id={escape(current.session_id)}&tab={escape(name)}">{escape(name)}</a>'
            for name in tabs
        )
        if tab == "events":
            blocks = adapter.list_events(current.session_id)
            inner = "".join(
                f'<div class="smallblock"><div class="role">{escape(item.event_type)}</div><pre>{escape(json.dumps(item.payload, indent=2, ensure_ascii=False))}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No events.</div>'
        elif tab == "tool_calls":
            blocks = adapter.list_tool_calls(current.session_id)
            inner = "".join(
                f'<div class="smallblock"><div><strong>{escape(item.tool_name)}</strong> '
                f'<span class="badge {"ok" if item.status == "completed" else "warn"}">{escape(item.status)}</span></div>'
                f'<div class="meta">{escape(item.summary)}</div><pre>{escape(json.dumps(item.payload, indent=2, ensure_ascii=False))}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No tool calls.</div>'
        elif tab == "artifacts":
            blocks = adapter.list_artifacts(current.session_id)
            inner = "".join(
                f'<div class="smallblock"><div><strong>{escape(item.artifact_type)}</strong></div><div class="meta">source={escape(item.source)}</div><pre>{escape(item.content)}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No artifacts.</div>'
        else:
            blocks = adapter.list_messages(current.session_id)
            inner = "".join(
                f'<div class="message"><div class="role">{escape(item.role)}{(" · " + escape(item.message_kind)) if item.message_kind else ""}</div><pre>{escape(item.content)}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No transcript.</div>'
        main = f'<div class="tabs">{tab_html}</div>{inner}'
        approvals = adapter.list_open_approvals()
        approval_html = "".join(
            f'<div class="smallblock"><div><strong>{escape(a.tool_name)}</strong> <span class="badge warn">{escape(a.status)}</span></div><div class="meta">{escape(a.summary)}</div></div>'
            for a in approvals
        ) or '<div class="empty">No approvals.</div>'
        side = (
            f'<div class="smallblock"><div><strong>{escape(current.session_id)}</strong></div>'
            f'<div class="meta">backend={escape(current.backend_name)} · model={escape(current.model)}</div>'
            f'<div class="meta">messages={current.message_count} · status={escape(current.status)}</div></div>'
            f'<h3 class="title">Open Approvals</h3>{approval_html}'
        )
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ORBIT Mock Workbench</title><style>{CSS}</style></head><body><div class="layout"><aside class="card"><h2 class="title">Sessions</h2>{session_links}</aside><main class="card"><h2 class="title">Mock Workbench</h2>{main}</main><section class="card"><h2 class="title">Session Summary</h2>{side}</section></div></body></html>'''


class MockWorkbenchHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        query = parse_qs(parsed.query)
        session_id = query.get("session_id", [None])[0]
        tab = query.get("tab", ["transcript"])[0]
        if tab not in {"transcript", "events", "tool_calls", "artifacts"}:
            tab = "transcript"
        html = _render_page(session_id=session_id, tab=tab).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def serve(host: str = "127.0.0.1", port: int = 8790, open_browser: bool = False) -> None:
    httpd = ThreadingHTTPServer((host, port), MockWorkbenchHandler)
    url = f"http://{host}:{port}"
    print(f"ORBIT mock workbench listening on {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ORBIT mock web workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=args.open_browser)
