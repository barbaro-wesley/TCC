"use client";

import { useId, useMemo, useState } from "react";
import { brl, shortDate } from "@/lib/format";
import type { HistoryPoint } from "@/lib/types";

type ChartPoint = { date: string; value: number; p10?: number; p90?: number; secondary?: number };

const W = 900;
const H = 310;
const PAD = { top: 22, right: 18, bottom: 34, left: 46 };

function geometry(data: ChartPoint[]) {
  const values = data.flatMap((d) => [d.value, d.p10, d.p90].filter((v): v is number => typeof v === "number"));
  let min = Math.min(...values);
  let max = Math.max(...values);
  const range = max - min || 1;
  min -= range * 0.14;
  max += range * 0.14;
  const x = (index: number) => PAD.left + (index / Math.max(1, data.length - 1)) * (W - PAD.left - PAD.right);
  const y = (value: number) => PAD.top + ((max - value) / (max - min)) * (H - PAD.top - PAD.bottom);
  const path = (key: "value" | "p10" | "p90") =>
    data
      .map((point, index) => {
        const value = point[key];
        return typeof value === "number" ? `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(value).toFixed(1)}` : "";
      })
      .filter(Boolean)
      .join(" ");
  return { min, max, x, y, path };
}

export function MarketChart({ history, mode = "price" }: { history: HistoryPoint[]; mode?: "price" | "drivers" }) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId().replaceAll(":", "");
  const data = useMemo<ChartPoint[]>(() => {
    if (mode === "drivers") {
      const valid = history.filter((item) => item.usd && item.brent);
      const baseUsd = valid[0]?.usd ?? 1;
      const baseBrent = valid[0]?.brent ?? 1;
      return valid.map((item) => ({
        date: item.date,
        value: ((item.brent ?? baseBrent) / baseBrent) * 100,
        secondary: ((item.usd ?? baseUsd) / baseUsd) * 100,
      }));
    }
    return history.map((item) => ({ date: item.date, value: item.forecast ?? item.price, p10: item.p10, p90: item.p90 }));
  }, [history, mode]);
  const g = geometry(data);
  const split = mode === "price" ? data.findIndex((item) => typeof item.p10 === "number") : -1;
  const historical = split > 0 ? data.slice(0, split) : data;
  const forecastData = split > 0 ? [data[split - 1], ...data.slice(split)] : [];
  const histPath = historical.map((p, index) => `${index === 0 ? "M" : "L"}${g.x(index)},${g.y(p.value)}`).join(" ");
  const forecastPath = forecastData.map((p, index) => `${index === 0 ? "M" : "L"}${g.x(index + split - 1)},${g.y(p.value)}`).join(" ");
  const band = forecastData.length
    ? [
        ...forecastData.map((p, index) => `${index === 0 ? "M" : "L"}${g.x(index + split - 1)},${g.y(p.p90 ?? p.value)}`),
        ...forecastData.slice().reverse().map((p, revIndex) => {
          const index = forecastData.length - 1 - revIndex;
          return `L${g.x(index + split - 1)},${g.y(p.p10 ?? p.value)}`;
        }),
        "Z",
      ].join(" ")
    : "";
  const secondPath = mode === "drivers" ? data.map((p, i) => `${i === 0 ? "M" : "L"}${g.x(i)},${g.y(p.secondary ?? p.value)}`).join(" ") : "";
  const ticks = Array.from({ length: 5 }, (_, i) => g.min + ((g.max - g.min) * i) / 4).reverse();
  const active = hover === null ? null : data[hover];

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={mode === "price" ? "Histórico e previsão do Diesel S10" : "Índice de Brent e câmbio"} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={`area-${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--green)" stopOpacity=".2"/><stop offset="1" stopColor="var(--green)" stopOpacity="0"/></linearGradient>
          <linearGradient id={`band-${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--blue)" stopOpacity=".22"/><stop offset="1" stopColor="var(--blue)" stopOpacity=".05"/></linearGradient>
        </defs>
        {ticks.map((tick) => <g key={tick}><line x1={PAD.left} y1={g.y(tick)} x2={W - PAD.right} y2={g.y(tick)} className="gridline"/><text x={PAD.left - 10} y={g.y(tick) + 4} textAnchor="end" className="axis-label">{mode === "price" ? tick.toFixed(2) : tick.toFixed(0)}</text></g>)}
        {[0, Math.floor((data.length - 1) / 3), Math.floor(((data.length - 1) * 2) / 3), data.length - 1].map((index) => <text key={index} x={g.x(index)} y={H - 8} textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"} className="axis-label">{shortDate(data[index].date)}</text>)}
        {mode === "price" && <path d={`${histPath} L${g.x(historical.length - 1)},${H - PAD.bottom} L${PAD.left},${H - PAD.bottom} Z`} fill={`url(#area-${id})`} />}
        {band && <path d={band} fill={`url(#band-${id})`} />}
        <path d={histPath} className="line-primary" />
        {forecastPath && <path d={forecastPath} className="line-forecast" />}
        {secondPath && <path d={secondPath} className="line-secondary" />}
        {data.map((point, index) => (
          <rect key={point.date} x={g.x(index) - Math.max(4, (W - PAD.left - PAD.right) / data.length / 2)} y={PAD.top} width={Math.max(8, (W - PAD.left - PAD.right) / data.length)} height={H - PAD.top - PAD.bottom} fill="transparent" onMouseEnter={() => setHover(index)} />
        ))}
        {hover !== null && active && <g><line x1={g.x(hover)} y1={PAD.top} x2={g.x(hover)} y2={H - PAD.bottom} className="crosshair"/><circle cx={g.x(hover)} cy={g.y(active.value)} r="4" className="active-dot"/></g>}
        {split > 0 && <g><line x1={g.x(split - 0.5)} y1={PAD.top} x2={g.x(split - 0.5)} y2={H - PAD.bottom} className="forecast-divider"/><text x={g.x(split - 0.5) + 8} y={PAD.top + 10} className="forecast-label">PREVISÃO</text></g>}
      </svg>
      {active && hover !== null && (
        <div className="chart-tooltip" style={{ left: `${Math.min(82, Math.max(8, (g.x(hover) / W) * 100))}%` }}>
          <span>{shortDate(active.date)}</span>
          <strong>{mode === "price" ? brl.format(active.value) : `Brent ${active.value.toFixed(1)}`}</strong>
          {mode === "drivers" && <small>USD {active.secondary?.toFixed(1)}</small>}
          {active.p10 !== undefined && <small>P10–P90 {brl.format(active.p10)} — {brl.format(active.p90 ?? active.value)}</small>}
        </div>
      )}
      {mode === "drivers" && <div className="chart-legend"><span><i className="legend-line green"/>Brent (índice)</span><span><i className="legend-line blue"/>USD/BRL (índice)</span></div>}
    </div>
  );
}

export function BacktestChart({ series }: { series: { date: string; actual: number; predicted: number; p10: number; p90: number }[] }) {
  const data = series.map((item) => ({ date: item.date, value: item.actual, p10: item.p10, p90: item.p90, secondary: item.predicted }));
  const g = geometry(data);
  const actual = data.map((p, i) => `${i === 0 ? "M" : "L"}${g.x(i)},${g.y(p.value)}`).join(" ");
  const predicted = data.map((p, i) => `${i === 0 ? "M" : "L"}${g.x(i)},${g.y(p.secondary ?? p.value)}`).join(" ");
  const band = [...data.map((p, i) => `${i === 0 ? "M" : "L"}${g.x(i)},${g.y(p.p90 ?? p.value)}`), ...data.slice().reverse().map((p, ri) => { const i = data.length - 1 - ri; return `L${g.x(i)},${g.y(p.p10 ?? p.value)}`; }), "Z"].join(" ");
  const ticks = Array.from({ length: 5 }, (_, i) => g.min + ((g.max - g.min) * i) / 4).reverse();
  return <div className="chart-wrap"><svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Previsões do backtest contra valor realizado">
    {ticks.map((tick) => <g key={tick}><line x1={PAD.left} y1={g.y(tick)} x2={W-PAD.right} y2={g.y(tick)} className="gridline"/><text x={PAD.left-10} y={g.y(tick)+4} textAnchor="end" className="axis-label">{tick.toFixed(2)}</text></g>)}
    <path d={band} className="backtest-band"/><path d={predicted} className="line-forecast"/><path d={actual} className="line-primary"/>
    {[0,Math.floor(data.length/2),data.length-1].map(i=><text key={i} x={g.x(i)} y={H-8} textAnchor={i===0?"start":i===data.length-1?"end":"middle"} className="axis-label">{shortDate(data[i].date)}</text>)}
  </svg><div className="chart-legend"><span><i className="legend-line green"/>Realizado</span><span><i className="legend-line blue dash"/>Previsto</span><span><i className="legend-block"/>P10–P90</span></div></div>;
}

export function CalibrationChart({ data }: { data: { bucket: string; predicted: number; observed: number }[] }) {
  return <div className="calibration-chart"><div className="calibration-plot"><div className="calibration-diagonal"/>{data.map((point) => <div key={point.bucket} className="calibration-dot" style={{ left: `${point.predicted}%`, bottom: `${point.observed}%` }} title={`${point.bucket}: previsto ${point.predicted}%, observado ${point.observed}%`} />)}</div><div className="calibration-labels"><span>0%</span><span>Probabilidade prevista</span><span>100%</span></div></div>;
}

export function Donut({ value, label, tone = "green", size = 96 }: { value: number; label: string; tone?: "green" | "amber" | "blue"; size?: number }) {
  const radius = 39;
  const circumference = 2 * Math.PI * radius;
  return <div className={`donut ${tone}`} style={{ width: size, height: size }}><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r={radius} className="donut-track"/><circle cx="50" cy="50" r={radius} className="donut-value" strokeDasharray={circumference} strokeDashoffset={circumference * (1-value/100)}/></svg><div><strong>{Math.round(value)}%</strong><span>{label}</span></div></div>;
}
