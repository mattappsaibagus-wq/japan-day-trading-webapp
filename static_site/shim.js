/**
 * Static-snapshot mode: answers the app's /api/* calls from JSON files written by
 * static_site/build_static.py, so the site runs on plain static hosting.
 * Loaded before app.js; app.js itself is unchanged.
 */
(function () {
  const realFetch = window.fetch.bind(window);
  const LOT = 100;
  let snapshotP = null;

  function snapshot() {
    if (!snapshotP) snapshotP = realFetch("/snapshot/snapshot.json").then(r => r.json());
    return snapshotP;
  }

  function reply(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }

  function fmtJst(iso) {
    if (!iso) return "--";
    return new Date(iso).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric",
      hour: "2-digit", minute: "2-digit", hour12: false });
  }

  // Port of market_rules.position_size (fixed-fractional, 100-share units)
  function positionSize(account, riskPct, entry, stop, maxCapPct) {
    const rps = Math.abs(entry - stop);
    if (account <= 0 || riskPct <= 0 || entry <= 0 || rps <= 0) {
      return { shares: 0, lots: 0, risk_budget: 0, risk_jpy: 0, capital_jpy: 0,
        risk_per_share: Math.round(rps * 10) / 10, limited_by: "invalid input" };
    }
    const budget = account * riskPct / 100;
    const byRisk = Math.floor(budget / (rps * LOT));
    const byCap = Math.floor(account * maxCapPct / 100 / (entry * LOT));
    const lots = Math.max(0, Math.min(byRisk, byCap));
    let limited = byRisk <= byCap ? "risk" : "capital";
    if (lots === 0) limited = byRisk === 0 ? "1 unit exceeds risk budget" : "insufficient capital";
    const shares = lots * LOT;
    return { shares, lots, risk_budget: Math.round(budget), risk_jpy: Math.round(shares * rps),
      capital_jpy: Math.round(shares * entry), risk_per_share: Math.round(rps * 10) / 10, limited_by: limited };
  }

  async function handle(url) {
    const u = new URL(url, location.origin);
    const p = u.pathname, q = u.searchParams;
    if (p === "/api/session") {
      const s = await snapshot();
      return reply({ state: "closed", label: `スナップショット ${fmtJst(s.last_bar)} 時点`,
        data: { provider: "Yahoo", realtime: false, delay_minutes: 20 } });
    }
    if (p === "/api/kronos") return realFetch("/snapshot/kronos.json");
    if (p === "/api/macro") return reply((await snapshot()).macro);
    if (p === "/api/screener") {
      const sc = (await snapshot()).screener;
      const cap = (q.get("cap") || "all").toLowerCase();
      const act = (q.get("action") || "all").toUpperCase();
      let rows = sc.stocks;
      if (cap !== "all") rows = rows.filter(d => d.cap.toLowerCase() === cap);
      if (act !== "ALL") rows = rows.filter(d => d.action_en === act);
      return reply(Object.assign({}, sc, { stocks: rows, count: rows.length }));
    }
    if (p.startsWith("/api/stock/")) {
      let sym = decodeURIComponent(p.slice("/api/stock/".length)).trim().toUpperCase();
      if (!sym.endsWith(".T")) sym += ".T";
      const iv = q.get("interval") || "15m";
      const r = await realFetch(`/snapshot/stock/${sym}_${iv}.json`);
      if (r.ok) return r;
      return reply({ success: false, error: "静的版は収録銘柄のみ表示できます" }, 404);
    }
    if (p === "/api/position-size") {
      const n = k => parseFloat(q.get(k));
      return reply(positionSize(n("account"), n("risk_pct"), n("entry"), n("stop"),
        q.has("max_capital_pct") ? n("max_capital_pct") : 100));
    }
    return null;
  }

  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input.url;
    if (url.startsWith("/api/")) {
      const res = await handle(url);
      if (res) return res;
    }
    return realFetch(input, init);
  };

  // Snapshot notice: the data is frozen at build time, and the signals have no measured edge.
  // Added to the disclaimer box; the snapshot time itself shows in the session pill.
  document.addEventListener("DOMContentLoaded", () => {
    const box = document.querySelector(".disclaimer-banner");
    if (!box) return;
    const note = document.createElement("span");
    note.className = "disclaimer-snap";
    note.textContent = "※ 静的スナップショット版 (自動更新なし)。バックテストでは取引コストを上回る優位性は未確認のため、実際の売買には使わないでください。";
    box.appendChild(note);
  });
})();
