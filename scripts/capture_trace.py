"""Capture a genuine run trace from the live API, for the README terminal card.

Writes docs/assets/trace.txt — the raw text the SVG/README is built from, so the
showcase shows real output rather than a mock-up.
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("API", "http://127.0.0.1:8060")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "assets")
os.makedirs(OUT, exist_ok=True)


def call(path, method="GET", body=None, sid=None):
    req = urllib.request.Request(f"{BASE}{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", **({"X-Student-Id": sid} if sid else {})})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode())


def ascii_clean(text: str, limit: int) -> str:
    """Normalise the API's typography to plain terminal ASCII, cut on a word boundary."""
    out = (text or "").replace("\u00b7", "|").replace("\u2014", "-").replace("\u2013", "-")
    out = out.replace("\u2019", "'").replace("\u2192", "->").replace("\u00b7", "|")
    out = out.encode("ascii", "ignore").decode()
    if len(out) <= limit:
        return out
    cut = out[:limit].rsplit(" ", 1)[0]
    return (cut or out[:limit]).rstrip() + "..."


def main():
    for _ in range(40):
        try:
            call("/healthz")
            break
        except Exception:
            time.sleep(0.5)

    sid = call("/api/students", "POST")["id"]
    call("/api/onboarding/sample", "POST", sid=sid)
    call("/api/students/me", "PATCH", {"roles": ["ai"], "locations": ["Pune"], "seniority": "intern"}, sid)

    run = call("/api/runs", "POST", {"command": "Find 10 AI/ML internships in Pune"}, sid)
    for _ in range(300):
        detail = call(f"/api/runs/{run['run_id']}", sid=sid)
        if detail["status"] not in ("queued", "running"):
            break
        time.sleep(0.15)

    lines = [
        '$ placepilot ask "Find 10 AI/ML internships in Pune"',
        "",
    ]
    for event in detail["events"]:
        phase = ascii_clean((event["phase"] or "").upper(), 6).ljust(6)
        title = ascii_clean(event["title"] or "", 28).ljust(28)
        body = ascii_clean(event["detail"] or "", 54)
        lines.append(f"  {event['seq']:>2}  {phase} {title} {body}")

    outcome = detail.get("outcome") or {}
    lines.append("")
    lines.append(f"  -> {outcome.get('count', 0)} ranked in {outcome.get('attempts', '?')} search attempt(s), "
                 f"planner={outcome.get('planner', '?')}")
    lines.append("  -> nothing sent: every bundle waits for a human approval")

    text = "\n".join(lines)
    with open(os.path.join(OUT, "trace.txt"), "w", encoding="utf8") as fh:
        fh.write(text + "\n")
    print(text)
    print(f"\nwrote {os.path.join(OUT, 'trace.txt')}")


if __name__ == "__main__":
    main()
