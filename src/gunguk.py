# pip install requests beautifulsoup4
import os, re, json, logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://www.kuh.ac.kr"
LIST_URL = BASE + "/m/recruit/apply/noticeList.do"
HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("kuh")

def parse_dt_kst(s: str):
    s = s.strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_range(txt: str):
    """
    예:
      '2025-10-13 15:00 ~ 2025-10-19 23:59'
      공백·줄바꿈은 정규화해서 처리.
    """
    if not txt:
        return None, None
    t = " ".join(txt.split())              # 줄바꿈/여러 공백 정리
    t = t.replace(".", "-")                # 혹시 점 표기 섞여도 대비
    m = re.search(
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*~\s*"
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)", t
    )
    if not m:
        dt = parse_dt_kst(t)
        return dt, None
    sdt, edt = parse_dt_kst(m.group(1)), parse_dt_kst(m.group(2))
    # 끝이 날짜만이면 23:59 보정
    if edt and edt.hour == 0 and edt.minute == 0 and not re.search(r"\d{2}:\d{2}", m.group(2)):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def crawl_kuh(output="kuh.json"):
    """
    - #proceeding > div 를 위에서부터 순회
    - 제목:   a > strong.title
    - 기간:   a > div (텍스트 전체)
    - 상태:   a > strong.color01  → '마감'이면 즉시 중단, 그 전까지 수집
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)

    r = sess.get(LIST_URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    container = soup.select_one("#proceeding")
    if not container:
        log.error("#proceeding 을 못 찾음. 구조가 바뀌었을 가능성.")
        return []

    results = []
    hard_stop = False

    # div들을 문서 순서대로
    for idx, div in enumerate(container.find_all("div", recursive=False), 1):
        a = div.find("a", recursive=False)
        if not a:
            continue

        status_el = a.select_one("strong.color01")
        status = status_el.get_text(strip=True) if status_el else ""
        if "마감" in status:
            log.info("마감 항목 도달(div %d) → 중단.", idx)
            break

        title_el = a.select_one("strong.title")
        title = title_el.get_text(strip=True) if title_el else ""

        period_el = a.find("div", recursive=False)
        period_text = period_el.get_text(" ", strip=True) if period_el else ""
        sdt, edt = parse_range(period_text)

        detail_url = urljoin(BASE, a.get("href", "")) if a and a.has_attr("href") else None

        results.append({
            "title": title,
            "period_text": period_text,
            "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
            "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
            "status_text": status,
            "detail_url": detail_url
        })



    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("저장 완료: %s (총 %d건, hard_stop=%s)", output, len(results), hard_stop)
    return results

if __name__ == "__main__":
    crawl_kuh(output=os.getenv("OUTPUT", "gunguk.json"))
