/**
 * Kabutrader — Japan Day Trading & Predictive Terminal
 * Frontend Application Engine
 */

let currentSymbol = "7203.T";
let currentTimeframe = "15m";
let currentCapFilter = "all";
let chartInstance = null;
let candleSeries = null;
let volumeSeries = null;

// Clock & Session Status
function updateJSTClock() {
  const clockEl = document.getElementById("jst-clock");
  if (!clockEl) return;
  const now = new Date();
  
  // Format to Tokyo Time (Asia/Tokyo)
  const jstString = now.toLocaleTimeString("en-GB", { timeZone: "Asia/Tokyo" });
  clockEl.textContent = jstString;
}
setInterval(updateJSTClock, 1000);
updateJSTClock();

// Toast helper
function showToast(msg) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3000);
}

// Fetch Macro Context
async function loadMacro() {
  try {
    const res = await fetch("/api/macro");
    const data = await res.json();
    
    // Nikkei
    if (data.nikkei) {
      const el = document.getElementById("macro-nikkei");
      const chgClass = data.nikkei.change >= 0 ? "up" : "down";
      const sign = data.nikkei.change >= 0 ? "+" : "";
      el.querySelector(".macro-val").textContent = "¥" + data.nikkei.price.toLocaleString();
      el.querySelector(".macro-chg").className = `macro-chg ${chgClass}`;
      el.querySelector(".macro-chg").textContent = `${sign}${data.nikkei.change_pct}%`;
    }

    // USD/JPY
    if (data.usdjpy) {
      const el = document.getElementById("macro-usdjpy");
      const chgClass = data.usdjpy.change >= 0 ? "up" : "down";
      const sign = data.usdjpy.change >= 0 ? "+" : "";
      el.querySelector(".macro-val").textContent = data.usdjpy.price.toFixed(2);
      el.querySelector(".macro-chg").className = `macro-chg ${chgClass}`;
      el.querySelector(".macro-chg").textContent = `${sign}${data.usdjpy.change_pct}%`;
    }

    // Regime
    if (data.regime) {
      const rBadge = document.querySelector(".badge-regime");
      rBadge.textContent = data.regime.toUpperCase();
      if (data.bias === "BULLISH") {
        rBadge.style.color = "var(--bull)";
        rBadge.style.borderColor = "var(--bull)";
      } else if (data.bias === "BEARISH") {
        rBadge.style.color = "var(--bear)";
        rBadge.style.borderColor = "var(--bear)";
      }
    }
  } catch (err) {
    console.error("Macro fetch error:", err);
  }
}

// Fetch Screener Data
async function loadScreener(cap = currentCapFilter) {
  const tbody = document.getElementById("screener-tbody");
  currentCapFilter = cap;

  try {
    const res = await fetch(`/api/screener?cap=${cap}`);
    const data = await res.json();
    const stocks = data.stocks || [];

    document.getElementById("stock-count").textContent = stocks.length;
    tbody.innerHTML = "";

    if (stocks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="loading-state">No stocks matched.</td></tr>`;
      return;
    }

    stocks.forEach((s) => {
      const tr = document.createElement("tr");
      if (s.symbol === currentSymbol) tr.classList.add("selected");
      tr.dataset.symbol = s.symbol;

      const chgClass = s.change >= 0 ? "macro-chg up" : "macro-chg down";
      const sign = s.change >= 0 ? "+" : "";
      const sigClass = s.signal.toLowerCase().replace(" ", "-");
      const rvolClass = s.rvol >= 1.5 ? "rvol-high" : "";

      tr.innerHTML = `
        <td class="cell-code">${s.code}</td>
        <td>
          <div class="cell-name-box">
            <span class="cell-name">${s.name}</span>
            <span class="cell-jp">${s.name_jp}</span>
          </div>
        </td>
        <td><span class="cap-tag ${s.cap}">${s.cap}</span></td>
        <td class="text-right font-mono">¥${s.price.toLocaleString()}</td>
        <td class="text-right font-mono ${chgClass}">${sign}${s.change_pct}%</td>
        <td class="text-center font-mono ${rvolClass}">${s.rvol}x</td>
        <td class="text-center font-mono">${s.rsi}</td>
        <td class="text-center"><span class="badge-sig ${sigClass}">${s.signal}</span></td>
        <td class="text-right font-mono" style="color: ${s.prob_up >= 50 ? 'var(--bull)' : 'var(--bear)'}; font-weight: 700;">
          ${s.prob_up}%
        </td>
      `;

      tr.addEventListener("click", () => {
        document.querySelectorAll(".screener-table tr").forEach(r => r.classList.remove("selected"));
        tr.classList.add("selected");
        selectStock(s.symbol);
      });

      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error("Screener fetch error:", err);
    tbody.innerHTML = `<tr><td colspan="9" class="loading-state" style="color: var(--bear);">Error loading live screener data.</td></tr>`;
  }
}

// Select & Load Stock Details
async function selectStock(symbol) {
  currentSymbol = symbol;
  
  try {
    const res = await fetch(`/api/stock/${symbol}?interval=${currentTimeframe}`);
    const data = await res.json();
    if (!data.success) {
      showToast("Error loading stock: " + (data.error || "Unknown"));
      return;
    }

    renderStockDetails(data);
    renderChart(data.candles);

  } catch (err) {
    console.error("Stock load error:", err);
    showToast("Failed to fetch stock telemetry.");
  }
}

// Populate Details View
function renderStockDetails(data) {
  const meta = data.meta;
  const pred = data.prediction;
  const ind = pred.indicators;
  const pivots = data.pivots;

  // Header
  document.getElementById("det-code").textContent = meta.symbol;
  document.getElementById("det-name").textContent = meta.name;
  document.getElementById("det-sub").textContent = `${meta.name_jp} // ${meta.sector} // ${meta.cap} Cap`;

  const priceEl = document.getElementById("det-price");
  const chgEl = document.getElementById("det-change");
  priceEl.textContent = `¥${ind.close.toLocaleString()}`;

  // Prediction Signals
  const sigTag = document.getElementById("det-signal");
  sigTag.textContent = pred.signal;
  sigTag.className = `signal-tag ${pred.signal.toLowerCase().replace(" ", "-")}`;

  const actTag = document.getElementById("det-action");
  actTag.textContent = `ACTION: ${pred.action}`;
  if (pred.action === "LONG") {
    actTag.style.background = "var(--bull)";
    actTag.style.color = "#000";
  } else if (pred.action === "SHORT") {
    actTag.style.background = "var(--bear)";
    actTag.style.color = "#fff";
  } else {
    actTag.style.background = "#243049";
    actTag.style.color = "#fff";
  }

  document.getElementById("det-setup").textContent = pred.setup;

  // Probabilities
  document.getElementById("det-prob-up").textContent = `${pred.probability_up}%`;
  document.getElementById("det-prob-down").textContent = `${pred.probability_down}%`;
  document.getElementById("det-meter-fill").style.width = `${pred.probability_up}%`;

  // Order Brackets
  document.getElementById("det-entry").textContent = `¥${pred.entry_price.toLocaleString()}`;
  document.getElementById("det-stop").textContent = `¥${pred.stop_loss.toLocaleString()}`;
  document.getElementById("det-target1").textContent = `¥${pred.target1.toLocaleString()}`;
  document.getElementById("det-target2").textContent = `¥${pred.target2.toLocaleString()}`;
  document.getElementById("det-rr").textContent = pred.risk_reward;

  // Factors Matrix (mapping -30..+30 to 0..100% width)
  const factorMap = [
    { id: "f-trend", val: pred.factors.trend, max: 30 },
    { id: "f-momentum", val: pred.factors.momentum, max: 25 },
    { id: "f-volatility", val: pred.factors.volatility, max: 20 },
    { id: "f-volume", val: pred.factors.volume, max: 15 },
    { id: "f-macro", val: pred.factors.macro, max: 10 }
  ];

  factorMap.forEach(f => {
    const bar = document.getElementById(f.id);
    const valText = document.getElementById(`${f.id}-val`);
    const pct = Math.max(5, Math.min(95, 50 + (f.val / f.max) * 45));
    bar.style.width = `${pct}%`;
    bar.style.background = f.val >= 0 ? "var(--bull)" : "var(--bear)";
    const sign = f.val > 0 ? "+" : "";
    valText.textContent = `${sign}${f.val}`;
    valText.style.color = f.val >= 0 ? "var(--bull)" : "var(--bear)";
  });

  // Pivots
  document.getElementById("p-r2").textContent = `¥${pivots.R2}`;
  document.getElementById("p-r1").textContent = `¥${pivots.R1}`;
  document.getElementById("p-p").textContent = `¥${pivots.P}`;
  document.getElementById("p-s1").textContent = `¥${pivots.S1}`;
  document.getElementById("p-s2").textContent = `¥${pivots.S2}`;
}

// Chart Renderer using LightweightCharts with fallback
function renderChart(candles) {
  const container = document.getElementById("chart-container");
  container.innerHTML = "";

  if (!candles || candles.length === 0) {
    container.innerHTML = `<div class="loading-state">No candle data available.</div>`;
    return;
  }

  if (typeof LightweightCharts === "undefined") {
    // Canvas fallback if CDN blocked
    renderCanvasChart(container, candles);
    return;
  }

  try {
    chartInstance = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 380,
      layout: {
        background: { color: "#0d111a" },
        textColor: "#8b9bb4"
      },
      grid: {
        vertLines: { color: "#161c2b" },
        horzLines: { color: "#161c2b" }
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal
      },
      timeScale: {
        borderColor: "#232d44",
        timeVisible: true,
        secondsVisible: false
      },
      rightPriceScale: {
        borderColor: "#232d44"
      }
    });

    candleSeries = chartInstance.addCandlestickSeries({
      upColor: "#00d084",
      downColor: "#ff4d6d",
      borderVisible: false,
      wickUpColor: "#00d084",
      wickDownColor: "#ff4d6d"
    });

    candleSeries.setData(candles.map(c => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close
    })));

    volumeSeries = chartInstance.addHistogramSeries({
      color: "#26a69a",
      priceFormat: { type: "volume" },
      priceScaleId: "",
      scaleMargins: {
        top: 0.82,
        bottom: 0
      }
    });

    volumeSeries.setData(candles.map(c => ({
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? "rgba(0, 208, 132, 0.4)" : "rgba(255, 77, 109, 0.4)"
    })));

    chartInstance.timeScale().fitContent();

    window.addEventListener("resize", () => {
      if (chartInstance && container) {
        chartInstance.applyOptions({ width: container.clientWidth });
      }
    });

  } catch (e) {
    console.error("Lightweight chart error, using canvas fallback:", e);
    renderCanvasChart(container, candles);
  }
}

// Fallback Canvas Chart
function renderCanvasChart(container, candles) {
  const canvas = document.createElement("canvas");
  canvas.width = container.clientWidth || 600;
  canvas.height = 380;
  container.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#0d111a";
  ctx.fillRect(0, 0, w, h);

  const maxPrice = Math.max(...candles.map(c => c.high));
  const minPrice = Math.min(...candles.map(c => c.low));
  const range = maxPrice - minPrice || 1;

  const barWidth = Math.max(2, (w / candles.length) - 2);

  candles.forEach((c, idx) => {
    const x = idx * (barWidth + 2) + 10;
    const yOpen = h - 20 - ((c.open - minPrice) / range) * (h - 40);
    const yClose = h - 20 - ((c.close - minPrice) / range) * (h - 40);
    const yHigh = h - 20 - ((c.high - minPrice) / range) * (h - 40);
    const yLow = h - 20 - ((c.low - minPrice) / range) * (h - 40);

    const isBull = c.close >= c.open;
    ctx.strokeStyle = isBull ? "#00d084" : "#ff4d6d";
    ctx.fillStyle = isBull ? "#00d084" : "#ff4d6d";

    // Wick
    ctx.beginPath();
    ctx.moveTo(x + barWidth / 2, yHigh);
    ctx.lineTo(x + barWidth / 2, yLow);
    ctx.stroke();

    // Body
    const top = Math.min(yOpen, yClose);
    const height = Math.max(2, Math.abs(yClose - yOpen));
    ctx.fillRect(x, top, barWidth, height);
  });
}

// Setup Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  loadMacro();
  loadScreener("all");
  selectStock(currentSymbol);

  // Auto-refresh macro every 30s
  setInterval(loadMacro, 30000);

  // Cap Filter Buttons
  document.querySelectorAll(".cap-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cap-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const cap = btn.dataset.cap;
      loadScreener(cap);
    });
  });

  // Timeframe Buttons
  document.querySelectorAll(".tf-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentTimeframe = btn.dataset.tf;
      selectStock(currentSymbol);
    });
  });

  // Refresh Button
  document.getElementById("btn-refresh").addEventListener("click", () => {
    showToast("Refreshing live Japan market data...");
    loadMacro();
    loadScreener(currentCapFilter);
    selectStock(currentSymbol);
  });

  // Custom Lookup
  const searchInput = document.getElementById("screener-search");
  const scanBtn = document.getElementById("btn-lookup-custom");

  const doScan = () => {
    const val = searchInput.value.trim();
    if (!val) return;
    showToast(`Scanning ticker ${val}...`);
    selectStock(val);
  };

  scanBtn.addEventListener("click", doScan);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doScan();
  });
});
