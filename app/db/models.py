from sqlalchemy import Column, VARCHAR, SMALLINT, BOOLEAN, DATETIME, func, ForeignKey
from sqlalchemy.dialects.mysql import TINYINT 
from app.db.client import Base

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