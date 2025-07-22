"""
헬스체크 관련 라우터 모듈
- 서비스 상태, DB 연결, 시스템 리소스 체크 엔드포인트
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.client import get_db
from app.services.health_service import (
    check_database_health_service,
    check_system_health_service,
    check_service_dependencies_service,
    get_comprehensive_health_service
)

router = APIRouter(
    prefix="/health",
    tags=["health"]
)


@router.get("/")
async def health_check():
    """
    기본 헬스체크 엔드포인트
    """
    return {
        "status": "healthy",
        "message": "간호사 근무 관리 시스템이 정상적으로 동작 중입니다.",
        "service": "nurse_rostering"
    }


@router.get("/alb")
async def alb_health_check(db: Session = Depends(get_db)):
    """
    ALB 상태검사를 위한 통합 헬스체크 엔드포인트
    - 간단하고 빠른 응답으로 ALB에서 사용
    """
    try:
        # 데이터베이스 연결 상태만 빠르게 체크
        db_health = check_database_health_service(db)
        
        if db_health["status"] == "healthy":
            return {
                "status": "healthy",
                "message": "서비스가 정상적으로 동작 중입니다.",
                "timestamp": db_health.get("database", {}).get("timestamp", "")
            }
        else:
            raise HTTPException(status_code=503, detail="서비스에 문제가 있습니다.")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"헬스체크 실패: {str(e)}")


@router.get("/simple")
async def simple_health_check():
    """
    간단한 헬스체크 엔드포인트
    - DB 연결 없이 기본적인 서비스 상태만 확인
    """
    return {
        "status": "healthy",
        "message": "간호사 근무 관리 시스템이 정상적으로 동작 중입니다.",
        "service": "nurse_rostering"
    }


@router.get("/database")
async def database_health_check(db: Session = Depends(get_db)):
    """
    데이터베이스 연결 상태 체크 엔드포인트
    """
    try:
        result = check_database_health_service(db)
        if result["status"] == "healthy":
            return result
        else:
            raise HTTPException(status_code=503, detail="데이터베이스 연결에 문제가 있습니다.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 헬스체크 실패: {str(e)}")


@router.get("/system")
async def system_health_check():
    """
    시스템 리소스 상태 체크 엔드포인트
    """
    try:
        result = check_system_health_service()
        if result["status"] == "healthy":
            return result
        else:
            raise HTTPException(status_code=503, detail="시스템 리소스에 문제가 있습니다.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시스템 헬스체크 실패: {str(e)}")


@router.get("/dependencies")
async def dependencies_health_check():
    """
    서비스 의존성 체크 엔드포인트
    """
    try:
        result = check_service_dependencies_service()
        if result["status"] == "healthy":
            return result
        else:
            raise HTTPException(status_code=503, detail="서비스 의존성에 문제가 있습니다.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"의존성 헬스체크 실패: {str(e)}")


@router.get("/comprehensive")
async def comprehensive_health_check(db: Session = Depends(get_db)):
    """
    종합 헬스체크 엔드포인트
    - 데이터베이스, 시스템, 의존성 모든 상태를 한번에 체크
    """
    try:
        result = get_comprehensive_health_service(db)
        if result["status"] == "healthy":
            return result
        else:
            raise HTTPException(status_code=503, detail="서비스에 문제가 있습니다.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"종합 헬스체크 실패: {str(e)}")


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """
    서비스 준비 상태 체크 엔드포인트
    - 로드밸런서나 쿠버네티스에서 사용
    """
    try:
        result = get_comprehensive_health_service(db)
        if result["status"] == "healthy":
            return {
                "status": "ready",
                "message": "서비스가 요청을 처리할 준비가 되었습니다."
            }
        else:
            raise HTTPException(status_code=503, detail="서비스가 준비되지 않았습니다.")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"준비 상태 체크 실패: {str(e)}")


@router.get("/live")
async def liveness_check():
    """
    서비스 생존 상태 체크 엔드포인트
    - 로드밸런서나 쿠버네티스에서 사용
    """
    return {
        "status": "alive",
        "message": "서비스가 정상적으로 동작 중입니다."
    } 