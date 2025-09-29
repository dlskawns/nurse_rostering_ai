"""
근무표 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공, 엔진 호출 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import RosterConfig as RosterConfigModel, Schedule, ShiftPreference, Nurse, ScheduleEntry, Shift, Group, RosterConfig, Wanted, IssuedRoster, ShiftManage
from schemas.roster_schema import RosterConfigCreate, PublishRequest, RosterRequest
from db.roster_config import NurseRosterConfig
from db.nurse_config import Nurse as NurseEngine
from services.roster_system import RosterSystem
from datetime import date, datetime
from sqlalchemy import func
import uuid


def save_roster_config_service(config_data: RosterConfigCreate, user, db: Session):
    """
    근무표 설정 저장 서비스 함수
    """
    try:
        nurse = db.query(Nurse).filter(Nurse.nurse_id == user.nurse_id).first()
        if not nurse or not nurse.group:
            raise Exception("User group information not found")
        # config_version을 사용하여 ShiftManage 조회
        # config_version = config_data.config_version
        # if not config_version:
        #     config_version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
        shift_manages = db.query(ShiftManage).filter(
            ShiftManage.office_id == nurse.group.office_id,
            ShiftManage.group_id == user.group_id,
            ShiftManage.nurse_class == 'RN',
            # ShiftManage.config_version == config_version
        ).all()
        day_req = eve_req = nig_req = 0
        if shift_manages:
            for sm in shift_manages:
                if sm.shift_slot == 1:
                    day_req = sm.manpower or 0
                elif sm.shift_slot == 2:
                    eve_req = sm.manpower or 0
                elif sm.shift_slot == 3:
                    nig_req = sm.manpower or 0
        else:
            day_req = eve_req = nig_req = 3
        config_dict = config_data.model_dump()
        config_dict.update({
            'day_req': day_req,
            'eve_req': eve_req,
            'nig_req': nig_req
        })
        
        ## config_version이 None이면 기본값 설정
        # if not config_dict.get('config_version'):
        #     config_dict['config_version'] = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        db_config = RosterConfigModel(
            **config_dict,
            office_id=user.office_id,
            group_id=user.group_id
        )
        db.add(db_config)
        db.commit()
        db.refresh(db_config)
        return {"message": "Configuration saved successfully"}
    except Exception as e:
        print(f'설정 저장 오류: {str(e)}')
        db.rollback()
        raise

def get_latest_schedule_service(current_user, db: Session):
    """
    최신 스케줄 정보 조회 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    latest_schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.dropped == False
    ).order_by(
        Schedule.year.desc(),
        Schedule.month.desc(),
        Schedule.version.desc()
    ).first()
    if not latest_schedule:
        return None
    return {
        "year": latest_schedule.year,
        "month": latest_schedule.month,
        "version": latest_schedule.version,
        "status": latest_schedule.status,
        "schedule_id": latest_schedule.schedule_id
    }

def get_issued_schedules_service(current_user, db: Session):
    """
    발행된(issued) 모든 스케줄 정보 조회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    
    schedules_query = db.query(Schedule.schedule_id, Schedule.year, Schedule.month).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.status == 'issued',
        Schedule.dropped == False
    ).distinct().order_by(Schedule.year.desc(), Schedule.month.desc()).all()
    schedules = [{"year": r.year, "month": r.month, "schedule_id": r.schedule_id} for r in schedules_query]
    return schedules

def get_schedule_status_service(year: int, month: int, current_user, db: Session):
    """
    특정 월의 스케줄 상태 조회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    if current_user.is_head_nurse:
        schedules = db.query(Schedule).filter(
            Schedule.group_id == current_user.group_id,
            Schedule.year == year,
            Schedule.month == month,
            Schedule.dropped == False
        ).all()
        has_schedules = len(schedules) > 0
        latest_status = schedules[0].status if schedules else None
        return {
            "has_schedules": has_schedules,
            "latest_status": latest_status,
            "schedule_count": len(schedules)
        }
    schedule = db.query(Schedule).filter(
        Schedule.group_id == current_user.group_id,
        Schedule.year == year,
        Schedule.month == month,
        Schedule.dropped == False
    ).order_by(Schedule.version.desc()).first()
    submitted_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == True
    ).order_by(ShiftPreference.submitted_at.desc()).first()
    if submitted_preference:
        return {
            "schedule_status": schedule.status if schedule else None,
            "preference_is_submitted": True,
            "preference_data": submitted_preference.data,
            "has_schedules": schedule is not None,
            "created_at": submitted_preference.created_at,
            "submitted_at": submitted_preference.submitted_at
        }
    draft_preference = db.query(ShiftPreference).filter(
        ShiftPreference.nurse_id == current_user.nurse_id,
        ShiftPreference.year == year,
        ShiftPreference.month == month,
        ShiftPreference.is_submitted == False
    ).order_by(ShiftPreference.created_at.desc()).first()
    if draft_preference:
        return {
            "schedule_status": schedule.status if schedule else None,
            "preference_is_submitted": False,
            "preference_data": draft_preference.data,
            "has_schedules": schedule is not None,
            "created_at": draft_preference.created_at,
            "submitted_at": None
        }
    return {
        "schedule_status": schedule.status if schedule else None,
        "preference_is_submitted": False,
        "preference_data": None,
        "has_schedules": schedule is not None,
        "created_at": None,
        "submitted_at": None
    }

# ... (다른 서비스 함수도 동일하게 분리하여 추가 예정) ... 