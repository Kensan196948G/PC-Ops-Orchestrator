const SCORE_STATUS = [
  { max: 40, cls: "severity-critical", label: "危険" },
  { max: 60, cls: "severity-high", label: "不安定" },
  { max: 80, cls: "severity-medium", label: "要注意" },
  { max: 101, cls: "severity-low", label: "正常" },
];

function scoreStatus(score) {
  return (
    SCORE_STATUS.find((s) => score < s.max) ||
    SCORE_STATUS[SCORE_STATUS.length - 1]
  );
}

function scoreBadge(score) {
  const st = scoreStatus(score);
  const span = document.createElement("span");
  span.className = "status-badge " + st.cls;
  span.textContent = st.label;
  return span;
}

function scoreBar(score) {
  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;align-items:center;gap:0.5rem;";
  const inner = document.createElement("div");
  inner.style.cssText =
    "background:var(--border);border-radius:4px;height:8px;width:80px;overflow:hidden;";
  const fill = document.createElement("div");
  const pct = Math.max(0, Math.min(100, score));
  const color =
    score < 40
      ? "#dc2626"
      : score < 60
        ? "#f59e0b"
        : score < 80
          ? "#3b82f6"
          : "#16a34a";
  fill.style.cssText = `width:${pct}%;height:100%;background:${color};`;
  inner.appendChild(fill);
  const num = document.createElement("span");
  num.style.cssText = "font-size:0.85rem;font-weight:600;min-width:3ch;";
  num.textContent = pct.toFixed(1);
  bar.appendChild(inner);
  bar.appendChild(num);
  return bar;
}

function fmtDeductions(deductionsJson) {
  let list;
  try {
    list =
      typeof deductionsJson === "string"
        ? JSON.parse(deductionsJson)
        : deductionsJson;
  } catch {
    return "-";
  }
  if (!Array.isArray(list) || list.length === 0) return "減点なし";
  return list
    .slice(0, 3)
    .map(
      (d) => `${d.label || d.category || "?"} (${d.points?.toFixed(1) ?? 0})`,
    )
    .join(", ");
}

function fmtDate(str) {
  if (!str) return "-";
  return new Date(str).toLocaleString("ja-JP");
}

function emptyRow(cols, msg) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = cols;
  td.className = "text-center";
  td.textContent = msg;
  tr.appendChild(td);
  return tr;
}

function clearBody(tbody) {
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
}

async function loadStats(days) {
  try {
    const data = await apiFetch(`/stability/scores?per_page=999&days=${days}`);
    const items = data.items || data || [];
    let critical = 0,
      unstable = 0,
      warning = 0,
      healthy = 0;
    for (const r of items) {
      const sc = r.latest_score ?? r.score ?? 100;
      if (sc < 40) critical++;
      else if (sc < 60) unstable++;
      else if (sc < 80) warning++;
      else healthy++;
    }
    const set = (id, v) => {
      const el = document.getElementById(id);
      if (el) el.textContent = v;
    };
    set("stat-total", items.length);
    set("stat-critical", critical);
    set("stat-unstable", unstable);
    set("stat-warning", warning);
    set("stat-healthy", healthy);
    return items;
  } catch (e) {
    console.error("loadStats error:", e);
    return [];
  }
}

function buildScoreRow(item) {
  const tr = document.createElement("tr");
  const score = item.latest_score ?? item.score ?? 100;

  // PC名 (link)
  const tdName = document.createElement("td");
  const a = document.createElement("a");
  a.href = `/pcs/${item.pc_id}`;
  a.textContent = item.pc_name || "PC#" + item.pc_id;
  tdName.appendChild(a);
  tr.appendChild(tdName);

  // スコアバー
  const tdScore = document.createElement("td");
  tdScore.appendChild(scoreBar(score));
  tr.appendChild(tdScore);

  // 状態バッジ
  const tdStatus = document.createElement("td");
  tdStatus.appendChild(scoreBadge(score));
  tr.appendChild(tdStatus);

  // 減点要因
  const tdDeduct = document.createElement("td");
  tdDeduct.style.cssText = "font-size:0.8rem;max-width:240px;";
  tdDeduct.textContent = fmtDeductions(item.deductions);
  tr.appendChild(tdDeduct);

  // 分析日数
  const tdDays = document.createElement("td");
  tdDays.textContent = item.analysis_days ?? "-";
  tr.appendChild(tdDays);

  // 計算日時
  const tdCalc = document.createElement("td");
  tdCalc.textContent = fmtDate(item.calculated_at);
  tr.appendChild(tdCalc);

  // Chevron
  const tdOp = document.createElement("td");
  tdOp.className = "row-chevron";
  const chevSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  chevSvg.setAttribute("width", "14");
  chevSvg.setAttribute("height", "14");
  chevSvg.setAttribute("viewBox", "0 0 24 24");
  chevSvg.setAttribute("fill", "none");
  chevSvg.setAttribute("stroke", "currentColor");
  chevSvg.setAttribute("stroke-width", "2.5");
  chevSvg.setAttribute("stroke-linecap", "round");
  chevSvg.setAttribute("stroke-linejoin", "round");
  const chevPoly = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "polyline",
  );
  chevPoly.setAttribute("points", "9 18 15 12 9 6");
  chevSvg.appendChild(chevPoly);
  tdOp.appendChild(chevSvg);
  tr.appendChild(tdOp);

  tr.classList.add("row-clickable");
  tr.addEventListener("click", () => openStabilityDrawer(item));

  return tr;
}

// ── Drawer ──────────────────────────────────────────────────────────────────

let _drawerItem = null;

function openStabilityDrawer(item) {
  const overlay = document.getElementById("stability-drawer-overlay");
  const titleEl = document.getElementById("stability-drawer-title");
  const bodyEl = document.getElementById("stability-drawer-body");
  const detailLink = document.getElementById("stability-drawer-detail-link");
  const recalcBtn = document.getElementById("stability-drawer-recalc-btn");
  if (!overlay || !bodyEl) return;

  _drawerItem = item;
  const score = item.latest_score ?? item.score ?? 100;

  if (titleEl) titleEl.textContent = item.pc_name || "PC#" + item.pc_id;
  if (detailLink) detailLink.href = `/pcs/${item.pc_id}`;
  if (recalcBtn) {
    recalcBtn.onclick = () => {
      recalculateOne(item.pc_id, item.pc_name);
      closeStabilityDrawer();
    };
  }

  bodyEl.textContent = "";

  // Score hero
  const hero = document.createElement("div");
  hero.className = "score-hero";
  const numEl = document.createElement("div");
  numEl.className = "score-hero-num";
  numEl.style.color =
    score < 40
      ? "var(--danger)"
      : score < 80
        ? "var(--warning)"
        : "var(--success)";
  numEl.textContent = score.toFixed(1);
  hero.appendChild(numEl);

  const metaEl = document.createElement("div");
  metaEl.className = "score-hero-meta";
  metaEl.appendChild(scoreBadge(score));
  const bar = document.createElement("div");
  bar.style.cssText =
    "width:100%;height:8px;background:var(--bg-elevated);border-radius:999px;overflow:hidden;margin-top:0.5rem;";
  const fill = document.createElement("div");
  fill.style.cssText = `height:100%;border-radius:999px;width:${score}%;background:${score < 40 ? "var(--danger)" : score < 80 ? "var(--warning)" : "var(--success)"};`;
  bar.appendChild(fill);
  metaEl.appendChild(bar);
  hero.appendChild(metaEl);
  bodyEl.appendChild(hero);

  // Key/value info
  const kvSection = document.createElement("div");
  const kvHead = document.createElement("div");
  kvHead.className = "drawer-section-title";
  kvHead.textContent = "基本情報";
  kvSection.appendChild(kvHead);

  const dl = document.createElement("dl");
  dl.className = "kv-grid";
  const pairs = [
    ["分析日数", item.analysis_days != null ? `${item.analysis_days} 日` : "-"],
    ["計算日時", fmtDate(item.calculated_at)],
  ];
  for (const [k, v] of pairs) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    dl.appendChild(dt);
    const dd = document.createElement("dd");
    dd.textContent = v;
    dl.appendChild(dd);
  }
  kvSection.appendChild(dl);
  bodyEl.appendChild(kvSection);

  // Deduction factors
  let deductions = [];
  try {
    deductions =
      typeof item.deductions === "string"
        ? JSON.parse(item.deductions)
        : item.deductions || [];
  } catch {
    deductions = [];
  }

  if (Array.isArray(deductions) && deductions.length > 0) {
    const factSection = document.createElement("div");
    const factHead = document.createElement("div");
    factHead.className = "drawer-section-title";
    factHead.textContent = "減点要因";
    factSection.appendChild(factHead);

    for (const d of deductions.slice(0, 6)) {
      const pts = d.points ?? d.score ?? 0;
      const row = document.createElement("div");
      row.className = "factor";

      const nameEl = document.createElement("div");
      nameEl.className = "factor-name";
      nameEl.textContent = d.label || d.category || "不明";
      row.appendChild(nameEl);

      const ptsEl = document.createElement("div");
      ptsEl.className = "factor-pts";
      ptsEl.textContent = `-${pts.toFixed(1)}pt`;
      row.appendChild(ptsEl);

      const track = document.createElement("div");
      track.className = "factor-track";
      const factFill = document.createElement("div");
      factFill.className = "factor-fill";
      factFill.style.width = `${Math.min(100, (pts / 30) * 100)}%`;
      track.appendChild(factFill);
      row.appendChild(track);

      factSection.appendChild(row);
    }
    bodyEl.appendChild(factSection);
  }

  overlay.classList.remove('hidden');
  document.body.style.overflow = "hidden";
}

function closeStabilityDrawer() {
  const overlay = document.getElementById("stability-drawer-overlay");
  if (overlay) overlay.classList.add('hidden');
  document.body.style.overflow = "";
  _drawerItem = null;
}

async function loadScores(days) {
  const tbody = document.getElementById("scores-body");
  if (!tbody) return;
  clearBody(tbody);
  tbody.appendChild(emptyRow(7, "読み込み中..."));
  try {
    const data = await apiFetch(`/stability/scores?per_page=999&days=${days}`);
    const items = (data.items || data || []).sort((a, b) => {
      const sa = a.latest_score ?? a.score ?? 100;
      const sb = b.latest_score ?? b.score ?? 100;
      return sa - sb;
    });
    clearBody(tbody);
    if (items.length === 0) {
      tbody.appendChild(emptyRow(7, "データなし"));
      return;
    }
    for (const item of items) tbody.appendChild(buildScoreRow(item));
  } catch (e) {
    clearBody(tbody);
    tbody.appendChild(emptyRow(7, "読み込み失敗"));
    console.error(e);
  }
}

async function loadRanking(days) {
  const tbody = document.getElementById("ranking-body");
  if (!tbody) return;
  clearBody(tbody);
  tbody.appendChild(emptyRow(5, "読み込み中..."));
  try {
    const data = await apiFetch(
      `/stability/event-ranking?days=${days}&limit=10`,
    );
    const items = data.items || data || [];
    clearBody(tbody);
    if (items.length === 0) {
      tbody.appendChild(emptyRow(5, "データなし"));
      return;
    }
    items.forEach((item, idx) => {
      const tr = document.createElement("tr");
      [
        String(idx + 1),
        String(item.event_id ?? "-"),
        item.category ?? "-",
        String(item.count ?? "-"),
        String(item.pc_count ?? "-"),
      ].forEach((text) => {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  } catch (e) {
    clearBody(tbody);
    tbody.appendChild(emptyRow(5, "読み込み失敗"));
    console.error(e);
  }
}

async function recalculateAll(days) {
  const btn = document.getElementById("btn-recalculate");
  if (btn) btn.disabled = true;
  try {
    await apiFetch(`/stability/calculate?days=${days}`, { method: "POST" });
    await Promise.all([loadStats(days), loadScores(days), loadRanking(days)]);
  } catch (e) {
    console.error("recalculate error:", e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function recalculateOne(pcId, pcName) {
  const days = document.getElementById("days-filter")?.value || "30";
  try {
    await apiFetch(`/stability/calculate/${pcId}?days=${days}`, {
      method: "POST",
    });
    await Promise.all([loadStats(days), loadScores(days)]);
  } catch (e) {
    console.error("recalculate " + pcName + " error:", e);
  }
}

function getDays() {
  return document.getElementById("days-filter")?.value || "30";
}

document.addEventListener("DOMContentLoaded", () => {
  const days = getDays();
  loadStats(days);
  loadScores(days);
  loadRanking(days);

  document.getElementById("days-filter")?.addEventListener("change", (e) => {
    const d = e.target.value;
    loadStats(d);
    loadScores(d);
    loadRanking(d);
  });

  document.getElementById("btn-recalculate")?.addEventListener("click", () => {
    recalculateAll(getDays());
  });

  document
    .getElementById("btn-close-stability-drawer")
    ?.addEventListener("click", closeStabilityDrawer);
  document
    .getElementById("stability-drawer-overlay")
    ?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeStabilityDrawer();
    });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeStabilityDrawer();
  });
});
