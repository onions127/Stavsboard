// Stavsboard client: polls /api/snapshot and paints it. Read-only except the refresh-mode setting.
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const DISCONNECTED_MS = 5000;
  const GiB = 1024 ** 3;
  const MiB = 1024 ** 2;

  const saved = {
    get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
  };

  const S = {
    snap: null,
    lastOk: 0,
    tab: "now",
    sort: "cpu",
    logOpen: saved.get("stavsboard.log", "0") === "1",
    timer: null,
    stalledPolls: 0,
    pendingMode: null,
    title: "",
    liveKey: "",
    procRows: new Map(),
    trendRows: new Map(),
    firstPaint: true,
  };

  // ---- formatting -------------------------------------------------------------------------
  const clock = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
  const hhmm = (epoch) => clock.format(new Date(epoch * 1000));
  const pct = (v) => `${Math.round(v)}%`;
  const pct1 = (v) => `${v < 10 ? v.toFixed(1) : Math.round(v)}%`;
  const gbNum = (b) => { const g = b / GiB; return g >= 100 ? Math.round(g).toString() : g.toFixed(1).replace(/\.0$/, ""); };
  const size = (b) => (b >= GiB ? `${(b / GiB).toFixed(1)} GB` : `${Math.round(b / MiB)} MB`);
  function duration(s) {
    if (s < 60) return "<1 min";
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  }
  const text = (el, value) => { if (el.textContent !== value) el.textContent = value; };
  const setLevelClass = (el, prefix, level) => {
    el.classList.remove(`${prefix}-warning`, `${prefix}-error`);
    if (level === "warning" || level === "error") el.classList.add(`${prefix}-${level}`);
  };
  const activeOf = (kind) => (S.snap?.active || []).find((a) => a.kind === kind);
  // Stale data keeps its numbers but loses its colors: it is neither calm nor alarming.
  const live = (level) => (connection() === "live" ? level : null);

  // ---- connection state ----------------------------------------------------------------------
  function connection() {
    if (!S.snap) return "loading";
    if (performance.now() - S.lastOk > DISCONNECTED_MS) return "disconnected";
    if (S.stalledPolls >= 2) return "stalled"; // two polls in a row, so a wake-up blip isn't a stall
    return "live";
  }

  // ---- polling ---------------------------------------------------------------------------------
  async function poll() {
    clearTimeout(S.timer);
    const ctrl = new AbortController();
    const abort = setTimeout(() => ctrl.abort(), 4000);
    try {
      const r = await fetch(`api/snapshot${S.tab === "trends" ? "?trends=1" : ""}`, { cache: "no-store", signal: ctrl.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const snap = await r.json();
      S.snap = snap;
      S.lastOk = performance.now();
      S.stalledPolls = snap.stalled ? S.stalledPolls + 1 : 0;
      render();
    } catch {
      paintConnection();
    } finally {
      clearTimeout(abort);
      S.timer = setTimeout(poll, (S.snap?.interval_s ?? 1) * 1000);
    }
  }

  // ---- paint -------------------------------------------------------------------------------------
  function render() {
    paintConnection();
    const s = S.snap;
    if (!s) return;
    paintWarnings(s);
    paintCpu(s);
    paintMem(s);
    paintProcs(s);
    paintContainers(s);
    paintSettings(s);
    if (S.tab === "trends") paintTrends(s);
    S.firstPaint = false;
  }

  function paintConnection() {
    const state = connection();
    const app = $("app");
    app.classList.toggle("is-loading", state === "loading");
    app.classList.toggle("is-stale", state === "disconnected" || state === "stalled");
    const dot = $("status-dot");
    const tabdot = $("tabdot");
    let sentence, more = "", level, liveKey, title;
    if (state === "live") {
      const st = S.snap.status;
      sentence = st.text;
      more = st.more > 0 ? ` · ${st.more} more` : "";
      level = st.level;
      liveKey = st.key;
      title = S.snap.title;
    } else {
      level = "hollow";
      if (state === "loading") {
        sentence = "Connecting…";
        title = "Stavsboard";
      } else if (state === "disconnected") {
        const age = Math.round((performance.now() - S.lastOk) / 1000 + (S.snap.collected_age_s || 0));
        sentence = `Disconnected, data ${age}s old`;
        title = "○ Disconnected · Stavsboard";
      } else {
        sentence = "Collector stalled";
        title = "○ Disconnected · Stavsboard";
      }
      liveKey = state;
    }
    dot.className = `dot ${level === "good" ? "" : level}`.trim();
    tabdot.className = `tabdot ${level === "good" ? "" : level}`.trim();
    text($("status-text"), sentence);
    text($("status-more"), more);
    if (liveKey !== S.liveKey) { // announce only when the situation changes, not every number
      S.liveKey = liveKey;
      text($("status-live"), sentence);
    }
    if (title !== S.title) { S.title = title; document.title = title; }
    if (state !== "live") {
      for (const id of ["sec-cpu", "sec-mem", "sec-ctrs"]) { setLevelClass($(id), "wash", null); setLevelClass($(id), "hue", null); }
    }
  }

  function paintWarnings(s) {
    const box = $("warn-items");
    const parts = [];
    for (const a of s.active) {
      const cls = a.level === "error" ? "crit" : "live";
      parts.push(`<span class="${cls}">${esc(a.label)} since ${hhmm(a.start)} (ongoing)</span>`);
    }
    if (!s.active.length) parts.push('<span class="ok">No active warnings</span>');
    const past = s.log.entries.find((e) => e.end !== null);
    if (past) parts.push(`<span class="past">${s.active.length ? "" : "Last: "}${pastText(past)}</span>`);
    const html = parts.join("");
    if (box.innerHTML !== html) box.innerHTML = html;

    const btn = $("log-btn");
    btn.hidden = false;
    text(btn, `Log · ${s.log.entries.length}`);
    btn.setAttribute("aria-expanded", String(S.logOpen));
    $("log").hidden = !S.logOpen;
    if (S.logOpen) paintLog(s);
  }

  function pastText(e) {
    if (e.kind === "container") return `${esc(e.label)} at <b>${hhmm(e.start)}</b>`;
    return `${esc(e.subject)} hit ${esc(e.peak_text)} at <b>${hhmm(e.start)}</b> for ${duration(e.end - e.start)}`;
  }

  function paintLog(s) {
    text($("log-head"), `Watching since ${hhmm(s.log.since)}`);
    const list = $("log-list");
    let html;
    if (!s.log.entries.length) {
      html = `<li class="none">No warnings since ${hhmm(s.log.since)}</li>`;
    } else {
      html = s.log.entries.map((e) => {
        const on = e.end === null;
        const peak = e.peak_text ? `peak ${esc(e.peak_text)} · ` : "";
        const detail = on ? `${peak}ongoing since ${hhmm(e.start)}` : `${peak}${duration(e.end - e.start)}`;
        const cls = on ? `on ${e.level}` : "";
        return `<li class="${cls}"><span class="t">${hhmm(e.start)}</span><span class="l">${esc(e.label)}</span><span class="d">${detail}</span></li>`;
      }).join("");
    }
    if (list.innerHTML !== html) list.innerHTML = html;
  }

  function paintCpu(s) {
    const sec = $("sec-cpu");
    const cpu = s.cpu;
    setLevelClass(sec, "wash", live(s.levels.cpu));
    setLevelClass(sec, "hue", live(activeOf("cpu")?.level));
    if (!cpu) return;
    text($("cpu-num"), pct(cpu.total));
    const arc = $("cpu-arc");
    arc.setAttribute("stroke-dasharray", `${Math.max(0, Math.min(100, cpu.total)).toFixed(1)} 100`);
    arc.classList.toggle("zero", cpu.total < 0.5);

    // per-core strip: at most 32 bars; above 32 cores each bar is the busiest of its group (DR7)
    const n = cpu.per_core.length;
    const group = n > 32 ? Math.ceil(n / 32) : 1;
    const bars = [];
    for (let i = 0; i < n; i += group) bars.push(Math.max(...cpu.per_core.slice(i, i + group)));
    const strip = $("cores");
    strip.classList.toggle("dense", bars.length > 16);
    while (strip.children.length < bars.length) strip.appendChild(document.createElement("i"));
    while (strip.children.length > bars.length) strip.lastChild.remove();
    bars.forEach((v, i) => {
      const bar = strip.children[i];
      bar.style.height = `${Math.max(6, Math.min(100, v))}%`;
      bar.classList.toggle("hot", v >= 90);
    });

    const sub = $("cpu-sub");
    let html = `${cpu.count} cores${group > 1 ? " · grouped" : ""}`;
    if (cpu.temp_c !== null && cpu.temp_c !== undefined) {
      const t = activeOf("temp");
      const temp = `${Math.round(cpu.temp_c)}°C`;
      html += t ? ` · <span class="hot ${t.level}">${temp}</span>` : ` · ${temp}`;
    }
    if (sub.innerHTML !== html) sub.innerHTML = html;
  }

  function paintMem(s) {
    const sec = $("sec-mem");
    setLevelClass(sec, "wash", live(s.levels.mem));
    setLevelClass(sec, "hue", live(activeOf("ram")?.level));
    const m = s.mem;
    if (!m) return;
    text($("mem-num"), pct(m.percent));
    text($("mem-sub"), `${gbNum(m.used)} of ${gbNum(m.total)} GB`);
    const cached = m.cached ?? 0;
    const free = Math.max(0, m.total - m.used - cached);
    const seg = (id, bytes) => {
      const el = $(id);
      const share = (bytes / m.total) * 100;
      el.style.flexGrow = share.toFixed(2);
      el.hidden = share < 0.3;
    };
    seg("seg-used", m.used);
    seg("seg-cached", cached);
    seg("seg-free", free);
    const legend = [`<span><b class="u"></b>Used ${size(m.used)}</span>`];
    if (m.cached !== null) legend.push(`<span><b class="c"></b>Cached ${size(m.cached)}</span>`);
    legend.push(`<span><b class="f"></b>Free ${size(free)}</span>`);
    const html = legend.join("");
    if ($("mem-legend").innerHTML !== html) $("mem-legend").innerHTML = html;

    const sw = s.swap;
    const line = $("swap-line");
    if (!sw || !sw.total) {
      line.hidden = true;
      text($("swap-cap"), "No swap");
    } else {
      line.hidden = false;
      const fill = $("swap-fill");
      fill.style.width = `${Math.min(100, sw.percent)}%`;
      fill.className = live(activeOf("swap")?.level) || "";
      text($("swap-cap"), `Swap ${gbNum(sw.used)} of ${gbNum(sw.total)} GB`);
    }
  }

  function paintProcs(s) {
    const rows = S.sort === "cpu" ? s.procs.by_cpu : s.procs.by_ram;
    const body = $("procs-body");
    const seen = new Set();
    rows.forEach((p, i) => {
      seen.add(p.pid);
      let tr = S.procRows.get(p.pid);
      if (!tr) {
        tr = document.createElement("tr");
        tr.innerHTML = '<td class="name"></td><td class="n"></td><td class="n m"></td>';
        if (!S.firstPaint) {
          // Regression: ISSUE-001 — the fade replayed on every reorder (moving a node restarts
          // its CSS animation). Found by /qa on 2026-11-03. Fade once, then drop the class.
          // A timer, not animationend: hidden tabs pause animations and would never fire it.
          tr.classList.add("enter");
          setTimeout(() => tr.classList.remove("enter"), 200);
        }
        S.procRows.set(p.pid, tr);
      }
      const name = p.name || `PID ${p.pid}`;
      const cpu = p.cpu === null ? "—" : pct1(p.cpu);
      const ram = p.rss === null ? "—" : size(p.rss);
      const [a, b] = S.sort === "cpu" ? [cpu, ram] : [ram, cpu];
      const cells = tr.children;
      text(cells[0], name);
      if (cells[0].title !== name) cells[0].title = name;
      text(cells[1], a);
      text(cells[2], b);
      if (body.children[i] !== tr) body.insertBefore(tr, body.children[i] || null); // instant reorder (DR16)
    });
    for (const [pid, tr] of S.procRows) {
      if (!seen.has(pid)) { tr.remove(); S.procRows.delete(pid); }
    }
  }

  function paintContainers(s) {
    const c = s.containers;
    const sec = $("sec-ctrs");
    const show = c.state === "ok" || c.state === "denied";
    sec.hidden = !show;
    $("lists").classList.toggle("solo", !show);
    if (!show) return;
    setLevelClass(sec, "wash", c.stale ? null : live(s.levels.containers));
    sec.classList.toggle("is-old", c.stale);
    const sum = $("ctrs-sum");
    const empty = $("ctrs-empty");
    const body = $("ctrs-body");
    if (c.state === "denied") {
      empty.hidden = false;
      text(empty, "No access to Docker");
      sum.className = "";
      text(sum, "");
      body.innerHTML = "";
      return;
    }
    const crashed = c.items.filter((i) => i.state === "exited" && i.exit_code);
    const running = c.items.filter((i) => i.state === "running");
    if (c.stale) { sum.className = "old"; text(sum, `data ${Math.round(c.age_s)}s old`); }
    else if (crashed.length) { sum.className = "bad"; text(sum, `${crashed.length} exited`); }
    else { sum.className = ""; text(sum, `${running.length} running`); }
    empty.hidden = c.items.length > 0;
    text(empty, "No containers");
    const html = c.items.map((i) => {
      let dot = "idle", mid, cls = "n";
      if (i.state === "running") {
        dot = "";
        mid = i.cpu === null ? "—" : pct1(i.cpu);
      } else if (i.state === "exited" && i.exit_code) {
        dot = "off"; mid = `exit ${i.exit_code}`; cls = "n exit";
      } else if (i.state === "exited") {
        mid = "exited 0"; cls = "n m";
      } else {
        mid = esc(i.state || "—"); cls = "n m";
      }
      const mem = i.mem === null ? "—" : size(i.mem);
      return `<tr><td class="name"><span class="ctr"><i class="${dot}"></i><span title="${esc(i.name)}">${esc(i.name)}</span></span></td><td class="${cls}">${mid}</td><td class="n m">${mem}</td></tr>`;
    }).join("");
    if (body.innerHTML !== html) body.innerHTML = html;
  }

  function paintSettings(s) {
    const mode = S.pendingMode || s.mode;
    for (const b of document.querySelectorAll("[data-mode-opt]")) b.setAttribute("aria-pressed", String(b.dataset.modeOpt === mode));
    text($("mode-hint"), mode === "low"
      ? "Every 2 seconds, lighter on the server. Applies to everyone viewing."
      : "Every second. Applies to everyone viewing.");
  }

  // ---- trends ------------------------------------------------------------------------------------------
  function paintTrends(s) {
    text($("trends-caption"), s.interval_s > 1 ? `Last ${Math.round((60 * s.interval_s) / 60)} minutes` : "Last 60 seconds");
    const box = $("trend-rows");
    const rows = s.trends || [];
    const keep = new Set(rows.map((r) => r.key));
    for (const [key, el] of S.trendRows) if (!keep.has(key)) { el.remove(); S.trendRows.delete(key); }
    rows.forEach((row, i) => {
      let el = S.trendRows.get(row.key);
      if (!el) {
        el = document.createElement("div");
        el.className = "trow";
        el.innerHTML = '<div class="trow-h"><span class="tl"></span><span class="tv"></span></div>' +
          '<svg class="spark" viewBox="0 0 59 40" preserveAspectRatio="none" aria-hidden="true"><path class="g"/><path class="w"/><path class="e"/></svg>';
        S.trendRows.set(row.key, el);
      }
      if (box.children[i] !== el) box.insertBefore(el, box.children[i] || null);
      const label = row.key.startsWith("ctr:") ? `${row.label} CPU` : row.label;
      text(el.querySelector(".tl"), label);
      const last = [...row.values].reverse().find((v) => v !== null);
      text(el.querySelector(".tv"), last === undefined ? "—" : `${Math.round(last)}${row.unit}`);
      const [g, w, e] = el.querySelectorAll("path");
      const paths = sparkPaths(row);
      g.setAttribute("d", paths.g);
      w.setAttribute("d", paths.w);
      e.setAttribute("d", paths.e);
    });
  }

  // Fixed 0-100 scale, no axes; segments at or above a threshold drawn in its alarm hue (DR14).
  function sparkPaths(row) {
    const vals = row.values;
    const n = vals.length;
    const x = (i) => 59 - (n - 1 - i); // fewer than 60 samples start at the right edge
    const y = (v) => 40 - (Math.max(0, Math.min(100, v)) / 100) * 38 - 1;
    const out = { g: "", w: "", e: "" };
    for (let i = 1; i < n; i++) {
      const a = vals[i - 1], b = vals[i];
      if (a === null || b === null) continue;
      const hi = Math.max(a, b);
      const k = row.crit_at !== null && hi >= row.crit_at ? "e" : row.warn_at !== null && hi >= row.warn_at ? "w" : "g";
      out[k] += `M${x(i - 1)} ${y(a).toFixed(2)}L${x(i)} ${y(b).toFixed(2)}`;
    }
    if (n === 1 && vals[0] !== null) out.g = `M58.5 ${y(vals[0]).toFixed(2)}L59 ${y(vals[0]).toFixed(2)}`;
    return out;
  }

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---- controls ------------------------------------------------------------------------------------------
  function selectTab(name, focus) {
    S.tab = name;
    for (const t of ["now", "trends"]) {
      const tab = $(`tab-${t}`);
      const on = t === name;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      $(`panel-${t}`).hidden = !on;
      if (on && focus) tab.focus();
    }
    poll();
  }
  $("tab-now").addEventListener("click", () => selectTab("now"));
  $("tab-trends").addEventListener("click", () => selectTab("trends"));
  document.querySelector(".tabs").addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowRight" || ev.key === "ArrowLeft" || ev.key === "Home" || ev.key === "End") {
      ev.preventDefault();
      const next = ev.key === "Home" ? "now" : ev.key === "End" ? "trends" : S.tab === "now" ? "trends" : "now";
      selectTab(next, true);
    }
  });

  for (const b of document.querySelectorAll("[data-sort]")) {
    b.addEventListener("click", () => {
      S.sort = b.dataset.sort;
      for (const o of document.querySelectorAll("[data-sort]")) o.setAttribute("aria-pressed", String(o === b));
      if (S.snap) {
        S.firstPaint = true; // a re-sort swaps the list instantly; no fade-ins
        paintProcs(S.snap);
        S.firstPaint = false;
      }
    });
  }

  $("log-btn").addEventListener("click", () => {
    S.logOpen = !S.logOpen;
    saved.set("stavsboard.log", S.logOpen ? "1" : "0");
    if (S.snap) paintWarnings(S.snap);
  });

  // Settings drawer: Esc, the Close button or a click outside closes it; focus stays inside
  // while open and returns to the Settings button after.
  function setDrawer(open) {
    const drawer = $("settings");
    if (drawer.hidden === !open) return;
    drawer.hidden = !open;
    $("scrim").hidden = !open;
    $("settings-btn").setAttribute("aria-expanded", String(open));
    if (open) (drawer.querySelector('[aria-pressed="true"]') || $("settings-close")).focus();
    else $("settings-btn").focus();
  }
  $("settings-btn").addEventListener("click", () => setDrawer(true));
  $("settings-close").addEventListener("click", () => setDrawer(false));
  $("scrim").addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (ev) => {
    const drawer = $("settings");
    if (drawer.hidden) return;
    if (ev.key === "Escape") { ev.preventDefault(); setDrawer(false); return; }
    if (ev.key !== "Tab") return;
    const items = [...drawer.querySelectorAll("button")];
    const first = items[0], last = items[items.length - 1];
    if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    else if (!drawer.contains(document.activeElement)) { ev.preventDefault(); first.focus(); }
  });

  function applyTheme(choice) {
    if (choice === "light" || choice === "dark") document.documentElement.setAttribute("data-theme", choice);
    else document.documentElement.removeAttribute("data-theme");
    for (const b of document.querySelectorAll("[data-theme-opt]")) b.setAttribute("aria-pressed", String(b.dataset.themeOpt === choice));
  }
  for (const b of document.querySelectorAll("[data-theme-opt]")) {
    b.addEventListener("click", () => { saved.set("stavsboard.theme", b.dataset.themeOpt); applyTheme(b.dataset.themeOpt); });
  }
  applyTheme(saved.get("stavsboard.theme", "auto"));

  for (const b of document.querySelectorAll("[data-mode-opt]")) {
    b.addEventListener("click", async () => {
      const mode = b.dataset.modeOpt;
      S.pendingMode = mode;
      if (S.snap) paintSettings(S.snap);
      try {
        const r = await fetch("api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } catch {
        text($("mode-hint"), "Couldn't change the refresh mode. Try again.");
      } finally {
        S.pendingMode = null;
        poll();
      }
    });
  }

  // Waking a sleeping tab: check data age before painting, so stale green never flashes.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") { paintConnection(); poll(); }
  });
  setInterval(() => { if (connection() !== "live") paintConnection(); }, 1000);

  poll();
})();
