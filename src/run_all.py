import os
import subprocess
import shutil

# 현재 파일이 위치한 폴더 = src
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
# 프로젝트 루트 = src 상위
ROOT_DIR = os.path.dirname(SRC_DIR)
OUT_DIR = os.path.join(ROOT_DIR, "json")
os.makedirs(OUT_DIR, exist_ok=True)

JOBS = [
    ("강북삼성병원", "gangbuk.py", "kbsmc.json"),
    ("고려대학교의료원", "goryu.py", "goryu.json"),
    ("건국대학교병원", "gunguk.py", "gunguk.json"),
    ("경희의료원", "gyunghee.py", "gyunghee.json"),
    ("한양대학교병원", "hanyang.py", "hanyang.json"),
    ("중앙대학교병원", "jungang.py", "jungang.json"),
    ("이대목동병원", "mokdong.py", "mokdong.json"),
    ("삼성서울병원", "samsung.py", "samsung.json"),
    ("세브란스병원", "sebrance.py", "sebrance.json"),
    ("서울대학교병원", "seoul.py", "seoul.json"),
    ("서울아산병원", "seoul_asan.py", "amc.json"),
    ("가톨릭대학교 서울성모병원", "sungmo.py", "cmcseoul.json"),
    ("이대서울병원", "seoul_mokdong.py", "seoul_mokdong.json"),
    ("분당서울병원", "bundang.py", "snubh.json")
]

def safe_move(src_path, dst_path):
    if os.path.exists(src_path):
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        if os.path.exists(dst_path):
            os.remove(dst_path)
        shutil.move(src_path, dst_path)

def run_one(name, script, final_filename):
    print(f"\n=== [{name}] 실행 ===")

    src_script = os.path.join(SRC_DIR, script)
    out_target = os.path.join(OUT_DIR, final_filename)

    if not os.path.exists(src_script):
        print(f"❌ 스크립트 없음: {os.path.relpath(src_script, ROOT_DIR)}")
        return

    env = os.environ.copy()
    env["OUTPUT"] = out_target
    env.setdefault("HEADLESS", "1")
    env.setdefault("LOG_LEVEL", "INFO")

    # src 폴더를 작업 디렉터리(cwd)로 고정
    result = subprocess.run(
        ["python", src_script],
        cwd=SRC_DIR,
        env=env,
        capture_output=True,
        text=True,
        shell=False
    )

    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())

    if result.returncode != 0:
        print(f"❌ [{name}] 실패 (returncode={result.returncode})")
        return

    # 기대 경로에 생성됐으면 OK
    if os.path.exists(out_target):
        print(f"✅ [{name}] 완료 → {os.path.relpath(out_target, ROOT_DIR)}")
        return

    # 스크립트가 OUTPUT 무시했을 가능성 대비: src/나 루트에 기본 파일명이 생겼는지 확인 후 이동
    fallback_candidates = [
        os.path.join(SRC_DIR, final_filename),
        os.path.join(ROOT_DIR, final_filename),
    ]
    for cand in fallback_candidates:
        if os.path.exists(cand):
            safe_move(cand, out_target)
            print(f"🛈 [{name}] OUTPUT 미준수 → 강제 이동: {os.path.relpath(out_target, ROOT_DIR)}")
            return

    print(f"⚠️ [{name}] 실행 성공했는데 결과 파일을 못 찾음: 기대 경로 {os.path.relpath(out_target, ROOT_DIR)}")

def sweep_src_json_to_out():
    """마지막 안전장치: src에 남아있는 모든 .json을 json/으로 이동(덮어쓰기)."""
    moved = 0
    for fname in os.listdir(SRC_DIR):
        if fname.lower().endswith(".json"):
            src_path = os.path.join(SRC_DIR, fname)
            dst_path = os.path.join(OUT_DIR, fname)
            safe_move(src_path, dst_path)
            print(f"🧹 stray json 이동: {os.path.relpath(dst_path, ROOT_DIR)}")
            moved += 1
    if moved == 0:
        print("🧹 stray json 없음")

if __name__ == "__main__":
    print("🏥 병원별 크롤링 일괄 실행 시작")
    for name, script, output in JOBS:
        run_one(name, script, output)

    # ✅ 마지막에 src에 남은 json 전부 json/로 이동
    sweep_src_json_to_out()

    print("\n🎯 전체 완료 — 결과는 ./json 폴더 확인")
