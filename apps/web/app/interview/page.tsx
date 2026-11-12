"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Chip, Empty, ErrorNote, Spinner } from "@/components/ui";

type Q = { id: string; topic: string; text: string; provenance: string; answer?: any };

export default function Interview() {
  const [weak, setWeak] = useState<any[]>([]);
  const [language, setLanguage] = useState<"en" | "hi">("en");
  const [role, setRole] = useState("AI/ML Intern");
  const [session, setSession] = useState<{ interview_id: string; questions: Q[] } | null>(null);
  const [idx, setIdx] = useState(0);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<any>(null);
  const [card, setCard] = useState<any>(null);
  const [error, setError] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const recog = useRef<any>(null);

  const loadWeak = useCallback(() => {
    api
      .interviews()
      .then((r) => setWeak(r.topics.filter((t) => t.avg_score < 3)))
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadWeak();
    return () => {
      if (typeof window !== "undefined") window.speechSynthesis?.cancel();
      recog.current?.stop?.();
    };
  }, [loadWeak]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const s = await api.startInterview({ role, language });
      setSession(s);
      setIdx(0);
      setFeedback(null);
      setCard(null);
      setAnswer("");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const q = session?.questions[idx];
  const progress = session ? ((idx + (feedback ? 1 : 0)) / session.questions.length) * 100 : 0;

  async function submit() {
    if (!session || !q) return;
    setBusy(true);
    setError(null);
    try {
      const fb = await api.answer(session.interview_id, { question_id: q.id, text: answer });
      setFeedback(fb);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function next() {
    if (!session) return;
    setFeedback(null);
    setAnswer("");
    if (idx + 1 < session.questions.length) setIdx(idx + 1);
  }

  async function finish() {
    if (!session) return;
    setBusy(true);
    try {
      setCard(await api.completeInterview(session.interview_id));
      setSession(null);
      loadWeak(); // the run just wrote these topics; the next setup screen needs them
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function speak() {
    if (!q || typeof window === "undefined" || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(q.text);
    u.lang = language === "hi" ? "hi-IN" : "en-IN";
    u.onend = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(u);
  }

  function dictate() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      setError({ message: "Speech input is not available in this browser.", hint: "Type your answer instead." });
      return;
    }
    const r = new SR();
    r.lang = language === "hi" ? "hi-IN" : "en-IN";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e: any) => {
      const text = Array.from(e.results).map((x: any) => x[0].transcript).join(" ");
      setAnswer((prev) => `${prev} ${text}`.trim());
    };
    r.onerror = () => setError({ message: "Speech recognition stopped.", hint: "You can keep typing." });
    recog.current = r;
    r.start();
  }

  const allDone = session && idx === session.questions.length - 1 && feedback;

  return (
    <div className="stack gap-16" style={{ maxWidth: 900 }}>
      <div className="row between wrap gap-12">
        <div>
          <h1 style={{ fontSize: 24, letterSpacing: "-0.03em" }}>Interview</h1>
          <p className="faint" style={{ fontSize: 13 }}>Scored by topic. Weak areas come back next session.</p>
        </div>
        {session && <Chip tone="lime">{session.questions.length} questions</Chip>}
      </div>

      {error && <ErrorNote error={error} />}

      {/* setup */}
      {!session && !card && (
        <div className="card stack gap-16">
          {weak.length > 0 && (
            <div className="card card-tight" style={{ background: "#0a0a0d" }}>
              <span className="eyebrow">Carried over from your last session</span>
              <div className="row gap-6 wrap mt-8">
                {weak.slice(0, 3).map((t) => (
                  <Chip key={t.topic} tone="amber">
                    {t.topic.toUpperCase()} {t.avg_score.toFixed(1)}/5
                  </Chip>
                ))}
              </div>
              <p className="faint mt-8" style={{ fontSize: 12.5 }}>
                The next mock reopens these topics first — with the score that put them on the list.
              </p>
            </div>
          )}
          <div className="row gap-16 wrap">
            <div className="grow" style={{ minWidth: 220 }}>
              <span className="label">Role you are practising for</span>
              <select className="select" value={role} onChange={(e) => setRole(e.target.value)}>
                {["AI/ML Intern", "Data Analyst Intern", "Backend Developer Intern", "Product Analyst Intern"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </div>
            <div>
              <span className="label">Question language</span>
              <div className="row gap-6">
                <button className={`chip${language === "en" ? " chip-lime" : ""}`} style={{ cursor: "pointer", padding: "6px 12px" }}
                        onClick={() => setLanguage("en")}>English</button>
                <button className={`chip${language === "hi" ? " chip-lime" : ""}`} style={{ cursor: "pointer", padding: "6px 12px" }}
                        onClick={() => setLanguage("hi")}>हिंदी</button>
              </div>
            </div>
          </div>
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={start}>
            {busy ? "Preparing…" : "Start 6-question mock"}
          </button>
        </div>
      )}

      {/* session */}
      {session && q && (
        <div className="card stack gap-16">
          <div className="row between gap-8">
            <div className="row gap-6 wrap">
              <span className="chip chip-lime mono" style={{ fontSize: 11 }}>{q.topic}</span>
              <span className="faint" style={{ fontSize: 11.5 }}>{q.provenance}</span>
            </div>
            <span className="mono faint" style={{ fontSize: 11 }}>{idx + 1} / {session.questions.length}</span>
          </div>
          <div className="bar"><i style={{ width: `${progress}%` }} /></div>

          <h2 style={{ fontSize: 21, lineHeight: 1.35, letterSpacing: "-0.02em" }}>{q.text}</h2>

          {!feedback ? (
            <>
              <textarea className="textarea" rows={6} value={answer} onChange={(e) => setAnswer(e.target.value)}
                        placeholder="Answer in your own words. Substance is scored, not fluency."
                        style={{ minHeight: 130 }} />
              <div className="row gap-8 wrap">
                <button className="btn btn-primary btn-sm" disabled={busy || answer.trim().length < 2} onClick={submit}>
                  {busy ? "Scoring…" : "Submit answer"}
                </button>
                <button className="btn btn-sm" onClick={speak} disabled={speaking}>
                  {speaking ? "Speaking…" : "Listen"}
                </button>
                <button className="btn btn-sm" onClick={dictate}>Speak answer</button>
                <button className="btn btn-ghost btn-sm" onClick={next}>Skip</button>
              </div>
            </>
          ) : (
            <div className="stack gap-12">
              <div className="card card-tight" style={{ background: "#0a0a0d" }}>
                <div className="row between">
                  <span className="eyebrow">Rubric score</span>
                  <span className="mono" style={{ fontSize: 15, color: "var(--lime)" }}>{feedback.score}/5</span>
                </div>
                <div className="bar mt-8"><i style={{ width: `${(feedback.score / 5) * 100}%` }} /></div>
                <p className="muted mt-8" style={{ fontSize: 13 }}>{feedback.strong}</p>
                {feedback.missing?.length > 0 && (
                  <p className="faint mt-4" style={{ fontSize: 12.5 }}>Not yet addressed: {feedback.missing.join(", ")}</p>
                )}
                <p className="faint mt-8" style={{ fontSize: 11.5 }}>{feedback.note}</p>
              </div>
              <div className="row gap-8">
                {!allDone ? (
                  <button className="btn btn-primary btn-sm" onClick={next}>Next question</button>
                ) : (
                  <button className="btn btn-primary btn-sm" disabled={busy} onClick={finish}>See scorecard</button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* scorecard */}
      {card && (
        <div className="card stack gap-16">
          <div className="row between wrap gap-12">
            <div>
              <span className="eyebrow">Session scorecard</span>
              <h2 style={{ fontSize: 30, letterSpacing: "-0.03em", marginTop: 4 }}>
                {card.overall}<span className="faint" style={{ fontSize: 16 }}>/5 overall</span>
              </h2>
            </div>
            <button className="btn" onClick={() => setCard(null)}>New mock</button>
          </div>

          <div className="stack gap-10">
            {card.scorecard.map((c: any) => (
              <div key={c.topic} className="row gap-10">
                <span className="mono" style={{ fontSize: 12, width: 120 }}>{c.topic}</span>
                <div className="bar grow" style={{ height: 8 }}>
                  <i style={{ width: `${(c.score / 5) * 100}%`, background: c.score < 3 ? "var(--amber)" : "var(--lime)" }} />
                </div>
                <span className="mono faint" style={{ fontSize: 11.5, width: 44, textAlign: "right" }}>{c.score}/5</span>
                {c.previous != null && (
                  <span className="mono faint" style={{ fontSize: 11, width: 46 }}>
                    {c.delta > 0 ? "+" : ""}{c.delta}
                  </span>
                )}
              </div>
            ))}
          </div>

          {card.weak?.length > 0 && (
            <div className="gate">
              <p style={{ fontSize: 13.5, fontWeight: 600 }}>Pushed into memory: {card.weak.join(", ")}</p>
              <p className="muted mt-4" style={{ fontSize: 12.5 }}>
                These will reopen first in your next mock, with the score above attached.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
