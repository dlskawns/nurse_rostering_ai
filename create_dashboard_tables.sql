-- 대시보드용 테이블 생성 스크립트

-- 근무표 분석 데이터 테이블
CREATE TABLE IF NOT EXISTS roster_analytics (
    analytics_id INT AUTO_INCREMENT PRIMARY KEY,
    schedule_id CHAR(12) NOT NULL,
    nurse_id VARCHAR(50) NOT NULL,
    year SMALLINT NOT NULL,
    month TINYINT NOT NULL,
    
    -- 개인별 만족도 지표
    off_satisfaction FLOAT NOT NULL DEFAULT 0.0,
    shift_satisfaction FLOAT NOT NULL DEFAULT 0.0,
    pair_satisfaction FLOAT NOT NULL DEFAULT 0.0,
    overall_satisfaction FLOAT NOT NULL DEFAULT 0.0,
    
    -- 요청 통계
    total_requests INT NOT NULL DEFAULT 0,
    satisfied_requests INT NOT NULL DEFAULT 0,
    off_requests INT NOT NULL DEFAULT 0,
    satisfied_off_requests INT NOT NULL DEFAULT 0,
    shift_requests INT NOT NULL DEFAULT 0,
    satisfied_shift_requests INT NOT NULL DEFAULT 0,
    pair_requests INT NOT NULL DEFAULT 0,
    satisfied_pair_requests INT NOT NULL DEFAULT 0,
    
    -- 생성 시간
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 외래키 제약조건
    FOREIGN KEY (schedule_id) REFERENCES schedules(schedule_id) ON DELETE CASCADE,
    FOREIGN KEY (nurse_id) REFERENCES nurses(nurse_id) ON DELETE CASCADE,
    
    -- 인덱스
    INDEX idx_schedule_id (schedule_id),
    INDEX idx_nurse_id (nurse_id),
    INDEX idx_year_month (year, month),
    INDEX idx_created_at (created_at)
);

-- 상세 요청 데이터 테이블
CREATE TABLE IF NOT EXISTS roster_request_details (
    detail_id INT AUTO_INCREMENT PRIMARY KEY,
    analytics_id INT NOT NULL,
    nurse_id VARCHAR(50) NOT NULL,
    day INT NOT NULL,
    request_type VARCHAR(20) NOT NULL,  -- 'off', 'shift', 'pair'
    shift_type VARCHAR(10) NULL,  -- 'D', 'E', 'N' (shift 요청의 경우)
    pair_type VARCHAR(20) NULL,  -- 'work_together', 'work_apart' (pair 요청의 경우)
    nurse_2_id VARCHAR(50) NULL,  -- pair 요청의 경우
    satisfied BOOLEAN NOT NULL DEFAULT FALSE,
    preference_score FLOAT NOT NULL DEFAULT 0.0,
    
    -- 생성 시간
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- 외래키 제약조건
    FOREIGN KEY (analytics_id) REFERENCES roster_analytics(analytics_id) ON DELETE CASCADE,
    FOREIGN KEY (nurse_id) REFERENCES nurses(nurse_id) ON DELETE CASCADE,
    -- nurse_2_id는 외래키 제약조건 제거 (순환 참조 문제 해결)
    -- FOREIGN KEY (nurse_2_id) REFERENCES nurses(nurse_id) ON DELETE SET NULL,
    
    -- 인덱스
    INDEX idx_analytics_id (analytics_id),
    INDEX idx_nurse_id (nurse_id),
    INDEX idx_request_type (request_type),
    INDEX idx_satisfied (satisfied),
    INDEX idx_created_at (created_at)
);

-- 테이블 생성 확인
SHOW TABLES LIKE 'roster_analytics';
SHOW TABLES LIKE 'roster_request_details';

-- 테이블 구조 확인
DESCRIBE roster_analytics;
DESCRIBE roster_request_details; 