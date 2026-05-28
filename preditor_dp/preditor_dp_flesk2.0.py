"""
Preditor de Deformação Permanente de Solos
DNIT 179/2018-IE | Random Forest + Modelo de Guimarães (2009)
"""

from flask import Flask, render_template, request, jsonify
import numpy as np
import pickle
import os
from scipy.optimize import curve_fit

app = Flask(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "data", "model_rf.pkl")
with open(MODEL_PATH, "rb") as f:
    MODEL = pickle.load(f)

P0_ATM = 101.325
CICLOS = [1,10,50,100,500,1000,2000,5000,10000,20000,50000,100000,150000]
CL_LABELS = ["1","10","50","100","500","1k","2k","5k","10k","20k","50k","100k","150k"]

DNIT_TABELA2 = {
    40:  [{"sd":40,"razao":"2,0"},{"sd":80,"razao":"3,0"},{"sd":120,"razao":"4,0"}],
    80:  [{"sd":80,"razao":"2,0"},{"sd":160,"razao":"3,0"},{"sd":240,"razao":"4,0"}],
    120: [{"sd":120,"razao":"2,0"},{"sd":240,"razao":"3,0"},{"sd":360,"razao":"4,0"}],
}

RANGES = {
    "hot":  {"min":8.0,  "max":21.0,  "unit":"%",     "label":"Umidade Ótima (Wot)"},
    "gd":   {"min":1.63, "max":2.11,  "unit":"g/cm³", "label":"γd máx"},
    "p10":  {"min":21.0, "max":100.0, "unit":"%",     "label":"Passante #10"},
    "p40":  {"min":16.0, "max":100.0, "unit":"%",     "label":"Passante #40"},
    "p200": {"min":4.31, "max":98.0,  "unit":"%",     "label":"Passante #200"},
    "cbr":  {"min":2.0,  "max":34.0,  "unit":"%",     "label":"CBR"},
}


def guimaraes_model(X_inp, psi1, psi2, psi3, psi4):
    s3, sd, N = X_inp
    return psi1 * (s3 / P0_ATM) ** psi2 * (sd / P0_ATM) ** psi3 * N ** psi4


def predict_curve(s3_kpa, sd_kpa, hot, gd, p10, p40, p200, cbr):
    s3 = s3_kpa / 1000.0
    sd = sd_kpa / 1000.0
    rows = [[np.log10(c), s3, sd, sd/s3, sd+s3, hot, gd, p10, p40, p200, cbr] for c in CICLOS]
    preds = MODEL.predict(np.array(rows))
    return np.maximum(preds, 0.0)


def fit_guimaraes(dp_curve, s3_kpa, sd_kpa):
    N_arr  = np.array(CICLOS, dtype=float)
    s3_arr = np.full(len(CICLOS), float(s3_kpa))
    sd_arr = np.full(len(CICLOS), float(sd_kpa))
    try:
        popt, _ = curve_fit(guimaraes_model, (s3_arr, sd_arr, N_arr), dp_curve,
                            p0=[0.1,0.5,1.0,0.1], maxfev=20000, bounds=(0,100))
        dp_fit = guimaraes_model((s3_arr, sd_arr, N_arr), *popt)
        ss_res = np.sum((dp_curve - dp_fit)**2)
        ss_tot = np.sum((dp_curve - np.mean(dp_curve))**2)
        r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0.0
        return [round(float(p),4) for p in popt], round(r2,4)
    except Exception:
        return None, None


def classify_behavior(dp_curve):
    dp150 = dp_curve[-1]
    slope = (dp_curve[-1] - dp_curve[8]) / (150000 - 10000)
    if dp150 < 0.5 and slope < 0.000015: return 1
    if dp150 < 1.5 and slope < 0.000060: return 2
    if dp150 < 3.5: return 3
    return 4


@app.route("/")
def index():
    return render_template("index.html", ranges=RANGES, dnit_tabela2=DNIT_TABELA2)


@app.route("/api/tensoes/<int:s3>")
def get_tensoes(s3):
    pares = DNIT_TABELA2.get(s3)
    if not pares:
        return jsonify({"error":"σ₃ inválido. Use 40, 80 ou 120 kPa."}), 400
    return jsonify(pares)


@app.route("/api/calcular", methods=["POST"])
def calcular():
    data = request.get_json()
    try:
        hot  = float(data["hot"])
        gd   = float(data["gd"])
        p10  = float(data["p10"])
        p40  = float(data["p40"])
        p200 = float(data["p200"])
        cbr  = float(data["cbr"])
        s3   = int(data["s3"])
        sd   = int(data["sd"])
        nc   = int(data.get("nc", 150000))
        nome = str(data.get("nome","Amostra")).strip() or "Amostra"
    except (KeyError,ValueError,TypeError) as e:
        return jsonify({"error":f"Parâmetro inválido: {e}"}), 400

    erros = []
    r = RANGES
    if not (r["hot"]["min"]  <= hot  <= r["hot"]["max"]):
        erros.append(f"Wot ({r['hot']['min']}–{r['hot']['max']}%)")
    if not (r["gd"]["min"]   <= gd   <= r["gd"]["max"]):
        erros.append(f"γd ({r['gd']['min']}–{r['gd']['max']} g/cm³)")
    if not (r["p10"]["min"]  <= p10  <= r["p10"]["max"]):
        erros.append(f"#10 ({r['p10']['min']}–{r['p10']['max']}%)")
    if not (r["p40"]["min"]  <= p40  <= r["p40"]["max"]):
        erros.append(f"#40 ({r['p40']['min']}–{r['p40']['max']}%)")
    if not (r["p200"]["min"] <= p200 <= r["p200"]["max"]):
        erros.append(f"#200 ({r['p200']['min']}–{r['p200']['max']}%)")
    if not (r["cbr"]["min"]  <= cbr  <= r["cbr"]["max"]):
        erros.append(f"CBR ({r['cbr']['min']}–{r['cbr']['max']}%)")
    if erros:
        return jsonify({"error":"Valores fora do intervalo de treino: " + ", ".join(erros)}), 422

    dp_curve = predict_curve(s3, sd, hot, gd, p10, p40, p200, cbr)

    dp_n = dp_curve[-1]
    if nc in CICLOS:
        dp_n = dp_curve[CICLOS.index(nc)]
    else:
        for i in range(len(CICLOS)-1):
            if CICLOS[i] < nc < CICLOS[i+1]:
                rv = (nc-CICLOS[i])/(CICLOS[i+1]-CICLOS[i])
                dp_n = dp_curve[i] + rv*(dp_curve[i+1]-dp_curve[i])
                break

    guim_params, guim_r2 = fit_guimaraes(dp_curve, s3, sd)
    tipo = classify_behavior(dp_curve)

    return jsonify({
        "curva":     dp_curve.round(4).tolist(),
        "ciclos":    CICLOS,
        "labels":    CL_LABELS,
        "dp_n":      round(float(dp_n),4),
        "dp_10k":    round(float(dp_curve[8]),4),
        "dp_50k":    round(float(dp_curve[10]),4),
        "dp_100k":   round(float(dp_curve[11]),4),
        "dp_150k":   round(float(dp_curve[12]),4),
        "tipo":      tipo,
        "guimaraes": guim_params,
        "guim_r2":   guim_r2,
        "nome":      nome,
        "inputs":    {"hot":hot,"gd":gd,"p10":p10,"p40":p40,"p200":p200,
                      "cbr":cbr,"s3":s3,"sd":sd,"nc":nc,"razao":round((s3+sd)/s3,1)},
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
