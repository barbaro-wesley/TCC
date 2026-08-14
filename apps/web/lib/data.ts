import type { DashboardData } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";

function isDashboardData(value: unknown): value is DashboardData {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<DashboardData>;
  return Boolean(data.market?.history?.length && data.forecasts?.length && data.sources);
}

async function fetchJson(url: string, signal: AbortSignal) {
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<unknown>;
}

export async function loadDashboardData(): Promise<{ data: DashboardData; source: "api" | "fallback" }> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 3500);

  try {
    const endpoints = API_BASE
      ? [`${API_BASE}/api/dashboard`, `${API_BASE}/dashboard`]
      : ["/api/dashboard", "http://127.0.0.1:8000/api/dashboard"];
    for (const endpoint of endpoints) {
      try {
        const payload = await fetchJson(endpoint, controller.signal);
        const candidate = (payload as { data?: unknown }).data ?? payload;
        if (isDashboardData(candidate)) return { data: candidate, source: "api" };
      } catch {
        // A local, provenance-labelled snapshot is the deliberate offline path.
      }
    }
  } finally {
    window.clearTimeout(timer);
  }

  const fallback = await fetch("/demo-data.json", { cache: "no-store" });
  if (!fallback.ok) throw new Error("Snapshot local indisponível");
  const data: unknown = await fallback.json();
  if (!isDashboardData(data)) throw new Error("Snapshot local inválido");
  return { data, source: "fallback" };
}
