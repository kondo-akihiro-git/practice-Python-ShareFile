"use strict";
(() => {
const $ = (id) => document.getElementById(id);
const ICONS = { folder: "📁", image: "🖼️", pdf: "📕", video: "🎞️", text: "📄", file: "📦" };
const PAGE = 200;
const state = {
  path: "", sort: localStorage.getItem("sf.sort") || "name", order: localStorage.getItem("sf.order") || "asc",
  q: "", recursive: false, entries: [], total: 0, sig: "", current: null, maxUpload: 0, busyUploads: 0,
};

const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
};

const fmtSize = (n) => {
  if (n < 1024) return n + " B";
  const u = ["KB", "MB", "GB", "TB"]; let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < 3);
  return n.toFixed(n >= 100 ? 0 : 1) + " " + u[i];
};
const fmtTime = (t) => new Date(t * 1000).toLocaleString("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const ext = (name) => { const i = name.lastIndexOf("."); return i > 0 ? name.slice(i + 1).toUpperCase() : ""; };
const typeLabel = (e) => e.is_dir ? "フォルダ" : (ext(e.name) || "ファイル");
const join = (a, b) => a ? a + "/" + b : b;
const parentOf = (p) => p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "";
const fileUrl = (p, dl) => "/api/file?path=" + encodeURIComponent(p) + (dl ? "&download=1" : "");

let toastTimer;
function toast(msg, error = false) {
  const t = $("toast"); t.textContent = msg; t.className = "toast show" + (error ? " error" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), error ? 5000 : 2800);
}

async function api(url, opts = {}) {
  const o = { ...opts, headers: { "X-Requested-With": "ShareFile", ...(opts.headers || {}) } };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; o.method = o.method || "POST"; }
  let res;
  try { res = await fetch(url, o); } catch { throw new Error("サーバーに接続できません"); }
  let data = null;
  try { data = await res.json(); } catch { /* 本文なし */ }
  if (!res.ok) throw new Error((data && data.error) || ("エラー (" + res.status + ")"));
  return data;
}

// ---- ダイアログ ----
function openDialog(dlg) { return new Promise((resolve) => { dlg.addEventListener("close", () => resolve(dlg.returnValue), { once: true }); dlg.returnValue = "cancel"; dlg.showModal(); }); }
async function promptText(title, value = "", okLabel = "OK") {
  $("pr-title").textContent = title; $("pr-input").value = value; $("pr-ok").textContent = okLabel;
  const p = openDialog($("dlg-prompt")); setTimeout(() => { $("pr-input").focus(); $("pr-input").select(); }, 50);
  return (await p) === "ok" ? $("pr-input").value.trim() : null;
}
async function choose(title, msg, buttons) {
  $("cf-title").textContent = title; $("cf-msg").textContent = msg;
  const box = $("cf-actions"); box.replaceChildren(...buttons.map((b) => h("button", { value: b.value, class: "btn " + (b.cls || "") }, b.label)));
  return openDialog($("dlg-confirm"));
}
async function pickFolder(title, exclude = []) {
  const { dirs } = await api("/api/dirs");
  const sel = $("mv-dest"); $("mv-title").textContent = title;
  sel.replaceChildren(...dirs.filter((d) => !exclude.some((x) => d === x || d.startsWith(x + "/"))).map((d) => h("option", { value: d }, "/" + d)));
  const r = await openDialog($("dlg-move"));
  return r === "ok" ? sel.value : null;
}

// ---- 一覧 ----
function renderCrumbs() {
  const nav = $("crumbs"); nav.replaceChildren();
  const parts = state.path ? state.path.split("/") : [];
  const items = [["共有フォルダ", ""]]; let acc = "";
  for (const p of parts) { acc = join(acc, p); items.push([p, acc]); }
  items.forEach(([label, p], i) => {
    if (i) nav.append(h("span", { class: "sep" }, "›"));
    if (i === items.length - 1) nav.append(h("span", { class: "cur" }, label));
    else nav.append(h("button", { onclick: () => go(p) }, i === 0 ? "🏠 " + label : label));
  });
  if (parts.length) nav.append(h("button", { onclick: () => go(parentOf(state.path)), title: "上位フォルダへ" }, "⬆ 上へ"));
}

function renderList() {
  const ul = $("list"); ul.replaceChildren();
  if (!state.entries.length) ul.append(h("li", { class: "empty" }, state.q ? "一致するファイルがありません" : "このフォルダは空です"));
  for (const e of state.entries) {
    const open = () => e.is_dir ? go(e.path) : openDetail(e);
    const where = state.q && state.recursive ? " ・ /" + parentOf(e.path) : "";
    const row = h("li", { class: "row" },
      h("button", { class: "main", onclick: open },
        h("span", { class: "ic", "aria-hidden": "true" }, ICONS[e.kind] || ICONS.file),
        h("span", { class: "txt" },
          h("div", { class: "name" }, e.name),
          h("div", { class: "meta" }, [typeLabel(e), e.is_dir ? null : fmtSize(e.size), fmtTime(e.mtime)].filter(Boolean).join(" ・ ") + where))),
      h("div", { class: "acts" },
        e.is_dir ? null : h("a", { class: "act", href: fileUrl(e.path, true), title: "ダウンロード", "aria-label": "ダウンロード" }, "⬇"),
        h("button", { class: "act", title: "名前変更", "aria-label": "名前変更", onclick: () => doRename(e) }, "✏"),
        h("button", { class: "act", title: "移動", "aria-label": "移動", onclick: () => doMove(e) }, "📂"),
        h("button", { class: "act del", title: "削除", "aria-label": "削除", onclick: () => doDelete(e) }, "🗑")),
      h("button", { class: "act ovf", "aria-label": "操作メニュー", onclick: () => openDetail(e) }, "⋯"));
    ul.append(row);
  }
  $("more").hidden = state.entries.length >= state.total;
  $("status").textContent = state.total + " 件" + (state.q ? "（検索: " + state.q + "）" : "");
}

async function load({ silent = false, append = false } = {}) {
  const params = new URLSearchParams({ path: state.path, sort: state.sort, order: state.order, q: state.q, recursive: state.recursive ? "1" : "0", offset: append ? state.entries.length : 0, limit: PAGE });
  const keep = append ? 0 : Math.max(state.entries.length, PAGE);
  if (silent && !append) params.set("limit", keep);
  try {
    const d = await api("/api/list?" + params);
    const sig = JSON.stringify([d.total, d.entries]);
    if (append) { state.entries = state.entries.concat(d.entries); state.total = d.total; renderList(); return; }
    if (silent && sig === state.sig) return;
    state.sig = sig; state.entries = d.entries; state.total = d.total;
    renderCrumbs(); renderList();
  } catch (err) {
    if (silent) return;
    if (state.path) { state.path = ""; syncHash(); return load(); }
    $("status").textContent = err.message; toast(err.message, true);
  }
}

function syncHash() { const want = state.path ? "#/" + state.path.split("/").map(encodeURIComponent).join("/") : "#/"; if (location.hash !== want) history.pushState(null, "", want); }
function pathFromHash() { try { return location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent).join("/"); } catch { return ""; } }
function go(p) { state.path = p; state.q = ""; $("search").value = ""; state.sig = ""; syncHash(); load(); }
window.addEventListener("popstate", () => { state.path = pathFromHash(); load(); });

// ---- 詳細・プレビュー ----
async function openDetail(e) {
  state.current = e;
  $("pv-name").textContent = e.name; $("pv-info").textContent = "";
  const body = $("pv-body"); body.replaceChildren();
  const url = fileUrl(e.path);
  $("pv-download").hidden = e.is_dir; $("pv-download").href = fileUrl(e.path, true); $("pv-download").setAttribute("download", e.name);
  $("pv-hash").hidden = false;
  if (e.is_dir) body.append(h("div", { class: "nopv" }, "📁 フォルダ"));
  else if (e.kind === "image") {
    const img = h("img", { src: url, alt: e.name });
    img.addEventListener("error", () => body.replaceChildren(h("div", { class: "nopv" }, "このブラウザではこの画像形式を表示できません（HEICなど）。ダウンロードしてご確認ください。")));
    body.append(img);
  } else if (e.kind === "video") body.append(h("video", { src: url, controls: "", playsinline: "", preload: "metadata" }));
  else if (e.kind === "pdf") body.append(h("iframe", { src: url, title: e.name }), h("div", { class: "nopv" }, h("a", { href: url, target: "_blank", rel: "noopener" }, "表示されない場合は新しいタブで開く")));
  else if (e.kind === "text") {
    const pre = h("pre", {}, "読み込み中…"); body.append(pre);
    try { const r = await fetch(url, { headers: { Range: "bytes=0-524287" } }); pre.textContent = await r.text(); if (e.size > 524288) pre.append("\n\n…（先頭512KBのみ表示）"); }
    catch { pre.textContent = "読み込めませんでした"; }
  } else body.append(h("div", { class: "nopv" }, "このファイル形式はプレビューできません。ダウンロードしてご利用ください。"));
  $("pv-info").textContent = `${typeLabel(e)} ・ ${e.is_dir ? "" : fmtSize(e.size) + " ・ "}${fmtTime(e.mtime)} ・ /${e.path}`;
  if (!$("dlg-preview").open) $("dlg-preview").showModal();
}
function closeDetail() { const d = $("dlg-preview"); if (d.open) d.close(); $("pv-body").replaceChildren(); }
$("pv-close").onclick = closeDetail;
$("dlg-preview").addEventListener("click", (ev) => { if (ev.target === $("dlg-preview")) closeDetail(); });
$("pv-hash").onclick = async () => {
  const e = state.current; $("pv-info").textContent = "計算中…";
  try {
    const d = await api("/api/info?hash=1&path=" + encodeURIComponent(e.path));
    $("pv-info").textContent = d.is_dir ? `フォルダ内 ${d.item_count} 件 ・ /${d.path}` : `${fmtSize(d.size)} ・ ${fmtTime(d.mtime)} ・ /${d.path} ・ SHA-256: ${d.sha256}`;
  } catch (err) { $("pv-info").textContent = err.message; }
};
$("pv-rename").onclick = () => doRename(state.current);
$("pv-move").onclick = () => doMove(state.current);
$("pv-delete").onclick = () => doDelete(state.current);

// ---- 変更操作 ----
async function doRename(e) {
  const name = await promptText("新しい名前", e.name, "変更");
  if (!name || name === e.name) return;
  try { await api("/api/rename", { json: { path: e.path, name } }); closeDetail(); toast("名前を変更しました"); await load(); } catch (err) { toast(err.message, true); }
}
async function doMove(e) {
  try {
    const dest = await pickFolder(`「${e.name}」の移動先`, e.is_dir ? [e.path] : []);
    if (dest === null) return;
    await api("/api/move", { json: { paths: [e.path], dest } }); closeDetail(); toast("移動しました"); await load();
  } catch (err) { toast(err.message, true); }
}
async function doDelete(e) {
  let msg = `「${e.name}」を削除します。`;
  if (e.is_dir) {
    try { const d = await api("/api/info?path=" + encodeURIComponent(e.path)); msg = `フォルダ「${e.name}」を削除します。フォルダ内のファイルとサブフォルダ（${d.item_count}件）もすべて削除されます。`; }
    catch (err) { return toast(err.message, true); }
  }
  msg += "（削除したものはUbuntu側のtrashフォルダに移動されます）";
  const r = await choose("削除の確認", msg, [{ value: "cancel", label: "キャンセル" }, { value: "ok", label: "削除する", cls: "danger solid" }]);
  if (r !== "ok") return;
  try { await api("/api/delete", { json: { path: e.path, confirm: true } }); closeDetail(); toast("削除しました"); await load(); } catch (err) { toast(err.message, true); }
}
$("btn-mkdir").onclick = async () => {
  const name = await promptText("新しいフォルダ名", "", "作成");
  if (!name) return;
  try { await api("/api/mkdir", { json: { path: state.path, name } }); toast("フォルダを作成しました"); await load(); } catch (err) { toast(err.message, true); }
};

// ---- アップロード ----
async function openUploadDialog(files) {
  try {
    const { dirs } = await api("/api/dirs");
    $("up-dest").replaceChildren(...dirs.map((d) => h("option", { value: d, selected: d === state.path ? "" : false }, "/" + d)));
    $("up-dest").value = state.path;
  } catch (err) { return toast(err.message, true); }
  $("up-newdir").value = ""; $("up-files").value = "";
  if (files) { try { const dt = new DataTransfer(); [...files].forEach((f) => dt.items.add(f)); $("up-files").files = dt.files; } catch { /* 非対応環境 */ } }
  if ((await openDialog($("dlg-upload"))) !== "ok") return;
  const picked = [...$("up-files").files];
  if (!picked.length) return toast("ファイルが選択されていません", true);
  let dest = $("up-dest").value; const nd = $("up-newdir").value.trim();
  if (nd) {
    try { await api("/api/mkdir", { json: { path: dest, name: nd } }); } catch (err) { if (!/既に存在/.test(err.message)) return toast(err.message, true); }
    dest = join(dest, nd);
  }
  startUploads(picked, dest);
}
$("btn-upload").onclick = () => openUploadDialog();

let queue = Promise.resolve();
function startUploads(files, dest) {
  const box = $("uploads"); box.hidden = false;
  for (const f of files) {
    const item = { bar: h("i"), msg: h("div", { class: "msg" }, "待機中"), pct: h("span", {}, "0%") };
    const el = h("div", { class: "up-item" }, h("div", { class: "t" }, h("span", {}, f.name), item.pct), h("div", { class: "bar" }, item.bar), item.msg);
    box.append(el);
    state.busyUploads++;
    queue = queue.then(() => uploadOne(f, dest, el, item)).catch(() => {}).finally(() => { state.busyUploads--; if (!state.busyUploads) finishBatch(box); });
  }
}
function finishBatch(box) {
  load({ silent: true });
  const errs = box.querySelectorAll(".up-item.err").length, oks = box.querySelectorAll(".up-item.done").length;
  toast(errs ? `アップロード完了 ${oks}件 / 失敗 ${errs}件` : `アップロード完了（${oks}件）`, !!errs);
  box.append(h("button", { class: "btn", onclick: () => { box.hidden = true; box.replaceChildren(); } }, "閉じる"));
}

function sendXhr(f, dest, mode, item) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/upload?dir=${encodeURIComponent(dest)}&name=${encodeURIComponent(f.name)}&mode=${mode}`);
    xhr.setRequestHeader("X-Requested-With", "ShareFile");
    xhr.setRequestHeader("X-Last-Modified", String(f.lastModified || 0));
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) { const p = Math.floor(ev.loaded / ev.total * 100); item.bar.style.width = p + "%"; item.pct.textContent = p + "%"; item.msg.textContent = `${fmtSize(ev.loaded)} / ${fmtSize(ev.total)}`; } };
    xhr.onerror = () => reject(new Error("通信エラー（ネットワークが切断された可能性があります）"));
    xhr.ontimeout = () => reject(new Error("タイムアウト"));
    xhr.onabort = () => reject(new Error("中断されました"));
    xhr.onload = () => { let d = null; try { d = JSON.parse(xhr.responseText); } catch { /* */ } resolve({ status: xhr.status, data: d }); };
    xhr.send(f);
  });
}

async function localHash(f) {
  if (!(window.crypto && crypto.subtle) || f.size > 100 * 1024 * 1024) return null;
  try { const buf = await crypto.subtle.digest("SHA-256", await f.arrayBuffer()); return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join(""); } catch { return null; }
}

async function uploadOne(f, dest, el, item) {
  try {
    if (state.maxUpload && f.size > state.maxUpload) throw new Error(`ファイルが大きすぎます（上限 ${fmtSize(state.maxUpload)}）`);
    let mode = "fail";
    item.msg.textContent = "送信中…";
    let res = await sendXhr(f, dest, mode, item);
    if (res.status === 409 && /同名のファイル/.test(res.data?.error || "")) {
      const r = await choose("同じ名前のファイルがあります", `「${f.name}」は既に存在します。どうしますか？`, [
        { value: "cancel", label: "スキップ" }, { value: "rename", label: "別名で保存" }, { value: "overwrite", label: "上書き", cls: "danger" }]);
      if (r === "cancel") { el.classList.add("err"); item.msg.textContent = "スキップしました"; return; }
      mode = r; item.bar.style.width = "0"; res = await sendXhr(f, dest, mode, item);
    }
    if (res.status !== 201) throw new Error(res.data?.error || `アップロード失敗 (${res.status})`);
    item.bar.style.width = "100%"; item.pct.textContent = "100%";
    const local = await localHash(f);
    const check = local === null ? "" : local === res.data.sha256 ? " ✔ SHA-256一致" : " ⚠ SHA-256が一致しません";
    if (local !== null && local !== res.data.sha256) throw new Error("SHA-256が一致しません。再送してください");
    el.classList.add("done"); item.msg.textContent = `完了: ${res.data.name} (${fmtSize(res.data.size)})${check} sha256:${res.data.sha256.slice(0, 12)}…`;
  } catch (err) { el.classList.add("err"); item.msg.textContent = err.message; item.pct.textContent = "失敗"; }
}

// ドラッグ&ドロップ（PC）
let dragDepth = 0;
addEventListener("dragenter", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { dragDepth++; $("dropzone").hidden = false; } });
addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("dropzone").hidden = true; } });
addEventListener("dragover", (e) => e.preventDefault());
addEventListener("drop", (e) => { e.preventDefault(); dragDepth = 0; $("dropzone").hidden = true; if (e.dataTransfer?.files?.length) startUploads([...e.dataTransfer.files], state.path); });

// ---- 検索・並び替え・更新 ----
let st;
$("search").addEventListener("input", (e) => { clearTimeout(st); st = setTimeout(() => { state.q = e.target.value; load(); }, 250); });
$("recursive").onchange = (e) => { state.recursive = e.target.checked; if (state.q) load(); };
$("sort").value = state.sort;
$("sort").onchange = (e) => { state.sort = e.target.value; localStorage.setItem("sf.sort", state.sort); load(); };
const orderLabel = () => { $("order").textContent = state.order === "asc" ? "↑ 昇順" : "↓ 降順"; };
orderLabel();
$("order").onclick = () => { state.order = state.order === "asc" ? "desc" : "asc"; localStorage.setItem("sf.order", state.order); orderLabel(); load(); };
$("btn-refresh").onclick = () => load().then(() => toast("更新しました"));
$("more").onclick = () => load({ append: true });
$("pr-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("dlg-prompt").close("ok"); } });

// Ubuntu側の変更を反映するため定期的に再取得
setInterval(() => { if (document.visibilityState === "visible" && !document.querySelector("dialog[open]") && !state.busyUploads) load({ silent: true }); }, 5000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load({ silent: true }); });

(async () => {
  try { state.maxUpload = (await api("/api/config")).max_upload_bytes; } catch { /* 一覧取得時にエラー表示 */ }
  state.path = pathFromHash(); renderCrumbs(); load();
})();
})();
