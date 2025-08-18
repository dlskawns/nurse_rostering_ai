"""
간호사 정보 관리 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Nurse as NurseModel
from schemas.roster_schema import NurseProfile
from schemas.auth_schema import User as UserSchema
from typing import List


def get_nurses_in_group_service(current_user, db: Session):
    """
    그룹 내 간호사 목록 조회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    nurses = (
        db.query(NurseModel)
        .filter(NurseModel.group_id == current_user.group_id)
        .order_by(NurseModel.sequence.asc(), NurseModel.experience.desc(), NurseModel.nurse_id.asc())
        .all()
    )
    return nurses

def bulk_update_nurses_service(nurses_data, current_user, db: Session):
    """
    간호사 일괄 업데이트 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    if not current_user.is_head_nurse:
        raise Exception("Permission denied")
    if not any(n.is_head_nurse for n in nurses_data):
        raise Exception("At least one head nurse must be assigned.")
    db_nurses_dict = {n.nurse_id: n for n in db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id).all()}
    for nurse_data in nurses_data:
        db_nurse = db_nurses_dict.get(nurse_data.nurse_id)
        if db_nurse:
            if db_nurse.group_id != current_user.group_id:
                continue
            update_data = nurse_data.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_nurse, key, value)
        else:
            nurse_dict = nurse_data.dict()
            nurse_dict.pop('group_id', None)
            # 신규 생성 시 sequence가 없으면 마지막 다음 번호로 설정
            max_seq = db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id).order_by(NurseModel.sequence.desc()).first()
            next_seq = (max_seq.sequence + 1) if max_seq and max_seq.sequence is not None else 0
            if 'sequence' not in nurse_dict or nurse_dict['sequence'] is None:
                nurse_dict['sequence'] = next_seq
            new_nurse = NurseModel(**nurse_dict, group_id=current_user.group_id)
            db.add(new_nurse)
    client_nurse_ids = {n.nurse_id for n in nurses_data}
    for db_nurse_id, db_nurse in db_nurses_dict.items():
        if db_nurse_id not in client_nurse_ids:
            db.delete(db_nurse)
    db.commit()
    return {"message": "Nurses updated successfully"} 

def move_nurse_service(req, current_user, db: Session):
    """
    간호사 순서 이동 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    if not current_user.is_head_nurse:
        raise Exception("Permission denied")
    nurse_to_move = db.query(NurseModel).filter(NurseModel.nurse_id == req.nurse_id, NurseModel.group_id == current_user.group_id).first()
    old_sequence = nurse_to_move.sequence
    new_sequence = req.new_sequence
    if old_sequence == new_sequence:
        return {"message": "변경사항이 없습니다."}
    if old_sequence < new_sequence:
        db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id, NurseModel.sequence > old_sequence, NurseModel.sequence <= new_sequence).update({"sequence": NurseModel.sequence - 1})
    else:
        db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id, NurseModel.sequence >= new_sequence, NurseModel.sequence < old_sequence).update({"sequence": NurseModel.sequence + 1})
    nurse_to_move.sequence = new_sequence
    db.commit()
    return {"message": "간호사 순서 변경 완료"}