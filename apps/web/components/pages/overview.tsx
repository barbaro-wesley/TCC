"use client";

import { useMemo, useState } from "react";
import { brl, compact, fullDate, liters, percent } from "@/lib/format";
import type { DashboardData, PageId } from "@/lib/types";
import { Donut, MarketChart } from "../charts";
import { Icon } from "../icons";
import { HorizonTabs, Metric, PageHeader, SectionHeader } from "../dashboard";

export function Overview({ data, navigate }: { data: DashboardData; navigate: (page: PageId) => void }) {
  const [horizon, setHorizon] = useState(7);
  const forecast = data.forecasts.find((item) => item.horizon === horizon) ?? data.forecasts[0];
  const latestHistory = useMemo(() => data.market.history.slice(-25), [data.market.history]);
  const rec = data.recommendation;

  return <div className="page-enter">
    <PageHeader eyebrow={`DIESEL S10 · ${data.meta.geographyCode}`} title="O mercado pede cautela, não paralisia." description={`Leitura semanal para ${data.meta.geography}. Dados conhecidos até ${fullDate(data.market.updatedAt)}.`}>
      <div className="region-select"><span>REGIÃO</span><strong>{data.meta.geographyCode}</strong><Icon name="chevron" size={14}/></div>
      <HorizonTabs horizon={horizon} setHorizon={setHorizon}/>
    </PageHeader>

    <section className="hero-grid">
      <div className="hero-price panel">
        <div className="hero-top"><div><span className="panel-kicker">PREÇO ATUAL · REVENDA</span><div className="big-price">{brl.format(data.market.currentPrice)}<small>/L</small></div><span className={`delta ${data.market.weeklyChangePct <= 0 ? "down" : "up"}`}><Icon name={data.market.weeklyChangePct <= 0 ? "arrow-down" : "arrow-up"} size={14}/>{percent(data.market.weeklyChangePct)} na semana</span></div><div className="sample-meta"><span>AMOSTRA</span><strong>{data.market.sampleSize}</strong><small>postos</small></div></div>
        <MarketChart history={latestHistory}/>
        <div className="hero-foot"><span><i className="legend-line green"/>ANP realizado</span><span><i className="legend-line blue dash"/>Forecast</span><span><i className="legend-block"/>Intervalo P10–P90</span></div>
      </div>

      <div className="decision-card panel">
        <div className="decision-head"><span className="panel-kicker">DECISÃO OPERACIONAL</span><span className="confidence-pill"><Icon name="shield" size={14}/>{rec.confidence}% confiança</span></div>
        <div className="signal"><i/><span>{rec.signal}</span></div>
        <h2>{rec.action}</h2>
        <p>Dadas as premissas operacionais, uma posição parcial oferece o melhor equilíbrio entre custo esperado e flexibilidade.</p>
        <div className="buy-callout"><div><span>COMPRA SUGERIDA AGORA</span><strong>{liters(rec.recommendedLiters)}</strong><small>de {liters(rec.totalLiters)} previstos</small></div><Donut value={rec.percentage} label="da demanda" size={104}/></div>
        <div className="decision-economics"><div><span>Economia potencial</span><strong className="positive-text">{brl.format(rec.potentialSavings)}</strong></div><div><span>Risco de timing</span><strong>{brl.format(rec.timingRisk)}</strong></div></div>
        <button className="primary-button full" onClick={()=>navigate("simulator")}>Simular minha operação <Icon name="arrow-right" size={16}/></button>
      </div>
    </section>

    <section className="forecast-strip">
      <Metric label={`PREVISÃO ${horizon} DIAS`} value={`${brl.format(forecast.point)}/L`} sub={percent(forecast.changePct) + " vs. atual"} tone={forecast.changePct > .5 ? "risk" : forecast.changePct < 0 ? "positive" : "default"}/>
      <Metric label="PROB. DE ALTA" value={`${forecast.probabilityUp}%`} sub="Alta relevante > 0,5%" tone={forecast.probabilityUp > 65 ? "risk" : "default"}/>
      <Metric label="INTERVALO P10–P90" value={`${brl.format(forecast.p10)} — ${brl.format(forecast.p90)}`} sub={`${forecast.coverage}% de cobertura histórica`} tone="info"/>
      <Metric label="MODEL AGREEMENT" value={forecast.agreement} sub={`${forecast.champion} · champion`} icon="shield"/>
    </section>

    <section className="two-col section-gap">
      <div className="panel briefing-panel">
        <SectionHeader title="O que mudou?" subtitle="Leitura automática dos movimentos mais relevantes" action={<button className="text-button" onClick={()=>navigate("forecasts")}>Abrir análise <Icon name="arrow-right" size={14}/></button>}/>
        <div className="briefing-list">{data.briefing.map((item,index)=><article key={item.title} className={item.tone}><span>0{index+1}</span><div><h3>{item.title}</h3><p>{item.body}</p></div></article>)}</div>
      </div>
      <div className="panel drivers-panel">
        <SectionHeader title="Drivers de mercado" subtitle="Contribuição direcional para o cenário atual"/>
        <div className="drivers-list">{data.drivers.map(driver=><div className="driver-row" key={driver.name}><div className={`driver-icon ${driver.direction}`}><Icon name={driver.direction === "up" ? "arrow-up" : driver.direction === "down" ? "arrow-down" : "arrow-right"}/></div><div className="driver-main"><div><strong>{driver.name}</strong><span>{driver.change}</span></div><small>{driver.detail}</small></div><strong>{driver.value}</strong></div>)}</div>
      </div>
    </section>

    <section className="trust-bar panel section-gap"><div><Icon name="shield"/><span><strong>Sem olhar para o futuro.</strong> Todas as features respeitam <code>available_at ≤ forecast_origin</code>.</span></div><div><span>26</span><small>folds temporais</small></div><div><span>{compact(data.sources.reduce((sum,item)=>sum+item.rows,0))}</span><small>observações rastreadas</small></div><button onClick={()=>navigate("research")}>Ver metodologia <Icon name="arrow-right" size={15}/></button></section>
  </div>;
}
