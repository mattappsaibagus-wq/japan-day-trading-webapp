/**
 * Kabutrader — 日本株デイトレード・予測ターミナル (TSE Pro)
 * Frontend Application Engine
 */

let currentSymbol = "7203.T";
let currentTimeframe = "15m";
let currentCapFilter = "all";
let currentActionFilter = "all";
let colorMode = localStorage.getItem("kabutrader_colormode") || "jp"; // "jp" (赤高/青安) or "us" (緑高/赤安)

let chartInstance = null;
let candleSeries = null;
let volumeSeries = null;
let cachedCandles = [];

// JST Market Session Status
function updateJSTMarketSession() {
  const clockEl = document.getElementById("jst-clock");
  const sessionDot = document.getElementById("session-dot");
  const sessionText = document.getElementById("session-status");
  if (!clockEl) return;

  const now = new Date();
  
  // Format to Tokyo Time
  const jstString = now.toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour12: false });
  clockEl.textContent = jstString;

  // Calculate Tokyo Stock Exchange Session
  const tokyoFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
    hour12: false
  });
  
  const parts = tokyoFormatter.formatToParts(now);
  const partMap = {};
  parts.forEach(p => partMap[p.type] = p.value);
  
  const weekday = partMap.weekday; // '月', '火', etc.
  const hour = parseInt(partMap.hour, 10);
  const minute = parseInt(partMap.minute, 10);
  const timeInMinutes = hour * 60 + minute;

  const isWeekend = (weekday === "土" || weekday === "日");

  if (isWeekend) {
    sessionText.textContent = "東証 休場日 (週末)";
    sessionDot.style.background = "#5d6879";
    sessionDot.style.boxShadow = "none";
  } else if (timeInMinutes >= 540 && timeInMinutes < 690) { // 09:00 - 11:30
    sessionText.textContent = "東証 開場中 [前場]";
    sessionDot.style.background = "var(--brand)";
    sessionDot.style.boxShadow = "0 0 10px var(--brand)";
  } else if (timeInMinutes >= 690 && timeInMinutes < 750) { // 11:30 - 12:30
    sessionText.textContent = "東証 昼休み [前引け後]";
    sessionDot.style.background = "var(--hold)";
    sessionDot.style.boxShadow = "0 0 8px var(--hold)";
  } else if (timeInMinutes >= 750 && timeInMinutes <= 930) { // 12:30 - 15:30
    sessionText.textContent = "東証 開場中 [後場]";
    sessionDot.style.background = "var(--brand)";
    sessionDot.style.boxShadow = "0 0 10px var(--brand)";
  } else {
    sessionText.textContent = "東証 取引時間外 [大引け後]";
    sessionDot.style.background = "#5d6879";
    sessionDot.style.boxShadow = "none";
  }
}
setInterval(updateJSTMarketSession, 1000);
updateJSTMarketSession();

// Toast helper
function showToast(msg) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3200);
}

// Color Mode Setup
function applyColorMode(mode) {
  colorMode = mode;
  document.body.dataset.colorMode = mode;
  localStorage.setItem("kabutrader_colormode", mode);
  
  const modeText = document.getElementById("mode-text");
  const legendBull = document.querySelector(".legend-text-bull");
  const legendBear = document.querySelector(".legend-text-bear");

  if (mode === "jp") {
    if (modeText) modeText.textContent = "東証式 (赤高/青安)";
    if (legendBull) legendBull.textContent = "陽線 (赤・上昇)";
    if (legendBear) legendBear.textContent = "陰線 (青・下落)";
  } else {
    if (modeText) modeText.textContent = "海外式 (緑高/赤安)";
    if (legendBull) legendBull.textContent = "陽線 (緑・上昇)";
    if (legendBear) legendBear.textContent = "陰線 (赤・下落)";
  }

  // Re-render chart candles if loaded
  if (cachedCandles.length > 0) {
    renderChart(cachedCandles);
  }
}

// Fetch Macro Context
async function loadMacro() {
  try {
    const res = await fetch("/api/macro");
    const data = await res.json();
    
    // Nikkei 225
    if (data.nikkei) {
      const el = document.getElementById("macro-nikkei");
      const chgClass = data.nikkei.change >= 0 ? "up" : "down";
      const arrow = data.nikkei.change > 0 ? "▲ +" : (data.nikkei.change < 0 ? "▼ " : "― ");
      el.querySelector(".macro-val").textContent = "¥" + data.nikkei.price.toLocaleString();
      el.querySelector(".macro-chg").className = `macro-chg ${chgClass}`;
      el.querySelector(".macro-chg").textContent = `${arrow}${Math.abs(data.nikkei.change_pct)}%`;
    }

    // USD/JPY
    if (data.usdjpy) {
      const el = document.getElementById("macro-usdjpy");
      const chgClass = data.usdjpy.change >= 0 ? "up" : "down";
      const arrow = data.usdjpy.change > 0 ? "▲ +" : (data.usdjpy.change < 0 ? "▼ " : "― ");
      el.querySelector(".macro-val").textContent = "¥" + data.usdjpy.price.toFixed(2);
      el.querySelector(".macro-chg").className = `macro-chg ${chgClass}`;
      el.querySelector(".macro-chg").textContent = `${arrow}${Math.abs(data.usdjpy.change_pct)}%`;
    }

    // Market Regime in Japanese
    if (data.regime) {
      const rBadge = document.querySelector(".badge-regime");
      let jpRegime = "中立・レンジ保ち合い";
      if (data.bias === "BULLISH") {
        jpRegime = "強気 (リスク選好・円安追い風)";
        rBadge.style.color = "var(--buy)";
        rBadge.style.borderColor = "var(--buy)";
      } else if (data.bias === "BEARISH") {
        jpRegime = "警戒 (リスクオフ・戻り売り優勢)";
        rBadge.style.color = "var(--sell)";
        rBadge.style.borderColor = "var(--sell)";
      } else {
        rBadge.style.color = "var(--brand-2)";
        rBadge.style.borderColor = "var(--border-strong)";
      }
      rBadge.textContent = jpRegime;
    }
  } catch (err) {
    console.error("Macro fetch error:", err);
  }
}

// Fetch Screener Data
async function loadScreener() {
  const tbody = document.getElementById("screener-tbody");

  try {
    const res = await fetch(`/api/screener?cap=${currentCapFilter}&action=${currentActionFilter}`);
    const data = await res.json();
    let stocks = data.stocks || [];

    // Client-side search query
    const searchVal = (document.getElementById("screener-search").value || "").trim().toLowerCase();
    if (searchVal) {
      stocks = stocks.filter(s => 
        s.code.includes(searchVal) || 
        s.symbol.toLowerCase().includes(searchVal) ||
        s.name.toLowerCase().includes(searchVal) ||
        s.name_jp.includes(searchVal)
      );
    }

    document.getElementById("stock-count").textContent = `${stocks.length} 銘柄`;
    tbody.innerHTML = "";

    if (stocks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="loading-state">該当する銘柄が見つかりませんでした。</td></tr>`;
      return;
    }

    stocks.forEach((s) => {
      const tr = document.createElement("tr");
      if (s.symbol === currentSymbol) tr.classList.add("selected");
      tr.dataset.symbol = s.symbol;

      const chgClass = s.change >= 0 ? "macro-chg up" : "macro-chg down";
      const arrow = s.change > 0 ? "▲ +" : (s.change < 0 ? "▼ " : "― ");
      const sigKey = s.signal.toLowerCase().replace(" ", "-");
      const rvolClass = s.rvol >= 1.4 ? "rvol-surge" : "";

      // Authentic Japanese mark + bilingual label
      const mark = s.mark || (s.signal.includes("BUY") ? "○" : (s.signal.includes("SELL") ? "▼" : "△"));
      const sigText = `${s.signal_jp || s.signal} / ${s.signal}`;

      tr.innerHTML = `
        <td class="cell-code">${s.code}</td>
        <td>
          <div class="cell-name-box">
            <span class="cell-name">${s.name_jp}</span>
            <span class="cell-en">${s.name}</span>
          </div>
        </td>
        <td><span class="cap-tag ${s.cap}">${s.cap === 'Large' ? 'プライム大型' : (s.cap === 'Mid' ? '中型主力' : 'グロース')}</span></td>
        <td class="text-right font-mono">¥${s.price.toLocaleString()}</td>
        <td class="text-right font-mono ${chgClass}">${arrow}${Math.abs(s.change_pct)}%</td>
        <td class="text-center font-mono ${rvolClass}">${s.rvol}倍</td>
        <td class="text-center font-mono">${s.rsi}</td>
        <td class="text-center">
          <span class="badge-sig ${sigKey}">
            <span>${mark}</span>
            <span>${sigText}</span>
          </span>
        </td>
        <td class="text-right font-mono" style="color: ${s.prob_up >= 50 ? 'var(--buy)' : 'var(--sell)'}; font-weight: 800;">
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
    tbody.innerHTML = `<tr><td colspan="9" class="loading-state" style="color: var(--sell);">スクリーナーデータの取得に失敗しました。</td></tr>`;
  }
}

// Select & Load Stock Details
async function selectStock(symbol) {
  currentSymbol = symbol;
  
  try {
    const res = await fetch(`/api/stock/${symbol}?interval=${currentTimeframe}`);
    const data = await res.json();
    if (!data.success) {
      showToast("銘柄読み込みエラー: " + (data.error || "不明"));
      return;
    }

    renderStockDetails(data);
    cachedCandles = data.candles || [];
    renderChart(cachedCandles);

  } catch (err) {
    console.error("Stock load error:", err);
    showToast("株価データの取得に失敗しました。");
  }
}

// Populate Details View with Japanese Trader Metrics
function renderStockDetails(data) {
  const meta = data.meta;
  const pred = data.prediction;
  const ind = pred.indicators;
  const pivots = data.pivots;

  // Header
  document.getElementById("det-code").textContent = meta.symbol;
  document.getElementById("det-name").textContent = meta.name_jp;
  document.getElementById("det-en").textContent = meta.name;
  
  const capLabel = meta.cap === 'Large' ? 'プライム大型' : (meta.cap === 'Mid' ? '中型主力' : 'グロース小型');
  document.getElementById("det-sub").textContent = `${meta.sector} // ${capLabel}`;

  const priceEl = document.getElementById("det-price");
  const chgEl = document.getElementById("det-change");
  priceEl.textContent = `¥${ind.close.toLocaleString()}`;

  // Signals with marks
  const sigTag = document.getElementById("det-signal");
  const markEl = document.getElementById("det-mark");
  const sigTextEl = document.getElementById("det-sig-text");
  
  const sigKey = pred.signal.toLowerCase().replace(" ", "-");
  sigTag.className = `signal-tag badge-sig ${sigKey}`;
  markEl.textContent = pred.mark || "―";
  sigTextEl.textContent = `${pred.signal_jp || pred.signal} / ${pred.signal}`;

  const actTag = document.getElementById("det-action");
  const jpAction = pred.action_jp || pred.action;
  actTag.textContent = `${jpAction} (${pred.action})`;
  
  if (pred.action === "BUY") {
    actTag.style.background = "var(--buy)";
    actTag.style.color = "#fff";
    actTag.style.boxShadow = "0 0 10px var(--buy-glow)";
  } else if (pred.action === "SELL") {
    actTag.style.background = "var(--sell)";
    actTag.style.color = "#fff";
    actTag.style.boxShadow = "0 0 10px var(--sell-glow)";
  } else {
    actTag.style.background = "var(--panel-strong)";
    actTag.style.color = "var(--hold)";
    actTag.style.boxShadow = "none";
  }

  document.getElementById("det-setup").textContent = pred.setup;

  // Probabilities & Confidence
  document.getElementById("det-prob-up").textContent = `${pred.probability_up}%`;
  document.getElementById("det-prob-down").textContent = `${pred.probability_down}%`;
  document.getElementById("det-confidence").textContent = `${pred.confidence}%`;
  document.getElementById("det-meter-fill").style.width = `${pred.probability_up}%`;

  // Order Execution Brackets
  document.getElementById("det-entry").textContent = `¥${pred.entry_price.toLocaleString()}`;
  document.getElementById("det-stop").textContent = `¥${pred.stop_loss.toLocaleString()}`;
  document.getElementById("det-target1").textContent = `¥${pred.target1.toLocaleString()}`;
  document.getElementById("det-target2").textContent = `¥${pred.target2.toLocaleString()}`;
  document.getElementById("det-rr").textContent = pred.risk_reward;

  // 5 Factors Matrix
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
    const pct = Math.max(6, Math.min(94, 50 + (f.val / f.max) * 44));
    bar.style.width = `${pct}%`;
    bar.style.background = f.val >= 0 ? "var(--buy)" : "var(--sell)";
    const sign = f.val > 0 ? "+" : "";
    valText.textContent = `${sign}${f.val}`;
    valText.style.color = f.val >= 0 ? "var(--buy)" : "var(--sell)";
  });

  // Floor Pivots
  document.getElementById("p-r2").textContent = `¥${pivots.R2}`;
  document.getElementById("p-r1").textContent = `¥${pivots.R1}`;
  document.getElementById("p-p").textContent = `¥${pivots.P}`;
  document.getElementById("p-s1").textContent = `¥${pivots.S1}`;
  document.getElementById("p-s2").textContent = `¥${pivots.S2}`;
}

// Chart Renderer using LightweightCharts with dynamic color mode
function renderChart(candles) {
  const container = document.getElementById("chart-container");
  container.innerHTML = "";

  if (!candles || candles.length === 0) {
    container.innerHTML = `<div class="loading-state">チャートデータがありません。</div>`;
    return;
  }

  // Determine colors based on active colorMode
  const isJP = (colorMode === "jp");
  const upColor = isJP ? "#ff5565" : "#00d084"; // Red in JP, Green in US
  const downColor = isJP ? "#4d8dff" : "#ff4d6d"; // Blue in JP, Red in US
  const volUpColor = isJP ? "rgba(255, 85, 101, 0.45)" : "rgba(0, 208, 132, 0.45)";
  const volDownColor = isJP ? "rgba(77, 141, 255, 0.45)" : "rgba(255, 77, 109, 0.45)";

  if (typeof LightweightCharts === "undefined") {
    renderCanvasChart(container, candles, upColor, downColor);
    return;
  }

  try {
    chartInstance = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 380,
      layout: {
        background: { color: "#080b12" },
        textColor: "#8e9ab0"
      },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.04)" },
        horzLines: { color: "rgba(255, 255, 255, 0.04)" }
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal
      },
      timeScale: {
        borderColor: "rgba(255, 255, 255, 0.08)",
        timeVisible: true,
        secondsVisible: false
      },
      rightPriceScale: {
        borderColor: "rgba(255, 255, 255, 0.08)"
      }
    });

    candleSeries = chartInstance.addCandlestickSeries({
      upColor: upColor,
      downColor: downColor,
      borderVisible: false,
      wickUpColor: upColor,
      wickDownColor: downColor
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
        top: 0.80,
        bottom: 0
      }
    });

    volumeSeries.setData(candles.map(c => ({
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? volUpColor : volDownColor
    })));

    chartInstance.timeScale().fitContent();

    window.addEventListener("resize", () => {
      if (chartInstance && container) {
        chartInstance.applyOptions({ width: container.clientWidth });
      }
    });

  } catch (e) {
    console.error("Lightweight chart error, using canvas fallback:", e);
    renderCanvasChart(container, candles, upColor, downColor);
  }
}

// Fallback Canvas Chart
function renderCanvasChart(container, candles, upColor, downColor) {
  const canvas = document.createElement("canvas");
  canvas.width = container.clientWidth || 600;
  canvas.height = 380;
  container.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#080b12";
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
    const col = isBull ? upColor : downColor;
    ctx.strokeStyle = col;
    ctx.fillStyle = col;

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

// Event Listeners Setup
document.addEventListener("DOMContentLoaded", () => {
  applyColorMode(colorMode);
  loadMacro();
  loadScreener();
  selectStock(currentSymbol);

  // Auto-refresh macro every 30s
  setInterval(loadMacro, 30000);

  // Color Mode Toggle Button
  document.getElementById("btn-mode-toggle").addEventListener("click", () => {
    const newMode = (colorMode === "jp") ? "us" : "jp";
    applyColorMode(newMode);
    showToast(`配色変更: ${newMode === 'jp' ? '東証式 (赤高/青安)' : '海外式 (緑高/赤安)'}`);
  });

  // Action Filters (Buy / Hold / Sell)
  document.querySelectorAll(".act-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".act-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentActionFilter = btn.dataset.action;
      loadScreener();
    });
  });

  // Market Cap Filters
  document.querySelectorAll(".cap-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cap-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentCapFilter = btn.dataset.cap;
      loadScreener();
    });
  });

  // Timeframe Buttons (15m Intraday vs 1d Daily)
  document.querySelectorAll(".tf-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentTimeframe = btn.dataset.tf;
      selectStock(currentSymbol);
    });
  });

  // Manual Refresh
  document.getElementById("btn-refresh").addEventListener("click", () => {
    showToast("東証マーケット全データを更新中...");
    loadMacro();
    loadScreener();
    selectStock(currentSymbol);
  });

  // Custom Search & Filter
  const searchInput = document.getElementById("screener-search");
  const scanBtn = document.getElementById("btn-lookup-custom");

  searchInput.addEventListener("input", () => {
    loadScreener();
  });

  const doScan = () => {
    const val = searchInput.value.trim();
    if (!val) return;
    showToast(`銘柄コード [${val}] をスキャン中...`);
    selectStock(val);
  };

  scanBtn.addEventListener("click", doScan);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doScan();
  });
});
