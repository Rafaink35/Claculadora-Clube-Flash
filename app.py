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
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data" / "categorias.json"
PARCEIROS_PATH = Path(__file__).parent / "data" / "parceiros.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


def carregar_categorias():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


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
    resp = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f"Gemini retornou {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    texto = data["candidates"][0]["content"]["parts"][0]["text"]
    return texto.strip()


def carregar_parceiros():
    with open(PARCEIROS_PATH, encoding="utf-8") as f:
        return json.load(f)


def listar_parceiros(categoria: str, limite: int = 8) -> dict:
    """Busca parceiros reais por categoria — o Mingo chama isto em vez de
    inventar nome de parceiro ou recusar responder."""
    todos = carregar_parceiros()
    categoria_norm = categoria.strip().lower()
    encontrados = [p for p in todos if p["categoria"].strip().lower() == categoria_norm]

    if not encontrados:
        categorias_disponiveis = sorted(set(p["categoria"] for p in todos))
        return {
            "erro": f"categoria '{categoria}' não encontrada",
            "categorias_disponiveis": categorias_disponiveis,
        }

    return {
        "categoria": categoria,
        "total_parceiros_na_categoria": len(encontrados),
        "parceiros": [p["nome"] for p in encontrados[:limite]],
        "mostrando": min(limite, len(encontrados)),
    }


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
    "name": "listar_parceiros",
    "description": (
        "Busca os nomes reais de parceiros ativos do Clube Flash numa categoria "
        "específica (Conveniência, Refeição, Bem-estar, Mobilidade, Educação, "
        "Saúde, Cultura, Alimentação ou Pets). Chame esta função SEMPRE que o "
        "usuário pedir nomes de parceiros, exemplos concretos, ou perguntar "
        "'quais parceiros' — nunca invente nome de parceiro nem diga apenas "
        "que 'tem muitos parceiros bacanas' sem checar."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "categoria": {
                "type": "STRING",
                "description": "Nome exato da categoria, como aparece na lista de categorias do sistema.",
            },
            "limite": {
                "type": "INTEGER",
                "description": "Quantos nomes retornar, no máximo. Use 8 se o usuário não especificar.",
            },
        },
        "required": ["categoria"],
    },
}]


def montar_system_prompt() -> str:
    categorias = carregar_categorias()
    total_parceiros = sum(c["parceiros"] for c in categorias)
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
   → Não minta nem minimize: o iFood tem escala e caixa que permitem esse tipo de subsídio pontual. Mas devolva o jogo pra sortimento e consistência: o Clube Flash cobre o dia a dia inteiro (alimentação, mobilidade, saúde, educação, bem-estar) com desconto real documentado, não é dependente de um único parceiro chamativo. Argumente algo como "o iFood brilha num benefício isolado, mas o Clube Flash entrega valor todo santo dia" — sempre em português simples, sem jargão de startup (nada de "early", "growth", "player" e afins).

COMO VOCÊ CONVERSA:
- Fale como alguém defendendo algo que acredita, não como um catálogo de FAQ. Entusiasmo real, sem exagero de propaganda vazia.
- Reaja ao que a pessoa disse antes de argumentar de volta — mas sem elogiar a pergunta dela primeiro.
- Frases curtas, linguagem natural, contrações do dia a dia ("tá", "pra", "dá pra").
- NUNCA use markdown — sem **negrito**, sem listas com hífen ou asterisco, sem títulos. Apenas texto corrido, porque a tela do chat não interpreta formatação e os símbolos apareceriam literalmente.
- Use vírgula para casas decimais, nunca ponto (ex: "39,0%", não "39.0%") — você está falando português do Brasil.

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
- Sempre que alguém pedir nomes de parceiros, exemplos concretos, ou perguntar "quais parceiros", chame a função listar_parceiros com a categoria certa. Nunca diga só "temos parceiros bacanas" sem checar — isso soa vazio. Se listar_parceiros não achar a categoria, peça pra pessoa escolher entre as categorias disponíveis que a função retornar.

LIMITE DA DEFESA — honestidade não é negociável:
- Defender o clube não significa esconder falha real. Se perguntarem especificamente sobre Educação (sem uso real desde 2023), seja transparente — reconheça o ponto e redirecione pro que É forte (as outras categorias, o compromisso de melhorar aquela específica).
- Sobre Mobilidade: seja direto se perguntado — hoje 100% do uso real da categoria vem de recarga de Bilhete Único (SPTrans) e crédito de Uber/Uber Cards, que não têm desconto percentual documentado. Isso já está refletido no cálculo (o desconto de Mobilidade é 0% no sistema, não inventado pra parecer melhor). Redirecione pro ponto forte real: as outras 8 categorias têm desconto documentado e mensurável.
- Argumentar bem inclui saber admitir o que ainda não está perfeito — isso é o que faz a defesa parecer confiável, não propaganda vazia.
- Se perguntarem diretamente se você é uma IA, responda honestamente que sim — você é o Mingo em versão IA, não uma pessoa.

CUIDADO CRÍTICO — o Mapa de Parceiros NÃO é o catálogo completo da Flash:
- A função listar_parceiros só enxerga os parceiros do Clube B2C. A Flash tem OUTROS produtos e benefícios negociados separadamente com a empresa cliente, fora do Clube.
- TOTALPASS: a Flash TEM TotalPass, com condições boas pra empresa — mas não é contratado pelo Clube, é direto com o time comercial. Se perguntarem sobre TotalPass, seja AFIRMATIVO: "Sim, a Flash tem TotalPass! Não é pelo Clube, é contratado direto com o nosso time comercial — fala com eles que te passam as condições." Nunca hesite ou trate como incerto — isso é fato confirmado.
- QUALQUER OUTRO produto/parceiro que listar_parceiros não encontrar: aqui sim, sem confirmação você não sabe se existe. Nunca diga "não temos" nem invente que existe — diga algo como "esse especificamente eu não vejo aqui no Clube, mas pode ser um produto à parte da Flash — vale confirmar com o nosso comercial" e direcione pro time comercial.

DESCONTO MÉDIO E PARCEIROS POR CATEGORIA (fatos reais, use com precisão):
{linhas_categorias}

Respostas curtas por padrão (2 a 4 frases) — só se estenda se a pessoa pedir mais detalhe."""


def montar_contents_gemini(historico: list) -> list:
    contents = []
    for msg in historico:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})
    return contents


def chamar_gemini_agente(historico: list) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY não configurada")

    contents = montar_contents_gemini(historico)
    payload = {
        "system_instruction": {"parts": [{"text": montar_system_prompt()}]},
        "contents": contents,
        "tools": [{"functionDeclarations": FUNCTION_DECLARATIONS}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 400},
    }

    resp = requests.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload, timeout=20)
    if not resp.ok:
        raise RuntimeError(f"Gemini retornou {resp.status_code} na 1a chamada: {resp.text[:500]}")
    data = resp.json()
    partes = data["candidates"][0]["content"]["parts"]

    function_call = next((p["functionCall"] for p in partes if "functionCall" in p), None)

    if function_call:
        nome_funcao = function_call["name"]
        args = function_call.get("args", {})

        if nome_funcao == "calcular_economia":
            resultado = calcular_economia(
                headcount=int(args.get("headcount", 1)),
                meses=int(args.get("meses", 12)),
            )
        elif nome_funcao == "listar_parceiros":
            resultado = listar_parceiros(
                categoria=str(args.get("categoria", "")),
                limite=int(args.get("limite", 8)),
            )
        else:
            resultado = {"erro": f"função desconhecida: {nome_funcao}"}

        # Segunda chamada: manda o resultado real da função de volta pro modelo
        # formular a resposta em linguagem natural em cima do número correto.
        contents.append({"role": "model", "parts": [{"functionCall": function_call}]})
        contents.append({
            "role": "function",
            "parts": [{"functionResponse": {"name": nome_funcao, "response": resultado}}],
        })
        payload2 = {
            "system_instruction": {"parts": [{"text": montar_system_prompt()}]},
            "contents": contents,
            "tools": [{"functionDeclarations": FUNCTION_DECLARATIONS}],
            "generationConfig": {"temperature": 0.85, "maxOutputTokens": 400},
        }
        resp2 = requests.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload2, timeout=20)
        if not resp2.ok:
            raise RuntimeError(f"Gemini retornou {resp2.status_code} na 2a chamada: {resp2.text[:500]}")
        data2 = resp2.json()
        return data2["candidates"][0]["content"]["parts"][0]["text"].strip()

    texto = next((p["text"] for p in partes if "text" in p), None)
    if not texto:
        raise RuntimeError("resposta do Gemini sem texto nem function call")
    return texto.strip()





N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL")
LEADS_LOG_PATH = Path(__file__).parent / "data" / "leads_log.jsonl"


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


@app.route("/agente")
def agente():
    return render_template("agente.html")


@app.route("/api/agente", methods=["POST"])
def api_agente():
    dados = request.get_json(force=True, silent=True) or {}
    historico = dados.get("historico", [])

    if not historico:
        return jsonify({"erro": "histórico vazio"}), 400

    try:
        resposta = chamar_gemini_agente(historico)
        return jsonify({"resposta": resposta, "fonte": "gemini"})
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

    enviado_n8n = False
    erro_n8n = None
    if N8N_WEBHOOK_URL:
        try:
            resp = requests.post(N8N_WEBHOOK_URL, json=dados, timeout=10)
            resp.raise_for_status()
            enviado_n8n = True
        except Exception as e:
            erro_n8n = str(e)

    return jsonify({"ok": True, "enviado_n8n": enviado_n8n, "erro_n8n": erro_n8n})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
