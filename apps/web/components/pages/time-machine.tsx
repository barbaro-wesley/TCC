"use client";

import { useState } from "react";
import { brl, fullDate, liters } from "@/lib/format";
import type { DashboardData } from "@/lib/types";
import { Icon } from "../icons";
import { Metric, PageHeader, SectionHeader } from "../dashboard";

export function TimeMachinePage({ data }: { data: DashboardData }) {
  const [index,setIndex]=useState(Math.max(0,data.timeMachine.length-1));
  const item=data.timeMachine[index];
  const error=item.forecast-item.actual;
  const verdict=Math.abs(error)<.08?"ACERTOU O CENÁRIO":error>0?"SUBESTIMOU A ALTA":"SUPERESTIMOU O PREÇO";
  const min=Math.min(item.p10,item.currentPrice,item.actual)-.06;
  const max=Math.max(item.p90,item.currentPrice,item.actual)+.06;
  const pos=(value:number)=>((value-min)/(max-min))*100;
  return <div className="page-enter">
    <PageHeader eyebrow="FORECAST TIME MACHINE" title="Veja somente o que o modelo sabia naquele dia." description="Reproduza uma decisão histórica com o snapshot causal, pesos e dados disponíveis na origem."/>
    <section className="time-control panel">
      <div className="time-date"><span>AS OF</span><strong>{fullDate(item.date)}</strong><small>dados conhecidos até {fullDate(item.knownThrough)}</small></div>
      <div className="timeline-control"><input type="range" min="0" max={data.timeMachine.length-1} step="1" value={index} onChange={event=>setIndex(Number(event.target.value))}/><div>{data.timeMachine.map((point,i)=><button key={point.date} className={i===index?"active":""} onClick={()=>setIndex(i)} aria-label={`Selecionar ${fullDate(point.date)}`}><i/><span>{new Date(`${point.date}T12:00:00`).toLocaleDateString("pt-BR",{month:"short"}).replace(".","")}</span></button>)}</div></div>
      <div className="causal-seal"><Icon name="shield"/><div><strong>SNAPSHOT CAUSAL</strong><span>{item.sourcesAvailable} fontes disponíveis</span></div></div>
    </section>
    <section className="replay-grid section-gap">
      <div className="panel replay-forecast">
        <SectionHeader title="O que o Atlas teria previsto" subtitle={`Origem: ${fullDate(item.date)} · horizonte 7 dias`}/>
        <div className="replay-numbers"><div><span>PREÇO NA ORIGEM</span><strong>{brl.format(item.currentPrice)}</strong></div><Icon name="arrow-right"/><div><span>FORECAST</span><strong className="info-text">{brl.format(item.forecast)}</strong></div><Icon name="arrow-right"/><div><span>REALIZADO</span><strong className="positive-text">{brl.format(item.actual)}</strong></div></div>
        <div className="interval-ruler"><div className="interval-band" style={{left:`${pos(item.p10)}%`,width:`${pos(item.p90)-pos(item.p10)}%`}}/><div className="interval-point forecast" style={{left:`${pos(item.forecast)}%`}}><i/><span>Forecast</span></div><div className="interval-point actual" style={{left:`${pos(item.actual)}%`}}><i/><span>Real</span></div><div className="interval-ends"><span style={{left:`${pos(item.p10)}%`}}>P10 {brl.format(item.p10)}</span><span style={{left:`${pos(item.p90)}%`}}>P90 {brl.format(item.p90)}</span></div></div>
        <div className="replay-verdict"><Icon name={Math.abs(error)<.08?"check":"warning"}/><div><span>{verdict}</span><strong>Erro de {brl.format(Math.abs(error))}/L</strong></div><p>O realizado {item.actual>=item.p10&&item.actual<=item.p90?"ficou dentro":"ficou fora"} do intervalo P10–P90.</p></div>
      </div>
      <div className="panel replay-decision">
        <span className="panel-kicker">DECISÃO GERADA NAQUELE DIA</span><div className="historical-action"><i/><span>{item.recommendation}</span></div><strong>{liters(item.suggestedLiters)}</strong><small>compra sugerida na origem</small><div className="realized-saving"><span>Resultado retrospectivo</span><strong className={item.realizedSaving>=0?"positive-text":"risk-text"}>{item.realizedSaving>=0?"+":""}{brl.format(item.realizedSaving)}</strong><small>economia vs. compra uniforme</small></div><p><Icon name="info"/> Valor contrafactual baseado no preço público médio; não inclui descontos, frete ou restrições contratuais.</p>
      </div>
    </section>
    <section className="four-grid section-gap"><Metric label="PROB. DE ALTA" value={`${item.probabilityUp}%`} sub="calculada na origem"/><Metric label="INTERVALO" value={`${brl.format(item.p10)} — ${brl.format(item.p90)}`} sub="sem recalibração posterior" tone="info"/><Metric label="ERRO ABSOLUTO" value={`${brl.format(Math.abs(error))}/L`} sub={verdict}/><Metric label="FONTES VISÍVEIS" value={`${item.sourcesAvailable}/${data.sources.length}`} sub="no instante da previsão"/></section>
    <section className="two-col section-gap">
      <div className="panel"><SectionHeader title="Pesos que estavam vigentes" subtitle="Sem usar erros realizados após a origem"/><div className="historical-weights">{item.weights.map(weight=><div key={weight.name}><span>{weight.name}</span><i><b style={{width:`${weight.value}%`}}/></i><strong>{weight.value}%</strong></div>)}</div></div>
      <div className="panel known-data"><SectionHeader title="Janela de conhecimento" subtitle="A barreira que impede leakage"/><div className="knowledge-flow"><div><span>OBSERVAÇÃO</span><strong>≤ {fullDate(item.knownThrough)}</strong><small>período de referência</small></div><Icon name="arrow-right"/><div><span>AVAILABLE_AT</span><strong>≤ {fullDate(item.date)}</strong><small>publicação conhecida</small></div><Icon name="arrow-right"/><div><span>FORECAST</span><strong>{fullDate(item.date)}</strong><small>origem imutável</small></div></div><div className="method-note"><Icon name="shield"/><p>Qualquer feature com <code>available_at &gt; forecast_origin</code> faz o pipeline falhar; não gera apenas um aviso.</p></div></div>
    </section>
  </div>;
}
