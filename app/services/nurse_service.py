"""
간호사 정보 관리 관련 서비스 로직 모듈
- DB 쿼리, 데이터 가공 등 라우터에서 분리
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from db.models import Nurse as NurseModel
from schemas.roster_schema import NurseProfile
from schemas.auth_schema import User as UserSchema
from typing import List, Optional
from pprint import pprint

def get_personnel_basic_info_service(current_user, db: Session):
    """
    간호사 기본 정보 조회 서비스 함수
    """

    try:
        if not current_user:
            raise Exception("Not authenticated")

        nurse = (
            db.query(NurseModel)
            .filter(NurseModel.group_id == current_user.group_id, NurseModel.nurse_id == current_user.nurse_id)
            .first()
        )
        return nurse
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"간호사 기본 정보 조회 실패: {str(e)}")

def get_nurses_in_group_service(current_user, db: Session):
    """
    그룹 내 간호사 목록 조회 서비스 함수
    """
    if not current_user:
        raise Exception("Not authenticated")
    nurses = (
        db.query(NurseModel)
        .filter(NurseModel.group_id == current_user.group_id)
        .order_by(NurseModel.active.desc(), NurseModel.sequence.asc(), NurseModel.experience.desc(), NurseModel.nurse_id.asc())
        .all()
    )
    return nurses



def get_next_sequence_for_active_status(group_id: str, active_status: int, db: Session) -> int:
    """
    특정 active 상태(활성/비활성)에서 다음 sequence 번호 반환
    """
    max_sequence = db.query(NurseModel.sequence).filter(
        NurseModel.group_id == group_id,
        NurseModel.active == active_status
    ).order_by(NurseModel.sequence.desc()).first()
    
    return (max_sequence[0] + 1) if max_sequence and max_sequence[0] is not None else 1

def _get_nurses_by_active(group_id: str, active_status: int, db: Session) -> List[NurseModel]:
    return (
        db.query(NurseModel)
        .filter(NurseModel.group_id == group_id, NurseModel.active == active_status)
        .order_by(NurseModel.sequence.asc(), NurseModel.nurse_id.asc())
        .all()
    )

def _reindex_contiguously(nurses: List[NurseModel]) -> None:
    """sequence를 1부터 연속되게 재부여"""
    for idx, n in enumerate(nurses, start=1):
        if n.sequence != idx:
            n.sequence = idx

def move_nurse_with_active_service(nurse_id: str, new_sequence: int, target_active: Optional[int], current_user, db: Session):
    """
    간호사 이동/상태변경을 단일 트랜잭션으로 처리.
    - target_active가 None이면 같은 active 안에서 재배치
    - target_active가 0/1이면 해당 상태 리스트로 이동 후 삽입
    """
    if not current_user:
        raise Exception("Not authenticated")
    if not current_user.is_head_nurse:
        raise Exception("Permission denied")

    nurse = (
        db.query(NurseModel)
        .filter(NurseModel.group_id == current_user.group_id, NurseModel.nurse_id == nurse_id)
        .first()
    )
    if not nurse:
        raise Exception("간호사를 찾을 수 없습니다.")

    group_id = current_user.group_id
    old_active = nurse.active

    if target_active is None or target_active == old_active:
        # 같은 상태 내 재배치
        lst = _get_nurses_by_active(group_id, old_active, db)
        # 해당 간호사 제외
        lst = [n for n in lst if n.nurse_id != nurse.nurse_id]
        # 경계 보정 (1-based)
        insert_idx = max(0, min(new_sequence - 1, len(lst)))
        lst.insert(insert_idx, nurse)
        _reindex_contiguously(lst)
    else:
        # 상태 변경: 기존 리스트에서 제거하고 reindex
        old_list = _get_nurses_by_active(group_id, old_active, db)
        old_list = [n for n in old_list if n.nurse_id != nurse.nurse_id]
        _reindex_contiguously(old_list)

        # 새 리스트로 이동하여 삽입
        nurse.active = target_active
        new_list = _get_nurses_by_active(group_id, target_active, db)
        insert_idx = max(0, min(new_sequence - 1, len(new_list)))
        new_list.insert(insert_idx, nurse)
        _reindex_contiguously(new_list)

    db.commit()
    return {"message": "순서/상태 변경 완료"}

def reorder_nurses_service(active_order: List[str], inactive_order: List[str], current_user, db: Session):
    """
    드래그앤드롭 완료 시점에 한 번 호출하여
    - active_order에 포함된 간호사들은 active=1로 설정하고 순서를 1..N 부여
    - inactive_order는 active=0으로 설정하고 순서를 1..M 부여
    - 전달되지 않은 간호사는 상태/순서 변경하지 않음(React 측에서 전체 보냄을 권장)
    """
    if not current_user:
        raise Exception("Not authenticated")
    if not current_user.is_head_nurse:
        raise Exception("Permission denied")

    group_id = current_user.group_id
    id_to_nurse = {
        n.nurse_id: n
        for n in db.query(NurseModel).filter(NurseModel.group_id == group_id).all()
    }

    # 활성 정렬 적용
    for idx, nid in enumerate(active_order, start=1):
        n = id_to_nurse.get(nid)
        if not n:
            continue
        n.active = 1
        n.sequence = idx

    # 비활성 정렬 적용
    for idx, nid in enumerate(inactive_order, start=1):
        n = id_to_nurse.get(nid)
        if not n:
            continue
        n.active = 0
        n.sequence = idx

    db.commit()
    return {"message": "일괄 재정렬 완료", "active_count": len(active_order), "inactive_count": len(inactive_order)}

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
    print(f"[DEBUG] nurses_data:")
    pprint(nurses_data)
    db_nurses_dict = {n.nurse_id: n for n in db.query(NurseModel).filter(NurseModel.group_id == current_user.group_id).all()}
    
    for nurse_data in nurses_data:
        db_nurse = db_nurses_dict.get(nurse_data.nurse_id)
        if db_nurse:
            if db_nurse.group_id != current_user.group_id:
                continue
            
            # active 상태가 변경되는 경우 sequence 재조정
            old_active = db_nurse.active
            update_data = nurse_data.dict(exclude_unset=True)
            new_active = update_data.get('active', old_active)
            
            # active 상태 변경 시 해당 상태의 마지막 sequence로 이동
            if old_active != new_active and 'active' in update_data:
                update_data['sequence'] = get_next_sequence_for_active_status(
                    current_user.group_id, new_active, db
                )
                print(f"[DEBUG] 간호사 {db_nurse.name} active 변경: {old_active} → {new_active}, sequence: {update_data['sequence']}")
            
            for key, value in update_data.items():
                setattr(db_nurse, key, value)
        else:
            nurse_dict = nurse_data.dict()
            nurse_dict.pop('group_id', None)
            
            # 신규 생성 시 active 상태에 따른 sequence 설정
            active_status = nurse_dict.get('active', 1)  # 기본값은 활성(1)
            if 'sequence' not in nurse_dict or nurse_dict['sequence'] is None:
                nurse_dict['sequence'] = get_next_sequence_for_active_status(
                    current_user.group_id, active_status, db
                )
                print(f"[DEBUG] 신규 간호사 sequence 설정: active={active_status}, sequence={nurse_dict['sequence']}")
            
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
    간호사 순서 이동 서비스 함수 (같은 active 상태 내에서만 이동)
    """
    if not current_user:
        raise Exception("Not authenticated")
    if not current_user.is_head_nurse:
        raise Exception("Permission denied")
    
    nurse_to_move = db.query(NurseModel).filter(
        NurseModel.nurse_id == req.nurse_id, 
        NurseModel.group_id == current_user.group_id
    ).first()
    
    if not nurse_to_move:
        raise Exception("해당 간호사를 찾을 수 없습니다.")
    
    old_sequence = nurse_to_move.sequence
    new_sequence = req.new_sequence
    active_status = nurse_to_move.active
    
    print(f"[DEBUG] 순서 이동: {nurse_to_move.name} (active={active_status}) {old_sequence} → {new_sequence}")
    
    if old_sequence == new_sequence:
        return {"message": "변경사항이 없습니다."}
    
    # 같은 active 상태의 간호사들만 대상으로 sequence 재조정
    if old_sequence < new_sequence:
        # 위로 이동: 기존 위치와 새 위치 사이의 간호사들을 앞으로 이동
        affected_nurses = db.query(NurseModel).filter(
            NurseModel.group_id == current_user.group_id,
            NurseModel.active == active_status,
            NurseModel.sequence > old_sequence,
            NurseModel.sequence <= new_sequence
        ).all()
        
        for nurse in affected_nurses:
            nurse.sequence -= 1
            print(f"[DEBUG] {nurse.name} sequence: {nurse.sequence + 1} → {nurse.sequence}")
    else:
        # 아래로 이동: 새 위치와 기존 위치 사이의 간호사들을 뒤로 이동
        affected_nurses = db.query(NurseModel).filter(
            NurseModel.group_id == current_user.group_id,
            NurseModel.active == active_status,
            NurseModel.sequence >= new_sequence,
            NurseModel.sequence < old_sequence
        ).all()
        
        for nurse in affected_nurses:
            nurse.sequence += 1
            print(f"[DEBUG] {nurse.name} sequence: {nurse.sequence - 1} → {nurse.sequence}")
    
    # 이동할 간호사의 sequence 업데이트
    nurse_to_move.sequence = new_sequence
    print(f"[DEBUG] {nurse_to_move.name} 최종 sequence: {new_sequence}")
    
    db.commit()
    return {"message": "간호사 순서 변경 완료"}