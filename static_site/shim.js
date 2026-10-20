/**
 * Static-site mode: answers the app's /api/* calls from JSON files written by
 * static_site/build_static.py, so the site runs on plain static hosting.
 * Loaded before app.js; app.js itself is unchanged.
 *
 * Data is read live from this repo's snapshot-data branch, which
 * .github/workflows/snapshot.yml rebuilds every 15 minutes during TSE hours, so
 * the site stays current without a new Netlify upload. If that branch cannot be
 * reached, the copy bundled at deploy time (/snapshot/...) is used instead.
 */
(function () {
  const realFetch = window.fetch.bind(window);
  const RAW = "https://raw.githubusercontent.com/mattappsaibagus-wq/japan-day-trading-webapp";
  const LIVE = `${RAW}/snapshot-data`;
  const KRONOS_LIVE = `${RAW}/kronos-data/kronos.json`;
  const SNAPSHOT_TTL_MS = 60e3;  // the app polls every minute; re-read the snapshot at most this often
  const LOT = 100;
  let snapshotP = null, snapshotAt = 0;

  // raw.githubusercontent caches for a few minutes; bust once a minute at most
  const bust = () => `m=${Math.floor(Date.now() / 60000)}`;

  async function liveOrBundled(path) {
    try {
      const r = await realFetch(`${LIVE}/${path}?${bust()}`, { cache: "no-store" });
      if (r.ok) return r;
    } catch (e) { /* offline or blocked: fall back */ }
    return realFetch(`/snapshot/${path}`);
  }

  function snapshot() {
    if (!snapshotP || Date.now() - snapshotAt > SNAPSHOT_TTL_MS) {
      snapshotAt = Date.now();
      snapshotP = liveOrBundled("snapshot.json").then(r => r.json()).catch(e => { snapshotP = null; throw e; });
    }
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

  // Port of market_rules.session_status. JPX holidays come from the snapshot
  // (build_static.py lists the coming weeks' non-trading weekdays).
  function sessionNow(holidays) {
    const d = new Date(Date.now() + 9 * 3600e3);
    const ymd = d.toISOString().slice(0, 10);
    const dow = d.getUTCDay();
    const hol = (holidays || {})[ymd];
    if (dow === 0 || dow === 6) return { state: "closed", label: "休場日", holiday: "週末" };
    if (hol) return { state: "closed", label: "休場日", holiday: hol };
    const m = d.getUTCHours() * 60 + d.getUTCMinutes();
    const at = (h, mm) => h * 60 + mm;
    if (m < at(8, 0)) return { state: "closed", label: "取引時間外", holiday: null };
    if (m < at(9, 0)) return { state: "pre_open", label: "寄付前 (板寄せ注文受付)", holiday: null };
    if (m < at(11, 30)) return { state: "morning", label: "前場", holiday: null };
    if (m < at(12, 30)) return { state: "lunch", label: "昼休み", holiday: null };
    if (m < at(15, 25)) return { state: "afternoon", label: "後場", holiday: null };
    if (m < at(15, 30)) return { state: "closing_auction", label: "クロージング・オークション", holiday: null };
    return { state: "closed", label: "大引け後", holiday: null };
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
      const now = sessionNow(s.holidays);
      return reply(Object.assign(now, {
        label: now.holiday ? now.label : `${now.label} · データ ${fmtJst(s.last_bar)} 時点`,
        data: { provider: "Yahoo", realtime: false, delay_minutes: 20 },
      }));
    }
    if (p === "/api/kronos") {
      // Kronos publishes every 30 min in TSE hours; read it directly, bundled copy as fallback
      try {
        const r = await realFetch(`${KRONOS_LIVE}?${bust()}`, { cache: "no-store" });
        if (r.ok) return r;
      } catch (e) { /* fall back */ }
      return realFetch("/snapshot/kronos.json");
    }
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
      const r = await liveOrBundled(`stock/${sym}_${iv}.json`);
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

  // Notice: data refreshes on a schedule (Yahoo, ~20 min delayed), and the signals have no measured edge.
  document.addEventListener("DOMContentLoaded", () => {
    const box = document.querySelector(".disclaimer-banner");
    if (!box) return;
    const note = document.createElement("span");
    note.className = "disclaimer-snap";
    note.textContent = "※ 取引時間中は約15分ごとに自動更新 (Yahoo 約20分遅延)。バックテストでは取引コストを上回る優位性は未確認のため、実際の売買には使わないでください。";
    box.appendChild(note);
  });
})();
