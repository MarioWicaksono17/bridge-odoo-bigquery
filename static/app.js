"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (r.status === 401) {           // sesi berakhir → kembali ke halaman login
    window.location = "/login";
    throw new Error("Sesi berakhir. Mengalihkan ke halaman login…");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
};
const jpost = (url, body) => api(url, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

let ACTOR = localStorage.getItem("bridge_actor") || "";
if (!ACTOR) { ACTOR = prompt("Nama Anda (untuk catatan siapa yang mengubah saklar):", "") || "anonim"; localStorage.setItem("bridge_actor", ACTOR); }

function toast(msg, kind = "") {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show " + kind;
  setTimeout(() => t.className = "toast", 2600);
}
function fmtTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
function relTime(iso) {
  if (!iso) return "belum pernah";
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return "baru saja";
  if (diff < 3600) return `${Math.floor(diff / 60)} menit lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`;
  return `${Math.floor(diff / 86400)} hari lalu`;
}

/* ============================================================ STATUS + SAKLAR */
async function refreshStatus() {
  let s;
  try { s = await api("/api/status"); }
  catch (e) { setConn(false, e.message); return; }

  setConn(s.connection.ok, s.connection.error);

  const on = s.control.enabled;
  $("#pulse_dot").className = "pulse " + (on ? "on" : "off");
  $("#hero_label").textContent = on ? "Sinkronisasi Otomatis Aktif" : "Sinkronisasi Otomatis Berhenti";
  const by = s.control.updated_by ? ` oleh ${s.control.updated_by}` : "";
  let sub = s.control.updated_at ? `diubah ${relTime(s.control.updated_at)}${by}` : "belum pernah diubah";
  if (s.schedule && s.schedule.next_run_iso) {
    sub += ` · penarikan terjadwal berikutnya ${fmtTime(s.schedule.next_run_iso)}`;
  }
  $("#hero_sub").textContent = sub;
  $("#btn_start").disabled = on;
  $("#btn_stop").disabled = !on;

  const last = s.last_run;
  if (last) {
    $("#sum_sukses").textContent = last.sukses ?? 0;
    $("#sum_gagal").textContent = last.gagal ?? 0;
    $("#sum_dilewati").textContent = last.dilewati ?? 0;
    $("#sum_baris").textContent = (last.total_baris ?? 0).toLocaleString("id-ID");
    $("#sum_waktu").textContent = `${relTime(last.waktu_mulai)} · ${last.dipicu_oleh || "-"}`;
  }

  // sinkronkan tombol run-now dengan proses background
  const running = s.run_now.running;
  $("#btn_run_now").disabled = running;
  $("#btn_run_now").textContent = running ? "⏳ Sedang menarik…" : "↻ Jalankan Sekarang";
  if (running) pollRunNow();
}

function setConn(ok, err) {
  $("#conn_dot").className = "dot " + (ok ? "on" : "off");
  $("#conn_text").textContent = ok ? "BigQuery terhubung" : ("terputus" + (err ? ": " + err.slice(0, 60) : ""));
}

$("#btn_start").onclick = () => setControl(true);
$("#btn_stop").onclick = () => setControl(false);
async function setControl(enabled) {
  try {
    await jpost("/api/control", { enabled, actor: ACTOR });
    toast(enabled ? "Sinkronisasi otomatis dinyalakan" : "Sinkronisasi otomatis dihentikan", "ok");
    refreshStatus();
  } catch (e) { toast(e.message, "err"); }
}

/* ============================================================ JALANKAN SEKARANG */
let runNowTimer = null;
$("#btn_run_now").onclick = async () => {
  try {
    $("#btn_run_now").disabled = true;
    $("#runlog_card").hidden = false;
    $("#runlog_title").textContent = "Menjalankan…";
    $("#runlog_pre").textContent = "Memulai…\n";
    await jpost("/api/run-now", {});
    pollRunNow();
  } catch (e) {
    toast(e.message, "err");
    $("#btn_run_now").disabled = false;
  }
};
$("#runlog_close").onclick = () => $("#runlog_card").hidden = true;

function pollRunNow() {
  if (runNowTimer) return;
  runNowTimer = setInterval(async () => {
    let s;
    try { s = await api("/api/run-now/status"); } catch { return; }
    $("#runlog_card").hidden = false;
    $("#runlog_pre").textContent = (s.logs || []).join("\n");
    $("#runlog_pre").scrollTop = $("#runlog_pre").scrollHeight;
    if (!s.running) {
      clearInterval(runNowTimer); runNowTimer = null;
      $("#btn_run_now").disabled = false;
      $("#btn_run_now").textContent = "↻ Jalankan Sekarang";
      $("#runlog_title").textContent = s.error ? "Selesai dengan error" : "Selesai";
      toast(s.error ? ("Gagal: " + s.error) : "Penarikan selesai", s.error ? "err" : "ok");
      refreshStatus(); loadLogs();
    }
  }, 2000);
}

/* ============================================================ PEMILIH KOLOM */
let CATALOG = null;
async function loadCatalog() {
  CATALOG = await api("/api/catalog");
  const proj = CATALOG.bigquery.project_id || "(project)";
  const dataset = CATALOG.bigquery.dataset;
  const wrap = $("#modules"); wrap.innerHTML = "";
  CATALOG.modules.forEach((m, idx) => wrap.appendChild(moduleCard(m, idx, proj, dataset)));
  buildModulTabs();
}

function moduleCard(m, idx, proj, dataset) {
  const el = document.createElement("div");
  el.className = "mod" + (idx === 0 ? " open" : "");
  const selCount = Object.keys(m.selected).length;
  const total = m.available.length;

  el.innerHTML = `
    <div class="mod-head">
      <span class="mod-caret">▶</span>
      <span class="mod-title">${m.label}</span>
      <span class="mod-model">${m.model}</span>
      <span class="mod-count"><b class="selc">${selCount}</b> / ${total}</span>
    </div>
    <div class="mod-body">
      <div class="mod-table-id">Tabel tujuan: <b>${proj}.${dataset}.${m.table}</b></div>
      <div class="mod-tools">
        <input type="text" class="mod-search" placeholder="Cari kolom…" />
        <button class="link act-all">centang semua</button>
        <button class="link act-none">kosongkan</button>
        <label class="chk"><input type="checkbox" class="only-sel" /> hanya dipilih</label>
        <button class="link act-reset">reset default</button>
      </div>
      <div class="cols"></div>
      <div class="mod-actions">
        <button class="btn btn-accent sm act-save">Simpan</button>
      </div>
    </div>`;

  const head = $(".mod-head", el);
  head.onclick = (e) => { if (!e.target.closest("button,input,label")) el.classList.toggle("open"); };

  const colsWrap = $(".cols", el);
  const state = {}; // name -> {checked, rename}
  m.available.forEach(c => {
    const inSel = c.name in m.selected;
    state[c.name] = { checked: inSel, rename: inSel ? m.selected[c.name] : c.name, col: c };
  });

  function render() {
    const term = $(".mod-search", el).value.toLowerCase().trim();
    const onlySel = $(".only-sel", el).checked;
    colsWrap.innerHTML = "";
    m.available.forEach(c => {
      const st = state[c.name];
      if (onlySel && !st.checked) return;
      if (term && !(c.label.toLowerCase().includes(term) || c.name.toLowerCase().includes(term))) return;
      const row = document.createElement("div");
      row.className = "col-row" + (c.loadable ? "" : " disabled");
      const useBadge = c.in_use ? `<span class="badge badge-use">dipakai</span>` : "";
      const typeBadge = c.type ? `<span class="badge badge-type">${c.type}</span>` : "";
      row.innerHTML = `
        <input type="checkbox" ${st.checked ? "checked" : ""} ${c.loadable ? "" : "disabled"} />
        <div class="col-info">
          <div class="cname">${c.label} ${useBadge}</div>
          <div class="ctech">${c.name} ${typeBadge} ${c.note || ""}</div>
        </div>
        <div class="col-rename"><input type="text" value="${st.rename}" placeholder="nama di BigQuery" /></div>`;
      const [chk, , rn] = [$("input[type=checkbox]", row), null, $("input[type=text]", row)];
      chk.onchange = () => { st.checked = chk.checked; updateCount(); };
      rn.oninput = () => { st.rename = rn.value.trim() || c.name; };
      colsWrap.appendChild(row);
    });
  }
  function updateCount() {
    const n = Object.values(state).filter(s => s.checked).length;
    $(".selc", el).textContent = n;
  }

  $(".mod-search", el).oninput = render;
  $(".only-sel", el).onchange = render;
  $(".act-all", el).onclick = () => { m.available.forEach(c => { if (c.loadable) state[c.name].checked = true; }); updateCount(); render(); };
  $(".act-none", el).onclick = () => { Object.values(state).forEach(s => s.checked = false); updateCount(); render(); };
  $(".act-reset", el).onclick = async () => {
    await jpost("/api/modules/reset", { key: m.key });
    toast("Direset ke default", "ok"); loadCatalog();
  };
  $(".act-save", el).onclick = async () => {
    const selected = {};
    Object.entries(state).forEach(([name, s]) => { if (s.checked) selected[name] = s.rename; });
    if (!Object.keys(selected).length) { toast("Pilih minimal 1 kolom", "err"); return; }
    try { await jpost("/api/modules/save", { key: m.key, selected }); toast(`${m.label} tersimpan`, "ok"); }
    catch (e) { toast(e.message, "err"); }
  };

  render();
  return el;
}

/* ============================================================ RIWAYAT */
let curModul = "semua";
function buildModulTabs() {
  const tabs = $("#modul_tabs");
  tabs.innerHTML = `<button class="tab is-active" data-modul="semua">Semua</button>`;
  CATALOG.modules.forEach(m => {
    const b = document.createElement("button");
    b.className = "tab"; b.dataset.modul = m.key; b.textContent = m.label;
    tabs.appendChild(b);
  });
  $$(".tab", tabs).forEach(t => t.onclick = () => {
    $$(".tab", tabs).forEach(x => x.classList.remove("is-active"));
    t.classList.add("is-active"); curModul = t.dataset.modul; loadLogs();
  });
}

async function loadLogs() {
  const q = $("#search").value.trim();
  const params = new URLSearchParams({ modul: curModul });
  if (q) params.set("q", q);
  let data;
  try { data = await api("/api/logs?" + params); } catch { return; }
  const body = $("#log_body"); body.innerHTML = "";
  $("#row_count").textContent = `Menampilkan ${data.count} riwayat`;
  if (!data.rows.length) {
    body.innerHTML = `<tr><td colspan="9" class="empty">Belum ada riwayat penarikan.</td></tr>`;
    return;
  }
  data.rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="tbl-mono">${fmtTime(r.waktu_mulai)}</td>
      <td>${r.label_modul || r.modul}</td>
      <td class="tbl-mono">${r.tabel_tujuan || "–"}</td>
      <td class="tbl-mono">${r.mode || "–"}</td>
      <td><span class="pill pill-${r.status}">${r.status}</span></td>
      <td class="num">${(r.jumlah_baris ?? 0).toLocaleString("id-ID")}</td>
      <td class="num">${r.durasi_detik != null ? r.durasi_detik.toFixed(1) + "s" : "–"}</td>
      <td>${r.dipicu_oleh || "–"}</td>
      <td class="muted sm">${r.pesan || "–"}</td>`;
    body.appendChild(tr);
  });
}

let searchTimer;
$("#search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadLogs, 350); };
$("#btn_refresh").onclick = loadLogs;

/* ============================================================ HAPUS / MODAL */
let confirmAction = null;
function askConfirm(title, body, action) {
  $("#confirm_title").textContent = title;
  $("#confirm_body").textContent = body;
  $("#confirm_text").value = "";
  $("#confirm_modal").hidden = false;
  confirmAction = action;
}
$("#confirm_cancel").onclick = () => $("#confirm_modal").hidden = true;
$("#confirm_ok").onclick = async () => {
  if ($("#confirm_text").value !== "HAPUS") { toast("Ketik HAPUS untuk konfirmasi", "err"); return; }
  $("#confirm_modal").hidden = true;
  try { await confirmAction(); } catch (e) { toast(e.message, "err"); }
};
$("#btn_clear_log").onclick = () => askConfirm(
  "Hapus semua riwayat?", "Menghapus seluruh isi pipeline_run_log. Tidak memengaruhi data staging maupun Odoo.",
  async () => { await jpost("/api/logs/clear", { confirm: "HAPUS" }); toast("Riwayat dihapus", "ok"); loadLogs(); });
$("#btn_clear_data").onclick = () => askConfirm(
  "Kosongkan tabel staging?", "Mengosongkan crm_lead_staging, customer_invoice_staging, vendor_bill_staging di BigQuery. Data Odoo tidak tersentuh.",
  async () => { await jpost("/api/data/clear", { confirm: "HAPUS" }); toast("Tabel staging dikosongkan", "ok"); });

/* ============================================================ INIT */
async function init() {
  await loadCatalog();
  await refreshStatus();
  await loadLogs();
  setInterval(() => { if ($("#auto_refresh").checked) { refreshStatus(); loadLogs(); } }, 8000);
}
init();
