# Projeto: Pipeline de produção semi-automática para canal de YouTube (IA para vendas B2B)

## Contexto

Canal de YouTube **faceless** (sem aparecer em câmera) sobre **IA aplicada a vendas e operações comerciais**, para **BDRs/SDRs e gestores de vendas**. O dono do canal grava a própria voz e a própria tela. O pipeline automatiza o resto.

Objetivo: reduzir o tempo por vídeo de ~2h para **45 min a 1h**, com **orçamento zero em ferramentas** (tudo local/grátis, exceto o uso do Claude).

### Decisões já tomadas
- Idioma inicial: **português (BR)**. Depois, mesma estrutura em inglês (re-gravando a voz).
- Voz: **a do próprio criador** (gravada no celular). Não usar TTS por padrão, por risco de desmonetização ("conteúdo inautêntico/em massa").
- Formato: 6-8 min, gravação de tela + voz + b-roll + legendas + música.
- Cadência alvo: 2 vídeos/semana, mesmos dias e horário (sugestão: terça e quinta, 11h-12h, horário de Brasília).
- Lote mensal: 8 vídeos.

### Decisões em aberto (perguntar ao usuário antes de assumir)
- Idioma definitivo do canal 1 (PT-BR ou EN).
- Se vai usar TTS em algum caso (padrão: não).
- Nome do canal e identidade visual (cores sugeridas para thumbnail: fundo azul-marinho + texto amarelo/laranja).

---

## Regras inegociáveis

1. **Nunca publicar sem aprovação humana.** O pipeline para em um passo "aprovar?" antes do upload. O upload inicial é sempre como **privado/não listado** ou **agendado**, nunca público automaticamente.
2. **Dados fictícios em tudo.** Nunca usar telas, listas de leads, nomes de clientes ou dados internos do empregador do criador nas gravações, exemplos ou roteiros.
3. **Não inventar resultados.** Nada de "aumentei minha taxa de resposta em X%" a menos que o criador forneça o dado real. Placeholder obrigatório: `[INSERIR RESULTADO REAL]`.
4. **Fatos verificáveis.** Qualquer afirmação factual no roteiro deve ser marcada com `[VERIFICAR]` para revisão humana.
5. **Segredos fora do repositório.** Credenciais OAuth do YouTube, chaves de API e tokens ficam em `.env` / `client_secret.json`, listados no `.gitignore`. Nunca imprimir segredos nos logs.
6. **Nunca sobrescrever arquivos originais.** Gravações brutas em `input/` são somente leitura; todo resultado vai para `output/`.

---

## Estrutura de pastas

```
youtube-pipeline/
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── config.yaml              # idioma, cadência, cores, pesos de áudio, caminhos
├── pipeline.py              # orquestrador (CLI)
├── topics/
│   └── backlog.csv          # tema, status, data_alvo
├── templates/
│   ├── script_prompt.md     # prompt-base do roteiro
│   ├── description.md       # modelo de descrição + CTA + links
│   └── thumbnail.html       # template da miniatura (HTML -> PNG)
├── input/
│   └── <slug>/
│       ├── voice.wav        # voz gravada pelo criador
│       ├── screen.mp4       # gravação de tela
│       └── broll/           # clipes de b-roll (Pexels/Pixabay)
├── music/                   # trilhas livres (YouTube Audio Library)
├── output/
│   └── <slug>/
│       ├── script.md
│       ├── metadata.json    # título, descrição, tags, capítulos
│       ├── voice_clean.wav
│       ├── captions.srt
│       ├── video_final.mp4
│       ├── thumbnail.png
│       └── review.md        # checklist de aprovação
└── src/
    ├── script_gen.py
    ├── audio.py
    ├── captions.py
    ├── video.py
    ├── thumbnail.py
    └── upload.py
```

---

## Etapas do pipeline

Comando principal: `python pipeline.py <slug> [--stage <etapa>] [--dry-run]`

Cada etapa deve poder rodar isolada e ser **idempotente** (rodar de novo não duplica nem quebra).

### 1. `script`: roteiro + metadados
- Entrada: tema (linha do `backlog.csv`) + `templates/script_prompt.md`.
- Gera `script.md` com a estrutura: **Hook (0:00-0:25) → Problema → Passos (2-3) → Erros comuns → CTA**.
- Gera também `metadata.json`: 3 opções de título (SEO + curiosidade/número), descrição, 10-15 tags, capítulos com timestamps estimados e texto da thumbnail (máx. 4 palavras).
- Regras de conteúdo: tom de colega, não de guru; sem promessa de resultado; aplicar regras 3 e 4 acima.
- Saída para leitura em voz alta: ~150 palavras/minuto, frases curtas, marcação de pausas.

### 2. `audio`: limpeza da voz e mixagem
- Entrada: `input/<slug>/voice.wav`.
- FFmpeg: remover silêncios longos (`silenceremove`), normalizar volume (`loudnorm`, alvo ~-16 LUFS), redução leve de ruído.
- Mixar música de fundo de `music/` a **10-15% de volume** sob a voz, com fade in/out.
- Saída: `voice_clean.wav` e `audio_mix.wav`.

### 3. `captions`: legendas
- Whisper local (`faster-whisper`, modelo `small` ou `medium`, idioma conforme `config.yaml`).
- Saída `captions.srt`. Gerar também versão com palavras destacadas, se viável.
- Deixar o SRT editável: o criador revisa nomes de ferramentas e termos técnicos.

### 4. `video`: montagem
- FFmpeg (ou MoviePy) junta: `screen.mp4` + b-roll nos pontos marcados + `audio_mix.wav` + legendas queimadas.
- Resolução 1920x1080, 30 fps, H.264, AAC.
- Preferir gravação de tela como base; b-roll apenas como apoio (evitar vídeo 100% stock, que parece conteúdo em massa).
- Gerar também corte vertical 9:16 (30-45 s) para Shorts a partir do melhor trecho (hook + 1 passo).

### 5. `thumbnail`: miniatura
- `templates/thumbnail.html` com variáveis (texto, cor, ícone) → PNG 1280x720 via Playwright ou Pillow.
- Regras: máx. 4 palavras, contraste alto, sem rosto, 1 elemento gráfico (ex.: cronômetro, seta antes/depois).
- Gerar 2 variações (A/B) por vídeo.

### 6. `review`: portão de aprovação (obrigatório)
Gerar `review.md` com checklist para o criador marcar:
- [ ] Todos os `[VERIFICAR]` conferidos
- [ ] Nenhum `[INSERIR RESULTADO REAL]` restante
- [ ] Nenhum dado interno/real de cliente ou empregador na tela
- [ ] Título e thumbnail não prometem algo que o vídeo não entrega
- [ ] Legendas revisadas
- [ ] Áudio claro, sem trechos cortados
O upload só roda se `review.md` estiver totalmente marcado.

### 7. `upload`: YouTube Data API
- OAuth rodando **no computador do usuário** (fluxo local com navegador). Salvar token em arquivo ignorado pelo git.
- Define título, descrição, tags, thumbnail, categoria, idioma e **data de agendamento** (`publishAt`), com `privacyStatus: private` até a hora agendada.
- Respeitar a cota diária da API; registrar em log o que foi enviado.
- Suportar `--dry-run` que valida tudo sem enviar.

---

## Planejamento em lote (8 vídeos/mês)

`pipeline.py batch --month YYYY-MM` deve:
1. Ler os próximos 8 temas do `backlog.csv`.
2. Gerar roteiros e metadados de todos (etapa 1) para revisão em bloco.
3. Imprimir o calendário de publicação (2 por semana, dia/hora de `config.yaml`).

Fluxo sugerido do criador: fim de semana 1 revisa roteiros → semana 2 grava voz e tela → semana 3 roda áudio/legendas/vídeo/thumbnail → semana 4 revisa e agenda.

---

## Backlog inicial de temas (primeiros 6 vídeos)

1. Como pesquisar 50 prospects em 10 minutos com IA (workflow de BDR)
2. Por que seus cold emails são ignorados (não é o assunto)
3. 10 prompts de ChatGPT/Claude para vendedores (copiar e colar)
4. 5 erros de cold email que a IA corrige em 60 segundos
5. 3 ferramentas grátis de IA que substituem 2 horas de prospecção
6. Como montar um lead scoring no Excel com IA

---

## Stack e dependências

- Python 3.11+, FFmpeg, `faster-whisper`, `Pillow` ou `playwright`, `google-api-python-client`, `google-auth-oauthlib`, `pyyaml`, `pandas`.
- Claude (via Claude Code ou API) para a etapa 1.
- Tudo configurável via `config.yaml` e `.env`.

---

## Primeiras tarefas para o Claude Code

1. Criar a estrutura de pastas, `requirements.txt`, `.gitignore` (incluindo `.env`, `client_secret.json`, `token.json`, `input/`, `output/`) e `config.yaml` com valores padrão.
2. Implementar `pipeline.py` com CLI e as etapas **1 (script)**, **2 (audio)** e **3 (captions)**; testar com um áudio de exemplo curto.
3. Implementar etapa **4 (video)** e **5 (thumbnail)**.
4. Implementar etapa **6 (review)** e, por último, a **7 (upload)** com `--dry-run`.
5. Escrever `README.md` com passo a passo de instalação (Windows/macOS), como gravar (dicas de áudio) e como criar as credenciais do YouTube.

Ao terminar cada tarefa, rodar um teste simples e resumir em 2-3 linhas o que funcionou e o que falta. Perguntar antes de tomar qualquer decisão listada em "Decisões em aberto".

---

## Estilo de trabalho esperado

- Respostas curtas e objetivas, em português.
- Antes de instalar algo ou gastar créditos de API, avisar.
- Preferir soluções grátis e locais; sinalizar quando algo exigir plano pago.
- Código simples e comentado, fácil de o criador entender e editar.
