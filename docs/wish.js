(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const today = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const days = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
  const store = {
    get(k, d) { try { const v = localStorage.getItem("wish:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("wish:" + k, JSON.stringify(v)); } catch { /* 무시 */ } },
  };
  const state = { wish: [], biz: [], culture: [], updated: null, career: store.get("career", "all"),
    openOnly: store.get("openOnly", true), showClosed: store.get("showClosed", false) };

  const get = async (p, d) => { try { const r = await fetch(`${p}?t=${Date.now()}`, { cache: "no-store" }); return r.ok ? r.json() : d; } catch { return d; } };

  async function load() {
    const [w, b, c] = await Promise.all([get("data/wishlist.json", { companies: [] }), get("data/biz_jobs.json", { jobs: [] }), get("data/jobs.json", { jobs: [] })]);
    state.wish = w.companies || []; state.biz = b.jobs || []; state.culture = c.jobs || [];
    state.updated = b.updated || c.updated;
    render();
  }


  // 회사별 공고 모으기
  function postingsFor(w) {
    const re = new RegExp(w.match, "i");
    const roleHits = (title) => w.roles.filter((r) => new RegExp(r.pattern, "i").test(title)).map((r) => r.label);
    const out = [];
    const seen = new Set();
    for (const j of state.biz) {
      if (!re.test(j.company)) continue;
      const roles = roleHits(j.title);
      if (w.kind === "company" && !roles.length) continue; // 기업: 고른 직무만
      out.push({ ...j, roles });
    }
    if (w.kind === "public") { // 공공기관: 탭1 공고(공공기관 API·아트모아·홈페이지)도 함께
      for (const j of state.culture) {
        if (!re.test(j.company) && !re.test(j.title)) continue;
        out.push({ ...j, roles: roleHits(j.title), career: j.career === "신입" ? "신입 가능" : j.career,
          emp_type: j.type === "계약직" ? "계약직·기간제" : j.type, education: "", location: j.region || "" });
      }
    }
    return out.filter((j) => { const k = j.title.replace(/\W/g, ""); if (seen.has(k)) return false; seen.add(k); return true; })
      .filter((j) => state.career === "all" || (state.career === "new" ? j.career === "신입" || j.career === "신입 가능" : j.career === "경력"));
  }

  function dday(j) {
    if (!j.deadline) return `<span class="dl">${j.always_open ? "상시·채용 시 마감" : "마감일 미표기"}</span>`;
    const n = days(today(), j.deadline);
    return `<span class="dday ${!j.closed && n <= 3 ? "soon" : ""}">${j.closed ? "마감" : n === 0 ? "오늘 마감" : "D-" + n}</span><span class="dl">~${j.deadline.slice(5).replace("-", ".")}</span>`;
  }
  function card(j) {
    const cond = [j.career_detail && j.career_detail !== j.career ? `${j.career || ""} (${j.career_detail})` : j.career, j.education, j.emp_type, j.location].filter(Boolean);
    return `<article class="job">
      <div class="meta">${(j.roles || []).map((r) => `<span class="badge target">${esc(r)}</span>`).join("")}
        <span class="company">${esc(j.company)}</span><span>${esc(j.source || "")}</span></div>
      <a class="title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
      <div class="cond">${cond.map((x) => `<span>${esc(x)}</span>`).join("")}</div>
      ${j.requirements ? `<details class="req"><summary>자격요건 보기</summary><pre>${esc(j.requirements)}</pre></details>` : ""}
      <div class="right">${dday(j)}</div>
    </article>`;
  }

  function render() {
    if (state.updated) $("#updated").textContent = "마지막 수집 " + new Date(state.updated).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul" });
    $("#careerChips").innerHTML = [["all", "전체"], ["new", "신입 가능"], ["exp", "경력"]]
      .map(([k, l]) => `<button class="chip ${state.career === k ? "on" : ""}" data-career="${k}">${l}</button>`).join("");
    $("#openOnly").checked = state.openOnly; $("#showClosed").checked = state.showClosed;

    let totalOpen = 0, withOpen = 0;
    const sections = state.wish.map((w, i) => {
      const ps = postingsFor(w);
      const open = ps.filter((j) => !j.closed).sort((a, b) => (a.deadline || "9999").localeCompare(b.deadline || "9999"));
      const closed = ps.filter((j) => j.closed).sort((a, b) => (b.deadline || "").localeCompare(a.deadline || ""));
      totalOpen += open.length; if (open.length) withOpen++;
      if (state.openOnly && !open.length) return { w, i, html: "", n: 0 };
      const html = `<section class="cgroup" id="w${i}">
        <h3>${esc(w.name)} <span class="muted small">${w.kind === "public" ? "공공기관" : "기업"} · 진행 중 ${open.length}건</span>
          <a class="small" href="${esc(w.url)}" target="_blank" rel="noopener" style="margin-left:6px">채용 사이트 ↗</a></h3>
        <div class="cond" style="margin-bottom:8px">${w.roles.map((r) => `<span>${esc(r.label)}</span>`).join("")}</div>
        <div class="list">${open.map(card).join("") || `<p class="muted small">지금 진행 중인 해당 직무 공고가 없어요.</p>`}</div>
        ${state.showClosed && closed.length ? `<details class="closed-box"><summary>마감된 공고 (${closed.length})</summary><div class="list closed">${closed.slice(0, 30).map(card).join("")}</div></details>` : ""}
      </section>`;
      return { w, i, html, n: open.length };
    });
    $("#jump").innerHTML = sections.filter((s) => s.html).map((s) => `<a class="chip" href="#w${s.i}" style="text-decoration:none">${esc(s.w.name)}${s.n ? ` <span class="muted">${s.n}</span>` : ""}</a>`).join("");
    $("#summary").textContent = `${state.wish.length}곳 중 ${withOpen}곳에서 진행 중인 공고 ${totalOpen}건`;
    $("#list").innerHTML = sections.map((s) => s.html).join("") || `<p class="empty">진행 중인 공고가 있는 회사가 없어요. '진행 중인 공고가 있는 회사만'을 끄면 전체 회사를 볼 수 있어요.</p>`;
  }

  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-career]");
    if (t) { state.career = t.dataset.career; store.set("career", state.career); render(); }
  });
  $("#openOnly").addEventListener("change", (e) => { state.openOnly = e.target.checked; store.set("openOnly", state.openOnly); render(); });
  $("#showClosed").addEventListener("change", (e) => { state.showClosed = e.target.checked; store.set("showClosed", state.showClosed); render(); });
  load();
})();
