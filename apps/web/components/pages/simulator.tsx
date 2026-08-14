"use client";

import { useMemo, useState } from "react";
import { brl, liters, percent } from "@/lib/format";
import type { DashboardData } from "@/lib/types";
import { Donut } from "../charts";
import { Icon } from "../icons";
import { HorizonTabs, PageHeader, SectionHeader } from "../dashboard";

type Risk = "conservative" | "moderate" | "aggressive";

export function SimulatorPage({ data }: { data: DashboardData }) {
  const [horizon,setHorizon]=useState(30);
  const [stock,setStock]=useState(18000);
  const [capacity,setCapacity]=useState(100000);
  const [daily,setDaily]=useState(2500);
  const [safety,setSafety]=useState(5);
  const [lead,setLead]=useState(3);
  const [risk,setRisk]=useState<Risk>("moderate");
  const [calculating,setCalculating]=useState(false);
  const forecast=data.forecasts.find(item=>item.horizon===horizon)??data.forecasts.at(-1)!;
  const result=useMemo(()=>{
    const demand=daily*horizon;
    const reserve=daily*safety;
    const need=Math.max(0,demand+reserve-stock);
    const available=Math.max(0,capacity-stock);
    const feasible=Math.min(need,available);
    const coverage=daily>0?stock/daily:999;
    const forced=Math.max(0,daily*(lead+safety)-stock);
    let fraction=.25; let signal="NEUTRO"; let action="MANTER COMPRA TÁTICA";
    if(forced>0){fraction=Math.max(.45,Math.min(1,forced/Math.max(feasible,1)));signal="COBERTURA CRÍTICA";action="REPOR E ANTECIPAR";}
    else if(forecast.probabilityUp>=72&&forecast.changePct>=.3){fraction=risk==="conservative"?.7:.6;signal="RISCO DE ALTA";action="ANTECIPAR PARCIALMENTE";}
    else if(forecast.probabilityUp>=56&&forecast.changePct>0){fraction=.4;signal="PRESSÃO DE ALTA";action="COMPRAR PARCIALMENTE";}
    else if(forecast.probabilityUp<=38&&coverage>lead+safety){fraction=0;signal="VIÉS DE QUEDA";action="AGUARDAR";}
    const now=Math.max(0,Math.min(available,Math.max(forced,feasible*fraction)));
    const rounded=Math.round(now/500)*500;
    const savings=rounded*Math.max(0,forecast.point-data.market.currentPrice);
    const timing=rounded*Math.max(0,data.market.currentPrice-forecast.p10);
    return {demand,reserve,need:feasible,available,coverage,now:rounded,later:Math.max(0,feasible-rounded),fraction:feasible?rounded/feasible*100:0,savings,timing,signal,action};
  },[capacity,daily,forecast,horizon,lead,risk,safety,stock,data.market.currentPrice]);
  const recalc=()=>{setCalculating(true);window.setTimeout(()=>setCalculating(false),500)};
  return <div className="page-enter">
    <PageHeader eyebrow="PROCUREMENT STUDIO" title="Transforme risco de mercado em uma compra possível." description="Ajuste estoque, consumo e tolerância. A política respeita capacidade, cobertura e lead time."><HorizonTabs horizon={horizon} setHorizon={(value)=>{setHorizon(value);recalc()}}/></PageHeader>
    <section className="simulator-layout">
      <div className="panel input-panel"><SectionHeader title="Premissas operacionais" subtitle="Cenário hipotético — substitua pelos dados da sua operação"/>
        <div className="input-grid"><NumberField label="Estoque atual" value={stock} setValue={setStock} suffix="L" step={1000}/><NumberField label="Capacidade do tanque" value={capacity} setValue={setCapacity} suffix="L" step={5000}/><NumberField label="Consumo diário" value={daily} setValue={setDaily} suffix="L/dia" step={250}/><NumberField label="Estoque de segurança" value={safety} setValue={setSafety} suffix="dias" step={1}/><NumberField label="Lead time do fornecedor" value={lead} setValue={setLead} suffix="dias" step={1}/><div className="field"><label>Tolerância a risco</label><div className="risk-toggle">{(["conservative","moderate","aggressive"] as Risk[]).map(item=><button key={item} className={risk===item?"active":""} onClick={()=>{setRisk(item);recalc()}}>{item==="conservative"?"Conservadora":item==="moderate"?"Moderada":"Agressiva"}</button>)}</div></div></div>
        <div className="scenario-line"><span>Cenário de mercado usado</span><div><strong>{horizon}d · {brl.format(forecast.point)}/L</strong><small>{forecast.probabilityUp}% prob. de alta · P10–P90 {brl.format(forecast.p10)}–{brl.format(forecast.p90)}</small></div></div><button className="primary-button full" onClick={recalc}><Icon name="spark"/>Recalcular política</button>
      </div>
      <div className={`panel result-panel ${calculating?"calculating":""}`}><div className="result-head"><span className="panel-kicker">RECOMENDAÇÃO MODELADA</span><span className="confidence-pill"><Icon name="shield" size={14}/>{forecast.confidence}% confiança</span></div><div className="signal"><i/><span>{result.signal}</span></div><h2>{result.action}</h2><p>Dadas as premissas informadas, esta parcela apresenta o menor custo esperado no cenário modelado.</p><div className="result-volume"><div><span>COMPRAR AGORA</span><strong>{liters(result.now)}</strong><small>{liters(result.later)} podem permanecer para depois</small></div><Donut value={Math.min(100,result.fraction)} label="da necessidade" tone="green" size={112}/></div><div className="result-money"><div><span>Economia esperada</span><strong className="positive-text">{brl.format(result.savings)}</strong></div><div><span>Risco de timing</span><strong>{brl.format(result.timing)}</strong></div></div><div className="disclaimer"><Icon name="info"/><span>Suporte à decisão, não uma ordem absoluta de compra. Resultado sensível às premissas.</span></div></div>
    </section>
    <section className="flow-panel panel section-gap"><SectionHeader title="Como a recomendação fecha" subtitle="Da demanda física à decisão de timing"/><div className="calculation-flow"><FlowItem label="Demanda no horizonte" value={liters(result.demand)} sub={`${daily.toLocaleString("pt-BR")} L × ${horizon} dias`}/><Icon name="arrow-right"/><FlowItem label="+ Reserva" value={liters(result.reserve)} sub={`${safety} dias de segurança`}/><Icon name="arrow-right"/><FlowItem label="− Estoque" value={liters(stock)} sub={`${result.coverage.toFixed(1)} dias de cobertura`}/><Icon name="arrow-right"/><FlowItem label="Necessidade factível" value={liters(result.need)} sub={`${liters(result.available)} de capacidade`}/><Icon name="arrow-right"/><FlowItem label="Comprar agora" value={liters(result.now)} sub={`${result.fraction.toFixed(0)}% tático`} highlight/></div></section>
    <section className="scenario-grid section-gap"><Scenario title="Queda (P10)" price={forecast.p10} current={data.market.currentPrice} volume={result.now} tone="positive"/><Scenario title="Cenário central" price={forecast.point} current={data.market.currentPrice} volume={result.now} tone="info"/><Scenario title="Alta (P90)" price={forecast.p90} current={data.market.currentPrice} volume={result.now} tone="risk"/></section>
  </div>;
}

function NumberField({label,value,setValue,suffix,step}:{label:string;value:number;setValue:(v:number)=>void;suffix:string;step:number}){return <div className="field"><label>{label}</label><div className="number-input"><input type="number" min="0" step={step} value={value} onChange={e=>setValue(Math.max(0,Number(e.target.value)))}/><span>{suffix}</span></div></div>}
function FlowItem({label,value,sub,highlight}:{label:string;value:string;sub:string;highlight?:boolean}){return <div className={`flow-item ${highlight?"highlight":""}`}><span>{label}</span><strong>{value}</strong><small>{sub}</small></div>}
function Scenario({title,price,current,volume,tone}:{title:string;price:number;current:number;volume:number;tone:string}){const delta=(price/current-1)*100;const impact=(price-current)*volume;return <div className={`panel scenario-card ${tone}`}><span>{title}</span><strong>{brl.format(price)}/L</strong><em>{percent(delta)}</em><div><small>Impacto sobre a compra</small><b className={impact>0?"risk-text":"positive-text"}>{impact>0?"+":""}{brl.format(impact)}</b></div></div>}
