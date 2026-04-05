from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _preview_snippet(value: str, *, limit: int = 80) -> str:
    preview = value.replace("\n", "\\n")
    return preview[:limit] + ("…" if len(preview) > limit else "")


def _mutation_summary_from_tool_data(tool_data: dict | None) -> str | None:
    if not isinstance(tool_data, dict):
        return None
    mutation_kind = tool_data.get("mutation_kind")
    if not mutation_kind:
        return None
    parts: list[str] = [str(mutation_kind)]
    path = tool_data.get("path")
    if path:
        parts.append(str(path))
    replacement_count = tool_data.get("replacement_count")
    if replacement_count is not None:
        parts.append(f"replacement_count={replacement_count}")
    match_count = tool_data.get("match_count")
    if match_count is not None:
        parts.append(f"match_count={match_count}")
    failure_layer = tool_data.get("failure_layer")
    if failure_layer:
        parts.append(f"failure_layer={failure_layer}")
    write_readiness = tool_data.get("write_readiness") if isinstance(tool_data.get("write_readiness"), dict) else {}
    readiness_reason = write_readiness.get("reason")
    if readiness_reason:
        parts.append(f"reason={readiness_reason}")
    return " · ".join(parts)


def _mutation_detail_html(tool_data: dict | None) -> str:
    if not isinstance(tool_data, dict):
        return ""
    mutation_kind = tool_data.get("mutation_kind")
    if not mutation_kind:
        return ""
    blocks: list[str] = []
    before_excerpt = tool_data.get("before_excerpt")
    after_excerpt = tool_data.get("after_excerpt")
    if isinstance(before_excerpt, str) and before_excerpt:
        blocks.append(
            '<div class="tool-call-reason"><strong>before</strong>: ' + escape(_preview_snippet(before_excerpt)) + '</div>'
        )
    if isinstance(after_excerpt, str) and after_excerpt:
        blocks.append(
            '<div class="tool-call-reason"><strong>after</strong>: ' + escape(_preview_snippet(after_excerpt)) + '</div>'
        )
    return ''.join(blocks)

from orbit.memory import MemoryService
from orbit.settings import DEFAULT_DB_PATH, DEFAULT_INSPECTOR_HOST, DEFAULT_INSPECTOR_PORT, DEFAULT_WORKSPACE_ROOT
from orbit.store.sqlite_store import SQLiteStore

VIO_INSPIRED_CSS = """
:root {
  --bg: #050510;
  --panel: #121222;
  --text: #BFE8FF;
  --text-dim: #7FC8E8;
  --cyan: #00FFC6;
  --pink: #FF2E88;
  --green: #3CFF9F;
  --amber: #FFCC66;
  --red: #FF6B8A;
  --violet: #B388FF;
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
.message-card.toolish { border-color: rgba(179,136,255,.38); background: linear-gradient(180deg, rgba(179,136,255,.10), rgba(18,18,34,.78)); box-shadow: 0 0 0 1px rgba(179,136,255,.12); }
.message-card.toolish.tool-ok { border-color: rgba(60,255,159,.30); background: linear-gradient(180deg, rgba(60,255,159,.08), rgba(18,18,34,.78)); }
.message-card.toolish.tool-fail { border-color: rgba(255,107,138,.30); background: linear-gradient(180deg, rgba(255,107,138,.08), rgba(18,18,34,.78)); }
.message-card.toolish.policy { border-color: rgba(255,204,102,.30); background: linear-gradient(180deg, rgba(255,204,102,.08), rgba(18,18,34,.78)); }
.message-card.toolish.approval-request { border-color: rgba(0,255,198,.30); background: linear-gradient(180deg, rgba(0,255,198,.08), rgba(18,18,34,.78)); }
.message-card.toolish.approval-decision { border-color: rgba(179,136,255,.32); background: linear-gradient(180deg, rgba(179,136,255,.10), rgba(18,18,34,.78)); }
.message-role { font-size: 16px; letter-spacing: .10em; text-transform: uppercase; color: var(--pink); margin-bottom: 8px; }
.message-card.toolish .message-role { color: var(--violet); }
.message-summary { margin-bottom: 10px; color: var(--text); font-size: 15px; line-height: 1.5; }
.message-meta-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.message-chip { padding: 6px 10px; border-radius: 999px; font-size: 13px; border: 1px solid rgba(0,255,198,.16); color: var(--text-dim); }
.message-chip.ok { border-color: rgba(60,255,159,.34); color: var(--green); }
.message-chip.fail { border-color: rgba(255,107,138,.34); color: var(--red); }
.message-chip.policy { border-color: rgba(255,204,102,.34); color: var(--amber); }
.tool-call-card.success .fragment-title { color: var(--green); }
.tool-call-card.failed .fragment-title { color: var(--red); }
.tool-call-status-badge { display: inline-flex; align-items: center; margin-left: 8px; padding: 4px 8px; border-radius: 999px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; border: 1px solid rgba(0,255,198,.18); color: var(--text-dim); }
.tool-call-status-badge.success { border-color: rgba(60,255,159,.34); color: var(--green); }
.tool-call-status-badge.failed { border-color: rgba(255,107,138,.34); color: var(--red); }
.tool-call-reason { margin: 0 0 8px; color: var(--text); font-size: 14px; }
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


def _format_local_timestamp(value) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return value
    else:
        return str(value)
    if dt.tzinfo is None:
        return dt.isoformat()
    return dt.astimezone().isoformat()


def _truncate_text(value: str, *, limit: int = 220) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[: limit - 1].rstrip() + "…", True


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
    assembly_meta = {
        "assembly_version": context_data.get("assembly_version"),
        "workspace_prompt_source": context_data.get("workspace_prompt_source"),
        "workspace_prompt_sha1": context_data.get("workspace_prompt_sha1"),
    }

    fragments_html.append(
        f'<div class="panel-block"><h2 class="section-title">Assembly Metadata</h2><pre>{escape(json.dumps(assembly_meta, indent=2, ensure_ascii=False))}</pre></div>'
    )
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


def _render_tool_calls_panel(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return '<div class="panel-block"><div class="empty">No tool calls recorded for this session.</div></div>'
    blocks = []
    for tool_call in tool_calls:
        status = str(tool_call.get("status", "unknown"))
        css = "success" if status == "completed" else "failed" if status == "failed" else ""
        result_payload = tool_call.get("result_payload") if isinstance(tool_call.get("result_payload"), dict) else {}
        failure_reason = None
        mutation_summary = None
        mutation_detail_html = ""
        if result_payload:
            result_data = result_payload.get("data", {}) if isinstance(result_payload.get("data"), dict) else {}
            failure_reason = result_payload.get("content") or result_data.get("reason")
            mutation_summary = _mutation_summary_from_tool_data(result_data)
            mutation_detail_html = _mutation_detail_html(result_data)
        summary_html = f'<div class="tool-call-reason">{escape(str(mutation_summary))}</div>' if mutation_summary else ""
        reason_html = f'<div class="tool-call-reason">{escape(str(failure_reason))}</div>' if failure_reason and status != "completed" else ""
        badge_class = "success" if status == "completed" else "failed" if status == "failed" else ""
        badge_html = f'<span class="tool-call-status-badge {badge_class}">{escape(status)}</span>' if badge_class else f'<span class="tool-call-status-badge">{escape(status)}</span>'
        blocks.append(
            f'<div class="fragment-card tool-call-card {css}">'
            f'<h3 class="fragment-title">{escape(str(tool_call.get("tool_name", "tool")))}{badge_html}</h3>'
            f'<div class="fragment-meta">requires_approval={escape(str(tool_call.get("requires_approval", False)))} · side_effect_class={escape(str(tool_call.get("side_effect_class", "unknown")))}</div>'
            f'{summary_html}'
            f'{mutation_detail_html}'
            f'{reason_html}'
            f'<pre>{escape(json.dumps(tool_call, indent=2, ensure_ascii=False))}</pre>'
            f'</div>'
        )
    return '<div class="panel-block"><h2 class="section-title">Tool Invocations</h2>' + ''.join(blocks) + '</div>'


def _render_memory_panel(*, memory_records: list[dict], memory_embeddings: list[dict], retrieval_query: str, retrieval_results: list[dict], backend_plan: dict | None = None, memory_top_k: int = 10, memory_scope: str = "all") -> str:
    records_html = []
    for record in memory_records:
        records_html.append(
            f'<div class="fragment-card">'
            f'<h3 class="fragment-title">{escape(str(record.get("memory_type", "memory")))} · {escape(str(record.get("memory_id", "unknown")))}</h3>'
            f'<div class="fragment-meta">scope={escape(str(record.get("scope", "unknown")))} · session_id={escape(str(record.get("session_id", "")))} · updated_at={escape(str(record.get("updated_at", "")))} · promotion_strategy={escape(str((record.get("metadata") or {}).get("promotion_strategy", "")))} · embedding_status={escape(str((record.get("metadata") or {}).get("embedding_status", "")))}</div>'
            f'<pre>{escape(json.dumps(record, indent=2, ensure_ascii=False))}</pre>'
            f'</div>'
        )
    embeddings_html = []
    for embedding in memory_embeddings:
        embeddings_html.append(
            f'<div class="fragment-card">'
            f'<h3 class="fragment-title">embedding · {escape(str(embedding.get("memory_id", "unknown")))}</h3>'
            f'<div class="fragment-meta">model={escape(str(embedding.get("model_name", "unknown")))} · dim={escape(str(embedding.get("embedding_dim", 0)))} · created_at={escape(str(embedding.get("created_at", "")))}</div>'
            f'<pre>{escape(json.dumps(embedding, indent=2, ensure_ascii=False))}</pre>'
            f'</div>'
        )
    retrieval_blocks = []
    for result in retrieval_results:
        retrieval_blocks.append(
            f'<div class="fragment-card">'
            f'<h3 class="fragment-title">retrieval · hybrid={escape(str(result.get("score", 0.0)))}</h3>'
            f'<div class="fragment-meta">memory_id={escape(str(result.get("memory_id", "unknown")))} · scope={escape(str(result.get("memory_scope", "unknown")))} · model={escape(str(result.get("embedding_model", "unknown")))} · semantic={escape(str(result.get("semantic_score", 0.0)))} · lexical={escape(str(result.get("lexical_score", 0.0)))}</div>'
            f'<pre>{escape(json.dumps(result, indent=2, ensure_ascii=False))}</pre>'
            f'</div>'
        )
    retrieval_html = ''.join(retrieval_blocks) if retrieval_blocks else '<div class="empty">No retrieval results for current query.</div>'
    records_html_joined = ''.join(records_html) if records_html else '<div class="empty">No canonical memory records.</div>'
    embeddings_html_joined = ''.join(embeddings_html) if embeddings_html else '<div class="empty">No memory embeddings.</div>'
    return (
        '<div class="panel-block"><h2 class="section-title">Canonical Memory Records</h2>' + records_html_joined + '</div>'
        + '<div class="panel-block"><h2 class="section-title">Memory Embeddings</h2>' + embeddings_html_joined + '</div>'
        + '<div class="panel-block"><h2 class="section-title">Retrieval Probe</h2>'
        + '<form method="GET" style="margin-bottom:12px; display:grid; gap:8px;">'
        + '<input type="hidden" name="tab" value="memory" />'
        + f'<input type="hidden" name="session_id" value="{escape(str((memory_records[0].get("session_id") if memory_records else "") or ""))}" />'
        + f'<label class="fragment-meta">query <input name="memory_query" value="{escape(retrieval_query or "")}" style="width:100%; margin-top:4px; background:#121222; color:#BFE8FF; border:1px solid rgba(0,255,198,.18); border-radius:8px; padding:8px;" /></label>'
        + f'<label class="fragment-meta">top-k <input name="memory_top_k" value="{memory_top_k}" style="width:100%; margin-top:4px; background:#121222; color:#BFE8FF; border:1px solid rgba(0,255,198,.18); border-radius:8px; padding:8px;" /></label>'
        + '<label class="fragment-meta">scope <select name="memory_scope" style="width:100%; margin-top:4px; background:#121222; color:#BFE8FF; border:1px solid rgba(0,255,198,.18); border-radius:8px; padding:8px;">'
        + f'<option value="all"{" selected" if memory_scope == "all" else ""}>all</option>'
        + f'<option value="durable"{" selected" if memory_scope == "durable" else ""}>durable</option>'
        + f'<option value="session"{" selected" if memory_scope == "session" else ""}>session</option>'
        + '</select></label>'
        + '<button type="submit" style="background:#121222; color:#00FFC6; border:1px solid rgba(0,255,198,.25); border-radius:8px; padding:8px 12px;">Run Probe</button>'
        + '</form>'
        + f'<div class="fragment-meta">query={escape(retrieval_query or "")} · top_k={memory_top_k} · scope={escape(memory_scope)}</div>'
        + (f'<div class="fragment-meta">backend={escape(str((backend_plan or {}).get("backend", "unknown")))} · strategy={escape(str((backend_plan or {}).get("strategy", "unknown")))} · notes={escape(str((backend_plan or {}).get("notes", "")))}</div>' if backend_plan else '')
        + retrieval_html
        + '</div>'
    )


def _render_main_panel(*, active_tab: str, transcript_items: list[str], payload_json: str, context_data: dict | None, tool_calls: list[dict], memory_records: list[dict], memory_embeddings: list[dict], retrieval_query: str, retrieval_results: list[dict], backend_plan: dict | None = None, memory_top_k: int = 10, memory_scope: str = "all") -> str:
    if active_tab == "payload":
        return f'<div class="panel-block"><pre>{escape(payload_json)}</pre></div>'
    if active_tab == "context":
        return _render_context_panel(context_data)
    if active_tab == "tool_calls":
        return _render_tool_calls_panel(tool_calls)
    if active_tab == "memory":
        return _render_memory_panel(
            memory_records=memory_records,
            memory_embeddings=memory_embeddings,
            retrieval_query=retrieval_query,
            retrieval_results=retrieval_results,
            backend_plan=backend_plan,
            memory_top_k=memory_top_k,
            memory_scope=memory_scope,
        )
    return ''.join(transcript_items)


def _html_page(*, sessions, current_session, transcript, events, artifacts, metadata, tool_calls, active_tab: str, memory_records: list[dict], memory_embeddings: list[dict], retrieval_query: str, retrieval_results: list[dict], backend_plan: dict | None = None, memory_top_k: int = 10, memory_scope: str = "all"):
    def esc(x):
        return escape(str(x))

    current_session_id = current_session.session_id if current_session is not None else None

    session_items = []
    for session in sessions:
        sid = session.session_id
        active = current_session_id is not None and sid == current_session_id
        klass = "session-link active" if active else "session-link"
        session_items.append(
            f'<a class="{klass}" href="/?session_id={esc(sid)}&tab={esc(active_tab)}"><div>{esc(sid)}</div><div class="meta">{esc(_format_local_timestamp(session.updated_at))}</div></a>'
        )
    if not session_items:
        session_items.append('<div class="empty">No sessions found.</div>')

    transcript_items = []
    toolish_kinds = {"tool_result", "policy_decision", "approval_request", "approval_decision", "guardrail_block", "policy_caution", "policy_termination"}
    for message in transcript:
        role = getattr(message.role, "value", str(message.role))
        kind = message.metadata.get("message_kind") if isinstance(message.metadata, dict) else None
        role_label = role if not kind else f"{role} ({kind})"
        if kind in toolish_kinds:
            tool_name = message.metadata.get("tool_name") if isinstance(message.metadata, dict) else None
            classes = ["message-card", "toolish"]
            chips = []
            preview_source = message.content or ""
            if kind == "tool_result":
                ok = bool(message.metadata.get("tool_ok")) if isinstance(message.metadata, dict) else False
                classes.append("tool-ok" if ok else "tool-fail")
                status_class = "ok" if ok else "fail"
                status_label = "success" if ok else "failed"
                chips.append(f'<span class="message-chip {status_class}">{status_label}</span>')
                tool_data = message.metadata.get("tool_data") if isinstance(message.metadata, dict) else None
                raw_result = tool_data.get("raw_result") if isinstance(tool_data, dict) else None
                structured = raw_result.get("structuredContent") if isinstance(raw_result, dict) else None
                current_tool_data = tool_data if isinstance(tool_data, dict) else None
                mutation_summary = _mutation_summary_from_tool_data(current_tool_data)
                mutation_detail_text = []
                if isinstance(current_tool_data, dict):
                    if isinstance(current_tool_data.get("before_excerpt"), str) and current_tool_data.get("before_excerpt"):
                        mutation_detail_text.append("before=" + _preview_snippet(current_tool_data.get("before_excerpt")))
                    if isinstance(current_tool_data.get("after_excerpt"), str) and current_tool_data.get("after_excerpt"):
                        mutation_detail_text.append("after=" + _preview_snippet(current_tool_data.get("after_excerpt")))
                if mutation_summary:
                    preview_source = mutation_summary + (("\n" + "\n".join(mutation_detail_text)) if mutation_detail_text else "")
                elif isinstance(structured, dict):
                    preview_source = json.dumps(structured, ensure_ascii=False)
            elif kind == "approval_request":
                classes.append("approval-request")
                chips.append('<span class="message-chip">approval request</span>')
            elif kind == "approval_decision":
                classes.append("approval-decision")
                chips.append('<span class="message-chip">approval decision</span>')
            elif kind.startswith("policy_") or kind == "guardrail_block":
                classes.append("policy")
                chips.append('<span class="message-chip policy">policy</span>')
            summary, was_truncated = _truncate_text(preview_source)
            if tool_name:
                chips.append(f'<span class="message-chip">tool={esc(tool_name)}</span>')
            if kind == "policy_decision" and isinstance(message.metadata, dict):
                reason = message.metadata.get("reason")
                outcome = message.metadata.get("outcome")
                if reason:
                    chips.append(f'<span class="message-chip policy">reason={esc(reason)}</span>')
                if outcome:
                    chips.append(f'<span class="message-chip policy">outcome={esc(outcome)}</span>')
            if was_truncated:
                chips.append('<span class="message-chip">truncated</span>')
            class_attr = " ".join(classes)
            chips_html = "".join(chips)
            metadata_json = json.dumps(message.metadata, indent=2, ensure_ascii=False)
            transcript_items.append(
                f'<div class="{class_attr}">'
                f'<div class="message-role">{esc(role_label)}</div>'
                f'<div class="message-meta-row">{chips_html}</div>'
                f'<div class="message-summary">{esc(summary)}</div>'
                f'<pre>{esc(metadata_json)}</pre>'
                f'</div>'
            )
        else:
            transcript_items.append(
                f'<div class="message-card"><div class="message-role">{esc(role_label)}</div><pre>{esc(message.content)}</pre></div>'
            )
    if not transcript_items:
        transcript_items.append('<div class="empty">No transcript yet.</div>')

    event_json = json.dumps(
        [
            {
                "event_type": getattr(event.event_type, "value", str(event.event_type)),
                "timestamp": _format_local_timestamp(event.timestamp),
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
    tool_calls_tab_class = "tab active" if active_tab == "tool_calls" else "tab"
    memory_tab_class = "tab active" if active_tab == "memory" else "tab"

    transcript_href = f"/?session_id={esc(title)}&tab=transcript" if current_session_id else "/?tab=transcript"
    payload_href = f"/?session_id={esc(title)}&tab=payload" if current_session_id else "/?tab=payload"
    context_href = f"/?session_id={esc(title)}&tab=context" if current_session_id else "/?tab=context"
    tool_calls_href = f"/?session_id={esc(title)}&tab=tool_calls" if current_session_id else "/?tab=tool_calls"
    memory_href = f"/?session_id={esc(title)}&tab=memory" if current_session_id else "/?tab=memory"

    main_panel_html = _render_main_panel(
        active_tab=active_tab,
        transcript_items=transcript_items,
        payload_json=payload_json,
        context_data=context_data,
        tool_calls=tool_calls,
        memory_records=memory_records,
        memory_embeddings=memory_embeddings,
        retrieval_query=retrieval_query,
        retrieval_results=retrieval_results,
        backend_plan=backend_plan,
        memory_top_k=memory_top_k,
        memory_scope=memory_scope,
    )

    summary_json = json.dumps(
        {
            "workspace_root": str(DEFAULT_WORKSPACE_ROOT),
            "workspace_prompt": str(DEFAULT_WORKSPACE_ROOT / "PROMPT.md"),
            "assembly_version": (context_data or {}).get("assembly_version"),
            "workspace_prompt_source": (context_data or {}).get("workspace_prompt_source"),
            "workspace_prompt_sha1": (context_data or {}).get("workspace_prompt_sha1"),
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
        <a class=\"{tool_calls_tab_class}\" href=\"{tool_calls_href}\">Tool Calls</a>
        <a class=\"{memory_tab_class}\" href=\"{memory_href}\">Memory</a>
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
        if active_tab not in {"transcript", "payload", "context", "tool_calls", "memory"}:
            active_tab = "transcript"

        current_session = None
        if session_id:
            current_session = store.get_session(session_id)
        elif sessions:
            current_session = sessions[0]

        transcript = store.list_messages_for_session(current_session.session_id) if current_session else []
        events = store.list_events_for_run(current_session.conversation_id) if current_session else []
        artifacts = store.list_context_for_run(current_session.conversation_id) if current_session else []
        tool_invocations = store.list_tool_invocations_for_run(current_session.conversation_id) if current_session else []
        tool_calls = [tool.model_dump(mode="json") for tool in tool_invocations]
        memory_service = MemoryService(store=store)
        memory_records_raw = store.list_memory_records(session_id=current_session.session_id, limit=200) if current_session else []
        memory_embeddings_raw = []
        if current_session:
            memory_ids = [record.memory_id for record in memory_records_raw]
            for memory_id in memory_ids:
                memory_embeddings_raw.extend(store.list_memory_embeddings(memory_id=memory_id))
        retrieval_query = query.get("memory_query", [""])[0]
        memory_scope = query.get("memory_scope", ["all"])[0]
        try:
            memory_top_k = max(1, min(int(query.get("memory_top_k", ["10"])[0]), 50))
        except Exception:
            memory_top_k = 10
        probe = memory_service.probe_memory_retrieval(
            session_id=current_session.session_id if current_session else None,
            query_text=retrieval_query,
            limit=memory_top_k,
            scope=memory_scope,
        )
        backend_plan_obj = probe.get("backend_plan")
        backend_plan = {
            "backend": getattr(backend_plan_obj, "backend", "unknown"),
            "strategy": getattr(backend_plan_obj, "strategy", "unknown"),
            "notes": getattr(backend_plan_obj, "notes", ""),
        }
        retrieval_results = list(probe.get("results", []))
        memory_records = [record.model_dump(mode="json") for record in memory_records_raw]
        memory_embeddings = [embedding.model_dump(mode="json") for embedding in memory_embeddings_raw]
        metadata = current_session.metadata if current_session is not None else {}
        if isinstance(metadata, dict) and isinstance(metadata.get("filesystem_read_state"), dict):
            metadata = dict(metadata)
            metadata["filesystem_read_state_summary"] = {
                path: {
                    "source_tool": state.get("source_tool"),
                    "grounding_kind": state.get("grounding_kind"),
                    "path_kind": state.get("path_kind"),
                    "is_partial_view": state.get("is_partial_view"),
                    "observed_modified_at_epoch": state.get("observed_modified_at_epoch"),
                    "observed_size_bytes": state.get("observed_size_bytes"),
                }
                for path, state in metadata.get("filesystem_read_state", {}).items()
                if isinstance(state, dict)
            }

        html = _html_page(
            sessions=sessions,
            current_session=current_session,
            transcript=transcript,
            events=events,
            artifacts=artifacts,
            metadata=metadata,
            tool_calls=tool_calls,
            active_tab=active_tab,
            memory_records=memory_records,
            memory_embeddings=memory_embeddings,
            retrieval_query=retrieval_query,
            retrieval_results=retrieval_results,
            backend_plan=backend_plan,
            memory_top_k=memory_top_k,
            memory_scope=memory_scope,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


def serve(host: str = DEFAULT_INSPECTOR_HOST, port: int = DEFAULT_INSPECTOR_PORT, open_browser: bool = False) -> None:
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
    parser.add_argument("--host", default=DEFAULT_INSPECTOR_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_INSPECTOR_PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=args.open_browser)
