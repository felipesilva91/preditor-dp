"""
PsiPav — treino e validação reproduzíveis.

Uso:
    pip install -r requirements-treino.txt
    python treino/treinar_modelos.py caminho/para/Modelagem_DP_ceara.xlsx

Lê a aba "Dados brutos", valida todos os modelos deixando um solo inteiro de fora
(LOSO), calibra as faixas de confiança (predição conformal agrupada por solo),
treina os modelos finais com todos os dados e grava em psipav/dados/:
    modelos.joblib, modelos_meta.json, banco.json
Também grava treino/resultados_validacao.json com as métricas para o artigo.
"""
import datetime
import json
import os
import sys
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "psipav", "dados")
PROPS = ["hot", "gd", "p10", "p40", "p200", "cbr", "LL", "IP", "DR"]
BASE = [10, 100, 500, 1000, 2000, 3000, 5000, 10000, 20000, 30000, 50000, 80000, 100000]
STOPS = [3000, 5000, 10000, 20000, 30000, 50000, 80000, 100000]
GRADE = [1, 10, 100, 1000, 5000, 10000, 50000, 100000, 150000]
C0 = 0.05  # termo de estabilização do escore conformal (% de deformação)


def et(leaf, mf):
    return ExtraTreesRegressor(500, min_samples_leaf=leaf, max_features=mf, random_state=0, n_jobs=-1)


def gb():
    return GradientBoostingRegressor(n_estimators=300, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=0)


def ep_interp(Nv, dv, n):
    return float(np.exp(np.interp(np.log(n), np.log(Nv), np.log(dv))))


def feats_triagem(D):
    a, b = D.s3.values / 1000, D.sd.values / 1000
    return np.c_[np.log10(D.N.values), a, b, b / a, a + b, D[PROPS].values]


def feats_ensaio(Nv, dv, stop, s3, sd):
    g = [n for n in BASE if n <= stop]
    e = np.log([ep_interp(Nv, dv, n) for n in g])
    s1 = (e[-1] - e[-2]) / np.log(g[-1] / g[-2])
    s2 = (e[-2] - e[-3]) / np.log(g[-2] / g[-3]) if len(g) > 2 else s1
    return [e[-1], e[0], e[-1] - e[0], s1, s2, s3, sd, sd / s3]


def main(planilha):
    df = pd.read_excel(planilha, sheet_name="Dados brutos", usecols=range(16))
    df.columns = ["solo", "LL", "LP", "IP", "DR", "hot", "gd", "cbr", "p10", "p40", "p200", "N", "s3", "sd", "dp", "aashto"]
    df = df.dropna(subset=["solo", "N", "dp"])
    df = df[(df.N >= 1) & (df.dp > 0)].copy()
    df["cid"] = df.solo + "|" + df.s3.astype(int).astype(str) + "|" + df.sd.astype(int).astype(str)
    print(f"{len(df)} leituras · {df.cid.nunique()} ensaios · {df.solo.nunique()} solos")
    res = {"dados": {"leituras": int(len(df)), "ensaios": int(df.cid.nunique()), "solos": int(df.solo.nunique())}}

    # ── Triagem: pontos em grade padrão de N (cada ensaio pesa igual) ──
    linhas = []
    for cid, c in df.groupby("cid"):
        c = c.sort_values("N")
        for n in GRADE:
            if n <= c.N.max() * 1.02:
                r = c.iloc[0]
                linhas.append(dict(solo=r.solo, s3=r.s3, sd=r.sd, N=n, dp=ep_interp(c.N.values, c.dp.values, n),
                                   **{k: r[k] for k in PROPS}))
    G = pd.DataFrame(linhas)
    X, y = feats_triagem(G), np.log(G.dp.values)
    solos = G.solo.unique()

    # validação deixando um solo de fora
    p_loso = np.zeros(len(G))
    p_rf = np.zeros(len(G))
    for s in solos:
        tr = (G.solo != s).values
        p_loso[~tr] = (et(10, 0.4).fit(X[tr], y[tr]).predict(X[~tr]) + gb().fit(X[tr], y[tr]).predict(X[~tr])) / 2
        p_rf[~tr] = RandomForestRegressor(100, max_depth=16, random_state=42, n_jobs=-1).fit(X[tr], y[tr]).predict(X[~tr])
    # comparação: divisão aleatória (mesmo solo no treino e no teste)
    p_kf = np.zeros(len(G))
    for tr, te in KFold(5, shuffle=True, random_state=1).split(X):
        p_kf[te] = RandomForestRegressor(100, max_depth=16, random_state=42, n_jobs=-1).fit(X[tr], y[tr]).predict(X[te])

    def metr(p, mask):
        e = np.abs(np.exp(p[mask] - y[mask]) - 1)
        yt, yp = np.exp(y[mask]), np.exp(p[mask])
        r2 = 1 - ((yt - yp) ** 2).sum() / ((yt - yt.mean()) ** 2).sum()
        return {"r2": float(r2), "erro_rel_mediano": float(np.median(e)), "erro_rel_p90": float(np.percentile(e, 90))}

    f150 = (G.N == 150000).values
    res["triagem"] = {"psipav_loso_150k": metr(p_loso, f150), "rf_original_loso_150k": metr(p_rf, f150),
                      "rf_kfold_aleatorio_150k": metr(p_kf, f150)}
    r = np.abs(p_loso - y)
    conformal_N = {str(int(n)): {"k80": float(np.quantile(r[(G.N == n).values], 0.8)),
                                 "k90": float(np.quantile(r[(G.N == n).values], 0.9))} for n in sorted(G.N.unique())}
    tri = {"et": et(10, 0.4).fit(X, y), "gb": gb().fit(X, y)}

    # ── Ensaio em andamento ──
    CUR = []
    for cid, c in df.groupby("cid"):
        c = c.sort_values("N").drop_duplicates("N")
        if c.N.max() >= 140000:
            CUR.append((c.solo.iloc[0], c.N.values.astype(float), c.dp.values, c.s3.iloc[0], c.sd.iloc[0]))
    gs = np.array([c[0] for c in CUR])
    ens, k80, k90, val_ens, escores = {}, {}, {}, {}, {}
    for st in STOPS:
        Xs = np.array([feats_ensaio(Nv, dv, st, s3, sd) for _, Nv, dv, s3, sd in CUR])
        ys = np.array([np.log(dv[-1] / ep_interp(Nv, dv, st)) for _, Nv, dv, s3, sd in CUR])
        p = np.zeros(len(ys))
        for s in np.unique(gs):
            tr = gs != s
            p[~tr] = (et(3, 0.6).fit(Xs[tr], ys[tr]).predict(Xs[~tr]) + gb().fit(Xs[tr], ys[tr]).predict(Xs[~tr])) / 2
        e_stop = np.array([ep_interp(Nv, dv, st) for _, Nv, dv, _, _ in CUR])
        real = np.array([dv[-1] for _, _, dv, _, _ in CUR])
        prev = e_stop * np.exp(p)
        sc = np.abs(prev - real) / (C0 + e_stop)
        escores[st] = (sc, e_stop, prev, real)
        k80[str(st)], k90[str(st)] = float(np.quantile(sc, 0.8)), float(np.quantile(sc, 0.9))
        rel = np.abs(prev / real - 1)
        val_ens[str(st)] = {"erro_rel_mediano": float(np.median(rel)), "erro_rel_p90": float(np.percentile(rel, 90)),
                            "erro_mm_mediano_cp200": float(np.median(np.abs(prev - real)) / 100 * 200)}
        ens[str(st)] = {"et": et(3, 0.6).fit(Xs, ys), "gb": gb().fit(Xs, ys)}
        print(f"  parada {st:>6}: erro mediano {val_ens[str(st)]['erro_rel_mediano'] * 100:.1f}%")
    # cobertura da faixa de 90% (quantil calculado sem o solo avaliado)
    cob = []
    for st in STOPS:
        sc, e_stop, prev, real = escores[st]
        for s in np.unique(gs):
            m = gs == s
            k = np.quantile(sc[~m], 0.9)
            cob.extend(list(np.abs(prev[m] - real[m]) <= k * (C0 + e_stop[m])))
    res["ensaio"] = {"por_parada": val_ens, "cobertura_90": float(np.mean(cob))}

    # ── Banco de ensaios reais e faixas ──
    sol = df.groupby("solo")[PROPS].first()
    ranges = {k: {"min": float(sol[k].min()), "max": float(sol[k].max())} for k in PROPS}
    meta = {
        "versao": "1.0.0", "treinado_em": datetime.date.today().isoformat(), "sklearn": sklearn.__version__,
        "dados": res["dados"],
        "triagem": {"modelo": "ExtraTrees + GradientBoosting (média em log εp)", "props": PROPS,
                    "conformal_por_N": conformal_N,
                    "validacao_150k": {k: res["triagem"]["psipav_loso_150k"][k] for k in ("erro_rel_mediano", "erro_rel_p90")}},
        "ensaio": {"modelo": "ExtraTrees + GradientBoosting por nível de parada (alvo log εp150k/εp_parada)",
                   "stops": STOPS, "C0": C0, "k90": k90, "k80": k80,
                   "validacao": f"deixa-um-solo-fora; cobertura da faixa 90% = {res['ensaio']['cobertura_90']:.3f}".replace(".", ",")},
        "ranges": ranges,
    }
    os.makedirs(SAIDA, exist_ok=True)
    joblib.dump({"triagem": tri, "ensaio": ens}, os.path.join(SAIDA, "modelos.joblib"), compress=3)
    with open(os.path.join(SAIDA, "modelos_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    # banco.json usa as funções do próprio app (classificação e Guimarães)
    with open(os.path.join(SAIDA, "banco.json"), "w", encoding="utf-8") as f:
        json.dump({"solos": {}, "ensaios": []}, f)
    sys.path.insert(0, RAIZ)
    from psipav import engine as E
    solos_b = {s: {**{k: float(c.iloc[0][k]) for k in PROPS}, "aashto": str(c.iloc[0].aashto)} for s, c in df.groupby("solo")}
    ensaios = []
    for (s, a, b), c in df.groupby(["solo", "s3", "sd"]):
        c = c.sort_values("N").drop_duplicates("N")
        Nv, dv = c.N.values.astype(float), c.dp.values
        idx = np.unique(np.r_[np.searchsorted(Nv, np.geomspace(Nv[0], Nv[-1], 60)).clip(0, len(Nv) - 1), len(Nv) - 1])
        ensaios.append({"solo": s, "s3": int(a), "sd": int(b), "N": Nv[idx].tolist(),
                        "ep": [round(float(x), 5) for x in dv[idx]], "classe": E.classificar(Nv, dv)})
    for s in solos_b:
        solos_b[s]["guimaraes"] = E.ajustar_guimaraes([e for e in ensaios if e["solo"] == s])
    with open(os.path.join(SAIDA, "banco.json"), "w", encoding="utf-8") as f:
        json.dump({"fonte": "Planilha Modelagem_DP_ceará (dados brutos), DNIT 179/2018-IE",
                   "solos": solos_b, "ensaios": ensaios}, f, ensure_ascii=False)
    res["classificacao"] = {
        "lima": pd.Series([e["classe"]["lima"] for e in ensaios]).value_counts().to_dict(),
        "werkmeister": pd.Series([e["classe"]["werkmeister"] for e in ensaios]).value_counts().to_dict(),
    }
    with open(os.path.join(RAIZ, "treino", "resultados_validacao.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Informe o caminho da planilha: python treino/treinar_modelos.py Modelagem_DP_ceara.xlsx")
    main(sys.argv[1])
