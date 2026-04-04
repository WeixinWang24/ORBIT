"""Mock-driven ORBIT web workbench shell.

This module is intentionally isolated from the current runtime and from the
existing `orbit.web_inspector` implementation.

Layout direction for this shell borrows from the current Vio app's web UI
language: topbar + left navigation + central work area + right operational rail.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .mock_adapter import MockOrbitInterfaceAdapter
from .style_vio import VIO_INSPIRED_WORKBENCH_CSS


def _render_page(session_id: str | None, tab: str) -> str:
    adapter = MockOrbitInterfaceAdapter()
    sessions = adapter.list_sessions()
    approvals = adapter.list_open_approvals()
    current = adapter.get_session(session_id) if session_id else (sessions[0] if sessions else None)
    if current is None:
        session_links = '<div class="empty">No sessions.</div>'
        main = '<div class="empty">No session selected.</div>'
        side = '<div class="empty">No details.</div>'
        title = 'No session selected'
        status_chip = '<span class="chip">mock-adapter</span>'
    else:
        title = current.session_id
        status_chip = f'<span class="chip">{escape(current.status)}</span><span class="chip">{escape(current.backend_name)}</span><span class="chip">{escape(current.model)}</span>'
        session_links = "".join(
            f'<a class="session-link {"active" if s.session_id == current.session_id else ""}" href="/?session_id={escape(s.session_id)}&tab={escape(tab)}">'
            f'<div class="session-title">{escape(s.session_id)}</div>'
            f'<div class="meta">{escape(s.status)} · {escape(s.updated_at.isoformat())}</div>'
            f'<div class="meta">{escape(s.last_message_preview)}</div></a>'
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
                f'<div class="panel-block"><div class="message-role">{escape(item.event_type)}</div><pre>{escape(json.dumps(item.payload, indent=2, ensure_ascii=False))}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No events.</div>'
        elif tab == "tool_calls":
            blocks = adapter.list_tool_calls(current.session_id)
            inner = "".join(
                f'<div class="panel-block"><div><strong>{escape(item.tool_name)}</strong> '
                f'<span class="badge {"ok" if item.status == "completed" else "warn"}">{escape(item.status)}</span></div>'
                f'<div class="meta">{escape(item.summary)}</div><pre>{escape(json.dumps(item.payload, indent=2, ensure_ascii=False))}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No tool calls.</div>'
        elif tab == "artifacts":
            blocks = adapter.list_artifacts(current.session_id)
            inner = "".join(
                f'<div class="panel-block"><div><strong>{escape(item.artifact_type)}</strong></div><div class="meta">source={escape(item.source)}</div><pre>{escape(item.content)}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No artifacts.</div>'
        else:
            blocks = adapter.list_messages(current.session_id)
            inner = "".join(
                f'<div class="message-card"><div class="message-role">{escape(item.role)}{(" · " + escape(item.message_kind)) if item.message_kind else ""}</div><pre>{escape(item.content)}</pre></div>'
                for item in blocks
            ) or '<div class="empty">No transcript.</div>'
        main = f'<div class="tabs">{tab_html}</div><div class="main-panel">{inner}</div>'
        approval_html = "".join(
            f'<div class="panel-block"><div><strong>{escape(a.tool_name)}</strong> <span class="badge warn">{escape(a.status)}</span></div><div class="meta">{escape(a.summary)}</div><div class="meta">session={escape(a.session_id)}</div></div>'
            for a in approvals
        ) or '<div class="empty">No approvals.</div>'
        event_count = len(adapter.list_events(current.session_id))
        tool_call_count = len(adapter.list_tool_calls(current.session_id))
        side = (
            f'<div class="panel-block"><div><strong>{escape(current.session_id)}</strong></div>'
            f'<div class="meta">conversation={escape(current.conversation_id)}</div>'
            f'<div class="meta">backend={escape(current.backend_name)} · model={escape(current.model)}</div>'
            f'<div class="meta">messages={current.message_count} · events={event_count} · tool_calls={tool_call_count}</div></div>'
            f'<div class="panel-block"><div><strong>Current status</strong></div><div class="meta">{escape(current.status)}</div></div>'
            f'<div><h3 class="section-title">Open Approvals</h3>{approval_html}</div>'
        )
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ORBIT Mock Workbench</title><style>{VIO_INSPIRED_WORKBENCH_CSS}</style></head><body><div class="dashboard"><div class="topbar card"><div class="brand"><h1>ORBIT Mock Workbench</h1><p>Vio-inspired isolated shell · runtime disconnected</p></div><div class="topbar-right">{status_chip}<span class="chip">mock data</span></div></div><aside class="sidebar card"><h2 class="section-title">Sessions</h2>{session_links}</aside><main class="main card"><h2 class="section-title">Main View · {escape(title)}</h2>{main}</main><section class="right"><div class="card"><div class="section-title">Session Summary</div><div style="padding:0 14px 14px;">{side}</div></div></section></div></body></html>'''


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
