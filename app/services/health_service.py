"""
헬스체크 관련 서비스 로직 모듈
- DB 연결 상태, 서비스 상태, 의존성 체크 등
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
- CloudWatch 로깅 기능 포함
"""
from sqlalchemy.orm import Session
from db.client import get_db
from db.models import Nurse, Schedule, ShiftPreference
from datetime import datetime
import psutil
import os
import logging
import traceback
import json

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


def log_health_error(service_name: str, error: Exception, context: dict = None):
    """
    헬스체크 오류를 CloudWatch에 로깅하는 함수
    """
    error_data = {
        "service": "health_check",
        "component": service_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.now().isoformat(),
        "traceback": traceback.format_exc(),
        "context": context or {}
    }
    
    logger.error(f"헬스체크 오류 발생: {json.dumps(error_data, ensure_ascii=False)}")
    return error_data


def check_database_health_service(db: Session):
    """
    데이터베이스 연결 상태 체크 서비스 함수
    """
    try:
        # 간단한 쿼리로 DB 연결 상태 확인
        nurse_count = db.query(Nurse).count()
        schedule_count = db.query(Schedule).count()
        preference_count = db.query(ShiftPreference).count()
        
        logger.info(f"데이터베이스 헬스체크 성공: nurse_count={nurse_count}, schedule_count={schedule_count}, preference_count={preference_count}")
        
        return {
            "status": "healthy",
            "database": {
                "connection": "ok",
                "nurse_count": nurse_count,
                "schedule_count": schedule_count,
                "preference_count": preference_count,
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        error_data = log_health_error("database", e, {
            "operation": "health_check",
            "db_session": "active" if db else "inactive"
        })
        return {
            "status": "unhealthy",
            "database": {
                "connection": "error",
                "error": str(e),
                "error_details": error_data,
                "timestamp": datetime.now().isoformat()
            }
        }


def check_system_health_service():
    """
    시스템 리소스 상태 체크 서비스 함수
    """
    try:
        # CPU 사용률
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 메모리 사용률
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # 디스크 사용률
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        
        # 프로세스 정보
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        logger.info(f"시스템 헬스체크 성공: cpu={cpu_percent}%, memory={memory_percent}%, disk={disk_percent}%, process_memory={process_memory:.2f}MB")
        
        return {
            "status": "healthy",
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "disk_percent": disk_percent,
                "process_memory_mb": round(process_memory, 2),
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        error_data = log_health_error("system", e, {
            "operation": "system_health_check",
            "psutil_available": "psutil" in globals()
        })
        return {
            "status": "unhealthy",
            "system": {
                "error": str(e),
                "error_details": error_data,
                "timestamp": datetime.now().isoformat()
            }
        }


def check_service_dependencies_service():
    """
    서비스 의존성 체크 서비스 함수
    """
    dependencies = {}
    errors = []
    
    # CP-SAT 엔진 의존성 체크
    try:
        from app.services.cp_sat_basic import generate_roster_cp_sat
        dependencies["cp_sat_basic"] = "available"
        logger.info("CP-SAT Basic 엔진 의존성 체크 성공")
    except ImportError as e:
        dependencies["cp_sat_basic"] = "unavailable"
        errors.append(f"cp_sat_basic: {str(e)}")
        logger.warning(f"CP-SAT Basic 엔진 의존성 체크 실패: {str(e)}")
    
    try:
        from app.services.cp_sat_main_v3 import generate_roster_cp_sat_main_v3
        dependencies["cp_sat_main_v3"] = "available"
        logger.info("CP-SAT Main V3 엔진 의존성 체크 성공")
    except ImportError as e:
        dependencies["cp_sat_main_v3"] = "unavailable"
        errors.append(f"cp_sat_main_v3: {str(e)}")
        logger.warning(f"CP-SAT Main V3 엔진 의존성 체크 실패: {str(e)}")
    
    try:
        from app.services.random_sampling import generate_roster
        dependencies["random_sampling"] = "available"
        logger.info("Random Sampling 엔진 의존성 체크 성공")
    except ImportError as e:
        dependencies["random_sampling"] = "unavailable"
        errors.append(f"random_sampling: {str(e)}")
        logger.warning(f"Random Sampling 엔진 의존성 체크 실패: {str(e)}")
    
    try:
        from app.services.graph_service import graph_service
        dependencies["graph_service"] = "available"
        logger.info("Graph Service 의존성 체크 성공")
    except ImportError as e:
        dependencies["graph_service"] = "unavailable"
        errors.append(f"graph_service: {str(e)}")
        logger.warning(f"Graph Service 의존성 체크 실패: {str(e)}")
    
    # 전체 상태 결정
    status = "healthy" if not errors else "unhealthy"
    
    if errors:
        error_data = log_health_error("dependencies", Exception("의존성 체크 실패"), {
            "failed_dependencies": errors,
            "available_dependencies": [k for k, v in dependencies.items() if v == "available"]
        })
    
    return {
        "status": status,
        "dependencies": dependencies,
        "errors": errors if errors else None,
        "timestamp": datetime.now().isoformat()
    }


def get_comprehensive_health_service(db: Session):
    """
    종합 헬스체크 서비스 함수
    """
    try:
        db_health = check_database_health_service(db)
        system_health = check_system_health_service()
        dependencies_health = check_service_dependencies_service()
        
        # 전체 상태 결정
        overall_status = "healthy"
        if (db_health["status"] == "unhealthy" or 
            system_health["status"] == "unhealthy" or
            dependencies_health["status"] == "unhealthy"):
            overall_status = "unhealthy"
        
        logger.info(f"종합 헬스체크 완료: status={overall_status}, db={db_health['status']}, system={system_health['status']}, dependencies={dependencies_health['status']}")
        
        return {
            "status": overall_status,
            "database": db_health.get("database", {}),
            "system": system_health.get("system", {}),
            "dependencies": dependencies_health.get("dependencies", {}),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        error_data = log_health_error("comprehensive", e, {
            "operation": "comprehensive_health_check"
        })
        return {
            "status": "unhealthy",
            "error": str(e),
            "error_details": error_data,
            "timestamp": datetime.now().isoformat()
        } 