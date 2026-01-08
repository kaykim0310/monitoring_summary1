import pdfplumber
import re
from collections import defaultdict
import sys

# Windows console encoding fix
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def clean_text(text):
    if not text:
        return ""
    return text.replace("\n", " ").strip()

def classify_factor(factor_name):
    """유해인자 이름을 기반으로 카테고리를 분류합니다."""
    factor_name = factor_name.replace("\n", "").strip()
    if not factor_name or factor_name == "유해인자":
        return None
        
    if "소음" in factor_name:
        return "물리적인자"
    elif any(x in factor_name for x in ["분진", "석영", "규소", "시멘트"]):
        return "분진류"
    elif any(x in factor_name for x in ["산화철", "망간", "티타늄", "용접흄", "금속"]):
        return "금속류"
    elif any(x in factor_name for x in ["산", "알칼리", "황산", "염산", "수산화"]):
        return "산 및 알칼리류"
    elif any(x in factor_name for x in ["아세톤", "톨루엔", "크실렌", "부틸", "에탄올", "유기화합물", "초산메틸"]):
        return "유기화합물"
    else:
        return "기타"

def extract_job_data(pdf_path):
    # 공정별 데이터 저장
    # 키: 공정명
    jobs = defaultdict(lambda: {
        "job_content": set(),
        "factors": defaultdict(set),
        "workers": 0, # 단순 합계가 아니라 중복 제거 로직 등이 필요할 수 있음
        "work_form": set(),
        "seen_workers": set() # 중복 집계 방지용 (이름 기준)
    })
    
    company_info = {}

    with pdfplumber.open(pdf_path) as pdf:
        # 1. 개요 정보 추출 (주로 첫 페이지)
        first_page_text = pdf.pages[0].extract_text()
        if "공장명" in first_page_text:
            match = re.search(r"공장명\s*:\s*(.*?)\s*[○\n]", first_page_text)
            if match:
                company_info["name"] = match.group(1).strip()
            # 공사명 등은 헤더나 상단 텍스트에서 유추
        
        # 2. 테이블 데이터 추출
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                # 테이블 구조 파악 (헤더 제외)
                # 보통: 공정명 | ... | 작업장소 | 유해인자 | 근로자수 | ...
                # 인덱스: 0      2          3          4
                
                # 병합된 셀 처리를 위해 이전 행 값 기억
                last_job = None
                
                for row_idx, row in enumerate(table):
                    # 헤더 건너뛰기
                    if not row or len(row) < 5: continue
                    if "공정명" in str(row[0]) or "부서" in str(row[0]): continue

                    # 공정명 (Col 0)
                    job_name = row[0]
                    if job_name:
                        job_name = job_name.replace("\n", "").strip()
                        last_job = job_name
                    else:
                        job_name = last_job # 병합된 셀 처리
                    
                    if not job_name: continue

                    # 작업장소/내용 (Col 2)
                    if len(row) > 2 and row[2]:
                        content = row[2].replace("\n", " ").strip()
                        if content and "작업장소" not in content:
                            jobs[job_name]["job_content"].add(content)
                            
                    # 유해인자 (Col 3)
                    if len(row) > 3 and row[3]:
                        factor_raw = row[3]
                        if factor_raw and "유해인자" not in factor_raw:
                            factors = factor_raw.replace("\n", " ").split() # 공백이나 줄바꿈으로 분리
                            # 또는 한글/영문 혼합 시 정규식 분리 고려
                            # 여기서는 단순 분리 후 정제
                            for f in factors:
                                f = f.strip()
                                if not f: continue
                                category = classify_factor(f)
                                if category:
                                    jobs[job_name]["factors"][category].add(f)

                    # 근로자 - 중복 방지 (이름이 Col 7에 있다고 가정하거나, 단순히 row 단위로 집계)
                    # PDF 덤프를 보면 Col 4에 '자수', Col 7에 '근로자명'이 있음
                    # Col 4: '13', '6' 등 (부서 전체 인원일 수 있음)
                    # 측정치 행마다가 아니라 공정별로 한번만 가져와야 함.
                    # 여기서는 '근로자명'(Col 7)이 있으면 카운트 하거나,
                    # Col 4(자수)가 숫자로 있으면 max 값을 취하는 전략 등 (페이지 넘김 고려)
                    
                    if len(row) > 4 and row[4]:
                         val = row[4].replace("\n", "").strip()
                         if val.isdigit():
                             # 해당 공정의 근로자수로 업데이트 (보통 같은 공정 행에는 같은 숫자가 적혀있음)
                             current_max = jobs[job_name]["workers"]
                             jobs[job_name]["workers"] = max(current_max, int(val))

                    # 근무형태 (Col 5)
                    if len(row) > 5 and row[5]:
                        form = row[5].replace("\n", " ").strip()
                        if "교대" in form:
                            jobs[job_name]["work_form"].add(form.split()[0])

    return company_info, jobs

def convert_pdf_to_txt(pdf_path):
    company_info, jobs = extract_job_data(pdf_path)
    
    lines = []
    lines.append("-" * 93) # 구분선 길이 조정
    
    company = company_info.get("name", "(주)동양건설산업")
    if "(주)" not in company and "동양" in company: company = "(주)" + company
    
    # 제목 부분
    lines.append(f"■ {company} 고속국도 제14호선 함양~창녕간 건설공사 제12공구에 대한 공정별 작업내용과")
    lines.append(f"   작업환경측정 대상 유해인자는 다음과 같습니다.")
    lines.append("-" * 93)
    
    lines.append("□ 공사개요")
    lines.append(f"   ◆ 공 사 명: 고속국도 제14호선 함양~창녕간 건설공사 제12공구")
    lines.append(f"   ◆ 착공일자: 2019. 02. 20")
    lines.append(f"   ◆ 준공일자: 2026. 12. 31(예정)")
    lines.append(f"   ◇ 특이사항: 공사현장의 경우 공기에 따라 작업내용이 달라질 수 있으므로 작업환경측정 당일") 
    lines.append(f"                진행되는 작업을 대상으로 작업환경측정을 실시함.")
    lines.append("-" * 93)
    
    # 공정 순서 (PDF 등장 순서대로 하거나 정렬)
    # 딕셔너리는 순서 보장 (Python 3.7+)
    
    for job_name, data in jobs.items():
        if not job_name: continue
        
        lines.append(f"■ {job_name}")
        lines.append("-" * 93)
        
        # 작업내용
        contents = ", ".join(sorted(list(data["job_content"])))
        lines.append(f"   ◇ 작업내용 : {contents}")
        lines.append("")
        
        # 유해인자
        # lines.append("   ◇ 유해인자 : ", end="") # Error fix
        lines.append("   ◇ 유해인자 :")
        # 수정: 라인 추가 방식 변경
        current_line_idx = len(lines) - 1
        lines[current_line_idx] = "   ◇ 유해인자 :" # 덮어쓰기
        
        category_order = ["물리적인자", "분진류", "금속류", "유기화합물", "산 및 알칼리류", "기타"]
        
        is_first = True
        for cat in category_order:
            if cat in data["factors"] and data["factors"][cat]:
                factors = sorted(list(data["factors"][cat]))
                factors_str = ", ".join(factors)
                
                header = f"* {cat}"
                # 정렬 맞추기: "* 물리적인자 :" (길이 고려)
                # 템플릿: "* 물리적인자 : 소음" (띄어쓰기 1칸)
                # 템플릿: "                 * 분진류     : ..." (줄바꿈 후 들여쓰기)
                
                # 카테고리명 뒤 공백 패딩 로직 (템플릿 처럼 '분진류     :')
                # 물리적인자(5글자) 기준?
                pad_len = 5 - len(cat) # 단순 길이 차이
                if pad_len < 0: pad_len = 0
                # spacer = " " * (pad_len * 2) # 한글 2byte 고려 대충
                # 템플릿 레이아웃 하드코딩에 가깝게
                
                if cat == "물리적인자": cat_disp = "물리적인자 :"
                elif cat == "분진류":     cat_disp = "분진류     :"
                elif cat == "금속류":     cat_disp = "금속류     :"
                elif cat == "유기화합물": cat_disp = "유기화합물 :"
                else:                     cat_disp = f"{cat} :"
                
                if is_first:
                    lines[current_line_idx] += f" {header} : {factors_str}" # 첫 줄은 옆에 붙임? 아님 템플릿은?
                    # 템플릿: "   ◇ 유해인자 : * 물리적인자 : 소음" -> 한 줄임
                    # 내 코드 수정:
                    lines[current_line_idx] = f"   ◇ 유해인자 : * {cat_disp} {factors_str}"
                    is_first = False
                else:
                    lines.append(f"                 * {cat_disp} {factors_str}")
        
        lines.append("") # 공백 라인
        
        # 근무현황
        forms = ", ".join(sorted(list(data["work_form"])))
        workers = data["workers"]
        lines.append(f"   ◇ 근무현황 : {workers}명, {forms}")
        
        lines.append("-" * 93)

    return "\n".join(lines)

if __name__ == "__main__":
    # 로컬 테스트 용
    result = convert_pdf_to_txt("측정결과_동양건설(창녕12공구)_25하.pdf")
    print(result)
    with open("분포실태_결과_test.txt", "w", encoding="utf-8") as f:
        f.write(result)
