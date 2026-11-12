(() => {
  "use strict";

  const TYPES = [
    { key: "all", label: "전체" },
    { key: "정규직", label: "정규직" },
    { key: "계약직", label: "계약직·기간제" },
    { key: "인턴", label: "인턴" },
    { key: "대외활동", label: "대외활동" },
    { key: "none", label: "미분류" },
  ];
  const TAGS = ["경영지원", "경영기획", "전략기획", "홍보마케팅", "하우스안내원"];
  // 예전에 수집된 공고에도 바로 적용되도록 화면에서도 한 번 더 판단
  const CAREER_NEW = /신입|경력\s*무관|경력\s*불문/;
  const CAREER_EXP = /경력\s*직|경력\s*\d|경력\s*(사원|채용|공채|제한|자)|\d+\s*년\s*이상|시니어|책임급|선임급/;
  const careerOf = (t) => (CAREER_NEW.test(t) ? "신입" : CAREER_EXP.test(t) ? "경력" : null);
  // 분야: 공고 제목 + 기관 이름으로 판단 (여러 분야에 동시에 들 수 있음)
  const FIELD_RULES = {
    "공연": /공연|극장|아트센터|아트홀|콘서트|오페라|발레|뮤지컬|연극|무용|댄스|오케스트라|심포니|교향악|국악|예술단|극단|문화회관|예술의전당|씨어터|시어터|무대|하우스\s*(안내|어텐던트|어셔|매니저|스태프)|티켓|객석|공연장|페스티벌|연극제|아트리움|콘서트홀|세종문화회관|정동극장/,
    "미술": /미술|갤러리|아트페어|비엔날레|큐레이터|도슨트|학예|전시|뮤지엄|박물관|아트\s*스페이스|조각|회화|공예|디자인\s*진흥|아트센터\s*나비|리움/,
    "도서관": /도서관|사서|도서|북\s*(카페|페스티벌|스타트)|책\s*(축제|나라|문화)|그림책|북스타트|출판|문학관|문학번역|독서/,
  };
  const FIELDS = Object.keys(FIELD_RULES);
  const TAG_RULES = { "하우스안내원": /하우스\s*\)?\s*(안내|매니저|부매니저|어텐던트|어셔|스태프)|안내원|어셔|어텐던트|객석\s*안내|공연장\s*안내|안내\s*데스크/ };
  const GROUPS = ["공연장", "문체부 산하 공공기관", "공공문화재단", "민간문화재단", "기업", "축제·대외활동", "기타 문화예술 기관"];
  const NEW_DAYS = 3;

  // ---------- 브라우저 저장 (이 기기에서만) ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 무시 */ } },
  };

  const state = {
    jobs: [], status: {}, companies: [], overrides: {}, updated: null,
    type: store.get("type", "all"),
    tags: new Set(store.get("tags", [])),
    groups: new Set(store.get("groups", [])),
    fields: new Set(store.get("fields", [])),
    q: "", newOnly: false, hideRead: store.get("hideRead", false),
    hideExp: store.get("hideExp", false), newcomerOnly: store.get("newcomerOnly", false),
    read: new Set(store.get("read", [])),
    repo: store.get("repo", guessRepo()),
    token: store.get("token", ""),
  };
  const admin = () => Boolean(state.token && state.repo);

  function guessRepo() {
    const m = location.hostname.match(/^([^.]+)\.github\.io$/);
    const seg = location.pathname.split("/").filter(Boolean)[0];
    return m && seg ? `${m[1]}/${seg}` : "";
  }

  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function getJSON(path, fallback) {
    try {
      const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch { return fallback; }
  }

  async function load() {
    const [jobs, status, companies, overrides] = await Promise.all([
      getJSON("data/jobs.json", { jobs: [] }),
      getJSON("data/status.json", { companies: {} }),
      getJSON("data/companies.json", { companies: [] }),
      getJSON("data/overrides.json", {}),
    ]);
    state.jobs = jobs.jobs || [];
    state.updated = jobs.updated;
    state.status = status.companies || {};
    state.companies = companies.companies || [];
    state.overrides = overrides || {};
    const pending = store.get("pendingOverrides", {});
    Object.assign(state.overrides, pending);
    render();
  }

  // ---------- 계산 ----------
  const today = () => {
    const d = new Date(Date.now() + 9 * 3600e3); // KST
    return d.toISOString().slice(0, 10);
  };
  function daysBetween(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 864e5); }

  function view(j) {
    const ov = state.overrides[j.id] || {};
    const type = ov.type || j.type || null;
    const refDay = (state.updated || today()).slice(0, 10);
    const isNew = !j.initial && !j.closed && daysBetween(j.first_seen, refDay) < NEW_DAYS;
    const career = j.career || careerOf(j.title);
    const tags = [...(j.tags || [])];
    for (const [t, re] of Object.entries(TAG_RULES)) if (re.test(j.title) && !tags.includes(t)) tags.push(t);
    const hay = `${j.title} ${j.company}`;
    const fields = FIELDS.filter((f) => FIELD_RULES[f].test(hay));
    return { ...j, type, tags, career, fields, hidden: Boolean(ov.hidden), isNew, isRead: state.read.has(j.id) };
  }

  function matches(j) {
    if (j.hidden) return false;
    if (state.type !== "all") {
      if (state.type === "none" ? j.type : j.type !== state.type) return false;
    }
    if (state.tags.size && !(j.tags || []).some((t) => state.tags.has(t))) return false;
    if (state.groups.size && !state.groups.has(j.group)) return false;
    if (state.fields.size && !j.fields.some((f) => state.fields.has(f))) return false;
    if (state.newOnly && !j.isNew) return false;
    if (state.hideRead && j.isRead) return false;
    if (state.hideExp && j.career === "경력") return false;
    if (state.newcomerOnly && j.career !== "신입") return false;
    if (state.q) {
      const hay = `${j.company} ${j.title}`.toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  const byDeadline = (a, b) =>
    (a.deadline || "9999") .localeCompare(b.deadline || "9999") ||
    (b.posted || b.first_seen || "").localeCompare(a.posted || a.first_seen || "");
  const byRecent = (a, b) =>
    (b.deadline || b.posted || b.last_seen || "").localeCompare(a.deadline || a.posted || a.last_seen || "");

  // ---------- 렌더 ----------
  function render() {
    renderHeader();
    renderAlerts();
    renderFilters();
    renderJobs();
    renderCompanies();
  }

  function renderHeader() {
    if (!state.updated) { $("#updated").textContent = "아직 수집 기록이 없어요"; return; }
    const d = new Date(state.updated);
    const txt = d.toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul" });
    $("#updated").textContent = `마지막 수집 ${txt}`;
  }

  function renderAlerts() {
    const fails = state.companies.filter((c) => state.status[c.id] && state.status[c.id].ok === false);
    const alio = state.status.__alio__;
    const box = $("#alerts");
    const out = [];
    if (alio && alio.ok === false) {
      out.push(`<div class="alert">⚠ 공공기관 채용정보 API 수집 실패: ${esc(alio.error)}</div>`);
    }
    if (fails.length) {
      out.push(`<div class="alert">⚠ ${fails.length}곳 수집 실패: ${fails.slice(0, 6).map((c) => esc(c.name)).join(", ")}${fails.length > 6 ? " 외" : ""} · <button data-go="companies">기관 목록에서 확인</button></div>`);
    }
    box.innerHTML = out.join("");
  }

  function renderFilters() {
    const all = state.jobs.map(view).filter((j) => !j.hidden && !j.closed);
    $("#typeTabs").innerHTML = TYPES.filter((t) => t.key !== "none" || all.some((j) => !j.type)).map((t) => {
      const list = all.filter((j) => t.key === "all" || (t.key === "none" ? !j.type : j.type === t.key));
      const nn = list.filter((j) => j.isNew).length;
      return `<button class="tab ${state.type === t.key ? "on" : ""}" data-type="${t.key}">${t.label}<span class="n">${list.length}</span>${nn ? `<span class="nn">+${nn}</span>` : ""}</button>`;
    }).join("");
    $("#tagChips").innerHTML = TAGS.map((t) => `<button class="chip ${state.tags.has(t) ? "on" : ""}" data-tag="${t}">${t}</button>`).join("");
    $("#fieldChips").innerHTML = FIELDS.map((f) => `<button class="chip ${state.fields.has(f) ? "on" : ""}" data-field="${f}">${f}</button>`).join("");
    $("#groupChips").innerHTML = GROUPS.map((g) => `<button class="chip ${state.groups.has(g) ? "on" : ""}" data-group="${g}">${g}</button>`).join("");
    $("#hideRead").checked = state.hideRead;
    $("#hideExp").checked = state.hideExp;
    $("#newcomerOnly").checked = state.newcomerOnly;
    $("#newOnly").checked = state.newOnly;
  }

  function dday(j) {
    if (!j.deadline) return `<span class="dl">마감일 미표기</span>`;
    const n = daysBetween(today(), j.deadline);
    const label = j.closed ? "마감" : n === 0 ? "오늘 마감" : `D-${n}`;
    return `<span class="dday ${!j.closed && n <= 3 ? "soon" : ""}">${label}</span><span class="dl">~${j.deadline.slice(5).replace("-", ".")}</span>`;
  }

  function card(j) {
    const typeLabel = j.type ? TYPES.find((t) => t.key === j.type)?.label || j.type : "미분류";
    const typeCls = j.type ? `t-${j.type}` : "t-none";
    const editor = admin()
      ? `<select class="type-edit" data-edit="${j.id}" aria-label="분류 수정">${TYPES.slice(1).map((t) => `<option value="${t.key}" ${((j.type || "none") === t.key) ? "selected" : ""}>${t.label}</option>`).join("")}</select>
         <button class="hide-btn" data-hide="${j.id}">숨기기</button>`
      : "";
    const posted = j.posted ? `게시 ${j.posted.slice(5).replace("-", ".")}` : "";
    return `<article class="job ${j.isRead ? "read" : ""}">
      <div class="meta">
        <span class="badge ${typeCls}" title="${esc(j.type_detail || "")}">${typeLabel}</span>
        ${j.isNew ? `<span class="badge new">NEW</span>` : ""}
        ${j.career ? `<span class="badge career">${j.career === "신입" ? "신입 가능" : "경력"}</span>` : ""}
        <span class="company">${esc(j.company)}</span>
        <span>${esc(j.group || "")}${j.fields.length ? ` · ${j.fields.join("·")}` : ""}</span>
      </div>
      <a class="title" href="${esc(j.url)}" target="_blank" rel="noopener" data-read="${j.id}">${esc(j.title)}</a>
      <div class="tags">${(j.tags || []).map((t) => `<span>${esc(t)}</span>`).join("")}${posted ? `<em class="dl">${posted}</em>` : ""}</div>
      <div class="right">${dday(j)}${editor}</div>
    </article>`;
  }

  function renderJobs() {
    const list = state.jobs.map(view).filter(matches);
    const open = list.filter((j) => !j.closed).sort(byDeadline);
    const closed = list.filter((j) => j.closed).sort(byRecent);
    $("#openList").innerHTML = open.length ? open.map(card).join("")
      : `<p class="empty">${state.jobs.length ? "조건에 맞는 진행 중 공고가 없어요." : "아직 수집된 공고가 없어요. 첫 수집이 끝나면 여기에 보여요."}</p>`;
    $("#closedCount").textContent = `(${closed.length})`;
    $("#closedList").innerHTML = closed.map(card).join("") || `<p class="empty">없음</p>`;
    $("#closedBox").hidden = !closed.length;
  }

  function renderCompanies() {
    const icon = (c) => {
      if (c.source === "link" || !c.url && c.source === "web") return `<td class="st">🔗 직접 확인</td>`;
      const s = state.status[c.id];
      if (!s) return `<td class="st muted">대기 중</td>`;
      if (s.ok === false) return `<td class="st fail">⚠ 수집 실패<span class="err">${esc(s.error || "")}</span></td>`;
      return `<td class="st">✓ ${s.count}건${s.method === "api" ? " · API" : ""}</td>`;
    };
    const groups = [...new Set([...GROUPS, ...state.companies.map((c) => c.group)])];
    $("#companyList").innerHTML = groups.map((g) => {
      const cs = state.companies.filter((c) => c.group === g);
      if (!cs.length) return "";
      return `<section class="cgroup"><h3>${esc(g)} <span class="muted small">${cs.length}</span></h3>
        <table class="ctable">${cs.map((c) => `<tr>
          ${icon(c)}
          <td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>` : esc(c.name)}
            ${c.recommended ? ` <span class="rec">추천</span>` : ""}
            ${c.note ? `<div class="note">${esc(c.note)}</div>` : ""}</td>
          ${admin() ? `<td style="width:60px;text-align:right"><button class="hide-btn" data-del="${esc(c.id)}">삭제</button></td>` : ""}
        </tr>`).join("")}</table></section>`;
    }).join("");
  }

  // ---------- GitHub에 저장 ----------
  async function gh(path, opts = {}) {
    const r = await fetch(`https://api.github.com/repos/${state.repo}/${path}`, {
      ...opts,
      headers: { Authorization: `Bearer ${state.token}`, Accept: "application/vnd.github+json", ...(opts.headers || {}) },
    });
    if (!r.ok) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 160)}`);
    return r.status === 204 ? null : r.json();
  }
  const b64 = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
  const unb64 = (s) => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\n/g, "")), (c) => c.charCodeAt(0)));

  async function updateFile(path, mutate, message) {
    const cur = await gh(`contents/${path}`);
    const next = mutate(JSON.parse(unb64(cur.content)));
    await gh(`contents/${path}`, {
      method: "PUT",
      body: JSON.stringify({ message, content: b64(JSON.stringify(next, null, 1) + "\n"), sha: cur.sha }),
    });
    return next;
  }

  async function setOverride(id, patch) {
    state.overrides[id] = { ...(state.overrides[id] || {}), ...patch };
    const pending = store.get("pendingOverrides", {});
    pending[id] = state.overrides[id];
    store.set("pendingOverrides", pending);
    render();
    try {
      await updateFile("docs/data/overrides.json", (o) => ({ ...o, [id]: state.overrides[id] }), "공고 분류 수정");
      const p = store.get("pendingOverrides", {}); delete p[id]; store.set("pendingOverrides", p);
    } catch (e) {
      alert(`저장 실패 (이 기기에만 반영됨): ${e.message}`);
    }
  }

  // ---------- 이벤트 ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-type],[data-tag],[data-field],[data-group],[data-view],[data-go],[data-read],[data-hide],[data-del]");
    if (!t) return;
    if (t.dataset.type) { state.type = t.dataset.type; store.set("type", state.type); render(); }
    else if (t.dataset.tag) { toggle(state.tags, t.dataset.tag); store.set("tags", [...state.tags]); render(); }
    else if (t.dataset.field) { toggle(state.fields, t.dataset.field); store.set("fields", [...state.fields]); render(); }
    else if (t.dataset.group) { toggle(state.groups, t.dataset.group); store.set("groups", [...state.groups]); render(); }
    else if (t.dataset.view || t.dataset.go) { showView(t.dataset.view || t.dataset.go); }
    else if (t.dataset.read) {
      state.read.add(t.dataset.read); store.set("read", [...state.read]);
      setTimeout(render, 300);
    } else if (t.dataset.hide) {
      if (confirm("이 공고를 숨길까요?")) setOverride(t.dataset.hide, { hidden: true });
    } else if (t.dataset.del) {
      const c = state.companies.find((x) => x.id === t.dataset.del);
      if (c && confirm(`'${c.name}'을(를) 기관 목록에서 삭제할까요?`)) {
        updateFile("docs/data/companies.json", (o) => ({ companies: o.companies.filter((x) => x.id !== c.id) }), `기관 삭제: ${c.name}`)
          .then((o) => { state.companies = o.companies; render(); })
          .catch((err) => alert(`삭제 실패: ${err.message}`));
      }
    }
  });
  document.addEventListener("change", (e) => {
    const s = e.target.closest("[data-edit]");
    if (s) setOverride(s.dataset.edit, { type: s.value === "none" ? null : s.value });
  });
  const toggle = (set, v) => (set.has(v) ? set.delete(v) : set.add(v));

  function showView(v) {
    document.querySelectorAll(".view").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    $("#view-jobs").hidden = v !== "jobs";
    $("#view-companies").hidden = v !== "companies";
    window.scrollTo(0, 0);
  }

  $("#q").addEventListener("input", (e) => { state.q = e.target.value.trim(); renderJobs(); });
  $("#newOnly").addEventListener("change", (e) => { state.newOnly = e.target.checked; renderJobs(); });
  $("#hideExp").addEventListener("change", (e) => { state.hideExp = e.target.checked; store.set("hideExp", state.hideExp); renderJobs(); });
  $("#newcomerOnly").addEventListener("change", (e) => { state.newcomerOnly = e.target.checked; store.set("newcomerOnly", state.newcomerOnly); renderJobs(); });
  $("#hideRead").addEventListener("change", (e) => { state.hideRead = e.target.checked; store.set("hideRead", state.hideRead); renderJobs(); });
  $("#resetFilters").addEventListener("click", () => {
    state.tags.clear(); state.groups.clear(); state.fields.clear(); store.set("fields", []); state.q = ""; state.newOnly = false; state.hideRead = false;
    state.hideExp = false; state.newcomerOnly = false; store.set("hideExp", false); store.set("newcomerOnly", false);
    $("#q").value = ""; store.set("tags", []); store.set("groups", []); store.set("hideRead", false); render();
  });

  // 설정
  $("#openSettings").addEventListener("click", () => {
    $("#repoInput").value = state.repo; $("#tokenInput").value = state.token; $("#settingsMsg").textContent = "";
    $("#settings").showModal();
  });
  $("#saveSettings").addEventListener("click", () => {
    state.repo = $("#repoInput").value.trim(); state.token = $("#tokenInput").value.trim();
    store.set("repo", state.repo); store.set("token", state.token); render();
  });
  $("#runNow").addEventListener("click", async () => {
    state.repo = $("#repoInput").value.trim(); state.token = $("#tokenInput").value.trim();
    try {
      await gh("actions/workflows/collect.yml/dispatches", { method: "POST", body: JSON.stringify({ ref: "main" }) });
      $("#settingsMsg").textContent = "수집을 시작했어요. 3~5분 뒤 새로고침하세요.";
    } catch (e) { $("#settingsMsg").textContent = `실패: ${e.message}`; }
  });

  // 기관 추가
  $("#groupSelect").innerHTML = GROUPS.map((g) => `<option>${g}</option>`).join("");
  $("#addCompanyBtn").addEventListener("click", () => {
    if (!admin()) { alert("기관을 추가하려면 먼저 ⚙ 관리 설정에서 GitHub 토큰을 넣어주세요."); return; }
    $("#addCompanyForm").reset(); $("#addCompany").showModal();
  });
  $("#addCompanyForm").addEventListener("submit", async (e) => {
    if (e.submitter && e.submitter.value === "cancel") return;
    const f = new FormData(e.target);
    const name = f.get("name").trim();
    const c = {
      name, group: f.get("group"), source: f.get("source"), url: f.get("url").trim() || null,
      recommended: false, id: name.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, ""),
    };
    if (f.get("note").trim()) c.note = f.get("note").trim();
    try {
      const o = await updateFile("docs/data/companies.json", (o) => ({ companies: [...o.companies.filter((x) => x.id !== c.id), c] }), `기관 추가: ${name}`);
      state.companies = o.companies; render();
    } catch (err) { alert(`추가 실패: ${err.message}`); }
  });

  showView("jobs");
  load();
})();
