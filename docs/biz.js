(() => {
  "use strict";
  const JOBS = ["AX 전략기획", "경영혁신", "PI", "경영전략·경영기획", "HR Transformation", "HR Planning", "IT 전략기획", "DX 컨설팅"];
  const CAREERS = [
    { key: "all", label: "전체" },
    { key: "new", label: "신입 가능" },
    { key: "exp", label: "경력" },
  ];
  const CATS = ["IT·플랫폼", "엔터테인먼트", "콘텐츠", "IT·AX 솔루션", "경영·IT 컨설팅"];
  const NEW_DAYS = 3;

  const store = {
    get(k, d) { try { const v = localStorage.getItem("biz:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("biz:" + k, JSON.stringify(v)); } catch { /* 무시 */ } },
  };
  const state = {
    jobs: [], updated: null, sources: {},
    sel: new Set(store.get("jobs", [])), career: store.get("career", "all"), cats: new Set(store.get("cats", [])),
    targetOnly: store.get("targetOnly", false), internOnly: false, hideHH: store.get("hideHH", true), newOnly: false, q: "",
    read: new Set(store.get("read", [])),
  };
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const today = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const days = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);

  async function load() {
    try {
      const r = await fetch(`data/biz_jobs.json?t=${Date.now()}`, { cache: "no-store" });
      const d = await r.json();
      state.jobs = d.jobs || []; state.updated = d.updated; state.sources = d.sources || {};
    } catch { state.jobs = []; }
    render();
  }

  function view(j) {
    const ref = (state.updated || today()).slice(0, 10);
    return { ...j, isNew: !j.initial && !j.closed && days(j.first_seen, ref) < NEW_DAYS, isRead: state.read.has(j.id) };
  }
  function matches(j) {
    if (state.sel.size && !(j.jobs || []).some((x) => state.sel.has(x))) return false;
    if (state.career === "new" && !(j.career === "신입" || j.career === "신입 가능")) return false;
    if (state.career === "exp" && j.career !== "경력") return false;
    if (state.cats.size && !state.cats.has(j.target_cat)) return false;
    if (state.targetOnly && !j.target) return false;
    if (state.internOnly && !j.intern) return false;
    if (state.hideHH && j.headhunter) return false;
    if (state.newOnly && !j.isNew) return false;
    if (state.q) {
      const hay = `${j.company} ${j.title} ${j.requirements || ""}`.toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  function render() {
    if (state.updated) {
      const t = new Date(state.updated).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul" });
      $("#updated").textContent = `마지막 수집 ${t}`;
    } else $("#updated").textContent = "아직 수집 기록이 없어요";
    const fails = Object.entries(state.sources).filter(([, v]) => v && v.ok === false);
    $("#alerts").innerHTML = fails.length ? `<div class="alert">⚠ 수집 실패: ${fails.map(([k, v]) => `${esc(k)} (${esc(v.error || "")})`).join(", ")}</div>` : "";

    const all = state.jobs.map(view);
    const open = all.filter((j) => !j.closed);
    $("#jobChips").innerHTML = JOBS.map((x) => {
      const n = open.filter((j) => (j.jobs || []).includes(x) && (!state.hideHH || !j.headhunter)).length;
      return `<button class="chip ${state.sel.has(x) ? "on" : ""}" data-job="${x}">${x} <span class="muted">${n}</span></button>`;
    }).join("");
    $("#careerChips").innerHTML = CAREERS.map((c) => `<button class="chip ${state.career === c.key ? "on" : ""}" data-career="${c.key}">${c.label}</button>`).join("");
    $("#catChips").innerHTML = CATS.map((c) => `<button class="chip ${state.cats.has(c) ? "on" : ""}" data-cat="${c}">${c}</button>`).join("");
    $("#targetOnly").checked = state.targetOnly; $("#hideHH").checked = state.hideHH;

    const list = all.filter(matches);
    const o = list.filter((j) => !j.closed).sort((a, b) =>
      (b.target ? 1 : 0) - (a.target ? 1 : 0) || (a.deadline || "9999").localeCompare(b.deadline || "9999"));
    const c = list.filter((j) => j.closed).sort((a, b) => (b.deadline || b.last_seen).localeCompare(a.deadline || a.last_seen));
    $("#summary").textContent = `진행 중 ${o.length}건 · 관심 기업 공고가 위에 먼저 보여요`;
    $("#openList").innerHTML = o.length ? o.map(card).join("") : `<p class="empty">${state.jobs.length ? "조건에 맞는 진행 중 공고가 없어요." : "아직 수집된 공고가 없어요. 다음 아침 수집 후 보여요."}</p>`;
    $("#closedCount").textContent = `(${c.length})`;
    $("#closedList").innerHTML = c.slice(0, 200).map(card).join("");
    $("#closedBox").hidden = !c.length;
  }

  function dday(j) {
    if (!j.deadline) return `<span class="dl">${j.always_open ? "상시·채용 시 마감" : "마감일 미표기"}</span>`;
    const n = days(today(), j.deadline);
    const label = j.closed ? "마감" : n === 0 ? "오늘 마감" : `D-${n}`;
    return `<span class="dday ${!j.closed && n <= 3 ? "soon" : ""}">${label}</span><span class="dl">~${j.deadline.slice(5).replace("-", ".")}</span>`;
  }
  function card(j) {
    const careerTxt = j.career ? (j.career_detail && j.career_detail !== j.career ? `${j.career} (${j.career_detail})` : j.career) : (j.career_detail || "");
    const cond = [careerTxt, j.education, j.emp_type, j.location].filter(Boolean);
    return `<article class="job ${j.isRead ? "read" : ""}">
      <div class="meta">
        ${(j.jobs || []).map((x) => `<span class="badge job">${esc(x)}</span>`).join("")}
        ${j.isNew ? `<span class="badge new">NEW</span>` : ""}
        ${j.target ? `<span class="badge target">관심 · ${esc(j.target)}</span>` : ""}
        ${j.headhunter ? `<span class="badge hh">헤드헌팅</span>` : ""}
        <span class="company">${esc(j.company)}</span>
        <span>${esc(j.source)}</span>
      </div>
      <a class="title" href="${esc(j.url)}" target="_blank" rel="noopener" data-read="${esc(j.id)}">${esc(j.title)}</a>
      <div class="cond">${cond.map((x) => `<span>${esc(x)}</span>`).join("")}</div>
      ${j.requirements ? `<details class="req"><summary>자격요건 보기</summary><pre>${esc(j.requirements)}</pre></details>`
        : `<div class="req muted">자격요건: ${j.req_checked ? "공고 원문에서 확인" : "다음 수집 때 가져와요"}</div>`}
      <div class="right">${dday(j)}</div>
    </article>`;
  }

  const toggle = (set, v) => (set.has(v) ? set.delete(v) : set.add(v));
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-job],[data-career],[data-cat],[data-read]");
    if (!t) return;
    if (t.dataset.job) { toggle(state.sel, t.dataset.job); store.set("jobs", [...state.sel]); }
    else if (t.dataset.career) { state.career = t.dataset.career; store.set("career", state.career); }
    else if (t.dataset.cat) { toggle(state.cats, t.dataset.cat); store.set("cats", [...state.cats]); }
    else if (t.dataset.read) { state.read.add(t.dataset.read); store.set("read", [...state.read]); setTimeout(render, 300); return; }
    render();
  });
  $("#q").addEventListener("input", (e) => { state.q = e.target.value.trim(); render(); });
  $("#targetOnly").addEventListener("change", (e) => { state.targetOnly = e.target.checked; store.set("targetOnly", state.targetOnly); render(); });
  $("#internOnly").addEventListener("change", (e) => { state.internOnly = e.target.checked; render(); });
  $("#hideHH").addEventListener("change", (e) => { state.hideHH = e.target.checked; store.set("hideHH", state.hideHH); render(); });
  $("#newOnly").addEventListener("change", (e) => { state.newOnly = e.target.checked; render(); });
  $("#resetFilters").addEventListener("click", () => {
    state.sel.clear(); state.cats.clear(); state.career = "all"; state.targetOnly = false; state.internOnly = false; state.hideHH = true; state.newOnly = false; state.q = "";
    $("#q").value = ""; $("#internOnly").checked = false; $("#newOnly").checked = false;
    ["jobs", "cats"].forEach((k) => store.set(k, [])); store.set("career", "all"); store.set("targetOnly", false); store.set("hideHH", true);
    render();
  });
  load();
})();
