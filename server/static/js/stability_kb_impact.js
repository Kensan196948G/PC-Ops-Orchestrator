function clearBody(tbody) {
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
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

function fmtDate(str) {
  if (!str) return "-";
  return new Date(str).toLocaleString("ja-JP");
}

function riskBadge(changeRatio) {
  const span = document.createElement("span");
  span.className = "status-badge";
  if (changeRatio >= 2.0) {
    span.classList.add("severity-critical");
    span.textContent = "高リスク";
  } else if (changeRatio >= 1.5) {
    span.classList.add("severity-high");
    span.textContent = "中リスク";
  } else if (changeRatio >= 1.0) {
    span.classList.add("severity-medium");
    span.textContent = "低リスク";
  } else {
    span.classList.add("severity-low");
    span.textContent = "影響軽微";
  }
  return span;
}

function fmtChangeRatio(ratio) {
  if (ratio === null || ratio === undefined) return "-";
  const pct = ((ratio - 1) * 100).toFixed(1);
  return (ratio >= 1 ? "+" : "") + pct + "%";
}

let allItems = [];

async function loadKbImpact() {
  const days = document.getElementById("days-filter")?.value || "30";
  const tbody = document.getElementById("kb-body");
  if (!tbody) return;
  clearBody(tbody);
  tbody.appendChild(emptyRow(8, "読み込み中..."));
  try {
    const data = await apiFetch(`/stability/kb-impact?days=${days}`);
    allItems = data.items || data || [];
    renderTable();
  } catch (e) {
    clearBody(tbody);
    tbody.appendChild(emptyRow(8, "読み込み失敗"));
    console.error(e);
  }
}

function renderTable() {
  const tbody = document.getElementById("kb-body");
  if (!tbody) return;
  const search =
    document.getElementById("kb-search")?.value?.toLowerCase() || "";
  const filtered = allItems.filter(
    (it) => !search || (it.kb_id || "").toLowerCase().includes(search),
  );

  clearBody(tbody);
  if (filtered.length === 0) {
    tbody.appendChild(emptyRow(8, "データなし"));
    return;
  }

  filtered.forEach((item, idx) => {
    const tr = document.createElement("tr");

    // 順位
    const tdRank = document.createElement("td");
    tdRank.textContent = String(idx + 1);
    tr.appendChild(tdRank);

    // KB番号
    const tdKb = document.createElement("td");
    const a = document.createElement("a");
    a.href = "#";
    a.textContent = item.kb_id || "-";
    a.addEventListener("click", (e) => {
      e.preventDefault();
      loadKbDetail(item.kb_id, item.title);
    });
    tdKb.appendChild(a);
    tr.appendChild(tdKb);

    // タイトル
    const tdTitle = document.createElement("td");
    tdTitle.style.cssText = "font-size:0.85rem;max-width:280px;";
    tdTitle.textContent = item.title || "-";
    tr.appendChild(tdTitle);

    // 影響PC数
    const tdPc = document.createElement("td");
    tdPc.textContent = String(item.pc_count ?? "-");
    tr.appendChild(tdPc);

    // インストール前エラー
    const tdBefore = document.createElement("td");
    tdBefore.textContent = (item.before_avg ?? 0).toFixed(2);
    tr.appendChild(tdBefore);

    // インストール後エラー
    const tdAfter = document.createElement("td");
    tdAfter.textContent = (item.after_avg ?? 0).toFixed(2);
    tr.appendChild(tdAfter);

    // 変化率
    const tdRatio = document.createElement("td");
    tdRatio.style.fontWeight = "600";
    const ratio = item.change_ratio ?? 1.0;
    tdRatio.textContent = fmtChangeRatio(ratio);
    tdRatio.style.color =
      ratio >= 1.5 ? "#dc2626" : ratio >= 1.0 ? "#f59e0b" : "#16a34a";
    tr.appendChild(tdRatio);

    // リスク
    const tdRisk = document.createElement("td");
    tdRisk.appendChild(riskBadge(ratio));
    tr.appendChild(tdRisk);

    tbody.appendChild(tr);
  });
}

async function loadKbDetail(kbId, title) {
  const overlay = document.getElementById("kb-drawer-overlay");
  const titleEl = document.getElementById("kb-drawer-title");
  const bodyEl = document.getElementById("kb-drawer-body");
  if (!overlay || !bodyEl) return;

  if (titleEl) titleEl.textContent = kbId;
  bodyEl.textContent = "";

  // Loading state
  const loadingMsg = document.createElement("p");
  loadingMsg.className = "text-center";
  loadingMsg.textContent = "読み込み中...";
  bodyEl.appendChild(loadingMsg);

  overlay.classList.remove('hidden');
  document.body.style.overflow = "hidden";

  try {
    const days = document.getElementById("days-filter")?.value || "30";
    const data = await apiFetch(`/stability/kb-impact/${kbId}?days=${days}`);
    const items = data.items || data.pcs || data || [];

    bodyEl.textContent = "";

    // Summary header
    if (title) {
      const summarySection = document.createElement("div");
      const summaryTitle = document.createElement("div");
      summaryTitle.className = "drawer-section-title";
      summaryTitle.textContent = "KB タイトル";
      summarySection.appendChild(summaryTitle);
      const summaryText = document.createElement("p");
      summaryText.style.cssText =
        "font-size:0.85rem;color:var(--text-secondary);";
      summaryText.textContent = title;
      summarySection.appendChild(summaryText);
      bodyEl.appendChild(summarySection);
    }

    // PC impact table section
    const tableSection = document.createElement("div");
    const tableTitle = document.createElement("div");
    tableTitle.className = "drawer-section-title";
    tableTitle.textContent = `PC別インストール影響 (${items.length} 件)`;
    tableSection.appendChild(tableTitle);

    if (items.length === 0) {
      const noData = document.createElement("p");
      noData.className = "text-center";
      noData.textContent = "PCデータなし";
      noData.style.cssText = "color:var(--text-muted);font-size:0.85rem;";
      tableSection.appendChild(noData);
    } else {
      const table = document.createElement("table");
      table.className = "table";
      table.style.fontSize = "0.82rem";

      const thead = document.createElement("thead");
      const htr = document.createElement("tr");
      for (const h of [
        "PC名",
        "インストール日",
        "前エラー",
        "後エラー",
        "変化",
      ]) {
        const th = document.createElement("th");
        th.textContent = h;
        htr.appendChild(th);
      }
      thead.appendChild(htr);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      for (const pc of items) {
        const tr = document.createElement("tr");
        const delta = (pc.after_count ?? 0) - (pc.before_count ?? 0);

        const tdName = document.createElement("td");
        const a = document.createElement("a");
        a.href = `/pcs/${pc.pc_id}`;
        a.textContent = pc.pc_name || "PC#" + pc.pc_id;
        tdName.appendChild(a);
        tr.appendChild(tdName);

        const tdInst = document.createElement("td");
        tdInst.textContent = fmtDate(pc.installed_at);
        tr.appendChild(tdInst);

        const tdB = document.createElement("td");
        tdB.textContent = String(pc.before_count ?? "-");
        tr.appendChild(tdB);

        const tdA = document.createElement("td");
        tdA.textContent = String(pc.after_count ?? "-");
        tr.appendChild(tdA);

        const tdDelta = document.createElement("td");
        tdDelta.textContent = (delta >= 0 ? "+" : "") + delta;
        tdDelta.style.fontWeight = "600";
        tdDelta.style.color =
          delta > 0
            ? "var(--danger)"
            : delta < 0
              ? "var(--success)"
              : "inherit";
        tr.appendChild(tdDelta);

        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      tableSection.appendChild(table);
    }
    bodyEl.appendChild(tableSection);
  } catch (e) {
    bodyEl.textContent = "";
    const errMsg = document.createElement("p");
    errMsg.className = "text-center";
    errMsg.style.color = "var(--danger)";
    errMsg.textContent = "読み込み失敗";
    bodyEl.appendChild(errMsg);
    console.error(e);
  }
}

function closeKbDrawer() {
  const overlay = document.getElementById("kb-drawer-overlay");
  if (overlay) overlay.classList.add('hidden');
  document.body.style.overflow = "";
}

document.addEventListener("DOMContentLoaded", () => {
  loadKbImpact();

  document
    .getElementById("days-filter")
    ?.addEventListener("change", loadKbImpact);
  document.getElementById("kb-search")?.addEventListener("input", renderTable);
  document
    .getElementById("btn-close-kb-drawer")
    ?.addEventListener("click", closeKbDrawer);
  document
    .getElementById("btn-close-kb-drawer-footer")
    ?.addEventListener("click", closeKbDrawer);
  document
    .getElementById("kb-drawer-overlay")
    ?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeKbDrawer();
    });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeKbDrawer();
  });
});
