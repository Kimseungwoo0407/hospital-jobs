# -*- coding: utf-8 -*-
# deps:
#   pip install selenium webdriver-manager python-dateutil
import json, re, time
from urllib.parse import urljoin, urlparse
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo
from dateutil import parser as dtparser

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://hyumc.recruiter.co.kr"
LIST_URL = "https://hyumc.recruiter.co.kr/career/home"
SEOUL = ZoneInfo("Asia/Seoul")

# ---------------------------- Driver ----------------------------
def get_driver(headless=True):
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1366,3000")
    opts.add_argument("--user-agent=Mozilla/5.0")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

# ---------------------------- Date utils ----------------------------
def to_iso(dt):
    return dt.astimezone(SEOUL).isoformat(timespec="minutes") if dt else None

def days_between(a: date, b: date) -> int:
    return (b - a).days

def compute_ddays(start_dt, end_dt):
    today = datetime.now(SEOUL).date()
    d_to_start = days_between(today, start_dt.date()) if start_dt else None
    d_to_end   = days_between(today, end_dt.date())   if end_dt   else None

    if start_dt and today < start_dt.date():
        smart = f"D-{d_to_start}"
        phase = "before"   # 접수전
    elif start_dt and end_dt and start_dt.date() <= today <= end_dt.date():
        smart = f"D-{d_to_end}"
        phase = "open"     # 접수중
    elif end_dt and today > end_dt.date():
        smart = f"D+{abs(d_to_end)}"
        phase = "closed"   # 마감
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

def try_parse_date(s, default_time=None):
    """
    '2025.10.15 ~', '2025.10.28 23:59', '2025-10-28(화) 23:59' 등 폭넓게 처리
    """
    s = (s or "").strip()
    # 요일/괄호류 제거
    s = re.sub(r"\([^)]*\)", " ", s)
    # 틱한 꼬리표 정리
    s = s.replace("~", " ").replace("–", "-").replace("~", " ")
    s = re.sub(r"(까지|마감|접수마감)", " ", s)
    # 구분자 통일
    s = s.replace("/", "-").replace(".", "-")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    try:
        dt = dtparser.parse(s, dayfirst=False, yearfirst=True, fuzzy=True)
        if dt.tzinfo is None:
            # 시간이 없으면 기본시각 보정
            if default_time is not None and re.search(r"\d{1,2}:\d{2}", s) is None:
                dt = datetime(dt.year, dt.month, dt.day, default_time.hour, default_time.minute, tzinfo=SEOUL)
            else:
                dt = dt.replace(tzinfo=SEOUL)
        else:
            dt = dt.astimezone(SEOUL)
        return dt
    except Exception:
        return None

# ---------------------------- DOM parsing ----------------------------
def wait_list_ul(driver, wait):
    """
    네가 준 컨테이너:
    .RecruitList_recruit-list__FlKk4.PC > ul
    block-id는 매번 바뀔 수 있으니 고정 클래스 기준으로 잡는다.
    """
    sel = ".RecruitList_recruit-list__FlKk4.PC > ul"
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
    return driver.find_element(By.CSS_SELECTOR, sel)

def try_click_more(driver):
    """
    더보기(있으면) 클릭해서 추가 로드. 없으면 False.
    """
    candidates = [
        "//button[contains(., '더보기')]",
        "//a[contains(., '더보기')]",
        "//*[contains(@class,'more') and (self::button or self::a)]",
    ]
    for xp in candidates:
        try:
            el = driver.find_element(By.XPATH, xp)
            if el.is_displayed() and el.is_enabled():
                driver.execute_script("arguments[0].click();", el)
                time.sleep(1.0)
                return True
        except Exception:
            pass
    return False

def parse_li(li):
    """
    li > a.RecruitList_list-item__... 내부에서 필드 추출
    """
    a = li.find_element(By.CSS_SELECTOR, "a.RecruitList_list-item__PzVZf")
    href = a.get_attribute("href")  # 상대경로일 수 있음
    detail_url = urljoin(BASE_URL, href)

    # 상태
    status = ""
    try:
        status_el = a.find_element(By.CSS_SELECTOR, ".RecruitList_submission-status-tag__IXUxc")
        status = status_el.text.strip()
    except:
        pass

    # 제목
    title = a.find_element(By.CSS_SELECTOR, ".RecruitList_title__OqWa3").text.strip()

    # 날짜 영역 (보통 두 개의 <p>)
    start_text = end_text = ""
    try:
        date_box = a.find_element(By.CSS_SELECTOR, ".RecruitList_date__AkCNU")
        ps = date_box.find_elements(By.TAG_NAME, "p")
        if len(ps) >= 1:
            start_text = ps[0].text.strip()  # 예: "2025.10.15 ~"
        if len(ps) >= 2:
            end_text = ps[1].text.strip()    # 예: "2025.10.28 23:59"
    except:
        pass

    # 태그(고용형태/구분/경력 등)
    tags = []
    try:
        for t in a.find_elements(By.CSS_SELECTOR, ".RecruitList_filtered-list__QSYUA .RecruitList_filtered-item__OglnX p"):
            txt = t.text.strip()
            if txt:
                tags.append(txt)
    except:
        pass

    # D-day가 페이지에 있긴 하지만 우리는 직접 계산할 거라 참고만
    # dday_text = ""
    # try:
    #     dday_text = a.find_element(By.CSS_SELECTOR, ".RecruitList_dday__sT3zv").text.strip()
    # except:
    #     pass

    # 시작/끝 파싱
    # start_text에 남아 있는 "~" 제거
    start_dt = try_parse_date(start_text.replace("~", " ").strip(), default_time=dtime(0, 0))
    end_dt   = try_parse_date(end_text, default_time=dtime(23, 59))

    # id 추출 (마지막 path segment)
    parsed = urlparse(detail_url)
    job_id = parsed.path.rstrip("/").split("/")[-1] if parsed.path else None

    # D-day 계산(스마트)
    dday_info = compute_ddays(start_dt, end_dt)

    item = {
        "title": title,
        "start_dt": to_iso(start_dt),
        "end_dt": to_iso(end_dt),
        "dday": dday_info["dday"],               # 스마트 D-day
        "dday_to_start": dday_info["dday_to_start"],
        "dday_to_end": dday_info["dday_to_end"],
        "phase": dday_info["phase"],             # before/open/closed
        "status": status,                        # 페이지 표기 상태(접수중 등)
        "recu_idx": job_id,                      # 네 포맷에 맞춰 recu_idx로 저장
        "announce_sn": job_id,                   # 별도 키가 없으니 동일 매핑
        "detail_url": detail_url,
        "tags": tags,
    }
    return item

# ---------------------------- Crawl ----------------------------
def crawl_hyumc(output_path="hyumc.json", show_only_open=True, click_more_times=0):
    driver = get_driver(headless=True)
    wait = WebDriverWait(driver, 12)
    driver.get(LIST_URL)

    # 리스트 컨테이너 대기
    ul = wait_list_ul(driver, wait)

    # 옵션: 더보기 연타 (무한스크롤/더보기 있으면)
    for _ in range(click_more_times):
        if not try_click_more(driver):
            break
        # 새로운 li 로드 대기(간단히 sleep)
        time.sleep(0.8)

    lis = driver.find_elements(By.CSS_SELECTOR, ".RecruitList_recruit-list__FlKk4.PC > ul > li")
    results = []
    for li in lis:
        try:
            item = parse_li(li)
            if show_only_open and item.get("status") != "접수중":
                continue
            results.append(item)
        except Exception as e:
            # 문제 있으면 넘어가고 계속
            # print("ERR:", e)
            continue

    driver.quit()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {output_path} (총 {len(results)}건)")

# ---------------------------- Run ----------------------------
if __name__ == "__main__":
    # show_only_open=True: '접수중'만, False: 전체
    # click_more_times: '더보기'가 있으면 몇 번 누를지 지정 (없으면 0)
    crawl_hyumc(output_path="hyumc.json", show_only_open=True, click_more_times=0)
