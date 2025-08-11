"""
대시보드 서비스 모듈
- 근무표 만족도 분석 데이터 저장 및 조회
- 개인별 요청 반영률 통계
"""
from sqlalchemy.orm import Session
from db.models import RosterAnalytics, RosterRequestDetails, Schedule, Nurse
from services.roster_system import RosterSystem
from typing import Dict, List, Optional
from datetime import date
import json
from sqlalchemy import inspect

def _check_table_exists(table_name: str, db: Session) -> bool:
    """테이블이 존재하는지 확인합니다."""
    try:
        inspector = inspect(db.bind)
        return table_name in inspector.get_table_names()
    except Exception:
        return False

def save_roster_analytics(
    schedule_id: str,
    roster_system: RosterSystem,
    db: Session
) -> bool:
    """
    근무표 분석 데이터를 DB에 저장합니다.
    
    Args:
        schedule_id: 스케줄 ID
        roster_system: RosterSystem 객체
        db: 데이터베이스 세션
        
    Returns:
        bool: 저장 성공 여부
    """
    try:
        # 테이블이 존재하는지 확인
        if not _check_table_exists('roster_analytics', db):
            print("roster_analytics 테이블이 존재하지 않습니다. 분석 데이터를 저장할 수 없습니다.")
            return False
        
        # 기존 분석 데이터 삭제 (같은 스케줄에 대해)
        db.query(RosterAnalytics).filter(
            RosterAnalytics.schedule_id == schedule_id
        ).delete()
        
        # 개인별 만족도 계산
        individual_satisfaction = roster_system.calculate_individual_satisfaction()
        
        # 상세 요청 분석
        detailed_analysis = roster_system.calculate_detailed_request_analysis()
        
        # 각 간호사별 분석 데이터 저장
        for nurse_id, satisfaction in individual_satisfaction.items():
            analytics = RosterAnalytics(
                schedule_id=schedule_id,
                nurse_id=nurse_id,
                year=roster_system.target_month.year,
                month=roster_system.target_month.month,
                off_satisfaction=satisfaction["off_satisfaction"],
                shift_satisfaction=satisfaction["shift_satisfaction"],
                pair_satisfaction=satisfaction["pair_satisfaction"],
                overall_satisfaction=satisfaction["overall_satisfaction"],
                total_requests=satisfaction["total_requests"],
                satisfied_requests=satisfaction["satisfied_requests"],
                off_requests=satisfaction.get("off_requests", 0),
                satisfied_off_requests=satisfaction.get("satisfied_off_requests", 0),
                shift_requests=satisfaction.get("shift_requests", 0),
                satisfied_shift_requests=satisfaction.get("satisfied_shift_requests", 0),
                pair_requests=satisfaction.get("pair_requests", 0),
                satisfied_pair_requests=satisfaction.get("satisfied_pair_requests", 0)
            )
            db.add(analytics)
            db.flush()  # analytics_id 생성
            
            # 상세 요청 데이터 저장
            for detail in detailed_analysis["request_details"]:
                if detail["nurse_id"] == nurse_id:
                    request_detail = RosterRequestDetails(
                        analytics_id=analytics.analytics_id,
                        nurse_id=nurse_id,
                        day=detail["day"],
                        request_type=detail["request_type"],
                        shift_type=detail.get("shift_type"),
                        pair_type=detail.get("pair_type"),
                        nurse_2_id=detail.get("nurse_2_id") if detail.get("nurse_2_id") else None,
                        satisfied=detail["satisfied"],
                        preference_score=detail["preference_score"]
                    )
                    db.add(request_detail)
        
        db.commit()
        return True
        
    except Exception as e:
        print(f"대시보드 데이터 저장 오류: {str(e)}")
        db.rollback()
        return False

def get_roster_analytics_summary(
    group_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = None
) -> Dict:
    """
    근무표 분석 요약 데이터를 조회합니다.
    
    Args:
        group_id: 그룹 ID
        year: 년도 (선택사항)
        month: 월 (선택사항)
        db: 데이터베이스 세션
        
    Returns:
        Dict: 분석 요약 데이터
    """
    try:
        # 먼저 테이블이 존재하는지 확인
        if not _check_table_exists('roster_analytics', db):
            print("roster_analytics 테이블이 존재하지 않습니다.")
            return {
                "total_nurses": 0,
                "average_satisfaction": 0.0,
                "satisfaction_breakdown": {
                    "off": 0.0,
                    "shift": 0.0,
                    "pair": 0.0
                },
                "request_statistics": {
                    "total_requests": 0,
                    "satisfied_requests": 0,
                    "satisfaction_rate": 0.0
                }
            }
        
        # RosterAnalytics 테이블에 데이터가 있는지 확인
        analytics_count = db.query(RosterAnalytics).count()
        if analytics_count == 0:
            print("RosterAnalytics 테이블에 데이터가 없습니다.")
            return {
                "total_nurses": 0,
                "average_satisfaction": 0.0,
                "satisfaction_breakdown": {
                    "off": 0.0,
                    "shift": 0.0,
                    "pair": 0.0
                },
                "request_statistics": {
                    "total_requests": 0,
                    "satisfied_requests": 0,
                    "satisfaction_rate": 0.0
                }
            }
        
        # 더 안전한 쿼리 사용
        try:
            query = db.query(RosterAnalytics).filter(
                RosterAnalytics.nurse_id.in_(
                    db.query(Nurse.nurse_id).filter(Nurse.group_id == group_id).subquery()
                )
            )
        except Exception as join_error:
            print(f"조인 쿼리 실패, 단순 쿼리로 시도: {join_error}")
            query = db.query(RosterAnalytics)
        
        if year:
            query = query.filter(RosterAnalytics.year == year)
        if month:
            query = query.filter(RosterAnalytics.month == month)
        
        analytics_list = query.all()
        
        if not analytics_list:
            return {
                "total_nurses": 0,
                "average_satisfaction": 0.0,
                "satisfaction_breakdown": {
                    "off": 0.0,
                    "shift": 0.0,
                    "pair": 0.0
                },
                "request_statistics": {
                    "total_requests": 0,
                    "satisfied_requests": 0,
                    "satisfaction_rate": 0.0
                }
            }
        
        # 평균 만족도 계산 (안전한 계산)
        total_off_satisfaction = sum(a.off_satisfaction or 0 for a in analytics_list)
        total_shift_satisfaction = sum(a.shift_satisfaction or 0 for a in analytics_list)
        total_pair_satisfaction = sum(a.pair_satisfaction or 0 for a in analytics_list)
        total_overall_satisfaction = sum(a.overall_satisfaction or 0 for a in analytics_list)
        
        nurse_count = len(analytics_list)
        
        # 요청 통계 계산 (안전한 계산)
        total_requests = sum(a.total_requests or 0 for a in analytics_list)
        satisfied_requests = sum(a.satisfied_requests or 0 for a in analytics_list)
        
        return {
            "total_nurses": nurse_count,
            "average_satisfaction": total_overall_satisfaction / nurse_count if nurse_count > 0 else 0.0,
            "satisfaction_breakdown": {
                "off": total_off_satisfaction / nurse_count if nurse_count > 0 else 0.0,
                "shift": total_shift_satisfaction / nurse_count if nurse_count > 0 else 0.0,
                "pair": total_pair_satisfaction / nurse_count if nurse_count > 0 else 0.0
            },
            "request_statistics": {
                "total_requests": total_requests,
                "satisfied_requests": satisfied_requests,
                "satisfaction_rate": (satisfied_requests / total_requests * 100) if total_requests > 0 else 0.0
            }
        }
        
    except Exception as e:
        print(f"대시보드 요약 데이터 조회 오류: {str(e)}")
        return {
            "total_nurses": 0,
            "average_satisfaction": 0.0,
            "satisfaction_breakdown": {
                "off": 0.0,
                "shift": 0.0,
                "pair": 0.0
            },
            "request_statistics": {
                "total_requests": 0,
                "satisfied_requests": 0,
                "satisfaction_rate": 0.0
            }
        }

def get_individual_analytics(
    group_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = None
) -> List[Dict]:
    """
    개인별 분석 데이터를 조회합니다.
    
    Args:
        group_id: 그룹 ID
        year: 년도 (선택사항)
        month: 월 (선택사항)
        db: 데이터베이스 세션
        
    Returns:
        List[Dict]: 개인별 분석 데이터 리스트
    """
    try:
        # 먼저 테이블이 존재하는지 확인
        if not _check_table_exists('roster_analytics', db):
            print("roster_analytics 테이블이 존재하지 않습니다.")
            return []
        
        # RosterAnalytics 테이블에 데이터가 있는지 확인
        analytics_count = db.query(RosterAnalytics).count()
        if analytics_count == 0:
            print("RosterAnalytics 테이블에 데이터가 없습니다.")
            return []
        
        # 더 안전한 쿼리 사용
        try:
            query = db.query(RosterAnalytics).join(Nurse).filter(
                RosterAnalytics.nurse_id.in_(
                    db.query(Nurse.nurse_id).filter(Nurse.group_id == group_id).subquery()
                )
            )
        except Exception as join_error:
            print(f"조인 쿼리 실패, 단순 쿼리로 시도: {join_error}")
            query = db.query(RosterAnalytics)
        
        if year:
            query = query.filter(RosterAnalytics.year == year)
        if month:
            query = query.filter(RosterAnalytics.month == month)
        
        analytics_list = query.all()
        
        result = []
        for analytics in analytics_list:
            try:
                result.append({
                    "nurse_id": analytics.nurse_id,
                    "nurse_name": getattr(analytics.nurse, 'name', 'Unknown') if hasattr(analytics, 'nurse') and analytics.nurse else 'Unknown',
                    "year": analytics.year,
                    "month": analytics.month,
                    "off_satisfaction": analytics.off_satisfaction or 0.0,
                    "shift_satisfaction": analytics.shift_satisfaction or 0.0,
                    "pair_satisfaction": analytics.pair_satisfaction or 0.0,
                    "overall_satisfaction": analytics.overall_satisfaction or 0.0,
                    "total_requests": analytics.total_requests or 0,
                    "satisfied_requests": analytics.satisfied_requests or 0,
                    "off_requests": analytics.off_requests or 0,
                    "satisfied_off_requests": analytics.satisfied_off_requests or 0,
                    "shift_requests": analytics.shift_requests or 0,
                    "satisfied_shift_requests": analytics.satisfied_shift_requests or 0,
                    "pair_requests": analytics.pair_requests or 0,
                    "satisfied_pair_requests": analytics.satisfied_pair_requests or 0
                })
            except Exception as row_error:
                print(f"행 데이터 처리 오류: {row_error}")
                continue
        
        return result
        
    except Exception as e:
        print(f"개인별 분석 데이터 조회 오류: {str(e)}")
        return []

def get_request_details(
    analytics_id: int,
    db: Session = None
) -> List[Dict]:
    """
    특정 분석의 상세 요청 데이터를 조회합니다.
    
    Args:
        analytics_id: 분석 ID
        db: 데이터베이스 세션
        
    Returns:
        List[Dict]: 상세 요청 데이터 리스트
    """
    try:
        details = db.query(RosterRequestDetails).filter(
            RosterRequestDetails.analytics_id == analytics_id
        ).all()
        
        result = []
        for detail in details:
            result.append({
                "day": detail.day,
                "request_type": detail.request_type,
                "shift_type": detail.shift_type,
                "pair_type": detail.pair_type,
                "nurse_2_id": detail.nurse_2_id if detail.nurse_2_id else None,
                "satisfied": detail.satisfied,
                "preference_score": detail.preference_score
            })
        
        return result
        
    except Exception as e:
        print(f"상세 요청 데이터 조회 오류: {str(e)}")
        return []

def get_monthly_trends(
    group_id: str,
    months: int = 6,
    db: Session = None
) -> List[Dict]:
    """
    월별 만족도 트렌드를 조회합니다.
    
    Args:
        group_id: 그룹 ID
        months: 조회할 월 수
        db: 데이터베이스 세션
        
    Returns:
        List[Dict]: 월별 트렌드 데이터
    """
    print('0804 여기 오긴함')
    try:
        from sqlalchemy import func
        from datetime import datetime
        
        # 먼저 테이블이 존재하는지 확인
        if not _check_table_exists('roster_analytics', db):
            print("roster_analytics 테이블이 존재하지 않습니다.")
            # 빈 데이터 반환
            current_date = datetime.now()
            result = []
            for i in range(months):
                year = current_date.year
                month = current_date.month - i
                if month <= 0:
                    month += 12
                    year -= 1
                
                result.insert(0, {
                    "year": year,
                    "month": month,
                    "avg_satisfaction": 0.0,
                    "avg_off_satisfaction": 0.0,
                    "avg_shift_satisfaction": 0.0,
                    "avg_pair_satisfaction": 0.0,
                    "total_requests": 0,
                    "satisfied_requests": 0,
                    "satisfaction_rate": 0.0
                })
            return result
        
        # RosterAnalytics 테이블에 데이터가 있는지 확인
        analytics_count = db.query(RosterAnalytics).count()
        if analytics_count == 0:
            print("RosterAnalytics 테이블에 데이터가 없습니다.")
            # 빈 데이터 반환
            current_date = datetime.now()
            result = []
            for i in range(months):
                year = current_date.year
                month = current_date.month - i
                if month <= 0:
                    month += 12
                    year -= 1
                
                result.insert(0, {
                    "year": year,
                    "month": month,
                    "avg_satisfaction": 0.0,
                    "avg_off_satisfaction": 0.0,
                    "avg_shift_satisfaction": 0.0,
                    "avg_pair_satisfaction": 0.0,
                    "total_requests": 0,
                    "satisfied_requests": 0,
                    "satisfaction_rate": 0.0
                })
            return result
        
        # 최근 N개월 데이터 조회 (더 안전한 쿼리)
        try:
            trends = db.query(
                RosterAnalytics.year,
                RosterAnalytics.month,
                func.avg(RosterAnalytics.overall_satisfaction).label('avg_satisfaction'),
                func.avg(RosterAnalytics.off_satisfaction).label('avg_off_satisfaction'),
                func.avg(RosterAnalytics.shift_satisfaction).label('avg_shift_satisfaction'),
                func.avg(RosterAnalytics.pair_satisfaction).label('avg_pair_satisfaction'),
                func.sum(RosterAnalytics.total_requests).label('total_requests'),
                func.sum(RosterAnalytics.satisfied_requests).label('satisfied_requests')
            ).filter(
                RosterAnalytics.nurse_id.in_(
                    db.query(Nurse.nurse_id).filter(Nurse.group_id == group_id).subquery()
                )
            ).group_by(
                RosterAnalytics.year,
                RosterAnalytics.month
            ).order_by(
                RosterAnalytics.year.desc(),
                RosterAnalytics.month.desc()
            ).limit(months).all()
        except Exception as join_error:
            print(f"조인 쿼리 실패, 단순 쿼리로 시도: {join_error}")
            # 조인 실패 시 단순 쿼리로 시도
            trends = db.query(
                RosterAnalytics.year,
                RosterAnalytics.month,
                func.avg(RosterAnalytics.overall_satisfaction).label('avg_satisfaction'),
                func.avg(RosterAnalytics.off_satisfaction).label('avg_off_satisfaction'),
                func.avg(RosterAnalytics.shift_satisfaction).label('avg_shift_satisfaction'),
                func.avg(RosterAnalytics.pair_satisfaction).label('avg_pair_satisfaction'),
                func.sum(RosterAnalytics.total_requests).label('total_requests'),
                func.sum(RosterAnalytics.satisfied_requests).label('satisfied_requests')
            ).group_by(
                RosterAnalytics.year,
                RosterAnalytics.month
            ).order_by(
                RosterAnalytics.year.desc(),
                RosterAnalytics.month.desc()
            ).limit(months).all()
        
        result = []
        for trend in trends:
            try:
                result.append({
                    "year": trend.year,
                    "month": trend.month,
                    "avg_satisfaction": float(trend.avg_satisfaction) if trend.avg_satisfaction is not None else 0.0,
                    "avg_off_satisfaction": float(trend.avg_off_satisfaction) if trend.avg_off_satisfaction is not None else 0.0,
                    "avg_shift_satisfaction": float(trend.avg_shift_satisfaction) if trend.avg_shift_satisfaction is not None else 0.0,
                    "avg_pair_satisfaction": float(trend.avg_pair_satisfaction) if trend.avg_pair_satisfaction is not None else 0.0,
                    "total_requests": int(trend.total_requests) if trend.total_requests is not None else 0,
                    "satisfied_requests": int(trend.satisfied_requests) if trend.satisfied_requests is not None else 0,
                    "satisfaction_rate": (int(trend.satisfied_requests) / int(trend.total_requests) * 100) if trend.total_requests and int(trend.total_requests) > 0 else 0.0
                })
            except Exception as row_error:
                print(f"행 데이터 처리 오류: {row_error}")
                continue
        
        # 결과가 없으면 빈 데이터 반환
        if not result:
            current_date = datetime.now()
            for i in range(months):
                year = current_date.year
                month = current_date.month - i
                if month <= 0:
                    month += 12
                    year -= 1
                
                result.insert(0, {
                    "year": year,
                    "month": month,
                    "avg_satisfaction": 0.0,
                    "avg_off_satisfaction": 0.0,
                    "avg_shift_satisfaction": 0.0,
                    "avg_pair_satisfaction": 0.0,
                    "total_requests": 0,
                    "satisfied_requests": 0,
                    "satisfaction_rate": 0.0
                })
        
        return result
        
    except Exception as e:
        print(f"월별 트렌드 조회 오류: {str(e)}")
        # 에러 발생 시 빈 데이터 반환
        current_date = datetime.now()
        result = []
        for i in range(months):
            year = current_date.year
            month = current_date.month - i
            if month <= 0:
                month += 12
                year -= 1
            
            result.insert(0, {
                "year": year,
                "month": month,
                "avg_satisfaction": 0.0,
                "avg_off_satisfaction": 0.0,
                "avg_shift_satisfaction": 0.0,
                "avg_pair_satisfaction": 0.0,
                "total_requests": 0,
                "satisfied_requests": 0,
                "satisfaction_rate": 0.0
            })
        return result 