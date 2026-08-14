"use client";

import { useMemo, useState } from "react";
import { brl, percent } from "@/lib/format";
import type { DashboardData } from "@/lib/types";
import { BacktestChart, CalibrationChart, Donut } from "../charts";
import { HorizonTabs, Metric, PageHeader, SectionHeader, StatusPill } from "../dashboard";
import { Icon } from "../icons";

export function ForecastsPage({ data }: { data: DashboardData }) {
  const [horizon,setHorizon]=useState(7);
  const forecast=data.forecasts.find(item=>item.horizon===horizon)??data.forecasts[0];
  const models=useMemo(()=>data.models.filter(item=>item.horizon===horizon).sort((a,b)=>a.mae-b.mae),[data.models,horizon]);
  const maxMae=Math.max(...models.map(item=>item.mae),.01);
  return <div className="page-enter">
    <PageHeader eyebrow="MODEL LAB" title="Previsão que mostra o próprio erro." description="Cada resultado é comparado no mesmo dataset, horizonte e protocolo temporal."><HorizonTabs horizon={horizon} setHorizon={setHorizon}/></PageHeader>
    <section className="forecast-summary panel">
      <div className="forecast-number"><span>PREVISÃO {horizon} DIAS</span><strong>{brl.format(forecast.point)}<small>/L</small></strong><em className={forecast.changePct>0?"risk-text":"positive-text"}>{percent(forecast.changePct)} vs. preço atual</em></div>
      <div className="range-visual"><div className="range-labels"><span>P10 <strong>{brl.format(forecast.p10)}</strong></span><span>POINT <strong>{brl.format(forecast.point)}</strong></span><span>P90 <strong>{brl.format(forecast.p90)}</strong></span></div><div className="range-track"><i style={{left:`${((forecast.point-forecast.p10)/(forecast.p90-forecast.p10))*100}%`}}/></div><p>80% da distribuição estimada · cobertura histórica {forecast.coverage}%</p></div>
      <Donut value={forecast.probabilityUp} label="prob. alta" tone={forecast.probabilityUp>65?"amber":"blue"}/><Donut value={forecast.confidence} label="confiança" tone="green"/>
    </section>
    <section className="four-grid section-gap"><Metric label="CHAMPION" value={forecast.champion} sub={`Selecionado para ${horizon}d`} tone="positive"/><Metric label="MODEL AGREEMENT" value={forecast.agreement} sub={`Amplitude ${brl.format(Math.max(...forecast.modelForecasts.map(i=>i.value))-Math.min(...forecast.modelForecasts.map(i=>i.value)))}`}/><Metric label="COBERTURA P10–P90" value={`${forecast.coverage}%`} sub="Alvo nominal: 80%" tone="info"/><Metric label="VALIDAÇÃO" value="Rolling-origin" sub={`${data.backtest.folds} folds · sem shuffle`}/></section>
    <section className="panel section-gap"><SectionHeader title="Backtest fora da amostra" subtitle={`${data.backtest.period} · ${data.backtest.refitCadence}`} action={<div className="chart-legend top"><span><i className="legend-line green"/>Realizado</span><span><i className="legend-line blue dash"/>Previsto</span></div>}/><BacktestChart series={data.backtest.series}/></section>
    <section className="two-col section-gap">
      <div className="panel leaderboard"><SectionHeader title="Leaderboard" subtitle={`Comparação no horizonte de ${horizon} dias`}/>{models.length?<div className="model-table"><div className="table-head"><span>Modelo</span><span>MAE</span><span>MASE</span><span>Direção</span><span>Peso</span></div>{models.map((model,index)=><div className="table-row" key={`${model.model}-${model.horizon}`}><div><b>{index+1}</b><span><strong>{model.model}</strong><small>{model.family}</small></span><StatusPill status={model.status}/></div><span>{model.mae.toFixed(3)}</span><span>{model.mase.toFixed(2)}</span><span>{model.directionalAccuracy.toFixed(1)}%</span><div className="weight-cell"><i style={{width:`${Math.max(2,(model.mae/maxMae)*100)}%`}}/><span>{model.weight}%</span></div></div>)}</div>:<div className="empty-inline">Métricas detalhadas ainda não disponíveis para este horizonte.</div>}</div>
      <div className="panel model-breakdown"><SectionHeader title="Ensemble por modelo" subtitle="Pesos calculados apenas com erros já realizados"/><div className="model-forecasts">{forecast.modelForecasts.map(item => {
        const weightPct = item.weight <= 1 ? item.weight * 100 : item.weight;
        return <div key={item.name}><div><span>{item.name}</span><strong>{brl.format(item.value)}</strong></div><div className="weight-track"><i style={{width:`${Math.min(100, Math.max(0, weightPct))}%`}}/><span>{Math.round(weightPct)}%</span></div></div>;
      })}</div><div className="method-note"><Icon name="info"/><p>Pesos inverse-MASE com shrinkage para a média uniforme, limite de 60% por modelo e normalização por horizonte.</p></div></div>
    </section>
    <section className="two-col section-gap">
      <div className="panel"><SectionHeader title="Calibração da probabilidade" subtitle="Alta prevista vs. frequência observada"/><CalibrationChart data={data.backtest.calibration}/></div>
      <div className="panel economic-card"><SectionHeader title="Backtest econômico" subtitle="Política de compra vs. reposição uniforme"/><div className="saving-number"><span>ECONOMIA ACUMULADA</span><strong>{brl.format(data.backtest.economic.saving)}</strong><em>{percent(data.backtest.economic.savingPct)} do custo-base</em></div><div className="economic-bars"><div><span>Política Atlas</span><i><b style={{width:"91%"}}/></i><strong>{brl.format(data.backtest.economic.strategyCost)}</strong></div><div><span>Baseline</span><i><b className="baseline" style={{width:"100%"}}/></i><strong>{brl.format(data.backtest.economic.baselineCost)}</strong></div></div><div className="economic-foot"><span><strong>{data.backtest.economic.positiveDecisions}/{data.backtest.economic.decisions}</strong> decisões favoráveis</span><span><strong>Simulado</strong> sem custos de contrato</span></div></div>
    </section>
  </div>;
}
