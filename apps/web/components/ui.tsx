"use client";

/** Small shared pieces. Plain elements + tokens; no UI library. */

export function ScoreRing({ score, label }: { score: number; label?: string }) {
  return (
    <div className="score-ring" style={{ ["--p" as any]: Math.max(0, Math.min(100, score)) }} title={label ?? `${score}/100`}>
      <span>{score}</span>
    </div>
  );
}

export function ScoreBars({ breakdown }: { breakdown: Record<string, number> }) {
  const max = Math.max(...Object.values(breakdown), 1);
  return (
    <div className="stack gap-6">
      {Object.entries(breakdown).map(([k, v]) => (
        <div key={k} className="row gap-10">
          <span className="mono faint" style={{ fontSize: 11, width: 92, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            {k.replace("_", " ")}
          </span>
          <div className="bar grow">
            <i style={{ width: `${(v / max) * 100}%`, opacity: v === 0 ? 0.15 : 1 }} />
          </div>
          <span className="mono faint" style={{ fontSize: 11, width: 30, textAlign: "right" }}>
            {Math.round(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function PhaseTag({ phase }: { phase: string }) {
  return <span className={`phase phase-${phase}`}>{phase}</span>;
}

export function Empty({ title, body, action }: { title: string; body?: string; action?: React.ReactNode }) {
  return (
    <div className="empty">
      <p style={{ color: "var(--muted)", fontWeight: 500 }}>{title}</p>
      {body && <p className="mt-8" style={{ fontSize: 13.5, maxWidth: "52ch", margin: "8px auto 0" }}>{body}</p>}
      {action && <div className="mt-16">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: any; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="card" style={{ borderColor: "rgba(255,122,112,.35)", background: "rgba(255,122,112,.06)" }}>
      <div className="row gap-8">
        <span className="chip chip-red mono">{error.status || "ERR"}</span>
        <strong style={{ fontSize: 14 }}>{error.message}</strong>
      </div>
      {error.hint && <p className="muted mt-8" style={{ fontSize: 13 }}>{error.hint}</p>}
      {error.code && <p className="mono faint mt-8" style={{ fontSize: 11 }}>{error.code}</p>}
      {onRetry && <button className="btn btn-sm mt-12" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row gap-8 muted" style={{ fontSize: 13 }}>
      <span className="pulse" />
      {label ?? "Working"}
    </span>
  );
}

export function Field({ label, value, onChange, placeholder, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  const id = `f_${label.replace(/\s+/g, "_").toLowerCase()}`;
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} className="input" type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

export function Chip({ children, tone }: { children: React.ReactNode; tone?: "lime" | "amber" | "red" | "ok" }) {
  return <span className={`chip${tone ? ` chip-${tone}` : ""}`}>{children}</span>;
}

export function deadlineTone(days: number | null): "red" | "amber" | undefined {
  if (days === null) return undefined;
  if (days < 0) return "red";
  if (days <= 3) return "amber";
  return undefined;
}

export function deadlineLabel(days: number | null): string {
  if (days === null) return "no deadline";
  if (days < 0) return `closed ${Math.abs(days)}d ago`;
  if (days === 0) return "closes today";
  return `${days}d left`;
}
