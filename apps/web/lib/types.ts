export type HistoryPoint = {
  date: string;
  price: number;
  usd?: number;
  brent?: number;
  p10?: number;
  p90?: number;
  forecast?: number;
  event?: string;
};

export type Forecast = {
  horizon: number;
  point: number;
  p10: number;
  p90: number;
  changePct: number;
  probabilityUp: number;
  confidence: number;
  coverage: number;
  champion: string;
  agreement: "ALTA" | "MÉDIA" | "BAIXA";
  modelForecasts: { name: string; value: number; weight: number }[];
};

export type ModelMetric = {
  model: string;
  family: string;
  status: "champion" | "challenger" | "baseline" | "experimental" | "quarantined";
  horizon: number;
  mae: number;
  mase: number;
  rmse: number;
  directionalAccuracy: number;
  intervalCoverage?: number;
  gainVsNaive: number;
  weight: number;
};

export type Source = {
  id: string;
  name: string;
  institution: string;
  status: "healthy" | "warning" | "stale" | "unavailable";
  rows: number;
  coverage: string;
  latest: string;
  lag: string;
  quality: number;
  unit: string;
  frequency: string;
  warning?: string | null;
};

export type Research = {
  id: string;
  title: string;
  target: string;
  why: string;
  usage: string;
  confidence: "Alta" | "Média" | "Exploratória";
  evidence: string;
  limitation: string;
  href?: string;
};

export type TimeMachinePoint = {
  date: string;
  knownThrough: string;
  currentPrice: number;
  forecast: number;
  p10: number;
  p90: number;
  actual: number;
  probabilityUp: number;
  recommendation: string;
  suggestedLiters: number;
  realizedSaving: number;
  weights: { name: string; value: number }[];
  sourcesAvailable: number;
};

export type DashboardData = {
  meta: {
    generatedAt: string;
    runId: string;
    dataMode: "live" | "cached" | "demo";
    geography: string;
    geographyCode: string;
    modelVersion: string;
  };
  market: {
    currentPrice: number;
    previousPrice: number;
    weeklyChangePct: number;
    sampleSize: number;
    updatedAt: string;
    history: HistoryPoint[];
  };
  forecasts: Forecast[];
  recommendation: {
    signal: string;
    action: string;
    recommendedLiters: number;
    totalLiters: number;
    percentage: number;
    potentialSavings: number;
    timingRisk: number;
    confidence: number;
    rationale: string[];
  };
  drivers: {
    name: string;
    value: string;
    impact: number;
    direction: "up" | "down" | "neutral";
    change: string;
    detail: string;
  }[];
  briefing: { title: string; body: string; tone: "risk" | "positive" | "neutral" }[];
  models: ModelMetric[];
  backtest: {
    period: string;
    folds: number;
    refitCadence: string;
    series: { date: string; actual: number; predicted: number; p10: number; p90: number }[];
    economic: {
      strategyCost: number;
      baselineCost: number;
      saving: number;
      savingPct: number;
      decisions: number;
      positiveDecisions: number;
    };
    calibration: { bucket: string; predicted: number; observed: number }[];
  };
  timeMachine: TimeMachinePoint[];
  sources: Source[];
  qualityChecks: { name: string; status: "pass" | "warning" | "fail"; detail: string }[];
  research: Research[];
};

export const NAV_ITEMS = [
  { id: "overview", label: "Visão geral", short: "Overview" },
  { id: "forecasts", label: "Forecast & backtest", short: "Forecast" },
  { id: "time-machine", label: "Time machine", short: "Replay" },
  { id: "simulator", label: "Simulador", short: "Procurement" },
  { id: "data-health", label: "Data health", short: "Fontes" },
  { id: "research", label: "Research", short: "Método" },
] as const;

export type PageId = (typeof NAV_ITEMS)[number]["id"];
