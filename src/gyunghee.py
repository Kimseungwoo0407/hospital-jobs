# pip install requests beautifulsoup4
import os, re, json, logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = "https://recruit.incruit.com"
START_URL = BASE + "/khmc/job/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("khmc")

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
    예: 
      '2025.10.13 00:00~2025.10.26 23:59'
      '2025.10.13 ~ 2025.10.26'
    """
    if not txt:
        return None, None

    # 점→대시, 불필요 공백 제거
    t = txt.strip().replace(".", "-")

    # '00:00~2025' 같이 붙어있는 것도 매칭
    m = re.search(
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*~\s*"
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)",
        t
    )
    if not m:
        # 매칭 안 되면 단일 날짜로 시도
        dt = parse_dt_kst(t)
        return dt, None

    sdt = parse_dt_kst(m.group(1))
    edt = parse_dt_kst(m.group(2))

    # 끝 시간이 날짜만 있을 때 23:59 보정
    if edt and edt.hour == 0 and edt.minute == 0 and not re.search(r"\d{2}:\d{2}", m.group(2)):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def crawl_khmc(output="khmc.json"):
    """
    - 인크루트 강북삼성병원 채용
    - 모집중인 항목(span.state='모집중')만 수집
    - title/em/url 추출
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)

    r = sess.get(START_URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    ul = soup.select_one("body > div > div.tamplet_container > div.inner-layout > div.list-item-box > ul")
    if not ul:
        log.error("공고 리스트 ul을 찾을 수 없음. 구조 변경됐을 가능성.")
        return []

    results = []
    lis = ul.find_all("li", recursive=False)
    for li in lis:
        state_el = li.select_one("div > span.state")
        state = state_el.get_text(strip=True) if state_el else ""
        if state != "모집중":
            continue

        title_el = li.select_one("div > span.title")
        title = title_el.get_text(strip=True) if title_el else ""

        period_el = li.select_one("div > em")
        period_text = period_el.get_text(strip=True) if period_el else ""
        sdt, edt = parse_range(period_text)

        a_el = li.select_one("div > a")
        detail_url = urljoin(BASE, a_el.get("href", "")) if a_el and a_el.has_attr("href") else None

        results.append({
            "title": title,
            "period_text": period_text,
            "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
            "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
            "status": state,
            "detail_url": detail_url
        })

    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("저장 완료: %s (총 %d건)", output, len(results))
    return results

if __name__ == "__main__":
    crawl_khmc()
