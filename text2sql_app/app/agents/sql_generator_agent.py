import os
import re
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from ..db.schema_provider import reflect_or_static_schema, tables_for_category
import dotenv

dotenv.load_dotenv()

class SQLGeneration(BaseModel):
    """SQL 생성 결과 모델"""
    sql: str
    explanation: str
    confidence: float  # 0.0 ~ 1.0
    tables_used: List[str]


class SQLGeneratorPrompt:
    def __init__(self, user_question: str, schema_info: str, category: str):
        """
        간호사 근무표 Text2SQL 생성 프롬프트
        """
        self.system = f"""
            ## GOAL:
                당신은 "간호사 근무표 Text2SQL 전문가" 입니다.
                한국어 자연어 질의를 받아 meditong_roster 데이터베이스용 MySQL SELECT 쿼리를 생성합니다.

            ## 1. 데이터베이스 스키마 정보
{schema_info}

            ## 2. 질의 카테고리: {category}
                - **schedule_details**: 구체적인 일정/교대 정보 조회 (schedule_entries, schedules, nurses, shifts 중심)
                - **statistics**: 통계/분석 데이터 조회 (roster_analytics, 집계 함수 사용)

            ## 3. SQL 작성 규칙
                **보안 제약**:
                - SELECT, SHOW, DESCRIBE, EXPLAIN만 허용
                - INSERT, UPDATE, DELETE, DROP, ALTER 등 금지
                - 세미콜론(;) 사용 금지 (단일 쿼리만)
                
                **스키마 제약**:
                - 위에 명시된 테이블과 컬럼만 사용
                - 스키마 접두사 생략 (예: meditong_roster.nurses → nurses)
                - 정확한 JOIN 키 사용 필수
                
                **쿼리 품질**:
                - 명확하고 효율적인 SQL 작성
                - 적절한 WHERE 조건으로 결과 범위 제한
                - 필요시 ORDER BY, LIMIT 사용
                - 한국어 데이터 처리를 위한 적절한 문자셋 고려

            ## 4. 주요 테이블 관계
                - nurses ↔ groups (group_id)
                - groups ↔ offices (office_id) 
                - schedules ↔ groups (group_id)
                - schedule_entries ↔ schedules (schedule_id)
                - schedule_entries ↔ nurses (nurse_id)
                - schedule_entries ↔ shifts (shift_id)
                - roster_analytics ↔ schedules (schedule_id)
                - roster_analytics ↔ nurses (nurse_id)

            ## 5. 교대 유형 코드
                - D: 주간 근무 (Day)
                - E: 저녁 근무 (Evening)  
                - N: 야간 근무 (Night)
                - O: 휴무 (Off)

            ## 6. 일반적인 질의 패턴
                **일정 조회**: 
                ```sql
                SELECT nurses.name, schedule_entries.work_date, shifts.name as shift_name
                FROM schedule_entries 
                JOIN nurses ON schedule_entries.nurse_id = nurses.nurse_id
                JOIN shifts ON schedule_entries.shift_id = shifts.shift_id
                WHERE schedule_entries.work_date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
                ```

                **통계 분석**:
                ```sql  
                SELECT nurses.name, COUNT(*) as night_count
                FROM schedule_entries
                JOIN nurses ON schedule_entries.nurse_id = nurses.nurse_id  
                JOIN shifts ON schedule_entries.shift_id = shifts.shift_id
                WHERE shifts.shift_id = 'N' AND YEAR(schedule_entries.work_date) = 2024
                GROUP BY nurses.name
                ORDER BY night_count DESC
                ```

            ## 7. 응답 형식
                - **sql**: 실행 가능한 MySQL SELECT 쿼리만
                - **explanation**: 쿼리 동작 설명 (한국어)
                - **confidence**: 쿼리 정확도 신뢰도 (0.0~1.0)
                - **tables_used**: 사용된 테이블 목록

            ## 주의사항
                - 존재하지 않는 테이블/컬럼 사용 금지
                - 모호한 질의의 경우 합리적인 해석으로 진행
                - 날짜 형식은 'YYYY-MM-DD' 사용
                - 한국어 컬럼값 검색시 LIKE 연산자 활용
        """
        
        self.human = f"""
            # 사용자 질의:
            {user_question}
            
            # SQL 생성 및 설명:
        """


class SQLGeneratorAgent:
    def __init__(self):
        """SQL Generator 에이전트 초기화 (모델은 lazy 로딩)"""
        self._models = None
        self.schema = reflect_or_static_schema()

    def _get_models(self):
        """모델들을 lazy 초기화"""
        if self._models is None:
            self._models = []
            
            # 1차: OpenAI (기본) - SQL 생성에 강함
            if os.getenv("OPENAI_API_KEY"):
                try:
                    self._models.append(ChatOpenAI(
                        model="gpt-4o",
                        openai_api_key=os.getenv("OPENAI_API_KEY"),
                        temperature=0.0,  # SQL은 정확성이 중요하므로 temperature 낮게
                    ))
                except Exception as e:
                    print(f"OpenAI 초기화 실패: {e}")
            
            # 2차: Anthropic (백업) - 코드 생성 능력 우수
            if os.getenv("ANTHROPIC_API_KEY"):
                try:
                    self._models.append(ChatAnthropic(
                        model="claude-3-5-sonnet-20241022",
                        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"), 
                        temperature=0.0,
                    ))
                except Exception as e:
                    print(f"Anthropic 초기화 실패: {e}")
            
            # 3차: Google Gemini (최종 백업)
            if os.getenv("GOOGLE_API_KEY"):
                try:
                    self._models.append(ChatGoogleGenerativeAI(
                        model="gemini-2.0-flash",
                        google_api_key=os.getenv("GOOGLE_API_KEY"),
                        temperature=0.0,
                    ))
                except Exception as e:
                    print(f"Google 초기화 실패: {e}")
                    
        return self._models

    def _format_schema_for_category(self, category: str) -> str:
        """카테고리에 맞는 스키마 정보를 포맷팅"""
        relevant_tables = tables_for_category(category)
        
        schema_lines = ["테이블 및 컬럼 정보:"]
        for table in relevant_tables:
            if table in self.schema:
                columns = self.schema[table]
                schema_lines.append(f"- **{table}**: {', '.join(columns)}")
        
        return "\n".join(schema_lines)

    def _extract_and_validate_sql(self, raw_sql: str) -> str:
        """생성된 SQL에서 순수 쿼리만 추출하고 기본 검증"""
        # 마크다운 코드블록 제거
        sql = re.sub(r'```sql\n?', '', raw_sql)
        sql = re.sub(r'```\n?', '', sql)
        
        # 앞뒤 공백 및 세미콜론 제거
        sql = sql.strip().rstrip(';')
        
        # SQL 키워드로 시작하는지 확인
        sql_lower = sql.lower().strip()
        if not any(sql_lower.startswith(keyword) for keyword in ['select', 'show', 'describe', 'explain']):
            raise ValueError(f"유효하지 않은 SQL 구문: {sql[:50]}...")
            
        return sql

    def generate_sql(self, user_question: str, category: str = "schedule_details") -> Dict[str, Any]:
        """
        사용자 질의를 바탕으로 SQL을 생성
        
        Args:
            user_question: 사용자 질의
            category: 질의 카테고리 ("schedule_details" 또는 "statistics")
            
        Returns:
            SQL 생성 결과 딕셔너리
        """
        schema_info = self._format_schema_for_category(category)
        prompt = SQLGeneratorPrompt(user_question, schema_info, category)
        
        messages = [
            SystemMessage(content=prompt.system),
            HumanMessage(content=prompt.human)
        ]
        
        # 기본값 설정
        result = {
            "sql": "",
            "explanation": "SQL 생성에 실패했습니다.",
            "confidence": 0.0,
            "tables_used": [],
            "model_used": None,
            "error": None
        }
        
        models = self._get_models()
        
        if not models:
            result["error"] = "No LLM models available"
            return result

        for i, client in enumerate(models):
            try:
                print(f"SQL Generator: {i+1}차 모델 시도 중...")
                
                # JSON 구조화된 출력으로 호출
                llm = client.with_structured_output(SQLGeneration)
                response = llm.invoke(messages)
                
                # SQL 추출 및 검증
                clean_sql = self._extract_and_validate_sql(response.sql)
                
                # 성공 시 결과 업데이트
                result.update({
                    "sql": clean_sql,
                    "explanation": response.explanation,
                    "confidence": response.confidence,
                    "tables_used": response.tables_used,
                    "model_used": f"model_{i+1}",
                    "error": None
                })
                
                print(f"SQL Generator: {i+1}차 모델 성공!")
                print(f"생성된 SQL: {clean_sql}")
                break
                
            except Exception as e:
                error_msg = str(e).lower()
                print(f"SQL Generator: {i+1}차 모델 오류 - {e}")
                
                # Rate limit 에러 확인
                if any(keyword in error_msg for keyword in [
                    "429", "rate", "529", "service unavailable", 
                    "quota", "limit", "too many requests"
                ]):
                    if i < len(self.models_to_try) - 1:
                        print(f"SQL Generator: {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("SQL Generator: 모든 백업 모델 실패")
                        result["error"] = "All models failed due to rate limits"
                        break
                else:
                    # 다른 에러는 즉시 백업 모델로 시도
                    if i < len(self.models_to_try) - 1:
                        print(f"SQL Generator: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("SQL Generator: 모든 모델 실패")
                        result["error"] = f"All models failed: {e}"
                        break
        
        return result

    async def generate_sql_async(self, user_question: str, category: str = "schedule_details") -> Dict[str, Any]:
        """
        비동기 버전의 SQL 생성
        """
        schema_info = self._format_schema_for_category(category)
        prompt = SQLGeneratorPrompt(user_question, schema_info, category)
        
        messages = [
            SystemMessage(content=prompt.system),
            HumanMessage(content=prompt.human)
        ]
        
        # 기본값 설정
        result = {
            "sql": "",
            "explanation": "SQL 생성에 실패했습니다.",
            "confidence": 0.0,
            "tables_used": [],
            "model_used": None,
            "error": None
        }
        
        for i, client in enumerate(self.models_to_try):
            try:
                print(f"SQL Generator: {i+1}차 모델 시도 중...")
                
                # JSON 구조화된 출력으로 호출
                llm = client.with_structured_output(SQLGeneration)
                response = await llm.ainvoke(messages)
                
                # SQL 추출 및 검증
                clean_sql = self._extract_and_validate_sql(response.sql)
                
                # 성공 시 결과 업데이트
                result.update({
                    "sql": clean_sql,
                    "explanation": response.explanation,
                    "confidence": response.confidence,
                    "tables_used": response.tables_used,
                    "model_used": f"model_{i+1}",
                    "error": None
                })
                
                print(f"SQL Generator: {i+1}차 모델 성공!")
                print(f"생성된 SQL: {clean_sql}")
                break
                
            except Exception as e:
                error_msg = str(e).lower()
                print(f"SQL Generator: {i+1}차 모델 오류 - {e}")
                
                if any(keyword in error_msg for keyword in [
                    "429", "rate", "529", "service unavailable", 
                    "quota", "limit", "too many requests"
                ]):
                    if i < len(self.models_to_try) - 1:
                        print(f"SQL Generator: {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("SQL Generator: 모든 백업 모델 실패")
                        result["error"] = "All models failed due to rate limits"
                        break
                else:
                    if i < len(self.models_to_try) - 1:
                        print(f"SQL Generator: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("SQL Generator: 모든 모델 실패")
                        result["error"] = f"All models failed: {e}"
                        break
        
        return result 