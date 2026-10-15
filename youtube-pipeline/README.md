# YouTube Pipeline

Pipeline semi-automático para um canal faceless sobre IA aplicada a vendas B2B.
Você grava voz e tela; o pipeline faz roteiro, limpeza de áudio, legendas, montagem, miniatura, revisão e upload agendado.
Regras do projeto: veja `CLAUDE.md` (nada publica sem sua aprovação; só dados fictícios; nada de resultados inventados).

## 1. Instalação

Precisa de **Python 3.11+** e **FFmpeg**.

**macOS** (com [Homebrew](https://brew.sh))
```bash
brew install python ffmpeg
```

**Windows** (PowerShell)
```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```
Feche e abra o terminal depois. Confira com `python --version` e `ffmpeg -version`.

Depois, na pasta do projeto:
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```
Na primeira legenda, o `faster-whisper` baixa o modelo (`small`, ~500 MB). É grátis e roda local.

## 2. Uso

```bash
python pipeline.py batch --month 2026-11     # roteiros do mês + calendário (terça/quinta)
python pipeline.py 1                         # roda script, audio, captions, video, thumbnail do tema 1
python pipeline.py <slug> --stage audio      # uma etapa isolada
python pipeline.py <slug> --stage review     # cria/confere o checklist
python pipeline.py <slug> --stage upload --publish-at 2026-11-03T11:30:00-03:00 --dry-run
```
`<slug>` ou o número da linha do `topics/backlog.csv`. Todas as etapas são idempotentes: rodar de novo pula o que já existe (apague o arquivo de saída para refazer).

**Roteiro sem gastar API:** sem `ANTHROPIC_API_KEY` (ou com `--dry-run`), a etapa `script` só salva `output/<slug>/prompt.txt`. Cole no Claude, e salve a resposta em `script.md` e `metadata.json`. Com a chave no `.env`, a etapa chama a API (**isso consome créditos**).

### Fluxo de um vídeo
1. `script` -> revise `script.md`; resolva todos os `[VERIFICAR]` e `[INSERIR RESULTADO REAL]` (apague a marca depois de conferir).
2. Grave voz e tela. Coloque em `input/<slug>/voice.wav` e `screen.mp4` (b-roll opcional em `broll/` + `broll.csv` com `arquivo,inicio,duracao`). Músicas livres em `music/`.
3. `audio` -> `captions` -> **edite `captions.srt`** (nomes de ferramentas) -> `video` -> `thumbnail`.
4. `review` -> marque `[x]` em todos os itens de `output/<slug>/review.md`.
5. `upload --dry-run`, depois sem `--dry-run`. O vídeo sobe **privado** e agendado.

`input/` nunca é alterado; tudo sai em `output/`.

## 3. Dicas de gravação de voz (celular)
- Ambiente pequeno e com tecidos (quarto, closet); evite cozinha e sala vazia (eco).
- Celular a ~20 cm da boca, levemente de lado (evita estouro de "p" e "b"). Modo avião.
- Grave um teste de 10 s e ouça com fones antes de gravar tudo.
- Fale em frases curtas, com pausa entre elas: o pipeline corta silêncios longos.
- Em caso de erro, pare 2 s e repita a frase; fica fácil de achar e cortar.
- Exporte/transfira como WAV (ou M4A e converta: `ffmpeg -i voz.m4a voice.wav`).
- Na gravação de tela, use só dados fictícios.

## 4. Credenciais do YouTube (OAuth)
Só o upload precisa. Faça no seu computador:
1. Acesse [Google Cloud Console](https://console.cloud.google.com), crie um projeto.
2. **APIs e serviços > Biblioteca** -> ative **YouTube Data API v3**.
3. **Tela de consentimento OAuth**: tipo *Externo*; adicione seu e-mail como **usuário de teste**.
4. **Credenciais > Criar credenciais > ID do cliente OAuth > App para computador**. Baixe o JSON e salve como `client_secret.json` na raiz do projeto.
5. No primeiro upload, abre o navegador para você autorizar; o token fica em `token.json`.

`client_secret.json`, `token.json` e `.env` estão no `.gitignore`: **nunca os envie ao git**.

Observações:
- A cota padrão da API é 10.000 unidades/dia e cada upload custa ~1.600: dá para ~6 por dia, sobra para 2 por semana.
- Projetos de API **não verificados** podem forçar vídeos enviados a ficarem privados e travados. O agendamento (`publishAt`) pode não publicar sozinho nesse caso. Se isso acontecer, solicite a auditoria do projeto da API ou publique manualmente no YouTube Studio.

## 5. Configuração
Tudo em `config.yaml` (idioma, cadência, volume da música, cores da miniatura, modelo do Whisper).
