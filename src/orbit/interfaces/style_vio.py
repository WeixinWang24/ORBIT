"""Shared Vio-inspired presentation helpers for isolated ORBIT interfaces."""

VIO_INSPIRED_WORKBENCH_CSS = """
:root {
  --bg: #050510;
  --bg-soft: #0b1020;
  --panel: #121222;
  --panel-2: #17172a;
  --line: #2a2a44;
  --text: #BFE8FF;
  --text-dim: #7FC8E8;
  --cyan: #00FFC6;
  --pink: #FF2E88;
  --purple: #7A00FF;
  --yellow: #ffe66d;
  --green: #4dffb8;
  --radius: 14px;
  --sidebar-w: 260px;
  --rightbar-w: 320px;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
  min-height: 100%;
  color-scheme: dark;
  background:
    linear-gradient(180deg, rgba(122,0,255,.06), transparent 30%),
    radial-gradient(circle at top right, rgba(0,255,198,.06), transparent 24%),
    radial-gradient(circle at bottom left, rgba(255,46,136,.05), transparent 24%),
    var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
body { overflow: hidden; }
.dashboard {
  width: calc(100vw - 24px);
  height: calc(100vh - 24px);
  margin: 12px;
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(220px, var(--sidebar-w)) minmax(0, 1fr) minmax(260px, var(--rightbar-w));
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
.topbar {
  grid-area: top;
  min-height: 56px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.brand h1 {
  margin: 0;
  font-size: 18px;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: #D59BFF;
}
.brand p {
  margin: 2px 0 0;
  color: var(--text-dim);
  font-size: 13px;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.topbar-right { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.chip {
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--text);
  border: 1px solid rgba(0,255,198,.18);
  background: rgba(255,255,255,.02);
}
.sidebar, .main, .right {
  min-height: 0;
  overflow: auto;
  padding: 14px;
}
.sidebar { grid-area: sidebar; }
.main { grid-area: main; display: flex; flex-direction: column; }
.right { grid-area: right; display: grid; gap: 12px; align-content: start; }
.section-title {
  margin: 0 0 12px;
  font-size: 15px;
  color: #D59BFF;
  text-transform: uppercase;
  letter-spacing: .14em;
  font-weight: 800;
}
.session-link {
  display: block;
  text-decoration: none;
  color: var(--text);
  border: 1px solid rgba(0,255,198,.12);
  border-radius: 12px;
  background: rgba(255,255,255,.02);
  padding: 10px 12px;
  margin-bottom: 8px;
}
.session-link.active {
  border-color: rgba(0,255,198,.32);
  box-shadow: 0 0 0 1px rgba(0,255,198,.14), 0 0 16px rgba(0,255,198,.08);
  background: linear-gradient(180deg, rgba(0,255,198,.06), rgba(122,0,255,.06));
}
.session-title { color: #C78BFF; font-size: 14px; font-weight: 700; }
.meta { color: var(--text-dim); font-size: 12px; }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.tab {
  text-decoration: none;
  color: var(--text-dim);
  border: 1px solid rgba(0,255,198,.14);
  border-radius: 999px;
  padding: 8px 12px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.tab.active {
  color: var(--text);
  border-color: rgba(0,255,198,.30);
  box-shadow: 0 0 0 1px rgba(0,255,198,.12), 0 0 16px rgba(0,255,198,.08);
}
.main-panel { flex: 1 1 auto; min-height: 0; overflow: auto; }
.message-card, .panel-block {
  border: 1px solid rgba(255,255,255,.05);
  border-radius: 12px;
  background: rgba(255,255,255,.02);
  padding: 12px;
  margin-bottom: 10px;
}
.message-role {
  color: #C78BFF;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .08em;
  margin-bottom: 8px;
}
pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  line-height: 1.55;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  text-transform: uppercase;
  border: 1px solid rgba(255,255,255,.08);
}
.badge.ok { color: var(--green); border-color: rgba(77,255,184,.24); }
.badge.warn { color: var(--yellow); border-color: rgba(255,230,109,.22); }
.empty { color: var(--text-dim); font-style: italic; }
@media (max-width: 1280px) {
  body { overflow: auto; }
  .dashboard {
    width: calc(100vw - 16px);
    height: auto;
    min-height: calc(100vh - 16px);
    margin: 8px;
    grid-template-columns: 1fr;
    grid-template-rows: auto auto minmax(420px, 1fr) auto;
    grid-template-areas: 'top' 'sidebar' 'main' 'right';
  }
}
"""
