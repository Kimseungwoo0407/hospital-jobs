# pip install requests beautifulsoup4
import os, json, logging, re
from urllib.parse import urljoin, urlencode, urlparse, urlunparse, parse_qs
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup

BASE = "https://www.snuh.org"
LIST_PATH = "/about/news/recruit/recruList.do"
HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("snuh")

def set_query(url: str, **params) -> str:
    u = urlparse(url)
    q = parse_qs(u.query)
    for k, v in params.items():
        q[k] = [str(v)]
    new_q = urlencode(q, doseq=True)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, u.fragment))

def parse_dt_kst(s: str):
    s = s.strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_range(txt: str):
    if not txt:
        return None, None
    txt = txt.strip()
    m = re.search(
        r"(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*~\s*"
        r"(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)",
        txt
    )
    if not m:
        dt = parse_dt_kst(txt)
        return dt, None
    sdt = parse_dt_kst(m.group(1))
    edt = parse_dt_kst(m.group(2))
    if edt and edt.hour == 0 and edt.minute == 0 and not re.search(r"\d{2}:\d{2}", m.group(2)):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def crawl_snuh(output="snuh.json", start_page=1, max_pages=50):
    """
    - pageIndex로 페이지네이션
    - 5번째 칸이 '마감'이면 스킵
    - end_dt < 오늘이면 스킵
    - 한 페이지에서 0건이면 즉시 종료
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)
    base_list_url = BASE + LIST_PATH
    results = []
    today = datetime.now(KST).date()

    for page in range(start_page, start_page + max_pages):
        url = set_query(base_list_url, pageIndex=page, searchKey="", searchWord="")
        log.info("GET %s", url)
        r = sess.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        table = soup.select_one("#content > div.boardTypeTbl > table")
        if not table:
            log.warning("리스트 테이블을 못 찾음 (page=%s). 중단.", page)
            break

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else []
        if not rows:
            log.info("더 이상 항목 없음 (page=%s). 종료.", page)
            break

        add_count = 0
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue

            a = tr.select_one("td.alignL > a")
            title = a.get_text(strip=True) if a else tds[1].get_text(strip=True)
            detail_url = urljoin(BASE, a.get("href", "")) if a and a.has_attr("href") else None

            period_text = tds[2].get_text(" ", strip=True)
            sdt, edt = parse_range(period_text)

            status_text = tds[4].get_text(strip=True)

            # 1) 상태가 '마감'이면 스킵
            if "마감" in status_text:
                continue
            # 2) end_dt가 오늘보다 이전이면 스킵
            if edt and edt.date() < today:
                continue

            results.append({
                "title": title,
                "period_text": period_text,
                "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
                "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
                "status": status_text,
                "detail_url": detail_url
            })
            add_count += 1

        log.info("page %d: %d건 수집 (누적 %d)", page, add_count, len(results))

        # ✅ 0건이면 즉시 종료
        if add_count == 0:
            log.info("page %d에서 신규 수집 0건 → 종료.", page)
            break

    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info("저장 완료: %s (총 %d건)", output, len(results))
    return results

if __name__ == "__main__":
    crawl_snuh(
        output=os.getenv("OUTPUT", "seoul.json"),
        start_page=int(os.getenv("START_PAGE", "1")),
        max_pages=int(os.getenv("MAX_PAGES", "50")),
    )
