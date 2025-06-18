from sqlalchemy import Column, VARCHAR, SMALLINT, BOOLEAN, DATETIME, func, ForeignKey, JSON, CHAR
from sqlalchemy.dialects.mysql import TINYINT 
from sqlalchemy.orm import relationship
from app.db.client import Base

class Group(Base):
    __tablename__ = 'groups'
    group_id = Column(VARCHAR(50), primary_key=True)
    office_id = Column(VARCHAR(50), ForeignKey('offices.office_id'))
    name = Column(VARCHAR(50), nullable=False)

class Office(Base):
    __tablename__ = 'offices'
    office_id = Column(VARCHAR(50), primary_key=True)
    name = Column(VARCHAR(100), nullable=False)
    address = Column(VARCHAR(255))
    contact_number = Column(VARCHAR(30))

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
    is_night_nurse = Column(BOOLEAN, default=False)
    personal_off_adjustment = Column(TINYINT, default=0)
    preceptor_id = Column(VARCHAR(50), ForeignKey("nurses.nurse_id"))
    created_at = Column(DATETIME, default=func.now())
    updated_at = Column(DATETIME, default=func.now(), onupdate=func.now())

    group = relationship("Group")

class Schedule(Base):
    __tablename__ = "schedules"
    schedule_id = Column(CHAR(12), primary_key=True)
    office_id = Column(VARCHAR(50), ForeignKey("offices.office_id"))
    group_id = Column(VARCHAR(50), ForeignKey("groups.group_id"))
    year = Column(SMALLINT, nullable=False)
    month = Column(TINYINT, nullable=False)
    version = Column(TINYINT, nullable=False)
    created_by = Column(VARCHAR(50), ForeignKey("nurses.account_id"))
    created_at = Column(DATETIME, default=func.now())
    updated_at = Column(DATETIME, default=func.now(), onupdate=func.now())
    status = Column(VARCHAR(10)) # e.g., 'requested', 'issued'

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
    name = Column(VARCHAR(20), nullable=False)
    color = Column(VARCHAR(10), nullable=False)

class ShiftPreference(Base):
    __tablename__ = "shift_preferences"
    nurse_id = Column(VARCHAR(50), ForeignKey("nurses.nurse_id"), primary_key=True)
    year = Column(SMALLINT, primary_key=True)
    month = Column(TINYINT, primary_key=True)
    data = Column(JSON, nullable=False)
    is_submitted = Column(BOOLEAN, nullable=False, default=False)
    created_at = Column(DATETIME, nullable=False, default=func.now())
    submitted_at = Column(DATETIME, nullable=True) 