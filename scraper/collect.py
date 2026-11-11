"""채용공고 수집기.

하루 한 번 GitHub Actions에서 실행된다.
  1) 공공기관 채용정보 API(공공데이터포털)로 문체부 산하 공공기관 공고 수집
  2) 각 기관 채용 게시판(web)에서 공고 제목/링크 수집
  3) docs/data/jobs.json, status.json 갱신
  4) 새 공고가 있으면 이메일 발송
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import smtplib
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
TODAY = NOW.date()
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NO_DEADLINE_DAYS = 30  # 마감일을 못 찾은 공고는 이 기간이 지나면 마감 처리

# ---------------------------------------------------------------- 분류 규칙
TYPE_RULES = [  # 위에서부터 먼저 맞는 것으로 분류
    ("대외활동", r"서포터즈|자원\s*봉사|자원\s*활동|봉사단|기자단|홍보대사|모니터링단|앰배서더|활동가\s*모집"),
    ("인턴", r"인턴"),
    ("계약직", r"계약|기간제|공무직|임시직|대체\s*인력|대체근로|육아휴직|단기|시간제|초단시간|위촉|촉탁|초빙|비정규|아르바이트|하우스\s*어텐던트|안내원|어셔"),
    ("정규직", r"정규|일반직|신입|경력|직원\s*(공개)?\s*채용|공개\s*채용|공채"),
]
JOB_KEYWORDS = {
    "경영지원": r"경영\s*지원|총무|인사|회계|재무|행정|사무|경영관리",
    "경영기획": r"경영\s*기획|기획\s*조정|예산|성과\s*관리",
    "전략기획": r"전략|기획",
    "홍보마케팅": r"홍보|마케팅|브랜드|PR|커뮤니케이션|SNS",
    "하우스안내원": r"하우스\s*(안내|매니저|어텐던트|어셔)|안내원|어셔|어텐던트|객석\s*안내|공연장\s*안내|안내\s*데스크",
}
# 게시판 글 중 '공고'로 볼 것 / 뺄 것
INCLUDE = r"채용|모집|인턴|서포터즈|자원\s*봉사|자원\s*활동|어텐던트|안내원|구인"
EXCLUDE = (r"합격|결과|발표|면접|필기|서류\s*(심사|전형)|입찰|대관|사전규격|강좌|수강|교육생|"
           r"수강생|참여자|참가자|입주|공모전|심의위원|평가위원|위원\s*후보|단원|오디션|아카데미|현황|생활체육|"
           r"용역|검진|지원사업|임원|비상임|감사|이사\s*(공개)?모집|공연장\s*모집|단체\s*모집|"
           r"원고|강사|전시\s*모집|제휴|업체|캠프|작가\s*모집|교육\s*프로그램|"
           r"관객|관람|이벤트|당첨|낙찰|계약\s*체결|선정\s*(결과|알림)")
NAV_WORDS = {"채용", "채용공고", "채용정보", "채용 공고", "인재채용", "채용안내", "더보기",
             "채용공고 더보기", "모집", "모집공고", "recruit", "careers"}
NOT_CULTURE = r"농림|농업|수산|산림|축산|해양|국토|에너지|체육|관광공사"
CULTURE_INST = r"문화|예술|박물관|극장|극단|콘텐츠|도서관|문학|영상|저작권|출판|발레|오페라|무용|오케스트라|심포니|국악|공예|세종학당|영화"


def classify_type(text: str) -> str | None:
    for t, pat in TYPE_RULES:
        if re.search(pat, text, re.I):
            return t
    return None


def job_tags(text: str) -> list[str]:
    return [k for k, pat in JOB_KEYWORDS.items() if re.search(pat, text, re.I)]


def norm(s: str) -> str:
    s = re.sub(r"재단법인|사단법인|\((재|사|주)\)|㈜", "", s or "")
    return re.sub(r"[\s()（）\[\]·.\-_]", "", s)


def mkid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


DATE_RE = r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})"


def to_date(y, m, d) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def find_deadline(text: str) -> date | None:
    m = re.search(r"~\s*\(?\s*" + DATE_RE, text)
    if m:
        return to_date(*m.groups())
    m = re.search(r"(마감|까지|접수\s*기간)[^0-9]{0,8}" + DATE_RE, text)
    if m:
        return to_date(*m.groups()[1:])
    # '~ 11.20' 처럼 연도 없는 마감
    m = re.search(r"~\s*\(?\s*(\d{1,2})\s*[./월]\s*(\d{1,2})", text)
    if m:
        d = to_date(TODAY.year, *m.groups())
        if d and d < TODAY - timedelta(days=180):
            d = to_date(TODAY.year + 1, *m.groups())
        return d
    return None


def find_post_date(text: str) -> date | None:
    ds = [to_date(*m.groups()) for m in re.finditer(DATE_RE, text)]
    ds = [d for d in ds if d and d <= TODAY + timedelta(days=1)]
    return max(ds) if ds else None


# ---------------------------------------------------------------- 공공기관 API
def collect_alio(companies: list[dict], key: str) -> tuple[list[dict], dict]:
    names = {}
    for c in companies:
        if c["source"] == "alio":
            for n in [c["name"]] + c.get("aliases", []):
                names[norm(n)] = c
    url = "https://apis.data.go.kr/1051000/recruitment/list"
    items, page, total = [], 1, None
    params = {"serviceKey": key, "resultType": "json", "numOfRows": 100, "ongoingYn": "Y"}
    while True:
        r = requests.get(url, params={**params, "pageNo": page}, timeout=30)
        r.raise_for_status()
        j = r.json()
        if "result" not in j:  # 오류 응답
            raise RuntimeError(json.dumps(j, ensure_ascii=False)[:300])
        rows = j.get("result") or []
        rows = [x.get("item", x) if isinstance(x, dict) else x for x in rows]
        items += rows
        total = j.get("totalCount", 0)
        if not rows or len(items) >= total or page >= 40:
            break
        page += 1
        time.sleep(0.3)
    out, matched = [], set()
    for it in items:
        inst = it.get("instNm", "")
        c = names.get(norm(inst))
        if not c and (not re.search(CULTURE_INST, inst) or re.search(NOT_CULTURE, inst)):
            continue
        hire = it.get("hireTypeNmLst") or ""
        title = it.get("recrutPbancTtl") or ""
        hire_list = [h.strip() for h in hire.split(",") if h.strip()]
        if "인턴" in hire or "인턴" in title:
            t = "인턴"
        elif "정규직" in hire_list:
            t = "정규직"
        elif hire:
            t = "계약직"
        else:
            t = classify_type(title)
        if c:
            matched.add(c["id"])
        sn = str(it.get("recrutPblntSn"))
        out.append({
            "id": "alio-" + sn,
            "company": c["name"] if c else inst,
            "company_id": c["id"] if c else None,
            "group": c["group"] if c else "문체부 산하 공공기관",
            "title": title.strip(),
            "url": f"https://job.alio.go.kr/recruitview.do?idx={sn}",
            "type": t,
            "type_detail": hire,
            "tags": job_tags(title + " " + (it.get("ncsCdNmLst") or "")),
            "posted": _ymd(it.get("pbancBgngYmd")),
            "deadline": _ymd(it.get("pbancEndYmd")),
            "region": it.get("workRgnNmLst"),
            "source": "공공기관 채용정보",
        })
    return out, {"total_api": len(items), "matched": sorted(matched)}


def _ymd(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


# ---------------------------------------------------------------- 게시판 수집
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
_browser = None


def fetch_static(url: str) -> str:
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


def fetch_rendered(url: str) -> str:
    global _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        kw = {}
        if os.environ.get("CHROMIUM_PATH"):
            kw["executable_path"] = os.environ["CHROMIUM_PATH"]
        if os.environ.get("HTTPS_PROXY"):
            kw["proxy"] = {"server": os.environ["HTTPS_PROXY"]}
        _browser = pw.chromium.launch(**kw)
    page = _browser.new_page(user_agent=UA, locale="ko-KR")
    try:
        page.goto(url, wait_until="load", timeout=45000)
        page.wait_for_timeout(4000)
        return page.content()
    finally:
        page.close()


def extract_next_data(html: str, base: str, company: dict) -> list[dict]:
    """Next.js 사이트: 페이지에 숨겨진 __NEXT_DATA__ JSON에서 글 목록을 읽는다.
    company["json_link"] 예: "/notice/detail/{id}" """
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    rows = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("title"), str) and "id" in o:
                rows.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(m.group(1)))
    inc = re.compile(company.get("include") or INCLUDE, re.I)
    out = []
    for r in rows:
        title = r["title"].strip()
        if not inc.search(title) or re.search(EXCLUDE, title):
            continue
        link = urljoin(base, company["json_link"].format(**r))
        posted = find_post_date(str(r.get("createdDate") or r.get("regDate") or ""))
        out.append({
            "id": mkid(company["id"], link), "company": company["name"], "company_id": company["id"],
            "group": company["group"], "title": title, "url": link, "type": classify_type(title),
            "tags": job_tags(title), "posted": posted.isoformat() if posted else None,
            "deadline": (lambda d: d.isoformat() if d else None)(find_deadline(title)),
            "closed_mark": False, "source": "기관 홈페이지",
        })
    return out


def extract(html: str, base: str, company: dict) -> list[dict]:
    if company.get("json_link"):
        return extract_next_data(html, base, company)
    soup = BeautifulSoup(html, "html.parser")
    inc = re.compile(company.get("include") or INCLUDE, re.I)
    out, seen = [], set()
    for a in soup.find_all("a"):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if len(text) < 8 or text.strip() in NAV_WORDS:
            continue
        if not inc.search(text) or re.search(EXCLUDE, text):
            continue
        row = a.find_parent(["tr", "li"]) or a.parent
        row_text = re.sub(r"\s+", " ", row.get_text(" ", strip=True)) if row else text
        if len(row_text) > 400:
            row_text = text
        href = (a.get("href") or "").strip()
        if company.get("link_pattern") and not re.search(company["link_pattern"], href):
            continue
        link = base if (not href or href.startswith(("#", "javascript"))) else urljoin(base, href)
        title = re.sub(r"^번호\s*\d+\s*|^제목\s*|\s*(작성일|등록일|조회수?)\b.*$", "", text)
        title = re.sub(r"^제목\s*", "", title)
        title = re.sub(r"^\d{1,3}\s+(20\d{2}\.\d{1,2}\.?\s*)?", "", title)
        title = re.sub(r"\s*20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?\s*(채용공고|공지|모집)?\s*$", "", title)
        title = re.sub(r"^채용공고\s+(?=\S)", "", title)
        if len(title) > 90:  # 본문 미리보기까지 붙은 경우 첫 '공고'까지만
            m = re.search(r"^.{15,90}?공고", title)
            title = m.group(0) if m else title[:90] + "…"
        title = re.sub(r"\s*20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\.?\s*$", "", title)
        title = re.sub(r"^(채용공고\s*)?(진행중|접수중|종료|마감)\s*", "", title).strip()
        key = link if link != base else title
        if key in seen:
            continue
        seen.add(key)
        closed_mark = bool(re.search(r"(^|\s)(종료|마감|접수마감)(\s|$)", row_text.replace(title, " ")))
        dl = find_deadline(text) or find_deadline(row_text)
        out.append({
            "id": mkid(company["id"], key),
            "company": company["name"],
            "company_id": company["id"],
            "group": company["group"],
            "title": title,
            "url": link,
            "type": classify_type(title),
            "tags": job_tags(title),
            "posted": (find_post_date(row_text.replace(text, " ")) or find_post_date(text) or None),
            "deadline": dl,
            "closed_mark": closed_mark,
            "source": "기관 홈페이지",
        })
    for o in out:
        for k in ("posted", "deadline"):
            if isinstance(o[k], date):
                o[k] = o[k].isoformat()
    return out


def collect_web(company: dict) -> tuple[list[dict], str]:
    url = company["url"]
    method = "static"
    try:
        html = fetch_static(url)
        items = extract(html, url, company)
    except Exception:
        items, html = [], ""
    # 공고가 거의 안 잡히면(자바스크립트로 목록을 그리는 사이트) 브라우저로 다시 시도
    if len(items) < 3 or company.get("render"):
        try:
            rendered = extract(fetch_rendered(url), url, company)
        except Exception:
            if not html:
                raise
            rendered = []
        if len(rendered) > len(items):
            items, method = rendered, "browser"
    return items, method


STRONG_KEY = r"접수\s*마감|마감\s*기한|마감\s*일시?|까지\s*접수"
DEADLINE_KEY = r"접수\s*마감|마감\s*기한|마감\s*일시?|접수\s*기간|원서\s*접수|서류\s*접수|공고\s*기간|모집\s*기간|지원\s*기간|접수\s*일정"


def detail_deadline(url: str) -> str | None:
    """공고 상세 페이지 본문에서 접수 마감일을 찾는다."""
    raw = fetch_static(url)
    raw = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"\s+", " ", text)
    def first_range_end(window):
        ds = sorted({d for d in (to_date(*m.groups()) for m in re.finditer(DATE_RE, window)) if d})[:2]
        if not ds:
            return None
        # '2026.9.1 ~ 9.15' 처럼 끝 날짜에 연도가 없는 경우
        for m2 in re.finditer(r"~\s*\(?\s*(\d{1,2})\s*[./월]\s*(\d{1,2})(?!\d)", window):
            d2 = to_date(ds[0].year, *m2.groups())
            if d2 and ds[0] <= d2 <= ds[0] + timedelta(days=120):
                ds.append(d2)
        return max(ds)

    # '접수 마감' 같은 확실한 표현을 먼저, 없으면 '접수 기간' 같은 표현의 첫 번째 것
    for pat in (STRONG_KEY, DEADLINE_KEY):
        for k in re.finditer(pat, text):
            d = first_range_end(text[k.end(): k.end() + 80])
            if d and TODAY - timedelta(days=400) < d < TODAY + timedelta(days=200):
                return d.isoformat()
    return None


# ---------------------------------------------------------------- 병합/저장
def load(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def is_closed(j: dict) -> bool:
    if j.get("deadline"):
        return j["deadline"] < TODAY.isoformat()
    if j.get("closed_mark"):
        return True
    base = j.get("posted") or j.get("first_seen")
    return bool(base) and base < (TODAY - timedelta(days=NO_DEADLINE_DAYS)).isoformat()


def send_mail(new_jobs: list[dict], failed: list[str]):
    host, user, pw, to = (os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO"))
    if not (host and user and pw and to):
        print("메일 설정 없음 → 발송 생략")
        return
    site = os.environ.get("SITE_URL", "")
    order = {"정규직": 0, "계약직": 1, "인턴": 2, "대외활동": 3, None: 4}
    rows = []
    for j in sorted(new_jobs, key=lambda x: (order.get(x.get("type"), 4), x.get("deadline") or "9999")):
        rows.append(
            f'<tr><td style="padding:6px 10px;color:#555">{j.get("type") or "미분류"}</td>'
            f'<td style="padding:6px 10px">{j["company"]}</td>'
            f'<td style="padding:6px 10px"><a href="{j["url"]}">{j["title"]}</a></td>'
            f'<td style="padding:6px 10px;color:#555">{j.get("deadline") or "-"}</td></tr>')
    fail = (f'<p style="color:#b45309">⚠ 수집 실패: {", ".join(failed)}</p>' if failed else "")
    html = (f'<div style="font-family:sans-serif"><h2>새 채용공고 {len(new_jobs)}건</h2>'
            f'<table style="border-collapse:collapse;font-size:14px">'
            f'<tr style="background:#f3f4f6"><th>분류</th><th>기관</th><th>공고</th><th>마감</th></tr>'
            + "".join(rows) + "</table>" + fail
            + (f'<p><a href="{site}">채용 모아보기 사이트 열기</a></p>' if site else "") + "</div>")
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = f"[채용 모아보기] 새 공고 {len(new_jobs)}건 ({TODAY:%m/%d})"
    msg["From"] = user
    msg["To"] = to
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    print(f"메일 발송: {to} ({len(new_jobs)}건)")


def main():
    only = sys.argv[1:]  # 테스트용: 특정 기관 id만
    companies = load("companies.json", {"companies": []})["companies"]
    old = {j["id"]: j for j in load("jobs.json", {"jobs": []})["jobs"]}
    # 기관(또는 공공기관 API)을 처음 수집하는 날은 기존 공고를 '새 공고'로 치지 않는다
    prev_ok = {k for k, v in load("status.json", {}).get("companies", {}).items() if v.get("ok")}
    status = {}
    found: list[dict] = []

    key = os.environ.get("DATA_GO_KR_KEY")
    if not only:
        if key:
            try:
                items, info = collect_alio(companies, key)
                found += items
                status["__alio__"] = {"ok": True, "count": len(items), **info}
                for c in companies:
                    if c["source"] == "alio":
                        n = sum(1 for i in items if i["company_id"] == c["id"])
                        status[c["id"]] = {"ok": True, "count": n, "method": "api"}
            except Exception as e:
                status["__alio__"] = {"ok": False, "error": str(e)[:300]}
                for c in companies:
                    if c["source"] == "alio":
                        status[c["id"]] = {"ok": False, "error": "공공기관 API 실패", "method": "api"}
        else:
            status["__alio__"] = {"ok": False, "error": "DATA_GO_KR_KEY 미설정"}
            for c in companies:
                if c["source"] == "alio":
                    status[c["id"]] = {"ok": False, "error": "API 키 미설정", "method": "api"}

    for c in companies:
        if c["source"] != "web" or not c.get("url") or (only and c["id"] not in only):
            continue
        try:
            items, method = collect_web(c)
            found += items
            status[c["id"]] = {"ok": True, "count": len(items), "method": method}
            print(f"OK   {c['name']}: {len(items)}건 ({method})")
        except Exception as e:
            status[c["id"]] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"FAIL {c['name']}: {e}")
        time.sleep(1)

    # 병합
    today = TODAY.isoformat()
    new_jobs = []
    merged = dict(old)
    seen_titles = set()
    for j in found:
        tkey = (j["company"], re.sub(r"\s+", "", j["title"]))
        if tkey in seen_titles:  # 같은 공고가 여러 게시판에 올라온 경우
            continue
        seen_titles.add(tkey)
        prev = old.get(j["id"])
        if prev:
            j["first_seen"] = prev["first_seen"]
            j["initial"] = prev.get("initial", False)
            # 게시판에서 이미 마감일을 알았으면 유지
            j["deadline"] = j.get("deadline") or prev.get("deadline")
        else:
            src = "__alio__" if j["id"].startswith("alio-") else j["company_id"]
            j["first_seen"] = today
            j["initial"] = src not in prev_ok
            if not j["initial"]:
                new_jobs.append(j)
        j["detail_checked"] = (prev or {}).get("detail_checked", False)
        j["last_seen"] = today
        merged[j["id"]] = j
    # 필터 규칙이 바뀌어 이제 제외 대상이 된 예전 글은 정리
    def still_wanted(j):
        if j.get("source") == "기관 홈페이지":
            return not re.search(EXCLUDE, j["title"])
        # 공공기관 API: 목록에 없는 기관 중 문화와 무관한 곳은 제외
        return bool(j.get("company_id")) or not re.search(NOT_CULTURE, j.get("company", ""))
    jobs = [j for j in merged.values() if still_wanted(j)]
    # 마감일을 제목에서 못 찾은 게시판 공고는 상세 페이지를 한 번 열어서 찾는다
    checked = 0
    for j in jobs:
        if (j.get("source") == "기관 홈페이지" and not j.get("deadline") and not j.get("detail_checked")
                and j["last_seen"] == today and checked < 40
                and j["url"] != next((c["url"] for c in companies if c["id"] == j["company_id"]), None)):
            checked += 1
            try:
                j["deadline"] = detail_deadline(j["url"])
            except Exception as e:
                print(f"상세 확인 실패 {j['url']}: {e}")
            j["detail_checked"] = True
            time.sleep(0.5)
    for j in jobs:
        j["closed"] = is_closed(j)
    # 마감 후 120일 지난 공고는 정리
    cutoff = (TODAY - timedelta(days=120)).isoformat()
    jobs = [j for j in jobs if not (j["closed"] and (j.get("deadline") or j["last_seen"]) < cutoff)]
    new_jobs = [j for j in new_jobs if not j["closed"]]

    save("jobs.json", {"updated": NOW.isoformat(timespec="minutes"), "jobs": jobs})
    if only:
        prev_status = load("status.json", {}).get("companies", {})
        prev_status.update(status)
        status = prev_status
    save("status.json", {"updated": NOW.isoformat(timespec="minutes"), "companies": status})

    failed = [c["name"] for c in companies if status.get(c["id"], {}).get("ok") is False]
    print(f"총 {len(jobs)}건, 새 공고 {len(new_jobs)}건, 실패 {len(failed)}곳")
    if new_jobs and not only:
        try:
            send_mail(new_jobs, failed)
        except Exception:
            traceback.print_exc()
    if _browser:
        _browser.close()


if __name__ == "__main__":
    main()
