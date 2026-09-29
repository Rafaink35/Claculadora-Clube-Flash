# Calculadora de Economia com Parceiros B2C — Clube Flash

MVP da calculadora de economia agregada que colaboradores geram usando o
Clube Flash. Serve como artefato para justificar o valor devolvido ao RH.

## Como funciona

- `app.py` — servidor Flask. Rota `/` serve a página; rota `/api/categorias`
  serve os dados de categoria em JSON.
- `data/categorias.json` — desconto médio e nº de parceiros ativos por
  categoria, extraídos do Mapa de Parceiros B2C. Frequência de uso e ticket
  médio são estimativas iniciais (editáveis na própria calculadora).
- `scripts/extrair_categorias.py` — regenera `data/categorias.json` a partir
  de uma nova versão do Mapa de Parceiros B2C (.xlsx).
- `templates/` e `static/` — front-end (HTML/CSS/JS puro, sem build step).

## Rodar localmente

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GEMINI_API_KEY="sua-chave-aqui"   # Windows: set GEMINI_API_KEY=sua-chave-aqui
python app.py
```

Abra http://localhost:5000. Sem a variável `GEMINI_API_KEY`, a calculadora funciona normalmente — o botão "✨ Gerar com IA" cai automaticamente no texto padrão (template determinístico), sem quebrar.

### Como conseguir a chave do Gemini (gratuita)

1. Acesse [aistudio.google.com](https://aistudio.google.com/apikey)
2. Faça login com uma conta Google e clique em "Create API key" — não pede cartão de crédito
3. Copie a chave gerada e use como `GEMINI_API_KEY`

## LP paralela (`/lp`)

Página pública independente do Figma, hospedada no mesmo app. Tem hero,
formulário de captura de lead e links para a calculadora (`/`) e para o
agente (`/agente`). O formulário envia o lead para `/api/lead`, que:

1. Salva uma cópia local em `data/leads_log.jsonl` (rede de segurança —
   **não confie só nisso**: no Render, o disco não é persistente entre
   deploys/restarts)
2. Repassa o lead para o webhook do n8n (`N8N_WEBHOOK_URL`), que já está
   conectado ao Slack e ao Google Sheets

Configure `N8N_WEBHOOK_URL` com a URL do node Webhook do seu workflow n8n
(a mesma que você já usa no fluxo Webhook → Slack). Sem essa variável
configurada, o lead ainda é salvo localmente, só não dispara o Slack/Sheets.

## Agente (`/agente`)

Chat com function calling: quando o usuário menciona um número de
colaboradores, o Gemini chama `calcular_economia()` no backend em vez de
estimar de cabeça — a matemática sempre vem do servidor, nunca do modelo.

## Base de parceiros: planilha do time de parcerias

Hoje a fonte de nome/categoria/desconto de parceiro é uma Google Sheet
mantida pelo time de parcerias — sem precisar de deploy pra atualizar.

**Estrutura da planilha** (primeira aba, primeira linha como cabeçalho):

| nome | categoria | status | desconto_pct |
|---|---|---|---|

- `categoria` precisa ser exatamente uma de: Conveniência, Refeição,
  Bem-estar, Mobilidade, Educação, Saúde, Cultura, Alimentação, Pets
- `status`: `Ativo` ou `Inativo`
- `desconto_pct`: só o número (ex: `15`), sem o símbolo `%`

**Configuração (uma vez só):**

1. Cria uma conta de serviço no Google Cloud com a Sheets API ativada,
   gera uma chave JSON
2. Compartilha a planilha com o e-mail da conta de serviço (campo
   `client_email` do JSON) como **Leitor**
3. No Render, configura:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — conteúdo inteiro do arquivo `.json`
   - `PARCEIROS_SHEET_ID` — o ID da planilha (entre `/d/` e `/edit` na URL)

**Cache:** os dados da planilha ficam em cache por 5 minutos — uma edição
do time de parcerias leva até esse tempo pra refletir no Mingo, sem
precisar reiniciar nada.

**Fallback:** se a planilha não estiver configurada, ou a leitura falhar
por qualquer motivo (credencial errada, planilha não compartilhada, etc.),
o app cai automaticamente para `data/parceiros.json` + `data/categorias.json`
(o snapshot local, extraído do Mapa de Parceiros B2C) — nunca quebra, só
fica desatualizado até o problema ser corrigido. O log do servidor mostra
`[AVISO] Não deu pra ler a planilha do Google...` quando isso acontece.

## Atualizar os dados de categoria

Quando o Mapa de Parceiros B2C mudar:

```bash
python scripts/extrair_categorias.py caminho/Mapa_de_Parceiros_B2C.xlsx data/categorias.json
```

Reinicie o servidor (ou faça redeploy) para os novos dados entrarem em vigor.

## Deploy no Render (via GitHub)

1. Crie um repositório no GitHub e suba este projeto:
   ```bash
   git init
   git add .
   git commit -m "MVP calculadora de economia — Clube Flash"
   git branch -M main
   git remote add origin <url-do-seu-repo>
   git push -u origin main
   ```
2. Em [render.com](https://render.com), clique em **New > Blueprint** e
   conecte o repositório. O Render lê o `render.yaml` deste projeto e
   configura o serviço automaticamente (build e start command já definidos).
   Ele vai pedir o valor de `GEMINI_API_KEY` durante a criação do Blueprint —
   cole a chave ali (nunca a coloque no `render.yaml` nem no código).
3. Alternativa manual: **New > Web Service**, aponte para o repositório,
   e configure:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
   - Em **Environment**, adicione a variável `GEMINI_API_KEY` com sua chave
4. Cada push na branch `main` gera um redeploy automático.

## Próximo passo (dado real)

Hoje `app.py` lê `data/categorias.json` como fonte de frequência de uso e
ticket médio (que são estimativas). Para plugar dado real:

1. Trocar a função `carregar_categorias()` em `app.py` por uma consulta ao
   Databricks/Metabase (uso real por colaborador e por categoria).
2. O front-end não muda — ele já consome tudo via `/api/categorias`.
