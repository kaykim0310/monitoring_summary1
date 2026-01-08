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
    # 계층적 데이터 저장: jobs[group_name][unit_name] = data
    jobs = defaultdict(lambda: defaultdict(lambda: {
        "job_content": "", # text accumulating
        "factors": defaultdict(set),
        "workers": 0,
        "work_form": set()
    }))
    
    company_info = {}

    with pdfplumber.open(pdf_path) as pdf:
        # 1. 개요 정보
        try:
            first_page_text = pdf.pages[0].extract_text()
            if "공장명" in first_page_text:
                match = re.search(r"공장명\s*:\s*(.*?)\s*[○\n]", first_page_text)
                if match: company_info["name"] = match.group(1).strip()
            if "공 사 명" in first_page_text:
                match = re.search(r"공 사 명\s*:\s*(.*)", first_page_text)
                if match: company_info["project"] = match.group(1).strip()
        except: pass
        
        # 2. 테이블 데이터 추출 (text layout strategy)
        for page in pdf.pages:
            # horizontal_strategy="text" 사용
            tables = page.extract_tables(table_settings={"horizontal_strategy": "text"})
            
            for table in tables:
                if not table: continue
                
                # State variables
                current_group = None
                current_unit_key = None # 임시 식별자(카운터 등) 또는 unit_name
                
                # 현재 Unit의 상태
                unit_completed = False
                unit_text_buffer = []
                
                # 이전 루프의 Group 유지를 위해
                if not 'last_persistent_group' in locals():
                    last_persistent_group = None

                for row in table:
                    # 너무 짧거나 헤더인 경우 스킵
                    if not row or len(row) < 5: continue
                    # 헤더 판별 (텍스트 포함 여부)
                    row_str = "".join([str(x) for x in row if x])
                    if "공정명" in row_str or "부서" in row_str: continue

                    # 컬럼 추출 (인덱스 조심, text strategy는 컬럼이 밀릴 수 있음)
                    # 보통 0:Group, 1:Null?, 2..:Unit?, ..:Workers?
                    # 공백 컬럼이 많을 수 있으니 index heuristic 필요 할 수도 있지만
                    # pdfplumber는 col 구조를 유지하려고 노력함.
                    # Col 0: Group (might be empty)
                    # Col 2: Job Content (might be empty)
                    # Col 3: Factors
                    # Col 4: Worker Count (Numeric?)
                    # Col 5: Work Form
                    
                    # Col 4 (Worker) Check
                    worker_val = None
                    if len(row) > 4 and row[4]:
                         val = str(row[4]).replace("\n", "").strip()
                         # 숫자 포함 여부
                         if any(c.isdigit() for c in val):
                             worker_val = val

                    # Col 0 (Group) Check
                    group_text = row[0]
                    if group_text:
                        group_text = str(group_text).replace("\n", "").strip()

                    # Col 2 (Unit Text)
                    unit_text_part = ""
                    if len(row) > 2 and row[2]:
                        unit_text_part = str(row[2]).replace("\n", " ").strip()

                    # Logic to Switch Unit/Group
                    if group_text:
                        # Case 1: Start New Group -> Force New Unit
                        last_persistent_group = group_text
                        current_group = group_text
                        
                        # Start New Unit
                        if unit_text_buffer: # Commit previous if buffer exists (though logic should have handled it)
                            pass 
                        
                        unit_text_buffer = [unit_text_part] if unit_text_part else []
                        unit_completed = False
                        
                        # 만약 이 라인에 worker도 있다면? -> Completed immediately
                        if worker_val:
                            unit_completed = True
                            
                    else:
                        # Case 2: Same Group (Col 0 empty)
                        current_group = last_persistent_group
                        
                        if not current_group: continue # Skip junk rows before first group
                        
                        if unit_completed and unit_text_part:
                            # Previous unit finished, and we see new text -> Start New Unit
                            unit_text_buffer = [unit_text_part]
                            unit_completed = False
                        else:
                            # Continuation
                            if unit_text_part:
                                unit_text_buffer.append(unit_text_part)
                        
                        if worker_val:
                             unit_completed = True

                    # Factor Accumulation & Store
                    # Since we don't know "When unit ends" until we start new one, 
                    # we should update the "Current Unit object" continuously.
                    # But the "Key" for the unit is the Text itself?
                    # Issue: Text accumulates over lines.
                    # Solution: Use a "Unit Object" reference.
                    
                    # Instead of dict jobs[group][name], let's use a list of units or keeping a pointer.
                    # jobs[group] = [ {unit_data}, ... ]
                    
                    # But return format expects dict items.
                    # Let's use `jobs[group][index]` or maintain a "Current Unit Object".
                    
                    # Simpler: Update the `last unit object` in the list.
                    # Whenever "Start New Unit" happens, create new object.
                    
                    # "Start New Unit" condition re-evaluated:
                    is_new_unit = False
                    if group_text: 
                        is_new_unit = True
                    elif unit_completed and unit_text_part: # Was completed, seeing new text implies new unit
                        # Wait, `unit_completed` was set in PREVIOUS row?
                        # Yes, I used `unit_completed` state variable.
                        # BUT, I need to check `unit_completed` (from prev row) BEFORE setting it for this row.
                        # My logic above: 
                        # `if unit_completed and unit_text_part:` -> Start New Unit.
                        is_new_unit = True
                    
                    # Re-structuring the loop logic properly:
                    
                table_iterator = iter(table)
                # ... rewriting inside `extract_job_data` ...
                pass 
                
    # Re-writing the function logic cleanly
    # (Since I cannot edit inside tool call as text, I will write the full function string below)
    return extract_job_data_impl(pdf_path)

def extract_job_data_impl(pdf_path):
    jobs = defaultdict(list) 
    company_info = {}
    
    # Default indices (heuristic)
    col_map = {
        "group": 0,
        "unit": 3,
        "factor": 4, 
        "worker": 5, 
        "form": 6
    }
    
    with pdfplumber.open(pdf_path) as pdf:
        try:
            first_page_text = pdf.pages[0].extract_text()
            if first_page_text:
                lines = first_page_text.split('\n')
                if lines:
                    for line in lines:
                        clean_line = line.strip()
                        if not clean_line: continue
                        
                        # Skip typical report headers
                        if "나-1" in clean_line or "단위작업" in clean_line:
                            if ":" in clean_line:
                                # Extract content after colon
                                temp = clean_line.split(":", 1)[1].strip()
                                if temp:
                                    company_info["name"] = temp
                                    break
                            continue
                        
                        if "측정" in clean_line and "결과" in clean_line: continue
                        
                        # If we reached here, it might be the company name line
                        company_info["name"] = clean_line
                        break
                        
            # Use regex if specific pattern found (more reliable)
            if "공장명" in first_page_text:
                m = re.search(r"공장명\s*:\s*(.*?)\s*[○\n]", first_page_text)
                if m: company_info["name"] = m.group(1).strip()

            if "공 사 명" in first_page_text:
                m = re.search(r"공 사 명\s*:\s*(.*)", first_page_text)
                if m: company_info["project"] = m.group(1).strip()
        except: pass

        for page in pdf.pages:
            tables = page.extract_tables(table_settings={"horizontal_strategy": "text"})
            for table in tables:
                if not table: continue
                
                # 1. Detect Header
                header_found = False
                for row in table[:5]:
                    if not row: continue
                    row_str = "".join([str(x) for x in row if x])
                    if "공정" in row_str and ("작업" in row_str or "장소" in row_str):
                        for cb_idx, cell in enumerate(row):
                            if not cell: continue
                            txt = str(cell).replace(" ", "")
                            if "공정" in txt or "부서" in txt: col_map["group"] = cb_idx
                            elif "작업" in txt or "장소" in txt or "단위" in txt: col_map["unit"] = cb_idx
                            elif "유해" in txt or "인자" in txt: col_map["factor"] = cb_idx
                            elif "근로" in txt or "자수" in txt or "측정치" in txt:
                                if "치" not in txt: col_map["worker"] = cb_idx
                            elif "형태" in txt or "근무" in txt: col_map["form"] = cb_idx
                        header_found = True
                        break
                
                current_group = None
                current_unit = None
                
                # Flag to track if the current unit 'row' seems complete (has workers/form)
                # If complete, next text implies new unit.
                unit_row_completed = False

                for row in table:
                    if not row or len(row) < 3: continue
                    
                    row_full = "".join([str(x) for x in row if x])
                    if "공정" in row_full and "작업" in row_full: continue
                    if "측정방법" in row_full or "비고" in row_full: continue 
                    if "평균치" in row_full: continue
                    if "측정시각" in row_full: continue # Time header

                    def get_col(idx):
                        if idx < len(row) and row[idx]:
                            return str(row[idx]).replace("\n", " ").strip()
                        return ""
                    
                    g_text = get_col(col_map["group"])
                    u_text = get_col(col_map["unit"])
                    f_text = get_col(col_map["factor"])
                    w_text = get_col(col_map["worker"])
                    form_text = get_col(col_map["form"])
                    
                    # Garbage Filter: Timestamps / Footer
                    # If any text contains "~" and ":" (e.g. ~ 15:30), it's likely a timestamp row
                    if re.search(r'~\s*\d{1,2}:\d{2}', row_full) or re.search(r'\d{1,2}:\d{2}\s*~', row_full):
                        continue
                    if "종료" in row_full or "시작" in row_full:
                        continue
                    
                    # Worker Val: Keep exact string 
                    w_val = None
                    if w_text: 
                         w_val = w_text
                    
                    # Unit Name Cleanup: Ignore numeric garbage
                    if u_text and (u_text.isdigit() or re.match(r'^\d+(\s+\d+)*$', u_text) or len(u_text) < 2 and u_text.isdigit()):
                        if not w_val: w_val = u_text # Fallback
                        u_text = ""

                    # Logic: When to start a New Unit?
                    # 1. Group text exists -> Definitely New Group -> New Unit
                    # 2. Unit text exists AND Previous Unit was 'Completed' (had workers/factors populated in a way that implies end)
                    # OR just standard: If Unit text exists -> New Unit (unless it looks like wrapped text).
                    # 'Wrapped text' heuristic: Previous line had NO workers/form, and this line has text.
                    
                    start_new_unit = False
                    
                    if g_text:
                        current_group = g_text
                        start_new_unit = True
                    elif u_text:
                        # If we have text, is it a new unit or continuation?
                        if unit_row_completed:
                            start_new_unit = True
                        else:
                            # Previous row didn't have workers/form.
                            # It might be a continuation of the name.
                            # OR it might be distinct unit that just has no worker data (unlikely for "Distribution" report)
                            # Let's assume continuation.
                            start_new_unit = False
                    
                    # If we don't have a current unit object yet, force start
                    if not current_unit and (g_text or u_text):
                        if not g_text and current_group: # Continuation of group but start of first unit finding
                             start_new_unit = True
                        elif g_text:
                             start_new_unit = True

                    if start_new_unit:
                        current_unit = {
                            "name_parts": [],
                            "factors": defaultdict(set),
                            "workers": "", # String accumulation
                            "work_form": set()
                        }
                        if current_group:
                            jobs[current_group].append(current_unit)
                        unit_row_completed = False
                        
                    if not current_unit: continue
                    
                    # 1. Name Parts
                    if u_text:
                        current_unit["name_parts"].append(u_text)
                    
                    # 2. Workers
                    if w_val:
                        # User wants exact string.
                        # If multiple rows have workers for same 'unit' (merged cells with split rows?), logic says we started new unit?
                        # If we are here, it means we are in 'current_unit'.
                        # If 'current_unit' already has workers, and we see NEW workers on this line...
                        # It suggests we missed a split? 
                        # Or it's just aggregating.
                        # Given "Strict Separation", if we see `w_val`, it flags completion.
                        current_unit["workers"] = w_val # Overwrite or append? "16(4)" usually one line.
                        unit_row_completed = True
                        
                    # 3. Form
                    if form_text:
                        if "교대" in form_text:
                            current_unit["work_form"].add(form_text.split()[0])
                        unit_row_completed = True # Form implies completion row usually
                            
                    # 4. Factors
                    if f_text and "유해인자" not in f_text:
                        if f_text.isdigit(): pass
                        else:
                            parts = f_text.split()
                            for p in parts:
                                p = p.strip()
                                cat = classify_factor(p)
                                if cat:
                                    current_unit["factors"][cat].add(p)

    # Post-process: Just flatten name parts
    final_jobs = defaultdict(list)
    
    for grp, unit_list in jobs.items():
        if not grp: continue
        # Filter out Header Groups
        if grp == "공정" or grp == "부서" or grp == "단위작업장소": continue
        
        for u in unit_list:
            full_name = " ".join(u["name_parts"]).strip()
            
            # Check for timestamp in worker field (e.g. 07:07) -> Garbage unit
            w_str = str(u["workers"])
            if re.search(r'\d{2}:\d{2}', w_str):
                continue
            
            if not full_name: 
                # If no name, and no significant data, skip
                if not u["factors"] and not w_str: continue
                full_name = "(공정명 없음)"
            
            # If name is still empty/placeholder and no meaningful data, skip
            if full_name == "(공정명 없음)" and (not w_str or w_str.strip() == ""):
                 continue

            # Save refined object
            u["job_content"] = full_name 
            final_jobs[grp].append(u)

    return company_info, final_jobs

def extract_job_data(pdf_path):
    return extract_job_data_impl(pdf_path)

def convert_pdf_to_txt(pdf_path):
    company_info, jobs = extract_job_data(pdf_path)
    
    lines = []
    lines.append("-" * 93)
    
    company = company_info.get("name", "OOO회사") # Default to generic
    if company and "(주)" not in company and "동양" not in company and "건설" in company: 
         # Simple heuristic, but safer to just use what is found or generic
         pass
    
    project_name = company_info.get("project", "OOOO 공사") # Generic default
    
    lines.append(f"■ {company} {project_name}에 대한 공정별 작업내용과")
    lines.append(f"   작업환경측정 대상 유해인자는 다음과 같습니다.")
    lines.append("-" * 93)
    
    lines.append("-" * 93)
    
    # lines.append("□ 공사개요")
    # lines.append(f"   ◆ 공 사 명: {project_name}")
    # lines.append(f"   ◆ 착공일자: 20  .   .   .") 
    # lines.append(f"   ◆ 준공일자: 20  .   .   .(예정)")
    # lines.append(f"   ◇ 특이사항: 공사현장의 경우 공기에 따라 작업내용이 달라질 수 있으므로 작업환경측정 당일") 
    # lines.append(f"                진행되는 작업을 대상으로 작업환경측정을 실시함.")
    # lines.append("-" * 93)
    
    # 계층적 출력
    # jobs: group -> list of unit objects
    
    for group_name, unit_list in jobs.items():
        if not group_name: continue
        
        # Group Header
        lines.append(f"<< {group_name} >>")
        lines.append("-" * 93)
        
        for data in unit_list:
            unit_name = data.get("job_content", "공정")
            
            # Unit Header
            lines.append(f"■ {unit_name}")
            lines.append("-" * 93)
            
            # 작업내용
            # unit_name 자체가 작업내용인 경우가 많음
            lines.append(f"   ◇ 작업내용 : {unit_name}")
            lines.append("")
            
            # 유해인자
            category_order = ["물리적인자", "분진류", "금속류", "유기화합물", "산 및 알칼리류", "기타"]
            
            # 유해인자 유무 확인 for Printing "◇ 유해인자 :"
            has_factors = any(data["factors"][cat] for cat in category_order)
            
            if has_factors:
                lines.append("   ◇ 유해인자 :")
                current_line_idx = len(lines) - 1
                
                is_first = True
                for cat in category_order:
                    if cat in data["factors"] and data["factors"][cat]:
                        factors = sorted(list(data["factors"][cat]))
                        factors_str = ", ".join(factors)
                        
                        # 포맷팅
                        if cat == "물리적인자": cat_disp = "물리적인자 :"
                        elif cat == "분진류":     cat_disp = "분진류     :"
                        elif cat == "금속류":     cat_disp = "금속류     :"
                        elif cat == "유기화합물": cat_disp = "유기화합물 :"
                        else:                     cat_disp = f"{cat:<10} :"
                        
                        if is_first:
                            lines[current_line_idx] = f"   ◇ 유해인자 : * {cat_disp} {factors_str}"
                            is_first = False
                        else:
                            lines.append(f"                 * {cat_disp} {factors_str}")
                lines.append("") # 공백
                
            # 근무현황
            forms = ", ".join(sorted(list(data["work_form"])))
            workers = data["workers"] # Now string
            if workers or forms:
                term = f"{workers}명" if str(workers).isdigit() else f"{workers}"
                if forms: term += f", {forms}"
                lines.append(f"   ◇ 근무현황 : {term}")
            
            lines.append("-" * 93)

    return "\n".join(lines)

if __name__ == "__main__":
    # 로컬 테스트 용
    result = convert_pdf_to_txt("측정결과_동양건설(창녕12공구)_25하.pdf")
    print(result)
    with open("분포실태_결과_test.txt", "w", encoding="utf-8") as f:
        f.write(result)
