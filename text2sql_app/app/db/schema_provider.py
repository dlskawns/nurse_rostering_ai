from __future__ import annotations
import os
from sqlalchemy import create_engine, inspect


STATIC_SCHEMA: dict[str, list[str]] = {
    "offices": ["office_id", "name", "address", "contact_number"],
    "groups": ["group_id", "office_id", "group_name"],
    "nurses": [
        "nurse_id", "group_id", "account_id", "name", "experience", "role", "level_",
        "is_head_nurse", "is_night_nurse", "personal_off_adjustment", "preceptor_id",
        "joining_date", "created_at", "updated_at", "resignation_date", "sequence", "active",
    ],
    "schedules": [
        "schedule_id", "office_id", "group_id", "year", "month", "version", "config_id",
        "created_by", "created_at", "updated_at", "status", "dropped",
    ],
    "schedule_entries": [
        "entry_id", "schedule_id", "nurse_id", "work_date", "shift_id"
    ],
    "shifts": [
        "shift_id", "office_id", "group_id", "name", "color", "start_time", "end_time",
        "type", "allday", "auto_schedule", "duration", "sequence",
    ],
    "shift_manage": [
        "office_id", "group_id", "nurse_class", "shift_slot", "main_code", "codes",
        "config_version", "manpower",
    ],
    "shift_preferences": [
        "nurse_id", "year", "month", "created_at", "data", "is_submitted", "submitted_at",
    ],
    "roster_config": [
        "config_id", "config_version", "office_id", "group_id", "day_req", "eve_req",
        "nig_req", "min_exp_per_shift", "req_exp_nurses", "two_offs_per_week",
        "max_nig_per_month", "three_seq_nig", "two_offs_after_three_nig",
        "two_offs_after_two_nig", "banned_day_after_eve", "max_conseq_work", "off_days",
        "shift_priority", "weekend_shift_ratio", "patient_amount", "sequential_offs",
        "even_nights", "created_at", "preceptor_gauge",
    ],
    "wanted": ["group_id", "year", "month", "exp_date", "status", "created_at"],
    "issued_roster": [
        "seq_no", "office_id", "group_id", "nurse_id", "issued_at", "version", "v_name",
        "issue_cmmt", "schedule_id",
    ],
    "roster_analytics": [
        "analytics_id", "schedule_id", "nurse_id", "year", "month",
        "off_satisfaction", "shift_satisfaction", "pair_satisfaction", "overall_satisfaction",
        "total_requests", "satisfied_requests", "off_requests", "satisfied_off_requests",
        "shift_requests", "satisfied_shift_requests", "pair_requests", "satisfied_pair_requests",
        "created_at",
    ],
    "roster_request_details": [
        "detail_id", "analytics_id", "nurse_id", "day", "request_type", "shift_type",
        "pair_type", "nurse_2_id", "satisfied", "preference_score", "created_at",
    ],
}


def reflect_or_static_schema() -> dict[str, list[str]]:
    """DB 접근이 가능하면 스키마를 리플렉션하고, 실패하면 STATIC_SCHEMA를 반환합니다."""
    try:
        host = os.getenv("DB_HOST", "127.0.0.1")
        port = int(os.getenv("DB_PORT", "3306"))
        user = os.getenv("DB_USER", "readonly_user")
        pwd = os.getenv("DB_PASSWORD", "readonly_password")
        db = os.getenv("DB_NAME", "meditong_roster")
        charset = os.getenv("DB_CHARSET", "utf8mb4")
        url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset={charset}"
        engine = create_engine(url)
        insp = inspect(engine)
        tables = insp.get_table_names()
        schema: dict[str, list[str]] = {}
        for t in tables:
            cols = [c["name"] for c in insp.get_columns(t)]
            schema[t] = cols
        return schema or STATIC_SCHEMA
    except Exception:
        return STATIC_SCHEMA


CATEGORY_TO_TABLES: dict[str, list[str]] = {
    # 세부 일정/근무표 관련 질의
    "schedule_details": [
        "schedule_entries", "schedules", "nurses", "offices", "groups", "shifts", "shift_manage", "shift_preferences", "roster_config", "wanted", "issued_roster",
    ],
    # 통계/요약 질의
    "statistics": [
        "schedule_entries","schedules", "roster_analytics", "roster_request_details", "nurses", "groups", "offices", "shifts", "shift_manage", "shift_preferences", "roster_config", "wanted", "issued_roster",
    ],
}


def tables_for_category(category: str) -> list[str]:
    return CATEGORY_TO_TABLES.get(category, list(STATIC_SCHEMA.keys())) 