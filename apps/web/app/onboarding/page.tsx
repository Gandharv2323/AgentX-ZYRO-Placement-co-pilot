"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type Fact } from "@/lib/api";
import { ErrorNote, Field, Spinner } from "@/components/ui";

const ROLE_OPTIONS = [
  { value: "ai", label: "AI / ML" },
  { value: "data", label: "Data / Analytics" },
  { value: "backend", label: "Backend" },
  { value: "frontend", label: "Frontend" },
  { value: "fullstack", label: "Full stack" },
];
const CITY_OPTIONS = ["Pune", "Mumbai", "Bengaluru", "Hyderabad", "Remote"];

export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [cities, setCities] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<any>(null);
  const [newFact, setNewFact] = useState("");
  const [contact, setContact] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () =>
    api
      .me()
      .then((me) => {
        setFacts(me.facts);
        if (me.facts.length) setStep(2);
        setRoles(me.student.roles ?? []);
        setCities(me.student.locations ?? []);
        setContact({ name: me.student.name, email: me.student.email, location: me.student.location });
      })
      .catch((e) => setError(e));

  useEffect(() => {
    load();
  }, []);

  async function ingest(fn: () => Promise<any>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      setStep(2);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const verified = facts.filter((f) => f.verified).length;

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: "34px 24px 60px" }}>
      <div className="row between wrap gap-12">
        <Link href="/" className="row gap-10">
          <span className="brand-mark">P</span>
          <span className="brand-name">PlacePilot</span>
        </Link>
        <div className="row gap-8">
          {[1, 2, 3].map((n) => (
            <span key={n} className={`chip${step >= n ? " chip-lime" : ""}`}>
              {n}. {["Resume", "Facts", "Targets"][n - 1]}
            </span>
          ))}
        </div>
      </div>

      {error && <div className="mt-20"><ErrorNote error={error} /></div>}

      {step === 1 && (
        <section className="mt-32 stack gap-20">
          <div className="stack gap-8">
            <h1 style={{ fontSize: 34, letterSpacing: "-0.03em" }}>Give the agent something true to work with.</h1>
            <p className="muted" style={{ maxWidth: "62ch" }}>
              Only verified facts can enter a tailored resume. Anything else shows up as a gap — not a guess.
            </p>
          </div>

          <div className="card stack gap-16">
            <div className="row between wrap gap-12">
              <div>
                <strong style={{ fontSize: 15 }}>Use the sample resume</strong>
                <p className="muted" style={{ fontSize: 13 }}>Aarav Mehta, final-year CSE. 13 facts, no real person&apos;s data.</p>
              </div>
              <button className="btn btn-primary" disabled={busy} onClick={() => ingest(() => api.sampleResume())}>
                {busy ? "Reading…" : "Load sample"}
              </button>
            </div>
            <hr className="divider" />
            <div className="row between wrap gap-12">
              <div>
                <strong style={{ fontSize: 15 }}>Or upload your own PDF</strong>
                <p className="muted" style={{ fontSize: 13 }}>Text PDFs only, up to 5 MB. Scans are rejected, not guessed.</p>
              </div>
              <div className="row gap-8">
                <input ref={fileRef} type="file" accept="application/pdf" hidden
                       onChange={(e) => {
                         const f = e.target.files?.[0];
                         if (f) ingest(() => api.uploadResume(f));
                       }} />
                <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
                  {busy ? "Reading…" : "Choose PDF"}
                </button>
              </div>
            </div>
            {busy && <Spinner label="Extracting text and splitting it into facts" />}
          </div>
        </section>
      )}

      {step === 2 && (
        <section className="mt-32 stack gap-16">
          <div className="row between wrap gap-12">
            <div>
              <h1 style={{ fontSize: 30, letterSpacing: "-0.03em" }}>Check what it read.</h1>
              <p className="muted mt-4" style={{ fontSize: 13.5 }}>
                {facts.length} facts · {verified} verified
                {contact?.name ? ` · ${contact.name}` : ""}
                {contact?.location ? ` · ${contact.location}` : ""}
              </p>
            </div>
            <span className="chip chip-lime">Only checked facts get used</span>
          </div>

          <div className="card card-tight stack">
            {facts.map((f) => (
              <div key={f.id} className="row gap-12" style={{ padding: "9px 4px", borderBottom: "1px solid #17171c" }}>
                <input
                  type="checkbox"
                  checked={!!f.verified}
                  aria-label={`Use this fact: ${f.text.slice(0, 60)}`}
                  onChange={async (e) => {
                    const next = e.target.checked;
                    setFacts((prev) => prev.map((x) => (x.id === f.id ? { ...x, verified: next ? 1 : 0 } : x)));
                    await api.patchFact(f.id, { verified: next });
                  }}
                  style={{ width: 16, height: 16, accentColor: "#c6ff00", flex: "none" }}
                />
                <span className="chip" style={{ minWidth: 92, justifyContent: "center", fontSize: 11 }}>{f.kind}</span>
                <span className="grow" style={{ fontSize: 13.5, opacity: f.verified ? 1 : 0.45 }}>{f.text}</span>
                <button
                  className="btn btn-ghost btn-sm"
                  aria-label="Delete fact"
                  onClick={async () => {
                    await api.deleteFact(f.id);
                    setFacts((prev) => prev.filter((x) => x.id !== f.id));
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
            <div className="row gap-8 mt-12">
              <input
                className="input"
                placeholder="Add a fact that the parser missed (e.g. a project or skill)"
                value={newFact}
                onChange={(e) => setNewFact(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === "Enter" && newFact.trim()) {
                    await api.addFact({ text: newFact.trim(), kind: "skill", section: "skills" });
                    setNewFact("");
                    load();
                  }
                }}
              />
              <button
                className="btn"
                disabled={!newFact.trim()}
                onClick={async () => {
                  await api.addFact({ text: newFact.trim(), kind: "skill", section: "skills" });
                  setNewFact("");
                  load();
                }}
              >
                Add
              </button>
            </div>
          </div>

          <div className="row gap-10">
            <button className="btn btn-primary" disabled={!verified} onClick={() => setStep(3)}>
              Continue with {verified} facts
            </button>
            <button className="btn btn-ghost" onClick={() => setStep(1)}>Replace resume</button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="mt-32 stack gap-16">
          <h1 style={{ fontSize: 30, letterSpacing: "-0.03em" }}>What should it aim at?</h1>
          <p className="muted" style={{ fontSize: 13.5 }}>These steer search and the interview mix. You can change them later.</p>

          <div className="card stack gap-16">
            <div>
              <span className="label">Target roles</span>
              <div className="row gap-8 wrap">
                {ROLE_OPTIONS.map((r) => {
                  const on = roles.includes(r.value);
                  return (
                    <button key={r.value} className={`chip${on ? " chip-lime" : ""}`}
                            style={{ cursor: "pointer", padding: "6px 12px" }}
                            onClick={() => setRoles((p) => (on ? p.filter((x) => x !== r.value) : [...p, r.value]))}>
                      {r.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <div>
              <span className="label">Where you can work</span>
              <div className="row gap-8 wrap">
                {CITY_OPTIONS.map((c) => {
                  const on = cities.includes(c);
                  return (
                    <button key={c} className={`chip${on ? " chip-lime" : ""}`}
                            style={{ cursor: "pointer", padding: "6px 12px" }}
                            onClick={() => setCities((p) => (on ? p.filter((x) => x !== c) : [...p, c]))}>
                      {c}
                    </button>
                  );
                })}
              </div>
            </div>
            <div style={{ maxWidth: 320 }}>
              <Field label="Your name" value={contact?.name ?? ""} onChange={(v) => setContact({ ...contact, name: v })} placeholder="As it should appear" />
            </div>
          </div>

          <div className="row gap-10">
            <button
              className="btn btn-primary"
              disabled={!roles.length || busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.patchMe({ roles, locations: cities, name: contact?.name, seniority: "intern" });
                  router.push("/desk");
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Saving…" : "Open the desk"}
            </button>
            <button className="btn btn-ghost" onClick={() => setStep(2)}>Back</button>
          </div>
        </section>
      )}
    </div>
  );
}
