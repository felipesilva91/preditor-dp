# PsiPav

**Previsão e análise de deformação permanente de solos tropicais (DNIT 179/2018-IE)**

O PsiPav é um aplicativo web para laboratórios e projetistas de pavimentos. Ele reúne três ferramentas:

| Módulo | Entrada | Saída |
|---|---|---|
| **Triagem** | Caracterização do solo (wot, γd, #10, #40, #200, CBR, LL, IP, densidade real) | Curva εp × N estimada com faixas de 80% e 90%, ψ₁–ψ₄ indicativos, acomodamento estimado |
| **Ensaio em andamento** | Leituras de um corpo de prova ainda em ensaio (CSV/XLSX) | εp prevista em 150.000 ciclos com faixa de 90% e indicação de quando o ensaio pode ser encerrado |
| **Ensaios completos** | Leituras de 6 a 9 corpos de prova do mesmo material | ψ₁–ψ₄ do modelo de Guimarães para o MeDiNa, classificação de acomodamento por par, contribuição da camada no afundamento |

Os relatórios saem em PDF (gráficos em alta resolução, sem distorção) e Excel (imagens dos gráficos e gráficos nativos editáveis). Cada gráfico tem escala linear/log, modo ampliado e exportação em PNG.

O acesso é protegido por senha (sessão de 12 h, limite de 5 tentativas erradas a cada 5 min). A senha **não fica no código**: defina no servidor a variável de ambiente `PSIPAV_SENHA` (ou `PSIPAV_SENHA_HASH`, com um hash do `werkzeug`). No Render: serviço → Environment → Add Environment Variable. Para rodar localmente: `set PSIPAV_SENHA=sua_senha` (Windows) antes de iniciar o app.

## Dados e validação

- 8.983 leituras válidas (9.060 na planilha) de 105 ensaios triaxiais de cargas repetidas, 15 solos do Ceará, até 150.000 ciclos.
- Toda a validação deixa **um solo inteiro de fora** do treino, que é a situação real de uso. A divisão aleatória das leituras coloca o mesmo solo no treino e no teste e superestima a precisão: no mesmo banco, o Random Forest original tem R² = 0,96 em 150.000 ciclos com divisão aleatória e R² = 0,15 com o solo de fora.

| Módulo | Erro relativo mediano em 150.000 ciclos | P90 |
|---|---|---|
| Triagem (só propriedades) | 47% | 72% |
| Ensaio parado em 10.000 ciclos | 9% | 49% |
| Ensaio parado em 20.000 ciclos | 7% | 29% |
| Ensaio parado em 30.000 ciclos | 6% | 22% |
| Ensaio parado em 50.000 ciclos | 3% | 15% |

- As faixas de confiança vêm de **predição conformal agrupada por solo**. A faixa de 90% do módulo de ensaio cobriu 88,6% dos casos na validação.
- Com o critério padrão de encerramento (faixa de 90% ≤ 0,10 mm ou ≤ 10%), o tempo total de ensaio do banco cairia cerca de 66%, com erro mediano de 0,02 mm em corpos de prova de 200 mm.
- O módulo de triagem serve para pré-seleção de jazidas e planejamento de ensaios. Ele não substitui o ensaio da norma.

## Métodos

- **Previsões**: média de ExtraTrees e Gradient Boosting sobre log(εp); a curva é forçada a ser não decrescente em N.
- **Guimarães (2009)**: εp(%) = ψ₁(σ₃/p₀)^ψ₂(σd/p₀)^ψ₃N^ψ₄, por regressão não linear múltipla em log(εp) com todos os pares, cada ensaio reamostrado em N log-espaçado.
- **Acomodamento**: gráfico de Dawson e Wellner com eixo fixo até 5%; critério de Lima (2020) (A: taxa ≤ 1×10⁻⁷ %/ciclo; AB: idem com εp > 1%; C: taxa > 1×10⁻⁵ %/ciclo; B nos demais casos) e de Werkmeister (2003)/EN 13286-7 (diferença entre 5.000 e 3.000 ciclos).

## Estrutura

```
psipav/
├── app.py            # rotas Flask e relatórios
├── engine.py         # modelos, faixas de confiança, Guimarães, acomodamento, leitura de arquivos
├── dados/            # modelos.joblib, modelos_meta.json, banco.json (ensaios reais)
├── fontes/           # DejaVu Sans (relatórios com letras gregas)
├── static/           # css, js e arquivos de exemplo
└── templates/
treino/treinar_modelos.py   # treino e validação reproduzíveis a partir da planilha de dados brutos
tests/test_api.py           # testes automáticos
```

## Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
python -m psipav.app              # http://localhost:5000
```

Testes: `pip install -r requirements-treino.txt` e depois `pytest -q`.

Retreinar: `python treino/treinar_modelos.py caminho/Modelagem_DP_ceara.xlsx`.

## Deploy no Render

1. Envie o projeto para o GitHub.
2. No Render: **New → Blueprint**, escolha o repositório. O `render.yaml` define build, start, health check e a versão do Python (3.13).

O app usa cerca de 210 MB de RAM (1 processo com 4 threads) e roda no plano free, de 512 MB.

## Referências

- DNIT. DNIT 179/2018-IE: Pavimentação – Solos – Determinação da deformação permanente – Instrução de ensaio. IPR, 2018 (com Errata 1, 2023).
- GUIMARÃES, A. C. R. Um método mecanístico-empírico para a previsão da deformação permanente em solos tropicais constituintes de pavimentos. Tese (D.Sc.), COPPE/UFRJ, 2009.
- LIMA, C. D. A. Avaliação da deformação permanente de materiais de pavimentação a partir de ensaios triaxiais de cargas repetidas. Tese (D.Sc.), COPPE/UFRJ, 2020.
- LIMA, C. D. A.; MOTTA, L. M. G.; ARAGÃO, F. T. S. Ensaios de deformação permanente: efeito do número de ciclos na interpretação do comportamento de solos e britas. Revista Matéria, v. 26, n. 3, 2021.
- ARAÚJO, M. J. R. et al. Definition of new stopping criteria for the characterization of permanent deformation of granular materials. Transportation Geotechnics, v. 44, 101159, 2024.
- WERKMEISTER, S. Permanent deformation behaviour of unbound granular materials in pavement constructions. Tese, TU Dresden, 2003.
