# -*- coding: utf-8 -*-
# deps: pip install selenium webdriver-manager python-dateutil
import json, re, time
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo
from dateutil import parser as dtparser

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://caumc.recruiter.co.kr"
LIST_URL = "https://caumc.recruiter.co.kr/app/jobnotice/list"
SEOUL = ZoneInfo("Asia/Seoul")

# ---------------------------- 드라이버/유틸 ----------------------------
def get_driver(headless=True):
    from selenium.webdriver.chrome.options import Options
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,3000")
    options.add_argument("--user-agent=Mozilla/5.0")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

def set_page_size_20(driver, wait):
    try:
        sel = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#pageSize")))
        Select(sel).select_by_value("20")
        time.sleep(1.0)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#divJobnoticeList > ul > li")))
    except Exception:
        pass

def extract_sn(url):
    q = parse_qs(urlparse(url).query)
    return (q.get("jobnoticeSn") or [""])[0]

def to_iso(dt):
    return dt.astimezone(SEOUL).isoformat(timespec="minutes") if dt else None

# ---------------------------- D-day 계산 ----------------------------
def days_between(a: date, b: date) -> int:
    return (b - a).days

def compute_ddays(start_dt, end_dt):
    """ dday를 start/end 둘 다로 계산해서 리턴 """
    today = datetime.now(SEOUL).date()
    d_to_start = days_between(today, start_dt.date()) if start_dt else None
    d_to_end   = days_between(today, end_dt.date())   if end_dt   else None

    # 스마트 dday: 아직 시작 전이면 start 기준, 진행 중이면 end 기준, 종료면 +경과일
    if start_dt and today < start_dt.date():
        smart = f"D-{d_to_start}"
        phase = "before"
    elif start_dt and end_dt and start_dt.date() <= today <= end_dt.date():
        smart = f"D-{d_to_end}"
        phase = "open"
    elif end_dt and today > end_dt.date():
        smart = f"D+{abs(d_to_end)}"
        phase = "closed"
    else:
        smart = None
        phase = "unknown"

    return {
        "dday": smart,
        "phase": phase,
        "dday_to_start": (f"D-{d_to_start}" if d_to_start is not None and d_to_start >= 0 else
                          (f"D+{abs(d_to_start)}" if d_to_start is not None else None)),
        "dday_to_end": (f"D-{d_to_end}" if d_to_end is not None and d_to_end >= 0 else
                        (f"D+{abs(d_to_end)}" if d_to_end is not None else None)),
    }

# ---------------------------- 날짜 파싱 ----------------------------
def try_parse_date(s, default_time=None):
    s = (s or "").strip()
    s = re.sub(r"[()]", " ", s)  # (월) 같은 요일 제거
    s = re.sub(r"(까지|마감|접수마감|채용시마감|채용시\s*마감)", " ", s)
    s = s.replace("상시채용", "").replace("상시", "")
    s = s.replace("/", "-").replace(".", "-")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    try:
        dt = dtparser.parse(s, dayfirst=False, yearfirst=True, fuzzy=True)
        if dt.tzinfo is None:
            if default_time is not None and dt.hour == 0 and dt.minute == 0 and re.search(r"\d{1,2}:\d{2}", s) is None:
                dt = datetime(dt.year, dt.month, dt.day, default_time.hour, default_time.minute, tzinfo=SEOUL)
            else:
                dt = dt.replace(tzinfo=SEOUL)
        else:
            dt = dt.astimezone(SEOUL)
        return dt
    except Exception:
        return None

def parse_date_span(text):
    """
    예시:
    - '2025.10.10(금) 10:00 ~ 2025.10.16(목) 23:59'
    - '2025.10.01 ~ 2025.10.31 23:59'
    - '2025-10-10 ~ 상시'
    """
    raw = (text or "").strip()
    if not raw:
        return None, None

    # 요일 등 괄호 안 제거
    cleaned = re.sub(r"\([^)]*\)", " ", raw)

    # 상시/채용시 마감
    if re.search(r"(상시|채용시\s*마감)", cleaned):
        m = re.search(r"(\d{4}[./-]\d{1,2}[./-]\d{1,2}(?:\s*\d{1,2}:\d{2})?)", cleaned)
        start = try_parse_date(m.group(1), default_time=dtime(0, 0)) if m else None
        return start, None

    # 일반 범위
    rx = re.compile(
        r"(?P<sdate>\d{4}[./-]\d{1,2}[./-]\d{1,2})(?:\s*(?P<stime>\d{1,2}:\d{2}))?\s*"
        r"[~\-–]\s*"
        r"(?P<edate>\d{4}[./-]\d{1,2}[./-]\d{1,2})(?:\s*(?P<etime>\d{1,2}:\d{2}))?",
        re.UNICODE
    )
    m = rx.search(cleaned)
    if m:
        sdate, stime = m.group("sdate"), m.group("stime")
        edate, etime = m.group("edate"), m.group("etime")
        sdt = try_parse_date(f"{sdate} {stime}" if stime else sdate, default_time=dtime(0, 0))
        edt = try_parse_date(f"{edate} {etime}" if etime else edate, default_time=dtime(23, 59))
        return sdt, edt

    # '... 23:00 까지' 꼬리표
    rx2 = re.compile(
        r"(?P<sdate>\d{4}[./-]\d{1,2}[./-]\d{1,2})\s*[~\-–]\s*"
        r"(?P<edate>\d{4}[./-]\d{1,2}[./-]\d{1,2})(?:\s*(?P<etime>\d{1,2}:\d{2}))?\s*(?:까지)?"
    )
    m2 = rx2.search(cleaned)
    if m2:
        sdate, edate, etime = m2.group("sdate"), m2.group("edate"), m2.group("etime")
        sdt = try_parse_date(sdate, default_time=dtime(0, 0))
        edt = try_parse_date(f"{edate} {etime}" if etime else edate, default_time=dtime(23, 59))
        return sdt, edt

    return None, None

# 날짜 텍스트를 확실하게 고르는 로직 (전용 클래스 우선)
DATE_LIKE = re.compile(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}")

def pick_date_text(content_el):
    # 1) 전용 클래스 우선
    try:
        span = content_el.find_element(By.CSS_SELECTOR, "span.list-bbs-date")
        txt = span.text.strip()
        if DATE_LIKE.search(txt):
            return txt
    except:
        pass
    # 2) 그 외 모든 span 탐색
    try:
        for sp in content_el.find_elements(By.CSS_SELECTOR, "span"):
            t = sp.text.strip()
            if DATE_LIKE.search(t):
                return t
    except:
        pass
    # 3) 안전망
    try:
        for node in content_el.find_elements(By.XPATH, ".//*[self::span or self::p or self::div]"):
            t = node.text.strip()
            if DATE_LIKE.search(t):
                return t
    except:
        pass
    return ""

# ---------------------------- 리스트 파싱 ----------------------------
def parse_list_page(driver, show_only_open=True, warn_on_fail=True):
    lis = driver.find_elements(By.CSS_SELECTOR, "#divJobnoticeList > ul > li")
    rows = []
    for li in lis:
        try:
            status = li.find_element(By.CSS_SELECTOR, "div.list-bbs-status > span").text.strip()
        except:
            status = ""

        if show_only_open and status != "접수중":
            continue

        content = li.find_element(By.CSS_SELECTOR, "div:nth-child(2)")
        a = content.find_element(By.CSS_SELECTOR, "a")
        title = a.text.strip()
        href = a.get_attribute("href")

        span_text = pick_date_text(content)
        sdt, edt = parse_date_span(span_text)
        if warn_on_fail and not (sdt and (edt or "상시" in span_text)):
            print("[WARN] 날짜 파싱 실패 →", span_text or f"(제목: {title})")

        dday_info = compute_ddays(sdt, edt)

        announce_sn = extract_sn(href)
        item = {
            "title": title,
            "start_dt": to_iso(sdt),
            "end_dt": to_iso(edt),
            "dday": dday_info["dday"],              # 스마트 D-day
            "dday_to_start": dday_info["dday_to_start"],
            "dday_to_end": dday_info["dday_to_end"],
            "phase": dday_info["phase"],            # before/open/closed
            "recu_idx": announce_sn,                # 대체키 없음 → announce_sn과 동일 사용
            "announce_sn": announce_sn,
            "detail_url": href,
        }
        rows.append(item)
    return rows

def click_next(driver):
    for xp in [
        "//a[normalize-space(text())='다음']",
        "//button[normalize-space(text())='다음']",
        "//*[contains(@class,'next')]/a | //*[contains(@class,'next')]"
    ]:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_enabled():
                driver.execute_script("arguments[0].click();", el)
                time.sleep(1.2)
                return True
        except:
            pass
    try:
        current = driver.find_element(By.CSS_SELECTOR, ".pagination li.active, .paging li.on, .page li.active")
        sib = current.find_element(By.XPATH, "following-sibling::li[1]/a")
        driver.execute_script("arguments[0].click();", sib)
        time.sleep(1.0)
        return True
    except:
        return False

# ---------------------------- 실행/저장 ----------------------------
def crawl_to_json(output_path="caumc_jobs.json", show_only_open=True, page_limit=10):
    driver = get_driver(headless=True)
    wait = WebDriverWait(driver, 10)
    driver.get(LIST_URL)
    set_page_size_20(driver, wait)

    all_rows, seen = [], set()

    for page in range(page_limit):
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#divJobnoticeList > ul > li")))
        page_rows = parse_list_page(driver, show_only_open=show_only_open, warn_on_fail=True)
        for r in page_rows:
            key = r["announce_sn"]
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(r)

        if page < page_limit - 1 and not click_next(driver):
            break

    driver.quit()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {output_path} (총 {len(all_rows)}건)")

if __name__ == "__main__":
    # 접수중만(True) / 전체(False)
    crawl_to_json(output_path="caumc.json", show_only_open=True, page_limit=10)
