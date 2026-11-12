"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Application } from "@/lib/api";
import { Chip, Empty, ErrorNote, ScoreBars, ScoreRing, Spinner, deadlineLabel, deadlineTone } from "@/components/ui";

type Tab = "diff" | "resume" | "cover" | "grounding";

export default function Review() {
  const { id } = useParams<{ id: string }>();
  const [app, setApp] = useState<Application | null>(null);
  const [tab, setTab] = useState<Tab>("diff");
  const [error, setError] = useState<any>(null);
  const [gateResult, setGateResult] = useState<any>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      setApp(await api.application(id));
    } catch (e) {
      setError(e);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !app) return <ErrorNote error={error} onRetry={load} />;
  if (!app) return <Spinner label="Loading the bundle" />;

  const resume = app.docs.resume;
  const cover = app.docs.cover;
  const approval = app.approval;
  const isApproved = approval?.status === "approved" || app.status === "approved";
  const isSent = app.status === "sent";
  const days = app.deadline ? Math.round((new Date(app.deadline).getTime() - Date.now()) / 86400000) : null;
  const diff = app.diff;

  async function trySend() {
    setBusy(true);
    setGateResult(null);
    try {
      const res = await api.send(id);
      setSent(res);
      await load();
    } catch (e) {
      const err = e as ApiError;
      setGateResult({ status: err.status, code: err.code, message: err.message, hint: err.hint, details: err.details });
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      await api.decide(id, { decision: "approve", confirm: true, bundle_hash: approval?.bundle_hash, note });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    try {
      await api.decide(id, { decision: "reject", note });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack gap-16" style={{ maxWidth: 1180 }}>
      <div className="row between wrap gap-12">
        <div>
          <Link href="/desk" className="faint" style={{ fontSize: 12.5 }}>← Desk</Link>
          <h1 style={{ fontSize: 22, letterSpacing: "-0.03em", marginTop: 4 }}>{app.job.title}</h1>
          <p className="faint" style={{ fontSize: 13 }}>
            {app.job.company} · {app.job.location}
            {resume && ` · draft v${resume.version}, generated ${resume.generated_by}`}
          </p>
        </div>
        <div className="row gap-8 wrap">
          <Chip tone={deadlineTone(days) as any}>{deadlineLabel(days)}</Chip>
          <Chip tone={isSent ? "ok" : isApproved ? "lime" : undefined}>
            {isSent ? "sent · demo outbox" : isApproved ? "approved by you" : approval?.status ?? "waiting for your yes"}
          </Chip>
        </div>
      </div>

      {error && <ErrorNote error={error} />}

      <div className="split split-review">
        <div className="card" style={{ padding: 0 }}>
          <div className="row gap-4 wrap" style={{ padding: "10px 12px", borderBottom: "1px solid var(--line)" }}>
            {(["diff", "resume", "cover", "grounding"] as Tab[]).map((t) => (
              <button key={t} className={`chip${tab === t ? " chip-lime" : ""}`}
                      style={{ cursor: "pointer", textTransform: "capitalize" }} onClick={() => setTab(t)}>
                {t === "diff" ? "Resume diff" : t === "cover" ? "Cover note" : t}
              </button>
            ))}
            <span className="right mono faint" style={{ fontSize: 11 }}>
              {approval?.bundle_hash?.slice(0, 14) ?? "no bundle"}
            </span>
          </div>

          <div style={{ padding: 16 }}>
            {tab === "diff" && (
              <div className="stack gap-12">
                <div className="row gap-8 wrap">
                  <Chip tone="lime">{diff.summary.added} added</Chip>
                  <Chip>{diff.summary.trimmed} trimmed</Chip>
                  <Chip>{diff.summary.kept} kept</Chip>
                  {resume?.grounding?.checked ? (
                    <Chip tone="ok">{resume.grounding.checked} claims traced</Chip>
                  ) : null}
                </div>
                <div className="diff">
                  {diff.ops.length === 0 && <p className="faint">Identical to your base resume.</p>}
                  {diff.ops.map((op, i) => (
                    <div key={i}>
                      {op.base?.map((l, j) => <span className="del" key={`d${j}`}>− {l || " "}</span>)}
                      {op.tailored?.map((l, j) => <span className="ins" key={`i${j}`}>+ {l || " "}</span>)}
                    </div>
                  ))}
                </div>
                {resume?.content?.not_claimed?.length ? (
                  <div className="card card-tight" style={{ background: "#0a0a0d" }}>
                    <span className="eyebrow">Deliberately not claimed</span>
                    <p className="muted mt-4" style={{ fontSize: 12.5 }}>
                      {resume.content.not_claimed.join(", ")} — required by the posting, absent from your verified facts.
                      PlacePilot listed these as gaps instead of inventing them.
                    </p>
                  </div>
                ) : null}
              </div>
            )}

            {tab === "resume" && (
              resume ? <pre className="doc">{resume.text}</pre> : <Empty title="No resume draft yet." />
            )}
            {tab === "cover" && (cover ? <div className="doc">{cover.text}</div> : <Empty title="No cover note yet." />)}

            {tab === "grounding" && (
              <div className="stack gap-12">
                {resume ? (
                  <>
                    <div className="row gap-8 wrap">
                      <Chip tone={resume.passed ? "ok" : "red"}>
                        {resume.passed ? "every claim traced" : "unsupported claim"}
                      </Chip>
                      <Chip>coverage {Math.round((resume.grounding.coverage ?? 1) * 100)}%</Chip>
                    </div>
                    {resume.content.sections && (
                      <table className="data">
                        <thead>
                          <tr><th>Claim</th><th>Fact ids</th><th>Status</th></tr>
                        </thead>
                        <tbody>
                          {Object.entries(resume.content.sections).flatMap(([section, items]) =>
                            items.map((item, i) => (
                              <tr key={`${section}-${i}`}>
                                <td style={{ fontSize: 13 }}>{item.text.slice(0, 110)}</td>
                                <td className="mono faint" style={{ fontSize: 11 }}>{item.fact_ids.join(", ")}</td>
                                <td><Chip tone="ok">supported</Chip></td>
                              </tr>
                            )),
                          )}
                        </tbody>
                      </table>
                    )}
                    {resume.grounding.problems?.length ? (
                      <div className="card card-tight" style={{ borderColor: "rgba(255,122,112,.4)" }}>
                        <span className="eyebrow" style={{ color: "var(--red)" }}>Rejected claims</span>
                        {resume.grounding.problems.map((p, i) => (
                          <p key={i} className="muted" style={{ fontSize: 12.5 }}>{p.claim}: {p.reason}</p>
                        ))}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <Empty title="Nothing to audit yet." />
                )}
              </div>
            )}
          </div>
        </div>

        {/* action column */}
        <aside className="stack gap-12">
          {app.fit && (
            <div className="card">
              <div className="row between">
                <span className="eyebrow">Fit</span>
                <span className="chip chip-lime">{app.fit.label}</span>
              </div>
              <div className="row gap-12 mt-12">
                <ScoreRing score={app.fit.score} />
                <div className="grow">
                  <ScoreBars breakdown={app.fit.breakdown} />
                </div>
              </div>
            </div>
          )}

          {sent ? (
            <div className="gate">
              <p style={{ fontSize: 14, fontWeight: 600 }}>Recorded. Nothing left this machine.</p>
              <p className="muted mt-8" style={{ fontSize: 12.5 }}>
                Written to the local demo outbox as <span className="mono">{sent.outbox_id}</span>. No email was dispatched.
              </p>
              <p className="mono faint mt-8" style={{ fontSize: 11 }}>{sent.recorded_at}</p>
              <Link href="/tracker" className="btn btn-sm mt-12">Open tracker</Link>
            </div>
          ) : isSent ? (
            <div className="gate">
              <p style={{ fontSize: 14, fontWeight: 600 }}>Already sent</p>
              <p className="muted mt-8" style={{ fontSize: 12.5 }}>
                Outbox <span className="mono">{app.outbox?.id}</span> at {app.outbox?.recorded_at}.
              </p>
            </div>
          ) : (
            <div className="gate">
              <p className="eyebrow">The gate</p>
              {!isApproved ? (
                <>
                  <p className="mt-8" style={{ fontSize: 13.5, fontWeight: 550 }}>Read it like a recruiter. Then decide.</p>
                  <ul className="muted mt-8" style={{ fontSize: 12.5, paddingLeft: 18, lineHeight: 1.6 }}>
                    <li>Every bullet traces to a fact you verified.</li>
                    <li>Gaps are listed, not invented.</li>
                    <li>Approval is bound to this exact bundle.</li>
                  </ul>
                  <label className="row gap-8 mt-12" style={{ fontSize: 12.5, alignItems: "flex-start", cursor: "pointer" }}>
                    <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}
                           style={{ marginTop: 2, width: 15, height: 15, accentColor: "#c6ff00" }} />
                    I reviewed every claim and change in this application.
                  </label>
                  <input className="input mt-10" placeholder="Optional note to yourself" value={note}
                         onChange={(e) => setNote(e.target.value)} style={{ fontSize: 12.5 }} />
                  <div className="row gap-8 mt-12">
                    <button className="btn btn-primary btn-sm" disabled={!confirmed || busy || !resume} onClick={approve}>
                      {busy ? "Saving…" : "Approve bundle"}
                    </button>
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={reject}>Reject</button>
                  </div>
                </>
              ) : (
                <>
                  <p className="mt-8" style={{ fontSize: 13.5, fontWeight: 550 }}>
                    Approved by you. PlacePilot can send this one now.
                  </p>
                  <p className="faint mt-4" style={{ fontSize: 11.5 }}>
                    Bound to {approval?.bundle_hash?.slice(0, 18)}… Editing a fact invalidates it.
                  </p>
                  <button className="btn btn-primary btn-sm mt-12" disabled={busy} onClick={trySend}>
                    {busy ? "Recording…" : "Send application"}
                  </button>
                </>
              )}
            </div>
          )}

          <div className={`gate${gateResult ? " gate-blocked" : ""}`}>
            <div className="row between">
              <span className="eyebrow">Prove the gate</span>
              {gateResult && <span className="mono" style={{ fontSize: 11, color: "var(--red)" }}>HTTP {gateResult.status}</span>}
            </div>
            {!gateResult ? (
              <>
                <p className="muted mt-8" style={{ fontSize: 12.5 }}>
                  This calls the send endpoint directly, skipping the button above.
                </p>
                <button className="btn btn-sm mt-10" disabled={busy || isSent} onClick={trySend}>
                  Try sending now
                </button>
              </>
            ) : (
              <pre className="mono mt-8" style={{ fontSize: 11, color: "#ffb3ad", whiteSpace: "pre-wrap", lineHeight: 1.5, margin: 0 }}>
{JSON.stringify({ code: gateResult.code, message: gateResult.message, hint: gateResult.hint }, null, 1)}
              </pre>
            )}
          </div>

          <div className="card card-tight">
            <span className="eyebrow">Reminders</span>
            {app.reminders?.length ? (
              app.reminders.map((r) => (
                <p key={r.id} className="mono faint" style={{ fontSize: 11.5 }}>{r.kind} · {r.due_at}</p>
              ))
            ) : (
              <p className="faint" style={{ fontSize: 12 }}>None yet.</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
