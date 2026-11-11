"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const NAV = [
  { href: "/desk", label: "Desk" },
  { href: "/tracker", label: "Tracker" },
  { href: "/interview", label: "Interview" },
  { href: "/memory", label: "Memory" },
];

/** App chrome. Hidden on landing/onboarding so those screens can use the full width. */
export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const bare = path === "/" || path.startsWith("/onboarding");
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api
        .health()
        .then((h) => alive && setOnline(h.ok))
        .catch(() => alive && setOnline(false));
    ping();
    const t = setInterval(ping, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (bare) return <>{children}</>;

  return (
    <div className="shell">
      <aside className="rail">
        <Link href="/" className="brand">
          <span className="brand-mark">P</span>
          <span className="brand-name">PlacePilot</span>
        </Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} data-active={path.startsWith(n.href)}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="rail-foot">
          <div className="chip chip-ok" style={{ alignSelf: "flex-start" }}>
            <span style={{ width: 6, height: 6, borderRadius: 9, background: "var(--ok)" }} />
            Local demo
          </div>
          <p className="faint" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
            Data stays in this machine&apos;s SQLite file. Nothing is emailed.
          </p>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="eyebrow">AgentX 2026 · PS-06 · Team ZYRO</span>
          <div className="row gap-8">
            <span className="chip" title="The planner is deterministic unless an LLM key is configured">
              Deterministic planner
            </span>
            {online === false && <span className="chip chip-red">API offline</span>}
            {online === true && <span className="chip chip-lime">API online</span>}
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
