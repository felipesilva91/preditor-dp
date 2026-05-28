/**
 * Preditor de Deformação Permanente — DNIT 179/2018-IE
 * JavaScript frontend — entrada livre de parâmetros do solo
 */

const state = { s3: null, sd: null, nc: 150000 };
let dpChart = null;

// ── Navegação ───────────────────────────────────────────────────────────────
function goStep(n) {
  if (n === 2 && !validarSolo()) return;
  if (n === 3) {
    if (!state.s3) { showErr("err-s3"); return; }
    if (!state.sd) { showErr("err-sd"); return; }
  }
  for (let i = 1; i <= 3; i++) {
    document.getElementById(`panel-${i}`).classList.toggle("hidden", i !== n);
    const p = document.getElementById(`prog-${i}`);
    p.classList.remove("active", "done");
    if (i === n) p.classList.add("active");
    if (i < n)  p.classList.add("done");
  }
  window.scrollTo(0, 0);
}

function showErr(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  if (msg) el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 4000);
}

// ── Validação dos campos do solo ────────────────────────────────────────────
function validarSolo() {
  const campos = ["hot","gd","p10","p40","p200","cbr"];
  let ok = true;
  campos.forEach(k => {
    const el = document.getElementById(`inp-${k}`);
    const val = parseFloat(el.value);
    if (isNaN(val) || el.value.trim() === "") {
      el.classList.add("input-error");
      ok = false;
    } else {
      el.classList.remove("input-error");
    }
  });
  if (!ok) showErr("err-solo", "Preencha todos os campos do solo antes de continuar.");
  return ok;
}

// Remove borda vermelha ao digitar
document.addEventListener("DOMContentLoaded", () => {
  ["hot","gd","p10","p40","p200","cbr"].forEach(k => {
    const el = document.getElementById(`inp-${k}`);
    if (el) el.addEventListener("input", () => el.classList.remove("input-error"));
  });
});

// ── Tensões DNIT 179 Tabela 2 ───────────────────────────────────────────────
const DNIT_T2 = {
  40:  [{sd:40,razao:"2,0"},{sd:80,razao:"3,0"},{sd:120,razao:"4,0"}],
  80:  [{sd:80,razao:"2,0"},{sd:160,razao:"3,0"},{sd:240,razao:"4,0"}],
  120: [{sd:120,razao:"2,0"},{sd:240,razao:"3,0"},{sd:360,razao:"4,0"}],
};

function selectS3(el, val) {
  state.s3 = val; state.sd = null;
  document.querySelectorAll("#grid-s3 .tbtn").forEach(b => b.classList.remove("selected"));
  el.classList.add("selected");
  const grid = document.getElementById("grid-sd");
  grid.innerHTML = "";
  DNIT_T2[val].forEach(par => {
    const btn = document.createElement("button");
    btn.className = "tbtn";
    btn.innerHTML = `${par.sd} kPa<span class="razao-hint">σ₁/σ₃ = ${par.razao}</span>`;
    btn.onclick = () => selectSd(btn, par.sd, val);
    grid.appendChild(btn);
  });
  document.getElementById("sd-label").innerHTML =
    `Tensão desvio σd (kPa) <span class="hint-text">— Tabela 2 DNIT 179</span>`;
  document.getElementById("resumo-tensao").classList.add("hidden");
}

function selectSd(el, sd, s3) {
  state.sd = sd;
  document.querySelectorAll("#grid-sd .tbtn").forEach(b => b.classList.remove("selected"));
  el.classList.add("selected");
  document.getElementById("r-s3").textContent    = s3;
  document.getElementById("r-sd").textContent    = sd;
  document.getElementById("r-razao").textContent = ((s3 + sd) / s3).toFixed(1);
  document.getElementById("resumo-tensao").classList.remove("hidden");
}

function selectNC(el, val) {
  state.nc = val;
  document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
  el.classList.add("active");
  document.getElementById("n-display").textContent = val.toLocaleString("pt-BR");
}

// ── Calcular ────────────────────────────────────────────────────────────────
function calcular() {
  const btnText = document.getElementById("btn-text");
  const spinner = document.getElementById("spinner");
  btnText.classList.add("hidden");
  spinner.classList.remove("hidden");

  const payload = {
    nome: document.getElementById("inp-nome").value.trim() || "Amostra",
    hot:  parseFloat(document.getElementById("inp-hot").value),
    gd:   parseFloat(document.getElementById("inp-gd").value),
    p10:  parseFloat(document.getElementById("inp-p10").value),
    p40:  parseFloat(document.getElementById("inp-p40").value),
    p200: parseFloat(document.getElementById("inp-p200").value),
    cbr:  parseFloat(document.getElementById("inp-cbr").value),
    s3:   state.s3,
    sd:   state.sd,
    nc:   state.nc,
  };

  fetch("/api/calcular", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(r => r.json())
    .then(data => {
      btnText.classList.remove("hidden");
      spinner.classList.add("hidden");
      if (data.error) { alert("⚠️ " + data.error); return; }
      renderResultado(data);
    })
    .catch(() => {
      btnText.classList.remove("hidden");
      spinner.classList.add("hidden");
      alert("Erro de conexão com o servidor.");
    });
}

// ── Renderizar resultado ────────────────────────────────────────────────────
function renderResultado(data) {
  lastResultData = data;
  const inp = data.inputs;

  document.getElementById("res-meta").innerHTML =
    `<strong>${data.nome}</strong> &nbsp;·&nbsp; ` +
    `σ₃ = ${inp.s3} kPa &nbsp;·&nbsp; σd = ${inp.sd} kPa &nbsp;·&nbsp; ` +
    `σ₁/σ₃ = ${inp.razao} &nbsp;·&nbsp; N = ${inp.nc.toLocaleString("pt-BR")} ciclos`;

  document.getElementById("ep-valor").textContent = data.dp_n.toFixed(3);
  document.getElementById("ep-sub").textContent =
    `εp a ${inp.nc.toLocaleString("pt-BR")} ciclos · DNIT 179/2018-IE`;

  document.getElementById("m-10k").textContent  = data.dp_10k.toFixed(3);
  document.getElementById("m-50k").textContent  = data.dp_50k.toFixed(3);
  document.getElementById("m-100k").textContent = data.dp_100k.toFixed(3);
  document.getElementById("m-150k").textContent = data.dp_150k.toFixed(3);

  renderChart(data.curva, data.labels, data.ciclos, inp.nc);
  renderTipo(data.tipo);
  renderDiag(data.tipo);
  renderGuimaraes(data.guimaraes, data.guim_r2);
  renderInputs(inp);

  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("resultado").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ── Gráfico ─────────────────────────────────────────────────────────────────
function renderChart(dp, labels, ciclos, nc) {
  if (dpChart) dpChart.destroy();
  const refIdx = ciclos.indexOf(nc);
  const ptColors = dp.map((_, i) => i === refIdx ? "#E74C3C" : "#1558A0");
  const ptSizes  = dp.map((_, i) => i === refIdx ? 7 : 4);

  dpChart = new Chart(document.getElementById("chart-dp"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "εp (%)", data: dp,
        borderColor: "#1558A0", backgroundColor: "rgba(21,88,160,0.06)",
        borderWidth: 2.5, fill: true, tension: 0.35,
        pointRadius: ptSizes, pointBackgroundColor: ptColors, pointHoverRadius: 6,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0A2540", titleColor: "#94BDE8", bodyColor: "#fff", padding: 10,
          callbacks: {
            title: ctx => `N = ${ciclos[ctx[0].dataIndex].toLocaleString("pt-BR")} ciclos`,
            label: ctx => ` εp = ${ctx.parsed.y.toFixed(4)}%`,
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Número de ciclos", font: { size: 11 }, color: "#9CA3AF" },
          ticks: { font: { size: 10 }, autoSkip: false, maxRotation: 0, color: "#6B7280" },
          grid: { color: "rgba(0,0,0,0.04)" },
        },
        y: {
          title: { display: true, text: "εp (%)", font: { size: 11 }, color: "#9CA3AF" },
          ticks: { font: { size: 10, family: "'IBM Plex Mono'" }, color: "#6B7280", callback: v => v.toFixed(3) + "%" },
          grid: { color: "rgba(0,0,0,0.04)" }, min: 0,
        },
      },
    },
  });
}

// ── Tipo de comportamento ────────────────────────────────────────────────────
const TIPOS = {
  1: { cls:"t1", icon:"I",   name:"Tipo I — Acomodamento plástico (rápido)",
       desc:"Shakedown plástico. Tendência de estabilização para poucos ciclos. Material adequado para pavimentação.",
       ref:"DNIT 179/2018-IE — seção 10.2, Tipo I" },
  2: { cls:"t2", icon:"II",  name:"Tipo II — Acomodamento plástico (tardio)",
       desc:"Shakedown plástico com alto valor de deslocamento antes do acomodamento. Requer controle de tensões.",
       ref:"DNIT 179/2018-IE — seção 10.2, Tipo II" },
  3: { cls:"t3", icon:"III", name:"Tipo III — Sem acomodamento",
       desc:"O material não se acomoda, continuando a acumular deformação com o número de ciclos.",
       ref:"DNIT 179/2018-IE — seção 10.2, Tipo III" },
  4: { cls:"t4", icon:"IV",  name:"Tipo IV — Colapso incremental",
       desc:"Ruptura a baixos números de ciclos. Risco de colapso do pavimento.",
       ref:"DNIT 179/2018-IE — seção 10.2, Tipo IV" },
};

function renderTipo(tipo) {
  const t = TIPOS[tipo];
  const card = document.getElementById("tipo-card");
  card.className = `tipo-card ${t.cls}`;
  document.getElementById("tipo-badge").textContent = t.icon;
  document.getElementById("tipo-name").textContent  = t.name;
  document.getElementById("tipo-desc").textContent  = t.desc;
  document.getElementById("tipo-ref").textContent   = t.ref;
}

// ── Diagnóstico ──────────────────────────────────────────────────────────────
const DIAG = {
  1: { base:{dot:"ok",txt:"Indicado para base"}, sub:{dot:"ok",txt:"Indicado para sub-base"}, sub2:{dot:"ok",txt:"Indicado para subleito"} },
  2: { base:{dot:"warn",txt:"Indicado com controle técnico"}, sub:{dot:"ok",txt:"Indicado para sub-base"}, sub2:{dot:"ok",txt:"Indicado para subleito"} },
  3: { base:{dot:"bad",txt:"Não indicado para base"}, sub:{dot:"warn",txt:"Com restrições — requer estudo"}, sub2:{dot:"ok",txt:"Indicado para subleito"} },
  4: { base:{dot:"bad",txt:"Não indicado"}, sub:{dot:"bad",txt:"Não indicado"}, sub2:{dot:"warn",txt:"Usar somente com reforço"} },
};

function renderDiag(tipo) {
  const d = DIAG[tipo];
  ["base","sub","sub2"].forEach(k => {
    const row = document.getElementById(`diag-${k}`);
    row.querySelector(".diag-dot").className = `diag-dot ${d[k].dot}`;
    row.querySelector(".diag-txt").textContent = d[k].txt;
  });
}

// ── Guimarães ────────────────────────────────────────────────────────────────
function renderGuimaraes(params, r2) {
  const labels = ["ψ₁", "ψ₂", "ψ₃", "ψ₄"];
  const descs  = ["fator de escala", "exp. σ₃", "exp. σd", "exp. N"];
  if (params) {
    document.getElementById("guim-res").innerHTML = params.map((v, i) => `
      <div class="guim-p-res">
        <div class="guim-p-lbl">${labels[i]}</div>
        <div class="guim-p-val">${v}</div>
        <div class="guim-p-desc">${descs[i]}</div>
      </div>`).join("");
    document.getElementById("guim-r2-row").innerHTML =
      r2 !== null
        ? `<div class="guim-r2">R² do ajuste: <strong>${r2}</strong> — qualidade do ajuste do modelo de Guimarães à curva Random Forest</div>`
        : "";
  }
}

// ── Parâmetros usados ────────────────────────────────────────────────────────
function renderInputs(inp) {
  const items = [
    { l: "Wot (%)",    v: inp.hot   },
    { l: "γd (g/cm³)", v: inp.gd    },
    { l: "#10 (%)",    v: inp.p10   },
    { l: "#40 (%)",    v: inp.p40   },
    { l: "#200 (%)",   v: inp.p200  },
    { l: "CBR (%)",    v: inp.cbr   },
    { l: "σ₃ (kPa)",   v: inp.s3    },
    { l: "σd (kPa)",   v: inp.sd    },
    { l: "σ₁/σ₃",      v: inp.razao },
    { l: "N ref.",     v: inp.nc.toLocaleString("pt-BR") },
  ];
  document.getElementById("inputs-grid").innerHTML = items.map(it => `
    <div class="inp-item">
      <div class="inp-lbl">${it.l}</div>
      <div class="inp-val">${it.v}</div>
    </div>`).join("");
}

// ── Exportar ─────────────────────────────────────────────────────────────────
let lastResultData = null;

function exportar(formato) {
  if (!lastResultData) return;
  const btn = document.getElementById(`btn-${formato}`);
  btn.disabled = true;
  btn.textContent = "Gerando…";

  const chartCanvas = document.getElementById("chart-dp");
  const chartImg = chartCanvas ? chartCanvas.toDataURL("image/png") : "";

  const payload = { ...lastResultData, chart_img: chartImg };

  fetch(`/api/exportar/${formato}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(r => {
      if (!r.ok) throw new Error("Erro ao gerar arquivo");
      return r.blob();
    })
    .then(blob => {
      const ext = formato === "pdf" ? "pdf" : "xlsx";
      const nome = (lastResultData.nome || "Amostra").replace(/\s+/g,"_").replace(/\//g,"-");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `DP_${nome}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    })
    .catch(e => alert("Erro ao exportar: " + e.message))
    .finally(() => {
      btn.disabled = false;
      btn.innerHTML = `<span class="export-icon">⬇</span> ${formato === "pdf" ? "PDF" : "Excel"}`;
    });
}

// ── Novo ensaio ──────────────────────────────────────────────────────────────
function novoEnsaio() {
  state.s3 = null; state.sd = null; state.nc = 150000;
  ["inp-nome","inp-hot","inp-gd","inp-p10","inp-p40","inp-p200","inp-cbr"].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.value = ""; el.classList.remove("input-error"); }
  });
  document.querySelectorAll(".tbtn,.chip").forEach(b => b.classList.remove("selected","active"));
  document.querySelector(".chip:last-child").classList.add("active");
  document.getElementById("grid-sd").innerHTML = "";
  document.getElementById("sd-label").innerHTML =
    `Tensão desvio σd (kPa) <span class="hint-text">(selecione σ₃ primeiro)</span>`;
  document.getElementById("resumo-tensao").classList.add("hidden");
  document.getElementById("n-display").textContent = "150.000";
  document.getElementById("resultado").classList.add("hidden");
  document.getElementById("empty-state").classList.remove("hidden");
  goStep(1);
}
