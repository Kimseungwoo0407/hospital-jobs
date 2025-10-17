# -*- coding: utf-8 -*-
# deps: pip install selenium webdriver-manager python-dateutil
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

BASE_URL = "https://www.cmcseoul.or.kr"
LIST_URL_TPL = "https://www.cmcseoul.or.kr/page/board/recruit?p={page}&s=12&q=%7B%7D"
SEOUL = ZoneInfo("Asia/Seoul")

# ---------------- 공통 유틸 ----------------
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

def to_iso(dt):
    return dt.astimezone(SEOUL).isoformat(timespec="minutes") if dt else None

def try_parse_date(s, default_time=None):
    if not s:
        return None
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("/", "-").replace(".", "-")
    s = re.sub(r"(까지|마감)", " ", s)
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
        d_to_start = (start_dt.date() - today).days
        return f"D-{d_to_start}"
    if end_dt:
        if start_dt and start_dt.date() <= today <= end_dt.date():
            return f"D-{d_to_end}"
        if today > end_dt.date():
            return f"D+{abs(d_to_end)}"
        return f"D-{d_to_end}"
    return None

# ---------------- 셀렉터 ----------------
LIST_UL_SEL = "#vue_board_list_content > div.list-type01 > ul"
LI_SEL = f"{LIST_UL_SEL} > li"
STATUS_SEL = "a > div.cont_wrap > div > div > span > em"          # 진행중 / 마감
POSTDATE_SEL = "a > div.info_wrap > em.data"                      # 게시일 (start_dt로)
TITLE_SEL = "a .tit, a strong, a h3"

# ---------------- 파싱 ----------------
def extract_title(li):
    for css in TITLE_SEL.split(","):
        try:
            t = li.find_element(By.CSS_SELECTOR, css.strip()).text.strip()
            if t:
                return t
        except:
            pass
    try:
        raw = li.find_element(By.CSS_SELECTOR, "a").text.strip()
        if raw:
            return raw.splitlines()[0].strip()
    except:
        pass
    return ""

def extract_post_date(li):
    """게시일 em.data -> start_dt로 사용"""
    try:
        txt = li.find_element(By.CSS_SELECTOR, POSTDATE_SEL).text.strip()
        if txt:
            return try_parse_date(txt, default_time=dtime(9, 0))
    except:
        return None
    return None

def extract_end_date(li):
    """본문의 기간 표시(~)를 찾아 마감일로 사용"""
    try:
        node = li.find_element(By.CSS_SELECTOR, "a .cont_wrap")
        lines = [t.strip() for t in node.text.splitlines() if "~" in t]
        if not lines:
            return None
        text = lines[0]
        m = re.search(r"~\s*(\d{4}[./-]\d{1,2}[./-]\d{1,2}(?:\s*\d{1,2}:\d{2})?)", text)
        if not m:
            return None
        return try_parse_date(m.group(1), default_time=dtime(23, 59))
    except:
        return None

def parse_li(li):
    # 상태
    try:
        status = li.find_element(By.CSS_SELECTOR, STATUS_SEL).text.strip()
    except:
        status = ""

    # 링크
    a = li.find_element(By.CSS_SELECTOR, "a")
    href = a.get_attribute("href")
    detail_url = urljoin(BASE_URL, href)

    # 타이틀
    title = extract_title(li)
    # 게시일 (start_dt)
    start_dt = extract_post_date(li)
    # 종료일
    end_dt = extract_end_date(li)

    dday = smart_dday(start_dt, end_dt)

    item = {
        "title": title,
        "start_dt": to_iso(start_dt),
        "end_dt": to_iso(end_dt),
        "dday": dday,
        "status": status,
        "recu_idx": urlparse(detail_url).path.rstrip("/").split("/")[-1] or None,
        "announce_sn": None,
        "detail_url": detail_url
    }
    return item

# ---------------- 크롤링 ----------------
def crawl_cmcseoul_until_closed(output="cmcseoul_jobs.json", only_open=True):
    driver = get_driver(headless=True)
    wait = WebDriverWait(driver, 12)
    results = []
    stop_flag = False
    page = 1

    while not stop_flag:
        url = LIST_URL_TPL.format(page=page)
        driver.get(url)

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, LIST_UL_SEL)))
        except:
            break

        lis = driver.find_elements(By.CSS_SELECTOR, LI_SEL)
        if not lis:
            break

        for li in lis:
            item = parse_li(li)
            if item.get("status") != "진행중":
                stop_flag = True
                break
            if only_open and item.get("status") == "진행중":
                results.append(item)

        if stop_flag:
            break

        page += 1
        time.sleep(0.8)

    driver.quit()

    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {output} (총 {len(results)}건)")

if __name__ == "__main__":
    crawl_cmcseoul_until_closed(output="cmcseoul.json", only_open=True)
