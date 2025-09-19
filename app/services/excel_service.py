"""
엑셀 파일 처리 서비스
간호사 정보 엑셀 업로드/다운로드 관련 기능 제공
"""
import pandas as pd
import uuid
import tempfile
import os
import re
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

from db.models import Nurse as NurseModel, Group as GroupModel, Office as OfficeModel
from schemas.auth_schema import User as UserSchema


def create_nurse_template() -> str:
    """간호사 정보 엑셀 템플릿 생성"""
    
    # 템플릿 데이터 구조
    template_data = {
        '병동명': ['ICU', 'ICU', '응급실', '(입력 가이드)', ''],
        '식별코드': ['UUID자동생성', 'UUID자동생성', 'UUID자동생성', '(UUID는 자동생성됨)', ''],
        '계정 ID': ['nurse001', 'nurse002', 'nurse003', '(영문숫자조합)', ''],
        '이름': ['김간호', '이수간', '박일반', '(한글이름)', ''],
        '경력': [5, 10, 3, '(1이상정수)', ''],
        '직군': ['간호사', '간호사', '간호사', '(간호사)', ''],
        '직책': ['주임', '수간호사', '일반', '(주임/수간호사/일반)', ''],
        '수간호사여부': ['N', 'Y', 'N', '(Y/N)', '']
    }
    
    # DataFrame 생성
    df = pd.DataFrame(template_data)
    
    # 임시 파일 생성
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
        template_path = tmp_file.name
    
    # 엑셀 파일로 저장
    with pd.ExcelWriter(template_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='간호사정보', index=False)
        
        # 워크시트 스타일링
        worksheet = writer.sheets['간호사정보']
        
        # 헤더 스타일 적용
        for col in range(1, len(df.columns) + 1):
            cell = worksheet.cell(row=1, column=col)
            cell.font = cell.font.copy(bold=True)
            cell.fill = cell.fill.copy(fgColor="CCCCCC")
        
        # 가이드 행 스타일 적용 (4번째 행)
        for col in range(1, len(df.columns) + 1):
            cell = worksheet.cell(row=4, column=col)
            cell.font = cell.font.copy(italic=True, color="666666")
    
    return template_path


def get_or_create_group(group_name: str, user: UserSchema, db: Session) -> Tuple[Optional[str], bool, List[str]]:
    """
    병동명을 기반으로 group_id를 찾거나 새로 생성
    Returns: (group_id, is_new_group, warnings)
    """
    warnings = []
    
    # 현재 사용자의 office_id로 해당 office의 모든 그룹 조회
    existing_group = db.query(GroupModel).filter(
        GroupModel.office_id == user.office_id,
        GroupModel.group_name == group_name
    ).first()
    
    if existing_group:
        warnings.append(f"기존 '{group_name}' 그룹에 추가됩니다.")
        return existing_group.group_id, False, warnings
    
    # 기존에 없는 그룹명인 경우 새 그룹 ID 생성
    new_group_id = generate_new_group_id(user.office_id, db)
    warnings.append(f"새로운 그룹 '{group_name}'이 생성됩니다.")
    return new_group_id, True, warnings


def generate_new_group_id(office_id: str, db: Session) -> str:
    """office_id + 001, 002, 003... 형태로 새 그룹 ID 생성"""
    
    # 해당 office의 기존 그룹들 중 최대 번호 찾기
    existing_groups = db.query(GroupModel).filter(
        GroupModel.office_id == office_id,
        GroupModel.group_id.like(f"{office_id}%")
    ).all()
    
    max_number = 0
    for group in existing_groups:
        try:
            # office_id 뒤의 숫자 부분 추출
            number_part = group.group_id.replace(office_id, "")
            if number_part.isdigit():
                max_number = max(max_number, int(number_part))
        except:
            continue
    
    # 다음 번호로 새 그룹 ID 생성
    new_number = max_number + 1
    return f"{office_id}{new_number:03d}"


def create_new_group(group_name: str, group_id: str, user: UserSchema, db: Session) -> str:
    """새로운 그룹 생성"""
    
    new_group = GroupModel(
        group_id=group_id,
        office_id=user.office_id,
        group_name=group_name
    )
    
    db.add(new_group)
    db.flush()  # DB에 즉시 반영하되 커밋은 나중에
    
    return group_id


def get_next_sequence(group_id: str, active_status: int, db: Session) -> int:
    """해당 그룹의 특정 active 상태에서 다음 sequence 번호 반환"""
    
    max_sequence = db.query(func.max(NurseModel.sequence)).filter(
        NurseModel.group_id == group_id,
        NurseModel.active == active_status
    ).scalar()
    
    return (max_sequence or 0) + 1


def process_excel_upload(file_path: str, user: UserSchema, db: Session) -> Dict[str, Any]:
    """엑셀 파일 업로드 처리 및 검증"""
    
    try:
        # 엑셀 파일 읽기
        df = pd.read_excel(file_path, sheet_name=0)
        
        # 빈 행 및 가이드 행 제거
        df = df.dropna(how='all')  # 모든 컬럼이 비어있는 행 제거
        df = df[~df.iloc[:, 0].astype(str).str.contains('입력 가이드', na=False)]  # 가이드 행 제거
        
        # 최대 행 수 검증
        if len(df) > 1000:
            raise ValueError("최대 1000행까지만 업로드 가능합니다.")
        # 컬럼 매핑
        column_mapping = {
            '병동명': 'group_name',
            '식별코드': 'nurse_id', 
            '계정 ID': 'account_id',
            '이름': 'name',
            '경력': 'experience',
            '직군': 'role',
            '직책': 'level_',
            '수간호사여부': 'is_head_nurse'
        }
        # 컬럼명 유연 매핑 (유사한 이름 인식)
        flexible_mapping = {}
        for excel_col in df.columns:
            excel_col_clean = str(excel_col).strip()
            for standard_col, db_field in column_mapping.items():
                if (excel_col_clean == standard_col or 
                    excel_col_clean in ['병동', '부서'] and standard_col == '병동명' or
                    excel_col_clean in ['ID', '아이디'] and standard_col == '계정 ID' or
                    excel_col_clean in ['성명', '간호사명'] and standard_col == '이름' or
                    excel_col_clean in ['년차', '경력년수'] and standard_col == '경력' or
                    excel_col_clean in ['수간호사', '헤드너스'] and standard_col == '수간호사여부'):
                    flexible_mapping[excel_col] = db_field
                    break
        # 필수 컬럼 확인
        required_fields = ['group_name', 'account_id', 'name', 'experience', 'role', 'level_', 'is_head_nurse']
        missing_fields = [field for field in required_fields if field not in flexible_mapping.values()]
        if missing_fields:
            missing_korean = []
            field_korean_map = {
                'group_name': '병동명',
                'account_id': '계정 ID', 
                'name': '이름',
                'experience': '경력',
                'role': '직군',
                'level_': '직책',
                'is_head_nurse': '수간호사여부'
            }
            for field in missing_fields:
                missing_korean.append(field_korean_map.get(field, field))
            raise ValueError(f"필수 컬럼이 누락되었습니다: {', '.join(missing_korean)}")
            
        # 병동명별 그룹 정보 수집
        unique_groups = df[get_excel_column_by_field('group_name', flexible_mapping)].dropna().unique()
        group_info = {}
        new_groups_needed = []
        
        for group_name in unique_groups:
            group_name = str(group_name).strip()
            if not group_name:
                continue
                
            group_id, is_new, warnings = get_or_create_group(group_name, user, db)
            group_info[group_name] = {
                'group_id': group_id,
                'is_new': is_new,
                'warnings': warnings
            }
            
            if is_new:
                new_groups_needed.append(group_name)
        
        # 그룹별 sequence 카운터 초기화 (활성 상태 기준)
        group_sequence_counters = {}
        for group_name, info in group_info.items():
            group_id = info['group_id']
            if info['is_new']:
                # 새 그룹인 경우 1부터 시작
                group_sequence_counters[group_id] = 1
            else:
                # 기존 그룹인 경우 활성 상태(active=1)의 다음 sequence 가져오기
                group_sequence_counters[group_id] = get_next_sequence(group_id, 1, db)
        
        # 데이터 변환
        processed_data = []
        validation_results = []
        
        for idx, row in df.iterrows():
            try:
                # 병동명 처리
                group_name = str(row[get_excel_column_by_field('group_name', flexible_mapping)]).strip()
                group_data = group_info.get(group_name, {})
                group_id = group_data.get('group_id')
                
                # sequence 할당
                sequence = group_sequence_counters.get(group_id, 0)
                group_sequence_counters[group_id] = sequence + 1
                
                # 기본 데이터 변환
                nurse_data = {
                    # 'group_name': group_name,
                    'group_id': group_id,
                    'nurse_id': str(uuid.uuid4()) if pd.isna(row.get('식별코드')) or str(row.get('식별코드')).strip() == 'UUID자동생성' else str(row.get('식별코드')),
                    'account_id': str(row[get_excel_column_by_field('account_id', flexible_mapping)]).strip(),
                    'name': str(row[get_excel_column_by_field('name', flexible_mapping)]).strip(),
                    'experience': int(float(row[get_excel_column_by_field('experience', flexible_mapping)])),
                    'role': str(row[get_excel_column_by_field('role', flexible_mapping)]).strip(),
                    'level_': str(row[get_excel_column_by_field('level_', flexible_mapping)]).strip(),
                    'is_head_nurse': parse_boolean(row[get_excel_column_by_field('is_head_nurse', flexible_mapping)]),
                    'is_night_nurse': False,  # 기본값
                    'personal_off_adjustment': 0,  # 기본값
                    'preceptor_id': None,  # 기본값
                    'joining_date': None,  # 기본값
                    'resignation_date': None,  # 기본값
                    'sequence': sequence,
                    'active': 1  # 엑셀 업로드는 기본적으로 활성 상태
                }
                
                # 개별 행 검증
                row_validation = validate_single_row(group_name, nurse_data, user, db)
                
                # 그룹 상태 정보 추가
                row_validation['warnings'].extend(group_data.get('warnings', []))
                row_validation['is_new_group'] = group_data.get('is_new', False)
                row_validation['group_name'] = group_name
                
                processed_data.append(nurse_data)
                validation_results.append(row_validation)
                
            except Exception as e:
                # 행별 오류 처리
                error_data = {
                    'row_index': idx + 2,  # 엑셀 행 번호 (헤더 포함)
                    'error': str(e),
                    'is_valid': False,
                    'errors': [str(e)],
                    'warnings': [],
                    'is_new_group': False
                }
                validation_results.append(error_data)
                processed_data.append(None)
        
        # 전체 검증 결과 요약
        valid_count = sum(1 for result in validation_results if result.get('is_valid', False))
        error_count = len(validation_results) - valid_count
        overwrite_count = sum(1 for result in validation_results if result.get('is_overwrite', False))
        new_group_count = len(new_groups_needed)
        
        return {
            'success': True,
            'data': processed_data,
            'validation_results': validation_results,
            'new_groups_needed': new_groups_needed,
            'summary': {
                'total': len(validation_results),
                'valid': valid_count,
                'error': error_count,
                'overwrite': overwrite_count,
                'new_groups': new_group_count
            }
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'data': [],
            'validation_results': [],
            'new_groups_needed': [],
            'summary': {'total': 0, 'valid': 0, 'error': 0, 'overwrite': 0, 'new_groups': 0}
        }


def get_excel_column_by_field(field: str, mapping: Dict[str, str]) -> str:
    """필드명으로 엑셀 컬럼명 찾기"""
    for excel_col, db_field in mapping.items():
        if db_field == field:
            return excel_col
    raise ValueError(f"필드 {field}에 해당하는 엑셀 컬럼을 찾을 수 없습니다.")


def parse_boolean(value: Any) -> bool:
    """다양한 형태의 불린 값 파싱"""
    if pd.isna(value):
        return False
    
    str_value = str(value).strip().upper()
    return str_value in ['Y', 'YES', 'TRUE', '1', 'T', '참', '예']


def validate_single_row(group_name: str, nurse_data: Dict[str, Any], user: UserSchema, db: Session) -> Dict[str, Any]:
    """개별 행 데이터 검증"""
    
    errors = []
    warnings = []
    is_overwrite = False
    
    # # 병동명 검증
    # if not nurse_data.get('group_name'):
    #     errors.append("병동명은 필수입니다.")
    # elif not nurse_data.get('group_id'):
    #     errors.append("유효하지 않은 병동명입니다.")
    
    # 필수 필드 검증
    if not nurse_data.get('account_id'):
        errors.append("계정 ID는 필수입니다.")
    elif not re.match(r'^[a-zA-Z0-9]+$', nurse_data['account_id']):
        errors.append("계정 ID는 영문과 숫자만 사용 가능합니다.")
    
    if not nurse_data.get('name'):
        errors.append("이름은 필수입니다.")
    
    if nurse_data.get('experience', 0) < 1:
        errors.append("경력은 1년 이상이어야 합니다.")
    
    if not nurse_data.get('role'):
        errors.append("직군은 필수입니다.")
    
    if not nurse_data.get('level_'):
        errors.append("직책은 필수입니다.")
    
    # 중복 검사
    if nurse_data.get('group_id'):
        existing_nurse = db.query(NurseModel).filter(
            NurseModel.nurse_id == nurse_data['nurse_id']
        ).first()
        
        if existing_nurse:
            is_overwrite = True
            warnings.append(f"기존 간호사 '{existing_nurse.name}' 데이터를 덮어씁니다.")
        
        # 계정 ID 중복 검사 (다른 nurse_id와)
        existing_account = db.query(NurseModel).filter(
            NurseModel.account_id == nurse_data['account_id'],
            NurseModel.nurse_id != nurse_data['nurse_id']
        ).first()
        
        if existing_account:
            errors.append(f"계정 ID '{nurse_data['account_id']}'는 이미 사용 중입니다.")
    
    return {
        'is_valid': len(errors) == 0,
        'is_overwrite': is_overwrite,
        'errors': errors,
        'warnings': warnings,
        'nurse_data': nurse_data,
        'group_name': group_name
    }


def validate_excel_data(data: List[Dict[str, Any]], user: UserSchema, db: Session) -> Dict[str, Any]:
    """엑셀 데이터 전체 유효성 검증"""
    
    validation_results = []
    
    for nurse_data in data:
        if nurse_data is None:
            validation_results.append({'is_valid': False, 'errors': ['데이터 파싱 오류']})
            continue
            
        result = validate_single_row(nurse_data, user, db)
        validation_results.append(result)
    
    # 수간호사 최소 1명 검증
    head_nurses = [
        result for result in validation_results 
        if result.get('is_valid') and result.get('nurse_data', {}).get('is_head_nurse')
    ]
    
    if len(head_nurses) == 0:
        # 기존 수간호사가 있는지 확인
        existing_head_nurses = db.query(NurseModel).filter(
            NurseModel.group_id == user.group_id,
            NurseModel.is_head_nurse == True
        ).count()
        
        if existing_head_nurses == 0:
            return {
                'success': False,
                'error': '최소 1명의 수간호사가 필요합니다.',
                'validation_results': validation_results
            }
    
    valid_count = sum(1 for result in validation_results if result.get('is_valid', False))
    error_count = len(validation_results) - valid_count
    overwrite_count = sum(1 for result in validation_results if result.get('is_overwrite', False))
    
    return {
        'success': True,
        'validation_results': validation_results,
        'summary': {
            'total': len(validation_results),
            'valid': valid_count,
            'error': error_count,
            'overwrite': overwrite_count
        }
    }


def save_excel_data(data: List[Dict[str, Any]], user: UserSchema, db: Session) -> Dict[str, Any]:
    """검증된 데이터 DB 저장"""
    
    try:
        saved_count = 0
        updated_count = 0
        for nurse_data in data:
            if not nurse_data:
                continue
                
            # 기존 데이터 확인
            existing_nurse = db.query(NurseModel).filter(
                NurseModel.nurse_id == nurse_data['nurse_id']
            ).first()
            
            if existing_nurse:
                # 업데이트
                for key, value in nurse_data.items():
                    if hasattr(existing_nurse, key):
                        setattr(existing_nurse, key, value)
                existing_nurse.updated_at = datetime.now()
                updated_count += 1
            else:
                # 신규 생성
                new_nurse = NurseModel(**nurse_data)
                db.add(new_nurse)
                saved_count += 1
        
        db.commit()
        
        return {
            'success': True,
            'message': f'저장 완료: 신규 {saved_count}건, 업데이트 {updated_count}건',
            'saved_count': saved_count,
            'updated_count': updated_count
        }
        
    except Exception as e:
        db.rollback()
        return {
            'success': False,
            'error': f'저장 실패: {str(e)}'
        } 


def create_groups_and_save_data(data: List[Dict[str, Any]], new_groups_to_create: List[str], user: UserSchema, db: Session) -> Dict[str, Any]:
    """새 그룹 생성 후 데이터 저장"""
    
    try:
        # 새 그룹 생성
        created_groups = {}
        for group_name in new_groups_to_create:
            # 새 그룹 ID 생성
            new_group_id = generate_new_group_id(user.office_id, db)
            # print('new_group_id', new_group_id)
            # 그룹 생성
            create_new_group(group_name, new_group_id, user, db)
            created_groups[group_name] = new_group_id

        # 데이터의 group_id 업데이트 (이미 생성된 그룹 ID 사용)
        for nurse_data in data:
            if nurse_data:
                group_name = nurse_data.get('group_name')
                if group_name in created_groups:
                    nurse_data['group_id'] = created_groups[group_name]
        
        # 데이터 저장
        result = save_excel_data(data, user, db)
        if result['success']:
            result['created_groups'] = created_groups
            result['message'] = f"{result['message']} (새 병동 {len(created_groups)}개 생성)"
        
        return result
        
    except Exception as e:
        db.rollback()
        return {
            'success': False,
            'error': f'그룹 생성 및 저장 실패: {str(e)}'
        } 


def export_schedule_excel_bytes(schedule_id: str, current_user, db) -> bytes:
    """지정된 schedule_id의 근무표를 엑셀(xlsx) 바이트로 생성하여 반환합니다.
    
    요약: schedules, schedule_entries, nurses, shifts, shift_manage 정보를 조회하여
    example.html과 유사한 표 형태(상단 제목, 일자 헤더, 간호사별 행, D/E/N/O 합계, 일일 현황)를 구성합니다.
    
    Args:
        schedule_id: 스케줄 식별자
        current_user: 요청 사용자(권한/그룹 필터용)
        db: SQLAlchemy 세션
    
    Returns:
        bytes: 생성된 엑셀 파일의 바이트 데이터
    
    예시:
        - 2025년 9월 → "2025년 9월 근무표" 제목 표시.
        - 일수 30일이면 1~30 열 생성.
    """
    from io import BytesIO
    from datetime import date
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    from db.models import Schedule, ScheduleEntry, Nurse, Shift, RosterConfig, ShiftManage

    # ───────── 1) 데이터 로드 ─────────
    schedule = db.query(Schedule).filter(
        Schedule.schedule_id == schedule_id,
        Schedule.group_id == current_user.group_id,
        Schedule.dropped == False
    ).first()
    if not schedule:
        raise ValueError("스케줄을 찾을 수 없습니다.")

    year, month = schedule.year, schedule.month

    # 간호사 목록(경력 desc, nurse_id asc)
    nurses = db.query(Nurse.nurse_id, Nurse.name, Nurse.experience, Nurse.sequence).filter(
        Nurse.group_id == current_user.group_id
    ).order_by(Nurse.sequence.asc(), Nurse.nurse_id.asc()).all()

    # 엔트리
    entries = db.query(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule_id).all()

    # 시프트(색상 등은 엑셀에서는 텍스트 표기 중심으로 사용)
    shifts_db = db.query(Shift).all()
    known_shift_ids = {s.shift_id for s in shifts_db}

    # # config_version → ShiftManage 별칭 맵 작성
    # if schedule.config_id:
    #     rc = db.query(RosterConfig).filter(RosterConfig.config_id == schedule.config_id).first()
    # else:
    #     rc = db.query(RosterConfig).filter(RosterConfig.group_id == current_user.group_id).order_by(RosterConfig.created_at.desc()).first()
    # config_version = rc.config_version if rc else None

    alias_map: dict[str, str] = {}
    # if config_version:
    sm_rows = db.query(ShiftManage).filter(
        ShiftManage.office_id == current_user.office_id,
        ShiftManage.group_id == current_user.group_id,
        # ShiftManage.config_version == config_version
    ).all()
    for row in sm_rows:
        if not row.main_code:
            continue
        base = row.main_code.upper()
        alias_map[base] = base
        if row.codes:
            for c in row.codes:
                alias_map[str(c).upper()] = base
    alias_map.setdefault('OFF', 'O'); alias_map.setdefault('O', 'O')

    def to_base(code: str) -> str:
        if not code:
            return '-'
        u = code.upper()
        if u in alias_map:
            return alias_map[u]
        # 휴리스틱 (미등록 코드)
        if u.startswith('D'):
            return 'D'
        if u.startswith('E'):
            return 'E'
        if u.startswith('N'):
            return 'N'
        if u in ('O', 'OFF'):
            return 'O'
        return u

    # 일 수
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]

    # nurse별 일자→shift 매핑
    by_nurse: dict[str, dict[int, str]] = {}
    for e in entries:
        by_nurse.setdefault(e.nurse_id, {})[e.work_date.day] = e.shift_id

    # ───────── 2) 워크북/시트 ─────────
    wb = Workbook()
    ws = wb.active
    ws.title = "근무표"

    # 스타일
    center = Alignment(horizontal="center", vertical="center")
    header_font = Font(bold=True, size=12)
    title_font = Font(bold=True, size=20)
    thin = Side(style="thin", color="000000")
    border_all = Border(left=thin, right=thin, top=thin, bottom=thin)
    gray_fill = PatternFill("solid", fgColor="DEE2E6")

    # ───────── 3) 제목 영역 ─────────
    title = f"{year}년 {month}월 근무표"
    # 열 구성: [번호, 구분, 이름] + days + [spacer] + [D,E,N,O]
    static_cols = 4
    spacer_cols = 1
    summary_cols = 4
    total_cols = static_cols + days_in_month + spacer_cols + summary_cols
    # 제목을 스케줄 전체 폭(1..total_cols)으로 병합
    ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=total_cols)
    ws.cell(row=2, column=1, value=title).font = title_font
    ws.cell(row=2, column=1).alignment = center

    # ───────── 4) 헤더 행 ─────────
    header_row = 7
    ws.cell(row=header_row, column=1, value="번호").font = header_font
    ws.cell(row=header_row, column=2, value="구분").font = header_font
    ws.cell(row=header_row, column=3, value="경력").font = header_font
    ws.cell(row=header_row, column=4, value="이름").font = header_font
    for c in range(1, static_cols + 1):
        cell = ws.cell(row=header_row, column=c)
        cell.alignment = center; cell.border = border_all; cell.fill = gray_fill

    for d in range(1, days_in_month + 1):
        col = static_cols + d
        cell = ws.cell(row=header_row, column=col, value=d)
        cell.font = header_font; cell.alignment = center; cell.border = border_all; cell.fill = gray_fill

    tail_labels = ['D', 'E', 'N', 'O']
    tail_start_col = static_cols + days_in_month + 1 + spacer_cols
    for i, lab in enumerate(tail_labels):
        col = tail_start_col + i
        cell = ws.cell(row=header_row, column=col, value=lab)
        cell.font = header_font; cell.alignment = center; cell.border = border_all; cell.fill = gray_fill

    # 열 너비 조정
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 6
    ws.column_dimensions['C'].width = 6
    ws.column_dimensions['D'].width = 12
    for d in range(1, days_in_month + 1):
        ws.column_dimensions[get_column_letter(static_cols + d)].width = 4
    # spacer 열 너비
    ws.column_dimensions[get_column_letter(static_cols + days_in_month + 1)].width = 3
    for i in range(summary_cols):
        ws.column_dimensions[get_column_letter(tail_start_col + i)].width = 5

    # ───────── 5) 본문: 간호사별 스케줄 ─────────
    start_row = header_row + 1
    daily_counts = {d: {'D': 0, 'E': 0, 'N': 0, 'O': 0} for d in range(1, days_in_month + 1)}

    for idx, n in enumerate(nurses, start=1):
        r = start_row + idx - 1
        # 번호/구분(간단 분류: HN/RN/AN 추정 불가 → RN로 표기)/이름
        ws.cell(row=r, column=1, value=idx)
        ws.cell(row=r, column=2, value="RN")
        ws.cell(row=r, column=3, value=n.experience)
        ws.cell(row=r, column=4, value=n.name)
        for c in range(1, static_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.alignment = center; cell.border = border_all

        # 일자별
        row_counts = {'D': 0, 'E': 0, 'N': 0, 'O': 0}
        schedule_map = by_nurse.get(n.nurse_id, {})
        for d in range(1, days_in_month + 1):
            shift_code = schedule_map.get(d, '-')
            cell = ws.cell(row=r, column=static_cols + d, value=shift_code)
            cell.alignment = center; cell.border = border_all
            base = to_base(shift_code)
            if base in row_counts:
                row_counts[base] += 1
                daily_counts[d][base] += 1

        # 합계(D/E/N/O)
        for i, lab in enumerate(tail_labels):
            col = tail_start_col + i
            cell = ws.cell(row=r, column=col, value=row_counts.get(lab, 0))
            cell.alignment = center; cell.border = border_all

    last_row = start_row + len(nurses) - 1

    # ───────── 6) 일일 근무 현황(풋터) ─────────
    footer_start = last_row + 2
    ws.cell(row=footer_start, column=2, value="일일 근무 현황").font = header_font

    def write_footer_row(label: str, values: list[int], row_idx: int):
        ws.cell(row=row_idx, column=3, value=label).font = header_font
        for c in range(1, static_cols):
            cell = ws.cell(row=row_idx, column=c)
            cell.border = border_all
        # days
        for d in range(1, days_in_month + 1):
            val = values[d - 1]
            cell = ws.cell(row=row_idx, column=static_cols + d, value=val)
            cell.alignment = center; cell.border = border_all
        # spacer + tail 4칸 비움(border 유지)
        for i in range(spacer_cols + summary_cols):
            col = static_cols + days_in_month + 1 + i
            cell = ws.cell(row=row_idx, column=col)
            cell.border = border_all

    d_vals = [daily_counts[d]['D'] for d in range(1, days_in_month + 1)]
    e_vals = [daily_counts[d]['E'] for d in range(1, days_in_month + 1)]
    n_vals = [daily_counts[d]['N'] for d in range(1, days_in_month + 1)]
    o_vals = [daily_counts[d]['O'] for d in range(1, days_in_month + 1)]

    write_footer_row('D', d_vals, footer_start + 1)
    write_footer_row('E', e_vals, footer_start + 2)
    write_footer_row('N', n_vals, footer_start + 3)
    write_footer_row('O', o_vals, footer_start + 4)

    # 테두리/정렬 마감 및 첫 행 스타일 약간 보정
    for row in ws.iter_rows(min_row=header_row, max_row=footer_start + 4, min_col=1, max_col=total_cols):
        for cell in row:
            if cell.value is None:
                continue
            # 이미 지정된 것 외 공통 보더
            if cell.border is None or cell.border.left.style is None:
                cell.border = border_all

    # 바이트로 저장
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read() 