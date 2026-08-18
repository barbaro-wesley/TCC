"use client";

import { useEffect, useMemo, useState } from "react";
import { loadDashboardData } from "@/lib/data";
import { brl, fullDate, number, percent } from "@/lib/format";
import { NAV_ITEMS, type DashboardData, type PageId } from "@/lib/types";
import { Icon, type IconName } from "./icons";
import { Overview } from "./pages/overview";
import { ForecastsPage } from "./pages/forecasts";
import { TimeMachinePage } from "./pages/time-machine";
import { SimulatorPage } from "./pages/simulator";
import { DataHealthPage } from "./pages/data-health";
import { ResearchPage } from "./pages/research";

const NAV_ICONS: Record<PageId, IconName> = {
  overview: "grid",
  forecasts: "chart",
  "time-machine": "clock",
  simulator: "sliders",
  "data-health": "database",
  research: "book",
};

function getHash(): PageId {
  if (typeof window === "undefined") return "overview";
  const hash = window.location.hash.slice(1) as PageId;
  return NAV_ITEMS.some((item) => item.id === hash) ? hash : "overview";
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [source, setSource] = useState<"api" | "fallback">("fallback");
  const [page, setPage] = useState<PageId>("overview");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await loadDashboardData();
      setData(result.data);
      setSource(result.source);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao carregar a plataforma");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const stored = window.localStorage.getItem("atlas-theme");
    if (stored === "light") setTheme("light");
    setPage(getHash());
    const onHash = () => setPage(getHash());
    window.addEventListener("hashchange", onHash);
    void reload();
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("atlas-theme", theme);
  }, [theme]);

  const navigate = (target: PageId) => {
    window.location.hash = target;
    setPage(target);
    setMobileOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const pageTitle = NAV_ITEMS.find((item) => item.id === page)?.label ?? "Visão geral";
  const healthySources = useMemo(() => data?.sources.filter((item) => item.status === "healthy").length ?? 0, [data]);

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><span>A</span><i /></div>
          <div><strong>ATLAS S10</strong><span>PROCUREMENT INTELLIGENCE</span></div>
        </div>
        <nav className="nav-list" aria-label="Navegação principal">
          <span className="nav-label">PLATAFORMA</span>
          {NAV_ITEMS.map((item) => (
            <button key={item.id} className={page === item.id ? "active" : ""} onClick={() => navigate(item.id)}>
              <Icon name={NAV_ICONS[item.id]} size={18}/><span>{item.label}</span>{item.id === "data-health" && data && <i className={healthySources === data.sources.length ? "status-dot healthy" : "status-dot warning"}/>} 
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="pipeline-state"><span><i className="pulse-dot"/>PIPELINE</span><strong>{data ? "OPERACIONAL" : "CONECTANDO"}</strong><small>{data ? `${healthySources}/${data.sources.length} fontes em dia` : "Aguardando dados"}</small></div>
          {data && <div className="run-meta"><span>MODEL RUN</span><code>{data.meta.runId}</code><small>{data.meta.modelVersion}</small></div>}
        </div>
      </aside>
      {mobileOpen && <button className="sidebar-backdrop" aria-label="Fechar menu" onClick={() => setMobileOpen(false)} />}

      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Abrir menu"><Icon name="menu" /></button><div><span>ATLAS S10 /</span><strong>{pageTitle.toUpperCase()}</strong></div></div>
          <div className="topbar-right">
            {data && <div className="data-status"><i className={source === "api" ? "live" : "cached"}/><span>{source === "api" ? "API CONECTADA" : "SNAPSHOT LOCAL"}</span><small>{fullDate(data.meta.generatedAt)}</small></div>}
            <button className="icon-button" onClick={() => void reload()} aria-label="Atualizar dados" title="Tentar atualizar"><Icon name="refresh" className={loading ? "spinning" : ""}/></button>
            <button className="icon-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Alternar tema"><Icon name={theme === "dark" ? "sun" : "moon"}/></button>
            <div className="avatar">WB</div>
          </div>
        </header>

        <main className="content">
          {loading && !data ? <DashboardSkeleton /> : error && !data ? <ErrorState error={error} reload={reload} /> : data ? (
            <>
              {source === "fallback" && <div className="snapshot-banner"><Icon name="info" size={15}/><span><strong>Modo snapshot.</strong> Os números abaixo vêm de artefatos nacionais versionados; não representam uma consulta ao vivo.</span><button onClick={() => navigate("data-health")}>Ver proveniência <Icon name="arrow-right" size={14}/></button></div>}
              {page === "overview" && <Overview data={data} navigate={navigate}/>} 
              {page === "forecasts" && <ForecastsPage data={data}/>} 
              {page === "time-machine" && <TimeMachinePage data={data}/>} 
              {page === "simulator" && <SimulatorPage data={data}/>} 
              {page === "data-health" && <DataHealthPage data={data}/>} 
              {page === "research" && <ResearchPage data={data}/>} 
            </>
          ) : null}
        </main>
        <footer className="footer"><span>Atlas S10 · Suporte à decisão de procurement</span><span>Previsões são probabilísticas e dependem das premissas informadas.</span></footer>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return <div className="skeleton-page"><div className="skeleton heading"/><div className="skeleton subheading"/><div className="skeleton-grid">{Array.from({length:4},(_,i)=><div className="skeleton card" key={i}/>)}</div><div className="skeleton chart-card"/></div>;
}

function ErrorState({ error, reload }: { error: string; reload: () => Promise<void> }) {
  return <div className="error-state"><div className="error-icon"><Icon name="warning" size={30}/></div><span className="eyebrow">DATA LAYER</span><h1>Não foi possível carregar os dados.</h1><p>{error}</p><button className="primary-button" onClick={() => void reload()}><Icon name="refresh"/>Tentar novamente</button></div>;
}

export function PageHeader({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children?: React.ReactNode }) {
  return <div className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{children && <div className="page-actions">{children}</div>}</div>;
}

export function SectionHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return <div className="section-header"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>;
}

export function Metric({ label, value, sub, tone = "default", icon }: { label: string; value: string; sub?: string; tone?: "default" | "positive" | "risk" | "info"; icon?: IconName }) {
  return <div className={`metric-card ${tone}`}><div className="metric-label"><span>{label}</span>{icon && <Icon name={icon} size={16}/>}</div><strong>{value}</strong>{sub && <small>{sub}</small>}</div>;
}

export function HorizonTabs({ horizon, setHorizon }: { horizon: number; setHorizon: (value: number) => void }) {
  return <div className="segmented" aria-label="Selecionar horizonte">{[7,14,30].map(value=><button key={value} className={horizon===value?"active":""} onClick={()=>setHorizon(value)} title={value===30?"Identificador legado 30: horizonte real de 4 semanas (28 dias)":undefined}>{horizonLabel(value)}</button>)}</div>;
}

export function horizonLabel(horizon: number) {
  return horizon === 30 ? "4 sem. (28d)" : `${horizon} dias`;
}

export function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  return <span className={`status-pill ${normalized}`}><i/>{status}</span>;
}

export const display = { brl, number, percent };
