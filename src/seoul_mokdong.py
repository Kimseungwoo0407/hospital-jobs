# pip install requests beautifulsoup4
import os, re, json, logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://seoul.eumc.ac.kr"
LIST_PATH = "/intro/recrut/list.do"
HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("eumc")

def parse_dt_kst(s: str):
    s = s.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_range(txt: str):
    """
    '2025.10.15 ~ 2025.10.22' 또는 '2025-10-15~2025-10-22' 등 처리
    """
    if not txt:
        return None, None
    t = re.sub(r"\s*~\s*", " ~ ", txt.strip().replace(".", "-"))
    m = re.search(r"(\d{4}-\d{2}-\d{2}).*~.*(\d{4}-\d{2}-\d{2})", t)
    if not m:
        dt = parse_dt_kst(t)
        return dt, None
    sdt = parse_dt_kst(m.group(1))
    edt = parse_dt_kst(m.group(2))
    if edt and edt.hour == 0 and edt.minute == 0:
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def crawl_eumc(output="seoul_mokdong.json"):
    sess = requests.Session()
    sess.headers.update(HEADERS)

    url = BASE + LIST_PATH
    log.info("GET %s", url)
    r = sess.get(url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    cards = soup.select("#content > div > ul.card-list > li")
    if not cards:
        log.warning("공고 항목을 찾지 못했습니다.")
        return []

    results = []
    today = datetime.now(KST).date()

    for li in cards:
        a = li.select_one("a")
        if not a:
            continue

        title = a.select_one("div > strong")
        date_div = a.select_one("div > div")

        title_text = title.get_text(strip=True) if title else "제목 없음"
        date_text = date_div.get_text(strip=True) if date_div else ""

        sdt, edt = parse_range(date_text)
        detail_url = urljoin(BASE, a.get("href", ""))

        # 마감된 공고는 스킵
        if edt and edt.date() < today:
            continue

        results.append({
            "title": title_text,
            "period_text": date_text,
            "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
            "end_dt": edt.isoformat(timespec="seconds") if edt else None,
            "detail_url": detail_url,
        })

    with open("./json/seoul_mokdong.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("총 %d건 수집 완료 → %s", len(results), output)
    return results


if __name__ == "__main__":
    crawl_eumc()
