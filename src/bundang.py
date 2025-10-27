from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import json
from datetime import datetime
import re
import time

def parse_date(date_str):
    """날짜 문자열을 ISO 8601 형식으로 변환"""
    try:
        # "2025.10.27" 형식을 파싱
        date_obj = datetime.strptime(date_str.strip(), "%Y.%m.%d")
        return date_obj
    except:
        return None

def parse_dday(dday_str):
    """D-day 문자열 추출"""
    # "D-3" 형식 추출
    match = re.search(r'D-?\d+', dday_str)
    if match:
        return match.group(0)
    return ""

def setup_driver():
    """Chrome 드라이버 설정 (자동 다운로드)"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 브라우저 창을 띄우지 않음
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # webdriver-manager를 사용하여 자동으로 ChromeDriver 다운로드
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def crawl_snubh_recruitment():
    """분당서울대병원 채용 공고 크롤링 (Selenium 사용)"""
    
    driver = None
    
    try:
        print("[INFO] Chrome 드라이버 초기화 중...")
        driver = setup_driver()
        
        # 기본 URL
        base_url = "https://snubh.recruiter.co.kr"
        list_url = f"{base_url}/app/jobnotice/list"
        
        print(f"[DEBUG] 페이지 접속 중: {list_url}")
        driver.get(list_url)
        
        # 페이지 로드 대기
        print("[DEBUG] 페이지 로딩 대기 중...")
        time.sleep(2)
        
        # 100개씩 보기 설정
        try:
            print("[DEBUG] 100개씩 보기 설정 중...")
            select_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "pageSize"))
            )
            select = Select(select_element)
            select.select_by_value("100")
            
            # 선택 후 페이지 로드 대기
            time.sleep(3)
            print("[DEBUG] 100개씩 보기 설정 완료")
        except Exception as e:
            print(f"[WARNING] 100개씩 보기 설정 실패: {e}")
        
        # divJobnoticeList가 로드될 때까지 대기
        print("[DEBUG] 채용 공고 목록 로딩 대기 중...")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "divJobnoticeList"))
        )
        
        # 추가 대기 (JavaScript 실행 완료)
        time.sleep(2)
        
        # 페이지 소스 가져오기
        page_source = driver.page_source
        print(f"[DEBUG] 페이지 소스 길이: {len(page_source)} 문자")
        
        # BeautifulSoup으로 파싱
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # 디버깅용 HTML 저장
        with open('debug_selenium_snubh.html', 'w', encoding='utf-8') as f:
            f.write(page_source)
        print("[DEBUG] HTML을 debug_selenium_snubh.html에 저장했습니다.")
        
        # 채용 공고 리스트
        job_list = []
        
        # divJobnoticeList 내부의 ul 찾기
        div_element = soup.find('div', id='divJobnoticeList')
        
        if not div_element:
            print("[ERROR] divJobnoticeList를 찾을 수 없습니다.")
            return []
        
        ul_element = div_element.find('ul')
        
        if not ul_element:
            print("[ERROR] ul 요소를 찾을 수 없습니다.")
            print(f"[DEBUG] divJobnoticeList 내용: {div_element.prettify()[:500]}")
            return []
        
        # li 태그들 찾기
        li_elements = ul_element.find_all('li', recursive=False)
        print(f"[DEBUG] 총 {len(li_elements)}개의 공고를 찾았습니다.\n")
        
        for idx, li in enumerate(li_elements, 1):
            try:
                print(f"\n[DEBUG] --- {idx}번째 공고 처리 중 ---")
                
                # 상태 확인 - "접수중"인지 체크
                status_element = li.select_one('div.list-bbs-status > span')
                
                if status_element:
                    status_text = status_element.get_text(strip=True)
                    print(f"[DEBUG] 상태: '{status_text}'")
                else:
                    print(f"[DEBUG] 상태 요소를 찾을 수 없습니다.")
                
                if not status_element or '접수중' not in status_element.get_text(strip=True):
                    print(f"[INFO] {idx}번째 공고: 접수중이 아니므로 크롤링을 종료합니다.")
                    break
                
                # 제목 및 링크
                # span.list-bbs-notice-name > a 셀렉터 사용
                title_element = li.select_one('span.list-bbs-notice-name > a')
                
                if not title_element:
                    # 대체 셀렉터
                    title_element = li.select_one('h2.list-bbs-title a')
                    print(f"[DEBUG] 대체 제목 셀렉터 사용")
                
                if not title_element:
                    print(f"[ERROR] {idx}번째 공고의 제목을 찾을 수 없습니다.")
                    continue
                
                title = title_element.get_text(strip=True)
                detail_path = title_element.get('href', '')
                detail_url = f"{base_url}{detail_path}" if detail_path else ""
                print(f"[DEBUG] 제목: {title}")
                print(f"[DEBUG] 상세 URL: {detail_url}")
                
                # 날짜 (시작일 ~ 종료일)
                date_element = li.select_one('span.list-bbs-date')
                
                if not date_element:
                    print(f"[ERROR] {idx}번째 공고의 날짜를 찾을 수 없습니다.")
                    continue
                
                date_text = date_element.get_text(strip=True)
                print(f"[DEBUG] 날짜 텍스트: '{date_text}'")
                
                # 날짜 파싱 (예: "2025.10.24(금) 09:00 ~ 2025.11.03(월) 23:59")
                start_dt = ""
                end_dt = ""
                
                # 정규식으로 날짜와 시간 추출
                date_pattern = r'(\d{4}\.\d{2}\.\d{2})\([^)]+\)\s+(\d{2}:\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})\([^)]+\)\s+(\d{2}:\d{2})'
                match = re.search(date_pattern, date_text)
                
                if match:
                    start_date_str = match.group(1)  # 2025.10.24
                    start_time_str = match.group(2)  # 09:00
                    end_date_str = match.group(3)    # 2025.11.03
                    end_time_str = match.group(4)    # 23:59
                    
                    # 시작일 파싱
                    start_date = parse_date(start_date_str)
                    if start_date:
                        start_hour, start_min = map(int, start_time_str.split(':'))
                        start_dt = start_date.replace(hour=start_hour, minute=start_min, second=0).strftime("%Y-%m-%dT%H:%M:%S+09:00")
                    
                    # 종료일 파싱
                    end_date = parse_date(end_date_str)
                    if end_date:
                        end_hour, end_min = map(int, end_time_str.split(':'))
                        end_dt = end_date.replace(hour=end_hour, minute=end_min, second=0).strftime("%Y-%m-%dT%H:%M:%S+09:00")
                    
                    print(f"[DEBUG] 파싱된 시작일: {start_dt}")
                    print(f"[DEBUG] 파싱된 종료일: {end_dt}")
                
                # D-day
                dday_element = li.select_one('span.list-bbs-dday')
                dday = parse_dday(dday_element.get_text(strip=True)) if dday_element else ""
                print(f"[DEBUG] D-day: '{dday}'")
                
                # URL에서 공고 번호 추출
                recu_idx = ""
                announce_sn = ""
                
                if detail_path:
                    # URL 파라미터 파싱
                    import urllib.parse
                    parsed = urllib.parse.urlparse(detail_path)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    print(f"[DEBUG] URL 파라미터: {query_params}")
                    
                    # jobnoticeSn 추출
                    if 'jobnoticeSn' in query_params:
                        announce_sn = query_params['jobnoticeSn'][0]
                        print(f"[DEBUG] announce_sn: {announce_sn}")
                
                # 결과 저장
                job_data = {
                    "title": title,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "dday": dday,
                    "recu_idx": recu_idx,
                    "announce_sn": announce_sn,
                    "detail_url": detail_url
                }
                
                job_list.append(job_data)
                print(f"[SUCCESS] {idx}. {title} - {dday} 추가 완료\n")
                
            except Exception as e:
                print(f"[ERROR] {idx}번째 공고 처리 중 오류: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        return job_list
        
    except Exception as e:
        print(f"[ERROR] 크롤링 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    finally:
        if driver:
            print("[INFO] 브라우저 종료 중...")
            driver.quit()

def save_to_json(data, filename='snubh.json'):
    """JSON 파일로 저장"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n결과를 {filename}에 저장했습니다.")

if __name__ == "__main__":
    print("=" * 60)
    print("분당서울대병원 채용 공고 크롤링 시작 (Selenium 사용)")
    print("=" * 60 + "\n")
    
    # 크롤링 실행
    jobs = crawl_snubh_recruitment()
    
    # 결과 출력
    print(f"\n{'=' * 60}")
    print(f"총 {len(jobs)}개의 접수중인 공고를 수집했습니다.")
    print(f"{'=' * 60}\n")
    
    # JSON 파일로 저장
    if jobs:
        save_to_json(jobs)
        
        # 결과 미리보기
        print("\n=== 수집된 데이터 미리보기 ===")
        print(json.dumps(jobs[:3], ensure_ascii=False, indent=2))
    else:
        print("수집된 데이터가 없습니다.")