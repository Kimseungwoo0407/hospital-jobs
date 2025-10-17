# pip install selenium beautifulsoup4
import os, re, json, time, logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ==========================
# 기본 설정
# ==========================

BASE = "https://recruit.kbsmc.co.kr"
LIST_URL = BASE + "/jsp/recruit/recruitList.jsp"
KST = timezone(timedelta(hours=9))

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("kbsmc")

# ==========================
# 유틸 함수
# ==========================

def norm_txt(s: str) -> str:
    """공백/개행 제거 및 정규화"""
    return re.sub(r"\s+", "", s or "").strip()

def parse_dt_kst(s: str):
    """문자열을 KST datetime으로 변환"""
    s = s.strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_range(txt: str):
    """기간 텍스트 예: '2025.10.10 ~ 2025.10.19'"""
    if not txt:
        return None, None
    t = txt.strip().replace(".", "-")
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*[~\-]\s*(\d{4}-\d{2}-\d{2})", t)
    if not m:
        dt = parse_dt_kst(t)
        return dt, None
    sdt, edt = parse_dt_kst(m.group(1)), parse_dt_kst(m.group(2))
    if edt and (edt.hour, edt.minute) == (0, 0):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def get_driver(headless=True):
    """Selenium Chrome 드라이버 생성"""
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1400,1200")
    return webdriver.Chrome(options=opts)

# ==========================
# 페이지 단위 추출
# ==========================

def extract_page_items(driver):
    """현재 페이지 HTML 파싱 (디버깅 로그 포함)"""
    soup = BeautifulSoup(driver.page_source, "html.parser")
    ul = soup.select_one("div.sub_0101_list.on > ul")
    if not ul:
        log.warning("리스트 ul을 못 찾음.")
        return [], False

    a_tags = ul.find_all("a", recursive=False)
    log.debug("현재 페이지에서 a태그 %d개 발견", len(a_tags))

    results = []
    stop = False

    for idx, a_tag in enumerate(a_tags, 1):
        li = a_tag.find("li")
        if not li:
            log.debug("a[%d]: li 없음, 스킵", idx)
            continue

        # 상태 텍스트 (예: NEW, 마감 등)
        status_el = li.select_one("div.tit_flex > div.flex2 > p")
        status_text = status_el.get_text(strip=True) if status_el else ""
        log.debug("a[%d]: 상태='%s'", idx, status_text)
        if "마감" in status_text:
            log.info("a[%d]: '마감' 발견 → stop 플래그 설정", idx)
            stop = True
            break

        # 직종
        job_type_el = li.select_one("div.tit_flex > div.flex1 > div > p")
        job_type_raw = job_type_el.get_text(strip=True) if job_type_el else ""
        job_type_norm = norm_txt(job_type_raw)  # 공백 제거
        if job_type_norm != "의료기사직":
            log.debug("a[%d]: 의료기사직 아님 → 스킵 (raw='%s')", idx, job_type_raw)
            continue

        # 제목
        title_el = li.select_one("p.txt18.mt40.mb30")
        title = title_el.get_text(strip=True) if title_el else ""

        # 기간
        date_el = li.select_one("div.bt_txt > div.flex3 > p")
        period_text = date_el.get_text(strip=True) if date_el else ""
        sdt, edt = parse_range(period_text)

        # 상세 URL
        detail_url = urljoin(BASE, a_tag.get("href", ""))

        log.debug("a[%d]: title='%s', 기간='%s'", idx, title, period_text)

        results.append({
            "title": title,
            "job_type": job_type_raw,
            "period_text": period_text,
            "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
            "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
            "status_text": status_text,
            "detail_url": detail_url
        })

    log.debug("이 페이지에서 실제 수집된 항목: %d건", len(results))
    return results, stop

# ==========================
# 전체 크롤링 루프
# ==========================

def crawl_kbsmc(output="kbsmc.json", headless=True, max_pages=20):
    driver = get_driver(headless=headless)
    results = []
    try:
        driver.get(LIST_URL)
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.sub_0101_list.on > ul > a")))

        for page_idx in range(1, max_pages + 1):
            log.info("===== PAGE %d =====", page_idx)
            items, stop_page = extract_page_items(driver)
            results.extend(items)
            log.info("page %d: %d건 수집 (누적 %d)", page_idx, len(items), len(results))

            if stop_page:
                log.info("이 페이지에서 '마감' 항목 발견 → 전체 중단.")
                break

            # 다음 페이지 버튼 클릭
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "#pageZone > a.pNext")
            except NoSuchElementException:
                log.info("다음 버튼 없음 → 종료.")
                break

            driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(1.0)

            try:
                wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.sub_0101_list.on > ul > a")))
            except TimeoutException:
                log.warning("리스트 로드 대기 초과 → 중단.")
                break

        # JSON 저장
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info("저장 완료: %s (총 %d건)", output, len(results))
        return results

    finally:
        driver.quit()

# ==========================
# 실행
# ==========================

if __name__ == "__main__":
    crawl_kbsmc(
        output=os.getenv("OUTPUT", "kbsmc.json"),
        headless=(os.getenv("HEADLESS", "1") == "1"),
        max_pages=int(os.getenv("MAX_PAGES", "20"))
    )
