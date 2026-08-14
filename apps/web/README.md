# Atlas S10 Web

Dashboard B2B de procurement intelligence em Next.js 15, React 19 e TypeScript.

## Executar

```powershell
cd apps\web
npm.cmd install
npm.cmd run dev
```

Abra `http://localhost:3000`.

Validação de produção:

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd run start
```

## Dados e API

O navegador tenta, nesta ordem:

1. `NEXT_PUBLIC_API_BASE_URL/api/dashboard` e `/dashboard`, quando a variável existe;
2. `/api/dashboard` na mesma origem;
3. `http://127.0.0.1:8000/api/dashboard` no desenvolvimento local;
4. `public/demo-data.json`, identificado na interface como snapshot local.

O payload é validado estruturalmente antes de substituir o fallback. O contrato TypeScript está em `lib/types.ts`.

Para apontar para outra API:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='http://localhost:8000'
npm.cmd run dev
```

O launcher `scripts/next.mjs` usa o SWC WebAssembly oficial no Windows porque o binário nativo não é carregado neste ambiente gerenciado. Defina `ATLAS_USE_NATIVE_SWC=1` para preferir o compilador nativo em outra máquina.

## Navegação

- Visão geral: preço, previsão, decisão, drivers e briefing.
- Forecast & backtest: intervalos, leaderboard, ensemble, calibração e valor econômico.
- Time machine: replay causal com dados, pesos, decisão e resultado disponíveis na origem.
- Simulador: estoque, capacidade, consumo, lead time, segurança e tolerância a risco.
- Data health: catálogo, freshness, quality gates e lineage.
- Research: metodologia, papers e limitações explícitas.
