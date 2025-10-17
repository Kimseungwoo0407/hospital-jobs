import re
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://recruit.amc.seoul.kr/recruit/career/list.do"
DETAIL_URL_TMPL = "https://recruit.amc.seoul.kr/recruit/career/view.do?recuIdx={recu_idx}&announceSn={announce_sn}"

DATE_RANGE_RE = re.compile(
    r"(\d{4}\.\d{2}\.\d{2})\([^)]+\)\s+(\d{2}:\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})\([^)]+\)\s+(\d{2}:\d{2})"
)
FNDETAIL_RE = re.compile(r"fnDetail\('(\d+)'\s*,\s*'(\d+)'\)")
KST = ZoneInfo("Asia/Seoul")


def parse_datetime_kst(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y.%m.%d %H:%M")
    return dt.replace(tzinfo=KST)


def fetch_page_html(page_index: int) -> str:
    params = {
        "seq": "",
        "scheduleno": "",
        "pageIndex": page_index,
        "codeFirst": "",
        "codeTwo": "",
        "codeThree": "",
        "searchKeyword": "",
    }
    url = f"{BASE_URL}?{urlencode(params)}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.text


def parse_list_items(html: str, now_kst: datetime):
    soup = BeautifulSoup(html, "html.parser")
    lis = soup.select("ul.dayListBox > li")
    open_items = []
    total_items = 0

    for li in lis:
        a = li.select_one(".dayListTitle a")
        if not a:
            continue
        total_items += 1

        title_span = a.select_one("span")
        title = title_span.get_text(strip=True) if title_span else a.get_text(strip=True)

        m = FNDETAIL_RE.search(a.get("onclick", ""))
        recu_idx, announce_sn = (None, None)
        if m:
            recu_idx, announce_sn = m.group(1), m.group(2)

        period_span = li.select_one(".dayListTitle2 span")
        period_text = period_span.get_text(" ", strip=True) if period_span else ""

        dday_span = li.select_one(".dayListBoxRight span")
        dday = dday_span.get_text(strip=True) if dday_span else ""

        m2 = DATE_RANGE_RE.search(period_text)
        if not m2:
            # 기간 파싱 실패 시 스킵
            continue

        s_date, s_time, e_date, e_time = m2.groups()
        start_dt = parse_datetime_kst(s_date, s_time)
        end_dt = parse_datetime_kst(e_date, e_time)

        # 마감 제외
        if now_kst > end_dt:
            continue

        detail_url = (
            DETAIL_URL_TMPL.format(recu_idx=recu_idx, announce_sn=announce_sn)
            if (recu_idx and announce_sn)
            else None
        )

        open_items.append(
            {
                "title": title,
                "start_dt": start_dt.isoformat(),
                "end_dt": end_dt.isoformat(),
                "dday": dday,
                "recu_idx": recu_idx,
                "announce_sn": announce_sn,
                "detail_url": detail_url,
            }
        )

    return open_items, total_items


def crawl_until_closed(max_pages: int = 100, delay_sec: float = 0.6):
    """
    pageIndex=1부터 시작해서 페이지마다 열린 공고만 수집.
    어떤 페이지에서든 '열린 공고가 0개'이면 더 이상 진행하지 않고 종료.
    - max_pages: 안전상한
    - delay_sec: 예의상 서버 부하 완화
    """
    now = datetime.now(KST)
    all_results = []
    page = 1

    while page <= max_pages:
        html = fetch_page_html(page)
        open_items, total_items = parse_list_items(html, now_kst=now)

        # 페이지에 항목이 전혀 없으면 종료(리스트 끝)
        if total_items == 0:
            break

        # 열린 공고가 하나도 없으면 종료(뒤는 더 오래돼서 보통 전부 마감)
        if len(open_items) == 0:
            break

        all_results.extend(open_items)

        page += 1
        if delay_sec:
            time.sleep(delay_sec)

    # 종료일 가까운 순으로 정렬
    all_results.sort(key=lambda x: x["end_dt"])
    return all_results


if __name__ == "__main__":
    data = crawl_until_closed(max_pages=100, delay_sec=0.5)

    # JSON 저장 (파일명에 날짜 포함)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    filename = f"amc.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
