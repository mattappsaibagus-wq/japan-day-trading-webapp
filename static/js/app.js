/**
 * Kabutrader — 日本株デイトレード・予測ターミナル (TSE Pro)
 * Frontend Application Engine
 */

let currentSymbol = "7203.T";
let currentTimeframe = "15m";
let currentCapFilter = "all";
let currentActionFilter = "all";
let colorMode = lsGet("kabutrader_colormode", "jp"); // "jp" (赤高/青安) or "us" (緑高/赤安)

let chartInstance = null;
let candleSeries = null;
let volumeSeries = null;
let cachedCandles = [];
let cachedDetail = null;
let marketSession = { state: "closed" };
let kronosFeed = { forecasts: {} };

// Scanner probability cell: how often the signal's own direction was right, coloured by
// its edge over the base rate (not by whether P(up) is above 50%).
const EDGE_PP = 2;
function probCellHtml(s) {
  if (s.prob_up === null || s.prob_up === undefined) {
    return `<span class="prob-uncal" title="backtest.py 未実行">未検証</span>`;
  }
  if (s.prob_signal === null || s.prob_signal === undefined) {
    return `<span class="prob-noedge" title="様子見 — 上昇確率 ${s.prob_up}%">―</span>`;
  }
  const edge = s.edge_pp;
  const cls = (edge === null || edge === undefined || Math.abs(edge) < EDGE_PP) ? "prob-noedge"
    : (edge > 0 ? "prob-edge" : "prob-negedge");
  const title = (edge === null || edge === undefined) ? "基準確率なし"
    : `基準比 ${edge > 0 ? "+" : ""}${edge}pt (±${EDGE_PP}pt 未満は優位性なし)`;
  return `<span class="${cls}" title="${title}">${s.prob_signal}%</span>`;
}

// Kronos: next-hour forecasts (4 x 15m bars) from this repo's own Kronos job. Shown in the
// agent row but kept out of the score until they have been backtested.
async function loadKronos() {
  try {
    const res = await fetch("/api/kronos");
    if (res.ok) kronosFeed = await res.json();
  } catch (err) {
    console.warn("Kronos feed unavailable:", err);
  }
}

function kronosMove(k) {
  const arrow = k.direction === "up" ? "▲" : k.direction === "down" ? "▼" : "→";
  const v = k.expected_move_pct;
  return `${arrow} ${v > 0 ? "+" : ""}${v}%`;
}

function kronosColor(k) {
  return k.direction === "up" ? "var(--buy)" : k.direction === "down" ? "var(--sell)" : "#aaa";
}

function jstTime(iso) {
  return iso ? new Date(iso).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric",
    day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "--";
}

function kronosTitle(k) {
  const agree = k.path_agreement != null ? `${Math.round(k.path_agreement * 100)}%` : "--";
  const range = Array.isArray(k.range_pct) ? `${k.range_pct[0]}% 〜 ${k.range_pct[1]}%` : "--";
  return `Kronos 1時間先予測 (${jstTime(k.target_bar)} の足まで) · パス一致 ${agree} · レンジ ${range} · ` +
    `${jstTime(kronosFeed.generated_at)} JST 更新 · スコアには含めていません`;
}

function kronosChipHtml(symbol) {
  const k = (kronosFeed.forecasts || {})[symbol];
  if (!k || k.direction === "flat") return "";
  return `<span class="kronos-chip ${k.direction}" title="${esc(kronosTitle(k))}">K ${kronosMove(k)}</span>`;
}

// Badge for the agent row, tagged 1h: it forecasts the next hour and is not part of the score.
function kronosBadgeHtml(symbol) {
  const k = (kronosFeed.forecasts || {})[symbol];
  const val = k
    ? `<span style="color:${kronosColor(k)};font-weight:bold">${kronosMove(k)}</span>`
    : `<span style="color:#aaa;font-weight:bold">n/a</span>`;
  const title = k ? kronosTitle(k) : "Kronos 1時間先予測: この銘柄の予測なし";
  return `<span class="agent-badge kronos-badge" data-agent="kronos" title="${esc(title)}">KRONOS ${val}<span class="kronos-tag">1h</span></span>`;
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function yen(v) {
  return (v === null || v === undefined) ? "¥--" : "¥" + Number(v).toLocaleString();
}
function lsGet(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } }

// JST clock (client) + TSE session state (server: knows JPX holidays and auction windows)
function updateJSTClock() {
  const clockEl = document.getElementById("jst-clock");
  if (clockEl) clockEl.textContent = new Date().toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo", hour12: false });
}
setInterval(updateJSTClock, 1000);
updateJSTClock();

const SESSION_STYLE = {
  morning: "var(--brand)", afternoon: "var(--brand)", closing_auction: "var(--hold)",
  pre_open: "var(--hold)", lunch: "var(--hold)", closed: "#5d6879"
};

async function loadSession() {
  try {
    const res = await fetch("/api/session");
    const data = await res.json();
    marketSession = data;
    const dot = document.getElementById("session-dot");
    const txt = document.getElementById("session-status");
    const label = data.holiday ? `東証 休場日 (${data.holiday})` : `東証 ${data.label}`;
    txt.textContent = label;
    const col = SESSION_STYLE[data.state] || "#5d6879";
    dot.style.background = col;
    dot.style.boxShadow = (data.state === "morning" || data.state === "afternoon") ? `0 0 10px ${col}` : "none";

    const feed = document.getElementById("data-feed-badge");
    if (data.data) {
      if (data.data.realtime) {
        feed.textContent = `${data.data.provider} リアルタイム`;
        feed.className = "badge badge-feed live";
      } else {
        feed.textContent = `${data.data.provider} 約${data.data.delay_minutes}分遅延`;
        feed.className = "badge badge-feed delayed";
        feed.title = "遅延データです。発注判断には証券会社のリアルタイム板を使用してください。";
      }
    }
  } catch (err) {
    console.error("Session fetch error:", err);
  }
}

function isMarketOpen() {
  return ["morning", "afternoon", "closing_auction"].includes(marketSession.state);
}

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
  lsSet("kabutrader_colormode", mode);
  
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
    if (data.error) {
      const rBadge = document.querySelector(".badge-regime");
      rBadge.textContent = "マクロデータ取得不可";
      rBadge.style.color = "var(--faint)";
      return;
    }
    
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
      rBadge.textContent = data.stale ? `${jpRegime} (旧データ)` : jpRegime;
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
    const bars = stocks.map(st => Date.parse(st.last_bar)).filter(Number.isFinite);
    doctor.screener = { ok: res.ok, rows: stocks.length, lastBar: bars.length ? Math.max(...bars) : null };
    runDoctor();

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

    document.getElementById("stock-count").textContent = `${stocks.length} 銘柄 · ${data.interval || ""}`;
    tbody.innerHTML = "";

    if (stocks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="loading-state">該当する銘柄が見つかりませんでした。</td></tr>`;
      return;
    }

    stocks.forEach((s) => {
      const tr = document.createElement("tr");
      if (s.symbol === currentSymbol) tr.classList.add("selected");
      tr.dataset.symbol = s.symbol;
      tr.dataset.sig = s.signal.toLowerCase().replace(" ", "-");

      const chgClass = s.change >= 0 ? "macro-chg up" : "macro-chg down";
      const arrow = s.change > 0 ? "▲ +" : (s.change < 0 ? "▼ " : "― ");
      const sigKey = s.signal.toLowerCase().replace(" ", "-");
      const rvolClass = s.rvol >= 1.4 ? "rvol-surge" : "";

      // Authentic Japanese mark + bilingual label
      const mark = s.mark || (s.signal.includes("BUY") ? "○" : (s.signal.includes("SELL") ? "▼" : "△"));
      const sigText = `${s.signal_jp || s.signal}<span class="sig-en"> / ${s.signal}</span>`;

      const pct = (v) => (v === null || v === undefined) ? "--" : `${v > 0 ? "+" : ""}${v}%`;
      const probCell = probCellHtml(s);
      const limitFlag = s.near_limit ? `<span class="limit-flag" title="値幅制限に接近">⚠</span>` : "";

      tr.innerHTML = `
        <td class="cell-code">${esc(s.code)}</td>
        <td>
          <div class="cell-name-box">
            <span class="cell-name">${esc(s.name_jp)}${limitFlag}</span>
            <span class="cell-en">${esc(s.name)}</span>${kronosChipHtml(s.symbol)}
          </div>
        </td>
        <td><span class="cap-tag ${esc(s.cap)}">${s.cap === 'Large' ? 'プライム大型' : (s.cap === 'Mid' ? '中型主力' : 'グロース')}</span></td>
        <td class="text-right font-mono">¥${s.price.toLocaleString()}</td>
        <td class="text-right font-mono ${chgClass}">${arrow}${Math.abs(s.change_pct)}%</td>
        <td class="text-right font-mono">${pct(s.gap_pct)}</td>
        <td class="text-right font-mono">${pct(s.vwap_dev_pct)}</td>
        <td class="text-center font-mono ${rvolClass}">${s.rvol ?? "--"}倍</td>
        <td class="text-center font-mono">${s.rsi}</td>
        <td class="text-center">
          <span class="badge-sig ${sigKey}" title="スコア ${s.score}">
            <span>${mark}</span>
            <span>${sigText}</span>
          </span>
        </td>
        <td class="text-right font-mono">${probCell}</td>
      `;

      tr.addEventListener("click", () => {
        document.querySelectorAll(".screener-table tr").forEach(r => r.classList.remove("selected"));
        tr.classList.add("selected");
        selectStock(s.symbol);
        // On phones the detail sits below the list, so bring it into view
        if (window.matchMedia("(max-width: 900px)").matches) {
          document.getElementById("detail-panel").scrollIntoView({ behavior: "smooth" });
        }
      });

      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error("Screener fetch error:", err);
    doctor.screener = { ok: false };
    runDoctor();
    tbody.innerHTML = `<tr><td colspan="9" class="loading-state" style="color: var(--sell);">スクリーナーデータの取得に失敗しました。</td></tr>`;
  }
}

// Doctor: judges in the browser whether the data on screen is current, stale or broken,
// from the timestamps the API returns. Re-checked every minute against the clock.
const doctor = { screener: null, detail: null };
const FEED_DELAY_MIN = 20;
const KRONOS_MAX_LAG_MIN = 90;  // Kronos job runs every 30 min in TSE hours (cron can lag)

function jstParts(ms) {
  const d = new Date(ms + 9 * 3600e3);
  return { y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate(), dow: d.getUTCDay(),
    mins: d.getUTCHours() * 60 + d.getUTCMinutes() };
}

// Latest bar a fresh feed should have reached by `now` (weekdays only; JPX holidays not modelled).
function expectedLatestBar(now) {
  const p = jstParts(now);
  const weekday = p.dow >= 1 && p.dow <= 5;
  if (weekday && p.mins >= 9 * 60 && p.mins < 15 * 60 + 30) {
    return { ms: now - FEED_DELAY_MIN * 60e3, open: true };
  }
  let back = (weekday && p.mins >= 15 * 60 + 30) ? 0 : 1;
  for (;; back++) {
    const q = jstParts(now - back * 86400e3);
    if (q.dow >= 1 && q.dow <= 5) return { ms: Date.UTC(q.y, q.m, q.d, 15, 30) - 9 * 3600e3, open: false };
  }
}

function fmtAge(ms) {
  const m = Math.round(ms / 60e3);
  if (m < 60) return `${m}分前`;
  if (m < 48 * 60) return `${Math.floor(m / 60)}時間${m % 60 ? (m % 60) + "分" : ""}前`;
  return `${Math.floor(m / 1440)}日前`;
}

function fmtJstShort(ms) {
  return new Date(ms).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false }) + " JST";
}

function runDoctor() {
  const now = Date.now();
  const checks = [];
  const sc = doctor.screener;
  if (!sc) {
    checks.push({ level: "pending", name: "スクリーナー", detail: "確認中..." });
  } else if (!sc.ok || sc.rows === 0) {
    checks.push({ level: "broken", name: "スクリーナー", detail: sc.ok ? "銘柄データが0件" : "データを取得できません" });
  } else {
    checks.push({ level: "ok", name: "スクリーナー", detail: `${sc.rows} 銘柄を取得` });
    const exp = expectedLatestBar(now);
    const tol = (exp.open ? 75 : 45) * 60e3;  // lunch break / last-bar slack
    const behind = exp.ms - sc.lastBar;
    checks.push({
      level: behind > tol ? "stale" : "ok", name: "市場データ",
      detail: `最終足 ${fmtJstShort(sc.lastBar)} (${fmtAge(now - sc.lastBar)})` +
        (behind > tol ? ` · ${exp.open ? "取引時間中ですが更新が止まっています" : `${fmtJstShort(exp.ms)} の大引けまで届いていません`}` : ""),
    });
  }
  if (doctor.detail === false) {
    checks.push({ level: "broken", name: "銘柄詳細", detail: "選択した銘柄のデータを読み込めません" });
  } else if (doctor.detail) {
    checks.push({ level: "ok", name: "銘柄詳細", detail: "読み込み OK" });
  }
  const kGen = kronosFeed.generated_at ? Date.parse(kronosFeed.generated_at) : null;
  if (!kGen) {
    checks.push({ level: "warn", name: "Kronos", detail: "予測データなし (Kronos ジョブから取得できず)" });
  } else {
    const n = Object.keys(kronosFeed.forecasts || {}).length;
    const old = kGen < expectedLatestBar(now) - KRONOS_MAX_LAG_MIN * 60e3;
    checks.push({ level: old ? "warn" : "ok", name: "Kronos",
      detail: `${fmtJstShort(kGen)} 更新 (${fmtAge(now - kGen)}) · ${n} 銘柄${old ? " · 古い予測です" : ""}` });
  }

  const has = l => checks.some(c => c.level === l);
  const status = has("broken") ? "broken" : has("stale") ? "stale" : has("pending") ? "pending" : "current";
  const label = { broken: "Health BROKEN", stale: "Health STALE", pending: "Health …", current: "Health OK" }[status];
  const chip = document.getElementById("doctor-chip");
  chip.dataset.status = status;
  document.getElementById("doctor-label").textContent = label;
  const mark = { ok: "✓", stale: "!", warn: "!", broken: "✕", pending: "…" };
  document.getElementById("doctor-panel").innerHTML =
    `<div class="doctor-head">データ診断 <span>${fmtJstShort(now)} 確認 · 毎分再チェック</span></div>` +
    checks.map(c => `<div class="doctor-row ${c.level}"><span class="doctor-mark">${mark[c.level]}</span>` +
      `<span class="doctor-name">${esc(c.name)}</span><span class="doctor-detail">${esc(c.detail)}</span></div>`).join("") +
    `<div class="doctor-foot">OK = 最新の大引け (取引中は約${FEED_DELAY_MIN}分遅れ) まで反映 · STALE = それより古い · BROKEN = データ欠落。祝日は未考慮。</div>`;
}

// Select & Load Stock Details
async function selectStock(symbol) {
  currentSymbol = symbol;
  
  try {
    const res = await fetch(`/api/stock/${symbol}?interval=${currentTimeframe}`);
    const data = await res.json();
    doctor.detail = !!data.success;
    runDoctor();
    if (!data.success) {
      showToast("銘柄読み込みエラー: " + (data.error || "不明"));
      return;
    }

    cachedDetail = data;
    renderStockDetails(data);
    cachedCandles = data.candles || [];
    renderChart(cachedCandles);
    updatePositionSize();

  } catch (err) {
    console.error("Stock load error:", err);
    doctor.detail = false;
    runDoctor();
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

  // Price change vs prior session close
  const lv = pred.levels || {};
  if (lv.prev_day_close) {
    const chg = ind.close - lv.prev_day_close;
    const pctChg = (chg / lv.prev_day_close * 100).toFixed(2);
    chgEl.textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(1)} (${chg >= 0 ? "+" : ""}${pctChg}%)`;
    chgEl.className = `quote-change ${chg >= 0 ? "up" : "down"}`;
  } else {
    chgEl.textContent = "--";
  }

  // Probability: only shown when measured by backtest.py
  const calibrated = pred.probability_up !== null && pred.probability_up !== undefined;
  document.getElementById("det-prob-up").textContent = calibrated ? `${pred.probability_up}%` : "未検証";
  document.getElementById("det-prob-down").textContent = calibrated ? `${pred.probability_down}%` : "未検証";
  document.getElementById("det-meter-fill").style.width = calibrated ? `${pred.probability_up}%` : "50%";
  const hit = pred.probability_signal;
  const hitText = (hit === null || hit === undefined) ? ""
    : ` / シグナル方向の的中率 ${hit}%` + (pred.signal_edge_pp === null || pred.signal_edge_pp === undefined
      ? "" : ` (基準比 ${pred.signal_edge_pp > 0 ? "+" : ""}${pred.signal_edge_pp}pt)`);
  document.getElementById("det-prob-source").textContent = calibrated
    ? `根拠: ${pred.probability_source}${hitText}`
    : "確率は未検証です — `python backtest.py` を実行すると実績ベースの確率が表示されます";
  document.getElementById("det-confidence").textContent = `${pred.confidence}%`;
  document.getElementById("det-score").textContent = pred.score > 0 ? `+${pred.score}` : `${pred.score}`;

  // Warnings
  document.getElementById("det-warnings").innerHTML =
    (pred.warnings || []).map(w => `<li>${esc(w)}</li>`).join("");

  // Agent badges
  const agentList = Array.isArray(pred.agents) ? pred.agents : [];
  document.getElementById("agent-badge-row").innerHTML = agentList.map(a => {
    const color = a.score > 0 ? "var(--buy)" : (a.score < 0 ? "var(--sell)" : "#aaa");
    return `<span class="agent-badge" data-agent="${esc(a.agent)}">${esc(a.agent.toUpperCase())} <span style="color:${color};font-weight:bold">${a.active ? (a.score > 0 ? "+" : "") + a.score : "n/a"}</span></span>`;
  }).join(" ") + " " + kronosBadgeHtml((data.meta && data.meta.symbol) || currentSymbol);

  // Agent breakdown with reasons
  document.getElementById("agent-rows").innerHTML = agentList.map(a => {
    const pct = Math.max(4, Math.min(96, 50 + a.score / 2));
    const col = a.score >= 0 ? "var(--buy)" : "var(--sell)";
    return `<div class="factor-row agent-row ${a.active ? "" : "inactive"}">
      <span class="f-name">${esc(a.label)} ×${a.weight}<span class="agent-reasons">${esc((a.reasons || []).join(" · "))}</span></span>
      <div class="f-bar-wrap"><div class="f-bar" style="width:${pct}%;background:${col}"></div></div>
      <span class="f-val" style="color:${col}">${a.active ? (a.score > 0 ? "+" : "") + a.score : "--"}</span>
    </div>`;
  }).join("");

  // Order brackets (only for BUY / SELL)
  const br = pred.brackets;
  document.getElementById("det-entry").textContent = br ? yen(br.entry_price) : "¥--";
  document.getElementById("det-stop").textContent = br ? yen(br.stop_loss) : "¥--";
  document.getElementById("det-target1").textContent = br ? yen(br.target1) : "¥--";
  document.getElementById("det-target2").textContent = br ? yen(br.target2) : "¥--";
  document.getElementById("det-rr").textContent = br ? br.risk_reward : "1:--";

  // Intraday levels
  const rows = [
    ["limit-up", "ストップ高 (値幅上限)", lv.limit_up],
    ["", "VWAP +2σ", lv.vwap_upper2],
    ["", "VWAP +1σ", lv.vwap_upper1],
    ["vwap", "VWAP (当日)", lv.vwap],
    ["", "VWAP −1σ", lv.vwap_lower1],
    ["", "VWAP −2σ", lv.vwap_lower2],
    ["", lv.or_complete ? "寄付30分 高値 (OR)" : "寄付30分 高値 (形成中)", lv.or_high],
    ["", lv.or_complete ? "寄付30分 安値 (OR)" : "寄付30分 安値 (形成中)", lv.or_low],
    ["", "前日高値", lv.prev_day_high],
    ["", "前日安値", lv.prev_day_low],
    ["", "前日終値", lv.prev_day_close],
    ["limit-down", "ストップ安 (値幅下限)", lv.limit_down],
  ].filter(r => r[2] !== null && r[2] !== undefined);
  document.getElementById("levels-table").innerHTML = rows.map(([cls, name, v]) =>
    `<div class="pivot-row lvl ${cls}"><span class="p-lvl">${name}</span><span class="p-price">${yen(v)}</span></div>`
  ).join("");

  // Floor pivots
  ["R2", "R1", "P", "S1", "S2"].forEach(k => {
    document.getElementById(`p-${k.toLowerCase()}`).textContent = pivots ? yen(pivots[k]) : "¥--";
  });

  const lastBar = document.getElementById("last-bar");
  if (lastBar && data.last_bar) {
    const t = new Date(data.last_bar).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
    lastBar.textContent = `最終足 ${t} JST`;
  }
}

// Position sizing (fixed-fractional, 100-share units) via /api/position-size
async function updatePositionSize() {
  const out = document.getElementById("size-result");
  const account = document.getElementById("size-account").value;
  const risk = document.getElementById("size-risk").value;
  const maxcap = document.getElementById("size-maxcap").value;
  lsSet("kabutrader_size", JSON.stringify({ account, risk, maxcap }));

  const br = cachedDetail && cachedDetail.prediction && cachedDetail.prediction.brackets;
  if (!br) {
    out.innerHTML = `<span class="muted">様子見シグナル — エントリーなし</span>`;
    return;
  }
  try {
    const q = new URLSearchParams({ account, risk_pct: risk, entry: br.entry_price, stop: br.stop_loss, max_capital_pct: maxcap });
    const res = await fetch(`/api/position-size?${q}`);
    const r = await res.json();
    if (r.error) { out.textContent = r.error; return; }
    if (r.shares === 0) {
      out.innerHTML = `<strong>0株</strong> <span class="muted">— ${esc(r.limited_by)} (1株あたりリスク ¥${r.risk_per_share})</span>`;
      return;
    }
    out.innerHTML = `推奨 <strong>${r.shares.toLocaleString()}株</strong> (${r.lots}単元) · 想定損失 ¥${r.risk_jpy.toLocaleString()} / 許容 ¥${r.risk_budget.toLocaleString()} · 必要資金 ¥${r.capital_jpy.toLocaleString()} <span class="muted">(${r.limited_by === "capital" ? "資金で上限" : "リスクで上限"})</span>`;
  } catch (err) {
    out.textContent = "株数計算に失敗しました";
  }
}

// Chart Renderer using LightweightCharts with dynamic color mode
function renderChart(candles) {
  const container = document.getElementById("chart-container");
  if (chartInstance) {
    chartInstance.remove();
    chartInstance = null;
  }
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
      height: container.clientWidth < 600 ? 280 : 380,
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

    // Session VWAP: one series per session so lines don't bridge the overnight gap
    const vwapPts = (cachedDetail && cachedDetail.vwap) || [];
    const bySession = {};
    vwapPts.forEach(p => { (bySession[p.session] = bySession[p.session] || []).push({ time: p.time, value: p.value }); });
    Object.values(bySession).forEach(pts => {
      const ls = chartInstance.addLineSeries({ color: "#f5b544", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      ls.setData(pts);
    });

    const br = cachedDetail && cachedDetail.prediction && cachedDetail.prediction.brackets;
    if (br) {
      const pl = (price, color, title, style) => candleSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
      pl(br.entry_price, "#e9edf5", "Entry", 2);
      pl(br.stop_loss, "#ff545a", "Stop", 0);
      pl(br.target1, "#00e0b8", "T1", 2);
      pl(br.target2, "#00e0b8", "T2", 2);
    }

    chartInstance.timeScale().fitContent();

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
  try {
    const saved = JSON.parse(lsGet("kabutrader_size", "null"));
    if (saved) {
      document.getElementById("size-account").value = saved.account;
      document.getElementById("size-risk").value = saved.risk;
      document.getElementById("size-maxcap").value = saved.maxcap;
    }
  } catch (e) { /* ignore bad saved state */ }
  ["size-account", "size-risk", "size-maxcap"].forEach(id =>
    document.getElementById(id).addEventListener("change", updatePositionSize));

  applyColorMode(colorMode);
  loadSession();
  loadMacro();
  // Kronos forecasts decorate the scanner and detail, so load them first
  loadKronos().then(() => {
    loadScreener();
    selectStock(currentSymbol);
  });

  // Phones: show a "back to list" button while the stock detail is on screen
  const backBtn = document.getElementById("back-to-list");
  const screenerPanel = document.querySelector(".screener-panel");
  backBtn.addEventListener("click", () => screenerPanel.scrollIntoView({ behavior: "smooth" }));
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => backBtn.classList.toggle("show", e.isIntersecting))
      .observe(document.getElementById("detail-panel"));
  }

  window.addEventListener("resize", () => {
    const container = document.getElementById("chart-container");
    if (chartInstance && container) chartInstance.applyOptions({ width: container.clientWidth });
  });

  const doctorChip = document.getElementById("doctor-chip");
  const toggleDoctor = () => document.getElementById("doctor-panel").classList.toggle("open");
  doctorChip.addEventListener("click", toggleDoctor);
  doctorChip.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") toggleDoctor(); });
  setInterval(runDoctor, 60000);

  setInterval(loadSession, 30000);
  setInterval(loadMacro, 60000);
  // While the market is open, refresh the scanner and the selected stock every minute
  setInterval(() => {
    if (!isMarketOpen()) return;
    loadScreener();
    selectStock(currentSymbol);
  }, 60000);

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

  // Timeframe Buttons (5m / 15m intraday, 1d swing context)
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
