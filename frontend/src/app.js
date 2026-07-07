/* fotorganize UI — vanilla JS hash router. No build step (see DECISIONS.md). */
const $ = (s, el = document) => el.querySelector(s);
const content = $("#content");

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtBytes = (n) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log2(n) / 10), u.length - 1);
  return (n / 1024 ** i).toFixed(i ? 1 : 0) + " " + u[i];
};

/* ---------- pages ---------- */

async function pageDashboard() {
  const [s, w] = await Promise.all([api("/api/stats"), api("/api/worker/status")]);
  const workerChip = w.running
    ? `<span class="badge ok">worker running (pid ${w.pid})</span>
       ${w.current_job ? `<span style="color:var(--fg-dim);font-size:12px"> — job ${w.current_job.id} ${w.current_job.job_type}: ${esc(w.current_job.progress || "starting")}</span>` : ""}
       <button class="small" onclick="workerCtl('stop')">Stop worker</button>`
    : `<span class="badge failed">worker NOT running</span>
       <button class="small primary" onclick="workerCtl('start')">Start worker</button>
       ${w.pending_jobs ? `<span class="error-msg" style="display:inline">${w.pending_jobs} job(s) waiting for it!</span>` : ""}`;
  content.innerHTML = `
    <h2>Dashboard</h2>
    <div class="cards">
      ${card(s.sources, "sources")}
      ${card(s.files_active, "active images")}
      ${card(s.files_missing, "missing images")}
      ${card(fmtBytes(s.total_bytes), "library size")}
      ${card(s.thumbs_ok, "thumbnails")}
      ${card(s.captions_ok, "captioned")}
      ${card(s.faces_total, "faces found")}
      ${card(s.people, "named people")}
      ${card(s.clusters_review, "clusters to review")}
      ${card(s.jobs_running + s.jobs_pending, "jobs queued/running")}
    </div>
    <h3>AI worker</h3>
    <p>${workerChip}</p>
    <p style="color:var(--fg-dim)">The worker is a separate process that runs the AI jobs
      below (so models never slow down this web app). Start it here or with
      <code>scripts\\start_worker.bat</code>. Logs: <code>data/logs/worker.log</code>.</p>
    <h3>AI pipeline</h3>
    <p style="color:var(--fg-dim)">${s.captions_pending} images await captioning,
      ${s.faces_pending} await face detection. Buttons enqueue jobs; the worker processes them.</p>
    <form class="inline">
      <button type="button" onclick="enqueue('captions')">Caption pending images</button>
      <button type="button" onclick="enqueue('faces')">Detect faces (pending)</button>
      <button type="button" onclick="enqueue('cluster')">Cluster faces</button>
    </form>`;
}
window.workerCtl = async (action) => {
  const r = await api(`/api/worker/${action}`, { method: "POST" });
  if (action === "start" && r.started) alert(`Worker started (pid ${r.pid}).`);
  if (action === "start" && r.already_running) alert(`Worker already running (pid ${r.pid}).`);
  if (action === "stop") alert(r.stopped ? "Worker stopped. Any interrupted job was reset to pending." : "Worker was not running.");
  pageDashboard();
};
window.enqueue = async (what) => {
  const map = { captions: "/api/analysis/captions", faces: "/api/analysis/faces", cluster: "/api/analysis/cluster" };
  const r = await api(map[what], { method: "POST" });
  const w = await api("/api/worker/status");
  if (!w.running && confirm(`Job ${r.job_id} queued, but the worker is not running.\nStart the worker now?`)) {
    await api("/api/worker/start", { method: "POST" });
  }
  pollJobs(); pageDashboard();
};
const card = (num, lbl) =>
  `<div class="card"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`;

async function pageSources() {
  const rows = await api("/api/sources");
  content.innerHTML = `
    <h2>Sources</h2>
    <form class="inline" id="add-form">
      <input id="src-name" placeholder="Name (e.g. NAS photos)" required>
      <input id="src-path" placeholder="Path (e.g. Z:\\family\\photos or \\\\nas-server\\homes\\family\\photos)" required style="min-width:380px">
      <button class="primary">Add source</button>
    </form>
    <div class="error-msg" id="src-err"></div>
    <table><thead><tr>
      <th>ID</th><th>Name</th><th>Path</th><th>Type</th><th>Status</th>
      <th>Images</th><th>Missing</th><th>Last scan</th><th>Actions</th>
    </tr></thead><tbody>
      ${rows.map((r) => `<tr>
        <td>${r.id}</td><td>${esc(r.name)}</td>
        <td style="font-family:monospace;font-size:12px">${esc(r.root_path)}</td>
        <td>${r.path_type}</td>
        <td><span class="badge ${r.status}">${r.status}</span></td>
        <td>${r.active_files}</td><td>${r.missing_files}</td>
        <td>${r.last_scan_at ? r.last_scan_at.replace("T", " ").replace("Z", "") : "never"}</td>
        <td>
          <button class="small" onclick="scanSource(${r.id})">Scan</button>
          ${r.status === "active"
            ? `<button class="small" onclick="setSourceStatus(${r.id},'paused')">Pause</button>
               <button class="small" onclick="setSourceStatus(${r.id},'inactive')">Deactivate</button>`
            : `<button class="small" onclick="setSourceStatus(${r.id},'active')">Activate</button>`}
          <button class="small" onclick="deleteSource(${r.id}, '${esc(r.name)}')" style="border-color:var(--err)">Delete</button>
        </td>
      </tr>`).join("")}
    </tbody></table>
    ${rows.length ? "" : "<p style='color:var(--fg-dim)'>No sources yet — add one above.</p>"}`;
  $("#add-form").onsubmit = async (e) => {
    e.preventDefault();
    $("#src-err").textContent = "";
    try {
      const r = await api("/api/sources", {
        method: "POST",
        body: JSON.stringify({ name: $("#src-name").value, root_path: $("#src-path").value }),
      });
      if (r.reconnected) alert("Existing source with this path was reconnected — prior data restored.");
      pageSources();
    } catch (err) { $("#src-err").textContent = err.message; }
  };
}

window.scanSource = async (id) => {
  try {
    const r = await api(`/api/sources/${id}/scan`, { method: "POST" });
    alert(r.already_running ? `Scan already running (job ${r.job_id})` : `Scan started (job ${r.job_id}) — watch the Jobs page.`);
    pollJobs();
  } catch (err) { alert(err.message); }
};
window.setSourceStatus = async (id, status) => {
  await api(`/api/sources/${id}/status`, { method: "POST", body: JSON.stringify({ status }) });
  pageSources();
};
window.deleteSource = async (id, name) => {
  if (!confirm(`HARD DELETE source "${name}"?\n\nThis permanently removes all its indexed `
    + `records, captions, faces, and person tags from the database. Your original photo `
    + `files on disk are NOT touched.\n\nTip: "Deactivate" instead keeps the data for later.`)) return;
  if (!confirm("Are you absolutely sure? This cannot be undone.")) return;
  const r = await api(`/api/sources/${id}/delete`, { method: "POST", body: JSON.stringify({ confirm: true }) });
  alert(`Deleted ${r.deleted_files} file records. Originals on disk untouched.`);
  pageSources();
};

let imgState = { page: 1, source_id: "", status: "active", q: "" };
async function pageImages() {
  const p = new URLSearchParams({ page: imgState.page, per_page: 100, status: imgState.status });
  if (imgState.source_id) p.set("source_id", imgState.source_id);
  if (imgState.q) p.set("q", imgState.q);
  const [data, sources] = await Promise.all([api(`/api/files?${p}`), api("/api/sources")]);
  const pages = Math.max(1, Math.ceil(data.total / data.per_page));
  content.innerHTML = `
    <h2>Images <span style="color:var(--fg-dim);font-size:14px">${data.total} total</span></h2>
    <form class="inline" id="img-filter">
      <select id="f-source"><option value="">All sources</option>
        ${sources.map((s) => `<option value="${s.id}" ${imgState.source_id == s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
      </select>
      <select id="f-status">
        ${["active", "missing", "all"].map((s) => `<option ${imgState.status === s ? "selected" : ""}>${s}</option>`).join("")}
      </select>
      <input id="f-q" placeholder="filter path…" value="${esc(imgState.q)}">
      <button>Apply</button>
    </form>
    <div id="grid">
      ${data.items.map((f) => `
        <div class="tile" onclick="showDetail(${f.id})"
             title="${esc(f.caption_short || f.relative_path.split("/").pop())}">
          <img loading="lazy" src="${thumbUrl(f)}"
               onerror="this.style.display='none'">
          <div class="cap">${esc(f.caption_short || f.relative_path.split("/").pop())}</div>
        </div>`).join("")}
    </div>
    <div class="pager">
      <button ${imgState.page <= 1 ? "disabled" : ""} onclick="imgPage(-1)">◀ Prev</button>
      <span>page ${imgState.page} / ${pages}</span>
      <button ${imgState.page >= pages ? "disabled" : ""} onclick="imgPage(1)">Next ▶</button>
    </div>`;
  $("#img-filter").onsubmit = (e) => {
    e.preventDefault();
    imgState = { page: 1, source_id: $("#f-source").value, status: $("#f-status").value, q: $("#f-q").value };
    pageImages();
  };
}
window.imgPage = (d) => { imgState.page += d; pageImages(); };

window.showDetail = async (id) => {
  const [f, a, faces] = await Promise.all([
    api(`/api/files/${id}`),
    api(`/api/files/${id}/analysis`).catch(() => null),
    api(`/api/files/${id}/faces`).catch(() => []),
  ]);
  const capBlock = a && a.status === "done" ? `
      <dt>Caption</dt><dd id="cap-view">${esc(a.caption_short)}
        <button class="small" onclick="editCaption(${id})" title="Edit caption">✏️</button></dd>
      <dt>Detailed</dt><dd style="color:var(--fg-dim)">${esc(a.caption_detailed)}</dd>
      ${a.object_tags && a.object_tags.length ? `<dt>Tags</dt><dd>${a.object_tags.map(esc).join(", ")}</dd>` : ""}
      ${a.ocr_text ? `<dt>OCR text</dt><dd style="font-family:monospace;font-size:11px">${esc(a.ocr_text)}</dd>` : ""}`
    : `<dt>Caption</dt><dd id="cap-view" style="color:var(--fg-dim)">not analyzed yet
        <button class="small" onclick="editCaption(${id})" title="Add caption">✏️</button></dd>`;
  const faceBlock = faces && faces.length ? `
    <div style="margin-top:12px"><b>${faces.length} face(s)</b>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
        ${faces.map((fc) => `<div style="text-align:center">
          <img src="/api/facecrop/${fc.id}" style="width:70px;height:70px;object-fit:cover;border-radius:6px"
               onerror="this.style.opacity=.3">
          <div style="font-size:10px;color:var(--fg-dim)">${fc.person_name ? esc(fc.person_name) : (fc.cluster_id ? "cluster " + fc.cluster_id : "?")}</div>
          ${fc.gender ? `<div style="font-size:10px;color:var(--fg-dim)">${fc.gender}${fc.age ? " ~" + fc.age : ""}</div>` : ""}
        </div>`).join("")}
      </div></div>` : "";
  $("#modal-body").innerHTML = `
    <img src="/api/original/${f.id}" onerror="this.src='${thumbUrl(f)}'">
    <dl>
      <dt>File</dt><dd>${esc(f.relative_path)}</dd>
      <dt>Source</dt><dd>${esc(f.source_name)} <span style="color:var(--fg-dim)">(${esc(f.source_root)})</span></dd>
      <dt>Size</dt><dd>${fmtBytes(f.file_size)} — ${f.width}×${f.height}</dd>
      <dt>Taken</dt><dd>${f.date_taken || "unknown"}</dd>
      <dt>Camera</dt><dd>${esc(f.camera_model) || "unknown"}</dd>
      <dt>GPS</dt><dd>${f.gps_lat ? f.gps_lat.toFixed(5) + ", " + f.gps_lon.toFixed(5) : "none"}</dd>
      ${capBlock}
      <dt>Status</dt><dd><span class="badge ${f.status}">${f.status}</span></dd>
    </dl>
    ${faceBlock}
    <p style="margin-top:12px"><button onclick="closeModal()">Close</button></p>`;
  $("#modal").classList.remove("hidden");
};
window.closeModal = () => $("#modal").classList.add("hidden");

window.editCaption = async (fileId) => {
  const a = await api(`/api/files/${fileId}/analysis`).catch(() => null);
  const cur = a && a.caption_short ? a.caption_short : "";
  const el = $("#cap-view");
  el.innerHTML = `
    <input id="cap-input" value="${esc(cur)}" style="min-width:320px">
    <button class="small primary" onclick="saveCaption(${fileId})">Save</button>
    <button class="small" onclick="showDetail(${fileId})">Cancel</button>`;
  $("#cap-input").focus();
  $("#cap-input").onkeydown = (e) => { if (e.key === "Enter") saveCaption(fileId); };
};
window.saveCaption = async (fileId) => {
  await api(`/api/files/${fileId}/caption`, {
    method: "POST",
    body: JSON.stringify({ caption_short: $("#cap-input").value }),
  });
  showDetail(fileId);
};

async function pageJobs() {
  const rows = await api("/api/jobs");
  content.innerHTML = `
    <h2>Jobs</h2>
    <form class="inline"><button type="button" onclick="retryThumbs()">Retry failed thumbnails</button></form>
    <table><thead><tr>
      <th>ID</th><th>Type</th><th>Status</th><th>Progress / Result</th><th>Error</th>
      <th>Created</th><th>Finished</th>
    </tr></thead><tbody>
      ${rows.map((j) => `<tr>
        <td>${j.id}</td><td>${j.job_type}</td>
        <td><span class="badge ${j.status}">${j.status}</span></td>
        <td style="font-size:12px">${esc(j.progress || "")}</td>
        <td style="font-size:12px;color:var(--err)">${esc(j.error_message || "")}</td>
        <td style="font-size:12px">${(j.created_at || "").replace("T", " ").replace("Z", "")}</td>
        <td style="font-size:12px">${(j.finished_at || "").replace("T", " ").replace("Z", "")}</td>
      </tr>`).join("")}
    </tbody></table>`;
}
window.retryThumbs = async () => {
  const r = await api("/api/thumbnails/retry", { method: "POST" });
  alert(`Thumbnail retry started (job ${r.job_id})`);
  pageJobs();
};

/* ---------- search ---------- */
let searchState = { q: "", person: "", confirmed_only: 0, has_people: "", screenshots: "" };
async function pageSearch() {
  content.innerHTML = `
    <h2>Search</h2>
    <form class="inline" id="search-form">
      <input id="s-q" placeholder="caption / tag / OCR text…" value="${esc(searchState.q)}" style="min-width:300px">
      <input id="s-person" placeholder="person name" value="${esc(searchState.person)}">
      <select id="s-haspeople">
        <option value="">any people</option>
        <option value="1" ${searchState.has_people==="1"?"selected":""}>has people</option>
        <option value="0" ${searchState.has_people==="0"?"selected":""}>no people</option>
      </select>
      <select id="s-shots">
        <option value="">any type</option>
        <option value="1" ${searchState.screenshots==="1"?"selected":""}>screenshots only</option>
        <option value="0" ${searchState.screenshots==="0"?"selected":""}>photos only</option>
      </select>
      <label style="color:var(--fg-dim)"><input type="checkbox" id="s-confirmed" style="min-width:auto" ${searchState.confirmed_only?"checked":""}> confirmed only</label>
      <button class="primary">Search</button>
    </form>
    <p style="color:var(--fg-dim)">Examples: <code>dog grass</code>, <code>screenshot</code>,
      person "George Clooney" + has people. FTS matches captions, object tags, and OCR text.</p>
    <div id="search-results"></div>`;
  $("#search-form").onsubmit = async (e) => {
    e.preventDefault();
    searchState = { q: $("#s-q").value, person: $("#s-person").value,
      confirmed_only: $("#s-confirmed").checked ? 1 : 0, has_people: $("#s-haspeople").value,
      screenshots: $("#s-shots").value };
    runSearch();
  };
  if (searchState.q || searchState.person || searchState.has_people !== "" || searchState.screenshots)
    runSearch();
}
let selMode = false;
let selIds = new Set();
async function runSearch() {
  selMode = false; selIds = new Set();
  const p = new URLSearchParams({ per_page: 200 });
  if (searchState.q) p.set("q", searchState.q);
  if (searchState.person) p.set("person", searchState.person);
  if (searchState.confirmed_only) p.set("confirmed_only", 1);
  if (searchState.has_people !== "") p.set("has_people", searchState.has_people);
  if (searchState.screenshots) p.set("screenshots", searchState.screenshots);
  let data;
  try { data = await api(`/api/search?${p}`); }
  catch (e) { $("#search-results").innerHTML = `<p class="error-msg">${esc(e.message)}</p>`; return; }
  window._searchItems = data.items;
  $("#search-results").innerHTML = `
    <p style="color:var(--fg-dim)">${data.total} results</p>
    ${data.total && searchState.q ? `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:12px">
      <b>Name a person in these captions</b>
      <div style="color:var(--fg-dim);font-size:12px;margin:4px 0 8px">
        Example: you searched "man red shirt" and it's George Clooney. Put <i>man</i> on the
        left, <i>George Clooney</i> on the right, hit Rename — the captions are rewritten AND
        those images are tagged as the person George Clooney (see the People page).</div>
      <form class="inline" style="margin:0" id="replace-form">
        <input id="r-find" placeholder="word to replace (man, woman, boy…)" style="min-width:190px">
        <span style="color:var(--fg-dim)">→</span>
        <input id="r-replace" placeholder="person's name (George Clooney)" style="min-width:200px">
        <select id="r-scope">
          <option value="all">in all ${data.total} results</option>
          <option value="selected">in selected images only</option>
        </select>
        <button class="primary">Rename</button>
        <button type="button" class="small" onclick="toggleSelMode()" id="selmode-btn">Select images…</button>
        <button type="button" class="small" onclick="exportSearch()" title="Copy these images + caption .txt files into a LoRA dataset folder under data/exports">Export results for LoRA…</button>
      </form>
      <label style="color:var(--fg-dim);font-size:12px;display:block;margin-top:6px">
        <input type="checkbox" id="r-tagperson" checked style="min-width:auto">
        also tag these images as this person (adds them to the People page)
      </label>
      <div id="replace-result" style="margin-top:6px"></div>
    </div>` : ""}
    <div id="grid">${gridTiles(data.items, "searchTileClick")}</div>`;
  const rf = $("#replace-form");
  if (rf) rf.onsubmit = (e) => { e.preventDefault(); doReplace(); };
}
window.toggleSelMode = () => {
  selMode = !selMode;
  $("#selmode-btn").textContent = selMode ? `Done selecting (${selIds.size})` : "Select images…";
  if (selMode) { $("#r-scope").value = "selected"; alert("Selection mode ON — click images to select/deselect them, then set your find/replace and hit Replace."); }
  document.querySelectorAll("#grid .tile").forEach((t) => t.style.outline = "");
  if (!selMode) return;
  document.querySelectorAll("#grid .tile").forEach((t, i) => {
    const f = window._searchItems[i];
    if (selIds.has(f.id)) t.style.outline = "3px solid var(--accent)";
  });
};
window.searchTileClick = (idx) => {
  const f = window._searchItems[idx];
  if (!selMode) { showDetail(f.id); return; }
  const tiles = document.querySelectorAll("#grid .tile");
  if (selIds.has(f.id)) { selIds.delete(f.id); tiles[idx].style.outline = ""; }
  else { selIds.add(f.id); tiles[idx].style.outline = "3px solid var(--accent)"; }
  $("#selmode-btn").textContent = `Done selecting (${selIds.size})`;
};
window.exportSearch = async () => {
  const name = prompt("Dataset name (used for the folder, e.g. river, motorcycles):",
    searchState.q.replace(/[^a-zA-Z0-9 ]/g, "").trim());
  if (!name) return;
  const trigger = prompt("Trigger word to prepend to every caption (optional, e.g. rvr_style):", "") || null;
  const body = { name, trigger, dedupe: true, zip_output: false };
  if (selMode && selIds.size) body.file_ids = [...selIds];
  else body.q = searchState.q;
  $("#replace-result").innerHTML = "exporting…";
  try {
    const r = await api("/api/search/export", { method: "POST", body: JSON.stringify(body) });
    $("#replace-result").innerHTML = `<span class="badge ok">Exported ${r.exported} image(s) + captions.</span>
      <span style="font-family:monospace;font-size:12px">${esc(r.output_path)}</span>`;
  } catch (e) { $("#replace-result").innerHTML = `<span class="error-msg">${esc(e.message)}</span>`; }
};

window.doReplace = async () => {
  const find = $("#r-find").value, replace = $("#r-replace").value;
  if (!find) { $("#replace-result").innerHTML = `<span class="error-msg">enter the word to replace (e.g. man)</span>`; return; }
  if (!replace) { $("#replace-result").innerHTML = `<span class="error-msg">enter the person's name</span>`; return; }
  const scope = $("#r-scope").value;
  const tagPerson = $("#r-tagperson").checked;
  const body = { find, replace, tag_person: tagPerson };
  if (scope === "selected") {
    if (!selIds.size) { $("#replace-result").innerHTML = `<span class="error-msg">no images selected — click "Select images…" then click tiles</span>`; return; }
    body.file_ids = [...selIds];
  } else {
    body.q = searchState.q;
  }
  if (!confirm(`Rename "${find}" to "${replace}" in ${scope === "selected" ? selIds.size + " selected" : "ALL " + window._searchItems.length + "+ matching"} image captions?`
    + (tagPerson ? `\n\nThese images will also be tagged as the person "${replace}".` : ""))) return;
  const r = await api("/api/captions/replace", { method: "POST", body: JSON.stringify(body) });
  let msg = `<span class="badge ok">Updated ${r.changed} caption(s).</span>`;
  if (r.person && r.person.person_id) {
    msg += ` <span class="badge ok">${r.person.tagged} image(s) tagged as ${esc(r.person.person_name)}.</span>
      <a href="#/person/${r.person.person_id}" style="color:var(--accent)">Open ${esc(r.person.person_name)}'s page →</a>`;
  } else {
    msg += ` <span style="color:var(--fg-dim);font-size:12px">Search now finds them under "${esc(replace)}".</span>`;
  }
  $("#replace-result").innerHTML = msg;
};
// version param busts browser cache whenever a thumbnail is regenerated
const thumbUrl = (f) => `/api/thumb/${f.id}?v=${encodeURIComponent(f.updated_at || "")}`;
const gridTiles = (items, clickFn) => items.map((f, i) => `
  <div class="tile" onclick="${clickFn ? `${clickFn}(${i})` : `showDetail(${f.id})`}"
       title="${esc(f.caption_short || (f.relative_path||"").split("/").pop())}">
    <img loading="lazy" src="${thumbUrl(f)}" onerror="this.style.display='none'">
    <div class="cap">${esc(f.caption_short || (f.relative_path||"").split("/").pop())}</div>
  </div>`).join("");

/* ---------- people ---------- */
async function pagePeople() {
  const people = await api("/api/people");
  content.innerHTML = `
    <h2>People <span style="color:var(--fg-dim);font-size:14px">${people.length}</span></h2>
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:14px">
      <b>Two ways people get in here:</b>
      <ol style="color:var(--fg-dim);font-size:13px;margin:6px 0">
        <li><a href="#/review">People Review</a> — name the face clusters the AI found (best for family/frequent faces).</li>
        <li><a href="#/search">Search</a> — search a caption (e.g. "man red shirt"), then use
          <b>Name a person in these captions</b> to rename "man" → "George Clooney"; those images get tagged automatically.</li>
      </ol>
      <button class="small" onclick="syncCaptionPeople()">Re-scan captions for these names</button>
      <span style="color:var(--fg-dim);font-size:12px">— links any newly-captioned images that mention a known person's name</span>
      <div id="sync-result" style="margin-top:6px"></div>
    </div>
    ${people.length ? "" : `<p style="color:var(--fg-dim)">No named people yet — use either method above.</p>`}
    <div id="grid">
      ${people.map((p) => `
        <div class="tile" onclick="location.hash='#/person/${p.id}'">
          <img src="${p.cover_face_id ? "/api/facecrop/" + p.cover_face_id
                      : (p.cover_file_id ? `/api/thumb/${p.cover_file_id}?v=${encodeURIComponent(p.updated_at || "")}` : "")}"
               onerror="this.style.display='none'">
          <div class="cap">${esc(p.display_name)} · ${p.image_count} imgs</div>
        </div>`).join("")}
    </div>`;
}
window.syncCaptionPeople = async () => {
  $("#sync-result").innerHTML = "scanning captions…";
  const r = await api("/api/captions/sync-people", { method: "POST" });
  $("#sync-result").innerHTML = r.people_updated
    ? `<span class="badge ok">${r.details.map((d) => `${esc(d.person)}: +${d.new_links} image(s)`).join(", ")}</span>`
    : `<span style="color:var(--fg-dim)">No new caption mentions of known people found.</span>`;
  if (r.people_updated) setTimeout(pagePeople, 1500);
};

async function pagePersonDetail(pid) {
  const [p, imgs] = await Promise.all([
    api(`/api/people/${pid}`), api(`/api/people/${pid}/images?per_page=200`)]);
  const others = (await api("/api/people")).filter((x) => x.id != pid);
  content.innerHTML = `
    <h2>${esc(p.display_name)}</h2>
    <p style="color:var(--fg-dim)">${p.face_count} faces · ${p.image_count} images
      ${p.relationship ? "· " + esc(p.relationship) : ""}</p>
    <form class="inline">
      <button type="button" onclick="location.hash='#/export/${pid}'">Export LoRA dataset</button>
      <input id="rename" placeholder="rename to…">
      <button type="button" onclick="renamePerson(${pid})">Rename</button>
      <select id="mergeinto"><option value="">merge into…</option>
        ${others.map((o) => `<option value="${o.id}">${esc(o.display_name)}</option>`).join("")}
      </select>
      <button type="button" onclick="mergePerson(${pid})">Merge</button>
    </form>
    <div id="grid">${gridTiles(imgs.items)}</div>`;
}
window.renamePerson = async (pid) => {
  const name = $("#rename").value.trim(); if (!name) return;
  await api(`/api/people/${pid}`, { method: "POST", body: JSON.stringify({ display_name: name }) });
  pagePersonDetail(pid);
};
window.mergePerson = async (pid) => {
  const into = $("#mergeinto").value; if (!into) return;
  if (!confirm("Merge this person into the selected one? This person will be removed.")) return;
  await api(`/api/people/${pid}/merge`, { method: "POST", body: JSON.stringify({ into_person_id: +into }) });
  location.hash = "#/people";
};

/* ---------- people review ---------- */
let reviewSel = new Set();
async function pageReview() {
  const clusters = await api("/api/clusters");
  content.innerHTML = `
    <h2>People Review</h2>
    <p style="color:var(--fg-dim)">${clusters.length} unnamed clusters need review. Click a
      cluster to name it or clean it up. Naming a cluster teaches fotorganize to auto-tag
      similar faces on the next <b>Cluster faces</b> run.</p>
    <div id="grid">
      ${clusters.map((c) => `
        <div class="tile" onclick="openCluster(${c.id})">
          <img src="/api/facecrop/${c.cover_face_id}" onerror="this.style.opacity=.3">
          <div class="cap">cluster ${c.id} · ${c.n} faces</div>
        </div>`).join("")}
    </div>
    ${clusters.length ? "" : `<p style="color:var(--fg-dim)">Nothing to review. Detect faces and cluster them from the Dashboard.</p>`}`;
}
window.openCluster = async (cid) => {
  reviewSel = new Set();
  const faces = await api(`/api/clusters/${cid}/faces`);
  $("#modal-body").innerHTML = `
    <h3>Cluster ${cid} — ${faces.length} faces</h3>
    <p style="color:var(--fg-dim)">Click faces to deselect any that don't belong, then name the rest.</p>
    <div id="cluster-faces" style="display:flex;gap:6px;flex-wrap:wrap;max-width:70vw">
      ${faces.map((f) => `
        <img data-fid="${f.id}" src="/api/facecrop/${f.id}" class="csel"
             style="width:80px;height:80px;object-fit:cover;border-radius:6px;cursor:pointer;outline:2px solid var(--accent)"
             onclick="toggleFace(${f.id}, this)" onerror="this.style.opacity=.3">`).join("")}
    </div>
    <form class="inline" style="margin-top:12px">
      <input id="cluster-name" placeholder="person name (e.g. George Clooney)">
      <button type="button" class="primary" onclick="nameCluster(${cid})">Name selected</button>
      <button type="button" onclick="clusterFaceStatus('not_person')">Mark not a person</button>
      <button type="button" onclick="clusterFaceStatus('bad_crop')">Bad crop</button>
      <button type="button" onclick="closeModal()">Cancel</button>
    </form>
    <div class="error-msg" id="cluster-err"></div>`;
  faces.forEach((f) => reviewSel.add(f.id));
  $("#modal").classList.remove("hidden");
};
window.toggleFace = (fid, el) => {
  if (reviewSel.has(fid)) { reviewSel.delete(fid); el.style.outline = "2px solid transparent"; el.style.opacity = .4; }
  else { reviewSel.add(fid); el.style.outline = "2px solid var(--accent)"; el.style.opacity = 1; }
};
window.nameCluster = async (cid) => {
  const name = $("#cluster-name").value.trim();
  if (!name) { $("#cluster-err").textContent = "enter a name"; return; }
  // assign only selected faces to the person; if all selected, name the whole cluster
  const all = await api(`/api/clusters/${cid}/faces`);
  if (reviewSel.size === all.length) {
    await api(`/api/clusters/${cid}/name`, { method: "POST", body: JSON.stringify({ name }) });
  } else {
    await api(`/api/faces/assign`, { method: "POST",
      body: JSON.stringify({ face_ids: [...reviewSel], name }) });
  }
  closeModal(); pageReview();
};
window.clusterFaceStatus = async (status) => {
  if (!reviewSel.size) return;
  await api(`/api/faces/status`, { method: "POST",
    body: JSON.stringify({ face_ids: [...reviewSel], status }) });
  closeModal(); pageReview();
};

/* ---------- export ---------- */
async function pageExport(pid) {
  const p = await api(`/api/people/${pid}`);
  content.innerHTML = `
    <h2>Export LoRA dataset — ${esc(p.display_name)}</h2>
    <p style="color:var(--fg-dim)">${p.image_count} candidate images. Output goes to
      <code>data/exports/</code> in ai-toolkit format (image + matching .txt caption).</p>
    <form id="export-form" style="display:grid;grid-template-columns:180px 1fr;gap:10px;max-width:560px">
      <label>Trigger word</label><input id="e-trigger" value="${esc(p.display_name.toLowerCase().replace(/[^a-z0-9]/g,'_'))}_person">
      <label>Export mode</label><select id="e-mode"><option value="full">full image</option><option value="face_crop">face crop</option><option value="smart_crop">smart crop around person</option></select>
      <label>Caption style</label><select id="e-caption"><option value="natural">natural sentence</option><option value="tag">LoRA tag style</option></select>
      <label>Min image size (px)</label><input id="e-minsize" type="number" value="0">
      <label>Max images (0=all)</label><input id="e-max" type="number" value="0">
      <label>Confirmed faces only</label><input id="e-confirmed" type="checkbox" style="min-width:auto">
      <label>Include group photos</label><input id="e-group" type="checkbox" style="min-width:auto" checked>
      <label>Remove near-duplicates</label><input id="e-dedupe" type="checkbox" style="min-width:auto" checked>
      <label>Exclude screenshots</label><input id="e-noshots" type="checkbox" style="min-width:auto" checked>
      <label>Also make .zip</label><input id="e-zip" type="checkbox" style="min-width:auto">
    </form>
    <p><button class="primary" onclick="runExport(${pid})">Export</button>
       <button onclick="location.hash='#/person/${pid}'">Back</button></p>
    <div id="export-result"></div>`;
}
window.runExport = async (pid) => {
  $("#export-result").innerHTML = "exporting…";
  const body = {
    trigger: $("#e-trigger").value, export_mode: $("#e-mode").value,
    caption_style: $("#e-caption").value, min_image_size: +$("#e-minsize").value,
    max_images: +$("#e-max").value, confirmed_only: $("#e-confirmed").checked,
    include_group: $("#e-group").checked, dedupe: $("#e-dedupe").checked,
    exclude_screenshots: $("#e-noshots").checked, zip_output: $("#e-zip").checked,
  };
  try {
    const r = await api(`/api/people/${pid}/export`, { method: "POST", body: JSON.stringify(body) });
    $("#export-result").innerHTML = `<p class="badge ok">Exported ${r.exported} images</p>
      <p style="font-family:monospace;font-size:12px">${esc(r.output_path)}${r.zip_path ? "<br>" + esc(r.zip_path) : ""}</p>`;
  } catch (e) { $("#export-result").innerHTML = `<p class="error-msg">${esc(e.message)}</p>`; }
};

async function pageExports() {
  const rows = await api("/api/exports");
  content.innerHTML = `
    <h2>Exports</h2>
    ${rows.length ? "" : `<p style="color:var(--fg-dim)">No exports yet. Open a person and click Export.</p>`}
    <table><thead><tr><th>ID</th><th>Person</th><th>Type</th><th>Output path</th><th>Zip</th><th>Created</th></tr></thead><tbody>
      ${rows.map((e) => `<tr><td>${e.id}</td><td>${esc(e.display_name||"")}</td><td>${e.export_type}</td>
        <td style="font-family:monospace;font-size:11px">${esc(e.output_path||"")}</td>
        <td>${e.zip_path ? "yes" : ""}</td>
        <td style="font-size:12px">${(e.created_at||"").replace("T"," ").replace("Z","")}</td></tr>`).join("")}
    </tbody></table>`;
}

/* ---------- duplicates + maintenance ---------- */
async function pageDuplicates() {
  const cfg = await api("/api/maintenance/config");
  content.innerHTML = `
    <h2>Duplicates &amp; cleanup</h2>
    <form class="inline">
      <button type="button" onclick="loadDupes('exact')">Find exact duplicates</button>
      <button type="button" onclick="loadDupes('near')">Find near-duplicates</button>
      <button type="button" onclick="flagScreenshots()">Flag screenshots/memes</button>
      <button type="button" onclick="writeSidecars()">Write XMP sidecars</button>
    </form>
    <p style="color:var(--fg-dim)">Exact = identical file content (SHA256). Near = visually
      similar (perceptual hash). Screenshot flagging fills a flag you can filter on in Search
      and exclude from LoRA exports. XMP sidecars are
      <b>${cfg.write_xmp_sidecars ? "ENABLED" : "disabled"}</b> in .env
      (${cfg.write_xmp_sidecars ? "writes .xmp next to each original" : "the button forces a one-off write; nothing writes automatically"}).
      Sidecars never modify your original photos.</p>
    <div id="dupe-results"></div>`;
}
window.loadDupes = async (kind) => {
  $("#dupe-results").innerHTML = "scanning…";
  const d = await api(`/api/maintenance/duplicates?kind=${kind}`);
  if (!d.groups.length) { $("#dupe-results").innerHTML = `<p style="color:var(--fg-dim)">No ${kind} duplicate groups found.</p>`; return; }
  $("#dupe-results").innerHTML = `<p>${d.group_count} ${kind} duplicate groups</p>` +
    d.groups.map((g) => `<div style="margin-bottom:14px">
      <div style="color:var(--fg-dim);font-size:12px">${g.count} copies</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${g.files.map((f) => `<div class="tile" style="width:130px;height:130px" onclick="showDetail(${f.id})">
          <img loading="lazy" src="/api/thumb/${f.id}" onerror="this.style.display='none'">
          <div class="cap">${esc((f.relative_path||"").split("/").pop())}</div></div>`).join("")}
      </div></div>`).join("");
};
window.flagScreenshots = async () => {
  $("#dupe-results").innerHTML = "flagging…";
  const r = await api("/api/maintenance/flag-screenshots", { method: "POST" });
  $("#dupe-results").innerHTML = `<p class="badge ok">Flagged ${r.screenshots} screenshots, ${r.not} non-screenshots.</p>
    <p style="color:var(--fg-dim)">Filter them in Search (screenshots only) or exclude from exports.</p>`;
};
window.writeSidecars = async () => {
  if (!confirm("Write .xmp sidecar files next to your original photos? Originals are not modified.")) return;
  $("#dupe-results").innerHTML = "writing…";
  const r = await api("/api/maintenance/write-sidecars?force=true", { method: "POST" });
  $("#dupe-results").innerHTML = `<p class="badge ok">${JSON.stringify(r)}</p>`;
};

/* ---------- router + job poller ---------- */

const routes = { dashboard: pageDashboard, sources: pageSources, images: pageImages,
  search: pageSearch, people: pagePeople, review: pageReview, exports: pageExports,
  duplicates: pageDuplicates, jobs: pageJobs };
function route() {
  const raw = (location.hash.replace("#/", "") || "dashboard").split("?")[0];
  const parts = raw.split("/");
  const page = parts[0];
  document.querySelectorAll("#sidebar a").forEach((a) =>
    a.classList.toggle("active", a.dataset.page === page));
  let fn;
  if (page === "person" && parts[1]) fn = () => pagePersonDetail(parts[1]);
  else if (page === "export" && parts[1]) fn = () => pageExport(parts[1]);
  else fn = routes[page] || pageDashboard;
  Promise.resolve(fn()).catch((e) => {
    content.innerHTML = `<h2>Error</h2><p class="error-msg">${esc(e.message)}</p>`;
  });
}
window.addEventListener("hashchange", route);

let pollTimer = null;
async function pollJobs() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const s = await api("/api/stats");
      $("#job-indicator").classList.toggle("hidden", s.jobs_running === 0);
      if (s.jobs_running === 0) clearInterval(pollTimer);
    } catch { clearInterval(pollTimer); }
  }, 3000);
}

route();
pollJobs();
