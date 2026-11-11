"""
PsiPav — Previsão e análise de deformação permanente de solos tropicais
DNIT 179/2018-IE · Modelo de Guimarães (2009) · Aprendizado de máquina com validação por solo
"""
import base64
import io
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

import numpy as np
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from fpdf import FPDF
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.drawing.image import Image as XLImage
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage
from werkzeug.security import check_password_hash, generate_password_hash

from psipav import engine as E

VERSAO = "1.1.0"
app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") is not None,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Acesso ───────────────────────────────────────────────────────────────────
# A senha NÃO fica no código (o repositório é público). Ela vem de uma variável de
# ambiente do servidor: PSIPAV_SENHA (texto) ou PSIPAV_SENHA_HASH (hash gerado com
# werkzeug.security.generate_password_hash). Sem nenhuma das duas, ninguém entra.
_senha_txt = os.environ.get("PSIPAV_SENHA")
SENHA_HASH = os.environ.get("PSIPAV_SENHA_HASH") or (generate_password_hash(_senha_txt) if _senha_txt else None)
del _senha_txt
_TENTATIVAS = {}           # ip -> [timestamps de tentativas erradas]
LIMITE_TENTATIVAS = 5
JANELA_S = 300
LIVRES = {"login", "logout", "health", "static"}


def _ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0]).strip()


@app.before_request
def _exigir_login():
    if request.endpoint in LIVRES or session.get("ok"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        ip = _ip()
        agora = time.time()
        lista = [t for t in _TENTATIVAS.get(ip, []) if agora - t < JANELA_S]
        if not SENHA_HASH:
            erro = "Senha de acesso não configurada no servidor (variável PSIPAV_SENHA)."
        elif len(lista) >= LIMITE_TENTATIVAS:
            erro = "Muitas tentativas. Aguarde alguns minutos e tente de novo."
        elif check_password_hash(SENHA_HASH, request.form.get("senha", "")):
            _TENTATIVAS.pop(ip, None)
            session.clear()
            session.permanent = True
            session["ok"] = True
            destino = request.args.get("next") or "/"
            return redirect(destino if destino.startswith("/") and not destino.startswith("//") else "/")
        else:
            lista.append(agora)
            erro = "Senha incorreta."
        _TENTATIVAS[ip] = lista
    return render_template("login.html", erro=erro, versao=VERSAO), (401 if erro else 200)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

ROTULOS = {
    "hot": ("Umidade ótima (wot)", "%"), "gd": ("Massa esp. aparente seca máx. (γd)", "g/cm³"),
    "p10": ("Passante #10", "%"), "p40": ("Passante #40", "%"), "p200": ("Passante #200", "%"),
    "cbr": ("CBR", "%"), "LL": ("Limite de liquidez (LL)", "%"), "IP": ("Índice de plasticidade (IP)", "%"),
    "DR": ("Densidade real dos grãos", "—"),
}


def _r(x, n=4):
    if x is None:
        return None
    return float(round(float(x), n))


def _lista(a, n=5):
    return [round(float(v), n) for v in a]


def _erro(msg, cod=400):
    return jsonify({"erro": msg}), cod


# ── Páginas ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", rotulos=ROTULOS, ranges=E.RANGES,
                           tabela2=E.TABELA2, versao=VERSAO)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "versao": VERSAO})


@app.route("/api/info")
def info():
    m = E.META
    return jsonify({
        "versao": VERSAO, "dados": m["dados"], "treinado_em": m["treinado_em"],
        "triagem": {"modelo": m["triagem"]["modelo"], "validacao_150k": m["triagem"]["validacao_150k"]},
        "ensaio": {"modelo": m["ensaio"]["modelo"], "validacao": m["ensaio"]["validacao"]},
        "solos": {k: {kk: v[kk] for kk in E.PROPS + ["aashto"]} for k, v in E.BANCO["solos"].items()},
        "ranges": E.RANGES,
    })


# ── Módulo 1: triagem por propriedades ───────────────────────────────────────
@app.route("/api/triagem", methods=["POST"])
def api_triagem():
    d = request.get_json(silent=True) or {}
    try:
        props = [float(d["props"][k]) for k in E.PROPS]
        s3 = int(d["s3"])
        sd = int(d["sd"])
        h_cm = float(d["h_cm"]) if d.get("h_cm") not in (None, "") else None
    except (KeyError, TypeError, ValueError) as e:
        return _erro(f"Dado inválido ou ausente: {e}")
    if (s3, sd) not in E.TABELA2:
        return _erro("Par de tensões fora da Tabela 2 da DNIT 179/2018-IE.")
    if h_cm is not None and not 0 < h_cm <= 200:
        return _erro("Espessura da camada deve estar entre 0 e 200 cm.")

    avisos = []
    fora = E.fora_do_dominio(props)
    if fora:
        nomes = ", ".join(ROTULOS[k][0] for k in fora)
        avisos.append(f"Fora da faixa dos dados de treino: {nomes}. A previsão é uma extrapolação.")
    p = dict(zip(E.PROPS, props))
    if not p["p200"] <= p["p40"] <= p["p10"]:
        avisos.append("Granulometria incoerente: o esperado é #200 ≤ #40 ≤ #10.")
    if p["IP"] > p["LL"]:
        avisos.append("IP maior que LL: confira os limites de Atterberg.")

    prev = E.prever_triagem(props, s3, sd)
    curvas9 = []
    for a, b in E.TABELA2:
        c = E.prever_triagem(props, a, b)["curva"]
        curvas9.append({"s3": a, "sd": b, "N": E.CICLOS, "ep": _lista(c)})
    guim = E.ajustar_guimaraes(curvas9)
    classe = E.classificar(E.CICLOS, prev["curva"])

    ref_nome, ref_dist, ref_nivel = E.solo_mais_parecido(props)
    if ref_nivel == "baixa":
        avisos.append(f"Nenhum solo do banco é parecido com o informado (o mais próximo é {ref_nome}).")
    ref_ensaio = next((e for e in E.BANCO["ensaios"]
                       if e["solo"] == ref_nome and e["s3"] == s3 and e["sd"] == sd), None)

    i150 = -1
    res = {
        "modulo": "triagem",
        "N": E.CICLOS,
        "ep": _lista(prev["curva"]),
        "inf80": _lista(prev["inf80"]), "sup80": _lista(prev["sup80"]),
        "inf90": _lista(prev["inf90"]), "sup90": _lista(prev["sup90"]),
        "ep150": _r(prev["curva"][i150]),
        "faixa90_150": [_r(prev["inf90"][i150]), _r(prev["sup90"][i150])],
        "pares9": curvas9,
        "guimaraes": guim,
        "guim_curva": E.curva_guimaraes(guim["psi"], s3, sd) if guim else None,
        "classe": classe,
        "taxas": E.taxas(E.CICLOS, prev["curva"]),
        "solo_ref": {"nome": ref_nome, "dist": ref_dist, "nivel": ref_nivel,
                     "props": {k: E.BANCO["solos"][ref_nome][k] for k in E.PROPS + ["aashto"]},
                     "ensaio": ({"N": ref_ensaio["N"], "ep": ref_ensaio["ep"], "classe": ref_ensaio["classe"]}
                                if ref_ensaio else None)},
        "avisos": avisos,
        "validacao": E.META["triagem"]["validacao_150k"],
    }
    if h_cm:
        res["atr"] = {"h_cm": h_cm, "mm": _r(prev["curva"][i150] / 100 * h_cm * 10, 3),
                      "inf90": _r(prev["inf90"][i150] / 100 * h_cm * 10, 3),
                      "sup90": _r(prev["sup90"][i150] / 100 * h_cm * 10, 3)}
    return jsonify(res)


# ── Leitura de arquivos ──────────────────────────────────────────────────────
@app.route("/api/importar", methods=["POST"])
def api_importar():
    if "arquivo" in request.files:
        f = request.files["arquivo"]
        nome = (f.filename or "").lower()
        if nome.endswith((".xlsx", ".xlsm")):
            try:
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                ws = wb.worksheets[0]
                linhas = ["\t".join("" if c is None else str(c) for c in r) for r in ws.iter_rows(values_only=True)]
                texto = "\n".join(linhas)
            except Exception as e:
                return _erro(f"Não foi possível ler a planilha: {e}")
        else:
            texto = f.read().decode("utf-8", errors="ignore")
    else:
        texto = (request.get_json(silent=True) or {}).get("texto", "")
    if not texto.strip():
        return _erro("Arquivo vazio.")
    cab, dados = E.ler_tabela(texto)
    if not dados:
        return _erro("Nenhuma linha numérica encontrada.")
    return jsonify({"cabecalho": cab, "linhas": dados[:20000], "n": len(dados)})


def _serie(d, altura_mm):
    """Converte N + deformação (% ou mm) em listas ordenadas e limpas."""
    N = np.asarray(d["N"], float)
    v = np.asarray(d["valor"], float)
    unidade = d.get("unidade", "pct")
    ep = v / altura_mm * 100.0 if unidade == "mm" else v
    m = np.isfinite(N) & np.isfinite(ep) & (N >= 1)
    N, ep = N[m], ep[m]
    ordem = np.argsort(N)
    N, ep = N[ordem], ep[ordem]
    _, idx = np.unique(N, return_index=True)
    return N[idx], ep[idx]


# ── Módulo 2: ensaio em andamento ────────────────────────────────────────────
@app.route("/api/ensaio", methods=["POST"])
def api_ensaio():
    d = request.get_json(silent=True) or {}
    try:
        s3 = float(d["s3"])
        sd = float(d["sd"])
        altura = float(d.get("altura_mm", 200))
        tol_mm = float(d.get("tol_mm", 0.10))
        tol_rel = float(d.get("tol_rel", 10)) / 100.0
        N, ep = _serie(d, altura)
    except (KeyError, TypeError, ValueError) as e:
        return _erro(f"Dado inválido ou ausente: {e}")
    if len(N) < 5:
        return _erro("Envie pelo menos 5 leituras.")
    if not (10 <= s3 <= 300 and 10 <= sd <= 800):
        return _erro("Tensões fora da faixa usual do ensaio (σ3 10–300 kPa; σd 10–800 kPa).")
    if np.any(ep <= 0):
        N, ep = N[ep > 0], ep[ep > 0]

    avisos = []
    if (int(s3), int(sd)) not in E.TABELA2:
        avisos.append("Par de tensões fora da Tabela 2. O modelo foi treinado só com os 9 pares da norma.")
    if np.any(np.diff(ep) < -0.02):
        avisos.append("Há quedas na deformação acumulada maiores que 0,02%. Verifique as leituras do LVDT.")
    if N.min() > 100:
        avisos.append("Faltam leituras iniciais (antes de 100 ciclos). A norma recomenda não descartar os ciclos iniciais.")

    prev = E.prever_ensaio(N, ep, s3, sd, altura, tol_mm, tol_rel)
    if "erro" in prev:
        return _erro(prev["erro"])
    classe = E.classificar(N, ep)
    res = {"modulo": "ensaio", "N": _lista(N, 1), "ep": _lista(ep), "s3": s3, "sd": sd,
           "altura_mm": altura, "tol_mm": tol_mm, "tol_rel": tol_rel * 100,
           "previsao": prev, "classe": classe, "taxas": E.taxas(N, ep), "avisos": avisos,
           "validacao": E.META["ensaio"]["validacao"]}
    return jsonify(res)


# ── Módulo 3: análise de ensaios completos ───────────────────────────────────
@app.route("/api/analise", methods=["POST"])
def api_analise():
    d = request.get_json(silent=True) or {}
    try:
        altura = float(d.get("altura_mm", 200))
        h_cm = float(d["h_cm"]) if d.get("h_cm") not in (None, "") else None
        brutos = d["ensaios"]
    except (KeyError, TypeError, ValueError) as e:
        return _erro(f"Dado inválido ou ausente: {e}")
    if not brutos:
        return _erro("Nenhum ensaio enviado.")

    ensaios, saida, avisos = [], [], []
    for b in brutos:
        try:
            N, ep = _serie(b, altura)
            s3, sd = float(b["s3"]), float(b["sd"])
        except (KeyError, TypeError, ValueError) as e:
            return _erro(f"Ensaio inválido: {e}")
        m = ep > 0
        N, ep = N[m], ep[m]
        if len(N) < 5:
            avisos.append(f"Ensaio σ3={s3:g}/σd={sd:g} ignorado: menos de 5 leituras.")
            continue
        cl = E.classificar(N, ep)
        ensaios.append({"s3": s3, "sd": sd, "N": N, "ep": ep})
        saida.append({"s3": s3, "sd": sd, "N": _lista(N, 1), "ep": _lista(ep), "classe": cl,
                      "taxas": E.taxas(N, ep)})
        if N.max() < 0.98 * E.N_FINAL:
            avisos.append(f"Ensaio σ3={s3:g}/σd={sd:g} terminou em {int(N.max()):,} ciclos (norma: 150.000).".replace(",", "."))

    pares = {(e["s3"], e["sd"]) for e in ensaios}
    if len(pares) < 6:
        avisos.append(f"Só {len(pares)} pares de tensão. A DNIT 179/2018-IE pede no mínimo 6, bem espaçados.")
    guim = E.ajustar_guimaraes(ensaios) if len(pares) >= 3 else None
    if guim is None:
        avisos.append("Não foi possível ajustar o modelo de Guimarães (são necessários pelo menos 3 pares).")
    else:
        for s in saida:
            s["modelo"] = E.curva_guimaraes(guim["psi"], s["s3"], s["sd"])
    res = {"modulo": "analise", "ensaios": saida, "guimaraes": guim, "avisos": avisos,
           "altura_mm": altura, "N_modelo": E.CICLOS}
    if h_cm and saida:
        pior = max(saida, key=lambda s: s["ep"][-1])
        res["atr"] = {"h_cm": h_cm, "mm": _r(pior["ep"][-1] / 100 * h_cm * 10, 3),
                      "par": [pior["s3"], pior["sd"]]}
    return jsonify(res)


# ── Relatórios ───────────────────────────────────────────────────────────────
class _PDF(FPDF):
    def header(self):
        self.set_font("dv", "B", 9)
        self.cell(0, 5, "PsiPav · Deformação permanente de solos · DNIT 179/2018-IE", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(0)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("dv", "", 7)
        self.cell(0, 5, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · PsiPav v{VERSAO} · "
                        f"Página {self.page_no()}", align="C")


def _pdf(rel):
    pdf = _PDF()
    fdir = os.path.join(BASE_DIR, "fontes")
    pdf.add_font("dv", "", os.path.join(fdir, "DejaVuSans.ttf"))
    pdf.add_font("dv", "B", os.path.join(fdir, "DejaVuSans-Bold.ttf"))
    pdf.add_font("dv", "I", os.path.join(fdir, "DejaVuSans-Oblique.ttf"))
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("dv", "B", 15)
    pdf.multi_cell(0, 7, rel.get("titulo", "Relatório"), new_x="LMARGIN", new_y="NEXT")
    if rel.get("subtitulo"):
        pdf.set_font("dv", "", 9)
        pdf.multi_cell(0, 5, rel["subtitulo"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    largura = pdf.w - pdf.l_margin - pdf.r_margin

    for sec in rel.get("secoes", []):
        tipo = sec.get("tipo")
        if sec.get("titulo"):
            precisa = 105 if tipo == "imagem" else 40
            if pdf.get_y() > pdf.h - 15 - precisa:
                pdf.add_page()
            pdf.ln(2)
            pdf.set_font("dv", "B", 10)
            pdf.cell(0, 6, sec["titulo"], new_x="LMARGIN", new_y="NEXT")
        if tipo == "texto":
            pdf.set_font("dv", "I" if sec.get("italico") else "", 8.5)
            pdf.multi_cell(0, 4.6, sec["texto"], new_x="LMARGIN", new_y="NEXT")
        elif tipo == "destaque":
            pdf.set_font("dv", "B", 20)
            pdf.cell(0, 10, sec["texto"], new_x="LMARGIN", new_y="NEXT")
            if sec.get("nota"):
                pdf.set_font("dv", "", 8.5)
                pdf.multi_cell(0, 4.6, sec["nota"], new_x="LMARGIN", new_y="NEXT")
        elif tipo in ("tabela", "kv"):
            linhas = sec["linhas"]
            cab = sec.get("cabecalho")
            ncol = len(cab) if cab else len(linhas[0])
            w = sec.get("larguras") or [largura / ncol] * ncol
            pdf.set_font("dv", "", 8)
            if cab:
                pdf.set_fill_color(225, 225, 225)
                pdf.set_font("dv", "B", 8)
                for c, wi in zip(cab, w):
                    pdf.cell(wi, 6, str(c), border=1, align="C", fill=True)
                pdf.ln()
                pdf.set_font("dv", "", 8)
            for ln in linhas:
                if pdf.get_y() > pdf.h - 20:
                    pdf.add_page()
                for j, (c, wi) in enumerate(zip(ln, w)):
                    estilo = "B" if (tipo == "kv" and j == 0) else ""
                    pdf.set_font("dv", estilo, 8)
                    pdf.cell(wi, 5.5, "" if c is None else str(c), border=1,
                             align="L" if (tipo == "kv" and j == 0) else "C")
                pdf.ln()
        elif tipo == "imagem" and sec.get("img"):
            try:
                bruto = base64.b64decode(sec["img"].split(",")[-1])
                with PILImage.open(io.BytesIO(bruto)) as im:
                    iw, ih = im.size
                w = largura
                h = w * ih / iw
                if h > 130:             # limita a altura e reduz a largura na mesma proporção
                    h = 130
                    w = h * iw / ih
                if pdf.get_y() + h > pdf.h - 15:
                    pdf.add_page()
                pdf.image(io.BytesIO(bruto), x=pdf.l_margin + (largura - w) / 2, w=w, h=h)
                pdf.ln(2)
            except Exception:
                pass
    return bytes(pdf.output())


def _xlsx(rel):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Relatório"
    negrito = Font(bold=True)
    cinza = PatternFill("solid", fgColor="E1E1E1")
    borda = Border(*(Side(style="thin"),) * 4)
    ws["A1"] = rel.get("titulo", "Relatório")
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = rel.get("subtitulo", "")
    ws["A3"] = f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · PsiPav v{VERSAO}"
    r = 5
    for sec in rel.get("secoes", []):
        tipo = sec.get("tipo")
        if tipo == "imagem":
            if not sec.get("img"):
                continue
            try:
                bruto = base64.b64decode(sec["img"].split(",")[-1])
                img = XLImage(io.BytesIO(bruto))
                escala = 760 / img.width
                img.width, img.height = int(img.width * escala), int(img.height * escala)
                if sec.get("titulo"):
                    ws.cell(row=r, column=1, value=sec["titulo"]).font = negrito
                    r += 1
                ws.add_image(img, f"A{r}")
                r += int(img.height / 20) + 2
            except Exception:
                pass
            continue
        if sec.get("titulo"):
            ws.cell(row=r, column=1, value=sec["titulo"]).font = negrito
            r += 1
        if tipo in ("texto", "destaque"):
            ws.cell(row=r, column=1, value=sec["texto"])
            r += 1
            if sec.get("nota"):
                ws.cell(row=r, column=1, value=sec["nota"])
                r += 1
        elif tipo in ("tabela", "kv"):
            if sec.get("cabecalho"):
                for j, c in enumerate(sec["cabecalho"], start=1):
                    cel = ws.cell(row=r, column=j, value=c)
                    cel.font, cel.fill, cel.border = negrito, cinza, borda
                r += 1
            for ln in sec["linhas"]:
                for j, c in enumerate(ln, start=1):
                    cel = ws.cell(row=r, column=j, value=c)
                    cel.border = borda
                    if tipo == "kv" and j == 1:
                        cel.font = negrito
                r += 1
        r += 1
    for j in range(1, 12):
        ws.column_dimensions[get_column_letter(j)].width = 18
    ws.column_dimensions["A"].width = 34

    for serie in rel.get("series", []):
        sh = wb.create_sheet(serie["nome"][:31])
        for j, c in enumerate(serie["colunas"], start=1):
            cel = sh.cell(row=1, column=j, value=c)
            cel.font, cel.fill = negrito, cinza
            sh.column_dimensions[get_column_letter(j)].width = 16
        for i, ln in enumerate(serie["linhas"], start=2):
            for j, c in enumerate(ln, start=1):
                sh.cell(row=i, column=j, value=c)
        g = serie.get("grafico")
        n = len(serie["linhas"])
        if g and n >= 2:
            ch = ScatterChart()
            ch.title = g.get("titulo", serie["nome"])
            ch.style = 2
            ch.height, ch.width = 11, 20
            ch.x_axis.title = g.get("x", serie["colunas"][0])
            ch.y_axis.title = g.get("y", "εp (%)")
            if g.get("log_x", True):
                ch.x_axis.scaling.logBase = 10
            ch.x_axis.delete = False
            ch.y_axis.delete = False
            ch.legend.position = "b"
            xs = Reference(sh, min_col=1, min_row=2, max_row=n + 1)
            colunas = g.get("colunas") or list(range(2, len(serie["colunas"]) + 1))
            for col in colunas:
                ys = Reference(sh, min_col=col, min_row=1, max_row=n + 1)
                s_ = Series(ys, xs, title_from_data=True)
                s_.marker.symbol = "none" if g.get("linhas", True) else "circle"
                s_.smooth = False
                ch.series.append(s_)
            sh.add_chart(ch, f"{get_column_letter(len(serie['colunas']) + 2)}2")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.route("/api/relatorio/<fmt>", methods=["POST"])
def api_relatorio(fmt):
    rel = request.get_json(silent=True) or {}
    nome = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rel.get("arquivo", "PsiPav"))[:60] or "PsiPav"
    if fmt == "pdf":
        dados, mime = _pdf(rel), "application/pdf"
    elif fmt == "xlsx":
        dados, mime = _xlsx(rel), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        return _erro("Formato inválido.")
    return send_file(io.BytesIO(dados), mimetype=mime, as_attachment=True, download_name=f"{nome}.{fmt}")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)))
