from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import subprocess
import os
import json
from datetime import datetime
import threading

app = Flask(__name__)
CORS(app)  # CORS 허용

# 🔹 상태 관리
status = {
    'running': False,
    'last_update': None,
    'progress': '',
    'error': None
}

# 🔹 마지막 업데이트 시간 파일
TIMESTAMP_FILE = 'last_update.json'


def load_last_update():
    """마지막 업데이트 시간 불러오기"""
    try:
        if os.path.exists(TIMESTAMP_FILE):
            with open(TIMESTAMP_FILE, 'r') as f:
                data = json.load(f)
                return data.get('last_update')
    except Exception:
        pass
    return None


def save_last_update():
    """마지막 업데이트 시간 저장"""
    with open(TIMESTAMP_FILE, 'w') as f:
        json.dump({'last_update': datetime.now().isoformat()}, f)


# 초기화 시 마지막 업데이트 불러오기
status['last_update'] = load_last_update()


def run_crawler():
    """크롤링 + 정규화 실행"""
    global status
    status['running'] = True
    status['progress'] = '크롤링 시작...'
    status['error'] = None

    try:
        # 1. 크롤링 실행
        status['progress'] = '📡 병원 데이터 크롤링 중...'
        result1 = subprocess.run(
            ['python3', 'src/run_all.py'],
            capture_output=True,
            text=True,
            timeout=600  # 10분 타임아웃
        )

        if result1.returncode != 0:
            raise Exception(f"크롤링 실패: {result1.stderr}")

        # 2. 정규화 실행
        status['progress'] = '🔄 데이터 정규화 중...'
        result2 = subprocess.run(
            ['python3', 'normalize_jobs.py', './json'],
            capture_output=True,
            text=True,
            timeout=300  # 5분 타임아웃
        )

        if result2.returncode != 0:
            raise Exception(f"정규화 실패: {result2.stderr}")

        # 3. 완료
        status['progress'] = '✅ 업데이트 완료!'
        status['last_update'] = datetime.now().isoformat()
        save_last_update()

    except subprocess.TimeoutExpired:
        status['error'] = '⏱️ 시간 초과: 스크립트 실행이 너무 오래 걸립니다.'
    except Exception as e:
        status['error'] = f'❌ 에러: {str(e)}'
    finally:
        status['running'] = False


# 🔹 API 엔드포인트

@app.route('/api/status')
def get_status():
    """현재 상태 반환"""
    return jsonify(status)


@app.route('/api/update', methods=['POST'])
def trigger_update():
    """크롤링 시작"""
    if status['running']:
        return jsonify({'error': '이미 실행 중입니다.'}), 400

    # 백그라운드에서 실행
    thread = threading.Thread(target=run_crawler)
    thread.daemon = True
    thread.start()

    return jsonify({'message': '크롤링 시작됨'})


@app.route('/api/can-update')
def can_update():
    """24시간 경과 여부 확인"""
    if not status['last_update']:
        return jsonify({'can_update': True, 'hours_passed': None})

    last = datetime.fromisoformat(status['last_update'])
    now = datetime.now()
    hours_passed = (now - last).total_seconds() / 3600

    return jsonify({
        'can_update': hours_passed >= 24,
        'hours_passed': round(hours_passed, 1),
        'last_update': status['last_update']
    })


# 🔹 정적 파일 서빙
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_file(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    print("🚀 Flask 서버 시작: http://localhost:5000")
    print("📡 관리자 페이지: http://localhost:5000/admin.html")
    app.run(debug=True, port=5000)
