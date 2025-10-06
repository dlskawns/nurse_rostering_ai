from typing import List, Dict, Any


import os
import datetime as _dt

from db.models import Shift, Nurse, Group, Office, ScheduleEntry
# from db.client2 import _get_mssql_session
from db.client import get_db
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine, func
_MSSQL_SESSION_MAKER: sessionmaker | None = None




def _to_time_str(value: Any) -> str | None:
    """TIME 컬럼값을 HH:MM:SS 문자열로 변환합니다."""
    if value is None:
        return None
    if isinstance(value, _dt.time):
        return value.strftime("%H:%M")
    s = str(value)
    # if len(s) == 5:
    #     return f"{s}:00"
    # print(s)
    return s


def get_shifts_service(current_user, db: Session | None = None) -> List[Dict[str, Any]]:
    """MSSQL 전용 ORM 기반 시프트 조회 서비스.
    - 항상 MSSQL 세션을 사용합니다(파라미터 db 무시).
    - 존재하면 반환, 없으면 기본 4개(O,E,N,D) 생성 후 반환
    - 그룹/오피스 자동 생성 로직은 수행하지 않습니다.
    """
    if not current_user:
        raise Exception("Not authenticated")

    session = get_db()
    try:
        # 1) 조회
        shifts = (
            session.query(Shift)
            .filter(Shift.group_id == current_user.group_id)
            .order_by(Shift.sequence.asc())
            .all()
        )
        if shifts:
            return [
                {
                    "shift_id": s.shift_id,
                    "name": s.name,
                    "color": s.color,
                    "start_time": _to_time_str(s.start_time),
                    "end_time": _to_time_str(s.end_time),
                    "type": s.type,
                    "allday": s.allday,
                    "auto_schedule": s.auto_schedule,
                    "duration": s.duration,
                    "sequence": s.sequence,
                    "default_shift": getattr(s, "default_shift", s.shift_id),
                    "id": getattr(s, "id", None),
                }
                for s in shifts
            ]

        # 2) 기본값 생성 (오피스/그룹은 존재한다고 가정; 없으면 office_id=None로 저장)
        print('기본값 생성')
        office_id = None
        group = session.query(Group).filter(Group.group_id == current_user.group_id).first()
        if group and group.office_id:
            office_id = group.office_id
        elif getattr(current_user, "office_id", None):
            office_id = current_user.office_id
        else:
            nurse = session.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
            if nurse and nurse.group and nurse.group.office_id:
                office_id = nurse.group.office_id

        def _mk(shift_id: str, name: str, color: str, st: str | None, et: str | None, typ: str, allday: int, auto_s: int, dur: int | None, seq: int, default_shift: str) -> Shift:
            return Shift(
                shift_id=shift_id,
                name=name,
                office_id=office_id,
                color=color,
                group_id=current_user.group_id,
                start_time=st,
                end_time=et,
                type=typ,
                allday=allday,
                auto_schedule=auto_s,
                duration=dur,
                sequence=seq,
                default_shift=default_shift,
            )
        print('디폴트')
        defaults = [
            # shift_id, name, color, start, end, type, allday, auto_schedule, duration, sequence, default_shift
            ("O", "Off", "#ffa0d2", None, None, "휴무", 1, 1, None, 4, "O"),
            ("E", "Evening", "#72bfff", "14:00:00", "22:00:00", "근무", 0, 1, None, 2, "E"),
            ("N", "Night", "#bab0f0", "22:00:00", "06:00:00", "근무", 0, 1, None, 3, "N"),
            ("D", "Day", "#59dbd7", "06:00:00", "14:00:00", "근무", 0, 1, None, 1, "D"),
        ]
        for args in defaults:
            session.add(_mk(*args))
        session.commit()

        shifts = (
            session.query(Shift)
            .filter(Shift.group_id == current_user.group_id)
            .order_by(Shift.sequence.asc())
            .all()
        )
        print('들어간다')
        return [
            {
                "shift_id": s.shift_id,
                "name": s.name,
                "color": s.color,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "type": s.type,
                "allday": s.allday,
                "auto_schedule": s.auto_schedule,
                "duration": s.duration,
                "sequence": s.sequence,
                "default_shift": getattr(s, "default_shift", s.shift_id),
                "id": getattr(s, "id", None),
            }
            for s in shifts
        ]
    finally:
        session.close()


def add_shift_service(req, current_user, db: Session | None = None):
    """시프트 등록 서비스(MSSQL)."""
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")

    session = get_db()
    try:
        nurse = session.query(Nurse).filter(Nurse.nurse_id == current_user.nurse_id).first()
        if not nurse or not nurse.group:
            raise Exception("User group information not found")

        existing_shift = session.query(Shift).filter(
            Shift.shift_id == req.shift_id,
            Shift.group_id == current_user.group_id
        ).first()
        if existing_shift:
            raise Exception("이미 존재하는 근무코드입니다.")

        max_sequence = session.query(func.max(Shift.sequence)).filter(
            Shift.group_id == current_user.group_id
        ).scalar() or 0

        new_shift = Shift(
            shift_id=req.shift_id,
            office_id=nurse.group.office_id if nurse.group else None,
            group_id=current_user.group_id,
            name=req.name,
            color=req.color,
            start_time=req.start_time,
            end_time=req.end_time,
            type=req.type,
            duration=req.duration,
            allday=req.allday,
            auto_schedule=req.auto_schedule,
            sequence=max_sequence + 1,
        )
        session.add(new_shift)
        session.commit()
        session.refresh(new_shift)
        return {
            "message": "근무코드가 성공적으로 추가되었습니다.",
            "shift": {
                "shift_id": new_shift.shift_id,
                "name": new_shift.name,
                "color": new_shift.color,
                "sequence": new_shift.sequence,
            }
        }
    finally:
        session.close()


def update_shift_service(req, current_user, db: Session | None = None):
    """시프트 수정 서비스(MSSQL)."""
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")

    session = get_db()
    print('들어옴11')
    try:
        existing_shift = session.query(Shift).filter(
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

        session.commit()
        session.refresh(existing_shift)
        return {
            "message": "근무코드가 성공적으로 수정되었습니다.",
            "shift": {
                "shift_id": existing_shift.shift_id,
                "name": existing_shift.name,
                "color": existing_shift.color,
                "sequence": existing_shift.sequence,
            }
        }
    finally:
        session.close()


def remove_shift_service(req, current_user, db: Session | None = None):
    """시프트 삭제 서비스(MSSQL)."""
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")

    session = get_db()
    try:
        existing_shift = session.query(Shift).filter(
            Shift.shift_id == req.shift_id,
            Shift.group_id == current_user.group_id
        ).first()
        if not existing_shift:
            raise Exception("해당 근무코드를 찾을 수 없습니다.")

        schedule_entries_count = session.query(ScheduleEntry).filter(
            ScheduleEntry.shift_id == req.shift_id
        ).count()
        if schedule_entries_count > 0:
            raise Exception("해당 근무코드는 현재 사용 중이므로 삭제할 수 없습니다.")

        deleted_sequence = existing_shift.sequence
        session.delete(existing_shift)
        session.query(Shift).filter(
            Shift.group_id == current_user.group_id,
            Shift.sequence > deleted_sequence
        ).update({"sequence": Shift.sequence - 1})
        session.commit()
        return {"message": "근무코드가 성공적으로 삭제되었습니다."}
    finally:
        session.close()


def move_shift_service(req, current_user, db: Session | None = None):
    """시프트 순서 이동 서비스(MSSQL)."""
    if not current_user or not current_user.is_head_nurse:
        raise Exception("Permission denied")

    session = get_db()
    try:
        shift_to_move = session.query(Shift).filter(
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
            session.query(Shift).filter(
                Shift.group_id == current_user.group_id,
                Shift.sequence > old_sequence,
                Shift.sequence <= new_sequence
            ).update({"sequence": Shift.sequence - 1})
        else:
            session.query(Shift).filter(
                Shift.group_id == current_user.group_id,
                Shift.sequence >= new_sequence,
                Shift.sequence < old_sequence
            ).update({"sequence": Shift.sequence + 1})
        shift_to_move.sequence = new_sequence
        session.commit()
        return {"message": "근무코드 순서가 성공적으로 변경되었습니다."}
    finally:
        session.close() 