"""Generate the README's animated SVG assets from real captured output.

- banner.svg        animated wordmark + tagline
- pipeline.svg      the request/approval pipeline, with the gate highlighted
- terminal.svg      real run trace (docs/assets/trace.txt) with a typing cursor

Run: python scripts/make_assets.py
"""
from __future__ import annotations

import os
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "docs", "assets")
os.makedirs(ASSETS, exist_ok=True)

LIME = "#c6ff00"
BG = "#0a0a0c"
SURFACE = "#121218"
LINE = "#2a2a33"
TEXT = "#f2f2f5"
MUTED = "#9a9aa6"
RED = "#ff7a70"

FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "Inter, Segoe UI, Helvetica, Arial, sans-serif"


def write(name: str, body: str) -> None:
    path = os.path.join(ASSETS, name)
    with open(path, "w", encoding="utf8") as fh:
        fh.write(body)
    print(f"wrote {name} ({len(body)} bytes)")


# ---------------------------------------------------------------- banner

def banner() -> None:
    body = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 260" width="1200" height="260" role="img" aria-label="PlacePilot - a placement agent that asks before it applies">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0b0b0e"/><stop offset="100%" stop-color="#141419"/>
    </linearGradient>
    <linearGradient id="lime" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{LIME}"/><stop offset="100%" stop-color="#8affc1"/>
    </linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect width="1200" height="260" fill="url(#bg)"/>
  <g opacity="0.10" stroke="{LIME}" stroke-width="1">
    {''.join(f'<path d="M0 {y} H1200" />' for y in range(20, 260, 24))}
  </g>

  <!-- mark -->
  <g transform="translate(70,70)">
    <rect width="120" height="120" rx="28" fill="{LIME}">
      <animate attributeName="opacity" values="0.85;1;0.85" dur="3.6s" repeatCount="indefinite"/>
    </rect>
    <path d="M42 92V28h30a20 20 0 0 1 0 40H42" fill="none" stroke="#0b0c00" stroke-width="13"
          stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="220" stroke-dashoffset="220">
      <animate attributeName="stroke-dashoffset" from="220" to="0" dur="1.6s" fill="freeze" calcMode="spline" keySplines="0.16 1 0.3 1"/>
    </path>
  </g>

  <text x="225" y="132" font-family="{SANS}" font-size="62" font-weight="700" fill="{TEXT}" letter-spacing="-2">
    PlacePilot
    <animate attributeName="opacity" from="0" to="1" dur="0.7s" fill="freeze"/>
  </text>
  <text x="227" y="172" font-family="{FONT}" font-size="19" fill="{MUTED}" letter-spacing="0.5">
    a placement agent that asks before it applies
    <animate attributeName="opacity" from="0" to="1" begin="0.35s" dur="0.9s" fill="freeze"/>
  </text>

  <g font-family="{FONT}" font-size="15">
    <g transform="translate(228,196)">
      <rect width="196" height="30" rx="15" fill="{LIME}" opacity="0.12" stroke="{LIME}" stroke-opacity="0.45"/>
      <circle cx="16" cy="15" r="4" fill="{LIME}"><animate attributeName="opacity" values="1;0.2;1" dur="1.8s" repeatCount="indefinite"/></circle>
      <text x="30" y="20" fill="{LIME}">nothing sends itself</text>
    </g>
    <g transform="translate(436,196)">
      <rect width="176" height="30" rx="15" fill="{SURFACE}" stroke="{LINE}"/>
      <text x="16" y="20" fill="{MUTED}">HTTP 422 gate</text>
    </g>
    <g transform="translate(624,196)">
      <rect width="188" height="30" rx="15" fill="{SURFACE}" stroke="{LINE}"/>
      <text x="16" y="20" fill="{MUTED}">grounded claims</text>
    </g>
  </g>

  <text x="1130" y="236" text-anchor="end" font-family="{FONT}" font-size="13" fill="#5c5c68">
    AgentX 2026 - PS-06 - Team ZYRO
  </text>
</svg>
'''
    write("banner.svg", body)


# ---------------------------------------------------------------- pipeline

def pipeline() -> None:
    stages = [
        ("Resume", "PDF -> verified facts", LIME),
        ("Plan", "deterministic or LLM", TEXT),
        ("Act", "audited tool calls", TEXT),
        ("Observe", "re-plan on thin results", TEXT),
        ("Ground", "every claim -> a fact", TEXT),
        ("APPROVE", "human says yes", LIME),
        ("Send", "local outbox record", TEXT),
    ]
    box_w, gap, x0, y = 148, 24, 30, 96
    parts = []
    for i, (title, sub, colour) in enumerate(stages):
        x = x0 + i * (box_w + gap)
        gate = title == "APPROVE"
        parts.append(f'''
  <g transform="translate({x},{y})">
    <rect width="{box_w}" height="86" rx="12" fill="{'#15150c' if gate else SURFACE}"
          stroke="{LIME if gate else LINE}" stroke-width="{2 if gate else 1}">
      {'<animate attributeName="stroke-opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>' if gate else ''}
    </rect>
    <text x="{box_w/2}" y="34" text-anchor="middle" font-family="{SANS}" font-size="16" font-weight="700"
          fill="{LIME if gate else TEXT}">{escape(title)}</text>
    <text x="{box_w/2}" y="58" text-anchor="middle" font-family="{FONT}" font-size="10.5" fill="{MUTED}">{escape(sub)}</text>
  </g>''')
        if i < len(stages) - 1:
            ax = x + box_w + 3
            parts.append(f'''
  <g>
    <line x1="{ax}" y1="{y+43}" x2="{ax+gap-6}" y2="{y+43}" stroke="{LINE}" stroke-width="2"/>
    <circle r="3" fill="{LIME}">
      <animateMotion dur="2.2s" begin="{i*0.28}s" repeatCount="indefinite"
        path="M{ax},{y+43} L{ax+gap-6},{y+43}"/>
      <animate attributeName="opacity" values="0;1;0" dur="2.2s" begin="{i*0.28}s" repeatCount="indefinite"/>
    </circle>
    <path d="M{ax+gap-11} {y+38} l6 5 -6 5" fill="none" stroke="{LINE}" stroke-width="2"/>
  </g>''')

    body = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 300" width="1200" height="300" role="img" aria-label="PlacePilot pipeline: resume to verified facts, plan, act, observe, ground, human approval gate, send">
  <rect width="1200" height="300" rx="14" fill="{BG}"/>
  <text x="30" y="46" font-family="{SANS}" font-size="19" font-weight="700" fill="{TEXT}">The loop, and the one door it cannot open on its own</text>
  <text x="30" y="70" font-family="{FONT}" font-size="12.5" fill="{MUTED}">every tool call is logged - the send tool is refused by the route, the executor and a SQLite trigger</text>
  {''.join(parts)}
  <g font-family="{FONT}" font-size="12">
    <text x="30" y="228" fill="{RED}">blocked without approval:</text>
    <text x="182" y="228" fill="{MUTED}">POST /api/applications/{'{id}'}/send  ->  422 approval_required</text>
    <text x="30" y="250" fill="{MUTED}">bundle_hash</text>
    <text x="126" y="250" fill="{LIME}">bndl_9c2e...</text>
    <text x="30" y="272" fill="{MUTED}">approve a bundle, then the outbox accepts a matching hash - edit a fact and that yes expires</text>
  </g>
</svg>
'''
    write("pipeline.svg", body)


# ---------------------------------------------------------------- terminal

def terminal() -> None:
    path = os.path.join(ASSETS, "trace.txt")
    lines = open(path, encoding="utf8").read().rstrip("\n").split("\n") if os.path.exists(path) else [
        '$ placepilot ask "Find 10 AI/ML internships in Pune"', "",
        "  (run scripts/capture_trace.py to regenerate from a live run)"]
    lh = 21
    top = 78
    height = top + lh * len(lines) + 34
    rows = []
    for i, line in enumerate(lines):
        colour = TEXT
        if line.strip().startswith("->"):
            colour = LIME
        elif "not enough" in line.lower():
            colour = "#ffb84d"
        elif "error" in line.lower():
            colour = RED
        elif line.strip().startswith(("1 ", "2 ", "3 ", "4 ", "5 ", "6 ", "7 ", "8 ", "9 ")):
            colour = MUTED
        rows.append(
            f'<text x="26" y="{top + i * lh}" font-family="{FONT}" font-size="13" fill="{colour}" '
            f'xml:space="preserve" opacity="0">'
            f'<animate attributeName="opacity" from="0" to="1" begin="{0.25 + i*0.16:.2f}s" dur="0.3s" fill="freeze"/>'
            f'{escape(line)}</text>')

    body = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 {height}" width="980" height="{height}" role="img" aria-label="Real PlacePilot run trace">
  <rect width="980" height="{height}" rx="12" fill="#0d0d11" stroke="{LINE}"/>
  <rect width="980" height="42" rx="12" fill="#14141a"/>
  <rect y="30" width="980" height="12" fill="#14141a"/>
  <circle cx="26" cy="21" r="6" fill="#ff5f57"/><circle cx="46" cy="21" r="6" fill="#febc2e"/><circle cx="66" cy="21" r="6" fill="#28c840"/>
  <text x="490" y="26" text-anchor="middle" font-family="{FONT}" font-size="12" fill="{MUTED}">placepilot - live run trace (captured, not mocked)</text>
  {''.join(rows)}
  <rect x="26" y="{top + len(lines)*lh - 11}" width="8" height="15" fill="{LIME}">
    <animate attributeName="opacity" values="1;0;1" dur="1.1s" repeatCount="indefinite"/>
  </rect>
</svg>
'''
    write("terminal.svg", body)


if __name__ == "__main__":
    banner()
    pipeline()
    terminal()
