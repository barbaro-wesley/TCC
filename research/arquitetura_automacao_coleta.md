# Atlas S10 — arquitetura de automação da coleta e retreino semanal

**Versão:** 1.0
**Data:** 18 de agosto de 2026
**Status:** proposta de arquitetura (design). Ainda não implementada.
**Decisões já tomadas:** estratégia de dados **incremental**; conectores devem
cobrir as fontes atuais **+ IPCA + biodiesel**.
**Decisão em aberto (esta análise recomenda):** onde executar a automação —
prioridade em **baixo custo**.

---

## 1. Objetivo e problema

Hoje a atualização é manual: toda semana é preciso visitar os sites do governo
(ANP, BCB, EIA), baixar os arquivos, colocá-los em `raw/` e rodar quatro comandos
(`sync_data` → `prepare_data` → `train` → `build_product`). O objetivo é
**automatizar ponta a ponta**: buscar os dados, atualizar o `gold`, retreinar e
publicar as novas previsões — **semanalmente, sem intervenção, e barato**.

Os "agentes de busca de dados" pedidos são, na prática, **conectores de fonte**
(um por fonte oficial) que baixam, validam e registram proveniência de cada
snapshot — mais um **orquestrador** que encadeia tudo e um **agendador** que roda
semanalmente.

## 2. O que já existe (e vamos reusar)

- **`pipelines/sync_data.py`** — conector de **ANP revenda (rolling 4 semanas)** e
  **BCB PTAX**, com o padrão certo: download **atômico** (temp → valida →
  substitui), **validação de schema** (`validate_anp_csv`, `validate_ptax_json`) e
  rede **opt-in** (`--network` / `ALLOW_NETWORK_SYNC`). É o molde para os demais
  conectores.
- **Cadeia de pipeline** (hoje manual): `sync_data` → `prepare_data` → `train` →
  `build_product`.
- **`POST /data/sync`** (`services/api/main.py`) já expõe o sync pela API.
- **Contrato causal** `observation_date` × `available_at` e
  `normalized_observations` (`atlas_s10/data.py`) — base para o append incremental.

## 3. Lacunas que impedem "tudo automático" hoje

1. **Cobertura de fontes incompleta.** O sync cobre só ANP-rolling + BCB. Faltam
   conectores para **EIA Brent**, **ANP distribuição**, **ANP produtor/importador**
   e — pela decisão de escopo — **IPCA** e **biodiesel**.
2. **Dependência do `raw/` (~350 MB, no `.gitignore`, ausente do repositório).**
   `prepare_data.py` exige os **5 CSVs semestrais** da ANP (`discover_retail_files`,
   `prepare_data.py:162`), os workbooks de cadeia (`load_anp_cost_drivers`) e os
   processados externos. Num ambiente limpo, falha na hora.
3. **`discover_retail_files` exige exatamente 5 semestrais** — quebra quando um novo
   semestre for publicado. Precisa ser generalizado.
4. **Sem orquestração única** e **sem agendador**.

## 4. Por que a automação NÃO pode rodar neste ambiente Claude

A rede deste ambiente (Claude Code na web) usa uma **allowlist restritiva**.
Teste feito em 18/08/2026, pelo proxy de egress:

| Fonte | Host | Resultado |
|---|---|---|
| ANP revenda | `www.gov.br` | **403 — policy denial** |
| BCB PTAX | `olinda.bcb.gov.br` | **403 — policy denial** |
| EIA Brent | `www.eia.gov` | **403 — policy denial** |

Só registries (pip/npm/pypi) e Anthropic são liberados. **Conclusão:** o executor
da automação precisa de um ambiente com **egress aberto** para os sites do governo.
Isso elimina "rodar aqui" e orienta a comparação da Seção 5.

## 5. Onde executar — comparação com custo (a decisão principal)

Todas as opções assumem os conectores Python já escritos (Seção 7). A diferença é
**onde** o cron dispara e **quanto custa**.

| Critério | **GitHub Actions** | **VPS + cron** | **Claude Routine** | **Máquina local** |
|---|---|---|---|---|
| Custo mensal | **~R$ 0** ¹ | ~R$ 0 (Oracle Free) a ~R$ 25–35 (VPS pago) | Consumo do seu plano Claude | R$ 0 |
| Precisa de servidor? | **Não** | Sim (você administra) | Não | Sim (seu PC) |
| Manutenção/ops | Mínima (YAML) | Alta (SO, segurança, Python, monitor) | Baixa | Média |
| Versiona resultados | **Sim (commit/PR)** | Não (você monta) | Sim (commit) | Não |
| Confiabilidade (roda sem você) | **Alta** | Alta (se o servidor estiver de pé) | Média | Baixa (PC precisa estar ligado) |
| Egress p/ gov | Aberto ² | Aberto | **Exige mudar política de rede do ambiente** | Aberto |
| Determinismo | Alto | Alto | Médio (é um LLM) | Alto |

¹ **GitHub Actions** é **gratuito e ilimitado** em repositórios **públicos**; em
repositórios privados o plano Free inclui 2.000 min/mês. Um job semanal de ~5 min
gasta ~22 min/mês — **desprezível nos dois casos**.
² Runners do GitHub têm internet própria (não passam por este proxy). Risco
residual: alguns sites gov podem bloquear IP de datacenter — a validar (Seção 11).

### Sobre a sua ideia de "Python + cron num servidor"
Funciona e é uma arquitetura clássica de ETL. O ponto honesto é o **custo total**:
além da mensalidade do VPS (ou da fricção do tier gratuito da Oracle Cloud), você
passa a ser responsável por **manter e proteger um servidor** (atualizações de SO,
firewall, ambiente Python, monitoramento, backup) e ainda precisa montar você
mesmo o versionamento dos resultados. O **GitHub Actions faz o mesmo cron, sem
servidor, de graça, e já comita o resultado** — por isso é a recomendação para
"melhor e que não custe muito".

### 🏆 Recomendação
**GitHub Actions** como executor do ETL semanal. Sem servidor, ~R$ 0, versionado,
reproduzível e independente da sua máquina. (Se um dia quiser adaptabilidade a
mudanças de layout dos sites, uma **Claude Routine como *supervisor*** do CI é a
evolução natural — opcional, Seção 11.)

## 6. Estratégia de dados: incremental (append causal ao `gold`)

Mantemos o histórico do `gold` versionado e, a cada rodada, anexamos apenas as
**semanas novas** — respeitando o contrato causal já existente:

1. **Buscar** os snapshots recentes de cada fonte (janela curta, ex.: últimas 4–8
   semanas), não o histórico inteiro.
2. **Normalizar** para o contrato longo `series_id, observation_date, available_at,
   value, ...` (reusar `normalized_observations`, `atlas_s10/data.py`).
3. **Anexar ao `gold`** com deduplicação por `(series_id, observation_date,
   geography_code)`, mantendo a **última revisão** e o `available_at` calculado por
   `availability_at_end_of_day` (nunca preencher semana futura ainda não publicada).
4. **Retreinar** (`train.py`) e **republicar** (`build_product.py`).
5. **Reconciliação periódica**: um **rebuild total mensal** (baixando os semestrais)
   corrige qualquer divergência acumulada e absorve revisões antigas.

Vantagens: downloads pequenos, robustez, e reaproveitamento do contrato causal
auditado (ver `research/auditoria_vazamento_dados.md`). Custo: um módulo novo de
*append* causal (com testes que travem `available_at` e a deduplicação).

## 7. Inventário de conectores ("agentes de busca")

Cada conector segue o mesmo contrato do `sync_data.py`: **download atômico →
validação de schema → registro de proveniência** (hash, URL, timestamp), e nunca
substitui dado bom por sintético em caso de falha.

| Fonte | Método / origem | Formato | Frequência | Lag de disponibilidade | Chave? | Status |
|---|---|---|---|---|---|---|
| ANP revenda (recente) | `gov.br/.../ultimas-4-semanas-diesel-gnv.csv` | CSV | Semanal | ~8 dias (premissa) | Não | **Existe** |
| ANP revenda (semestral) | Série histórica ANP (rebuild) | CSV | Semestral | — | Não | A criar |
| BCB PTAX USD/BRL | OData PTAX (`olinda.bcb.gov.br`) | JSON | Diária | ~1 dia | Não | **Existe** |
| EIA Brent RBRTE | API EIA (`api.eia.gov`, chave grátis) **ou** planilha RBRTE | JSON/XLS | Diária útil | ~3 dias | API: sim (grátis) | A criar |
| ANP distribuição S10 | `raw/anp/distribuicao/...combustiveis-liquidos-brasil.xlsx` (dados abertos ANP) | XLSX | Semanal | ~14 dias (assumido) | Não | A criar |
| ANP produtor/importador S10 | `...precos-medios-ponderados-semanais-2013.xls` (dados abertos ANP) | XLS | Semanal | ~12 dias | Não | A criar |
| **IPCA (SIDRA 7060)** | API SIDRA (`apisidra.ibge.gov.br`) | JSON | Mensal | ~10 dias após o mês | Não | **A criar (decidido)** |
| **Biodiesel** | Dados abertos ANP (produção / B100) | CSV/XLSX | Mensal | a confirmar | Não | **A criar (decidido)** |

> **Nota de escopo — IPCA e biodiesel.** O conector é o primeiro passo, mas para o
> modelo *usar* essas séries é preciso um segundo passo: integrá-las como **features
> auxiliares** em `prepare_data.py` / `atlas_s10/features.py` e **provar valor
> preditivo** no backtest (a spec exige isso; elas só permanecem se ajudarem). O
> conector e a integração de feature são fases distintas (Seção 12). URLs/endpoints
> exatos de IPCA e biodiesel devem ser **confirmados** na primeira implementação.

## 8. Desenho do código (proposta)

```
atlas_s10/sources/                 # pacote de conectores ("agentes de busca")
  __init__.py
  base.py                          # contrato comum: fetch() -> atomic download + validate + provenance
  anp_revenda.py                   # generaliza o sync atual (rolling + semestral)
  bcb_ptax.py                      # migra o conector BCB existente
  eia_brent.py                     # NOVO
  anp_distribuicao.py              # NOVO
  anp_produtor_importador.py       # NOVO
  ibge_ipca.py                     # NOVO (SIDRA 7060)
  anp_biodiesel.py                 # NOVO
pipelines/
  fetch_sources.py                 # orquestra todos os conectores (--network, --since)
  append_gold.py                   # NOVO: normaliza + anexa incremental ao gold (causal)
tests/
  test_sources_*.py                # um teste de contrato por parser (estende test_sync_parsers.py)
```

- **Contrato comum** (`base.py`): reaproveita `_download`/validador atômico do
  `sync_data.py` e um objeto de proveniência padronizado.
- **Config**: variáveis de ambiente (ex.: `EIA_API_KEY` como *secret* do GitHub;
  `ALLOW_NETWORK_SYNC`), sem segredos no código.
- **Orquestrador** `fetch_sources.py`: baixa tudo, agrega proveniência, e falha alto
  se qualquer schema mudar (o `prepare_data` já faz isso — mantemos a política).

## 9. Orquestração e agendamento (GitHub Actions)

Workflow `.github/workflows/atualizacao-semanal.yml` (esboço conceitual):

```yaml
on:
  schedule:
    - cron: "0 15 * * 3"   # quarta 12:00 America/Sao_Paulo (após o lag de ~8 dias da ANP)
  workflow_dispatch: {}     # permite disparo manual
jobs:
  refresh:
    steps:
      - checkout
      - setup-python 3.11 + pip install -r requirements.txt
      - python -m pipelines.fetch_sources --network      # conectores
      - python -m pipelines.append_gold                  # append incremental causal
      - python -m pipelines.train                        # retreino
      - python -m pipelines.build_product                # atualiza demo-data.json
      - python -m pytest -q                              # trava causalidade/contratos
      - commit data/gold + artifacts + apps/web/public/demo-data.json → abre PR
```

- **Só derivados pequenos** são comitados (`data/gold/`, `artifacts/`,
  `demo-data.json`); o `raw/` fica efêmero no runner e é descartado — resolve o
  problema dos 350 MB.
- **Falha = sinal**: se um schema mudar, o job falha e o GitHub notifica (ou abre
  uma *issue*). Nunca publica dado inventado.
- **Timing causal**: agendar após a publicação da ANP evita usar a semana-alvo antes
  de ela existir de fato.

## 10. Robustez e ética (manter o padrão do projeto)

Download atômico · validação que **falha alto** · **nunca inventar dado** (em falha,
manter último cache bom e pular a semana) · retry com backoff + headers educados ·
respeitar robots/ToS · **timing causal** · proveniência (hash+URL+timestamp) ·
comitar em **PR revisável**, não direto na `main`.

## 11. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Site gov bloqueia IP de datacenter (runner do GitHub) | Testar na Fase 1; se ocorrer, usar **Claude Routine** (IP do ambiente, com política liberada) ou um mirror/cache |
| **Schema drift** dos workbooks ANP | O pipeline já quebra de propósito; adicionar alerta + **Routine supervisora** que adapta o parser |
| `discover_retail_files` fixo em 5 | Generalizar para *N* semestrais |
| IPCA/biodiesel: conector ≠ uso no modelo | Fase separada de integração de feature + prova de valor |
| Gestão de segredo (EIA API key) | GitHub Secrets; ou usar a planilha RBRTE sem chave |
| Revisões retroativas das fontes | Rebuild total mensal reconcilia |

## 12. Roadmap de implementação (fases)

- **Fase 1 — Conectores das fontes atuais.** `atlas_s10/sources/` + `fetch_sources.py`
  para ANP revenda, BCB, EIA Brent, distribuição e produtor/importador; testes de
  contrato. *(Entrega: buscar tudo que o modelo já usa.)*
- **Fase 2 — Append incremental causal.** `append_gold.py` + testes que travam
  `available_at`/dedup; rebuild total mensal como reconciliação.
- **Fase 3 — Agendamento.** Workflow do GitHub Actions + PR automático + timing.
- **Fase 4 — IPCA + biodiesel.** Conectores + integração como feature auxiliar +
  prova de valor no backtest.
- **Fase 5 (opcional) — Supervisor.** Claude Routine que observa o CI e conserta
  parsers quando um site muda de layout.

## 13. Decisões pendentes (para a implementação)

1. Repositório **público ou privado** (afeta minutos do Actions, mas ~R$ 0 nos dois).
2. EIA via **API com chave** (mais estável) ou **planilha RBRTE** (sem segredo).
3. **Dia/hora** exatos do cron (proposto: quarta, após o lag da ANP).
4. Destino do commit: **PR para revisão** (recomendado) ou branch de dados dedicado.

## 14. Referências no repositório

- `pipelines/sync_data.py` — molde do conector atômico.
- `pipelines/prepare_data.py` — pipeline causal e guards de schema.
- `atlas_s10/data.py` — contrato `normalized_observations` (base do append).
- `research/methodology.md` — contrato causal normativo.
- `research/auditoria_vazamento_dados.md` — garantias de causalidade a preservar.

---

*Documento de arquitetura — parte do dossiê de engenharia do Atlas S10. Próximo
passo após aprovação: Fase 1 (conectores das fontes atuais).*
