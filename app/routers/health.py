"""
헬스체크 관련 라우터 모듈
- 서비스 상태, DB 연결, 시스템 리소스 체크 엔드포인트
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
- CloudWatch 로깅 기능 포함
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.client import get_db
from services.health_service import (
    check_database_health_service,
    check_system_health_service,
    check_service_dependencies_service,
    get_comprehensive_health_service
)
import logging
import traceback
import json
from datetime import datetime

# CloudWatch 로깅 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 로그 포맷 설정
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 핸들러 설정 (CloudWatch로 전송될 수 있도록)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)


def log_health_endpoint_error(endpoint_name: str, error: Exception, context: dict = None):
    """
    헬스체크 엔드포인트 오류를 CloudWatch에 로깅하는 함수
    """
    error_data = {
        "service": "health_endpoint",
        "endpoint": endpoint_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.now().isoformat(),
        "traceback": traceback.format_exc(),
        "context": context or {}
    }
    
    logger.error(f"헬스체크 엔드포인트 오류 발생: {json.dumps(error_data, ensure_ascii=False)}")
    return error_data


router = APIRouter(
    prefix="/health",
    tags=["health"]
)


@router.get("/basic")
async def health_check():
    """
    기본 헬스체크 엔드포인트
    """
    try:
        logger.info("기본 헬스체크 엔드포인트 호출됨")
        return {
            "status": "healthy",
            "message": "간호사 근무 관리 시스템이 정상적으로 동작 중입니다.",
            "service": "nurse_rostering",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        log_health_endpoint_error("health_check", e)
        raise HTTPException(status_code=500, detail=f"기본 헬스체크 실패: {str(e)}")


@router.get("/alb")
async def alb_health_check(db: Session = Depends(get_db)):
    """
    ALB 상태검사를 위한 통합 헬스체크 엔드포인트
    - 간단하고 빠른 응답으로 ALB에서 사용
    """
    try:
        logger.info("ALB 헬스체크 엔드포인트 호출됨")
        # 데이터베이스 연결 상태만 빠르게 체크
        db_health = check_database_health_service(db)
        
        if db_health["status"] == "healthy":
            logger.info("ALB 헬스체크 성공")
            return {
                "status": "healthy",
                "message": "서비스가 정상적으로 동작 중입니다.",
                "timestamp": db_health.get("database", {}).get("timestamp", "")
            }
        else:
            logger.error(f"ALB 헬스체크 실패: {db_health}")
            raise HTTPException(status_code=503, detail="서비스에 문제가 있습니다.")
    except Exception as e:
        log_health_endpoint_error("alb_health_check", e, {
            "db_health_status": db_health.get("status") if 'db_health' in locals() else "unknown"
        })
        raise HTTPException(status_code=503, detail=f"헬스체크 실패: {str(e)}")


@router.get("/simple")
async def simple_health_check():
    """
    간단한 헬스체크 엔드포인트
    - DB 연결 없이 기본적인 서비스 상태만 확인
    """
    try:
        logger.info("간단한 헬스체크 엔드포인트 호출됨")
        return {
            "status": "healthy",
            "message": "간호사 근무 관리 시스템이 정상적으로 동작 중입니다.",
            "service": "nurse_rostering",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        log_health_endpoint_error("simple_health_check", e)
        raise HTTPException(status_code=500, detail=f"간단한 헬스체크 실패: {str(e)}")


@router.get("/database")
async def database_health_check(db: Session = Depends(get_db)):
    """
    데이터베이스 연결 상태 체크 엔드포인트
    """
    try:
        logger.info("데이터베이스 헬스체크 엔드포인트 호출됨")
        result = check_database_health_service(db)
        if result["status"] == "healthy":
            logger.info("데이터베이스 헬스체크 성공")
            return result
        else:
            logger.error(f"데이터베이스 헬스체크 실패: {result}")
            raise HTTPException(status_code=503, detail="데이터베이스 연결에 문제가 있습니다.")
    except Exception as e:
        log_health_endpoint_error("database_health_check", e)
        raise HTTPException(status_code=500, detail=f"데이터베이스 헬스체크 실패: {str(e)}")


@router.get("/system")
async def system_health_check():
    """
    시스템 리소스 상태 체크 엔드포인트
    """
    try:
        logger.info("시스템 헬스체크 엔드포인트 호출됨")
        result = check_system_health_service()
        if result["status"] == "healthy":
            logger.info("시스템 헬스체크 성공")
            return result
        else:
            logger.error(f"시스템 헬스체크 실패: {result}")
            raise HTTPException(status_code=503, detail="시스템 리소스에 문제가 있습니다.")
    except Exception as e:
        log_health_endpoint_error("system_health_check", e)
        raise HTTPException(status_code=500, detail=f"시스템 헬스체크 실패: {str(e)}")


@router.get("/dependencies")
async def dependencies_health_check():
    """
    서비스 의존성 체크 엔드포인트
    """
    try:
        logger.info("의존성 헬스체크 엔드포인트 호출됨")
        result = check_service_dependencies_service()
        if result["status"] == "healthy":
            logger.info("의존성 헬스체크 성공")
            return result
        else:
            logger.error(f"의존성 헬스체크 실패: {result}")
            raise HTTPException(status_code=503, detail="서비스 의존성에 문제가 있습니다.")
    except Exception as e:
        log_health_endpoint_error("dependencies_health_check", e)
        raise HTTPException(status_code=500, detail=f"의존성 헬스체크 실패: {str(e)}")


@router.get("/comprehensive")
async def comprehensive_health_check(db: Session = Depends(get_db)):
    """
    종합 헬스체크 엔드포인트
    - 데이터베이스, 시스템, 의존성 모든 상태를 한번에 체크
    """
    try:
        logger.info("종합 헬스체크 엔드포인트 호출됨")
        result = get_comprehensive_health_service(db)
        if result["status"] == "healthy":
            logger.info("종합 헬스체크 성공")
            return result
        else:
            logger.error(f"종합 헬스체크 실패: {result}")
            raise HTTPException(status_code=503, detail="서비스에 문제가 있습니다.")
    except Exception as e:
        log_health_endpoint_error("comprehensive_health_check", e)
        raise HTTPException(status_code=500, detail=f"종합 헬스체크 실패: {str(e)}")


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """
    서비스 준비 상태 체크 엔드포인트
    - 로드밸런서나 쿠버네티스에서 사용
    """
    try:
        logger.info("준비 상태 체크 엔드포인트 호출됨")
        result = get_comprehensive_health_service(db)
        if result["status"] == "healthy":
            logger.info("준비 상태 체크 성공")
            return {
                "status": "ready",
                "message": "서비스가 요청을 처리할 준비가 되었습니다.",
                "timestamp": datetime.now().isoformat()
            }
        else:
            logger.error(f"준비 상태 체크 실패: {result}")
            raise HTTPException(status_code=503, detail="서비스가 준비되지 않았습니다.")
    except Exception as e:
        log_health_endpoint_error("readiness_check", e)
        raise HTTPException(status_code=503, detail=f"준비 상태 체크 실패: {str(e)}")


@router.get("/live")
async def liveness_check():
    """
    서비스 생존 상태 체크 엔드포인트
    - 로드밸런서나 쿠버네티스에서 사용
    """
    try:
        logger.info("생존 상태 체크 엔드포인트 호출됨")
        return {
            "status": "alive",
            "message": "서비스가 정상적으로 동작 중입니다.",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        log_health_endpoint_error("liveness_check", e)
        raise HTTPException(status_code=500, detail=f"생존 상태 체크 실패: {str(e)}") 