"""Testes da API do PsiPav. Rodar com: pytest -q"""
import os

import pytest

os.environ.setdefault("PSIPAV_SENHA", "senha-de-teste")
from psipav.app import app  # noqa: E402
from psipav import engine as E  # noqa: E402

EX = os.path.join(os.path.dirname(os.path.dirname(__file__)), "psipav", "static", "exemplos")
PROPS = dict(hot=11, gd=1.97, p10=86.71, p40=67.09, p200=41.45, cbr=3, LL=29, IP=13, DR=2.64)


SENHA = os.environ["PSIPAV_SENHA"]


@pytest.fixture
def anon():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def c(anon):
    r = anon.post("/login", data={"senha": SENHA})
    assert r.status_code == 302
    return anon


def test_login_obrigatorio(anon):
    assert anon.get("/").status_code == 302
    assert anon.post("/api/triagem", json={}).status_code == 401
    assert anon.get("/health").status_code == 200
    assert anon.get("/login").status_code == 200


def test_senha_errada_e_limite(anon):
    for _ in range(5):
        r = anon.post("/login", data={"senha": "errada"}, environ_base={"REMOTE_ADDR": "9.9.9.9"})
        assert r.status_code == 401
    r = anon.post("/login", data={"senha": SENHA}, environ_base={"REMOTE_ADDR": "9.9.9.9"})
    assert r.status_code == 401 and "Muitas tentativas".encode() in r.data


def test_logout(c):
    assert c.get("/").status_code == 200
    c.get("/logout")
    assert c.get("/").status_code == 302


def test_health(c):
    assert c.get("/health").get_json()["status"] == "ok"


def test_pagina(c):
    r = c.get("/")
    assert r.status_code == 200 and b"PsiPav" in r.data


def test_triagem(c):
    d = c.post("/api/triagem", json={"props": PROPS, "s3": 80, "sd": 160, "h_cm": 20}).get_json()
    assert d["ep150"] > 0
    assert d["faixa90_150"][0] <= d["ep150"] <= d["faixa90_150"][1]
    assert all(b >= a for a, b in zip(d["ep"], d["ep"][1:])), "curva deve ser não decrescente"
    assert len(d["pares9"]) == 9 and d["guimaraes"] is not None
    assert d["atr"]["mm"] > 0


def test_triagem_par_invalido(c):
    r = c.post("/api/triagem", json={"props": PROPS, "s3": 80, "sd": 999})
    assert r.status_code == 400


def test_triagem_fora_do_dominio_avisa(c):
    p = dict(PROPS, hot=30)
    d = c.post("/api/triagem", json={"props": p, "s3": 80, "sd": 160}).get_json()
    assert any("Fora da faixa" in a for a in d["avisos"])


def _ler(c, nome):
    with open(os.path.join(EX, nome), encoding="utf-8") as f:
        return c.post("/api/importar", json={"texto": f.read()}).get_json()["linhas"]


def test_ensaio_em_andamento(c):
    L = _ler(c, "exemplo_ensaio_em_andamento.csv")
    d = c.post("/api/ensaio", json={"s3": 80, "sd": 160, "N": [l[0] for l in L],
                                    "valor": [l[1] for l in L], "unidade": "pct"}).get_json()
    p = d["previsao"]
    assert p["nivel_parada"] == 20000
    assert p["inf90"] <= p["ep150"] <= p["sup90"]
    assert abs(p["ep150"] - 0.224) / 0.224 < 0.15  # valor medido em 150.000 ciclos: 0,224%


def test_ensaio_unidade_mm(c):
    L = _ler(c, "exemplo_ensaio_em_andamento.csv")
    mm = [l[1] / 100 * 200 for l in L]
    d = c.post("/api/ensaio", json={"s3": 80, "sd": 160, "N": [l[0] for l in L], "valor": mm,
                                    "unidade": "mm", "altura_mm": 200}).get_json()
    assert d["previsao"]["ep150"] > 0


def test_analise_completa(c):
    L = _ler(c, "exemplo_ensaios_completos.csv")
    g = {}
    for s3, sd, n, v in L:
        g.setdefault((s3, sd), {"s3": s3, "sd": sd, "N": [], "valor": [], "unidade": "pct"})
        g[(s3, sd)]["N"].append(n)
        g[(s3, sd)]["valor"].append(v)
    d = c.post("/api/analise", json={"ensaios": list(g.values()), "h_cm": 20}).get_json()
    assert d["guimaraes"]["n_pares"] == 9
    assert d["guimaraes"]["r2"] > 0.7
    assert {e["classe"]["lima"] for e in d["ensaios"]} <= {"A", "AB", "B", "C"}


def test_relatorios(c):
    rel = {"titulo": "Teste ψ σ ε", "secoes": [{"titulo": "Tabela", "tipo": "tabela", "cabecalho": ["a", "b"], "linhas": [[1, 2]]},
                                              {"tipo": "texto", "texto": "εp = ψ1"}],
           "series": [{"nome": "S", "colunas": ["N", "εp"], "linhas": [[1, 0.1], [10, 0.2]], "grafico": {"titulo": "t"}}]}
    assert c.post("/api/relatorio/pdf", json=rel).data[:4] == b"%PDF"
    x = c.post("/api/relatorio/xlsx", json=rel).data
    assert x[:2] == b"PK"
    import io, openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(x))
    assert len(wb["S"]._charts) == 1


def test_ler_tabela_virgula_decimal():
    cab, d = E.ler_tabela("N;dp\n1;0,5\n10;1.234,5\n")
    assert cab == ["n", "dp"] and d == [[1.0, 0.5], [10.0, 1234.5]]


def test_classificacao_basica():
    import numpy as np
    N = np.geomspace(1, 150000, 60)
    estavel = 0.2 * (1 - np.exp(-N / 200))
    assert E.classificar(N, estavel + 1e-6)["lima"] in ("A", "AB")
    crescente = 0.5 + 2e-5 * N
    assert E.classificar(N, crescente)["lima"] == "C"
