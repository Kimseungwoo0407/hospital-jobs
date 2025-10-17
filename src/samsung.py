# pip install requests beautifulsoup4
import os, re, json, logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode, urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.samsunghospital.com"
LIST_PATH = "/home/recruit/recruitInfo/recruitNotice.do"
HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("samsung")

# ---------- utils ----------
def set_cpage(url: str, page: int) -> str:
    """cPage는 '01','02' 형식."""
    u = urlparse(url)
    q = parse_qs(u.query)
    q["cPage"] = [f"{page:02d}"]
    new_q = urlencode(q, doseq=True)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, u.fragment))

def parse_dt_kst(s: str):
    s = s.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_range(txt: str):
    """
    '2025.10.15\n~ 2025.10.22' 같은 형식을 처리.
    """
    if not txt:
        return None, None
    # 줄바꿈/공백 정리 후 점→대시
    t = re.sub(r"\s*~\s*", " ~ ", " ".join(txt.split())).replace(".", "-")
    m = re.search(
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*~\s*"
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)", t
    )
    if not m:
        dt = parse_dt_kst(t)
        return dt, None
    sdt = parse_dt_kst(m.group(1))
    edt = parse_dt_kst(m.group(2))
    if edt and edt.hour == 0 and edt.minute == 0 and not re.search(r"\d{2}:\d{2}", m.group(2)):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

# ---------- core ----------
def crawl_samsung(output="samsung.json", start_page=1, max_pages=50, end_past_skip=True):
    """
    - #contents > table 내부 tr 순회
    - 제목:    td.text-left > a
    - 접수기간: td:nth-child(5)
    - 마감일:   td.deadline-today  (참고용: 값 저장)
    - 상태:    td:nth-child(7) 가 '진행중'만 수집
    - 진행중 아닌 항목을 만나면 즉시 중단
    - 한 페이지에서 0건이면 중단
    - end_past_skip=True면 end_dt < 오늘은 스킵(안심장치)
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)
    base_list_url = BASE + LIST_PATH

    results = []
    today = datetime.now(KST).date()
    hard_stop = False

    for page in range(start_page, start_page + max_pages):
        url = set_cpage(base_list_url, page)
        log.info("GET %s", url)
        r = sess.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        table = soup.select_one("#contents > table")
        if not table:
            log.warning("리스트 테이블을 못 찾음(page=%s). 중단.", page)
            break

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else []
        if not rows:
            log.info("더 이상 항목 없음(page=%s). 종료.", page)
            break

        add_count = 0
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 7:
                continue

            # 상태(td:nth-child(7))
            status_text = tds[6].get_text(strip=True)

            # 진행중만 수집, 진행중이 아니면 하드 스톱
            if "진행중" not in status_text:
                hard_stop = True
                break

            # 제목/링크
            a = tr.select_one("td.text-left > a")
            title = a.get_text(strip=True) if a else tds[2].get_text(strip=True)
            detail_url = urljoin(BASE, a.get("href", "")) if a and a.has_attr("href") else None

            # 접수기간(td:nth-child(5))
            period_text = tds[4].get_text("\n", strip=True)
            sdt, edt = parse_range(period_text)

            # 마감일(td.deadline-today) - 값만 저장(필터엔 안 씀)
            deadline_el = tr.select_one("td.deadline-today")
            deadline_text = deadline_el.get_text(strip=True) if deadline_el else None

            # 이미 지난 공고는 안전하게 스킵(옵션)
            if end_past_skip and edt and edt.date() < today:
                continue

            results.append({
                "title": title,
                "period_text": period_text,
                "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
                "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
                "deadline_text": deadline_text,   # 예: 'D-6', '오늘마감' 등
                "status": status_text,            # '진행중'
                "detail_url": detail_url
            })
            add_count += 1

        log.info("page %d: %d건 수집 (누적 %d)", page, add_count, len(results))

        if hard_stop:
            log.info("진행중이 아닌 항목 발견 → 즉시 중단.")
            break
        if add_count == 0:
            log.info("page %d에서 신규 수집 0건 → 종료.", page)
            break

    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("저장 완료: %s (총 %d건)", output, len(results))
    return results

if __name__ == "__main__":
    crawl_samsung(
        output=os.getenv("OUTPUT", "samsung.json"),
        start_page=int(os.getenv("START_PAGE", "1")),
        max_pages=int(os.getenv("MAX_PAGES", "50")),
        end_past_skip=(os.getenv("END_PAST_SKIP", "1") == "1"),
    )
