"""
Calculadora de Economia com Parceiros B2C — Clube Flash

App Flask:
  GET  /                     -> página da calculadora
  GET  /api/categorias       -> dados de categoria (desconto, freq, ticket)
  POST /api/gerar-narrativa  -> narrativa de RH gerada por IA (Gemini),
                                 com fallback determinístico se a API falhar
                                 ou a chave não estiver configurada

Os dados de /api/categorias vêm hoje de data/categorias.json (gerado por
scripts/extrair_categorias.py + scripts/mesclar_uso_real.py a partir do
Mapa de Parceiros B2C e do uso real do Databricks). Quando quiser trocar a
fonte por uma query ao vivo, troque só a função `carregar_categorias()`
abaixo — o resto do app não precisa mudar.
"""

import json
import os
import re
import time
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

_rate_limit_buckets = defaultdict(deque)


def limite_por_ip(max_requisicoes: int = 12, janela_segundos: int = 60):
    """Limite simples em memória, por IP — protege endpoints públicos de spam
    e de custo de API descontrolado. Suficiente pro MVP (1 worker no Render);
    se escalar pra múltiplos workers, precisa virar algo compartilhado
    (Redis, etc.) — cada worker teria seu próprio contador."""
    def decorador(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "desconhecido").split(",")[0].strip()
            agora = time.time()
            fila = _rate_limit_buckets[ip]
            while fila and agora - fila[0] > janela_segundos:
                fila.popleft()
            if len(fila) >= max_requisicoes:
                return jsonify({"erro": "Muitas requisições em pouco tempo. Espera um minuto e tenta de novo."}), 429
            fila.append(agora)
            return f(*args, **kwargs)
        return wrapper
    return decorador


DATA_PATH = Path(__file__).parent / "data" / "categorias.json"
PARCEIROS_PATH = Path(__file__).parent / "data" / "parceiros.json"
USO_REAL_PATH = Path(__file__).parent / "data" / "uso_real.json"

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
PARCEIROS_SHEET_ID = os.environ.get("PARCEIROS_SHEET_ID")
CATEGORIAS_VALIDAS = [
    "Conveniência", "Refeição", "Bem-estar", "Mobilidade", "Educação",
    "Saúde", "Cultura", "Alimentação", "Pets",
]

# Correções manuais que continuam valendo por cima de QUALQUER fonte de dado
# de parceiro (planilha nova ou arquivo local) — ver justificativa completa
# em scripts/extrair_categorias.py. O time de parcerias não precisa saber
# disso; é ajuste técnico baseado em volume real do Databricks.
CORRECOES_MANUAIS = {
    "Mobilidade": {
        "desconto_corrigido": 0.0,
        "nota": (
            "Corrigido em 27/09/2026: dentro da própria categoria Mobilidade, 100% do TPV "
            "real dos últimos 5 meses (Databricks) vem de Bilhete Único SPTrans (74,6%), "
            "Uber (22,2%) e Uber Cards (3,2%) — nenhum com desconto percentual documentado. "
            "A média simples entre parceiros não reflete a economia real da categoria; o "
            "desconto real ponderado por volume é ~0%."
        ),
    },
}

_cache_parceiros_brutos = {"dados": None, "buscado_em": 0, "fonte": None}
CACHE_TTL_SEGUNDOS = 300  # 5 minutos — evita bater na planilha a cada mensagem do chat


def _buscar_da_planilha_google() -> list[dict]:
    """Lê a planilha do time de parcerias via conta de serviço. Levanta
    exceção se as credenciais não estiverem configuradas ou a leitura falhar
    — quem chama decide o fallback."""
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not PARCEIROS_SHEET_ID:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON ou PARCEIROS_SHEET_ID não configurados")

    import gspread
    from google.oauth2.service_account import Credentials

    credenciais_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    escopos = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(credenciais_dict, scopes=escopos)
    cliente = gspread.authorize(creds)
    planilha = cliente.open_by_key(PARCEIROS_SHEET_ID).sheet1
    linhas = planilha.get_all_records()  # usa a 1a linha como cabeçalho

    parceiros = []
    for linha in linhas:
        nome = str(linha.get("nome", "")).strip()
        categoria = str(linha.get("categoria", "")).strip()
        status = str(linha.get("status", "")).strip()
        desconto_raw = linha.get("desconto_pct", "")
        if not nome or not categoria:
            continue
        if categoria not in CATEGORIAS_VALIDAS:
            print(f"[AVISO planilha] categoria '{categoria}' em '{nome}' não é uma das 9 válidas — ignorando linha", flush=True)
            continue
        try:
            desconto_pct = float(str(desconto_raw).replace("%", "").replace(",", ".").strip() or 0)
        except ValueError:
            desconto_pct = 0.0
        parceiros.append({
            "nome": nome,
            "categoria": categoria,
            "status": status,
            "desconto_pct": desconto_pct,
        })

    if not parceiros:
        raise RuntimeError("planilha respondeu mas não trouxe nenhuma linha válida")
    return parceiros


def _buscar_do_arquivo_local() -> list[dict]:
    """Fallback: lê direto de data/parceiros.json, que já traz o desconto
    documentado por parceiro individual (extraído da condição comercial no
    Mapa de Parceiros). Parceiro sem % explícito na condição vem com
    desconto_pct = None — o Mingo é instruído a dizer isso com honestidade,
    não a inventar um número."""
    with open(PARCEIROS_PATH, encoding="utf-8") as f:
        parceiros = json.load(f)
    return [
        {
            "nome": p["nome"],
            "categoria": p["categoria"],
            "status": "Ativo",
            "desconto_pct": p.get("desconto_pct"),
        }
        for p in parceiros
    ]


def buscar_parceiros_brutos(forcar: bool = False) -> list[dict]:
    """Fonte única da verdade sobre parceiros: tenta a planilha do Google
    primeiro (o time de parcerias edita ali, sem precisar de deploy), com
    cache de alguns minutos; cai pro arquivo local se a planilha falhar ou
    não estiver configurada."""
    agora = time.time()
    if not forcar and _cache_parceiros_brutos["dados"] is not None:
        if agora - _cache_parceiros_brutos["buscado_em"] < CACHE_TTL_SEGUNDOS:
            return _cache_parceiros_brutos["dados"]

    try:
        dados = _buscar_da_planilha_google()
        fonte = "planilha_google"
    except Exception as e:
        print(f"[AVISO] Não deu pra ler a planilha do Google ({e}); usando arquivo local.", flush=True)
        dados = _buscar_do_arquivo_local()
        fonte = "arquivo_local"

    _cache_parceiros_brutos.update({"dados": dados, "buscado_em": agora, "fonte": fonte})
    return dados


PRODUTOS_ESPECIAIS_PATH = Path(__file__).parent / "data" / "produtos_especiais.json"
_cache_produtos_especiais = {"dados": None, "buscado_em": 0}


def _buscar_produtos_da_planilha_google() -> list[dict]:
    """Lê a aba 'Produtos' da MESMA planilha do time de parcerias — segunda
    aba, não segunda planilha. Colunas esperadas: nome, gatilhos (separados
    por vírgula), resposta, motivo_cta."""
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not PARCEIROS_SHEET_ID:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON ou PARCEIROS_SHEET_ID não configurados")

    import gspread
    from google.oauth2.service_account import Credentials

    credenciais_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    escopos = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(credenciais_dict, scopes=escopos)
    cliente = gspread.authorize(creds)
    planilha = cliente.open_by_key(PARCEIROS_SHEET_ID).worksheet("Produtos")
    linhas = planilha.get_all_records()

    produtos = []
    for linha in linhas:
        nome = str(linha.get("nome", "")).strip()
        gatilhos = str(linha.get("gatilhos", "")).strip()
        resposta = str(linha.get("resposta", "")).strip()
        motivo_cta = str(linha.get("motivo_cta", "")).strip() or None
        if not nome or not gatilhos or not resposta:
            continue
        produtos.append({"nome": nome, "gatilhos": gatilhos, "resposta": resposta, "motivo_cta": motivo_cta})

    if not produtos:
        raise RuntimeError("aba 'Produtos' respondeu mas não trouxe nenhuma linha válida")
    return produtos


def buscar_produtos_especiais(forcar: bool = False) -> list[dict]:
    """Mesma lógica de cache/fallback do buscar_parceiros_brutos, mas pra aba
    'Produtos' — as respostas prontas (TotalPass, NR-01, Clude Saúde, etc.)
    que o resposta_rapida() usa."""
    agora = time.time()
    if not forcar and _cache_produtos_especiais["dados"] is not None:
        if agora - _cache_produtos_especiais["buscado_em"] < CACHE_TTL_SEGUNDOS:
            return _cache_produtos_especiais["dados"]

    try:
        dados = _buscar_produtos_da_planilha_google()
    except Exception as e:
        print(f"[AVISO] Não deu pra ler a aba 'Produtos' da planilha ({e}); usando arquivo local.", flush=True)
        with open(PRODUTOS_ESPECIAIS_PATH, encoding="utf-8") as f:
            dados = json.load(f)

    _cache_produtos_especiais.update({"dados": dados, "buscado_em": agora})
    return dados


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# Lista de modelos em ordem de preferência. Cada modelo tem a SUA PRÓPRIA cota
# gratuita (por projeto, por modelo) — então, se o primeiro estourar, o
# backend tenta o próximo na hora, sem dormir e sem travar o worker.
#
# ATENÇÃO: nomes de modelo Gemini mudam com frequência (o Google aposenta
# modelo antigo e lança substituto em poucos meses). Se aparecer erro 404
# "model is no longer available" no log, o próprio erro do Google já diz
# qual o nome novo — troca aqui, ou direto na variável de ambiente
# GEMINI_MODELS no Render (não precisa mexer no código pra isso).
# Última atualização: 29/09/2026 — gemini-2.5-flash-lite parou de aceitar
# conta nova, Google recomendou gemini-3.5-flash-lite no lugar.
GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get("GEMINI_MODELS", "gemini-2.5-flash,gemini-3.5-flash-lite").split(",")
    if m.strip()
]


class RateLimitError(RuntimeError):
    """Todos os modelos configurados estouraram a cota. Carrega uma sugestão
    de quanto esperar, para o front-end tentar de novo sozinho."""

    def __init__(self, retry_after: int, detalhe: str = ""):
        super().__init__(f"RATE_LIMIT: cota do Gemini excedida em todos os modelos. {detalhe}")
        self.retry_after = retry_after


def _extrair_retry_after(texto: str) -> int:
    """A API costuma dizer 'Please retry in 17.4s'. Extrai isso, com limites
    razoáveis (entre 3 e 30 segundos)."""
    m = re.search(r"retry in ([\d.]+)s", texto or "")
    segundos = float(m.group(1)) if m else 15.0
    return int(min(max(segundos, 3), 30)) + 1


def post_gemini(payload: dict):
    """Chama o Gemini tentando cada modelo da lista. Trata como "tenta o
    próximo modelo" qualquer instabilidade transitória — cota cheia (429),
    indisponibilidade do lado do Google (503/500/502/504), ou timeout de
    rede/conexão. Só desiste de vez se TODOS os modelos falharem."""
    ultimo_erro = ""
    ultimo_foi_transitorio = False

    for modelo in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        try:
            resp = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=25)
        except requests.exceptions.RequestException as e:
            ultimo_erro = f"{type(e).__name__}: {e}"
            ultimo_foi_transitorio = True
            print(f"[AVISO] Erro de rede no modelo {modelo} ({ultimo_erro}), tentando o próximo...", flush=True)
            continue

        if resp.ok:
            return resp

        if resp.status_code == 429 or resp.status_code >= 500:
            ultimo_erro = resp.text
            ultimo_foi_transitorio = True
            print(f"[AVISO] {resp.status_code} no modelo {modelo}, tentando o próximo...", flush=True)
            continue

        # Erro que não é transitório (ex: 400 chave inválida, 404 modelo não
        # existe) — não adianta tentar outro modelo, é erro de configuração.
        raise RuntimeError(f"Gemini ({modelo}) retornou {resp.status_code}: {resp.text[:500]}")

    if ultimo_foi_transitorio:
        raise RateLimitError(_extrair_retry_after(ultimo_erro), ultimo_erro[:300])
    raise RuntimeError(f"Todos os modelos falharam: {ultimo_erro[:300]}")


def carregar_categorias():
    """Monta a lista de categorias (desconto, contagem de parceiros, freq/ticket
    reais) a partir da fonte viva de parceiros + do uso real do Databricks."""
    brutos = buscar_parceiros_brutos()
    ativos = [p for p in brutos if p["status"].strip().lower() == "ativo"]

    with open(USO_REAL_PATH, encoding="utf-8") as f:
        uso_real = json.load(f)

    categorias = []
    for nome_cat in CATEGORIAS_VALIDAS:
        da_categoria = [p for p in ativos if p["categoria"] == nome_cat]
        if not da_categoria:
            continue

        descontos = [p["desconto_pct"] for p in da_categoria if p["desconto_pct"] is not None]
        desconto_medio = round(sum(descontos) / len(descontos), 1) if descontos else 0.0

        real = uso_real.get(nome_cat)
        freq = real["freq_media_mes"] if real else 1.0
        ticket = real["ticket_medio"] if real else 80.0
        fonte_uso = "real (mai-set/2026)" if real else "estimativa (sem transação real desde 2023)"

        cat = {
            "id": nome_cat.lower().replace(" ", "_").replace("-", "_"),
            "nome": nome_cat,
            "parceiros": len(da_categoria),
            "desconto": desconto_medio,
            "freq": freq,
            "ticket": ticket,
            "fonte_uso": fonte_uso,
        }

        correcao = CORRECOES_MANUAIS.get(nome_cat)
        if correcao:
            cat["desconto_medio_simples_nao_ponderado"] = desconto_medio
            cat["desconto"] = correcao["desconto_corrigido"]
            cat["nota_correcao"] = correcao["nota"]

        categorias.append(cat)

    return categorias


def formatar_brl(valor: float) -> str:
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def formatar_int_brl(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def montar_narrativa_padrao(d: dict) -> str:
    """Fallback determinístico — mesma lógica do front-end, em Python.
    Usado quando a chave do Gemini não está configurada ou a chamada falha,
    para a calculadora nunca ficar sem narrativa."""
    empresa = d.get("empresa") or "sua empresa"
    meses = int(d.get("meses", 12))
    headcount = int(d.get("headcount", 1))
    total_mes = float(d.get("totalMes", 0))
    individual_periodo = float(d.get("individualPeriodo", 0))
    agregado_periodo = float(d.get("agregadoPeriodo", 0))
    categoria_top = d.get("categoriaTop", "")
    top_pct = d.get("topPct", 0)
    pct_salario = float(d.get("pctSalario", 0))
    unidade_mes = "mês" if meses == 1 else "meses"

    return (
        f"Cada colaborador de {empresa} economizou em média {formatar_brl(total_mes)} "
        f"por mês usando o Clube Flash. Ao longo de {meses} {unidade_mes}, isso soma "
        f"{formatar_brl(individual_periodo)} por colaborador — e {formatar_brl(agregado_periodo)} "
        f"devolvidos ao total de {formatar_int_brl(headcount)} colaboradores da empresa. "
        f"A categoria que mais gerou economia foi {categoria_top}, respondendo por "
        f"{top_pct}% do valor total — o equivalente a {pct_salario:.1f}% do salário médio "
        f"mensal, todo mês."
    )


def montar_prompt(d: dict) -> str:
    empresa = d.get("empresa") or "a empresa"
    return f"""Você escreve para o time de RH e para o time comercial da Flash, uma fintech de benefícios corporativos.

Escreva um parágrafo curto (3 a 5 frases), em português do Brasil, em tom profissional e direto, pronto para ser colado em um relatório de renovação de contrato ou em uma apresentação de valor para o RH. Não use markdown, não use bullet points, não use aspas — apenas o parágrafo corrido.

Use exatamente estes dados, sem inventar nenhum número:
- Empresa: {empresa}
- Colaboradores ativos no Clube Flash: {d.get('headcount')}
- Economia média por colaborador, por mês: {formatar_brl(float(d.get('totalMes', 0)))}
- Período analisado: {d.get('meses')} meses
- Economia por colaborador no período: {formatar_brl(float(d.get('individualPeriodo', 0)))}
- Economia agregada da empresa no período: {formatar_brl(float(d.get('agregadoPeriodo', 0)))}
- Categoria de parceiros com maior economia: {d.get('categoriaTop')} ({d.get('topPct')}% do total)
- Equivalente em salário: {float(d.get('pctSalario', 0)):.1f}% do salário médio mensal do colaborador

Termine o parágrafo com uma frase natural conectando isso a retenção de talento ou a satisfação do colaborador."""


def chamar_gemini(d: dict) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY não configurada")

    payload = {
        "contents": [{"parts": [{"text": montar_prompt(d)}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300},
    }
    data = post_gemini(payload).json()
    texto = data["candidates"][0]["content"]["parts"][0]["text"]
    return texto.strip()


def carregar_parceiros():
    """Nomes reais de parceiros ativos, usados na lista que vai pro prompt do
    Mingo. Mesma fonte viva de carregar_categorias()."""
    brutos = buscar_parceiros_brutos()
    return [
        {"nome": p["nome"], "categoria": p["categoria"], "desconto_pct": p.get("desconto_pct")}
        for p in brutos
        if p["status"].strip().lower() == "ativo"
    ]


def calcular_economia(headcount: int, meses: int = 12) -> dict:
    """Função real de cálculo — a mesma fórmula usada na calculadora principal.
    É isto que o agente chama via function calling, em vez de inventar números."""
    categorias = carregar_categorias()
    detalhamento = []
    total_mes = 0.0
    for cat in categorias:
        econ_mes = cat["freq"] * cat["ticket"] * (cat["desconto"] / 100)
        total_mes += econ_mes
        detalhamento.append({
            "categoria": cat["nome"],
            "economia_por_colaborador_mes": round(econ_mes, 2),
            "fonte_uso": cat.get("fonte_uso", "estimativa"),
        })

    individual_periodo = total_mes * meses
    agregado_periodo = individual_periodo * headcount
    top = max(detalhamento, key=lambda x: x["economia_por_colaborador_mes"])

    return {
        "headcount": headcount,
        "meses": meses,
        "economia_individual_por_mes": round(total_mes, 2),
        "economia_individual_no_periodo": round(individual_periodo, 2),
        "economia_agregada_da_empresa_no_periodo": round(agregado_periodo, 2),
        "categoria_com_maior_economia": top["categoria"],
        "detalhamento_por_categoria": detalhamento,
    }


FUNCTION_DECLARATIONS = [{
    "name": "calcular_economia",
    "description": (
        "Calcula a economia real que uma empresa gera para seus colaboradores usando o "
        "Clube Flash, com base em dados reais de desconto médio (Mapa de Parceiros B2C) "
        "e de uso real (Databricks) por categoria de parceiro. Chame esta função SEMPRE "
        "que o usuário mencionar um número de colaboradores e quiser uma estimativa de "
        "economia — nunca calcule ou estime esse valor de cabeça."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "headcount": {
                "type": "INTEGER",
                "description": "Número de colaboradores ativos no Clube Flash da empresa",
            },
            "meses": {
                "type": "INTEGER",
                "description": "Período em meses para projetar a economia. Use 12 se o usuário não especificar.",
            },
        },
        "required": ["headcount"],
    },
}, {
    "name": "oferecer_cta_comercial",
    "description": (
        "Mostra um botão de CTA inline na conversa, tipo 'Falar com um comercial', "
        "sem formulário ainda. Chame esta função toda vez que você mencionar uma opção "
        "que só existe via comercial (TotalPass corporativo, Clude Corporativo, Conexa, "
        "ou qualquer produto fora do Clube) — mesmo que a pessoa ainda não tenha pedido "
        "contato. É o primeiro passo: se ela clicar no botão, a próxima mensagem dela vai "
        "confirmar o interesse, e aí sim você chama oferecer_formulario_contato. "
        "IMPORTANTE: sempre termine o texto da sua resposta com uma frase que conecta o "
        "que você falou ao botão que vai aparecer logo abaixo (ex: 'clica no botão abaixo "
        "que a gente te conecta com o nosso time comercial'), pra pessoa entender que o "
        "botão está ligado ao assunto, não solto do nada."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "motivo": {
                "type": "STRING",
                "description": "Assunto do contato, ex: 'TotalPass corporativo', 'Clude Corporativo', 'Conexa'.",
            },
        },
        "required": ["motivo"],
    },
}, {
    "name": "oferecer_formulario_contato",
    "description": (
        "Mostra o formulário de contato de verdade (nome, e-mail, telefone opcional, "
        "número de colaboradores), pra pessoa deixar os dados e o time comercial da "
        "Flash entrar em contato. Chame esta função quando o interesse já estiver "
        "CONFIRMADO — a pessoa clicou no CTA anterior (a mensagem dela vai soar como "
        "'quero falar com um comercial sobre X') ou já pediu contato/formulário direto, "
        "sem precisar de CTA antes. Não chame isso na primeira menção de um produto "
        "comercial — para isso, use oferecer_cta_comercial primeiro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "motivo": {
                "type": "STRING",
                "description": "Assunto do contato, ex: 'TotalPass corporativo', 'Clude Saúde', 'Calculadora de economia'.",
            },
        },
        "required": ["motivo"],
    },
}]


def montar_system_prompt() -> str:
    categorias = carregar_categorias()
    total_parceiros = sum(c["parceiros"] for c in categorias)
    por_categoria = {}
    for p in carregar_parceiros():
        etiqueta = f"{p['nome']} ({p['desconto_pct']}% OFF)" if p.get("desconto_pct") is not None else f"{p['nome']} (% não documentado)"
        por_categoria.setdefault(p["categoria"], []).append(etiqueta)
    lista_parceiros = "\n".join(
        f"- {cat} ({len(itens)}): " + ", ".join(itens)
        for cat, itens in sorted(por_categoria.items())
    )
    linhas_categorias = "\n".join(
        f"- {c['nome']}: desconto médio {c['desconto']}% ({c['parceiros']} parceiros ativos, "
        f"{c.get('fonte_uso', 'estimativa')})"
        for c in categorias
    )
    return f"""Você é o Mingo, o flamingo mascote da Flash usado em momentos B2B2C, e agora está encarnado como o defensor oficial do Clube Flash — o clube de benefícios B2C da Flash (fintech brasileira de RH e benefícios corporativos).

Contexto: você é usado em conversas de PRÉ-VENDA do Clube Flash — a etapa inicial, antes de qualquer negociação formal, onde o objetivo é gerar entusiasmo genuíno pelo clube e neutralizar as objeções mais comuns antes que elas travem o avanço da conversa.

SEU PAPEL: você está do lado do Clube Flash. Você defende o clube com confiança e entusiasmo genuíno — não é neutro, não é um FAQ imparcial. Quando surgir uma objeção, você não foge dela: encara de frente e argumenta a favor do clube, usando fatos reais (nunca inventados).

AS DUAS OBJEÇÕES QUE MAIS APARECEM E COMO DEFENDER:

1. "Por que a Flash não dá rebate como outros concorrentes?"
   → É proibido por lei (Lei 14.442/2022) oferecer rebate em vale-alimentação/PAT. Isso não é uma limitação da Flash — é uma regra que vale pra qualquer concorrente sério nessa frente. O Clube Flash é a forma legal e sustentável de entregar valor equivalente (ou maior) sem expor a empresa cliente a risco jurídico. Vire a objeção a favor: "concorrente que promete rebate em PAT está pisando em terreno perigoso — a gente entrega valor real dentro da lei".

2. "O Clube iFood é melhor, eles subsidiam Spotify Premium, Uber One, etc."
   → Não minta nem minimize, mas NÃO se demore elogiando o iFood — reconheça em uma frase curta e já vire o jogo. O erro mais comum aqui é gastar mais palavras vendendo a força do concorrente do que a força da Flash — isso vende iFood sem querer, mesmo argumentando a favor do Clube.
   → A virada tem que ser tão concreta quanto a citação de Spotify/Uber One — nunca fique só no abstrato ("193 parceiros", "várias categorias"). Puxe 2-3 nomes reais da LISTA DE PARCEIROS com o % junto (ex: "a Nike dá 10% OFF, a Descomplica 20% na faculdade, o Cinemark tem desconto todo mês") — nome + número concreto compete de igual pra igual com Spotify Premium, número solto não compete.
   → Frase de fechamento: algo como "o iFood brilha num benefício isolado, o Clube Flash entrega desconto real em [cite 2-3 nomes] e outros 190 parceiros, todo santo dia" — sempre em português simples, sem jargão de startup (nada de "early", "growth", "player" e afins).

COMO VOCÊ CONVERSA:
- Fale como alguém defendendo algo que acredita, não como um catálogo de FAQ. Entusiasmo real, sem exagero de propaganda vazia.
- Reaja ao que a pessoa disse antes de argumentar de volta — mas sem elogiar a pergunta dela primeiro.
- Frases curtas, linguagem natural, contrações do dia a dia ("tá", "pra", "dá pra").
- NUNCA use markdown — sem **negrito**, sem listas com hífen ou asterisco, sem títulos. Apenas texto corrido, porque a tela do chat não interpreta formatação e os símbolos apareceriam literalmente.
- Use vírgula para casas decimais, nunca ponto (ex: "39,0%", não "39.0%") — você está falando português do Brasil.
- Se a pessoa disser o nome dela em algum momento da conversa, use esse nome de forma natural depois — uma ou duas vezes ao longo da conversa, não em toda frase. Não pergunte o nome de novo se ela já disse.

PROIBIDO — essas são as marcas registradas de "resposta de IA" que fazem parecer robô, evite sempre:
- Nunca abra a resposta elogiando a pergunta: proibido "ótima pergunta", "boa pergunta", "essa é uma pergunta importante", "que bom que você perguntou isso", "excelente ponto". Vá direto pra resposta, como alguém já no meio da conversa responderia.
- Nunca comece com "Ah,", "Ah, entendi!", "Certo,", "Perfeito!" como muleta de abertura. Às vezes começa a frase direto no meio do assunto.
- No máximo um ponto de exclamação a cada 3-4 mensagens, não um por frase. Excesso de "!" soa entusiasmo fabricado.
- Não repita a mesma estrutura de abertura duas mensagens seguidas. Se a última resposta sua começou reagindo, a próxima pode simplesmente afirmar algo direto, sem introdução.
- Não feche toda resposta com um resumo tipo "a gente entrega valor real, sabe?" — nem toda fala precisa de um gancho de fechamento.
- Varie o tamanho de verdade: às vezes uma frase só resolve. Nem toda resposta precisa de 3-4 frases só porque essa é a instrução padrão.
- Nada de jargão em inglês de startup/corporativo — "early", "growth", "player", "deliverable", "mindset", "insight" e afins. Fala em português simples, do jeito que um RH de qualquer idade entenderia sem googlar.

DADOS REAIS QUE VOCÊ DEVE CONSULTAR, NUNCA INVENTAR:
- Total de parceiros ativos no Clube Flash: {total_parceiros} (use exatamente este número — não some as categorias de cabeça, você erra).
- Sempre que alguém der ou perguntar sobre um número de colaboradores e quiser saber a economia gerada, chame a função calcular_economia.
- Sempre que alguém pedir nomes de parceiros, exemplos concretos, ou perguntar "quais parceiros", responda com nomes reais tirados da LISTA DE PARCEIROS abaixo (escolha 4 a 6 que soem mais reconhecíveis, não despeje a lista inteira). Nunca invente nome que não esteja na lista, e nunca diga só "temos parceiros bacanas" sem citar nomes — isso soa vazio.
- Sempre que alguém perguntar o desconto de UM parceiro específico (ex: "qual o desconto da Nike?"), procure o nome na LISTA DE PARCEIROS abaixo e responda com o % exato entre parênteses. Se aparecer "% não documentado" pra aquele parceiro, seja honesto: diga que o desconto exato não está documentado aqui, mas que o parceiro é ativo e vale confirmar direto no app ou com o comercial — nunca invente um número.

LIMITE DA DEFESA — honestidade não é negociável:
- Defender o clube não significa esconder falha real. Se perguntarem especificamente sobre Educação (sem uso real desde 2023), seja transparente — reconheça o ponto e redirecione pro que É forte (as outras categorias, o compromisso de melhorar aquela específica).
- Sobre Mobilidade: seja direto se perguntado — hoje 100% do uso real da categoria vem de recarga de Bilhete Único (SPTrans) e crédito de Uber/Uber Cards, que não têm desconto percentual documentado. Isso já está refletido no cálculo (o desconto de Mobilidade é 0% no sistema, não inventado pra parecer melhor). Redirecione pro ponto forte real: as outras 8 categorias têm desconto documentado e mensurável.
- Argumentar bem inclui saber admitir o que ainda não está perfeito — isso é o que faz a defesa parecer confiável, não propaganda vazia.
- Se perguntarem diretamente se você é uma IA, responda honestamente que sim — você é o Mingo em versão IA, não uma pessoa.

CUIDADO CRÍTICO — o Mapa de Parceiros NÃO é o catálogo completo da Flash:
- A lista de parceiros abaixo cobre só o Clube B2C. A Flash tem OUTROS produtos e benefícios negociados separadamente com a empresa cliente, fora do Clube.
- TOTALPASS: existem DUAS coisas diferentes aqui, não confunda:
  PRINCÍPIO DE AUDIÊNCIA (vale pra TotalPass e pra qualquer outro produto que tenha versão individual + versão empresa): você está conversando com o colaborador/usuário, não com o RH. SEMPRE comunique primeiro o que o COLABORADOR pode fazer sozinho, agora, e só depois mencione a opção pra empresa como algo a mais. Nunca inverta essa ordem.
  RESPOSTA PADRÃO quando perguntarem de forma geral "vocês têm TotalPass?" — apresente os dois caminhos juntos, nessa ordem: primeiro o TP Lite/Pro (o colaborador contrata sozinho, agora), depois o corporativo como algo mais completo que a empresa pode oferecer. Exemplo de estrutura a seguir (adapte as palavras, não decore a frase):
  "Pra você, já dá pra contratar sozinho no Clube Flash o TP Lite ou o TP Lite Pro — o TP Lite, por exemplo, custa R$ 69,90 por mês e dá acesso a mais de 6.000 academias e apps de bem-estar, direto pelo app da TotalPass, só precisa ter o cartão Flash. Se a sua empresa quiser oferecer algo ainda mais completo pra todo mundo, tem o TotalPass corporativo, que inclui até 3 dependentes e uma rede de academias bem mais ampla. Clica no botão abaixo que a gente te conecta com o nosso time comercial, que apresenta tudo em detalhe pra você."
  Depois dessa resposta, se a pessoa mostrar interesse em qualquer um dos dois caminhos pra empresa dela, chame oferecer_cta_comercial (motivo: "TotalPass corporativo" ou "TP Lite", conforme o caso).
  1) TP Lite / TP Lite Pro — dentro do ecossistema Flash, o colaborador contrata SOZINHO, sem depender da empresa: existem dois planos (TP Lite e TP Lite Pro, com preços e redes de academia diferentes — o TP Lite custa R$ 69,90/mês, e dá acesso a mais de 6.000 academias e apps de bem-estar como Zen App, Total Play, Nutri+ e Positiv). A contratação é individual (sem dependentes) e acontece pelo próprio app da TotalPass (cadastro por CPF), não precisa que a empresa ofereça TotalPass corporativo — só precisa ter acesso via um parceiro elegível (Flash, Alelo, Ticket, etc.). Mencione esse SEMPRE PRIMEIRO quando o assunto for TotalPass.
     ATENÇÃO — nunca recomende isso: TP Lite NÃO é uma versão mais barata do plano corporativo, e ninguém que já tem TotalPass corporativo pela empresa deve cancelar pra migrar pro TP Lite — são públicos diferentes, o cadastro corporativo é vinculado ao CPF + CNPJ da empresa parceira. Se alguém com TotalPass corporativo perguntar sobre economizar ou trocar de plano, oriente a verificar categorias mais baratas (TP1 a TP5+) direto com a própria empresa/TotalPass — nunca sugira migrar pro TP Lite nesse caso.
  2) TotalPass corporativo (o plano completo, contratado PELA EMPRESA) — mencione DEPOIS do TP Lite, como um "a mais" pra quem quiser oferecer mais. Isso NÃO é pelo Clube, é direto com o time comercial. É o plano mais robusto: inclui até 3 dependentes por colaborador e rede de academias com maior abrangência que o TP Lite/Pro. Sempre que mencionar essa opção, chame oferecer_cta_comercial (motivo: "TotalPass corporativo") NA MESMA resposta — não espere a pessoa demonstrar interesse primeiro, o botão de CTA é justamente o convite.
  Nunca hesite ou trate como incerto — os dois são fatos confirmados.
- CLUDE SAÚDE: parceria real Flash + Clude, também fora do Mapa de Parceiros do Clube (é assinatura individual, exclusiva pra quem tem cartão Flash, não desconto de marketplace). Seja AFIRMATIVO sobre isso. O que inclui: telemedicina 24h por dia, 7 dias por semana (WhatsApp ou app), pedido de exame e receita direto na consulta por vídeo; consulta com especialista a partir de R$ 45; desconto de até 80% em exames (rede com Sabin, Labi Exames, entre outros); desconto de até 60% em mais de 26.000 farmácias (Drogasil, Droga Raia, Drogaria São Paulo, entre outras); acesso a mais de 50 cirurgias com condições especiais de pagamento e acompanhamento de assistente social; e dois extras — Clude Nutrifit (chat com nutricionista) e Clude Mind (consulta com psicólogo por valor acessível). Tem uma assistente de IA própria (a "Clu") pra acompanhar condição crônica como diabetes e pressão alta.
  Hoje tem uma condição promocional de assinatura (plano individual, valor com desconto) — cite que existe condição especial pro cartão Flash, mas não prometa um valor exato fixo, porque preço promocional pode mudar; se pedirem o valor exato, diga que é melhor confirmar no app, já que é uma promoção por tempo limitado.
  Importante: isso NÃO é seguro nem plano de saúde — é telemedicina e desconto em rede credenciada. Se alguém perguntar se é plano de saúde, corrija com clareza.
  Sempre que mencionar o Clude Saúde como opção real, chame oferecer_cta_comercial (motivo: "Clude Saúde") na mesma resposta.
- OPÇÕES MAIS COMPLETAS DE SAÚDE (via comercial): se o cliente quiser algo mais robusto que o Clude Saúde individual, existem duas frentes — o Clude Corporativo (versão mais completa do Clude, contratada pela empresa, não autoatendimento) e a parceria da Flash com a Conexa (healthtech de telemedicina e saúde integral, com atuação também em saúde mental). As duas são reais e confirmadas, mas NÃO são autoatendimento — seja AFIRMATIVO que existem, e chame oferecer_cta_comercial (motivo: "Clude Corporativo" ou "Conexa", conforme o caso) na mesma resposta em que mencionar a opção.
- PSICOLOGIA / NR-01 (assunto quente, responda com cuidado): ATENÇÃO DE GATILHO — "NR-01", "NR01", "NR 01", "risco psicossocial", "saúde mental", "psicólogo", "terapia" e variações são sobre ESTE bloco, não são nome de parceiro/produto pra procurar na lista de parceiros. Nunca trate "NR01" como um produto desconhecido nem caia no fallback genérico de "não vejo isso aqui, pode ser produto à parte" — isso está errado, a resposta certa é sempre esta: sim, a Flash tem suporte psicológico — é o Clude Mind, dentro do Clude Saúde (consulta por vídeo com psicólogo por valor acessível, chat com equipe de psicólogos seg-sex 8h-20h). Contexto pra usar: a NR-01 foi atualizada e agora exige que toda empresa CLT inclua os riscos psicossociais (estresse, sobrecarga, assédio, etc.) no PGR (Programa de Gerenciamento de Riscos) — a fiscalização com multa já começou em 26/05/2026, não é mais teoria.
  ATENÇÃO — nunca prometa conformidade: oferecer suporte psicológico (Clude Mind) AJUDA a mitigar risco psicossocial, mas NÃO substitui a avaliação formal e documentada do PGR, que exige profissional qualificado mapeando os riscos — isso é um processo à parte, não um benefício de app. Nunca diga "com isso sua empresa fica em conformidade com a NR-01" ou equivalente — isso é uma afirmação legal falsa. Diga algo como "o Clude Mind é uma peça boa da estratégia de bem-estar, mas a NR-01 exige uma avaliação formal de risco à parte — isso complementa, não substitui". Se a empresa quiser algo mais robusto pra encarar a NR-01 de frente, mencione que o Clude Corporativo e a parceria com a Conexa são opções mais completas nessa frente — e chame oferecer_cta_comercial (motivo: "Clude Saúde / NR-01") na mesma resposta.
- QUALQUER OUTRO produto/parceiro que NÃO esteja na lista de parceiros abaixo: aqui sim, sem confirmação você não sabe se existe. Nunca diga "não temos" nem invente que existe — diga algo como "esse especificamente eu não vejo aqui no Clube, mas pode ser um produto à parte da Flash" e chame oferecer_cta_comercial (motivo: nome do produto perguntado) na mesma resposta, pra pessoa poder confirmar com o comercial se quiser.

DESCONTO MÉDIO E PARCEIROS POR CATEGORIA (fatos reais, use com precisão):
{linhas_categorias}

LISTA DE PARCEIROS DO CLUBE (fonte da verdade — só cite nomes que estão aqui):
{lista_parceiros}

Respostas curtas por padrão (2 a 4 frases) — só se estenda se a pessoa pedir mais detalhe."""


def montar_contents_gemini(historico: list) -> list:
    contents = []
    for msg in historico:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})
    return contents


def chamar_gemini_agente(historico: list) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY não configurada")

    contents = montar_contents_gemini(historico)
    payload = {
        "system_instruction": {"parts": [{"text": montar_system_prompt()}]},
        "contents": contents,
        "tools": [{"functionDeclarations": FUNCTION_DECLARATIONS}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 400},
    }

    data = post_gemini(payload).json()
    partes = data["candidates"][0]["content"]["parts"]

    function_call = next((p["functionCall"] for p in partes if "functionCall" in p), None)
    mostrar_formulario = False
    motivo_formulario = None
    mostrar_cta = False
    motivo_cta = None

    if function_call:
        nome_funcao = function_call["name"]
        args = function_call.get("args", {})

        if nome_funcao == "calcular_economia":
            resultado = calcular_economia(
                headcount=int(args.get("headcount", 1)),
                meses=int(args.get("meses", 12)),
            )
        elif nome_funcao == "oferecer_cta_comercial":
            mostrar_cta = True
            motivo_cta = str(args.get("motivo", "Falar com o comercial"))
            resultado = {"cta_exibido": True}
        elif nome_funcao == "oferecer_formulario_contato":
            mostrar_formulario = True
            motivo_formulario = str(args.get("motivo", "Falar com o comercial"))
            resultado = {"formulario_exibido": True}
        else:
            resultado = {"erro": f"função desconhecida: {nome_funcao}"}

        # Segunda chamada: manda o resultado real da função de volta pro modelo
        # formular a resposta em linguagem natural em cima do número correto.
        contents.append({"role": "model", "parts": [{"functionCall": function_call}]})
        contents.append({
            # Modelos mais novos (ex: gemini-3.5-flash-lite) rejeitam role "function"
            # com 400 INVALID_ARGUMENT — a resposta da função vai em "user" agora.
            "role": "user",
            "parts": [{"functionResponse": {"name": nome_funcao, "response": resultado}}],
        })
        payload2 = {
            "system_instruction": {"parts": [{"text": montar_system_prompt()}]},
            "contents": contents,
            "tools": [{"functionDeclarations": FUNCTION_DECLARATIONS}],
            "generationConfig": {"temperature": 0.85, "maxOutputTokens": 400},
        }
        data2 = post_gemini(payload2).json()
        texto = data2["candidates"][0]["content"]["parts"][0]["text"].strip()
        return {
            "texto": texto,
            "mostrar_formulario": mostrar_formulario,
            "motivo": motivo_formulario,
            "mostrar_cta": mostrar_cta,
            "motivo_cta": motivo_cta,
        }

    texto = next((p["text"] for p in partes if "text" in p), None)
    if not texto:
        raise RuntimeError("resposta do Gemini sem texto nem function call")
    return {"texto": texto.strip(), "mostrar_formulario": False, "motivo": None, "mostrar_cta": False, "motivo_cta": None}





SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
LEADS_LOG_PATH = Path(__file__).parent / "data" / "leads_log.jsonl"


def enviar_para_slack(texto: str) -> bool:
    """Posta direto no Incoming Webhook do Slack — recurso nativo do Slack,
    sem n8n nem nenhuma ferramenta terceira no meio (proibido pelo time de
    segurança). Retorna True se enviou, False se falhou ou não configurado."""
    if not SLACK_WEBHOOK_URL:
        return False
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": texto}, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"[ERRO Slack] {type(e).__name__}: {e}", flush=True)
        return False



@app.route("/")
def index():
    return render_template("index.html")


@app.route("/lp")
def landing_page():
    return render_template("lp.html")


@app.route("/api/categorias")
def api_categorias():
    return jsonify(carregar_categorias())


@app.route("/api/gerar-narrativa", methods=["POST"])
@limite_por_ip(max_requisicoes=15, janela_segundos=60)
def api_gerar_narrativa():
    dados = request.get_json(force=True, silent=True) or {}

    campos_obrigatorios = ["headcount", "totalMes", "individualPeriodo", "agregadoPeriodo"]
    faltando = [c for c in campos_obrigatorios if c not in dados]
    if faltando:
        return jsonify({"erro": f"campos faltando: {', '.join(faltando)}"}), 400

    try:
        narrativa = chamar_gemini(dados)
        return jsonify({"narrativa": narrativa, "fonte": "gemini"})
    except Exception as e:
        app.logger.error("Erro ao chamar Gemini (/api/gerar-narrativa): %s", e, exc_info=True)
        print(f"[ERRO /api/gerar-narrativa] {type(e).__name__}: {e}", flush=True)
        # Nunca deixa a calculadora sem narrativa: cai no template determinístico
        narrativa = montar_narrativa_padrao(dados)
        return jsonify({"narrativa": narrativa, "fonte": "template", "aviso": str(e)})


def resposta_rapida(mensagem: str) -> dict | None:
    """Perguntas de altíssima frequência que já têm resposta 100% definida na
    base de conhecimento — respondidas na hora, SEM chamar o Gemini. Isso tira
    essas perguntas da dependência de API externa (rate limit, modelo fora do
    ar, etc.) e resolve exatamente o problema de "isso não devia precisar de
    IA". Qualquer coisa fora desses padrões cai pro Mingo (IA) normal.
    Retorna None se nada bateu, pra seguir o fluxo normal com o Gemini."""
    m = mensagem.lower().strip()

    # Confirmação de CTA (mensagem sempre gerada pelo nosso próprio botão,
    # nunca digitada livre — pode casar por padrão fixo com segurança)
    prefixo_cta = "quero falar com um comercial sobre"
    if m.startswith(prefixo_cta):
        motivo = mensagem[len(prefixo_cta):].strip(" :")  or "Falar com o comercial"
        texto = f"Show! Deixa seus dados aqui embaixo que o comercial entra em contato sobre {motivo}."
        return {"texto": texto, "mostrar_formulario": True, "motivo": motivo, "mostrar_cta": False, "motivo_cta": None}

    # Produtos especiais (TotalPass, NR-01, Clude Saúde, etc.) — vem da aba
    # "Produtos" da planilha do time de parcerias, editável sem deploy.
    for produto in buscar_produtos_especiais():
        gatilhos = [g.strip() for g in produto["gatilhos"].split(",") if g.strip()]
        if any(g in m for g in gatilhos):
            return {
                "texto": produto["resposta"],
                "mostrar_formulario": False,
                "motivo": None,
                "mostrar_cta": bool(produto.get("motivo_cta")),
                "motivo_cta": produto.get("motivo_cta"),
            }

    # Total de parceiros do Clube
    if re.search(r'quant[oa]s?\s+parceir', m):
        total = sum(c["parceiros"] for c in carregar_categorias())
        texto = f"O Clube Flash tem {total} parceiros ativos agora, espalhados por 9 categorias — de alimentação e mobilidade a educação e bem-estar."
        return {"texto": texto, "mostrar_formulario": False, "motivo": None, "mostrar_cta": False, "motivo_cta": None}

    # Cálculo de economia por número de colaboradores (só se não caiu em nenhum
    # produto específico acima — "colaboradores" é palavra genérica demais
    # pra checar primeiro)
    match_headcount = re.search(r'(\d{1,6})\s*colaborador', m)
    if match_headcount and any(p in m for p in ["econom", "quanto"]):
        headcount = int(match_headcount.group(1))
        meses_match = re.search(r'(\d{1,2})\s*mes', m)
        meses = int(meses_match.group(1)) if meses_match else 12
        r = calcular_economia(headcount=headcount, meses=meses)
        texto = (
            f"Com {headcount} colaboradores, em {meses} meses a economia agregada da "
            f"empresa fica em torno de {formatar_brl(r['economia_agregada_da_empresa_no_periodo'])}, "
            f"considerando {formatar_brl(r['economia_individual_no_periodo'])} por colaborador no "
            f"período. A categoria que mais pesa nisso é {r['categoria_com_maior_economia']}."
        )
        return {"texto": texto, "mostrar_formulario": False, "motivo": None, "mostrar_cta": False, "motivo_cta": None}

    return None


@app.route("/agente")
def agente():
    return render_template("agente.html")


@app.route("/api/agente", methods=["POST"])
@limite_por_ip(max_requisicoes=15, janela_segundos=60)
def api_agente():
    dados = request.get_json(force=True, silent=True) or {}
    historico = dados.get("historico", [])

    if not historico:
        return jsonify({"erro": "histórico vazio"}), 400

    ultima_mensagem = historico[-1]
    if ultima_mensagem.get("role") == "user":
        rapida = resposta_rapida(ultima_mensagem.get("text", ""))
        if rapida:
            return jsonify({
                "resposta": rapida["texto"],
                "fonte": "base_conhecimento",
                "mostrar_formulario": rapida["mostrar_formulario"],
                "motivo_formulario": rapida["motivo"],
                "mostrar_cta": rapida["mostrar_cta"],
                "motivo_cta": rapida["motivo_cta"],
            })

    try:
        resultado = chamar_gemini_agente(historico)
        return jsonify({
            "resposta": resultado["texto"],
            "fonte": "gemini",
            "mostrar_formulario": resultado["mostrar_formulario"],
            "motivo_formulario": resultado["motivo"],
            "mostrar_cta": resultado["mostrar_cta"],
            "motivo_cta": resultado["motivo_cta"],
        })
    except RateLimitError as e:
        # Não é falha de verdade: só cota cheia em todos os modelos. Devolve um
        # sinal estruturado pro front-end esperar e tentar de novo sozinho.
        print(f"[RATE LIMIT /api/agente] todos os modelos cheios; sugerir espera de {e.retry_after}s", flush=True)
        return jsonify({
            "fonte": "rate_limit",
            "retry_after": e.retry_after,
            "resposta": "Tá bombando por aqui, já te respondo...",
        }), 200
    except Exception as e:
        app.logger.error("Erro ao chamar Gemini (/api/agente): %s", e, exc_info=True)
        print(f"[ERRO /api/agente] {type(e).__name__}: {e}", flush=True)
        return jsonify({
            "resposta": (
                "Não consegui falar com a IA agora. Você pode tentar de novo em alguns "
                "segundos, ou usar a calculadora principal em / enquanto isso."
            ),
            "fonte": "erro",
            "aviso": str(e),
        }), 200


@app.route("/api/lead", methods=["POST"])
@limite_por_ip(max_requisicoes=6, janela_segundos=60)
def api_lead():
    dados = request.get_json(force=True, silent=True) or {}

    obrigatorios = ["nome", "email", "empresa"]
    faltando = [c for c in obrigatorios if not dados.get(c)]
    if faltando:
        return jsonify({"erro": f"campos faltando: {', '.join(faltando)}"}), 400

    dados["origem"] = "lp_render"

    # Salva localmente como rede de segurança extra. IMPORTANTE: no Render,
    # o disco não é persistente entre deploys/restarts — isto não substitui
    # o n8n (que já grava no Slack e no Sheets), é só um log auxiliar.
    try:
        with open(LEADS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(dados, ensure_ascii=False) + "\n")
    except Exception:
        pass

    texto_slack = (
        f":inbox_tray: *Novo lead via LP*\n"
        f"*Nome:* {dados.get('nome', '')}\n"
        f"*E-mail:* {dados.get('email', '')}\n"
        f"*Empresa:* {dados.get('empresa', '')}\n"
        f"*Cargo:* {dados.get('cargo') or 'não informado'}\n"
        f"*Colaboradores:* {dados.get('headcount') or 'não informado'}"
    )
    enviado = enviar_para_slack(texto_slack)

    return jsonify({"ok": True, "enviado_slack": enviado})


@app.route("/api/lead-comercial", methods=["POST"])
@limite_por_ip(max_requisicoes=6, janela_segundos=60)
def api_lead_comercial():
    """Recebe o formulário mostrado dentro do chat do Mingo (quando o usuário
    topa falar com o comercial) e manda direto pro Slack via Incoming Webhook
    — sem n8n, conforme a política de segurança."""
    dados = request.get_json(force=True, silent=True) or {}

    obrigatorios = ["nome", "email"]
    faltando = [c for c in obrigatorios if not dados.get(c)]
    if faltando:
        return jsonify({"erro": f"campos faltando: {', '.join(faltando)}"}), 400

    nome = dados.get("nome", "")
    email = dados.get("email", "")
    empresa = dados.get("empresa") or "não informado"
    telefone = dados.get("telefone") or "não informado"
    colaboradores = dados.get("colaboradores") or "não informado"
    motivo = dados.get("motivo") or "Contato via Mingo"

    dados["origem"] = "agente_mingo"
    try:
        with open(LEADS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(dados, ensure_ascii=False) + "\n")
    except Exception:
        pass

    texto_slack = (
        f":robot_face: *Novo contato via Mingo (agente)*\n"
        f"*Motivo:* {motivo}\n"
        f"*Nome:* {nome}\n"
        f"*E-mail:* {email}\n"
        f"*Telefone:* {telefone}\n"
        f"*Empresa:* {empresa}\n"
        f"*Colaboradores:* {colaboradores}"
    )
    enviado = enviar_para_slack(texto_slack)

    return jsonify({"ok": True, "enviado_slack": enviado})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
