"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function Landing() {
  const [ready, setReady] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    api.health().then((h) => setOnline(h.ok)).catch(() => setOnline(false));
    api
      .me()
      .then((me) => setReady(me.facts.length > 0))
      .catch(() => setReady(false));
  }, []);

  return (
    <div className="landing">
      <nav className="landing-nav">
        <div className="row gap-10">
          <span className="brand-mark">P</span>
          <span className="brand-name">PlacePilot</span>
        </div>
        <div className="row gap-12">
          <span className="eyebrow">AgentX 2026 · PS-06</span>
          <Link className="btn btn-sm" href="/onboarding">Start</Link>
        </div>
      </nav>

      <section className="hero">
        <div className="stack gap-24">
          <div className="stack gap-16">
            <span className="eyebrow">Placement co-pilot · Agentic AI · Career Tech</span>
            <h1>A placement agent that asks before it applies.</h1>
            <p className="lede">
              Upload a resume, name the roles. PlacePilot searches openings, tailors each application
              from your verified facts, tracks every deadline and rehearses the interview.
              <span style={{ color: "var(--text)" }}> It sends nothing without your yes.</span>
            </p>
          </div>

          <div className="row gap-10 wrap">
            <Link className="btn btn-primary" href="/onboarding">
              {ready ? "Open the desk" : "Upload a resume"}
            </Link>
            <Link className="btn" href="/tracker">See the tracker</Link>
            {online === false && <span className="chip chip-red">API offline — run scripts\\dev.ps1</span>}
          </div>

          <div className="stats">
            <div className="stat">
              <b>44%</b>
              <span>of Indian graduates are not job-ready (India Skills Report 2026)</span>
            </div>
            <div className="stat">
              <b>&lt;5 min</b>
              <span>target per tailored application vs. a manual rewrite</span>
            </div>
            <div className="stat">
              <b>100%</b>
              <span>of sends require your approval, enforced at the API layer</span>
            </div>
          </div>
        </div>

        <div className="hero-art">
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="row between" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
              <span className="mono faint" style={{ fontSize: 11 }}>app_7f3a · AI/ML Intern</span>
              <span className="chip chip-lime">fit 85</span>
            </div>
            <div style={{ padding: 16 }}>
              <p className="faint" style={{ fontSize: 11.5, marginBottom: 6 }}>TAILORED · 2 of 12 lines changed</p>
              <div className="diff">
                <span className="same">- Built a churn model in Python</span>
                <span className="ins">+ Built a churn model in Python with scikit-learn</span>
                <span className="ins">+ recall 0.61 → 0.74 on a 40k-row dataset</span>
                <span className="del">- CourseCart (small React project)</span>
              </div>
            </div>
            <div className="gate gate-blocked" style={{ margin: 16, marginTop: 0 }}>
              <div className="row between gap-12">
                <div>
                  <p className="mono" style={{ fontSize: 12, color: "var(--red)" }}>HTTP 422 · approval_required</p>
                  <p className="muted mt-4" style={{ fontSize: 12.5 }}>
                    Send blocked until you approve this bundle.
                  </p>
                </div>
                <span className="mono faint" style={{ fontSize: 11 }}>bndl_9c2e…</span>
              </div>
            </div>
            <div className="row between" style={{ padding: "12px 16px", borderTop: "1px solid var(--line)" }}>
              <span className="faint" style={{ fontSize: 12 }}>Kubernetes not added — not in your facts</span>
              <span className="chip">Review</span>
            </div>
          </div>
          <p className="faint mt-12" style={{ fontSize: 11.5, textAlign: "center" }}>
            Real interface. The gate is a database trigger, not a toast.
          </p>
        </div>
      </section>

      <footer style={{ marginTop: "auto", borderTop: "1px solid var(--line)", padding: "18px 34px" }}>
        <div className="row between wrap gap-12">
          <span className="faint" style={{ fontSize: 12 }}>
            Team ZYRO · Vishwakarma Institute of Technology, Pune · team code 79257B
          </span>
          <span className="faint" style={{ fontSize: 12 }}>
            Gandharv Shinde · Swapnil Gangate · Atif Panhalkar · Siddesh Shirote
          </span>
        </div>
        <p className="faint mt-8" style={{ fontSize: 11.5 }}>
          Local demo: everything stays in a SQLite file on this machine. No email is ever sent.
        </p>
      </footer>
    </div>
  );
}
