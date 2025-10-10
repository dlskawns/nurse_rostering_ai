from sqlalchemy import Column, VARCHAR, SMALLINT, BOOLEAN, DATETIME, func, ForeignKey, JSON, CHAR, INTEGER, FLOAT, Index
from sqlalchemy.dialects.mysql import TINYINT 
from sqlalchemy.orm import relationship
from db.client import Base
from sqlalchemy import DATE, DECIMAL, TEXT

class Group(Base):
    __tablename__ = 'groups'
    group_id = Column(VARCHAR(50), primary_key=True)
    office_id = Column(VARCHAR(50), ForeignKey('offices.office_id'))
    group_name = Column(VARCHAR(50), nullable=False)
    office = relationship("Office", back_populates="groups") 
class Office(Base):
    __tablename__ = 'offices'
    office_id = Column(VARCHAR(50), primary_key=True)
    name = Column(VARCHAR(100), nullable=False)
    address = Column(VARCHAR(255))
    contact_number = Column(VARCHAR(30))
    groups = relationship("Group", back_populates="office") 
class Nurse(Base):
    __tablename__ = "nurses"

    nurse_id = Column(VARCHAR(50), primary_key=True)
    group_id = Column(VARCHAR(50), ForeignKey("groups.group_id"))
    account_id = Column(VARCHAR(50), unique=True, nullable=False)
    name = Column(VARCHAR(50), nullable=False)
    experience = Column(SMALLINT)
    role = Column(VARCHAR(20))
    level_ = Column(VARCHAR(20))
    is_head_nurse = Column(BOOLEAN, default=False)
    is_night_nurse = Column(SMALLINT, default=0)
    personal_off_adjustment = Column(TINYINT, default=0)
    preceptor_id = Column(VARCHAR(50), ForeignKey("nurses.nurse_id"))
    joining_date = Column(DATETIME, nullable=True)
    created_at = Column(DATETIME, default=func.now())
    updated_at = Column(DATETIME, default=func.now(), onupdate=func.now())
    resignation_date = Column(DATETIME, nullable=True)
    # 화면 표시 및 알고리즘 입력 순서 제어용
    sequence = Column(INTEGER, nullable=False, default=0)
    active = Column(INTEGER, default=1)
    group = relationship("Group")

    @property
    def office_id(self) -> str | None:
        return self.group.office_id if self.group else None 
class Schedule(Base):
    __tablename__ = "schedules"
    schedule_id = Column(CHAR(12), primary_key=True)
    office_id = Column(VARCHAR(50), ForeignKey("offices.office_id"))
    group_id = Column(VARCHAR(50), ForeignKey("groups.group_id"))
    year = Column(SMALLINT, nullable=False)
    month = Column(TINYINT, nullable=False)
    version = Column(TINYINT, nullable=False)
    config_id = Column(INTEGER, ForeignKey("roster_config.config_id"))
    created_by = Column(VARCHAR(50), ForeignKey("nurses.account_id"))
    created_at = Column(DATETIME, default=func.now())
    updated_at = Column(DATETIME, default=func.now(), onupdate=func.now())
    status = Column(VARCHAR(10)) # e.g., 'requested', 'issued'
    dropped = Column(BOOLEAN, nullable=False, default=False)
    name = Column(VARCHAR(50))
    # violations = Column(JSON, nullable=True) # 임시로 주석 처리 - DB 스키마 업데이트 후 활성화 예정

    roster_config = relationship("RosterConfig")

class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"
    entry_id = Column(VARCHAR(16), primary_key=True)
    schedule_id = Column(CHAR(12), ForeignKey("schedules.schedule_id"))
    nurse_id = Column(VARCHAR(50), ForeignKey("nurses.nurse_id"))
    work_date = Column(DATETIME, nullable=False)
    shift_id = Column(VARCHAR(10), ForeignKey("shifts.shift_id")) # D, E, N, O, etc.

class Shift(Base):
    __tablename__ = "shifts"
    shift_id = Column(VARCHAR(10), primary_key=True)
    office_id = Column(VARCHAR(50), ForeignKey("offices.office_id"))
    group_id = Column(VARCHAR(50), ForeignKey("groups.group_id"))
    name = Column(VARCHAR(20), nullable=False)
    color = Column(VARCHAR(10), nullable=False)
    start_time = Column(VARCHAR(5), nullable=True)  # HH:MM format
    end_time = Column(VARCHAR(5), nullable=True)    # HH:MM format
    type = Column(VARCHAR(10), nullable=False, default='근무')  # 'work' or 'off'
    allday = Column(INTEGER, nullable=False, default=0)
    auto_schedule = Column(INTEGER, nullable=False, default=1)
    # time_type = Column(VARCHAR(10), nullable=False, default='range')  # 'range', 'allday', 'hours'
    duration = Column(INTEGER, nullable=True)  # for time_type='hours'
    sequence = Column(INTEGER, nullable=False, default=0)  # 순서 관리용
    default_shift = Column(VARCHAR(10), nullable=True)  # 기본 근무코드
    id = Column(INTEGER, primary_key=True, nullable=False, autoincrement=True)

    office = relationship("Office")
    group = relationship("Group")

class ShiftManage(Base):
    __tablename__ = "shift_manage"
    # ── 복합 PRIMARY KEY ──────────────────────────────
    office_id  = Column(VARCHAR(50), ForeignKey("offices.office_id"), primary_key=True)
    group_id   = Column(VARCHAR(50), ForeignKey("groups.group_id"), primary_key=True)
    nurse_class = Column(VARCHAR(10), nullable=False)  # 'RN', 'AN', '보조'
    shift_slot = Column(INTEGER, nullable=False, primary_key=True)  # 슬롯 번호 (1, 2, 3...)
    main_code = Column(VARCHAR(10), nullable=True)  # 메인 근무코드 (하나만)
    codes = Column(JSON, nullable=True)  # 근무코드 리스트 ['D', 'E', 'N']
    # config_version = Column(VARCHAR(20), primary_key=True)
    manpower = Column(INTEGER, nullable=False, default=0)  # 인력 수

    office = relationship("Office")
    group = relationship("Group")

class ShiftPreference(Base):
    __tablename__ = "shift_preferences"
    nurse_id = Column(VARCHAR(50), ForeignKey("nurses.nurse_id"), primary_key=True)
    year = Column(SMALLINT, primary_key=True)
    month = Column(TINYINT, primary_key=True)
    created_at = Column(DATETIME, primary_key=True)
    data = Column(JSON, nullable=False)
    is_submitted = Column(BOOLEAN, nullable=False, default=False)
    submitted_at = Column(DATETIME, nullable=True)
    
    # # 복합 인덱스 추가 (성능 향상)
    # __table_args__ = (
    #     Index('idx_nurse_year_month_created', 'nurse_id', 'year', 'month', 'created_at'),
    # )

class RosterConfig(Base):
    __tablename__ = 'roster_config'
    config_id = Column(INTEGER, primary_key=True, autoincrement=True)
    config_version = Column(VARCHAR(20))
    office_id = Column(VARCHAR(50), ForeignKey('offices.office_id'))
    group_id = Column(VARCHAR(50), ForeignKey('groups.group_id'))
    day_req = Column(INTEGER)
    eve_req = Column(INTEGER)
    nig_req = Column(INTEGER)
    min_exp_per_shift = Column(INTEGER)
    req_exp_nurses = Column(INTEGER)
    two_offs_per_week = Column(BOOLEAN)
    max_nig_per_month = Column(INTEGER)
    three_seq_nig = Column(BOOLEAN)
    two_offs_after_three_nig = Column(BOOLEAN)
    two_offs_after_two_nig = Column(BOOLEAN)
    banned_day_after_eve = Column(BOOLEAN)
    max_conseq_work = Column(INTEGER)
    off_days = Column(INTEGER)
    shift_priority = Column(FLOAT)
    weekend_shift_ratio = Column(FLOAT)
    patient_amount = Column(INTEGER)
    sequential_offs = Column(BOOLEAN)
    even_nights = Column(BOOLEAN)
    nod_noe = Column(BOOLEAN)
    created_at = Column(DATETIME, default=func.now())
    preceptor_gauge = Column(INTEGER, nullable=False, default=5)

    office = relationship("Office")
    group = relationship("Group")

class Wanted(Base):
    __tablename__ = 'wanted'
    group_id = Column(VARCHAR(50), ForeignKey('groups.group_id'), primary_key=True)
    year = Column(SMALLINT, primary_key=True)
    month = Column(TINYINT, primary_key=True)
    exp_date = Column(DATETIME, nullable=True)  # 마감일
    status = Column(VARCHAR(10), default='requested')  # requested, closed
    created_at = Column(DATETIME, default=func.now())
    
    group = relationship("Group")

class IssuedRoster(Base):
    __tablename__ = 'issued_roster'
    seq_no = Column(INTEGER, primary_key=True, autoincrement=True)
    office_id = Column(VARCHAR(50), ForeignKey('offices.office_id'), nullable=False)
    group_id = Column(VARCHAR(50), ForeignKey('groups.group_id'), nullable=False)
    nurse_id = Column(VARCHAR(50), ForeignKey('nurses.nurse_id'), nullable=False)  # 발행한 사람
    issued_at = Column(DATETIME, default=func.now())
    version = Column(TINYINT, nullable=False)
    v_name = Column(VARCHAR(100), nullable=True)  # 버전 명
    issue_cmmt = Column(VARCHAR(500), nullable=True)  # 발행 코멘트
    schedule_id = Column(CHAR(12), ForeignKey('schedules.schedule_id'), nullable=False)
    
    office = relationship("Office")
    group = relationship("Group")
    nurse = relationship("Nurse")
    schedule = relationship("Schedule") 

class RosterAnalytics(Base):
    __tablename__ = 'roster_analytics'
    analytics_id = Column(INTEGER, primary_key=True, autoincrement=True)
    schedule_id = Column(CHAR(12), ForeignKey('schedules.schedule_id'), nullable=False)
    nurse_id = Column(VARCHAR(50), ForeignKey('nurses.nurse_id'), nullable=False)
    year = Column(SMALLINT, nullable=False)
    month = Column(TINYINT, nullable=False)
    
    # 개인별 만족도 지표
    off_satisfaction = Column(FLOAT, nullable=False, default=0.0)
    shift_satisfaction = Column(FLOAT, nullable=False, default=0.0)
    pair_satisfaction = Column(FLOAT, nullable=False, default=0.0)
    overall_satisfaction = Column(FLOAT, nullable=False, default=0.0)
    
    # 요청 통계
    total_requests = Column(INTEGER, nullable=False, default=0)
    satisfied_requests = Column(INTEGER, nullable=False, default=0)
    off_requests = Column(INTEGER, nullable=False, default=0)
    satisfied_off_requests = Column(INTEGER, nullable=False, default=0)
    shift_requests = Column(INTEGER, nullable=False, default=0)
    satisfied_shift_requests = Column(INTEGER, nullable=False, default=0)
    pair_requests = Column(INTEGER, nullable=False, default=0)
    satisfied_pair_requests = Column(INTEGER, nullable=False, default=0)
    
    # 생성 시간
    created_at = Column(DATETIME, default=func.now())
    
    # 관계 설정
    schedule = relationship("Schedule")
    nurse = relationship("Nurse")

class RosterRequestDetails(Base):
    __tablename__ = 'roster_request_details'
    detail_id = Column(INTEGER, primary_key=True, autoincrement=True)
    analytics_id = Column(INTEGER, ForeignKey('roster_analytics.analytics_id'), nullable=False)
    nurse_id = Column(VARCHAR(50), ForeignKey('nurses.nurse_id'), nullable=False)
    day = Column(INTEGER, nullable=False)
    request_type = Column(VARCHAR(20), nullable=False)  # 'off', 'shift', 'pair'
    shift_type = Column(VARCHAR(10), nullable=True)  # 'D', 'E', 'N' (shift 요청의 경우)
    pair_type = Column(VARCHAR(20), nullable=True)  # 'work_together', 'work_apart' (pair 요청의 경우)
    nurse_2_id = Column(VARCHAR(50), nullable=True)  # pair 요청의 경우 (외래키 제약조건 제거)
    satisfied = Column(BOOLEAN, nullable=False, default=False)
    preference_score = Column(FLOAT, nullable=False, default=0.0)
    
    # 생성 시간
    created_at = Column(DATETIME, default=func.now())
    
    # 관계 설정
    analytics = relationship("RosterAnalytics")
    nurse = relationship("Nurse", foreign_keys=[nurse_id])
    # nurse_2 관계는 필요시에만 사용하도록 주석 처리
    # nurse_2 = relationship("Nurse", foreign_keys=[nurse_2_id])


class WantedRequest(Base):
    __tablename__ = 'wanted_requests'
    nurse_id = Column(VARCHAR(50), primary_key=True)
    request_id = Column(INTEGER, primary_key=True)
    month = Column(CHAR(7), primary_key=True)  # 'YYYY-MM'
    request = Column(TEXT, nullable=True)
    is_submitted = Column(TINYINT(1), nullable=False, default=0)
    created_at = Column(DATETIME, nullable=False, default=func.now())
    submitted_at = Column(DATETIME, nullable=True)


class NurseShiftRequest(Base):
    __tablename__ = 'nurse_shift_requests'
    nurse_id = Column(VARCHAR(50), primary_key=True)
    request_id = Column(INTEGER, primary_key=True)
    detailed_request_id = Column(INTEGER, primary_key=True)
    shift_date = Column(DATE, primary_key=True)
    shift = Column(CHAR(1), nullable=False)  # 'D','E','N','O'
    score = Column(DECIMAL(3, 1), nullable=False)
    partial_request = Column(TEXT, nullable=True)


class NursePairRequest(Base):
    __tablename__ = 'nurse_pair_requests'
    nurse_id = Column(VARCHAR(50), primary_key=True)
    request_id = Column(INTEGER, primary_key=True)
    detailed_request_id = Column(INTEGER, primary_key=True)
    target_id = Column(VARCHAR(50), primary_key=True)
    score = Column(DECIMAL(3, 1), nullable=False)
    partial_request = Column(TEXT, nullable=True)
class DailyShift(Base):
    __tablename__ = 'daily_shift'

    office_id = Column(VARCHAR(50), ForeignKey('offices.office_id'), primary_key=True)
    group_id = Column(VARCHAR(50), ForeignKey('groups.group_id'), primary_key=True)
    year = Column(SMALLINT, primary_key=True)
    month = Column(TINYINT, primary_key=True)
    day = Column(TINYINT, primary_key=True)
    d_count = Column(SMALLINT, nullable=False, default=0)
    e_count = Column(SMALLINT, nullable=False, default=0)
    n_count = Column(SMALLINT, nullable=False, default=0)
    created_at = Column(DATETIME, default=func.now())
    updated_at = Column(DATETIME, default=func.now(), onupdate=func.now())

    office = relationship("Office")
    group = relationship("Group")
