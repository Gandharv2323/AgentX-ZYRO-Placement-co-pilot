"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Run, type RunEvent } from "@/lib/api";
import { Chip, ErrorNote, Empty, PhaseTag, ScoreBars, ScoreRing, Spinner, deadlineLabel, deadlineTone } from "@/components/ui";

const STARTERS = [
  "Find 10 AI/ML internships in Pune",
  "Find 6 data analyst roles this month",
  "What are my deadlines this week?",
];

export default function Desk() {
  const router = useRouter();
  const [command, setCommand] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState<any>(null);
  const [starting, setStarting] = useState(false);
  const [tab, setTab] = useState<"trace" | "tools">("trace");
  const timer = useRef<any>(null);

  const refreshJobs = useCallback(() => {
    api.jobs().then((r) => setJobs(r.jobs)).catch(() => {});
  }, []);

  useEffect(() => {
    api.me().then((me) => {
      if (!me.facts.length) router.replace("/onboarding");
    }).catch(() => {});
    refreshJobs();
    return () => clearInterval(timer.current);
  }, [refreshJobs, router]);

  const poll = useCallback(
    async (runId: string, after = 0) => {
      try {
        const next = await api.run(runId, after);
        setRun((prev) => {
          if (!prev || prev.id !== next.id) return next;
          const seen = new Set(prev.events.map((e) => e.seq));
          return { ...next, events: [...prev.events, ...next.events.filter((e) => !seen.has(e.seq))] };
        });
        if (next.status === "queued" || next.status === "running") {
          timer.current = setTimeout(() => poll(runId, next.last_seq), 450);
        } else {
          refreshJobs();
          setPicked([]);
        }
        return next;
      } catch (e) {
        setError(e);
      }
    },
    [refreshJobs],
  );

  async function start(text?: string) {
    const cmd = (text ?? command).trim();
    if (!cmd) return;
    setStarting(true);
    setError(null);
    setRun(null);
    try {
      const r = await api.startRun({ command: cmd, kind: "chat" });
      await poll(r.run_id, 0);
    } catch (e) {
      setError(e);
    } finally {
      setStarting(false);
    }
  }

  async function tailor() {
    if (!picked.length) return;
    setError(null);
    try {
      const r = await api.tailor(picked);
      router.push(`/applications/${r.application_ids[0]}`);
    } catch (e) {
      setError(e);
    }
  }

  const running = run && (run.status === "queued" || run.status === "running");
  const applications = jobs.filter((j) => j.application_id);

  return (
    <div className="stack gap-16">
      <div className="row between wrap gap-12">
        <div>
          <h1 style={{ fontSize: 24, letterSpacing: "-0.03em" }}>Desk</h1>
          <p className="faint" style={{ fontSize: 13 }}>Ask for openings. It plans its own steps and shows every tool call.</p>
        </div>
        <Link className="btn btn-sm" href="/tracker">Open tracker</Link>
      </div>

      <form
        className="row gap-8"
        onSubmit={(e) => {
          e.preventDefault();
          start();
        }}
      >
        <input
          className="input"
          style={{ padding: "12px 14px", fontSize: 15 }}
          placeholder="Find 10 AI/ML internships in Pune…"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          aria-label="Agent command"
        />
        <button className="btn btn-primary" disabled={running || starting || !command.trim()} type="submit">
          {running ? "Working…" : "Run"}
        </button>
      </form>
      <div className="row gap-6 wrap" style={{ marginTop: -6 }}>
        {STARTERS.map((s) => (
          <button key={s} className="chip" style={{ cursor: "pointer" }} onClick={() => { setCommand(s); start(s); }}>
            {s}
          </button>
        ))}
      </div>

      {error && <ErrorNote error={error} />}

      <div className="split">
        <div className="stack gap-16">
          {!run && !jobs.length && (
            <Empty title="The desk is clear." body="Ask for openings above. Every step it takes is recorded, including the ones that fail." />
          )}

          {run && run.outcome?.count > 0 && (
            <div className="card card-tight row between wrap gap-12">
              <div className="row gap-8" style={{ flexWrap: "wrap" }}>
                <Chip tone="lime">{run.outcome.count} ranked</Chip>
                <Chip>
                  {run.outcome.attempts} search attempt{run.outcome.attempts > 1 ? "s" : ""}
                </Chip>
                {run.outcome.attempts > 1 && <Chip tone="amber">plan revised</Chip>}
              </div>
              <span className="faint" style={{ fontSize: 12 }}>
                Select up to 3 to tailor. Approval is per bundle.
              </span>
            </div>
          )}

          {jobs.length > 0 && (
            <div className="stack gap-10">
              <div className="row between">
                <span className="eyebrow">Openings · ranked by fit</span>
                {picked.length > 0 && (
                  <button className="btn btn-primary btn-sm" onClick={tailor}>
                    Tailor {picked.length} selected
                  </button>
                )}
              </div>
              {jobs.map((job) => {
                const on = picked.includes(job.id);
                const days = job.apply_by
                  ? Math.round((new Date(job.apply_by).getTime() - Date.now()) / 86400000)
                  : null;
                const fit = job.fit_score ?? 0;
                const detail = (job as any)._fit;
                return (
                  <div
                    key={job.id}
                    className="card"
                    style={{
                      borderColor: on ? "rgba(198,255,0,.45)" : "var(--line)",
                      background: on ? "linear-gradient(180deg, rgba(198,255,0,.06), var(--surface))" : "var(--surface)",
                    }}
                  >
                    <div className="row gap-12" style={{ alignItems: "flex-start" }}>
                      <ScoreRing score={fit} label={`Fit ${fit} of 100`} />
                      <div className="grow">
                        <div className="row gap-8 wrap">
                          <strong style={{ fontSize: 15 }}>{job.title}</strong>
                          <span className="mono faint" style={{ fontSize: 11.5 }}>{job.company}</span>
                        </div>
                        <div className="row gap-6 wrap mt-8">
                          <Chip>{job.location}</Chip>
                          <Chip>₹{Math.round((job.stipend_month ?? 0) / 1000)}k/mo</Chip>
                          <Chip tone={deadlineTone(days) as any}>{deadlineLabel(days)}</Chip>
                          {job.status !== "draft" && <Chip tone="ok">{job.status}</Chip>}
                        </div>
                      </div>
                      <label className="row gap-6" style={{ fontSize: 13, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={!on && picked.length >= 3}
                          onChange={(e) =>
                            setPicked((p) => (e.target.checked ? [...p, job.id] : p.filter((x) => x !== job.id)))
                          }
                          style={{ width: 16, height: 16, accentColor: "#c6ff00" }}
                        />
                        Tailor
                      </label>
                    </div>
                    {detail && (
                      <div className="mt-12 stack gap-6">
                        {detail.reasons?.map((r: string) => (
                          <span key={r} style={{ fontSize: 12.5, color: "var(--muted)" }}>✓ {r}</span>
                        ))}
                        {detail.gaps?.length > 0 && (
                          <span style={{ fontSize: 12.5, color: "var(--faint)" }}>
                            — gap: {detail.gaps.join(", ")} (listed, never claimed)
                          </span>
                        )}
                      </div>
                    )}
                    <div className="row gap-8 mt-12">
                      <Link className="btn btn-ghost btn-sm" href={`/applications/${job.application_id}`}>
                        Review draft
                      </Link>
                      <span className="mono faint" style={{ fontSize: 11 }}>
                        posted {job.posted_at} · closes {job.apply_by}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* trace column */}
        <aside className="card trace-col">
          <div className="row between">
            <span className="eyebrow">Run trace</span>
            {running && <Spinner label="live" />}
          </div>
          <div className="row gap-6 mt-12">
            <button className={`chip${tab === "trace" ? " chip-lime" : ""}`} style={{ cursor: "pointer" }} onClick={() => setTab("trace")}>
              Steps
            </button>
            <button className={`chip${tab === "tools" ? " chip-lime" : ""}`} style={{ cursor: "pointer" }} onClick={() => setTab("tools")}>
              Tools
            </button>
          </div>

          {tab === "tools" ? (
            <ToolsList />
          ) : !run ? (
            <p className="faint mt-16" style={{ fontSize: 12.5 }}>
              Nothing has run yet. Each step is stored with its tool, arguments, result and duration.
            </p>
          ) : (
            <div className="mt-12">
              {run.events.map((e: RunEvent) => (
                <div className="event" key={e.seq}>
                  <span className="mono faint" style={{ fontSize: 10.5, width: 18, flex: "none" }}>{e.seq}</span>
                  <div className="grow">
                    <div className="row gap-6 wrap">
                      <PhaseTag phase={e.phase} />
                      <strong style={{ fontSize: 12.5 }}>{e.title}</strong>
                    </div>
                    <p className="event-detail mt-4">{e.detail}</p>
                  </div>
                </div>
              ))}
              {run.status === "error" && (
                <p className="mono mt-8" style={{ fontSize: 11.5, color: "var(--red)" }}>{run.error}</p>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function ToolsList() {
  const [tools, setTools] = useState<{ name: string; risk: string; detail: string }[]>([]);
  useEffect(() => {
    api.tools().then((r) => setTools(r.tools)).catch(() => {});
  }, []);
  return (
    <div className="mt-12 stack gap-8">
      {tools.map((t) => (
        <div key={t.name} className="row gap-8" style={{ alignItems: "flex-start" }}>
          <span className={`chip${t.risk === "destructive" ? " chip-red" : t.risk === "write" ? " chip-amber" : ""}`} style={{ flex: "none", fontSize: 10.5 }}>
            {t.risk}
          </span>
          <div>
            <span className="mono" style={{ fontSize: 12 }}>{t.name}</span>
            <p className="faint" style={{ fontSize: 11.5 }}>{t.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
