"""
Preditor de Deformação Permanente de Solos
DNIT 179/2018-IE | Random Forest + Modelo de Guimarães (2009)
"""

import base64
import io
import json
import os
from datetime import datetime

import numpy as np
from flask import Flask, jsonify, render_template, request, send_file
from fpdf import FPDF
import openpyxl
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from scipy.optimize import curve_fit

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


# ── Modelo ───────────────────────────────────────────────────────────────────
def _carregar_modelo():
    """Carrega o modelo comprimido (joblib). Se não existir, usa o .pkl antigo."""
    caminho_joblib = os.path.join(DATA_DIR, "model_rf.joblib")
    if os.path.exists(caminho_joblib):
        import joblib
        return joblib.load(caminho_joblib)
    import pickle
    with open(os.path.join(DATA_DIR, "model_rf.pkl"), "rb") as f:
        return pickle.load(f)


MODEL = _carregar_modelo()

with open(os.path.join(DATA_DIR, "app_data.json"), "r", encoding="utf-8") as f:
    DB = json.load(f)
REAIS = set(DB.get("lookup_reais", []))


# ── Constantes ───────────────────────────────────────────────────────────────
P0_ATM = 101.325
CICLOS = [1, 10, 50, 100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 150000]
CL_LABELS = ["1", "10", "50", "100", "500", "1k", "2k", "5k", "10k", "20k", "50k", "100k", "150k"]
IDX = {n: i for i, n in enumerate(CICLOS)}

DNIT_TABELA2 = {
    40:  [{"sd": 40, "razao": "2,0"}, {"sd": 80, "razao": "3,0"}, {"sd": 120, "razao": "4,0"}],
    80:  [{"sd": 80, "razao": "2,0"}, {"sd": 160, "razao": "3,0"}, {"sd": 240, "razao": "4,0"}],
    120: [{"sd": 120, "razao": "2,0"}, {"sd": 240, "razao": "3,0"}, {"sd": 360, "razao": "4,0"}],
}
PARES_T2 = [(s3, p["sd"]) for s3, pares in DNIT_TABELA2.items() for p in pares]

RANGES = {
    "hot":  {"min": 8.0,  "max": 21.0,  "unit": "%",     "label": "Umidade Ótima (Wot)"},
    "gd":   {"min": 1.63, "max": 2.11,  "unit": "g/cm³", "label": "γd máx"},
    "p10":  {"min": 21.0, "max": 100.0, "unit": "%",     "label": "Passante #10"},
    "p40":  {"min": 16.0, "max": 100.0, "unit": "%",     "label": "Passante #40"},
    "p200": {"min": 4.31, "max": 98.0,  "unit": "%",     "label": "Passante #200"},
    "cbr":  {"min": 2.0,  "max": 34.0,  "unit": "%",     "label": "CBR"},
}
SOLO_KEYS = ["hot", "gd", "p10", "p40", "p200", "cbr"]

# Limites de distância (propriedades normalizadas pela faixa de treino) para
# avisar quando o solo informado é diferente dos 15 solos do banco.
DIST_PARECIDO = 0.30
DIST_MODERADO = 0.60

# Limites do critério indicativo de comportamento (definidos neste app, NÃO
# constam da DNIT 179/2018-IE, que descreve os tipos de forma qualitativa).
TIPO_LIMITES = {"ep1": 0.5, "taxa1": 1.5e-5, "ep2": 1.5, "taxa2": 6.0e-5, "ep3": 3.5}


# ── Funções de cálculo ───────────────────────────────────────────────────────
def guimaraes_model(X_inp, psi1, psi2, psi3, psi4):
    s3, sd, N = X_inp
    return psi1 * (s3 / P0_ATM) ** psi2 * (sd / P0_ATM) ** psi3 * N ** psi4


def _linhas(s3_kpa, sd_kpa, solo):
    """Monta as linhas de entrada do RF (mesma ordem de features do treino)."""
    s3 = s3_kpa / 1000.0
    sd = sd_kpa / 1000.0
    return [[np.log10(c), s3, sd, sd / s3, sd + s3,
             solo["hot"], solo["gd"], solo["p10"], solo["p40"], solo["p200"], solo["cbr"]]
            for c in CICLOS]


def _monotonica(curva):
    """εp acumulada não pode diminuir com N: aplica máximo acumulado."""
    return np.maximum.accumulate(np.maximum(np.asarray(curva, dtype=float), 0.0))


def prever_pares(solo, pares):
    """Prevê as curvas de vários pares de tensão numa chamada só."""
    X = np.array([linha for s3, sd in pares for linha in _linhas(s3, sd, solo)])
    preds = MODEL.predict(X).reshape(len(pares), len(CICLOS))
    return [_monotonica(p) for p in preds]


def faixa_arvores(solo, s3, sd):
    """Dispersão entre as árvores do RF (P10–P90) para o par escolhido."""
    if not hasattr(MODEL, "estimators_"):
        return None, None
    X = np.array(_linhas(s3, sd, solo))
    todas = np.stack([arv.predict(X) for arv in MODEL.estimators_])
    todas = np.array([_monotonica(c) for c in todas])
    return np.percentile(todas, 10, axis=0), np.percentile(todas, 90, axis=0)


def ajustar_guimaraes(curvas, pares):
    """Regressão não linear múltipla com os 9 pares da Tabela 2 (DNIT 179, item 10.1).

    O ajuste é feito em log(εp): assim os pares de tensão baixa (εp pequeno) pesam
    tanto quanto os de tensão alta. Em escala linear os pares mais carregados
    dominam o ajuste e a curva fica ruim para os demais.
    Retorna os parâmetros, o R² (escala linear, todos os pontos) e o erro
    relativo médio por ponto.
    """
    s3_arr, sd_arr, n_arr, y = [], [], [], []
    for (s3, sd), curva in zip(pares, curvas):
        for n, v in zip(CICLOS, curva):
            if v > 0:
                s3_arr.append(float(s3))
                sd_arr.append(float(sd))
                n_arr.append(float(n))
                y.append(float(v))
    X = (np.array(s3_arr), np.array(sd_arr), np.array(n_arr))
    y = np.array(y)

    def _log_modelo(X_inp, psi1, psi2, psi3, psi4):
        return np.log(guimaraes_model(X_inp, psi1, psi2, psi3, psi4))

    try:
        popt, _ = curve_fit(_log_modelo, X, np.log(y), p0=[0.1, 0.5, 1.0, 0.1],
                            bounds=([1e-6, -3, 0, 0], [100, 3, 5, 1]), maxfev=20000)
        fit = guimaraes_model(X, *popt)
        ss_res = np.sum((y - fit) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        erro_rel = float(np.mean(np.abs(fit - y) / y))
        return [round(float(p), 4) for p in popt], round(float(r2), 4), round(erro_rel, 4)
    except Exception:
        return None, None, None


def ep_em_n(curva, nc):
    """εp num N qualquer, interpolando em log(N)."""
    if nc in IDX:
        return float(curva[IDX[nc]])
    logs = np.log10(CICLOS)
    return float(np.interp(np.log10(max(nc, 1)), logs, curva))


def dados_shakedown(curva):
    """Pontos do gráfico de acomodamento: εp acumulada × taxa de acréscimo por ciclo."""
    pontos = []
    for i in range(1, len(CICLOS)):
        dn = CICLOS[i] - CICLOS[i - 1]
        taxa = (curva[i] - curva[i - 1]) / dn
        pontos.append({"ep": round(float(curva[i]), 5),
                       "taxa": float(taxa) if taxa > 0 else None,
                       "n": CICLOS[i]})
    return pontos


def classificar(curva):
    """Critério indicativo do app (não normativo) para os tipos I a IV."""
    ep150 = curva[-1]
    taxa = (curva[-1] - curva[IDX[10000]]) / (150000 - 10000)
    L = TIPO_LIMITES
    if ep150 < L["ep1"] and taxa < L["taxa1"]:
        tipo = 1
    elif ep150 < L["ep2"] and taxa < L["taxa2"]:
        tipo = 2
    elif ep150 < L["ep3"]:
        tipo = 3
    else:
        tipo = 4
    return tipo, float(taxa)


def solo_mais_parecido(solo, s3, sd):
    """Compara com os 15 solos do banco (distância normalizada pela faixa de treino)."""
    vet = np.array([solo[k] for k in SOLO_KEYS])
    faixa = np.array([RANGES[k]["max"] - RANGES[k]["min"] for k in SOLO_KEYS])
    melhor, dist_min = None, np.inf
    for nome, props in DB["solos"].items():
        ref = np.array([props[k] for k in SOLO_KEYS])
        d = float(np.sqrt(np.sum(((vet - ref) / faixa) ** 2)))
        if d < dist_min:
            melhor, dist_min = nome, d
    if dist_min <= DIST_PARECIDO:
        nivel = "parecido"
    elif dist_min <= DIST_MODERADO:
        nivel = "moderado"
    else:
        nivel = "distante"
    # Só mostra a curva se ela for de um ensaio real (o "lookup" também tem curvas
    # que não foram ensaiadas; a lista de ensaios reais veio da planilha de dados brutos).
    chave = f"{melhor}|{s3}|{sd}"
    curva_lab = DB["lookup"].get(chave) if chave in REAIS else None
    return {"nome": melhor, "dist": round(dist_min, 3), "nivel": nivel,
            "aashto": DB.get("aashto", {}).get(melhor),
            "props": DB["solos"][melhor], "curva_lab": curva_lab}


# ── Rotas ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", ranges=RANGES, dnit_tabela2=DNIT_TABELA2)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/tensoes/<int:s3>")
def get_tensoes(s3):
    pares = DNIT_TABELA2.get(s3)
    if not pares:
        return jsonify({"error": "σ₃ inválido. Use 40, 80 ou 120 kPa."}), 400
    return jsonify(pares)


@app.route("/api/calcular", methods=["POST"])
def calcular():
    data = request.get_json(silent=True) or {}
    try:
        solo = {k: float(data[k]) for k in SOLO_KEYS}
        s3 = int(data["s3"])
        sd = int(data["sd"])
        nc = int(data.get("nc", 150000))
        nome = str(data.get("nome", "Amostra")).strip() or "Amostra"
        h_cm = data.get("h_cm")
        h_cm = float(h_cm) if h_cm not in (None, "") else None
    except (KeyError, ValueError, TypeError) as e:
        return jsonify({"error": f"Parâmetro inválido: {e}"}), 400

    if (s3, sd) not in PARES_T2:
        return jsonify({"error": "Par de tensões fora da Tabela 2 da DNIT 179/2018-IE."}), 400
    if not 1 <= nc <= 150000:
        return jsonify({"error": "N deve estar entre 1 e 150.000 ciclos."}), 400
    if h_cm is not None and not 0 < h_cm <= 200:
        return jsonify({"error": "Espessura da camada deve estar entre 0 e 200 cm."}), 400

    erros = []
    for k in SOLO_KEYS:
        r = RANGES[k]
        if not r["min"] <= solo[k] <= r["max"]:
            erros.append(f"{r['label']} ({r['min']}–{r['max']} {r['unit']})")
    if erros:
        return jsonify({"error": "Valores fora do intervalo de treino: " + ", ".join(erros)}), 422

    avisos = []
    if not solo["p200"] <= solo["p40"] <= solo["p10"]:
        avisos.append("Granulometria incoerente: o esperado é #200 ≤ #40 ≤ #10.")

    # 9 pares da Tabela 2 (o par escolhido está entre eles)
    curvas9 = prever_pares(solo, PARES_T2)
    curva = curvas9[PARES_T2.index((s3, sd))]
    p10, p90 = faixa_arvores(solo, s3, sd)

    guim, guim_r2, guim_erro = ajustar_guimaraes(curvas9, PARES_T2)
    guim_curva = None
    if guim:
        guim_curva = [round(float(guimaraes_model((s3, sd, n), *guim)), 4) for n in CICLOS]

    tipo, taxa_final = classificar(curva)
    ref = solo_mais_parecido(solo, s3, sd)
    if ref["nivel"] == "distante":
        avisos.append(f"O solo informado é bem diferente dos 15 solos do banco "
                      f"(mais parecido: {ref['nome']}). Use o resultado com cautela.")

    dp_n = ep_em_n(curva, nc)
    atr = None
    if h_cm:
        atr = {"h_cm": h_cm, "delta_mm": round(dp_n / 100.0 * h_cm * 10.0, 3)}

    return jsonify({
        "curva": np.round(curva, 4).tolist(),
        "banda_p10": np.round(p10, 4).tolist() if p10 is not None else None,
        "banda_p90": np.round(p90, 4).tolist() if p90 is not None else None,
        "ciclos": CICLOS,
        "labels": CL_LABELS,
        "dp_n": round(dp_n, 4),
        "dp_10k": round(float(curva[IDX[10000]]), 4),
        "dp_50k": round(float(curva[IDX[50000]]), 4),
        "dp_100k": round(float(curva[IDX[100000]]), 4),
        "dp_150k": round(float(curva[-1]), 4),
        "tipo": tipo,
        "taxa_final": taxa_final,
        "shakedown": dados_shakedown(curva),
        "guimaraes": guim,
        "guim_r2": guim_r2,
        "guim_erro": guim_erro,
        "guim_curva": guim_curva,
        "pares9": [{"s3": a, "sd": b, "curva": np.round(c, 4).tolist()}
                   for (a, b), c in zip(PARES_T2, curvas9)],
        "solo_ref": ref,
        "atr": atr,
        "avisos": avisos,
        "nome": nome,
        "inputs": {**solo, "s3": s3, "sd": sd, "nc": nc,
                   "razao": round((s3 + sd) / s3, 1)},
    })


# ── Exportação ───────────────────────────────────────────────────────────────
TIPOS_NOME_ASCII = {
    1: "Tipo I - Acomodamento plastico (rapido)",
    2: "Tipo II - Acomodamento plastico (tardio)",
    3: "Tipo III - Sem acomodamento",
    4: "Tipo IV - Colapso incremental",
}
TIPOS_NOME = {
    1: "Tipo I — Acomodamento plástico (rápido)",
    2: "Tipo II — Acomodamento plástico (tardio)",
    3: "Tipo III — Sem acomodamento",
    4: "Tipo IV — Colapso incremental",
}
DIAG_LABELS = {
    1: ("Indicado para base", "Indicado para sub-base", "Indicado para subleito"),
    2: ("Indicado com controle tecnico", "Indicado para sub-base", "Indicado para subleito"),
    3: ("Nao indicado para base", "Com restricoes - requer estudo", "Indicado para subleito"),
    4: ("Nao indicado", "Nao indicado", "Usar somente com reforco"),
}


def _ascii(txt):
    """Helvetica do fpdf não aceita acentos/símbolos gregos."""
    import unicodedata
    txt = str(txt).replace("—", "-").replace("–", "-").replace("≤", "<=")
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")


def _nome_arquivo(nome):
    seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in _ascii(nome))
    return seguro.strip("_") or "Amostra"


@app.route("/api/exportar/pdf", methods=["POST"])
def exportar_pdf():
    data = request.get_json(silent=True) or {}
    inp = data.get("inputs", {})
    dp_n = data.get("dp_n", 0)
    tipo = data.get("tipo", 0)
    guim = data.get("guimaraes") or []
    guim_r2 = data.get("guim_r2")
    nome = data.get("nome", "Amostra")
    chart_b64 = data.get("chart_img", "")
    ref = data.get("solo_ref") or {}
    atr = data.get("atr")
    avisos = data.get("avisos") or []

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def _hdr(cells, widths):
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("Helvetica", "B", 9)
        for txt, w in zip(cells, widths):
            pdf.cell(w, 7, _ascii(txt), border=1, align="C", fill=True)
        pdf.ln()

    def _row(cells, widths):
        pdf.set_font("Helvetica", "", 9)
        for txt, w in zip(cells, widths):
            pdf.cell(w, 6, _ascii(txt), border=1, align="C")
        pdf.ln()

    def _section(title):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, _ascii(title), ln=True)

    def _texto(txt, size=9, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _ascii(txt), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Preditor de Deformacao Permanente - DNIT 179/2018-IE", ln=True)
    _texto("Random Forest | 9.024 leituras de ensaios triaxiais | 15 solos do Ceara")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _ascii(f"Amostra: {nome}"), ln=True)
    nc_fmt = f"{inp.get('nc', 0):,}".replace(",", ".")
    _texto(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | "
           f"s3 = {inp.get('s3')} kPa | sd = {inp.get('sd')} kPa | "
           f"s1/s3 = {inp.get('razao')} | N ref. = {nc_fmt}")

    _section(f"Deformacao permanente especifica prevista (ep) a {nc_fmt} ciclos")
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, f"{dp_n:.3f} %", ln=True)

    _section("Metricas de deformacao permanente")
    w4 = [47, 47, 47, 47]
    _hdr(["N = 10.000", "N = 50.000", "N = 100.000", "N = 150.000"], w4)
    _row([f"{data.get(k, 0):.3f}%" for k in ("dp_10k", "dp_50k", "dp_100k", "dp_150k")], w4)

    if atr:
        _section("Contribuicao estimada da camada para o afundamento")
        _texto(f"Espessura h = {atr['h_cm']} cm  ->  delta = ep x h = {atr['delta_mm']} mm "
               f"(estimativa simplificada com o par de tensoes do ensaio)")

    if chart_b64:
        try:
            img = io.BytesIO(base64.b64decode(chart_b64.split(",")[-1]))
            _section("Curva ep x numero de ciclos")
            pdf.image(img, x=10, w=188, h=80)
        except Exception:
            pass

    _section("Comportamento (criterio indicativo do app)")
    _texto(TIPOS_NOME_ASCII.get(tipo, "-"), 10, "B")
    _texto("Os tipos I a IV estao descritos no item 10.2 da DNIT 179/2018-IE de forma "
           "qualitativa. Os limites numericos usados aqui sao do app e nao constam da norma.", 8)

    _section("Diagnostico indicativo - uso em pavimento")
    for camada, txt in zip(["Base", "Sub-base", "Subleito"], DIAG_LABELS.get(tipo, ("-",) * 3)):
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(28, 6, camada, border=1)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(160, 6, txt, border=1, ln=True)

    if guim:
        _section("Modelo de Guimaraes (2009): ep = psi1*(s3/p0)^psi2*(sd/p0)^psi3*N^psi4")
        _texto("Parametros obtidos por regressao nao linear multipla (em log) com as curvas "
               "previstas para os 9 pares de tensao da Tabela 2 (DNIT 179/2018-IE, item 10.1).", 8)
        _hdr(["psi1", "psi2", "psi3", "psi4"], w4)
        _row([str(v) for v in guim], w4)
        if guim_r2 is not None:
            erro = data.get("guim_erro")
            extra = f" | erro relativo medio: {erro * 100:.1f}%" if erro is not None else ""
            _texto(f"R2 do ajuste (9 pares): {guim_r2}{extra}", 8)

    if ref:
        _section("Solo do banco mais parecido")
        _texto(f"{ref.get('nome')} ({ref.get('aashto') or '-'}) | distancia normalizada "
               f"{ref.get('dist')} ({ref.get('nivel')})")

    _section("Parametros do solo inseridos")
    params = [("Wot (%)", "hot"), ("gd max (g/cm3)", "gd"), ("Pass. #10 (%)", "p10"),
              ("Pass. #40 (%)", "p40"), ("Pass. #200 (%)", "p200"), ("CBR (%)", "cbr")]
    _hdr([p[0] for p in params], [31] * 6)
    _row([inp.get(p[1]) for p in params], [31] * 6)

    if avisos:
        _section("Avisos")
        for a in avisos:
            _texto(f"- {a}", 8)

    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 4, "DNIT 179/2018-IE (com Errata 1, 2023) | Guimaraes (2009) COPPE/UFRJ. "
                         "Previsao por aprendizado de maquina: nao substitui o ensaio triaxial.")

    buf = io.BytesIO(bytes(pdf.output()))
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"DP_{_nome_arquivo(nome)}.pdf")


@app.route("/api/exportar/xlsx", methods=["POST"])
def exportar_xlsx():
    data = request.get_json(silent=True) or {}
    inp = data.get("inputs", {})
    curva = data.get("curva", [])
    ciclos = data.get("ciclos", CICLOS)
    p10 = data.get("banda_p10") or []
    p90 = data.get("banda_p90") or []
    guim = data.get("guimaraes") or []
    guim_r2 = data.get("guim_r2")
    nome = data.get("nome", "Amostra")
    tipo = data.get("tipo", 0)
    pares9 = data.get("pares9") or []
    ref = data.get("solo_ref") or {}
    atr = data.get("atr")

    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")
    thin = Border(*(Side(style="thin"),) * 4)
    cinza = PatternFill("solid", fgColor="E6E6E6")

    def hdr(ws, r, c, v):
        cell = ws.cell(row=r, column=c, value=v)
        cell.font, cell.fill, cell.alignment, cell.border = bold, cinza, center, thin

    def val(ws, r, c, v):
        cell = ws.cell(row=r, column=c, value=v)
        cell.alignment, cell.border = center, thin

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws["A1"] = "Preditor de Deformação Permanente — DNIT 179/2018-IE"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = f"Amostra: {nome}"
    ws["D2"] = f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    r = 4
    for lbl, v in [("σ₃ (kPa)", inp.get("s3")), ("σd (kPa)", inp.get("sd")),
                   ("σ₁/σ₃", inp.get("razao")), ("N ref.", inp.get("nc"))]:
        hdr(ws, r, 1, lbl)
        val(ws, r, 2, v)
        r += 1
    r = 4
    for lbl, k in [("εp a N ref. (%)", "dp_n"), ("εp a 10.000 (%)", "dp_10k"),
                   ("εp a 50.000 (%)", "dp_50k"), ("εp a 100.000 (%)", "dp_100k"),
                   ("εp a 150.000 (%)", "dp_150k")]:
        hdr(ws, r, 4, lbl)
        val(ws, r, 5, data.get(k))
        r += 1

    r += 1
    ws.cell(row=r, column=1, value=f"Comportamento (critério indicativo do app): "
                                   f"{TIPOS_NOME.get(tipo, '—')}").font = bold
    if atr:
        r += 1
        ws.cell(row=r, column=1, value=f"Camada h = {atr['h_cm']} cm → contribuição estimada "
                                       f"no afundamento = {atr['delta_mm']} mm")
    if ref:
        r += 1
        ws.cell(row=r, column=1, value=f"Solo do banco mais parecido: {ref.get('nome')} "
                                       f"(distância {ref.get('dist')}, {ref.get('nivel')})")

    r += 2
    solo_params = [("Wot (%)", "hot"), ("γd máx (g/cm³)", "gd"), ("Pass. #10 (%)", "p10"),
                   ("Pass. #40 (%)", "p40"), ("Pass. #200 (%)", "p200"), ("CBR (%)", "cbr")]
    for i, (lbl, k) in enumerate(solo_params, start=1):
        hdr(ws, r, i, lbl)
        val(ws, r + 1, i, inp.get(k))

    if guim:
        r += 3
        ws.cell(row=r, column=1, value="Modelo de Guimarães (2009) — ajuste com os 9 pares "
                                       "da Tabela 2").font = bold
        r += 1
        for i, sym in enumerate(["ψ₁", "ψ₂", "ψ₃", "ψ₄"], start=1):
            hdr(ws, r, i, sym)
            val(ws, r + 1, i, guim[i - 1])
        if guim_r2 is not None:
            ws.cell(row=r + 2, column=1, value=f"R² do ajuste: {guim_r2}").font = Font(italic=True)

    for i in range(1, 7):
        ws.column_dimensions[get_column_letter(i)].width = 22

    # Curva do par escolhido
    ws2 = wb.create_sheet("Curva εp")
    for c, t in enumerate(["N (ciclos)", "εp (%)", "P10 árvores", "P90 árvores"], start=1):
        hdr(ws2, 1, c, t)
    for i, n in enumerate(ciclos, start=2):
        val(ws2, i, 1, n)
        val(ws2, i, 2, curva[i - 2] if i - 2 < len(curva) else None)
        val(ws2, i, 3, p10[i - 2] if i - 2 < len(p10) else None)
        val(ws2, i, 4, p90[i - 2] if i - 2 < len(p90) else None)
    chart = LineChart()
    chart.title = f"Curva εp — {nome}"
    chart.y_axis.title = "εp (%)"
    chart.x_axis.title = "Ponto de leitura"
    chart.height, chart.width = 12, 20
    chart.add_data(Reference(ws2, min_col=2, min_row=1, max_row=len(ciclos) + 1),
                   titles_from_data=True)
    ws2.add_chart(chart, "F2")
    for col in "ABCD":
        ws2.column_dimensions[col].width = 14

    # 9 pares (entrada para o MeDiNa / conferência do ajuste)
    if pares9:
        ws3 = wb.create_sheet("9 pares Tabela 2")
        hdr(ws3, 1, 1, "N (ciclos)")
        for j, p in enumerate(pares9, start=2):
            hdr(ws3, 1, j, f"σ₃={p['s3']} / σd={p['sd']}")
            ws3.column_dimensions[get_column_letter(j)].width = 16
        for i, n in enumerate(ciclos, start=2):
            val(ws3, i, 1, n)
            for j, p in enumerate(pares9, start=2):
                val(ws3, i, j, p["curva"][i - 2])
        ws3.column_dimensions["A"].width = 12

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=f"DP_{_nome_arquivo(nome)}.xlsx")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1",
            host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
