"use client";

import { useState } from "react";
import type { DashboardData } from "@/lib/types";
import { Icon } from "../icons";
import { PageHeader, SectionHeader, StatusPill } from "../dashboard";

const STEPS=[
  {n:"01",title:"Snapshot causal",body:"Cada observação separa a data do fato da data em que ficou disponível. Consultas históricas usam as duas."},
  {n:"02",title:"Features past-only",body:"Lags, scalers, seleção e transformações são recalculados dentro de cada fold — nunca na série completa."},
  {n:"03",title:"Rolling-origin",body:"O treino expande semana a semana; o futuro permanece intocado até o instante de avaliação."},
  {n:"04",title:"Champion por horizonte",body:"7, 14 e 30 dias competem separadamente contra naive, médias móveis e modelos estatísticos."},
  {n:"05",title:"Distribuição calibrada",body:"Ponto, probabilidade e intervalos são avaliados por MAE, MASE, Brier e cobertura realizada."},
  {n:"06",title:"Decisão operacional",body:"Forecast vira quantidade somente depois de estoque, capacidade, demanda, lead time e risco."}
];

export function ResearchPage({data}:{data:DashboardData}){
  const [tab,setTab]=useState<"method"|"papers"|"limits">("method");
  return <div className="page-enter">
    <PageHeader eyebrow="RESEARCH & METHODOLOGY" title="Evidência, implementação e hipótese — sem misturar." description="O Atlas não declara um vencedor a priori. Cada modelo precisa ganhar no backtest brasileiro."/>
    <div className="research-tabs"><button className={tab==="method"?"active":""} onClick={()=>setTab("method")}>Metodologia</button><button className={tab==="papers"?"active":""} onClick={()=>setTab("papers")}>Base científica <span>{data.research.length}</span></button><button className={tab==="limits"?"active":""} onClick={()=>setTab("limits")}>Limitações</button></div>
    {tab==="method"&&<Methodology/>}{tab==="papers"&&<Papers data={data}/>} {tab==="limits"&&<Limitations/>}
  </div>;
}

function Methodology(){return <>
  <section className="principle-card panel"><div className="principle-mark">≠</div><div><span className="eyebrow">PRINCÍPIO CIENTÍFICO</span><h2>Arquitetura é hipótese. Backtest é evidência.</h2><p>Modelos são comparados no mesmo dataset, período, target, horizonte e protocolo. Se o naive vencer, ele vira champion — complexidade não recebe crédito por existir.</p></div></section>
  <section className="panel section-gap method-section"><SectionHeader title="Do dado à decisão" subtitle="Pipeline temporal auditável"/><div className="method-grid">{STEPS.map((step,index)=><article key={step.n}><span>{step.n}</span><div className="method-icon"><Icon name={index===0?"database":index===1?"sliders":index===2?"clock":index===3?"chart":index===4?"shield":"spark"}/></div><h3>{step.title}</h3><p>{step.body}</p>{index<STEPS.length-1&&<Icon name="arrow-right" className="method-arrow"/>}</article>)}</div></section>
  <section className="two-col section-gap"><div className="panel guardrails"><SectionHeader title="Guardrails de causalidade" subtitle="Falham o pipeline; não são warnings"/><div><p><Icon name="check"/><span><strong>Publication leakage</strong> disponível depois da origem</span></p><p><Icon name="check"/><span><strong>Normalization leakage</strong> scaler fora do fold</span></p><p><Icon name="check"/><span><strong>Hyperparameter leakage</strong> tuning no outer test</span></p><p><Icon name="check"/><span><strong>Decomposition leakage</strong> decomposição na série inteira</span></p></div></div><div className="panel confidence-formula"><SectionHeader title="Confiança não é marketing" subtitle="Composição operacional explicável"/><div className="formula"><span>Calibração</span><b>+</b><span>Intervalo</span><b>+</b><span>Agreement</span><b>+</b><span>Data health</span><b>+</b><span>Regime</span></div><p>O score resume qualidade probabilística e operacional. Nunca representa uma “certeza da IA”.</p></div></section>
  </>}

function Papers({data}:{data:DashboardData}){return <section className="research-content"><div className="research-intro"><span>{data.research.length} REFERÊNCIAS MAPEADAS</span><p>Cada referência explicita o que suporta, onde se limita e como influencia a implementação.</p></div><div className="papers-grid">{data.research.map(paper=><article className="panel paper-card" key={paper.id}><div className="paper-top"><span>{paper.id}</span><StatusPill status={paper.confidence}/></div><h2>{paper.title}</h2><div className="paper-target"><span>TARGET</span><strong>{paper.target}</strong></div><div><span>POR QUE IMPORTA</span><p>{paper.why}</p></div><div><span>USADO PELO ATLAS</span><p>{paper.usage}</p></div><details><summary>Evidence & limitation <Icon name="chevron" size={14}/></summary><p><strong>Evidence:</strong> {paper.evidence}</p><p><strong>Limitation:</strong> {paper.limitation}</p></details></article>)}</div></section>}

function Limitations(){const items=[{title:"Cobertura histórica curta no varejo",body:"O alvo nacional possui 130 semanas completas. Isso limita regimes observados e favorece modelos parcimoniosos."},{title:"Snapshot ANP exige atualização",body:"A última semana completa local termina em 28 jun 2026. A interface sinaliza freshness em vez de fingir tempo real."},{title:"Preço público não é preço contratado",body:"Economia simulada usa média de revenda; frete, descontos, prazo e take-or-pay ainda não entram no contrafactual."},{title:"Publication lag é premissa conservadora",body:"ANP usa +8 dias na demo. O horário oficial de cada publicação deve ser monitorado e versionado em produção."},{title:"Challengers não são reprodução acadêmica",body:"VS-ePL-KRLS permanece experimental e com peso zero até validação matemática e de licença."},{title:"Choques são difíceis por definição",body:"O salto de março concentrou grande parte do erro. Intervalos ajudam a comunicar risco, não eliminam surpresa."}];return <section><div className="limitations-grid">{items.map((item,index)=><article className="panel" key={item.title}><span>LIMITAÇÃO {String(index+1).padStart(2,"0")}</span><h2>{item.title}</h2><p>{item.body}</p><StatusPill status={index<2?"atenção":"documentado"}/></article>)}</div><div className="honesty-note panel"><Icon name="info"/><div><strong>Como ler esta demo</strong><p>O snapshot local usa o target nacional e os artefatos reais persistidos. A API, quando conectada, substitui todo o contrato após validação estrutural.</p></div></div></section>}
