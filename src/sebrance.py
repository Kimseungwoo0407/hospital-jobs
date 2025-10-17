# pip install selenium beautifulsoup4
import json, os, time, logging, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE = "https://yuhs.recruiter.co.kr"
LIST_URL = BASE + "/app/jobnotice/list"
KST = timezone(timedelta(hours=9))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("yuhs-selenium")

def parse_dt_guess(s: str):
    if not s: return None
    s = s.strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            from datetime import datetime as dt
            return dt.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_date_range(txt: str):
    """
    날짜 문자열 예시:
      '2025.08.20(수) 00:00 ~ 2025.08.26(화) 23:59'
      '2025-08-20 ~ 2025-08-26'
    요일, 괄호, 한글 요일명은 제거 후 파싱
    """
    if not txt:
        return None, None

    # 1. 공백/불필요 문자 정리
    txt = txt.strip()
    # 2. '(월)', '(화)', '(수)', '(목)', '(금)', '(토)', '(일)' 제거
    txt = re.sub(r"\([\w가-힣]+\)", "", txt)
    # 3. '.'을 '-'로 통일
    txt = txt.replace(".", "-")

    # 4. 정규식으로 범위 추출
    m = re.search(
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*[~\-]\s*"
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)",
        txt
    )
    if not m:
        dt = parse_dt_guess(txt)
        return dt, None

    sdt = parse_dt_guess(m.group(1))
    edt = parse_dt_guess(m.group(2))

    # 끝 시간이 날짜만 있으면 23:59 보정
    if edt and edt.hour == 0 and edt.minute == 0 and not re.search(r"\d{2}:\d{2}", m.group(2)):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt


def compute_dday(sdt, edt, dday_txt):
    if dday_txt: return dday_txt.strip()
    today = datetime.now(KST).date()
    if sdt and today < sdt.date():
        return f"D-{(sdt.date() - today).days}"
    if edt:
        d = (edt.date() - today).days
        return f"D-{d}" if d >= 0 else f"D+{abs(d)}"
    return None

def get_driver(headless=True):
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1400,1200")
    # Selenium 4.6+ 는 크롬 자동 관리 지원(별도 드라이버 없이 동작)
    driver = webdriver.Chrome(options=opts)
    return driver

def set_page_size_100(driver):
    """#pageSize 셀렉트를 100으로 바꾼다. 바꾼 뒤 리스트 로딩을 기다린다."""
    try:
        sel = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#pageSize"))
        )
        Select(sel).select_by_value("100")
        # 바뀌면 보통 자동 submit이나 XHR 발생 → 리스트 갱신 대기
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#divJobnoticeList > ul > li"))
        )
        time.sleep(0.5)  # 잔여 렌더링 여유
        log.info("페이지 사이즈를 100으로 설정 완료.")
        return True
    except TimeoutException:
        log.warning("pageSize 셀렉터를 찾지 못했거나 변경 이벤트 미발생.")
        return False

def extract_from_dom(html):
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.select_one("#divJobnoticeList > ul")
    if not ul:
        return [], False
    items, stop = [], False
    lis = ul.find_all("li", recursive=False)
    for li in lis:
        # 위치
        loc_tag = li.select_one("div.list-bbs-type")
        location = (loc_tag.get_text(strip=True) if loc_tag else "").strip()
        if location not in ("신촌", "강남"):
            continue

        # 상태
        status_el = li.select_one("div.list-bbs-status > span")
        status_txt = status_el.get_text(strip=True) if status_el else ""
        if status_txt != "접수중":
            stop = True
            break

        # 날짜, d-day
        date_el = li.select_one("div:nth-child(2) > span.list-bbs-date")
        date_txt = date_el.get_text(strip=True) if date_el else ""
        sdt, edt = parse_date_range(date_txt)

        dday_el = li.select_one("div:nth-child(2) > span.list-bbs-dday")
        dday_txt = dday_el.get_text(strip=True) if dday_el else None
        dday = compute_dday(sdt, edt, dday_txt)

        # 제목/링크
        a = li.select_one("a")
        title = a.get_text(strip=True) if a else ""
        detail_url = urljoin(BASE, a.get("href", "")) if a and a.has_attr("href") else None

        items.append({
            "title": title,
            "location": location,
            "status": status_txt,
            "date_text": date_txt,
            "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
            "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
            "dday": dday,
            "detail_url": detail_url
        })
    return items, stop

def paginate_and_collect(driver, max_pages=5):
    """현재 페이지부터 다음 페이지로 넘어가며 수집. '접수중' 아닌 항목 만나면 즉시 중단."""
    all_items = []
    for p in range(max_pages):
        # 리스트 DOM 대기
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#divJobnoticeList > ul > li"))
            )
        except TimeoutException:
            log.warning("리스트 LI 대기 타임아웃. 중단.")
            break

        html = driver.page_source
        items, stop = extract_from_dom(html)
        all_items.extend(items)
        log.info("현재 페이지에서 %d건 수집 (누적 %d)", len(items), len(all_items))
        if stop:
            log.info("비접수 항목 발견 → 즉시 중단.")
            break

        # 다음 페이지 버튼 찾기
        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, ".pagination a.next, .paginate a.next, a[aria-label='Next']")
        except NoSuchElementException:
            log.info("다음 페이지 없음. 종료.")
            break

        # next가 disabled면 끝
        if "disabled" in next_btn.get_attribute("class").lower():
            log.info("다음 페이지 disabled. 종료.")
            break

        driver.execute_script("arguments[0].click();", next_btn)
        time.sleep(0.7)  # 페이지 전환 대기(사이트에 맞춰 필요시 조절)

    return all_items

def crawl_yuhs(output="yuhs.json", headless=True, max_pages=3):
    driver = get_driver(headless=headless)
    try:
        driver.get(LIST_URL)
        # 페이지 사이즈 100 적용
        set_page_size_100(driver)
        results = paginate_and_collect(driver, max_pages=max_pages)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info("저장 완료: %s (총 %d건)", output, len(results))
        return results
    finally:
        driver.quit()

if __name__ == "__main__":
    # 예) LOG_LEVEL=DEBUG python yuhs_selenium.py
    crawl_yuhs(
        output=os.getenv("OUTPUT", "sebran.json"),
        headless=(os.getenv("HEADLESS", "1") == "1"),
        max_pages=int(os.getenv("MAX_PAGES", "3")),
    )
