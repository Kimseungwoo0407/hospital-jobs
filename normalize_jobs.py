# -*- coding: utf-8 -*-
import os, re, sys, json, glob
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
KEEP_KEYS = {"title", "start_dt", "end_dt", "dday", "detail_url"}

def parse_dt_kst(s: str):
    """다양한 포맷을 KST aware datetime으로 파싱"""
    if not s or not isinstance(s, str):
        return None
    t = s.strip().replace("/", "-").replace(".", "-")
    # "+09:00" 또는 "+0900" 모두 허용
    t = re.sub(r"(\+\d{2})(\d{2})$", r"\1:\2", t)  # +0900 -> +09:00
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M%z",
        "%Y-%m-%d %H:%M:%S",   "%Y-%m-%d %H:%M", "%Y-%m-%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(t, fmt)
            if dt.tzinfo is None:  # naive면 KST 부여
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST)
        except ValueError:
            continue
    return None

def parse_range(text: str):
    """기간 문자열에서 (start, end) 추출. 시:분 없으면 end는 23:59 보정."""
    if not text:
        return None, None
    norm = text.strip().replace(".", "-").replace("/", "-")
    m = re.search(
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*[~\-]\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)",
        norm
    )
    if not m:
        sdt = parse_dt_kst(norm)
        return sdt, None
    s_raw, e_raw = m.group(1), m.group(2)
    sdt = parse_dt_kst(s_raw)
    edt = parse_dt_kst(e_raw)
    if edt and not re.search(r"\d{2}:\d{2}", e_raw):
        edt = edt.replace(hour=23, minute=59)
    return sdt, edt

def compute_dday(sdt, edt):
    today = datetime.now(KST).date()
    if sdt and today < sdt.date():
        return f"D-{(sdt.date() - today).days}"
    if edt:
        d = (edt.date() - today).days
        return f"D-{d}" if d >= 0 else f"D+{abs(d)}"
    return None

def normalize_record(rec: dict):
    # 1) 기본 키 매핑
    title = rec.get("title") or rec.get("subject") or rec.get("name")

    # 2) start/end 직접 또는 period_text 등으로 보완
    sdt = parse_dt_kst(rec.get("start_dt")) if rec.get("start_dt") else None
    edt = parse_dt_kst(rec.get("end_dt")) if rec.get("end_dt") else None

    period = rec.get("period_text") or rec.get("date_text") or rec.get("period") or rec.get("date")
    if (sdt is None or edt is None) and period:
        ps, pe = parse_range(period)
        sdt = sdt or ps
        edt = edt or pe

    s_iso = sdt.isoformat(timespec="seconds") if sdt else None
    e_iso = edt.isoformat(timespec="seconds") if edt else None

    # 3) dday 우선순위: rec의 dday(str 형태 D-숫자) → 계산
    dday = rec.get("dday")
    if isinstance(dday, str) and not re.match(r"^D[+-]?\d+$|^오늘$", dday):
        dday = None
    if dday == "오늘":
        dday = "D-0"
    if dday is None:
        dday = compute_dday(sdt, edt)

    # 4) detail_url 후보
    detail_url = rec.get("detail_url") or rec.get("url") or rec.get("link")

    return {
        "title": title,
        "start_dt": s_iso,
        "end_dt": e_iso,
        "dday": dday,
        "detail_url": detail_url
    }

def normalize_file(in_path, out_path=None):
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"⚠️ 리스트 JSON이 아님: {in_path}")
        return

    norm = [normalize_record(r) for r in data]
    # 출력 경로
    if out_path is None:
        base = os.path.basename(in_path).rsplit(".", 1)[0]
        out_dir = r"C:\Users\LEGION\Desktop\hospital\hospital-jobs\normalized"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{base}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=2)

    print(f"OK: {os.path.basename(in_path)} → {os.path.relpath(out_path)} ({len(norm)}건)")

def expand_targets(args):
    targets = []
    for a in args:
        p = os.path.abspath(a)
        if os.path.isdir(p):
            targets.extend(sorted(glob.glob(os.path.join(p, "*.json"))))
        elif os.path.isfile(p):
            targets.append(p)
        else:
            print(f"무시: {a}")
    return targets

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python normalize_jobs.py <json파일 또는 폴더> [...]")
        sys.exit(1)
    files = expand_targets(sys.argv[1:])
    if not files:
        print("처리할 JSON이 없습니다.")
        sys.exit(0)
    for fp in files:
        normalize_file(fp)
