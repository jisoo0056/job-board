"""탭2: 기업 직무 채용 수집기 (AX 전략기획, 경영혁신, PI, 경영전략·기획, HR, IT 전략, DX 컨설팅).

출처
  1) 사람인 검색: 직무 키워드별 + 관심 기업 이름별 (신입/경력, 학력, 고용형태, 마감일 제공)
  2) 네이버 채용 사이트 (네이버·네이버웹툰 등 계열사)
  3) 토스 채용 사이트
새로 잡힌 공고는 상세 페이지를 열어 '자격요건' 부분을 뽑아 둔다.
결과: docs/data/biz_jobs.json, 새 공고가 있으면 메일.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect as base  # noqa: E402  (날짜, 메일 설정 재사용)

TODAY = base.TODAY
NOW = base.NOW
DATA = base.DATA
UA = base.UA
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})

# ---------------------------------------------------------------- 직무 분류 (우선순위 순)
JOBS = [
    ("AX 전략기획", r"\bAX\b|AX\s*(전략|기획|혁신|추진)|AI\s*(전략|기획|혁신|도입|추진|트랜스포메이션|Transformation)|생성형\s*AI\s*(기획|전략)"),
    ("경영혁신", r"경영\s*혁신|조직\s*혁신|혁신\s*(팀|담당|기획|추진)|변화\s*관리|Change\s*Management"),
    ("PI", r"(?<![A-Za-z])PI(?![A-Za-z])|프로세스\s*(혁신|개선)|Process\s*Innovation|BPR|업무\s*프로세스\s*(개선|혁신|설계)"),
    ("경영전략·경영기획", r"경영\s*전략|경영\s*기획|전략\s*기획|사업\s*전략|기획\s*조정|Corporate\s*(Strategy|Planning)|Strategy\s*(Manager|Planning)|전략\s*담당|Biz\s*Strategy"),
    ("HR Transformation", r"HR\s*(Transformation|혁신|DX|시스템|Tech)|인사\s*(혁신|제도)|People\s*(System|Tech|Ops)|HRIS|Workday|SAP\s*HR"),
    ("HR Planning", r"HR\s*(Planning|기획|전략)|인력\s*(계획|운영\s*계획|기획)|조직\s*(설계|개발|문화\s*기획)|인사\s*기획|HRBP|HR\s*Business\s*Partner|HRM|\bOD\b"),
    ("IT 전략기획", r"IT\s*(전략|기획|거버넌스)|정보화\s*(전략|기획)|ISP|디지털\s*전략|IT\s*Strategy|CIO"),
    ("DX 컨설팅", r"\bDX\b|DX\s*(컨설팅|컨설턴트|전략|추진)|디지털\s*(전환|트랜스포메이션)|Digital\s*Transformation|(경영|IT|전략|HR|PI|AX|AI)\s*컨설(팅|턴트)|(Strategy|Management|Digital|DX|AX|HR)\s*Consultant"),
]
SEARCHES = [  # 사람인 검색어
    "AX 전략기획", "AI 전략기획", "AX 추진", "경영혁신", "PI 프로세스혁신", "업무 프로세스 혁신",
    "경영전략", "경영기획", "전략기획", "HR Transformation", "인사제도 혁신", "HRIS",
    "HR Planning", "인사기획", "인력계획 조직설계", "HRBP", "IT 전략기획", "정보화 전략", "DX 컨설팅",
    "디지털 전환 컨설팅", "경영컨설팅", "전략기획 인턴", "HR 인턴", "경영기획 인턴",
]
# 관심 기업: (보여줄 이름, 회사 이름 판별 정규식, 사람인 검색어, 분류)
TARGETS = [
    ("네이버", r"네이버|NAVER", None, "IT·플랫폼"),
    ("카카오", r"^\(?주\)?\s*카카오(?!엔터|뱅크|페이|모빌리티|게임즈)|^카카오$", "카카오", "IT·플랫폼"),
    ("토스", r"비바리퍼블리카|토스", None, "IT·플랫폼"),
    ("HYBE", r"하이브|HYBE|빅히트", "하이브", "엔터테인먼트"),
    ("SM", r"에스엠|SM\s*엔터|SM Entertainment", "에스엠엔터테인먼트", "엔터테인먼트"),
    ("JYP", r"제이와이피|JYP", "제이와이피엔터테인먼트", "엔터테인먼트"),
    ("CJ ENM", r"씨제이이엔엠|CJ\s*ENM", "CJ ENM", "콘텐츠"),
    ("네이버웹툰", r"네이버웹툰|웹툰", None, "콘텐츠"),
    ("카카오엔터테인먼트", r"카카오엔터", "카카오엔터테인먼트", "콘텐츠"),
    ("삼성SDS", r"삼성에스디에스|삼성SDS", "삼성SDS", "IT·AX 솔루션"),
    ("LG CNS", r"엘지씨엔에스|LG\s*CNS", "LG CNS", "IT·AX 솔루션"),
    ("SK AX", r"SK\s*AX|에스케이에이엑스|SK\s*C&C|에스케이씨앤씨|SK주식회사", "SK AX", "IT·AX 솔루션"),
    ("PwC (삼일)", r"삼일회계|삼일PwC|PwC", "삼일회계법인", "경영·IT 컨설팅"),
    ("Deloitte (안진)", r"딜로이트|Deloitte|안진", "딜로이트", "경영·IT 컨설팅"),
    ("EY (한영)", r"한영회계|EY", "EY한영", "경영·IT 컨설팅"),
    ("KPMG (삼정)", r"삼정회계|삼정KPMG|KPMG", "삼정KPMG", "경영·IT 컨설팅"),
]
HEADHUNTER = r"써치|서치|헤드헌|커리어|HR컨설팅|인재|리크루트|Search|파트너스|휴먼|잡코리아|매니지먼트"
REQ_HEAD = r"자격\s*요건|지원\s*자격|필수\s*(요건|사항|역량)|Qualifications|Requirements|이런\s*분을\s*찾|필요\s*역량|Who\s*we\s*are\s*looking"
REQ_END = r"우대\s*(사항|요건)|Preferred|근무\s*조건|채용\s*절차|전형\s*절차|접수\s*(기간|방법)|혜택|복리\s*후생|Benefits|기타\s*사항|유의\s*사항"


def classify_job(text: str) -> list[str]:
    return [name for name, pat in JOBS if re.search(pat, text, re.I)]


def target_of(company: str):
    for name, pat, _, cat in TARGETS:
        if re.search(pat, company, re.I):
            return name, cat
    return None, None


def career_norm(t: str) -> str | None:
    if re.search(r"신입\s*[·/]\s*경력|신입.*경력|경력\s*무관|무관", t):
        return "신입 가능"
    if "신입" in t or "인턴" in t:
        return "신입"
    if "경력" in t:
        return "경력"
    return None


def md_to_date(s: str) -> str | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})", s or "")
    if not m:
        return None
    d = base.to_date(TODAY.year, *m.groups())
    if d and d < TODAY - timedelta(days=60):
        d = base.to_date(TODAY.year + 1, *m.groups())
    return d.isoformat() if d else None


# ---------------------------------------------------------------- 사람인
def saramin_search(word: str, pages: int = 2) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        r = S.get("https://www.saramin.co.kr/zf_user/search/recruit",
                  params={"searchword": word, "recruitPage": page, "recruitPageCount": 40,
                          "recruitSort": "relation"}, timeout=40)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("div.item_recruit")
        for it in items:
            a = it.select_one("h2.job_tit a")
            corp = it.select_one("strong.corp_name a") or it.select_one("strong.corp_name")
            if not a or not corp:
                continue
            title = (a.get("title") or a.get_text(" ", strip=True)).strip()
            company = corp.get_text(" ", strip=True)
            cond = [x.get_text(" ", strip=True) for x in it.select("div.job_condition span")]
            sector = it.select_one("div.job_sector")
            sector_t = sector.get_text(" ", strip=True) if sector else ""
            date_t = (it.select_one("div.job_date .date") or BeautifulSoup("", "html.parser")).get_text(" ", strip=True)
            m = re.search(r"rec_idx=(\d+)", a.get("href", ""))
            if not m:
                continue
            rec = m.group(1)
            career_t = next((c for c in cond if re.search(r"신입|경력|무관", c)), "")
            edu = next((c for c in cond if re.search(r"학력|대졸|고졸|초대졸|석사|박사", c)), "")
            emp = next((c for c in cond if re.search(r"정규직|계약직|인턴|파견|프리랜서|아르바이트|위촉", c)), "")
            loc = cond[0] if cond else ""
            deadline = None
            if re.search(r"오늘\s*마감", date_t):
                deadline = TODAY.isoformat()
            elif re.search(r"내일\s*마감", date_t):
                deadline = (TODAY + timedelta(days=1)).isoformat()
            else:
                deadline = md_to_date(date_t)
            out.append({
                "id": f"saramin-{rec}", "company": company, "title": title,
                "url": f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={rec}",
                "detail_url": f"https://www.saramin.co.kr/zf_user/jobs/relay/view-detail?rec_idx={rec}&rec_seq=0",
                "career": career_norm(career_t + " " + title), "career_detail": career_t,
                "education": edu, "emp_type": emp, "location": loc, "deadline": deadline,
                "always_open": bool(re.search(r"상시|채용시", date_t)),
                "hint": sector_t, "source": "사람인",
            })
        if len(items) < 40:
            break
        time.sleep(1.5)
    return out


# ---------------------------------------------------------------- 네이버
def naver_jobs() -> list[dict]:
    out, idx = [], 0
    while idx < 600:
        r = S.get("https://recruit.navercorp.com/rcrt/loadJobList.do", params={"firstIndex": idx},
                  headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        r.raise_for_status()
        rows = r.json().get("list") or []
        if not rows:
            break
        for x in rows:
            end = x.get("endYmd") or ""
            out.append({
                "id": f"naver-{x['annoId']}", "company": x.get("sysCompanyCdNm") or "NAVER",
                "title": x.get("annoSubject", ""),
                "url": f"https://recruit.navercorp.com/rcrt/view.do?annoId={x['annoId']}",
                "detail_url": f"https://recruit.navercorp.com/rcrt/view.do?annoId={x['annoId']}",
                "career": career_norm((x.get("entTypeCdNm") or "") + " " + x.get("annoSubject", "")),
                "career_detail": x.get("entTypeCdNm") or "", "education": "",
                "emp_type": (x.get("empTypeCdNm") or "").replace("정규", "정규직"), "location": "",
                "deadline": f"{end[:4]}-{end[4:6]}-{end[6:8]}" if re.fullmatch(r"\d{8}", end) and not end.startswith("9999") else None,
                "always_open": end.startswith("9999"),
                "hint": f"{x.get('classCdNm', '')} {x.get('subJobCdNm', '')}", "source": "네이버 채용",
            })
        idx += len(rows)
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------- 토스
def toss_jobs() -> list[dict]:
    r = S.get("https://api-public.toss.im/api/v3/ipd-eggnog/career/jobs", timeout=40)
    r.raise_for_status()
    out = []
    for x in r.json().get("success") or []:
        meta = {m.get("name", ""): m.get("value") for m in x.get("metadata") or []}
        emp = meta.get("Employment_Type") or ""
        sub = next((v for k, v in meta.items() if "자회사" in k and v), None)
        dl = (x.get("application_deadline") or "")[:10] or None
        out.append({
            "id": f"toss-{x['id']}", "company": f"토스 ({sub})" if sub else "토스",
            "title": x.get("title", ""), "url": x.get("absolute_url"), "detail_url": None,
            "career": career_norm(emp + " " + x.get("title", "")), "career_detail": "",
            "education": "", "emp_type": emp if isinstance(emp, str) else "", "location": (x.get("location") or {}).get("name", ""),
            "deadline": dl, "always_open": not dl, "hint": "", "source": "토스 채용",
        })
    return out


# ---------------------------------------------------------------- 자격요건
def requirements_of(url: str) -> str | None:
    r = S.get(url, timeout=30)
    r.raise_for_status()
    text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
    text = re.sub(r"[​﻿]", "", text)
    m = re.search(REQ_HEAD, text, re.I)
    if not m:
        return None
    rest = text[m.end():]
    e = re.search(REQ_END, rest, re.I)
    body = rest[: e.start()] if e else rest[:800]
    lines = [ln.strip(" :•·-○▶※*") for ln in body.split("\n")]
    lines = [ln for ln in lines if len(ln) > 3][:12]
    out = "\n".join(f"· {ln}" for ln in lines)
    return out[:900] or None


# ---------------------------------------------------------------- 메인
def main():
    P = DATA / "biz_jobs.json"
    old_doc = json.loads(P.read_text(encoding="utf-8")) if P.exists() else {"jobs": [], "sources": {}}
    old = {j["id"]: j for j in old_doc["jobs"]}
    prev_ok = {k for k, v in (old_doc.get("sources") or {}).items() if v.get("ok")}
    status, found = {}, []

    def run(key, fn):
        try:
            items = fn()
            status[key] = {"ok": True, "count": len(items)}
            found.extend((key, it) for it in items)
            print(f"OK   {key}: {len(items)}")
        except Exception as e:  # 한 출처가 실패해도 나머지는 계속
            status[key] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"}
            print(f"FAIL {key}: {e}")

    for w in SEARCHES:
        run("사람인", lambda w=w: saramin_search(w))
        time.sleep(1.5)
    for name, _, q, _ in TARGETS:
        if q:
            run("사람인", lambda q=q: saramin_search(q, pages=1))
            time.sleep(1.5)
    run("네이버 채용", naver_jobs)
    run("토스 채용", toss_jobs)
    # 사람인 상태는 검색 여러 번의 합
    sr = [v for k, v in status.items() if k == "사람인"]

    jobs, seen = {}, set()
    for src, j in found:
        text = f"{j['title']} {j.get('hint', '')}"
        cats = classify_job(j["title"])
        if not cats and j["source"] == "사람인" and re.search(r"기획|전략|혁신|인사|HR|컨설|AX|DX", j["title"]):
            cats = classify_job(j.get("hint", ""))  # 제목이 애매하면 사람인 직무 분류로 보조
        tname, tcat = target_of(j["company"])
        if not cats:
            continue
        if base.unwanted(j["title"]):
            continue
        key = re.sub(r"\W", "", j["company"] + j["title"])
        if j["id"] in jobs or key in seen:
            continue
        seen.add(key)
        prev = old.get(j["id"])
        j.update({
            "jobs": cats, "target": tname, "target_cat": tcat,
            "headhunter": bool(re.search(HEADHUNTER, j["company"])) and not tname,
            "intern": bool(re.search(r"인턴", j["title"] + j.get("emp_type", ""))),
        })
        j.pop("hint", None)
        if prev:
            j["first_seen"], j["initial"] = prev["first_seen"], prev.get("initial", False)
            j["requirements"] = prev.get("requirements")
            j["req_checked"] = prev.get("req_checked", False)
        else:
            j["first_seen"] = TODAY.isoformat()
            j["initial"] = j["source"] not in prev_ok
            j["requirements"], j["req_checked"] = None, False
        j["last_seen"] = TODAY.isoformat()
        jobs[j["id"]] = j
    # 이번에 안 잡힌 예전 공고도 마감 표시용으로 남김(60일)
    found_ids = {j["id"] for _, j in found}
    for oid, oj in old.items():
        # 이번에 다시 잡혔는데 규칙상 빠진 공고는 버리고, 목록에서 사라진 공고만 마감 표시용으로 남김
        if oid not in jobs and oid not in found_ids and oj["last_seen"] >= (TODAY - timedelta(days=60)).isoformat():
            jobs[oid] = oj

    # 자격요건: 새 공고 위주로 상세 페이지 확인
    checked = 0
    for j in sorted(jobs.values(), key=lambda j: (not j.get("target"), j["first_seen"]), reverse=False):
        if j.get("req_checked") or not j.get("detail_url") or j["last_seen"] != TODAY.isoformat() or checked >= 150:
            continue
        checked += 1
        try:
            j["requirements"] = requirements_of(j["detail_url"])
        except Exception as e:
            print("자격요건 실패", j["detail_url"], e)
        j["req_checked"] = True
        time.sleep(1.0)

    for j in jobs.values():
        if j.get("deadline"):
            j["closed"] = j["deadline"] < TODAY.isoformat()
        else:  # 상시/채용시 마감: 목록에서 사라진 지 3일 지나면 마감
            j["closed"] = j["last_seen"] < (TODAY - timedelta(days=3)).isoformat()

    sources = {"사람인": {"ok": any(v.get("ok") for v in sr) if sr else False,
                        "count": sum(1 for j in jobs.values() if j["source"] == "사람인" and j["last_seen"] == TODAY.isoformat())},
               "네이버 채용": status.get("네이버 채용", {"ok": False}),
               "토스 채용": status.get("토스 채용", {"ok": False})}
    if sr and not sources["사람인"]["ok"]:
        sources["사람인"]["error"] = next((v.get("error") for v in sr if v.get("error")), "")
    doc = {"updated": NOW.isoformat(timespec="minutes"), "sources": sources,
           "targets": [{"name": n, "category": c} for n, _, _, c in TARGETS],
           "jobs": sorted(jobs.values(), key=lambda j: j["id"])}
    P.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    new = [j for j in jobs.values() if j["first_seen"] == TODAY.isoformat() and not j["initial"]
           and not j["closed"] and not j["headhunter"]]
    print(f"총 {len(jobs)}건, 새 공고 {len(new)}건, 자격요건 확인 {checked}건")
    if new:
        for j in new:
            j["type"] = " · ".join(j["jobs"])
        try:
            base.send_mail(new, [], subject_prefix="[기업 직무]")
        except Exception as e:
            print("메일 실패", e)


if __name__ == "__main__":
    main()
