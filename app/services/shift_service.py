"""
시프트(근무코드) 관리 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Shift, Nurse
from schemas.auth_schema import User as UserSchema
from sqlalchemy import func
from db.models import ScheduleEntry


def get_shifts_service(current_user, db: Session):
    """
    그룹 내 모든 시프트 정보 조회 서비스 함수

    - 만약 해당 그룹에 시프트가 하나도 없으면, 기본 4개 시프트(O/E/N/D)를
      현재 사용자의 office_id, group_id 로 DB에 생성한 뒤 반환합니다.
    """
    if not current_user:
        raise Exception("Not authenticated")
    
    shifts = db.query(Shift).filter(Shift.group_id == current_user.group_id).order_by(Shift.sequence.asc()).all()
    if shifts:
        return [
            {
                "shift_id": shift.shift_id,
                "name": shift.name,
                "color": shift.color,
                "start_time": shift.start_time,
                "end_time": shift.end_time,
                "type": shift.type,
                "allday": shift.allday,
                "auto_schedule": shift.auto_schedule,
                "duration": shift.duration,
                "sequence": shift.sequence,
                "default_shift" : shift.default_shift,
                "id": shift.id,
                # time_display는 라우터에서 포맷팅 함수로 처리할 수 있음
            }
            for shift in shifts
        ]
    else:
        # 기본 시프트 자동 생성
        nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
        if not nurse or not nurse.group:
            raise Exception("User group information not found")
        office_id = nurse.group.office_id
        group_id = current_user.group_id

        def _hhmm(t: str | None) -> str | None:
            """HH:MM:SS → HH:MM 포맷으로 보정."""
            if not t:
                return None
            if len(t) >= 5 and ":" in t:
                parts = t.split(":")
                if len(parts) >= 2:
                    return f"{parts[0]}:{parts[1]}"
            return t

        defaults = [
            # shift_id, name, color, start, end, type, allday, auto_schedule, duration, sequence
            ("O", "Off", "#ffa0d2", None, None, "휴무", 1, 1, None, 4, "O"),
            ("E", "Evening", "#72bfff", "14:00:00", "22:00:00", "근무", 0, 1, None, 2, "E"),
            ("N", "Night", "#bab0f0", "22:00:00", "06:00:00", "근무", 0, 1, None, 3, "N"),
            ("D", "Day", "#59dbd7", "06:00:00", "14:00:00", "근무", 0, 1, None, 1, "D"),
        ]

        created = []
        for sid, name, color, st, et, typ, allday, auto_s, dur, seq, default_shift in defaults:
            new_shift = Shift(
                shift_id=sid,
                office_id=office_id,
                group_id=group_id,
                name=name,
                color=color,
                start_time=_hhmm(st),
                end_time=_hhmm(et),
                type=typ,
                allday=allday,
                auto_schedule=auto_s,
                duration=dur,
                sequence=seq,
                default_shift=default_shift,
            )
            db.add(new_shift)
            created.append(new_shift)
        db.commit()
        # 정렬된 결과 반환
        created_sorted = db.query(Shift).filter(Shift.group_id == group_id).order_by(Shift.sequence.asc()).all()
        return [
            {
                "shift_id": shift.shift_id,
                "name": shift.name,
                "color": shift.color,
                "start_time": shift.start_time,
                "end_time": shift.end_time,
                "type": shift.type,
                "allday": shift.allday,
                "auto_schedule": shift.auto_schedule,
                "duration": shift.duration,
                "sequence": shift.sequence,
                "default_shift": shift.default_shift,
            }
            for shift in created_sorted
        ]


def add_shift_service(req, current_user, db):
    """
    시프트 등록 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    nurse = db.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
    if not nurse or not nurse.group:
        raise Exception("User group information not found")
    existing_shift = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    if existing_shift:
        raise Exception("이미 존재하는 근무코드입니다.")
    max_sequence = db.query(func.max(Shift.sequence)).filter(
        Shift.group_id == current_user.group_id
    ).scalar() or 0
    new_shift = Shift(
        shift_id=req.shift_id,
        office_id=nurse.group.office_id,
        group_id=current_user.group_id,
        name=req.name,
        color=req.color,
        start_time=req.start_time,
        end_time=req.end_time,
        type=req.type,
        duration=req.duration,
        allday=req.allday,
        auto_schedule=req.auto_schedule,
        sequence=max_sequence + 1
    )
    db.add(new_shift)
    db.commit()
    db.refresh(new_shift)
    return {
        "message": "근무코드가 성공적으로 추가되었습니다.",
        "shift": {
            "shift_id": new_shift.shift_id,
            "name": new_shift.name,
            "color": new_shift.color,
            "sequence": new_shift.sequence,
        }
    }


def update_shift_service(req, current_user, db):
    """
    시프트 수정 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    print('req! ', req)

    existing_shift = db.query(Shift).filter(
        Shift.id == req.id,
        Shift.group_id == current_user.group_id
    ).first()
    
    if not existing_shift:
        raise Exception("해당 근무코드를 찾을 수 없습니다.")
    existing_shift.shift_id = req.shift_id
    existing_shift.name = req.name
    existing_shift.color = req.color
    existing_shift.start_time = req.start_time
    existing_shift.end_time = req.end_time
    existing_shift.type = req.type
    existing_shift.duration = req.duration
    existing_shift.allday = req.allday
    existing_shift.auto_schedule = req.auto_schedule

    db.commit()
    db.refresh(existing_shift)
    return {
        "message": "근무코드가 성공적으로 수정되었습니다.",
        "shift": {
            "shift_id": existing_shift.shift_id,
            "name": existing_shift.name,
            "color": existing_shift.color,
            "sequence": existing_shift.sequence,
        }
    }


def remove_shift_service(req, current_user, db):
    """
    시프트 삭제 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    existing_shift = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    if not existing_shift:
        raise Exception("해당 근무코드를 찾을 수 없습니다.")
    schedule_entries_count = db.query(ScheduleEntry).filter(
        ScheduleEntry.shift_id == req.shift_id
    ).count()
    if schedule_entries_count > 0:
        raise Exception("해당 근무코드는 현재 사용 중이므로 삭제할 수 없습니다.")
    deleted_sequence = existing_shift.sequence
    db.delete(existing_shift)
    db.query(Shift).filter(
        Shift.group_id == current_user.group_id,
        Shift.sequence > deleted_sequence
    ).update({"sequence": Shift.sequence - 1})
    db.commit()
    return {"message": "근무코드가 성공적으로 삭제되었습니다."}


def move_shift_service(req, current_user, db):
    """
    시프트 순서 이동 서비스 함수
    """
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")
    shift_to_move = db.query(Shift).filter(
        Shift.shift_id == req.shift_id,
        Shift.group_id == current_user.group_id
    ).first()
    if not shift_to_move:
        raise Exception("해당 근무코드를 찾을 수 없습니다.")
    old_sequence = shift_to_move.sequence
    new_sequence = req.new_sequence
    if old_sequence == new_sequence:
        return {"message": "변경사항이 없습니다."}
    if old_sequence < new_sequence:
        db.query(Shift).filter(
            Shift.group_id == current_user.group_id,
            Shift.sequence > old_sequence,
            Shift.sequence <= new_sequence
        ).update({"sequence": Shift.sequence - 1})
    else:
        db.query(Shift).filter(
            Shift.group_id == current_user.group_id,
            Shift.sequence >= new_sequence,
            Shift.sequence < old_sequence
        ).update({"sequence": Shift.sequence + 1})
    shift_to_move.sequence = new_sequence
    db.commit()
    return {"message": "근무코드 순서가 성공적으로 변경되었습니다."} 