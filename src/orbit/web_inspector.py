from __future__ import annotations

import argparse
import json
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from orbit.settings import DEFAULT_DB_PATH, DEFAULT_WORKSPACE_ROOT
from orbit.store.sqlite_store import SQLiteStore

VIO_INSPIRED_CSS = """
:root {
  --bg: #050510;
  --panel: #121222;
  --text: #BFE8FF;
  --text-dim: #7FC8E8;
  --cyan: #00FFC6;
  --pink: #FF2E88;
  --radius: 14px;
  --shadow-cyan: 0 0 0 1px rgba(0,255,198,.18), 0 0 18px rgba(0,255,198,.08);
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; width: 100%; min-height: 100%; color-scheme: dark;
  background:
    linear-gradient(180deg, rgba(122,0,255,.06), transparent 30%),
    radial-gradient(circle at top right, rgba(0,255,198,.06), transparent 24%),
    radial-gradient(circle at bottom left, rgba(255,46,136,.05), transparent 24%),
    var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 18px;
}
body { overflow: hidden; }
.dashboard {
  width: calc(100vw - 24px);
  height: calc(100vh - 24px);
  margin: 12px;
  display: grid;
  gap: 14px;
  grid-template-columns: 300px minmax(0, 1fr) 420px;
  grid-template-rows: 56px minmax(0, 1fr);
  grid-template-areas:
    'top top top'
    'sidebar main right';
}
.card {
  background: linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.01));
  border: 1px solid rgba(0,255,198,.18);
  border-radius: var(--radius);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 0 0 1px rgba(0,255,198,.08);
  backdrop-filter: blur(10px);
}
.topbar { grid-area: top; padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; }
.brand h1 { margin: 0; font-size: 22px; text-transform: uppercase; letter-spacing: .12em; color: #D59BFF; }
.brand p { margin: 4px 0 0; color: var(--text-dim); font-size: 16px; letter-spacing: .06em; text-transform: uppercase; }
.sidebar, .main, .right { min-height: 0; overflow: auto; padding: 14px; }
.sidebar { grid-area: sidebar; }
.main { grid-area: main; display: flex; flex-direction: column; }
.right { grid-area: right; display: grid; gap: 14px; grid-template-rows: repeat(4, minmax(180px, 1fr)); }
.section-title { margin: 0 0 12px; font-size: 16px; letter-spacing: .12em; text-transform: uppercase; color: var(--cyan); }
.session-link {
  display: block; padding: 10px 12px; margin-bottom: 8px; text-decoration: none; color: var(--text);
  border: 1px solid rgba(0,255,198,.14); border-radius: 12px; background: rgba(18,18,34,.68);
}
.session-link.active { box-shadow: var(--shadow-cyan); border-color: rgba(0,255,198,.32); }
.tabbar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.tab {
  display: inline-flex; align-items: center; padding: 10px 14px; border-radius: 999px; text-decoration: none;
  border: 1px solid rgba(0,255,198,.18); color: var(--text-dim); background: rgba(18,18,34,.72); font-size: 16px;
}
.tab.active { color: var(--text); box-shadow: var(--shadow-cyan); border-color: rgba(0,255,198,.30); }
.main-panel { min-height: 0; overflow: auto; flex: 1; }
.meta { color: var(--text-dim); font-size: 16px; }
.message-card { margin-bottom: 12px; padding: 16px; border-radius: 12px; border: 1px solid rgba(0,255,198,.12); background: rgba(18,18,34,.75); }
.message-role { font-size: 16px; letter-spacing: .10em; text-transform: uppercase; color: var(--pink); margin-bottom: 8px; }
pre {
  margin: 0; white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 16px; line-height: 1.7;
}
.panel-block { padding: 16px; border-radius: 12px; border: 1px solid rgba(0,255,198,.12); background: rgba(18,18,34,.75); overflow: auto; }
.fragment-card { margin-bottom: 12px; padding: 14px; border-radius: 12px; border: 1px solid rgba(0,255,198,.12); background: rgba(18,18,34,.75); }
.fragment-title { font-size: 16px; color: var(--cyan); margin: 0 0 8px; letter-spacing: .08em; text-transform: uppercase; }
.fragment-meta { color: var(--text-dim); font-size: 14px; margin-bottom: 8px; }
.empty { color: var(--text-dim); font-style: italic; }
.chip { padding: 8px 12px; border-radius: 999px; border: 1px solid rgba(255,46,136,.22); color: #ffd1e6; font-size: 16px; }
"""


def _render_context_panel(context_data: dict | None) -> str:
    if not context_data:
        return '<div class="panel-block"><div class="empty">No context assembly snapshot available.</div></div>'

    fragments_html = []
    for key, title in [
        ("instruction_fragments", "Instruction Fragments"),
        ("history_context_fragments", "History Context Fragments"),
        ("auxiliary_context_fragments", "Auxiliary Context Fragments"),
        ("runtime_only_fragments", "Runtime-only Fragments"),
    ]:
        fragments = context_data.get(key) or []
        if not fragments:
            continue
        section_blocks = []
        for fragment in fragments:
            section_blocks.append(
                f'<div class="fragment-card">'
                f'<h3 class="fragment-title">{escape(str(fragment.get("fragment_name", "fragment")))}</h3>'
                f'<div class="fragment-meta">scope={escape(str(fragment.get("visibility_scope", "unknown")))} · priority={escape(str(fragment.get("priority", 0)))}</div>'
                f'<pre>{escape(str(fragment.get("content", "")))}</pre>'
                f'</div>'
            )
        fragments_html.append(f'<div class="panel-block"><h2 class="section-title">{title}</h2>{"".join(section_blocks)}</div>')

    projection_hints = context_data.get("projection_hints") or {}
    effective_instructions = context_data.get("effective_instructions") or ""
    projected_input = context_data.get("projected_input") or []

    fragments_html.append(
        f'<div class="panel-block"><h2 class="section-title">Effective Instructions</h2><pre>{escape(str(effective_instructions))}</pre></div>'
    )
    fragments_html.append(
        f'<div class="panel-block"><h2 class="section-title">Projection Hints</h2><pre>{escape(json.dumps(projection_hints, indent=2, ensure_ascii=False))}</pre></div>'
    )
    fragments_html.append(
        f'<div class="panel-block"><h2 class="section-title">Projected Input Preview</h2><pre>{escape(json.dumps(projected_input, indent=2, ensure_ascii=False))}</pre></div>'
    )
    return ''.join(fragments_html)


def _render_main_panel(*, active_tab: str, transcript_items: list[str], payload_json: str, context_data: dict | None) -> str:
    if active_tab == "payload":
        return f'<div class="panel-block"><pre>{escape(payload_json)}</pre></div>'
    if active_tab == "context":
        return _render_context_panel(context_data)
    return ''.join(transcript_items)


def _html_page(*, sessions, current_session, transcript, events, artifacts, metadata, active_tab: str):
    def esc(x):
        return escape(str(x))

    current_session_id = current_session.session_id if current_session is not None else None

    session_items = []
    for session in sessions:
        sid = session.session_id
        active = current_session_id is not None and sid == current_session_id
        klass = "session-link active" if active else "session-link"
        session_items.append(
            f'<a class="{klass}" href="/?session_id={esc(sid)}&tab={esc(active_tab)}"><div>{esc(sid)}</div><div class="meta">{esc(session.updated_at.isoformat())}</div></a>'
        )
    if not session_items:
        session_items.append('<div class="empty">No sessions found.</div>')

    transcript_items = []
    for message in transcript:
        role = getattr(message.role, "value", str(message.role))
        kind = message.metadata.get("message_kind") if isinstance(message.metadata, dict) else None
        role_label = role if not kind else f"{role} ({kind})"
        transcript_items.append(
            f'<div class="message-card"><div class="message-role">{esc(role_label)}</div><pre>{esc(message.content)}</pre></div>'
        )
    if not transcript_items:
        transcript_items.append('<div class="empty">No transcript yet.</div>')

    event_json = json.dumps(
        [
            {
                "event_type": getattr(event.event_type, "value", str(event.event_type)),
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
            }
            for event in events
        ],
        indent=2,
        ensure_ascii=False,
    )

    artifact_json = json.dumps(
        [
            {
                "artifact_type": artifact.artifact_type,
                "source": artifact.source,
                "content": artifact.content,
            }
            for artifact in artifacts
        ],
        indent=2,
        ensure_ascii=False,
    )

    metadata_json = json.dumps(metadata, indent=2, ensure_ascii=False)
    payload_json = (
        json.dumps(metadata.get("last_provider_payload"), indent=2, ensure_ascii=False)
        if metadata.get("last_provider_payload") is not None
        else "No payload snapshot available."
    )
    context_data = metadata.get("last_context_assembly")

    title = current_session_id or "No session selected"
    transcript_tab_class = "tab active" if active_tab == "transcript" else "tab"
    payload_tab_class = "tab active" if active_tab == "payload" else "tab"
    context_tab_class = "tab active" if active_tab == "context" else "tab"

    transcript_href = f"/?session_id={esc(title)}&tab=transcript" if current_session_id else "/?tab=transcript"
    payload_href = f"/?session_id={esc(title)}&tab=payload" if current_session_id else "/?tab=payload"
    context_href = f"/?session_id={esc(title)}&tab=context" if current_session_id else "/?tab=context"

    main_panel_html = _render_main_panel(
        active_tab=active_tab,
        transcript_items=transcript_items,
        payload_json=payload_json,
        context_data=context_data,
    )

    summary_json = json.dumps(
        {
            "workspace_root": str(DEFAULT_WORKSPACE_ROOT),
            "workspace_prompt": str(DEFAULT_WORKSPACE_ROOT / "PROMPT.md"),
            "last_context_assembly": metadata.get("last_context_assembly"),
            "last_provider_payload": metadata.get("last_provider_payload"),
            "last_auth_failure": metadata.get("last_auth_failure"),
        },
        indent=2,
        ensure_ascii=False,
    )

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>ORBIT Inspector</title>
  <style>{VIO_INSPIRED_CSS}</style>
</head>
<body>
  <div class=\"dashboard\">
    <div class=\"topbar card\">
      <div class=\"brand\">
        <h1>ORBIT Inspector</h1>
        <p>Vio-inspired local workbench for session transcript, context, payload, events, and metadata</p>
      </div>
      <div class=\"chip\">SQLite: {esc(DEFAULT_DB_PATH)}</div>
      <div class=\"chip\">Workspace: {esc(DEFAULT_WORKSPACE_ROOT)}</div>
    </div>
    <aside class=\"sidebar card\">
      <h2 class=\"section-title\">Sessions</h2>
      {''.join(session_items)}
    </aside>
    <main class=\"main card\">
      <h2 class=\"section-title\">Main View · {esc(title)}</h2>
      <div class=\"tabbar\">
        <a class=\"{transcript_tab_class}\" href=\"{transcript_href}\">Transcript</a>
        <a class=\"{payload_tab_class}\" href=\"{payload_href}\">Payload</a>
        <a class=\"{context_tab_class}\" href=\"{context_href}\">Context</a>
      </div>
      <div class=\"main-panel\">{main_panel_html}</div>
    </main>
    <section class=\"right\">
      <div class=\"card panel-block\"><h2 class=\"section-title\">Session Metadata</h2><pre>{esc(metadata_json)}</pre></div>
      <div class=\"card panel-block\"><h2 class=\"section-title\">Runtime Events</h2><pre>{esc(event_json)}</pre></div>
      <div class=\"card panel-block\"><h2 class=\"section-title\">Artifacts</h2><pre>{esc(artifact_json)}</pre></div>
      <div class=\"card panel-block\"><h2 class=\"section-title\">Latest Context/Payload Summary</h2><pre>{esc(summary_json)}</pre></div>
    </section>
  </div>
</body>
</html>"""


class InspectorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        store = SQLiteStore(DEFAULT_DB_PATH)
        sessions = list(reversed(store.list_sessions()))
        query = parse_qs(parsed.query)
        session_id = query.get("session_id", [None])[0]
        active_tab = query.get("tab", ["transcript"])[0]
        if active_tab not in {"transcript", "payload", "context"}:
            active_tab = "transcript"

        current_session = None
        if session_id:
            current_session = store.get_session(session_id)
        elif sessions:
            current_session = sessions[0]

        transcript = store.list_messages_for_session(current_session.session_id) if current_session else []
        events = store.list_events_for_run(current_session.conversation_id) if current_session else []
        artifacts = store.list_context_for_run(current_session.conversation_id) if current_session else []
        metadata = current_session.metadata if current_session is not None else {}

        html = _html_page(
            sessions=sessions,
            current_session=current_session,
            transcript=transcript,
            events=events,
            artifacts=artifacts,
            metadata=metadata,
            active_tab=active_tab,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def serve(host: str = "127.0.0.1", port: int = 8789, open_browser: bool = False) -> None:
    httpd = ThreadingHTTPServer((host, port), InspectorHandler)
    url = f"http://{host}:{port}"
    print(f"ORBIT inspector listening on {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ORBIT local web inspector")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=args.open_browser)
