"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, resetStudent } from "@/lib/api";
import { Chip, Empty, ErrorNote } from "@/components/ui";

export default function Memory() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<any>(null);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.memory().then(setData).catch(setError);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function exportAll() {
    const d = await api.exportData();
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "placepilot-export.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function deleteAll() {
    setBusy(true);
    try {
      const r = await api.deleteMe();
      setResult(r);
      resetStudent();
      setData(null);
      setConfirming(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <ErrorNote error={error} onRetry={load} />;

  const facts = data?.facts ?? [];
  const topics = data?.topics ?? [];
  const calls = data?.calls ?? [];
  const runs = data?.runs ?? [];
  const memories = data?.memories ?? [];

  return (
    <div className="stack gap-16" style={{ maxWidth: 1000 }}>
      <div className="row between wrap gap-12">
        <div>
          <h1 style={{ fontSize: 24, letterSpacing: "-0.03em" }}>Memory</h1>
          <p className="faint" style={{ fontSize: 13 }}>Everything the agent remembers about you. Nothing it doesn&apos;t.</p>
        </div>
        <div className="row gap-8">
          <button className="btn btn-sm" onClick={exportAll}>Export JSON</button>
          <button className="btn btn-danger btn-sm" onClick={() => setConfirming(true)}>Delete all</button>
        </div>
      </div>

      {result && (
        <div className="gate">
          <p style={{ fontSize: 13.5, fontWeight: 600 }}>Deleted.</p>
          <p className="muted mt-4" style={{ fontSize: 12.5 }}>
            Rows removed: {Object.entries(result.deleted as Record<string, number>).map(([k, v]) => `${k} ${v}`).join(", ")}.
            Remaining for this student:{" "}
            <span className="mono">
              {Object.values(result.remaining as Record<string, number>).reduce((a, b) => a + b, 0)}
            </span>.
            Foreign-key violations: {result.fk_violations}.
          </p>
          <Link className="btn btn-sm mt-12" href="/onboarding">Start over</Link>
        </div>
      )}

      {confirming && (
        <div className="gate gate-blocked">
          <p style={{ fontSize: 13.5, fontWeight: 600 }}>Delete all student data?</p>
          <p className="muted mt-4" style={{ fontSize: 12.5 }}>
            Profile, resume text, facts, drafts, approvals, outbox records, interview scores and tool history.
            Not just the row on this screen. This cannot be undone.
          </p>
          <div className="row gap-8 mt-12">
            <button className="btn btn-danger btn-sm" disabled={busy} onClick={deleteAll}>
              {busy ? "Deleting…" : "Yes, delete everything"}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </div>
      )}

      {!data ? (
        <Empty title="No profile yet." action={<Link className="btn btn-sm" href="/onboarding">Onboard</Link>} />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, alignItems: "start" }}>
          <section className="card">
            <div className="row between">
              <span className="eyebrow">Profile</span>
              <Chip>{facts.filter((f: any) => f.verified).length} verified facts</Chip>
            </div>
            <p className="mt-8" style={{ fontSize: 13.5 }}>{data.student.name || "Unnamed student"}</p>
            <p className="faint" style={{ fontSize: 12 }}>{data.student.email} · {data.student.location}</p>
            <div className="row gap-6 wrap mt-8">
              {(data.student.roles ?? []).map((r: string) => <Chip key={r} tone="lime">{r}</Chip>)}
              {(data.student.locations ?? []).map((r: string) => <Chip key={r}>{r}</Chip>)}
            </div>
            <hr className="divider" />
            <span className="eyebrow">Weak interview topics</span>
            {topics.length ? (
              <div className="stack gap-4 mt-8">
                {topics.map((t: any) => (
                  <div key={t.topic} className="row between">
                    <span className="mono" style={{ fontSize: 12 }}>{t.topic}</span>
                    <span className="faint mono" style={{ fontSize: 11.5 }}>{t.avg_score.toFixed(1)}/5 · {t.attempts}×</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="faint mt-8" style={{ fontSize: 12.5 }}>No interview scores yet.</p>
            )}
          </section>

          <section className="card">
            <span className="eyebrow">What it carries across sessions</span>
            {memories.length ? (
              <div className="stack gap-6 mt-8">
                {memories.slice(0, 8).map((m: any) => (
                  <p key={m.id} className="muted" style={{ fontSize: 12.5 }}>
                    <span className="mono faint" style={{ fontSize: 10.5 }}>{m.kind}</span> · {m.text}
                  </p>
                ))}
              </div>
            ) : (
              <p className="faint mt-8" style={{ fontSize: 12.5 }}>
                Nothing yet. Weak topics and observations appear here after a mock interview or a run.
              </p>
            )}
          </section>

          <section className="card" style={{ gridColumn: "1 / -1" }}>
            <div className="row between">
              <span className="eyebrow">Tool-call history</span>
              <Chip>{calls.length} calls</Chip>
            </div>
            {calls.length ? (
              <div style={{ overflowX: "auto" }} className="mt-8">
                <table className="data">
                  <thead><tr><th>Tool</th><th>Status</th><th>Duration</th><th>Args</th><th>When</th></tr></thead>
                  <tbody>
                    {calls.slice(0, 15).map((c: any, i: number) => (
                      <tr key={i}>
                        <td className="mono" style={{ fontSize: 12 }}>{c.tool}</td>
                        <td><span className={`chip${c.status === "ok" ? " chip-ok" : " chip-red"}`} style={{ fontSize: 10.5 }}>{c.status}</span></td>
                        <td className="mono faint" style={{ fontSize: 11.5 }}>{c.duration_ms}ms</td>
                        <td className="mono faint" style={{ fontSize: 11, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {String(c.args_json).slice(0, 70)}
                        </td>
                        <td className="mono faint" style={{ fontSize: 11 }}>{c.created_at?.slice(11, 19)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="faint mt-8" style={{ fontSize: 12.5 }}>No runs yet.</p>
            )}
          </section>

          <section className="card" style={{ gridColumn: "1 / -1" }}>
            <span className="eyebrow">Recent runs</span>
            {runs.length ? runs.map((r: any) => (
              <div key={r.id} className="row between gap-8" style={{ padding: "7px 0", borderBottom: "1px solid #17171c" }}>
                <span className="mono faint" style={{ fontSize: 11.5 }}>{r.id}</span>
                <span className="grow muted" style={{ fontSize: 12.5 }}>{r.command || r.kind}</span>
                <Chip tone={r.status === "done" ? "ok" : r.status === "error" ? "red" : undefined}>{r.status}</Chip>
              </div>
            )) : <p className="faint mt-8" style={{ fontSize: 12.5 }}>Nothing has run yet.</p>}
          </section>
        </div>
      )}
    </div>
  );
}
