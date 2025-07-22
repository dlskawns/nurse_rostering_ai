"""
헬스체크 관련 서비스 로직 모듈
- DB 연결 상태, 서비스 상태, 의존성 체크 등
- 모든 함수는 한글 docstring, 한글 print/logging, PEP8 스타일 적용
"""
from sqlalchemy.orm import Session
from app.db.client import get_db
from app.db.models import Nurse, Schedule, ShiftPreference
from datetime import datetime
import psutil
import os


def check_database_health_service(db: Session):
    """
    데이터베이스 연결 상태 체크 서비스 함수
    """
    try:
        # 간단한 쿼리로 DB 연결 상태 확인
        nurse_count = db.query(Nurse).count()
        schedule_count = db.query(Schedule).count()
        preference_count = db.query(ShiftPreference).count()
        
        return {
            "status": "healthy",
            "database": {
                "connection": "ok",
                "nurse_count": nurse_count,
                "schedule_count": schedule_count,
                "preference_count": preference_count
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": {
                "connection": "error",
                "error": str(e)
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
        return {
            "status": "unhealthy",
            "system": {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        }


def check_service_dependencies_service():
    """
    서비스 의존성 체크 서비스 함수
    """
    dependencies = {}
    
    # CP-SAT 엔진 의존성 체크
    try:
        from app.services.cp_sat_basic import generate_roster_cp_sat
        dependencies["cp_sat_basic"] = "available"
    except ImportError:
        dependencies["cp_sat_basic"] = "unavailable"
    
    try:
        from app.services.cp_sat_main_v3 import generate_roster_cp_sat_main_v3
        dependencies["cp_sat_main_v3"] = "available"
    except ImportError:
        dependencies["cp_sat_main_v3"] = "unavailable"
    
    try:
        from app.services.random_sampling import generate_roster
        dependencies["random_sampling"] = "available"
    except ImportError:
        dependencies["random_sampling"] = "unavailable"
    
    try:
        from app.services.graph_service import graph_service
        dependencies["graph_service"] = "available"
    except ImportError:
        dependencies["graph_service"] = "unavailable"
    
    return {
        "status": "healthy",
        "dependencies": dependencies,
        "timestamp": datetime.now().isoformat()
    }


def get_comprehensive_health_service(db: Session):
    """
    종합 헬스체크 서비스 함수
    """
    db_health = check_database_health_service(db)
    system_health = check_system_health_service()
    dependencies_health = check_service_dependencies_service()
    
    # 전체 상태 결정
    overall_status = "healthy"
    if (db_health["status"] == "unhealthy" or 
        system_health["status"] == "unhealthy" or
        dependencies_health["status"] == "unhealthy"):
        overall_status = "unhealthy"
    
    return {
        "status": overall_status,
        "database": db_health.get("database", {}),
        "system": system_health.get("system", {}),
        "dependencies": dependencies_health.get("dependencies", {}),
        "timestamp": datetime.now().isoformat()
    } 