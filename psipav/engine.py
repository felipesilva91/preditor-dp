"""
PsiPav — núcleo de cálculo.

Reúne tudo o que não depende do Flask: modelos de previsão, faixas de confiança
(predição conformal agrupada por solo), ajuste do modelo de Guimarães (2009),
classificação de acomodamento (shakedown) e leitura de arquivos de ensaio.
"""
import csv
import io
import json
import os

import joblib
import numpy as np
from scipy.optimize import curve_fit

P0 = 101.325  # kPa (pressão atmosférica de referência)
PROPS = ["hot", "gd", "p10", "p40", "p200", "cbr", "LL", "IP", "DR"]
BASE = [10, 100, 500, 1000, 2000, 3000, 5000, 10000, 20000, 30000, 50000, 80000, 100000]
STOPS = [3000, 5000, 10000, 20000, 30000, 50000, 80000, 100000]
CICLOS = [1, 10, 50, 100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 150000]
N_FINAL = 150000

TABELA2 = [(40, 40), (40, 80), (40, 120), (80, 80), (80, 160), (80, 240),
           (120, 120), (120, 240), (120, 360)]

# Critério de acomodamento (Lima, 2020), em %/ciclo:
# taxa de 10^-6 x 10^-3 por ciclo = 1e-9 /ciclo = 1e-7 %/ciclo
TAXA_A = 1e-7
TAXA_C = 1e-5
EP_AB = 1.0          # % (1% da altura do corpo de prova)
# Werkmeister (2003) / EN 13286-7: diferença entre 5.000 e 3.000 ciclos (deformação, adimensional)
WERK_A = 0.045e-3
WERK_C = 0.4e-3

DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados")

# ── Carregamento ─────────────────────────────────────────────────────────────
_MODELOS = joblib.load(os.path.join(DADOS, "modelos.joblib"))
with open(os.path.join(DADOS, "modelos_meta.json"), encoding="utf-8") as f:
    META = json.load(f)
with open(os.path.join(DADOS, "banco.json"), encoding="utf-8") as f:
    BANCO = json.load(f)

RANGES = META["ranges"]


# ── Utilidades ───────────────────────────────────────────────────────────────
def ep_interp(Nv, dv, n):
    """εp em N qualquer, interpolando em log-log."""
    Nv = np.asarray(Nv, float)
    dv = np.asarray(dv, float)
    m = (Nv > 0) & (dv > 0)
    return float(np.exp(np.interp(np.log(n), np.log(Nv[m]), np.log(dv[m]))))


def _media_modelos(par, X):
    return (par["et"].predict(X) + par["gb"].predict(X)) / 2.0


def guimaraes(X, psi1, psi2, psi3, psi4):
    s3, sd, N = X
    return psi1 * (s3 / P0) ** psi2 * (sd / P0) ** psi3 * N ** psi4


# ── Triagem por propriedades ─────────────────────────────────────────────────
def _feats_triagem(N, s3, sd, props):
    N = np.atleast_1d(np.asarray(N, float))
    a, b = s3 / 1000.0, sd / 1000.0
    P = np.tile(np.asarray(props, float), (len(N), 1))
    return np.c_[np.log10(N), np.full(len(N), a), np.full(len(N), b),
                 np.full(len(N), b / a), np.full(len(N), a + b), P]


def _k_triagem(n, nivel):
    tabela = META["triagem"]["conformal_por_N"]
    ns = sorted(int(k) for k in tabela)
    alvo = min(ns, key=lambda x: abs(np.log(x) - np.log(max(n, 1))))
    return tabela[str(alvo)][nivel]


def prever_triagem(props, s3, sd, ciclos=CICLOS):
    """Curva prevista só com propriedades + faixa conformal de 80% e 90%."""
    X = _feats_triagem(ciclos, s3, sd, props)
    log_ep = _media_modelos(_MODELOS["triagem"], X)
    curva = np.maximum.accumulate(np.exp(log_ep))
    k80 = np.array([_k_triagem(n, "k80") for n in ciclos])
    k90 = np.array([_k_triagem(n, "k90") for n in ciclos])
    return {
        "curva": curva,
        "inf80": curva / np.exp(k80), "sup80": curva * np.exp(k80),
        "inf90": curva / np.exp(k90), "sup90": curva * np.exp(k90),
    }


def fora_do_dominio(props):
    avisos = []
    for k, v in zip(PROPS, props):
        r = RANGES[k]
        if not r["min"] <= v <= r["max"]:
            avisos.append(k)
    return avisos


def solo_mais_parecido(props):
    vet = np.asarray(props, float)
    faixa = np.array([max(RANGES[k]["max"] - RANGES[k]["min"], 1e-6) for k in PROPS])
    melhor, dmin = None, np.inf
    for nome, s in BANCO["solos"].items():
        ref = np.array([s[k] for k in PROPS])
        d = float(np.sqrt(np.mean(((vet - ref) / faixa) ** 2)))
        if d < dmin:
            melhor, dmin = nome, d
    nivel = "alta" if dmin <= 0.12 else ("média" if dmin <= 0.25 else "baixa")
    return melhor, round(dmin, 3), nivel


# ── Ensaio em andamento ──────────────────────────────────────────────────────
def _feats_ensaio(Nv, dv, stop, s3, sd):
    g = [n for n in BASE if n <= stop]
    e = np.log([ep_interp(Nv, dv, n) for n in g])
    s1 = (e[-1] - e[-2]) / np.log(g[-1] / g[-2])
    s2 = (e[-2] - e[-3]) / np.log(g[-2] / g[-3]) if len(g) > 2 else s1
    return [e[-1], e[0], e[-1] - e[0], s1, s2, s3, sd, sd / s3]


def prever_ensaio(Nv, dv, s3, sd, altura_mm=200.0, tol_mm=0.10, tol_rel=0.10):
    """Prevê εp em 150.000 ciclos a partir das leituras já feitas."""
    Nv = np.asarray(Nv, float)
    dv = np.asarray(dv, float)
    nmax = float(Nv.max())
    if nmax >= N_FINAL * 0.98:
        return {"concluido": True}
    possiveis = [s for s in STOPS if s <= nmax]
    if not possiveis:
        return {"erro": f"São necessárias leituras até pelo menos {STOPS[0]:,} ciclos.".replace(",", ".")}
    stop = possiveis[-1]
    X = np.array([_feats_ensaio(Nv, dv, stop, s3, sd)])
    r = float(_media_modelos(_MODELOS["ensaio"][str(stop)], X)[0])
    e_stop = ep_interp(Nv, dv, stop)
    e150 = e_stop * np.exp(r)
    e150 = max(e150, float(dv[Nv <= nmax][-1]))  # não pode ser menor que o já medido
    c0 = META["ensaio"]["C0"]
    meia90 = META["ensaio"]["k90"][str(stop)] * (c0 + e_stop)
    meia80 = META["ensaio"]["k80"][str(stop)] * (c0 + e_stop)
    e_atual = float(dv[np.argmax(Nv)])

    # trecho projetado (lei de potência entre a última leitura e a previsão)
    n_proj = np.unique(np.r_[nmax, [n for n in [5000, 10000, 20000, 30000, 50000, 80000, 100000, 150000] if n > nmax]])
    b = np.log(e150 / max(e_atual, 1e-6)) / np.log(N_FINAL / nmax) if nmax < N_FINAL else 0.0
    proj = e_atual * (n_proj / nmax) ** b
    frac = np.log(n_proj / nmax) / np.log(N_FINAL / nmax)
    inf90 = np.maximum(proj - frac * meia90, e_atual)
    sup90 = proj + frac * meia90

    meia_mm = meia90 / 100.0 * altura_mm
    pode_parar = (meia_mm <= tol_mm) or (meia90 / e150 <= tol_rel)
    proximo = next((s for s in STOPS if s > stop), N_FINAL)
    return {
        "concluido": False,
        "nivel_parada": stop,
        "ep_atual": e_atual,
        "n_atual": nmax,
        "ep150": e150,
        "inf90": max(e150 - meia90, e_atual), "sup90": e150 + meia90,
        "inf80": max(e150 - meia80, e_atual), "sup80": e150 + meia80,
        "meia90_mm": meia_mm,
        "delta150_mm": e150 / 100.0 * altura_mm,
        "pode_parar": bool(pode_parar),
        "proximo_ponto": proximo,
        "proj_n": n_proj.tolist(), "proj_ep": proj.tolist(),
        "proj_inf90": inf90.tolist(), "proj_sup90": sup90.tolist(),
        "horas_economizadas": (N_FINAL - nmax) / 2.0 / 3600.0,
    }


# ── Acomodamento (shakedown) ─────────────────────────────────────────────────
def taxas(Nv, dv):
    """Pontos do gráfico de Dawson e Wellner: εp acumulada × taxa (%/ciclo)."""
    Nv = np.asarray(Nv, float)
    dv = np.asarray(dv, float)
    ordem = np.argsort(Nv)
    Nv, dv = Nv[ordem], dv[ordem]
    pts = []
    for i in range(1, len(Nv)):
        dn = Nv[i] - Nv[i - 1]
        if dn <= 0:
            continue
        t = (dv[i] - dv[i - 1]) / dn
        if t > 0 and dv[i] > 0:
            pts.append({"ep": float(dv[i]), "taxa": float(t), "n": float(Nv[i])})
    return pts


def classificar(Nv, dv):
    """Classificação A / AB / B / C (Lima, 2020) e A / B / C (Werkmeister, 2003)."""
    Nv = np.asarray(Nv, float)
    dv = np.asarray(dv, float)
    m = (Nv > 0) & (dv > 0)
    Nv, dv = Nv[m], dv[m]
    n_end = float(Nv.max())
    ep_end = float(dv[np.argmax(Nv)])
    trecho = Nv >= n_end / 3.0
    if trecho.sum() >= 3:
        B = float(np.polyfit(np.log(Nv[trecho]), np.log(dv[trecho]), 1)[0])
    else:
        B = float(np.polyfit(np.log(Nv[Nv >= 100]), np.log(dv[Nv >= 100]), 1)[0])
    B = max(B, 0.0)
    taxa_fim = B * ep_end / n_end
    n_estrela = None
    if taxa_fim > TAXA_A and 0 < B < 1:
        n_estrela = n_end * (TAXA_A / taxa_fim) ** (1.0 / (B - 1.0))
    if taxa_fim <= TAXA_A:
        lima = "AB" if ep_end > EP_AB else "A"
    elif taxa_fim > TAXA_C:
        lima = "C"
    else:
        lima = "B"
    werk = None
    if n_end >= 5000:
        delta = (ep_interp(Nv, dv, 5000) - ep_interp(Nv, dv, 3000)) / 100.0
        werk = "A" if delta < WERK_A else ("C" if delta > WERK_C else "B")
    return {
        "lima": lima, "werkmeister": werk, "taxa_final": taxa_fim, "expoente_local": B,
        "ep_final": ep_end, "n_final": n_end,
        "n_acomodamento": n_estrela,
    }


# ── Guimarães (2009) ─────────────────────────────────────────────────────────
def ajustar_guimaraes(ensaios, pontos_por_ensaio=25):
    """Regressão não linear múltipla em log(εp) com todos os ensaios (DNIT 179, item 10.1).

    Cada ensaio é reamostrado em N log-espaçado para que ensaios com mais leituras
    não pesem mais no ajuste.
    """
    s3a, sda, na, ya = [], [], [], []
    for e in ensaios:
        Nv = np.asarray(e["N"], float)
        dv = np.asarray(e["ep"], float)
        m = (Nv >= 1) & (dv > 0)
        if m.sum() < 3:
            continue
        grade = np.unique(np.geomspace(max(Nv[m].min(), 1), Nv[m].max(), pontos_por_ensaio))
        for n in grade:
            s3a.append(float(e["s3"]))
            sda.append(float(e["sd"]))
            na.append(float(n))
            ya.append(ep_interp(Nv[m], dv[m], n))
    if len({(a, b) for a, b in zip(s3a, sda)}) < 3:
        return None
    X = (np.array(s3a), np.array(sda), np.array(na))
    y = np.array(ya)

    def _log(Xi, a, b, c, d):
        return np.log(guimaraes(Xi, a, b, c, d))

    try:
        popt, _ = curve_fit(_log, X, np.log(y), p0=[0.1, 0.3, 1.0, 0.07],
                            bounds=([1e-6, -3, 0, 0], [100, 3, 5, 1]), maxfev=40000)
    except Exception:
        return None
    fit = guimaraes(X, *popt)
    ss_res = np.sum((y - fit) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return {
        "psi": [float(p) for p in popt],
        "r2": float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
        "erro_rel_medio": float(np.mean(np.abs(fit - y) / y)),
        "n_pares": len({(a, b) for a, b in zip(s3a, sda)}),
    }


def curva_guimaraes(psi, s3, sd, ciclos=CICLOS):
    return [float(guimaraes((s3, sd, n), *psi)) for n in ciclos]


# ── Leitura de arquivos ──────────────────────────────────────────────────────
def _num(txt):
    txt = str(txt).strip().replace(" ", "")
    if txt.count(",") == 1 and txt.count(".") >= 1:
        txt = txt.replace(".", "").replace(",", ".")
    else:
        txt = txt.replace(",", ".")
    return float(txt)


def ler_tabela(texto):
    """Lê CSV/TXT colado ou enviado. Aceita ; , ou tab e vírgula decimal.

    Retorna lista de linhas numéricas e o cabeçalho (se houver).
    """
    texto = texto.strip().lstrip("﻿")
    amostra = texto[:2000]
    if "\t" in amostra:
        sep = "\t"
    elif ";" in amostra:
        sep = ";"
    else:
        sep = ","
    linhas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    cab, dados = None, []
    for ln in linhas:
        ln = [c for c in ln if c.strip() != ""]
        if not ln:
            continue
        try:
            dados.append([_num(c) for c in ln])
        except ValueError:
            if cab is None and not dados:
                cab = [c.strip().lower() for c in ln]
    return cab, dados
