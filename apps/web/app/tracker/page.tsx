"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Chip, Empty, ErrorNote, deadlineLabel, deadlineTone } from "@/components/ui";

export default function Tracker() {
  const [apps, setApps] = useState<any[]>([]);
  const [error, setError] = useState<any>(null);

  useEffect(() => {
    api.applications().then((r) => setApps(r.applications)).catch(setError);
  }, []);

  const unsent = apps.filter((a) => a.status !== "sent");
  const closed = apps.filter((a) => a.status === "sent");

  return (
    <div className="stack gap-16">
      <div className="row between wrap gap-12">
        <div>
          <h1 style={{ fontSize: 24, letterSpacing: "-0.03em" }}>Tracker</h1>
          <p className="faint" style={{ fontSize: 13 }}>Deadlines, approvals and what actually left the machine.</p>
        </div>
        <a className="btn btn-sm" href={`${api.apiBase()}/api/calendar.ics`} download>
          Download .ics
        </a>
      </div>

      {error && <ErrorNote error={error} />}

      <div className="row gap-8 wrap">
        <Chip>{unsent.length} open</Chip>
        <Chip tone="ok">{closed.length} sent</Chip>
      </div>

      {!apps.length ? (
        <Empty title="Nothing tracked yet." body="Rank openings on the desk and tailor one — it lands here with its deadline."
               action={<Link className="btn btn-sm" href="/desk">Go to desk</Link>} />
      ) : (
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data">
            <thead>
              <tr>
                <th>Role</th><th>Company</th><th>Fit</th><th>Deadline</th><th>Approval</th><th>Status</th><th />
              </tr>
            </thead>
            <tbody>
              {(unsent as any[]).concat(closed as any[]).map((a) => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 500 }}>{a.title}</td>
                  <td className="mono faint" style={{ fontSize: 12 }}>{a.company}</td>
                  <td><span className="mono" style={{ fontSize: 12.5 }}>{a.fit_score}</span></td>
                  <td>
                    <Chip tone={deadlineTone(a.days_left) as any}>{deadlineLabel(a.days_left)}</Chip>
                  </td>
                  <td>
                    <span className={`chip${a.approval === "approved" ? " chip-lime" : ""}`} style={{ fontSize: 11 }}>
                      {a.approval ?? "not requested"}
                    </span>
                  </td>
                  <td>
                    <span className={`chip${a.status === "sent" ? " chip-ok" : ""}`} style={{ fontSize: 11 }}>
                      {a.status}
                    </span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <Link className="btn btn-ghost btn-sm" href={`/applications/${a.id}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card card-tight">
        <span className="eyebrow">What &quot;sent&quot; means here</span>
        <p className="muted mt-4" style={{ fontSize: 12.5, maxWidth: "80ch" }}>
          In this demo, sending writes an immutable record to a local outbox after your approval.
          No email is dispatched and no third party is contacted. The approval gate is enforced by the
          API and again by a database trigger.
        </p>
      </div>
    </div>
  );
}
