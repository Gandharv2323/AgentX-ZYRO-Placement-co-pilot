/** Typed API client. One place for headers, errors and polling. */

export type Fit = {
  score: number;
  label: string;
  breakdown: Record<string, number>;
  reasons: string[];
  gaps: string[];
  must_matches: string[];
};

export type Job = {
  id: string;
  title: string;
  company: string;
  location: string;
  remote: number;
  employment: string;
  stipend_month: number;
  seniority: string;
  description: string;
  url: string;
  apply_by: string;
  posted_at: string;
  required: string[];
  nice: string[];
  tags: string[];
};

export type RunEvent = {
  seq: number;
  phase: string;
  tool: string | null;
  title: string;
  detail: string;
  status: string;
  payload: any;
  created_at: string;
};

export type Run = {
  id: string;
  status: "queued" | "running" | "done" | "blocked" | "error";
  kind: string;
  command: string;
  error: string | null;
  outcome: any;
  events: RunEvent[];
  last_seq: number;
};

export type Fact = {
  id: string;
  kind: string;
  section: string;
  text: string;
  skills_json: string;
  verified: number;
  source_line: string;
};

export type Doc = {
  id: string;
  version: number;
  text: string;
  content: { sections?: Record<string, { text: string; fact_ids: string[] }[]>; not_claimed?: string[] };
  hash: string;
  passed: boolean;
  grounding: { passed: boolean; checked: number; problems: { claim: string; reason: string }[]; coverage: number };
  generated_by: string;
  created_at: string;
};

export type Application = {
  id: string;
  status: string;
  fit: Fit;
  deadline: string | null;
  job: Job;
  docs: Record<string, Doc>;
  approval: { id: string; status: string; bundle_hash: string; requested_at: string } | null;
  outbox: { id: string; recorded_at: string } | null;
  reminders: { id: string; kind: string; due_at: string }[];
  diff: { ops: { op: string; base: string[]; tailored: string[] }[]; summary: { added: number; trimmed: number; kept: number } };
};

export type ApiErrorBody = {
  error: { code: string; message: string; hint: string; details: Record<string, any> };
};

/**
 * API origin. Order: explicit NEXT_PUBLIC_API, then ?api= in the page URL,
 * then the local default. Kept out of module scope so it is resolved at call time.
 */
function baseUrl(): string {
  if (process.env.NEXT_PUBLIC_API) return process.env.NEXT_PUBLIC_API;
  if (typeof window !== "undefined") {
    const override = new URLSearchParams(window.location.search).get("api");
    if (override) {
      localStorage.setItem("placepilot.api", override);
      return override;
    }
    const stored = localStorage.getItem("placepilot.api");
    if (stored) return stored;
  }
  return "http://127.0.0.1:8010";
}

export const apiBase = baseUrl;

function BASE(): string {
  return baseUrl();
}

export class ApiError extends Error {
  status: number;
  code: string;
  hint: string;
  details: Record<string, any>;
  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    super(body?.error?.message ?? fallback);
    this.status = status;
    this.code = body?.error?.code ?? "internal";
    this.hint = body?.error?.hint ?? "";
    this.details = body?.error?.details ?? {};
  }
}

export function studentId(): string {
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem("placepilot.student");
  if (!id) {
    id = "stu_pending";
  }
  return id;
}

export async function ensureStudent(): Promise<string> {
  const existing = localStorage.getItem("placepilot.student");
  if (existing) return existing;
  const res = await fetch(`${BASE()}/api/students`, { method: "POST" });
  if (!res.ok) throw new ApiError(res.status, null, "Could not create a local student profile. Is the API running on :8000?");
  const body = await res.json();
  localStorage.setItem("placepilot.student", body.id);
  return body.id;
}

export function resetStudent(): void {
  localStorage.removeItem("placepilot.student");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const id = await ensureStudent();
  const headers: Record<string, string> = { "X-Student-Id": id, ...(init.headers as any) };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${BASE()}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(0, null, "Cannot reach the PlacePilot API on 127.0.0.1:8000. Start it with scripts/dev.ps1");
  }
  if (res.status === 404) {
    const body = await res.clone().json().catch(() => null);
    if (body?.error?.code === "student_not_found") {
      resetStudent();
    }
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(res.status, body, `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    request<{
      ok: boolean;
      jobs: number;
      live_jobs: number;
      planner: string;
      jobs_source: string;
      llm_configured: boolean;
      adzuna_configured: boolean;
    }>("/healthz"),

  me: () => request<{ student: any; facts: Fact[] }>("/api/students/me"),
  patchMe: (body: any) => request<{ student: any; facts: Fact[] }>("/api/students/me", { method: "PATCH", body: JSON.stringify(body) }),
  deleteMe: () => request<any>("/api/students/me", { method: "DELETE" }),
  exportData: () => request<any>("/api/export"),

  sampleResume: () => request<{ facts: number; contact: any }>("/api/onboarding/sample", { method: "POST" }),
  uploadResume: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ facts: number; contact: any }>("/api/onboarding/upload", { method: "POST", body: fd });
  },
  addFact: (body: any) => request<{ id: string }>("/api/facts", { method: "POST", body: JSON.stringify(body) }),
  patchFact: (id: string, body: any) => request<any>(`/api/facts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteFact: (id: string) => request<any>(`/api/facts/${id}`, { method: "DELETE" }),

  jobs: () => request<{ jobs: any[] }>("/api/jobs"),
  startRun: (body: any) => request<{ run_id: string; kind: string }>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  run: (id: string, after = 0) => request<Run>(`/api/runs/${id}?after_seq=${after}`),
  tools: () => request<{ tools: { name: string; risk: string; detail: string }[] }>("/api/agent/tools"),

  applications: () => request<{ applications: any[] }>("/api/applications"),
  application: (id: string) => request<Application>(`/api/applications/${id}`),
  tailor: (jobIds: string[]) => request<{ run_id: string; application_ids: string[] }>("/api/applications", { method: "POST", body: JSON.stringify({ job_ids: jobIds }) }),
  regenerate: (id: string) => request<{ run_id: string }>(`/api/applications/${id}/regenerate`, { method: "POST" }),
  decide: (id: string, body: any) => request<any>(`/api/applications/${id}/approvals`, { method: "POST", body: JSON.stringify(body) }),
  send: (id: string) => request<any>(`/api/applications/${id}/send`, { method: "POST" }),

  interviews: () => request<{ topics: any[] }>("/api/interviews/weak-topics"),
  startInterview: (body: any) => request<{ interview_id: string; questions: { id: string; topic: string; text: string; provenance: string }[] }>("/api/interviews", { method: "POST", body: JSON.stringify(body) }),
  interview: (id: string) => request<any>(`/api/interviews/${id}`),
  answer: (id: string, body: any) => request<any>(`/api/interviews/${id}/answers`, { method: "POST", body: JSON.stringify(body) }),
  completeInterview: (id: string) => request<any>(`/api/interviews/${id}/complete`, { method: "POST" }),

  memory: () => request<any>("/api/memory"),
  reset: () => request<any>("/api/demo/reset", { method: "POST" }),
  calendarUrl: () => `${BASE()}/api/calendar.ics`,
  resumeUrl: (id: string) => `${BASE()}/api/applications/${id}/resume.html`,
  apiBase,
};
