# pip install requests beautifulsoup4
import re, json, requests, logging, os, sys, traceback
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta

BASE = "https://mokdong.eumc.ac.kr"
LIST_TPL = BASE + "/intro/recrut/list.do?pageIndex={page}&bid_status=I&searchWord="
HEADERS = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))

# ── logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("eumc_mokdong")

def snapshot(html: str, page: int, tag: str):
    path = f"debug_page{page}_{tag}.html"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        log.debug("HTML 스냅샷 저장: %s", path)
    except Exception:
        log.warning("스냅샷 저장 실패: %s", path)

# ── utils ─────────────────────────────────────────────────────────────────────
def parse_dt(s: str):
    s = s.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None

def parse_range(line: str):
    # "2025-10-14 00:00:00 ~ 2025-10-20 23:59:00"
    m = re.search(
        r"(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*~\s*"
        r"(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)", line
    )
    if not m:
        return None, None
    sdt = parse_dt(m.group(1))
    edt = parse_dt(m.group(2))
    # 끝 시간이 날짜만이었다면 23:59 보정
    if edt and edt.hour == 0 and edt.minute == 0 and not re.search(r"\d{2}:\d{2}", m.group(2)):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def compute_dday(start_dt, end_dt):
    today = datetime.now(KST).date()
    if start_dt and today < start_dt.date():
        return f"D-{(start_dt.date() - today).days}"
    if end_dt:
        d = (end_dt.date() - today).days
        return f"D-{d}" if d >= 0 else f"D+{abs(d)}"
    return None

def extract_item(li, page, idx):
    a = li.select_one("a")
    if not a:
        log.debug("[page %s][li %s] <a> 없음", page, idx)
        return None
    href = urljoin(BASE, a.get("href", ""))
    raw_text = a.get_text("\n")
    lines = [t.strip() for t in raw_text.splitlines() if t.strip()]
    date_line = next((x for x in lines if "~" in x), "")
    dday_line = next((x for x in lines if x.startswith(("D-", "D+"))), None)
    title = next((x for x in lines if x not in (date_line, dday_line)), "")

    if not title:
        log.debug("[page %s][li %s] 제목 파싱 실패. lines=%r", page, idx, lines)

    sdt, edt = parse_range(date_line) if date_line else (None, None)
    item = {
        "title": title or "",
        "start_dt": sdt.isoformat(timespec="seconds") if sdt else None,
        "end_dt":   edt.isoformat(timespec="seconds") if edt else None,
        "dday": compute_dday(sdt, edt),
        "detail_url": href,
        "raw_lines": lines,  # 디버깅용
    }
    log.debug("[page %s][li %s] item=%r", page, idx, item)
    return item

# ── crawler ───────────────────────────────────────────────────────────────────
def crawl(output="eumc_mokdong.json", start_page=1, max_pages=200, save_html=False):
    page = start_page
    results = []

    session = requests.Session()
    session.headers.update(HEADERS)

    while page < start_page + max_pages:
        url = LIST_TPL.format(page=page)
        log.info("요청: %s", url)
        try:
            r = session.get(url, timeout=15)
            log.debug("HTTP %s %s bytes", r.status_code, len(r.text))
            r.raise_for_status()
        except Exception as e:
            log.error("요청 실패(page=%s): %s", page, e)
            # 네트워크 레벨에서 막히면 즉시 중단이 맞다
            break

        html = r.text
        if save_html:
            snapshot(html, page, "list")

        soup = BeautifulSoup(html, "html.parser")
        ul = soup.select_one("#content > div > ul.card-list")
        if not ul:
            log.warning("리스트 UL 선택자 불일치(page=%s). selector 갱신 필요", page)
            if save_html:
                snapshot(html, page, "no_ul")
            # 더 진행해봐야 의미 없음 → 중단
            break

        # 직계 li만
        lis = ul.find_all("li", recursive=False)
        log.info("page=%s li개수=%s", page, len(lis))

        if not lis:
            # 더 이상 게시글이 없는 정상 종료 케이스로 간주
            log.info("더 이상 항목 없음. 종료.")
            break

        for i, li in enumerate(lis, 1):
            try:
                item = extract_item(li, page, i)
                if item:
                    results.append(item)
                else:
                    log.debug("[page %s][li %s] item None", page, i)
            except Exception:
                log.error("[page %s][li %s] 파싱 예외:\n%s", page, i, traceback.format_exc())
                # 문제가 되는 li HTML도 떨궈둔다
                if save_html:
                    try:
                        snapshot(li.prettify(), page, f"li{i:02d}_error")
                    except Exception:
                        pass

        page += 1

    try:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info("저장 완료: %s (총 %d건)", output, len(results))
    except Exception as e:
        log.error("파일 저장 실패: %s", e)

if __name__ == "__main__":
    # 환경변수로 제어:
    #   LOG_LEVEL=DEBUG           → 디테일 로그
    #   SAVE_HTML=1               → HTML 스냅샷 저장
    save_html_flag = os.getenv("SAVE_HTML", "0") == "1"
    # 빠른 재현을 위해 기본 페이지/횟수도 축소 가능
    start = int(os.getenv("START_PAGE", "1"))
    pages = int(os.getenv("MAX_PAGES", "5"))

    crawl(
        output=os.getenv("OUTPUT", "mokdong.json"),
        start_page=start,
        max_pages=pages,
        save_html=save_html_flag,
    )
