const SEVERITY_MAP = {
  critical: { cls: "severity-critical", label: "危険" },
  warning: { cls: "severity-high", label: "警告" },
  info: { cls: "severity-low", label: "情報" },
};

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

function severityBadge(sev) {
  const meta = SEVERITY_MAP[sev] || SEVERITY_MAP.info;
  const span = document.createElement("span");
  span.className = "status-badge " + meta.cls;
  span.textContent = meta.label;
  return span;
}

function severityRank(sev) {
  return sev === "critical" ? 0 : sev === "warning" ? 1 : 2;
}

let allItems = [];
let currentPage = 1;
const PER_PAGE = 30;

async function loadDiskHealth() {
  const tbody = document.getElementById("disk-body");
  if (!tbody) return;
  clearBody(tbody);
  tbody.appendChild(emptyRow(8, "読み込み中..."));
  try {
    const data = await apiFetch(`/stability/disk-health?flat=1`);
    allItems = (data.items || data || []).sort((a, b) => {
      const sa = severityRank(a.severity || "info");
      const sb = severityRank(b.severity || "info");
      if (sa !== sb) return sa - sb;
      return new Date(b.occurred_at || 0) - new Date(a.occurred_at || 0);
    });
    updateStats();
    currentPage = 1;
    renderPage();
  } catch (e) {
    clearBody(tbody);
    tbody.appendChild(emptyRow(8, "読み込み失敗"));
    console.error(e);
  }
}

function updateStats() {
  let total = allItems.length;
  let critical = 0,
    warning = 0;
  const pcSet = new Set();
  for (const it of allItems) {
    if (it.severity === "critical") critical++;
    else if (it.severity === "warning") warning++;
    if (it.pc_id != null) pcSet.add(it.pc_id);
  }
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };
  set("stat-total-events", total);
  set("stat-critical-events", critical);
  set("stat-warning-events", warning);
  set("stat-affected-pcs", pcSet.size);
}

function renderPage() {
  const tbody = document.getElementById("disk-body");
  const paginationEl = document.getElementById("disk-pagination");
  if (!tbody) return;

  const searchVal =
    document.getElementById("pc-search")?.value?.toLowerCase() || "";
  const sevFilter = document.getElementById("severity-filter")?.value || "";
  const filtered = allItems.filter((it) => {
    if (sevFilter && (it.severity || "") !== sevFilter) return false;
    if (searchVal && !(it.pc_name || "").toLowerCase().includes(searchVal))
      return false;
    return true;
  });

  clearBody(tbody);
  if (filtered.length === 0) {
    tbody.appendChild(emptyRow(8, "データなし"));
    if (paginationEl) paginationEl.textContent = "";
    return;
  }

  const start = (currentPage - 1) * PER_PAGE;
  const page = filtered.slice(start, start + PER_PAGE);

  for (const item of page) {
    const tr = document.createElement("tr");

    const tdName = document.createElement("td");
    const a = document.createElement("a");
    a.href = `/pcs/${item.pc_id}`;
    a.textContent = item.pc_name || "PC#" + item.pc_id;
    tdName.appendChild(a);
    tr.appendChild(tdName);

    const tdEvent = document.createElement("td");
    tdEvent.textContent = String(item.event_id ?? "-");
    tr.appendChild(tdEvent);

    const tdSrc = document.createElement("td");
    tdSrc.textContent = item.source || "-";
    tr.appendChild(tdSrc);

    const tdDisk = document.createElement("td");
    tdDisk.textContent = item.disk || item.disk_name || "-";
    tr.appendChild(tdDisk);

    const tdSev = document.createElement("td");
    tdSev.appendChild(severityBadge(item.severity || "info"));
    tr.appendChild(tdSev);

    const tdMsg = document.createElement("td");
    tdMsg.style.cssText = "font-size:0.8rem;max-width:320px;";
    tdMsg.textContent = item.message || "-";
    tr.appendChild(tdMsg);

    const tdOccur = document.createElement("td");
    tdOccur.textContent = fmtDate(item.occurred_at);
    tr.appendChild(tdOccur);

    const tdCollect = document.createElement("td");
    tdCollect.textContent = fmtDate(item.collected_at);
    tr.appendChild(tdCollect);

    tr.classList.add("row-clickable");
    tr.addEventListener("click", () => openDiskDrawer(item));

    tbody.appendChild(tr);
  }

  if (paginationEl) {
    paginationEl.textContent = "";
    const totalPages = Math.ceil(filtered.length / PER_PAGE);
    if (totalPages > 1) {
      for (let p = 1; p <= totalPages; p++) {
        const btn = document.createElement("button");
        btn.className =
          "btn " + (p === currentPage ? "btn-primary" : "btn-secondary");
        btn.style.cssText = "margin:0.1rem;padding:0.2rem 0.6rem;";
        btn.textContent = String(p);
        btn.addEventListener("click", () => {
          currentPage = p;
          renderPage();
        });
        paginationEl.appendChild(btn);
      }
    }
  }
}

function exportCsv() {
  const rows = [
    [
      "PC名",
      "イベントID",
      "ソース",
      "ディスク",
      "重大度",
      "メッセージ",
      "発生日時",
      "収集日時",
    ],
  ];
  for (const it of allItems) {
    const sevMeta = SEVERITY_MAP[it.severity] || SEVERITY_MAP.info;
    rows.push([
      it.pc_name || "",
      String(it.event_id ?? ""),
      it.source || "",
      it.disk || it.disk_name || "",
      sevMeta.label,
      (it.message || "").replace(/[\r\n]+/g, " "),
      it.occurred_at || "",
      it.collected_at || "",
    ]);
  }
  const csv = rows
    .map((r) =>
      r.map((v) => '"' + String(v).replace(/"/g, '""') + '"').join(","),
    )
    .join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "disk_health.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ── Drawer ──────────────────────────────────────────────────────────────────

function openDiskDrawer(item) {
  const overlay = document.getElementById("disk-drawer-overlay");
  const titleEl = document.getElementById("disk-drawer-title");
  const bodyEl = document.getElementById("disk-drawer-body");
  const pcLink = document.getElementById("disk-drawer-pc-link");
  if (!overlay || !bodyEl) return;

  const sevMeta = SEVERITY_MAP[item.severity] || SEVERITY_MAP.info;

  if (titleEl) {
    titleEl.textContent = "";
    const badge = severityBadge(item.severity || "info");
    titleEl.appendChild(badge);
    titleEl.appendChild(
      document.createTextNode(" " + (item.pc_name || "PC#" + item.pc_id)),
    );
  }
  if (pcLink) pcLink.href = `/pcs/${item.pc_id}`;

  bodyEl.textContent = "";

  // Event details section
  const detailSection = document.createElement("div");
  const detailTitle = document.createElement("div");
  detailTitle.className = "drawer-section-title";
  detailTitle.textContent = "イベント詳細";
  detailSection.appendChild(detailTitle);

  const dl = document.createElement("dl");
  dl.className = "kv-grid";
  const pairs = [
    ["イベントID", String(item.event_id ?? "-")],
    ["ソース", item.source || "-"],
    ["ディスク", item.disk || item.disk_name || "-"],
    ["重大度", sevMeta.label],
    ["発生日時", fmtDate(item.occurred_at)],
    ["収集日時", fmtDate(item.collected_at)],
  ];
  for (const [k, v] of pairs) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    dl.appendChild(dt);
    const dd = document.createElement("dd");
    dd.textContent = v;
    dl.appendChild(dd);
  }
  detailSection.appendChild(dl);
  bodyEl.appendChild(detailSection);

  // Full message
  if (item.message) {
    const msgSection = document.createElement("div");
    const msgTitle = document.createElement("div");
    msgTitle.className = "drawer-section-title";
    msgTitle.textContent = "メッセージ全文";
    msgSection.appendChild(msgTitle);

    const pre = document.createElement("pre");
    pre.style.cssText =
      "font-size:0.78rem;white-space:pre-wrap;word-break:break-word;" +
      "background:var(--bg-tertiary);border:1px solid var(--border);" +
      "border-radius:var(--radius);padding:0.75rem;color:var(--text-secondary);";
    pre.textContent = item.message;
    msgSection.appendChild(pre);
    bodyEl.appendChild(msgSection);
  }

  overlay.classList.remove('hidden');
  document.body.style.overflow = "hidden";
}

function closeDiskDrawer() {
  const overlay = document.getElementById("disk-drawer-overlay");
  if (overlay) overlay.classList.add('hidden');
  document.body.style.overflow = "";
}

document.addEventListener("DOMContentLoaded", () => {
  loadDiskHealth();

  document.getElementById("pc-search")?.addEventListener("input", () => {
    currentPage = 1;
    renderPage();
  });
  document.getElementById("severity-filter")?.addEventListener("change", () => {
    currentPage = 1;
    renderPage();
  });
  document
    .getElementById("btn-export-csv")
    ?.addEventListener("click", exportCsv);

  document
    .getElementById("btn-close-disk-drawer")
    ?.addEventListener("click", closeDiskDrawer);
  document
    .getElementById("disk-drawer-overlay")
    ?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeDiskDrawer();
    });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDiskDrawer();
  });
});
