# Deploy do Atlas S10 numa VM Azure (API ao vivo)

A VM faz **tudo**: segura o `raw/`, roda o pipeline (coleta → treino → build) num
timer e serve a **API FastAPI** por HTTPS. O painel Next.js fica no **Vercel** e
consome essa API. Se a API cair, o painel usa o `demo-data.json` versionado.

```
Vercel (painel) ──HTTPS──► Caddy (VM :443, auto-TLS) ──► api (uvicorn :8000)
                                                            ▲ lê artifacts/ + data/gold
                                   pipeline (timer semanal) ─┘ escreve artifacts/
                                            ▲ raw/ (na VM)
```

## Arquivos deste deploy
- `Dockerfile` — imagem única (serve a API e roda o pipeline).
- `docker-compose.yml` — serviços `api` + `caddy` (+ `pipeline`, one-shot).
- `Caddyfile` — reverse proxy com HTTPS automático (Let's Encrypt).
- `deploy/pipeline.sh` — o ciclo dentro do container.
- `deploy/refresh.sh` + `atlas-refresh.{service,timer}` — agendamento no host.

## Pré-requisitos
- VM Linux (Ubuntu 22.04+; uma **B1s/B2s** já serve para um TCC).
- Um **domínio** com um **A record** apontando para o IP público da VM
  (ex.: `api.seudominio.com`).
- Sua **`EIA_API_KEY`**.

## 1. DNS
Crie um A record: `api.seudominio.com  →  <IP público da VM>`.

## 2. Firewall (Azure NSG)
Libere **inbound** apenas:
- **443** (HTTPS) e **80** (HTTP, para o desafio do Let's Encrypt) — origem `Any`.
- **22** (SSH) — restrinja à **sua origem** (seu IP), não `Any`.

A porta **8000 não é exposta** (só o Caddy fala com a API, pela rede interna).

## 3. Instalar Docker na VM
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # relogue depois disto
timedatectl set-timezone America/Sao_Paulo   # para o timer bater com o horário local
```

## 4. Clonar o repositório e configurar
```bash
sudo mkdir -p /opt/atlas && sudo chown "$USER" /opt/atlas
cd /opt/atlas
git clone https://github.com/barbaro-wesley/TCC.git
cd TCC

cp .env.example .env
# edite o .env:
#   EIA_API_KEY=...suachave...
#   ATLAS_ALLOWED_ORIGINS=https://SEU-PAINEL.vercel.app   (a origem real do painel)

# aponte o Caddy para o seu domínio:
sed -i 's/api\.seudominio\.com/api.SEUDOMINIO.com/' Caddyfile
```

## 5. Enviar os dados grandes (`raw/`) uma vez
`raw/` (~350 MB) e `processed/` são gitignored — envie-os da **sua máquina**:
```bash
# rode na SUA máquina, na raiz do repo local:
rsync -avz --progress raw/ processed/ USUARIO@IP_DA_VM:/opt/atlas/TCC/  # (mantém raw/ e processed/)
```
(Se você usa a planilha do EIA offline em vez da API, envie também o XLS; com a
`EIA_API_KEY` o pipeline baixa o Brent sozinho.)

## 6. Subir a API
```bash
docker compose up -d          # constrói a imagem, sobe api + caddy
docker compose ps             # api deve ficar "healthy"; caddy "running"
```
O Caddy pega o certificado sozinho no primeiro acesso ao domínio.

## 7. Primeiro ciclo (gerar previsões)
```bash
docker compose run --rm pipeline     # sync -> prepare -> train -> build (alguns minutos)
curl -s https://api.SEUDOMINIO.com/health          # -> {"status":"healthy",...}
curl -s https://api.SEUDOMINIO.com/api/dashboard | head -c 300
```

## 8. Agendar o refresh semanal
```bash
sudo cp deploy/atlas-refresh.service /etc/systemd/system/
sudo cp deploy/atlas-refresh.timer   /etc/systemd/system/
# confira o WorkingDirectory/ExecStart no .service (default: /opt/atlas/TCC)
sudo systemctl daemon-reload
sudo systemctl enable --now atlas-refresh.timer
systemctl list-timers | grep atlas          # confirma o próximo disparo
```

## 9. Painel no Vercel
1. Importe o projeto `apps/web` no Vercel (root do projeto = `apps/web`).
2. Variável de ambiente: `NEXT_PUBLIC_API_BASE_URL=https://api.SEUDOMINIO.com`.
3. Se o Vercel não detectar o build (o projeto usa `scripts/next.mjs`), defina
   **Build Command** `npm run build` e deixe o output padrão do Next.
4. Abra o painel: o topo deve mostrar **"API CONECTADA"** (e não "SNAPSHOT LOCAL").

## Operação
- **Atualizar código:** `git pull && docker compose up -d --build`.
- **Ver logs:** `docker compose logs -f api` / `... caddy`.
- **Refresh manual:** `docker compose run --rm pipeline`.
- **Rollback:** `git checkout <commit anterior> && docker compose up -d --build`.

## Segurança (resumo)
- Container roda como usuário **não-root**; só **80/443** expostos; **8000** interna.
- `.env` fora do Git (segredos). HTTPS obrigatório (HSTS). CORS restrito à origem
  do painel via `ATLAS_ALLOWED_ORIGINS`.

## Observação sobre a coleta no GitHub Actions
Com a VM coletando, o workflow `atualizacao-semanal.yml` fica **redundante**.
Mantenha-o como backup de proveniência **ou** desabilite-o em Actions — à sua escolha.
