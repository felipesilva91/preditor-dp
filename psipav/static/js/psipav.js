/* PsiPav · interface */
"use strict";

const PROPS = ["hot", "gd", "p10", "p40", "p200", "cbr", "LL", "IP", "DR"];
const ROT = { hot: "wot (%)", gd: "γd (g/cm³)", p10: "#10 (%)", p40: "#40 (%)", p200: "#200 (%)", cbr: "CBR (%)", LL: "LL (%)", IP: "IP (%)", DR: "DR" };
const CORES = ["#111827", "#1d4ed8", "#b45309", "#047857", "#7c3aed", "#be123c", "#0e7490", "#4d7c0f", "#6b7280"];
const graficos = {};
const ultimo = {};

// ── Utilidades ──────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const num = (v, d = 3) => (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const inteiro = (v) => Math.round(v).toLocaleString("pt-BR");
const cient = (v) => (v === null || v === undefined) ? "—" : Number(v).toExponential(1).replace(".", ",");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function toast(msg, tipo = "erro") {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("info", tipo === "info");
  t.classList.remove("oculto");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("oculto"), 6000);
}

async function postar(url, corpo) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
  let d;
  try { d = await r.json(); } catch { throw new Error("Resposta inválida do servidor."); }
  if (!r.ok || d.erro) throw new Error(d.erro || "Erro no servidor.");
  return d;
}

function ocupado(form, sim) {
  const b = form.querySelector(".btn-pri");
  b.disabled = sim;
  b.dataset.txt = b.dataset.txt || b.textContent;
  b.textContent = sim ? "Calculando…" : b.dataset.txt;
}

function avisosHTML(lista) {
  if (!lista || !lista.length) return "";
  return `<div class="avisos"><ul>${lista.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>`;
}

function selo(c) { return c ? `<span class="selo ${c}">${c}</span>` : "—"; }

// ── Abas ────────────────────────────────────────────────────────────────────
document.querySelectorAll(".aba").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".aba").forEach((x) => x.classList.toggle("ativa", x === b));
  document.querySelectorAll(".modulo").forEach((m) => m.classList.toggle("ativo", m.id === "mod-" + b.dataset.aba));
  if (b.dataset.aba === "metodo") carregarMetodo();
  window.scrollTo({ top: 0 });
}));

// ── Gráficos ────────────────────────────────────────────────────────────────
const fundoBranco = {
  id: "fundoBranco",
  beforeDraw(c) { const x = c.ctx; x.save(); x.globalCompositeOperation = "destination-over"; x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); x.restore(); },
};
Chart.register(fundoBranco);
Chart.defaults.font.family = "Inter, system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = "#4b5563";

function desenhar(id, cfg) {
  if (graficos[id]) graficos[id].destroy();
  graficos[id] = new Chart($(id), cfg);
  return graficos[id];
}

// Exporta o gráfico em tamanho fixo e alta resolução (sem distorção no PDF/Excel)
function imagemAlta(id, largura = 960, altura = 540) {
  const g = graficos[id];
  if (!g) return null;
  const cv = document.createElement("canvas");
  cv.width = largura; cv.height = altura;
  cv.style.width = largura + "px"; cv.style.height = altura + "px";
  const caixa = document.createElement("div");
  caixa.style.cssText = `position:fixed;left:-10000px;top:0;width:${largura}px;height:${altura}px`;
  caixa.appendChild(cv);
  document.body.appendChild(caixa);
  const fonteAnt = Chart.defaults.font.size;
  Chart.defaults.font.size = 14;
  const dados = JSON.parse(JSON.stringify(g.config.data));
  const opcoes = Object.assign({}, g.config.options, { responsive: false, maintainAspectRatio: false, animation: false, devicePixelRatio: 2.5 });
  const tmp = new Chart(cv, { type: g.config.type, data: dados, options: opcoes });
  const url = tmp.toBase64Image("image/png", 1);
  tmp.destroy();
  Chart.defaults.font.size = fonteAnt;
  caixa.remove();
  return url;
}
const imagem = (id) => imagemAlta(id);

const eixoEpLog = { type: "logarithmic", title: { display: true, text: "εp (%) · escala log" }, grid: { color: "#f1f5f9" },
  ticks: { callback: (v) => { const l = Math.log10(v); return Math.abs(l - Math.round(l)) < 1e-9 ? num(v, v < 1 ? Math.min(4, -Math.round(l)) : 0) : ""; } } };

function titulo(texto, id, opc = {}) {
  return `<div class="card-tit com-ferr"><span>${texto}</span><span class="ferr" data-g="${id}" data-log="${opc.log ? 1 : 0}"></span></div>`;
}

function montarFerramentas(raiz) {
  raiz.querySelectorAll(".ferr").forEach((f) => {
    const id = f.dataset.g;
    const btns = [];
    if (f.dataset.log === "1") btns.push(`<button type="button" data-a="log" title="Alternar escala do eixo vertical">Escala log</button>`);
    btns.push(`<button type="button" data-a="ampliar" title="Ampliar o gráfico">Ampliar</button>`);
    btns.push(`<button type="button" data-a="png" title="Baixar o gráfico em PNG de alta resolução">PNG</button>`);
    f.innerHTML = btns.join("");
    f.addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (!b || !graficos[id]) return;
      const g = graficos[id];
      if (b.dataset.a === "log") {
        const ligar = !b.classList.contains("on");
        b.classList.toggle("on", ligar);
        b.textContent = ligar ? "Escala linear" : "Escala log";
        g.config.options.scales.y = Object.assign({}, ligar ? eixoEpLog : eixoEp);
        g.update();
      } else if (b.dataset.a === "ampliar") {
        const caixa = $(id).parentElement;
        const grande = !caixa.classList.contains("grande");
        caixa.classList.toggle("grande", grande);
        b.classList.toggle("on", grande);
        b.textContent = grande ? "Reduzir" : "Ampliar";
        setTimeout(() => g.resize(), 220);
      } else if (b.dataset.a === "png") {
        const a = document.createElement("a");
        a.href = imagemAlta(id, 1600, 900);
        a.download = `PsiPav_${id}.png`;
        a.click();
      }
    });
  });
}

const pts = (xs, ys) => xs.map((x, i) => ({ x, y: ys[i] }));
const eixoN = (titulo = "Número de ciclos, N") => ({
  type: "logarithmic", min: 1, max: 150000, title: { display: true, text: titulo },
  ticks: { autoSkip: false, maxRotation: 0, callback: (v) => ([1, 10, 100, 1000, 10000, 100000].includes(v) ? inteiro(v) : "") },
  grid: { color: "#f1f5f9" },
});
const eixoEp = { title: { display: true, text: "εp (%)" }, beginAtZero: true, grid: { color: "#f1f5f9" }, ticks: { callback: (v) => num(v, 2) } };

function graficoShakedown(id, series) {
  // Lima (2020): eixo das abscissas fixo até 5%; linhas de referência em 1e-7 e 1e-5 %/ciclo
  const ds = series.map((s, i) => ({
    label: s.rotulo, data: s.taxas.map((p) => ({ x: p.ep, y: p.taxa, n: p.n })),
    showLine: true, borderColor: s.cor || CORES[i % CORES.length], backgroundColor: s.cor || CORES[i % CORES.length],
    pointRadius: 1.8, borderWidth: 1.4,
  }));
  ds.push({ label: "Acomodamento (1×10⁻⁷ %/ciclo)", data: [{ x: 0.001, y: 1e-7 }, { x: 5, y: 1e-7 }], showLine: true, borderColor: "#166534", borderDash: [6, 4], pointRadius: 0, borderWidth: 1.2 });
  ds.push({ label: "Limite C (1×10⁻⁵ %/ciclo)", data: [{ x: 0.001, y: 1e-5 }, { x: 5, y: 1e-5 }], showLine: true, borderColor: "#991b1b", borderDash: [2, 3], pointRadius: 0, borderWidth: 1.2 });
  desenhar(id, {
    type: "scatter", data: { datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } },
        tooltip: { callbacks: { label: (c) => c.raw.n ? ` N = ${inteiro(c.raw.n)} · εp = ${num(c.raw.x, 3)}% · taxa = ${cient(c.raw.y)} %/ciclo` : c.dataset.label } },
      },
      scales: {
        x: { type: "logarithmic", min: 0.001, max: 5, title: { display: true, text: "εp acumulada (%)" }, grid: { color: "#f1f5f9" },
             ticks: { autoSkip: false, maxRotation: 0, callback: (v) => ([0.001, 0.01, 0.1, 1, 5].includes(Number(v.toPrecision(3))) ? num(v, v < 0.01 ? 3 : (v < 1 ? 2 : 0)) : "") } },
        y: { type: "logarithmic", min: 1e-9, title: { display: true, text: "Taxa de acréscimo (%/ciclo)" }, ticks: { callback: (v) => (Math.log10(v) % 1 === 0 ? cient(v) : "") }, grid: { color: "#f1f5f9" } },
      },
    },
  });
}


async function baixar(fmt, rel) {
  try {
    const r = await fetch(`/api/relatorio/${fmt}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rel) });
    if (!r.ok) throw new Error("Falha ao gerar o arquivo.");
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${rel.arquivo || "PsiPav"}.${fmt}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { toast(e.message); }
}

const nomeArq = (prefixo, nome) => `${prefixo}_${(nome || "amostra").replace(/[^\p{L}\p{N}_-]+/gu, "_")}`;
const NOTA_LIMA = "Classificação de acomodamento: Lima (2020), com taxa de referência de 1×10⁻⁷ %/ciclo para A/AB, εp > 1% para AB e 1×10⁻⁵ %/ciclo para C; Werkmeister (2003)/EN 13286-7 pela diferença entre 5.000 e 3.000 ciclos. Classificação automática: confira o gráfico de acomodamento (DNIT 179/2018-IE, item 10.2).";

// ═══════════════════════════ TRIAGEM ═══════════════════════════
$("form-triagem").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const props = {};
  let ok = true;
  PROPS.forEach((k) => {
    const el = $("t-" + k);
    const v = parseFloat(String(el.value).replace(",", "."));
    el.classList.toggle("invalido", isNaN(v));
    if (isNaN(v)) ok = false;
    props[k] = v;
  });
  if (!ok) { toast("Preencha todos os campos de caracterização."); return; }
  const [s3, sd] = $("t-par").value.split("|").map(Number);
  const form = ev.target;
  ocupado(form, true);
  try {
    const d = await postar("/api/triagem", { props, s3, sd, h_cm: $("t-h").value || null });
    d.nome = $("t-nome").value.trim() || "Amostra";
    d.s3 = s3; d.sd = sd; d.props = props;
    ultimo.triagem = d;
    renderTriagem(d);
  } catch (e) { toast(e.message); }
  ocupado(form, false);
});

$("t-exemplo").addEventListener("click", async () => {
  const info = await (await fetch("/api/info")).json();
  const nomes = Object.keys(info.solos);
  const n = nomes[Math.floor(Math.random() * nomes.length)];
  PROPS.forEach((k) => { $("t-" + k).value = info.solos[n][k]; $("t-" + k).classList.remove("invalido"); });
  $("t-nome").value = `${n} (solo do banco)`;
});

function renderTriagem(d) {
  const c = d.classe, g = d.guimaraes, ref = d.solo_ref;
  const v = d.validacao;
  $("res-triagem").innerHTML = `
    <div class="barra">
      <div><h2>${esc(d.nome)}</h2><div class="meta">σ₃ = ${d.s3} kPa · σd = ${d.sd} kPa · previsão por propriedades (triagem)</div></div>
      <div class="acoes"><button class="btn btn-sec btn-peq" id="t-pdf">PDF</button><button class="btn btn-sec btn-peq" id="t-xlsx">Excel</button></div>
    </div>
    ${avisosHTML(d.avisos)}
    <div class="kpis">
      <div class="kpi"><div class="kpi-rot">εp em 150.000 ciclos</div><div class="kpi-val">${num(d.ep150)} <small>%</small></div><div class="kpi-sub">faixa 90%: ${num(d.faixa90_150[0])} a ${num(d.faixa90_150[1])}%</div></div>
      <div class="kpi"><div class="kpi-rot">Acomodamento estimado</div><div class="kpi-val">${selo(c.lima)}</div><div class="kpi-sub">Werkmeister: ${c.werkmeister || "—"} · indicativo</div></div>
      ${d.atr ? `<div class="kpi"><div class="kpi-rot">Contribuição da camada</div><div class="kpi-val">${num(d.atr.mm, 2)} <small>mm</small></div><div class="kpi-sub">h = ${d.atr.h_cm} cm · faixa 90%: ${num(d.atr.inf90, 2)} a ${num(d.atr.sup90, 2)} mm</div></div>` : ""}
      <div class="kpi"><div class="kpi-rot">Solo mais parecido do banco</div><div class="kpi-val" style="font-size:16px">${esc(ref.nome)}</div><div class="kpi-sub">semelhança ${ref.nivel} (distância ${num(ref.dist, 2)})</div></div>
    </div>
    <div class="card">
      ${titulo("Curva εp × N prevista", "g-t-curva", { log: true })}
      <div class="graf"><canvas id="g-t-curva"></canvas></div>
      <div class="nota">Faixas de 80% e 90% (a partir de 100 ciclos) calibradas por validação cruzada deixando um solo inteiro de fora (erro mediano em 150.000 ciclos: ${num(v.erro_rel_mediano * 100, 0)}%; P90: ${num(v.erro_rel_p90 * 100, 0)}%). ${ref.ensaio ? `Pontos: ensaio real de ${esc(ref.nome)} no mesmo par de tensões.` : ""}</div>
    </div>
    <div class="duas">
      <div class="card">
        <div class="card-tit">Modelo de Guimarães (2009) · 9 pares da Tabela 2</div>
        ${g ? `<div class="psis">${g.psi.map((p, i) => `<div class="psi"><b>ψ${"₁₂₃₄"[i]}</b><span>${num(p, 4)}</span></div>`).join("")}</div>
        <div class="nota">εp(%) = ψ₁·(σ₃/p₀)^ψ₂·(σd/p₀)^ψ₃·N^ψ₄, p₀ = 101,325 kPa. Regressão não linear múltipla em log(εp) sobre as 9 curvas previstas. R² = ${num(g.r2, 3)} · erro relativo médio = ${num(g.erro_rel_medio * 100, 1)}%. Parâmetros de triagem: para o MeDiNa, use os obtidos de ensaios.</div>` : "<p>Não foi possível ajustar.</p>"}
      </div>
      <div class="card">
        <div class="card-tit">εp prevista em 150.000 ciclos · 9 pares</div>
        <table class="tab"><thead><tr><th>σ₃ (kPa)</th><th>σd (kPa)</th><th>σ₁/σ₃</th><th>εp (%)</th></tr></thead><tbody>
        ${d.pares9.map((p) => `<tr${p.s3 === d.s3 && p.sd === d.sd ? ' style="font-weight:700"' : ""}><td>${p.s3}</td><td>${p.sd}</td><td>${num((p.s3 + p.sd) / p.s3, 0)}</td><td>${num(p.ep[p.ep.length - 1])}</td></tr>`).join("")}
        </tbody></table>
      </div>
    </div>
    <div class="card">
      ${titulo("Análise de acomodamento (Dawson e Wellner)", "g-t-shake")}
      <div class="graf"><canvas id="g-t-shake"></canvas></div>
      <div class="nota">${NOTA_LIMA}</div>
    </div>`;

  const corte = (arr) => arr.map((v, i) => (d.N[i] >= 100 ? v : null));
  const ds = [
    { label: "Faixa 90%", data: pts(d.N, corte(d.sup90)), borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(17,24,39,.08)", fill: "+1" },
    { label: "_i90", data: pts(d.N, corte(d.inf90)), borderWidth: 0, pointRadius: 0, fill: false },
    { label: "Faixa 80%", data: pts(d.N, corte(d.sup80)), borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(17,24,39,.12)", fill: "+1" },
    { label: "_i80", data: pts(d.N, corte(d.inf80)), borderWidth: 0, pointRadius: 0, fill: false },
    { label: "Previsão (PsiPav)", data: pts(d.N, d.ep), borderColor: "#111827", backgroundColor: "#111827", borderWidth: 2.2, pointRadius: 2.5 },
  ];
  if (d.guim_curva) ds.push({ label: "Guimarães (9 pares)", data: pts(d.N, d.guim_curva), borderColor: "#1d4ed8", borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 });
  if (ref.ensaio) ds.push({ label: `Ensaio real: ${ref.nome}`, data: pts(ref.ensaio.N, ref.ensaio.ep), showLine: false, pointStyle: "rect", pointRadius: 3, borderColor: "#b45309", backgroundColor: "rgba(180,83,9,.15)" });
  desenhar("g-t-curva", {
    type: "line", data: { datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, filter: (i) => !i.text.startsWith("_") } },
        tooltip: { filter: (i) => !i.dataset.label.startsWith("_"), callbacks: { title: (c) => `N = ${inteiro(c[0].parsed.x)}`, label: (c) => ` ${c.dataset.label}: ${num(c.parsed.y, 4)}%` } } },
      scales: { x: eixoN(), y: eixoEp },
    },
  });
  graficoShakedown("g-t-shake", [{ rotulo: "Previsão", taxas: d.taxas, cor: "#111827" }]);
  montarFerramentas($("res-triagem"));
  $("t-pdf").onclick = () => baixar("pdf", relTriagem(d));
  $("t-xlsx").onclick = () => baixar("xlsx", relTriagem(d));
}

function relTriagem(d) {
  const g = d.guimaraes;
  const secoes = [
    { titulo: "Caracterização informada", tipo: "tabela", cabecalho: PROPS.map((k) => ROT[k]), linhas: [PROPS.map((k) => d.props[k])] },
    { titulo: `Deformação permanente específica em 150.000 ciclos (σ₃ = ${d.s3} kPa, σd = ${d.sd} kPa)`, tipo: "destaque", texto: `${num(d.ep150)} %`,
      nota: `Faixa de 90%: ${num(d.faixa90_150[0])} a ${num(d.faixa90_150[1])} %. Acomodamento estimado: ${d.classe.lima} (Lima, 2020) · ${d.classe.werkmeister || "—"} (Werkmeister, 2003).` },
  ];
  if (d.atr) secoes.push({ titulo: "Contribuição da camada no afundamento", tipo: "kv", linhas: [["Espessura (cm)", d.atr.h_cm], ["δ = εp·h (mm)", num(d.atr.mm, 2)], ["Faixa de 90% (mm)", `${num(d.atr.inf90, 2)} a ${num(d.atr.sup90, 2)}`]] });
  secoes.push({ titulo: "Curva εp × N", tipo: "imagem", img: imagem("g-t-curva") });
  if (g) secoes.push({ titulo: "Modelo de Guimarães (2009) ajustado às 9 curvas previstas", tipo: "tabela", cabecalho: ["ψ1", "ψ2", "ψ3", "ψ4", "R²", "Erro rel. médio"], linhas: [[...g.psi.map((p) => num(p, 4)), num(g.r2, 3), num(g.erro_rel_medio * 100, 1) + "%"]] });
  secoes.push({ titulo: "εp prevista em 150.000 ciclos para os 9 pares da Tabela 2", tipo: "tabela", cabecalho: ["σ3 (kPa)", "σd (kPa)", "σ1/σ3", "εp (%)"], linhas: d.pares9.map((p) => [p.s3, p.sd, num((p.s3 + p.sd) / p.s3, 0), num(p.ep[p.ep.length - 1])]) });
  secoes.push({ titulo: "Análise de acomodamento", tipo: "imagem", img: imagem("g-t-shake") });
  secoes.push({ titulo: "Solo de referência do banco", tipo: "texto", texto: `${d.solo_ref.nome} (${d.solo_ref.props.aashto}), semelhança ${d.solo_ref.nivel}, distância normalizada ${num(d.solo_ref.dist, 2)}.` });
  if (d.avisos.length) secoes.push({ titulo: "Avisos", tipo: "texto", texto: d.avisos.join(" ") });
  secoes.push({ titulo: "Notas", tipo: "texto", italico: true, texto: `Previsão de triagem por aprendizado de máquina (ExtraTrees + Gradient Boosting) treinado com 105 ensaios de 15 solos. Em validação deixando cada solo de fora, o erro relativo mediano em 150.000 ciclos foi de ${num(d.validacao.erro_rel_mediano * 100, 0)}% (P90 ${num(d.validacao.erro_rel_p90 * 100, 0)}%). Não substitui o ensaio da DNIT 179/2018-IE. ${NOTA_LIMA}` });
  return {
    arquivo: nomeArq("PsiPav_triagem", d.nome), titulo: `Triagem de deformação permanente · ${d.nome}`,
    subtitulo: "PsiPav · previsão por propriedades do solo · DNIT 179/2018-IE", secoes,
    series: [
      { nome: "Curva prevista", colunas: ["N", "εp (%)", "Inf. 90%", "Sup. 90%", "Inf. 80%", "Sup. 80%"], linhas: d.N.map((n, i) => [n, d.ep[i], d.inf90[i], d.sup90[i], d.inf80[i], d.sup80[i]]),
        grafico: { titulo: `Curva εp × N prevista (σ3 = ${d.s3} / σd = ${d.sd} kPa)`, colunas: [2, 3, 4] } },
      { nome: "9 pares Tabela 2", colunas: ["N", ...d.pares9.map((p) => `${p.s3}/${p.sd}`)], linhas: d.N.map((n, i) => [n, ...d.pares9.map((p) => p.ep[i])]),
        grafico: { titulo: "εp × N prevista · 9 pares da Tabela 2" } },
    ],
  };
}

// ═══════════════════════════ IMPORTAÇÃO ═══════════════════════════
async function importarArquivo(input, destino) {
  const f = input.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("arquivo", f);
  try {
    const r = await fetch("/api/importar", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok || d.erro) throw new Error(d.erro);
    $(destino).value = d.linhas.map((l) => l.join(";")).join("\n");
    toast(`${inteiro(d.n)} linhas lidas de ${f.name}`, "info");
  } catch (e) { toast(e.message || "Não foi possível ler o arquivo."); }
  input.value = "";
}
$("e-arq").addEventListener("change", (e) => importarArquivo(e.target, "e-txt"));
$("a-arq").addEventListener("change", (e) => importarArquivo(e.target, "a-txt"));

async function lerTexto(id) {
  const texto = $(id).value;
  if (!texto.trim()) throw new Error("Envie um arquivo ou cole as leituras.");
  return await postar("/api/importar", { texto });
}

// ═══════════════════════════ ENSAIO EM ANDAMENTO ═══════════════════════════
$("form-ensaio").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  ocupado(form, true);
  try {
    const t = await lerTexto("e-txt");
    const linhas = t.linhas.filter((l) => l.length >= 2);
    const corpo = {
      s3: parseFloat($("e-s3").value), sd: parseFloat($("e-sd").value),
      altura_mm: parseFloat($("e-alt").value) || 200, unidade: $("e-un").value,
      tol_mm: parseFloat($("e-tolmm").value) || 0.1, tol_rel: parseFloat($("e-tolrel").value) || 10,
      N: linhas.map((l) => l[0]), valor: linhas.map((l) => l[1]),
    };
    const d = await postar("/api/ensaio", corpo);
    d.nome = $("e-nome").value.trim() || "Corpo de prova";
    ultimo.ensaio = d;
    renderEnsaio(d);
  } catch (e) { toast(e.message); }
  ocupado(form, false);
});

function renderEnsaio(d) {
  const p = d.previsao, c = d.classe;
  if (p.concluido) {
    $("res-ensaio").innerHTML = `${avisosHTML(d.avisos)}<div class="decisao ok"><div class="decisao-ic">✓</div><div><div class="decisao-tit">Ensaio já completo</div><div class="decisao-txt">As leituras chegam a 150.000 ciclos. Use a aba <b>Ensaios completos</b> para ajustar o modelo de Guimarães com todos os corpos de prova.</div></div></div>`;
    return;
  }
  const decisao = p.pode_parar
    ? `<div class="decisao ok"><div class="decisao-ic">✓</div><div><div class="decisao-tit">Previsão estável: o ensaio pode ser encerrado</div><div class="decisao-txt">A faixa de 90% em 150.000 ciclos é de ±${num(p.meia90_mm, 3)} mm, dentro da tolerância (${num(d.tol_mm, 2)} mm ou ${num(d.tol_rel, 0)}%). Economia estimada de ${num(p.horas_economizadas, 1)} h de equipamento a 2 Hz.</div></div></div>`
    : `<div class="decisao continuar"><div class="decisao-ic">→</div><div><div class="decisao-tit">Continuar o ensaio até ${inteiro(p.proximo_ponto)} ciclos</div><div class="decisao-txt">A faixa de 90% em 150.000 ciclos ainda é de ±${num(p.meia90_mm, 3)} mm, acima da tolerância (${num(d.tol_mm, 2)} mm ou ${num(d.tol_rel, 0)}%). Reenvie as leituras quando o ensaio chegar a ${inteiro(p.proximo_ponto)} ciclos.</div></div></div>`;
  $("res-ensaio").innerHTML = `
    <div class="barra">
      <div><h2>${esc(d.nome)}</h2><div class="meta">σ₃ = ${d.s3} kPa · σd = ${d.sd} kPa · ${inteiro(d.N.length)} leituras até ${inteiro(p.n_atual)} ciclos · modelo do nível ${inteiro(p.nivel_parada)} ciclos</div></div>
      <div class="acoes"><button class="btn btn-sec btn-peq" id="e-pdf">PDF</button><button class="btn btn-sec btn-peq" id="e-xlsx">Excel</button></div>
    </div>
    ${avisosHTML(d.avisos)}
    ${decisao}
    <div class="kpis">
      <div class="kpi"><div class="kpi-rot">Leitura atual</div><div class="kpi-val">${num(p.ep_atual)} <small>%</small></div><div class="kpi-sub">em ${inteiro(p.n_atual)} ciclos</div></div>
      <div class="kpi"><div class="kpi-rot">Previsão em 150.000</div><div class="kpi-val">${num(p.ep150)} <small>%</small></div><div class="kpi-sub">faixa 90%: ${num(p.inf90)} a ${num(p.sup90)}%</div></div>
      <div class="kpi"><div class="kpi-rot">Deslocamento previsto</div><div class="kpi-val">${num(p.delta150_mm, 2)} <small>mm</small></div><div class="kpi-sub">CP de ${num(d.altura_mm, 0)} mm · ±${num(p.meia90_mm, 2)} mm</div></div>
      <div class="kpi"><div class="kpi-rot">Acomodamento até agora</div><div class="kpi-val">${selo(c.lima)}</div><div class="kpi-sub">Werkmeister: ${c.werkmeister || "—"} · taxa ${cient(c.taxa_final)} %/ciclo</div></div>
    </div>
    <div class="card">
      ${titulo("Leituras e projeção até 150.000 ciclos", "g-e-curva", { log: true })}
      <div class="graf"><canvas id="g-e-curva"></canvas></div>
      <div class="nota">Faixa de 90% calibrada por validação deixando cada solo de fora (cobertura obtida: 88,6%). O modelo usa só as leituras do próprio ensaio e o estado de tensões, então vale para qualquer solo.</div>
    </div>
    <div class="card">
      ${titulo("Análise de acomodamento (Dawson e Wellner)", "g-e-shake")}
      <div class="graf"><canvas id="g-e-shake"></canvas></div>
      <div class="nota">${NOTA_LIMA}${c.n_acomodamento ? ` Mantida a tendência atual, a taxa de 1×10⁻⁷ %/ciclo seria atingida por volta de ${inteiro(c.n_acomodamento)} ciclos.` : ""}</div>
    </div>`;
  desenhar("g-e-curva", {
    type: "line",
    data: { datasets: [
      { label: "Faixa 90%", data: pts(p.proj_n, p.proj_sup90), borderWidth: 0, pointRadius: 0, backgroundColor: "rgba(29,78,216,.12)", fill: "+1" },
      { label: "_inf", data: pts(p.proj_n, p.proj_inf90), borderWidth: 0, pointRadius: 0, fill: false },
      { label: "Leituras", data: pts(d.N, d.ep), borderColor: "#111827", backgroundColor: "#111827", borderWidth: 1.8, pointRadius: 1.6 },
      { label: "Projeção PsiPav", data: pts(p.proj_n, p.proj_ep), borderColor: "#1d4ed8", borderDash: [6, 4], borderWidth: 2, pointRadius: 0 },
      { label: "Previsão em 150.000", data: [{ x: 150000, y: p.ep150 }], borderColor: "#1d4ed8", backgroundColor: "#1d4ed8", pointRadius: 5, showLine: false },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, filter: (i) => !i.text.startsWith("_") } },
        tooltip: { filter: (i) => !i.dataset.label.startsWith("_"), callbacks: { title: (c) => `N = ${inteiro(c[0].parsed.x)}`, label: (c) => ` ${c.dataset.label}: ${num(c.parsed.y, 4)}%` } } },
      scales: { x: eixoN(), y: eixoEp },
    },
  });
  graficoShakedown("g-e-shake", [{ rotulo: "Ensaio", taxas: d.taxas, cor: "#111827" }]);
  montarFerramentas($("res-ensaio"));
  $("e-pdf").onclick = () => baixar("pdf", relEnsaio(d));
  $("e-xlsx").onclick = () => baixar("xlsx", relEnsaio(d));
}

function relEnsaio(d) {
  const p = d.previsao, c = d.classe;
  return {
    arquivo: nomeArq("PsiPav_ensaio", d.nome), titulo: `Ensaio em andamento · ${d.nome}`,
    subtitulo: `PsiPav · σ3 = ${d.s3} kPa · σd = ${d.sd} kPa · leituras até ${inteiro(p.n_atual)} ciclos`,
    secoes: [
      { titulo: "Decisão", tipo: "texto", texto: p.pode_parar ? `Previsão estável: o ensaio pode ser encerrado (faixa de 90% de ±${num(p.meia90_mm, 3)} mm; tolerância ${num(d.tol_mm, 2)} mm ou ${num(d.tol_rel, 0)}%).` : `Continuar o ensaio até ${inteiro(p.proximo_ponto)} ciclos (faixa de 90% de ±${num(p.meia90_mm, 3)} mm; tolerância ${num(d.tol_mm, 2)} mm ou ${num(d.tol_rel, 0)}%).` },
      { titulo: "εp prevista em 150.000 ciclos", tipo: "destaque", texto: `${num(p.ep150)} %`, nota: `Faixa de 90%: ${num(p.inf90)} a ${num(p.sup90)} %. Deslocamento previsto: ${num(p.delta150_mm, 2)} mm (CP de ${num(d.altura_mm, 0)} mm).` },
      { titulo: "Resumo", tipo: "kv", linhas: [["Leitura atual", `${num(p.ep_atual)} % em ${inteiro(p.n_atual)} ciclos`], ["Nível de parada do modelo", `${inteiro(p.nivel_parada)} ciclos`], ["Acomodamento (Lima, 2020)", c.lima], ["Werkmeister (2003)", c.werkmeister || "—"], ["Taxa atual", `${cient(c.taxa_final)} %/ciclo`], ["Horas de equipamento economizadas (2 Hz)", num(p.horas_economizadas, 1)]] },
      { titulo: "Leituras e projeção", tipo: "imagem", img: imagem("g-e-curva") },
      { titulo: "Análise de acomodamento", tipo: "imagem", img: imagem("g-e-shake") },
      ...(d.avisos.length ? [{ titulo: "Avisos", tipo: "texto", texto: d.avisos.join(" ") }] : []),
      { titulo: "Notas", tipo: "texto", italico: true, texto: `Modelo de extrapolação (ExtraTrees + Gradient Boosting) treinado com 102 ensaios de 15 solos, usando só as leituras até o nível de parada e o estado de tensões. Faixa de 90% por predição conformal agrupada por solo. ${NOTA_LIMA}` },
    ],
    series: [{ nome: "Leituras", colunas: ["N", "εp (%)"], linhas: d.N.map((n, i) => [n, d.ep[i]]), grafico: { titulo: "Leituras do ensaio" } },
             { nome: "Projeção", colunas: ["N", "εp (%)", "Inf. 90%", "Sup. 90%"], linhas: p.proj_n.map((n, i) => [n, p.proj_ep[i], p.proj_inf90[i], p.proj_sup90[i]]), grafico: { titulo: "Projeção até 150.000 ciclos" } }],
  };
}

// ═══════════════════════════ ENSAIOS COMPLETOS ═══════════════════════════
$("form-analise").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  ocupado(form, true);
  try {
    const t = await lerTexto("a-txt");
    const grupos = new Map();
    t.linhas.filter((l) => l.length >= 4).forEach(([s3, sd, n, v]) => {
      const k = `${s3}|${sd}`;
      if (!grupos.has(k)) grupos.set(k, { s3, sd, N: [], valor: [], unidade: $("a-un").value });
      grupos.get(k).N.push(n); grupos.get(k).valor.push(v);
    });
    if (!grupos.size) throw new Error("Não encontrei linhas com 4 colunas (σ3; σd; N; deformação).");
    const d = await postar("/api/analise", { ensaios: [...grupos.values()], altura_mm: parseFloat($("a-alt").value) || 200, h_cm: $("a-h").value || null });
    d.nome = $("a-nome").value.trim() || "Material";
    ultimo.analise = d;
    renderAnalise(d);
  } catch (e) { toast(e.message); }
  ocupado(form, false);
});

function renderAnalise(d) {
  const g = d.guimaraes;
  const ens = [...d.ensaios].sort((a, b) => a.s3 - b.s3 || a.sd - b.sd);
  $("res-analise").innerHTML = `
    <div class="barra">
      <div><h2>${esc(d.nome)}</h2><div class="meta">${ens.length} corpos de prova · altura de referência ${num(d.altura_mm, 0)} mm</div></div>
      <div class="acoes"><button class="btn btn-sec btn-peq" id="a-pdf">PDF</button><button class="btn btn-sec btn-peq" id="a-xlsx">Excel</button></div>
    </div>
    ${avisosHTML(d.avisos)}
    ${g ? `<div class="card">
      <div class="card-tit">Modelo de Guimarães (2009) · parâmetros para o MeDiNa</div>
      <div class="psis">${g.psi.map((p, i) => `<div class="psi"><b>ψ${"₁₂₃₄"[i]}</b><span>${num(p, 4)}</span></div>`).join("")}</div>
      <div class="nota">εp(%) = ψ₁·(σ₃/p₀)^ψ₂·(σd/p₀)^ψ₃·N^ψ₄, p₀ = 101,325 kPa. Regressão não linear múltipla em log(εp) com ${g.n_pares} pares (DNIT 179/2018-IE, item 10.1); cada ensaio reamostrado em N log-espaçado para pesar igual. R² = ${num(g.r2, 3)} · erro relativo médio = ${num(g.erro_rel_medio * 100, 1)}%.</div>
    </div>` : ""}
    ${d.atr ? `<div class="kpis"><div class="kpi"><div class="kpi-rot">Contribuição da camada (pior par)</div><div class="kpi-val">${num(d.atr.mm, 2)} <small>mm</small></div><div class="kpi-sub">h = ${d.atr.h_cm} cm · par ${d.atr.par[0]}/${d.atr.par[1]} kPa</div></div></div>` : ""}
    <div class="card">
      ${titulo("Curvas εp × N · ensaios (linhas cheias) e modelo ajustado (tracejado)", "g-a-curvas", { log: true })}
      <div class="graf" style="height:400px"><canvas id="g-a-curvas"></canvas></div>
    </div>
    <div class="card">
      <div class="card-tit">Resultado por corpo de prova</div>
      <table class="tab"><thead><tr><th>σ₃</th><th>σd</th><th>σ₁/σ₃</th><th>N final</th><th>εp final (%)</th><th>Taxa final (%/ciclo)</th><th>Lima (2020)</th><th>Werkmeister</th><th>N p/ acomodar</th></tr></thead><tbody>
      ${ens.map((e) => `<tr><td>${e.s3}</td><td>${e.sd}</td><td>${num((e.s3 + e.sd) / e.s3, 0)}</td><td>${inteiro(e.classe.n_final)}</td><td>${num(e.classe.ep_final)}</td><td>${cient(e.classe.taxa_final)}</td><td>${selo(e.classe.lima)}</td><td>${selo(e.classe.werkmeister)}</td><td>${e.classe.n_acomodamento ? (e.classe.n_acomodamento > 1e7 ? "> 10⁷" : inteiro(e.classe.n_acomodamento)) : "atingido"}</td></tr>`).join("")}
      </tbody></table>
      <div class="nota">${NOTA_LIMA}</div>
    </div>
    <div class="card">
      ${titulo("Análise de acomodamento (Dawson e Wellner)", "g-a-shake")}
      <div class="graf" style="height:400px"><canvas id="g-a-shake"></canvas></div>
    </div>`;
  const ds = [];
  ens.forEach((e, i) => {
    const cor = CORES[i % CORES.length];
    ds.push({ label: `${e.s3}/${e.sd}`, data: pts(e.N, e.ep), borderColor: cor, backgroundColor: cor, borderWidth: 1.6, pointRadius: 0 });
    if (e.modelo) ds.push({ label: `_m${i}`, data: pts(d.N_modelo, e.modelo), borderColor: cor, borderDash: [5, 4], borderWidth: 1.1, pointRadius: 0 });
  });
  desenhar("g-a-curvas", {
    type: "line", data: { datasets: ds },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, filter: (i) => !i.text.startsWith("_") } },
        tooltip: { filter: (i) => !i.dataset.label.startsWith("_"), callbacks: { title: (c) => `N = ${inteiro(c[0].parsed.x)}`, label: (c) => ` σ₃/σd ${c.dataset.label}: ${num(c.parsed.y, 4)}%` } } },
      scales: { x: eixoN(), y: eixoEp },
    },
  });
  graficoShakedown("g-a-shake", ens.map((e, i) => ({ rotulo: `${e.s3}/${e.sd}`, taxas: e.taxas, cor: CORES[i % CORES.length] })));
  montarFerramentas($("res-analise"));
  $("a-pdf").onclick = () => baixar("pdf", relAnalise(d, ens));
  $("a-xlsx").onclick = () => baixar("xlsx", relAnalise(d, ens));
}

function relAnalise(d, ens) {
  const g = d.guimaraes;
  const secoes = [];
  if (g) secoes.push({ titulo: "Modelo de Guimarães (2009) · parâmetros para o MeDiNa", tipo: "tabela", cabecalho: ["ψ1", "ψ2", "ψ3", "ψ4", "R²", "Erro rel. médio", "Pares"], linhas: [[...g.psi.map((p) => num(p, 4)), num(g.r2, 3), num(g.erro_rel_medio * 100, 1) + "%", g.n_pares]] });
  if (d.atr) secoes.push({ titulo: "Contribuição da camada no afundamento (pior par)", tipo: "kv", linhas: [["Espessura (cm)", d.atr.h_cm], ["Par (kPa)", `${d.atr.par[0]}/${d.atr.par[1]}`], ["δ = εp·h (mm)", num(d.atr.mm, 2)]] });
  secoes.push({ titulo: "Curvas εp × N", tipo: "imagem", img: imagem("g-a-curvas") });
  secoes.push({ titulo: "Resultado por corpo de prova", tipo: "tabela", cabecalho: ["σ3", "σd", "N final", "εp final (%)", "Taxa final (%/ciclo)", "Lima (2020)", "Werkmeister"],
    linhas: ens.map((e) => [e.s3, e.sd, inteiro(e.classe.n_final), num(e.classe.ep_final), cient(e.classe.taxa_final), e.classe.lima, e.classe.werkmeister || "—"]) });
  secoes.push({ titulo: "Análise de acomodamento", tipo: "imagem", img: imagem("g-a-shake") });
  if (d.avisos.length) secoes.push({ titulo: "Avisos", tipo: "texto", texto: d.avisos.join(" ") });
  secoes.push({ titulo: "Notas", tipo: "texto", italico: true, texto: `Regressão não linear múltipla em log(εp), com cada ensaio reamostrado em 25 pontos log-espaçados. ${NOTA_LIMA}` });
  return {
    arquivo: nomeArq("PsiPav_ensaios", d.nome), titulo: `Análise de ensaios de deformação permanente · ${d.nome}`,
    subtitulo: `PsiPav · ${ens.length} corpos de prova · DNIT 179/2018-IE`, secoes,
    series: [
      ...(g ? [{ nome: "Modelo Guimarães", colunas: ["N", ...ens.map((e) => `${e.s3}/${e.sd}`)], linhas: d.N_modelo.map((n, i) => [n, ...ens.map((e) => e.modelo[i])]),
        grafico: { titulo: "Modelo de Guimarães ajustado · todos os pares" } }] : []),
      ...ens.map((e) => ({ nome: `${e.s3}-${e.sd}`, colunas: ["N", "εp (%)", ...(e.modelo ? [] : [])], linhas: e.N.map((n, i) => [n, e.ep[i]]),
        grafico: { titulo: `Ensaio σ3 = ${e.s3} / σd = ${e.sd} kPa` } })),
    ],
  };
}

// ═══════════════════════════ MÉTODO ═══════════════════════════
let metodoCarregado = false;
async function carregarMetodo() {
  if (metodoCarregado) return;
  try {
    const info = await (await fetch("/api/info")).json();
    const v = info.triagem.validacao_150k;
    const solos = Object.entries(info.solos);
    $("metodo-corpo").innerHTML = `
      <div class="card"><h3>Dados</h3><ul>
        <li>${inteiro(info.dados.leituras)} leituras de ${info.dados.ensaios} ensaios triaxiais de cargas repetidas (DNIT 179/2018-IE), ${info.dados.solos} solos do Ceará, até 150.000 ciclos.</li>
        <li>Propriedades: umidade ótima, γd máx, passantes #10, #40 e #200, CBR, LL, IP e densidade real.</li>
        <li>Pares de tensão da Tabela 2 da norma (σ₃ de 40, 80 e 120 kPa; σ₁/σ₃ de 2, 3 e 4).</li></ul></div>
      <div class="card"><h3>Validação</h3><ul>
        <li>Todos os modelos foram avaliados deixando <b>um solo inteiro de fora</b> do treino, que é a situação real de uso. A divisão aleatória das leituras mistura o mesmo solo no treino e no teste e superestima a precisão: no mesmo banco, o Random Forest original tem R² = 0,96 em 150.000 ciclos com divisão aleatória e R² = 0,15 com o solo de fora.</li>
        <li><b>Triagem</b> (só propriedades): erro relativo mediano de ${num(v.erro_rel_mediano * 100, 0)}% em 150.000 ciclos (P90 ${num(v.erro_rel_p90 * 100, 0)}%). Com só 15 solos, as propriedades explicam pouco da variação entre solos: use como pré-seleção.</li>
        <li><b>Ensaio em andamento</b>: erro mediano de 9% parando em 10.000 ciclos, 7% em 20.000, 6% em 30.000 e 3% em 50.000. A faixa de 90% cobriu 88,6% dos casos. Com tolerância de 0,10 mm ou 10%, o tempo total de ensaio cai cerca de 66%, com erro mediano de 0,02 mm.</li></ul></div>
      <div class="card"><h3>Como o PsiPav calcula</h3><ul>
        <li><b>Previsões</b>: média de ExtraTrees e Gradient Boosting sobre log(εp), com curva forçada a ser não decrescente em N.</li>
        <li><b>Faixas de confiança</b>: predição conformal agrupada por solo, a partir dos resíduos da validação deixando cada solo de fora.</li>
        <li><b>Guimarães (2009)</b>: εp(%) = ψ₁(σ₃/p₀)^ψ₂(σd/p₀)^ψ₃N^ψ₄, por regressão não linear múltipla em log(εp) com todos os pares (item 10.1 da norma).</li>
        <li><b>Contribuição da camada</b>: δ = εp·h (item 3.8 da norma), com o par de tensões do ensaio.</li></ul></div>
      <div class="card"><h3>Acomodamento (shakedown)</h3><ul>
        <li>Gráfico de Dawson e Wellner: εp acumulada × taxa de acréscimo, com eixo das abscissas fixo até 5% (Lima, 2020).</li>
        <li><b>Lima (2020)</b>: A quando a taxa chega a 1×10⁻⁷ %/ciclo; AB se, além disso, εp &gt; 1%; C se a taxa não desce de 1×10⁻⁵ %/ciclo; B nos demais casos.</li>
        <li><b>Werkmeister (2003) / EN 13286-7</b>: pela diferença de deformação entre 5.000 e 3.000 ciclos (A &lt; 0,045×10⁻³; C &gt; 0,4×10⁻³).</li>
        <li>A classificação automática é uma ajuda: a norma pede a avaliação do gráfico (item 10.2).</li></ul></div>
      <div class="card larga"><h3>Solos do banco</h3>
        <table class="tab"><thead><tr><th>Solo</th><th>AASHTO</th>${PROPS.map((k) => `<th>${ROT[k]}</th>`).join("")}</tr></thead><tbody>
        ${solos.map(([n, s]) => `<tr><td class="txt">${esc(n)}</td><td class="txt">${esc(s.aashto)}</td>${PROPS.map((k) => `<td>${s[k]}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div>
      <div class="card larga"><h3>Referências</h3>
        <p class="ref">DNIT. DNIT 179/2018-IE: Pavimentação – Solos – Determinação da deformação permanente – Instrução de ensaio. Rio de Janeiro: IPR, 2018 (versão com Errata 1, 2023).</p>
        <p class="ref">GUIMARÃES, A. C. R. Um método mecanístico-empírico para a previsão da deformação permanente em solos tropicais constituintes de pavimentos. Tese (Doutorado), COPPE/UFRJ, 2009.</p>
        <p class="ref">LIMA, C. D. A. Avaliação da deformação permanente de materiais de pavimentação a partir de ensaios triaxiais de cargas repetidas. Tese (Doutorado), COPPE/UFRJ, 2020.</p>
        <p class="ref">LIMA, C. D. A.; MOTTA, L. M. G.; ARAGÃO, F. T. S. Ensaios de deformação permanente: efeito do número de ciclos na interpretação do comportamento de solos e britas. Revista Matéria, v. 26, n. 3, 2021.</p>
        <p class="ref">ARAÚJO, M. J. R.; BARROSO, S. H. A.; RIBEIRO, A. J. A.; VIEIRA, F. A. F. Definition of new stopping criteria for the characterization of permanent deformation of granular materials. Transportation Geotechnics, v. 44, 101159, 2024.</p>
        <p class="ref">WERKMEISTER, S. Permanent deformation behaviour of unbound granular materials in pavement constructions. Tese (Doutorado), TU Dresden, 2003.</p>
        <p class="ref">DAWSON, A. R.; WELLNER, F. Plastic behavior of granular materials. Final Report ARC Project 933, University of Nottingham, 1999.</p></div>`;
    metodoCarregado = true;
  } catch { $("metodo-corpo").innerHTML = `<div class="vazio">Não foi possível carregar as informações.</div>`; }
}
