# Preditor de Deformação Permanente — DNIT 179/2018-IE

App web em Python/Flask para previsão de deformação permanente de solos tropicais cearenses,
baseado em modelo Random Forest treinado com 9.024 ensaios triaxiais de 15 solos do Ceará.

---

## Estrutura do projeto

```
preditor_dp/
├── app.py                  # Servidor Flask (rotas e API)
├── requirements.txt        # Dependências Python
├── Procfile                # Para deploy no Heroku/Railway
├── README.md               # Este arquivo
├── data/
│   └── app_data.json       # Banco de dados (solos, curvas, Guimarães)
├── templates/
│   └── index.html          # Template principal (Jinja2)
└── static/
    ├── css/
    │   └── style.css       # Estilos completos
    └── js/
        └── app.js          # Lógica frontend (JavaScript)
```

---

## Rodar localmente (VS Code)

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Rodar o servidor

```bash
python app.py
```

### 3. Acessar

Abra o navegador em: http://localhost:5000

---

## Deploy na internet

### Opção 1 — Railway (recomendado, gratuito)

1. Crie conta em https://railway.app
2. Crie novo projeto → "Deploy from GitHub"
3. Faça upload ou conecte o repositório
4. Railway detecta o `Procfile` automaticamente
5. Deploy feito! URL gerada automaticamente.

### Opção 2 — Render (gratuito)

1. Crie conta em https://render.com
2. New → Web Service
3. Conecte o repositório GitHub
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `gunicorn app:app`
6. Deploy!

### Opção 3 — Heroku

```bash
heroku create nome-do-app
git push heroku main
```

---

## API do app

O app expõe três endpoints REST:

### GET /api/solos
Retorna todos os solos com propriedades, classificação AASHTO e parâmetros de Guimarães.

### GET /api/tensoes/<int:s3>
Retorna os pares de tensão disponíveis para um dado sigma3 (40, 80 ou 120 kPa),
conforme Tabela 2 da DNIT 179/2018-IE.

**Exemplo:** `GET /api/tensoes/40`
```json
[
  {"sd": 40, "razao": "2,0"},
  {"sd": 80, "razao": "3,0"},
  {"sd": 120, "razao": "4,0"}
]
```

### POST /api/calcular
Calcula a curva de deformação permanente e o diagnóstico.

**Body JSON:**
```json
{
  "solo": "Aracati",
  "s3": 40,
  "sd": 80,
  "nc": 150000
}
```

**Retorno:**
```json
{
  "curva":      [0.077, 0.112, ...],
  "ciclos":     [1, 10, 50, ...],
  "labels":     ["1", "10", "50", ...],
  "dp_n":       0.4482,
  "dp_10k":     0.3514,
  "dp_50k":     0.3998,
  "dp_100k":    0.4311,
  "dp_150k":    0.4482,
  "tipo":       2,
  "guimaraes":  [0.1492, 0.0, 3.3647, 0.0539],
  "props":      {"hot": 10.0, "gd": 1.79, ...},
  "aashto":     "A-3",
  "razao":      3.0
}
```

---

## Norma de referência

DNIT 179/2018-IE — Pavimentação – Solos – Determinação da deformação permanente –
Instrução de ensaio. Instituto de Pesquisas Rodoviárias, DNIT, 2018
(versão corrigida 20/04/2023).

Modelo matemático: GUIMARÃES, A. C. R. Um Método Mecanístico-Empírico para a
Previsão da Deformação Permanente em Solos Tropicais. COPPE/UFRJ, 2009.
