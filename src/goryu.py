# -*- coding: utf-8 -*-
# deps:
#   pip install selenium webdriver-manager python-dateutil
import json, re, time
from urllib.parse import urljoin, urlparse
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from dateutil import parser as dtparser

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://kumc.recruiter.co.kr"
LIST_URL = "https://kumc.recruiter.co.kr/career/job"
SEOUL = ZoneInfo("Asia/Seoul")

# ---------------- Driver ----------------
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

# ---------------- Date / D-day ----------------
def to_iso(dt):
    return dt.astimezone(SEOUL).isoformat(timespec="minutes") if dt else None

def try_parse_date(s, default_time=None):
    if not s: return None
    s = re.sub(r"\([^)]*\)", " ", s)  # (월) 요일 제거
    s = s.replace("/", "-").replace(".", "-")
    s = re.sub(r"(까지|마감|접수마감)", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    try:
        dt = dtparser.parse(s, yearfirst=True, fuzzy=True)
        if dt.tzinfo is None:
            if default_time and not re.search(r"\d{1,2}:\d{2}", s):
                dt = datetime(dt.year, dt.month, dt.day, default_time.hour, default_time.minute, tzinfo=SEOUL)
            else:
                dt = dt.replace(tzinfo=SEOUL)
        else:
            dt = dt.astimezone(SEOUL)
        return dt
    except:
        return None

def smart_dday(start_dt, end_dt):
    today = datetime.now(SEOUL).date()
    if end_dt:
        d_to_end = (end_dt.date() - today).days
    else:
        d_to_end = None
    if start_dt and today < start_dt.date():
        return f"D-{(start_dt.date() - today).days}"
    if end_dt:
        if start_dt and start_dt.date() <= today <= end_dt.date():
            return f"D-{d_to_end}"
        if today > end_dt.date():
            return f"D+{abs(d_to_end)}"
        return f"D-{d_to_end}"
    return None

# ---------------- Selectors ----------------
LIST_UL = ".RecruitList_recruit-list__FlKk4.PC > ul"
LI_SEL  = f"{LIST_UL} > li"
A_SEL   = "a.RecruitList_list-item__PzVZf"
STATUS_SEL = ".RecruitList_submission-status-tag__IXUxc"
TITLE_SEL  = ".RecruitList_title__OqWa3"
DATE_BOX   = ".RecruitList_date__AkCNU"
TAGS_SEL   = ".RecruitList_filtered-list__QSYUA .RecruitList_filtered-item__OglnX p"

# 페이지네이션(숫자)
PAGINATION_LI = ".RecruitViewList_pagination__Img3k .Pagination_middle__fDE1y ol li"

# ---------------- Parse helpers ----------------
def parse_li(li):
    a = li.find_element(By.CSS_SELECTOR, A_SEL)
    href = a.get_attribute("href")
    detail_url = urljoin(BASE_URL, href)

    # 상태
    status = ""
    try:
        status = a.find_element(By.CSS_SELECTOR, STATUS_SEL).text.strip()
    except:
        pass

    # 제목
    title = a.find_element(By.CSS_SELECTOR, TITLE_SEL).text.strip()

    # 날짜(두 줄: 시작/종료)
    start_text = end_text = ""
    try:
        ps = a.find_element(By.CSS_SELECTOR, DATE_BOX).find_elements(By.TAG_NAME, "p")
        if len(ps) >= 1: start_text = ps[0].text.strip()
        if len(ps) >= 2: end_text   = ps[1].text.strip()
    except:
        pass

    # 태그(첫 칸이 병원명일 가능성 큼)
    tags = []
    try:
        for t in a.find_elements(By.CSS_SELECTOR, TAGS_SEL):
            txt = t.text.strip()
            if txt: tags.append(txt)
    except:
        pass

    sdt = try_parse_date(start_text.replace("~", " ").strip(), default_time=dtime(0, 0))
    edt = try_parse_date(end_text, default_time=dtime(23, 59))
    dday = smart_dday(sdt, edt)

    job_id = urlparse(detail_url).path.rstrip("/").split("/")[-1] or None

    return {
        "title": title,
        "start_dt": to_iso(sdt),
        "end_dt": to_iso(edt),
        "dday": dday,
        "status": status,
        "recu_idx": job_id,
        "announce_sn": job_id,
        "detail_url": detail_url,
        "tags": tags,
        "hospital": (tags[0] if tags else None),
    }

# ---------------- Pagination helpers ----------------
def get_total_pages(driver):
    """
    페이지 번호 li들의 텍스트 중 숫자 최대값을 total_pages로 본다.
    (앞/뒤 이동 버튼은 숫자가 아니므로 자동 배제)
    """
    lis = driver.find_elements(By.CSS_SELECTOR, PAGINATION_LI)
    nums = []
    for li in lis:
        try:
            t = li.text.strip()
            if t.isdigit():
                nums.append(int(t))
        except:
            pass
    return max(nums) if nums else 1

def click_page(driver, target_num, wait, wait_css=LIST_UL, timeout=10):
    """
    페이지 번호가 보이는 상태에서, 해당 숫자(li/a 텍스트 == target_num) 클릭.
    클릭 전후 첫 번째 항목의 href가 바뀔 때까지 대기해서 페이지 전환을 보장.
    """
    # 현재 첫 li의 링크 저장
    try:
        old_first = driver.find_element(By.CSS_SELECTOR, f"{LI_SEL}:nth-child(1) {A_SEL}").get_attribute("href")
    except:
        old_first = None

    lis = driver.find_elements(By.CSS_SELECTOR, PAGINATION_LI)
    target_el = None
    for li in lis:
        t = li.text.strip()
        if t == str(target_num):
            # li 안의 a가 있을 수도/없을 수도 있음 → 클릭 가능한 요소 선택
            try:
                target_el = li.find_element(By.CSS_SELECTOR, "a")
            except:
                target_el = li
            break
    if not target_el:
        return False

    driver.execute_script("arguments[0].click();", target_el)

    # 전환 대기
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_css))
        )
        if old_first:
            WebDriverWait(driver, timeout).until(
                lambda d: d.find_element(By.CSS_SELECTOR, f"{LI_SEL}:nth-child(1) {A_SEL}").get_attribute("href") != old_first
            )
    except:
        pass
    time.sleep(0.5)
    return True

# ---------------- Crawl ----------------
def crawl_kumc_paged(output_path="kumc_jobs.json", only_open=True, hospitals=("안암병원","구로병원")):
    driver = get_driver(headless=True)
    wait = WebDriverWait(driver, 12)
    driver.get(LIST_URL)

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, LIST_UL)))

    total_pages = get_total_pages(driver)
    results = []
    stop_flag = False   # ⬅ 추가

    for page_num in range(1, total_pages + 1):
        if page_num > 1:
            ok = click_page(driver, page_num, wait)
            if not ok:
                break
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, LIST_UL)))

        lis = driver.find_elements(By.CSS_SELECTOR, LI_SEL)
        for li in lis:
            try:
                item = parse_li(li)
            except Exception:
                continue

            # ❗ 접수마감 만나면 즉시 종료
            if item.get("status") == "접수마감":
                stop_flag = True
                break

            # 접수중만 수집
            if only_open and item.get("status") != "접수중":
                continue

            # 병원 필터
            hos_ok = False
            for h in hospitals:
                if (item.get("hospital") and h in item["hospital"]) or (h in item["title"]):
                    hos_ok = True
                    break
            if not hos_ok:
                continue

            results.append(item)

        if stop_flag:
            break   # 페이지 루프도 중단

    driver.quit()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {output_path} (총 {len(results)}건)")


# ---------------- Run ----------------
if __name__ == "__main__":
    # 안암/구로만, 접수중만, 숫자 페이지 끝까지 순회
    crawl_kumc_paged(output_path="kumc.json", only_open=True, hospitals=("안암병원","구로병원"))
