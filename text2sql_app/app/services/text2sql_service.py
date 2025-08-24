import os
from typing import Dict, Any, List, Generator
import dotenv
from ..agents.query_analyzer_agent import QueryAnalyzerAgent
from ..agents.sql_generator_agent import SQLGeneratorAgent  
from ..agents.answer_generator_agent import AnswerGeneratorAgent
from ..db.client import create_readonly_engine, execute_select
from ..db.sanitizer import sanitize_sql
from ..db.schema_provider import tables_for_category

# .env 파일 로드
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

# 디버그 로깅 추가
print("🔍 [DEBUG] Text2SQLService 모듈 로드됨")
print(f"🔍 [DEBUG] .env 파일 경로: {os.path.join(os.path.dirname(__file__), '../../.env')}")


class Text2SQLService:
    """
    Text2SQL 전체 파이프라인을 관리하는 메인 서비스
    
    Flow: 질의 분석 → SQL 생성 → DB 실행 → 답변 생성
    """
    
    def __init__(self):
        """서비스 초기화"""
        print("🔍 [DEBUG] Text2SQLService.__init__() 시작")
        
        try:
            print("🔍 [DEBUG] QueryAnalyzerAgent 초기화 중...")
            self.query_analyzer = QueryAnalyzerAgent()
            print("✅ [DEBUG] QueryAnalyzerAgent 초기화 완료")
            
            print("🔍 [DEBUG] SQLGeneratorAgent 초기화 중...")
            self.sql_generator = SQLGeneratorAgent()
            print("✅ [DEBUG] SQLGeneratorAgent 초기화 완료")
            
            print("🔍 [DEBUG] AnswerGeneratorAgent 초기화 중...")
            self.answer_generator = AnswerGeneratorAgent()
            print("✅ [DEBUG] AnswerGeneratorAgent 초기화 완료")
            
            print("🔍 [DEBUG] DB 엔진 초기화 중...")
            self.db_engine = create_readonly_engine()
            print("✅ [DEBUG] DB 엔진 초기화 완료")
            
        except Exception as e:
            print(f"❌ [DEBUG] Text2SQLService 초기화 실패: {e}")
            raise
        
        print("✅ [DEBUG] Text2SQLService.__init__() 완료")
        
    def process_query_stream(self, user_input: str) -> Generator[Dict[str, Any], None, None]:
        """
        사용자 입력을 받아 전체 Text2SQL 파이프라인을 스트리밍으로 실행
        
        Args:
            user_input: 사용자가 입력한 자연어 질의
            
        Yields:
            각 단계별 처리 결과가 담긴 딕셔너리
        """
        print(f"🔍 [DEBUG] process_query_stream() 시작 - 입력: '{user_input}'")
        
        try:
            # Step 1: 질의 분석
            print("🔍 [DEBUG] Step 1: 질의 분석 시작")
            yield {
                "type": "step",
                "step": "1단계: 질의 분석을 시작합니다",
                "step_number": 1,
                "status": "loading"
            }
            
            analysis_result = self.query_analyzer.analyze_query_sync(user_input)
            print(f"🔍 [DEBUG] 질의 분석 결과: {analysis_result}")
            
            if analysis_result.get("error"):
                error_msg = f"질의 분석 실패: {analysis_result['error']}"
                print(f"❌ [DEBUG] {error_msg}")
                yield {
                    "type": "error",
                    "message": error_msg
                }
                return
                
            yield {
                "type": "update",
                "message": f"질의 분석 완료: {analysis_result['type']}/{analysis_result['category']}",
                "step_number": 1
            }
            print(f"✅ [DEBUG] Step 1 완료: {analysis_result['type']}/{analysis_result['category']}")
            
            # Step 2: SQL 생성 (query 타입인 경우만)
            if analysis_result["type"] == "query":
                print("🔍 [DEBUG] Step 2: SQL 생성 시작")
                yield {
                    "type": "step",
                    "step": "2단계: SQL 생성을 시작합니다",
                    "step_number": 2,
                    "status": "loading"
                }
                
                category = analysis_result.get("category", "schedule_details")
                print(f"🔍 [DEBUG] 카테고리: {category}")
                
                sql_result = self.sql_generator.generate_sql(user_input, category)
                print(f"🔍 [DEBUG] SQL 생성 결과: {sql_result}")
                
                if sql_result.get("error") or not sql_result.get("sql"):
                    error_msg = f"SQL 생성 실패: {sql_result.get('error', 'Unknown error')}"
                    print(f"❌ [DEBUG] {error_msg}")
                    yield {
                        "type": "error",
                        "message": error_msg
                    }
                    return
                    
                yield {
                    "type": "update",
                    "message": f"SQL 생성 완료: {sql_result['sql'][:50]}...",
                    "step_number": 2
                }
                print(f"✅ [DEBUG] Step 2 완료: SQL 생성됨")
                
                # Step 3: SQL 실행
                print("🔍 [DEBUG] Step 3: SQL 실행 시작")
                yield {
                    "type": "step",
                    "step": "3단계: 데이터베이스 쿼리를 실행합니다",
                    "step_number": 3,
                    "status": "loading"
                }
                
                execution_result = self._execute_sql_safely(sql_result["sql"], category)
                print(f"🔍 [DEBUG] SQL 실행 결과: {execution_result}")
                
                if execution_result.get("error"):
                    error_msg = f"SQL 실행 실패: {execution_result['error']}"
                    print(f"❌ [DEBUG] {error_msg}")
                    yield {
                        "type": "error",
                        "message": error_msg
                    }
                    return
                    
                yield {
                    "type": "update",
                    "message": f"SQL 실행 완료: {execution_result['row_count']}건 조회",
                    "step_number": 3
                }
                print(f"✅ [DEBUG] Step 3 완료: {execution_result['row_count']}건 조회")
                
                # Step 4: 답변 생성
                print("🔍 [DEBUG] Step 4: 답변 생성 시작")
                yield {
                    "type": "step",
                    "step": "4단계: 자연어 답변을 생성합니다",
                    "step_number": 4,
                    "status": "loading"
                }
                
                answer_result = self.answer_generator.generate_answer(
                    user_input,
                    sql_result["sql"],
                    execution_result["columns"],
                    execution_result["rows"]
                )
                print(f"🔍 [DEBUG] 답변 생성 결과: {answer_result}")
                
                if answer_result.get("error"):
                    yield {
                        "type": "update",
                        "message": f"답변 생성 부분 실패, 기본 응답 사용",
                        "step_number": 4
                    }
                    final_answer = f"총 {execution_result['row_count']}건의 데이터가 조회되었습니다."
                else:
                    yield {
                        "type": "update",
                        "message": "답변 생성 완료",
                        "step_number": 4
                    }
                    final_answer = answer_result["answer"]
                    print(f"✅ [DEBUG] Step 4 완료: 답변 생성됨")
                
                # 최종 결과 전송
                yield {
                    "type": "complete",
                    "analysis": analysis_result,
                    "sql": sql_result["sql"],
                    "columns": execution_result["columns"],
                    "rows": execution_result["rows"],
                    "answer": final_answer,
                    "sql_generation": sql_result,
                    "sql_execution": execution_result,
                    "answer_generation": answer_result
                }
                    
            else:
                # 일반 채팅인 경우
                print("🔍 [DEBUG] Step 2: 일반 대화 응답 생성")
                yield {
                    "type": "step",
                    "step": "2단계: 일반 대화로 인식되어 간단한 응답을 생성합니다",
                    "step_number": 2,
                    "status": "loading"
                }
                
                answer_result = self.answer_generator.generate_answer(user_input)
                
                yield {
                    "type": "update",
                    "message": "응답 생성 완료",
                    "step_number": 2
                }
                
                yield {
                    "type": "complete",
                    "analysis": analysis_result,
                    "sql": "",
                    "columns": [],
                    "rows": [],
                    "answer": answer_result["answer"],
                    "answer_generation": answer_result
                }
                print(f"✅ [DEBUG] 일반 대화 응답 완료")
                
        except Exception as e:
            error_msg = f"처리 중 예상치 못한 오류 발생: {str(e)}"
            print(f"❌ [DEBUG] {error_msg}")
            yield {
                "type": "error",
                "message": error_msg
            }
            
        print(f"🔍 [DEBUG] process_query_stream() 완료")
        
    def process_query(self, user_input: str) -> Dict[str, Any]:
        """
        사용자 입력을 받아 전체 Text2SQL 파이프라인 실행
        
        Args:
            user_input: 사용자가 입력한 자연어 질의
            
        Returns:
            전체 처리 결과가 담긴 딕셔너리
        """
        print(f"🔍 [DEBUG] process_query() 시작 - 입력: '{user_input}'")
        
        # 결과 저장용 딕셔너리
        result = {
            "user_input": user_input,
            "logs": [],
            "analysis": None,
            "sql_generation": None,
            "sql_execution": None,
            "answer_generation": None,
            "final_answer": "",
            "error": None
        }
        
        try:
            # Step 1: 질의 분석
            print("🔍 [DEBUG] Step 1: 질의 분석 시작")
            result["logs"].append("1단계: 질의 분석을 시작합니다.")
            analysis_result = self.query_analyzer.analyze_query_sync(user_input)
            result["analysis"] = analysis_result
            print(f"🔍 [DEBUG] 질의 분석 결과: {analysis_result}")
            
            if analysis_result.get("error"):
                error_msg = f"질의 분석 실패: {analysis_result['error']}"
                print(f"❌ [DEBUG] {error_msg}")
                result["logs"].append(error_msg)
                result["final_answer"] = "질의 분석 중 오류가 발생했습니다. 다시 시도해주세요."
                return result
                
            result["logs"].append(f"질의 분석 완료: {analysis_result['type']}/{analysis_result['category']}")
            print(f"✅ [DEBUG] Step 1 완료: {analysis_result['type']}/{analysis_result['category']}")
            
            # Step 2: SQL 생성 (query 타입인 경우만)
            if analysis_result["type"] == "query":
                print("🔍 [DEBUG] Step 2: SQL 생성 시작")
                result["logs"].append("2단계: SQL 생성을 시작합니다.")
                
                category = analysis_result.get("category", "schedule_details")
                print(f"🔍 [DEBUG] 카테고리: {category}")
                
                sql_result = self.sql_generator.generate_sql(user_input, category)
                result["sql_generation"] = sql_result
                print(f"🔍 [DEBUG] SQL 생성 결과: {sql_result}")
                
                if sql_result.get("error") or not sql_result.get("sql"):
                    error_msg = f"SQL 생성 실패: {sql_result.get('error', 'Unknown error')}"
                    print(f"❌ [DEBUG] {error_msg}")
                    result["logs"].append(error_msg)
                    result["final_answer"] = "SQL 생성 중 오류가 발생했습니다. 질문을 다시 확인해주세요."
                    return result
                    
                result["logs"].append(f"SQL 생성 완료: {sql_result['sql'][:100]}...")
                print(f"✅ [DEBUG] Step 2 완료: SQL 생성됨")
                
                # Step 3: SQL 실행
                print("🔍 [DEBUG] Step 3: SQL 실행 시작")
                result["logs"].append("3단계: 데이터베이스 쿼리를 실행합니다.")
                execution_result = self._execute_sql_safely(sql_result["sql"], category)
                result["sql_execution"] = execution_result
                print(f"🔍 [DEBUG] SQL 실행 결과: {execution_result}")
                
                if execution_result.get("error"):
                    error_msg = f"SQL 실행 실패: {execution_result['error']}"
                    print(f"❌ [DEBUG] {error_msg}")
                    result["logs"].append(error_msg)
                    result["final_answer"] = "데이터베이스 조회 중 오류가 발생했습니다."
                    return result
                    
                result["logs"].append(f"SQL 실행 완료: {execution_result['row_count']}건 조회")
                print(f"✅ [DEBUG] Step 3 완료: {execution_result['row_count']}건 조회")
                
                # Step 4: 답변 생성
                print("🔍 [DEBUG] Step 4: 답변 생성 시작")
                result["logs"].append("4단계: 자연어 답변을 생성합니다.")
                answer_result = self.answer_generator.generate_answer(
                    user_input,
                    sql_result["sql"],
                    execution_result["columns"],
                    execution_result["rows"]
                )
                result["answer_generation"] = answer_result
                print(f"🔍 [DEBUG] 답변 생성 결과: {answer_result}")
                
                if answer_result.get("error"):
                    error_msg = f"답변 생성 실패: {answer_result['error']}"
                    print(f"❌ [DEBUG] {error_msg}")
                    result["logs"].append(error_msg)
                    result["final_answer"] = f"총 {execution_result['row_count']}건의 데이터가 조회되었습니다."
                else:
                    result["logs"].append("답변 생성 완료")
                    result["final_answer"] = answer_result["answer"]
                    print(f"✅ [DEBUG] Step 4 완료: 답변 생성됨")
                    
            else:
                # 일반 채팅인 경우
                print("🔍 [DEBUG] Step 2: 일반 대화 응답 생성")
                result["logs"].append("2단계: 일반 대화로 인식되어 간단한 응답을 생성합니다.")
                answer_result = self.answer_generator.generate_answer(user_input)
                result["answer_generation"] = answer_result
                result["final_answer"] = answer_result["answer"]
                print(f"✅ [DEBUG] 일반 대화 응답 완료")
                
        except Exception as e:
            error_msg = f"처리 중 예상치 못한 오류 발생: {str(e)}"
            print(f"❌ [DEBUG] {error_msg}")
            result["logs"].append(error_msg)
            result["error"] = error_msg
            result["final_answer"] = "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            
        print(f"🔍 [DEBUG] process_query() 완료 - 최종 답변: '{result['final_answer']}'")
        return result
    
    def _execute_sql_safely(self, sql: str, category: str) -> Dict[str, Any]:
        """
        SQL을 안전하게 실행하고 결과 반환
        
        Args:
            sql: 실행할 SQL 쿼리
            category: 질의 카테고리 (보안 검증용)
            
        Returns:
            실행 결과 딕셔너리
        """
        print(f"🔍 [DEBUG] _execute_sql_safely() 시작 - SQL: {sql}")
        
        result = {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": None
        }
        
        try:
            # SQL 보안 검증
            print("🔍 [DEBUG] SQL 보안 검증 중...")
            allowed_tables = tables_for_category(category)
            print(f"🔍 [DEBUG] 허용된 테이블: {allowed_tables}")
            
            is_valid, cleaned_sql, error_msg = sanitize_sql(sql, allowed_tables)
            
            if not is_valid:
                error_msg = f"SQL 보안 검증 실패: {error_msg}"
                print(f"❌ [DEBUG] {error_msg}")
                result["error"] = error_msg
                return result
                
            print(f"✅ [DEBUG] SQL 보안 검증 통과: {cleaned_sql}")
                
            # SQL 실행
            print("🔍 [DEBUG] SQL 실행 중...")
            columns, rows = execute_select(self.db_engine, cleaned_sql)
            
            result.update({
                "columns": columns,
                "rows": [list(row) for row in rows],
                "row_count": len(rows)
            })
            
            print(f"✅ [DEBUG] SQL 실행 완료: {len(columns)}개 컬럼, {len(rows)}행")
            
        except Exception as e:
            error_msg = f"SQL 실행 오류: {str(e)}"
            print(f"❌ [DEBUG] {error_msg}")
            result["error"] = error_msg
            
        return result
    
    async def process_query_async(self, user_input: str) -> Dict[str, Any]:
        """
        비동기 버전의 질의 처리
        
        Args:
            user_input: 사용자가 입력한 자연어 질의
            
        Returns:
            전체 처리 결과가 담긴 딕셔너리
        """
        print(f"🔍 [DEBUG] process_query_async() 시작 - 입력: '{user_input}'")
        
        # 결과 저장용 딕셔너리
        result = {
            "user_input": user_input,
            "logs": [],
            "analysis": None,
            "sql_generation": None,
            "sql_execution": None,
            "answer_generation": None,
            "final_answer": "",
            "error": None
        }
        
        try:
            # Step 1: 질의 분석
            result["logs"].append("1단계: 질의 분석을 시작합니다.")
            analysis_result = await self.query_analyzer.analyze_query(user_input)
            result["analysis"] = analysis_result
            
            if analysis_result.get("error"):
                result["logs"].append(f"질의 분석 실패: {analysis_result['error']}")
                result["final_answer"] = "질의 분석 중 오류가 발생했습니다. 다시 시도해주세요."
                return result
                
            result["logs"].append(f"질의 분석 완료: {analysis_result['type']}/{analysis_result['category']}")
            
            # Step 2: SQL 생성 (query 타입인 경우만)
            if analysis_result["type"] == "query":
                result["logs"].append("2단계: SQL 생성을 시작합니다.")
                
                category = analysis_result.get("category", "schedule_details")
                sql_result = await self.sql_generator.generate_sql_async(user_input, category)
                result["sql_generation"] = sql_result
                
                if sql_result.get("error") or not sql_result.get("sql"):
                    result["logs"].append(f"SQL 생성 실패: {sql_result.get('error', 'Unknown error')}")
                    result["final_answer"] = "SQL 생성 중 오류가 발생했습니다. 질문을 다시 확인해주세요."
                    return result
                    
                result["logs"].append(f"SQL 생성 완료: {sql_result['sql'][:100]}...")
                
                # Step 3: SQL 실행
                result["logs"].append("3단계: 데이터베이스 쿼리를 실행합니다.")
                execution_result = self._execute_sql_safely(sql_result["sql"], category)
                result["sql_execution"] = execution_result
                
                if execution_result.get("error"):
                    result["logs"].append(f"SQL 실행 실패: {execution_result['error']}")
                    result["final_answer"] = "데이터베이스 조회 중 오류가 발생했습니다."
                    return result
                    
                result["logs"].append(f"SQL 실행 완료: {execution_result['row_count']}건 조회")
                
                # Step 4: 답변 생성
                result["logs"].append("4단계: 자연어 답변을 생성합니다.")
                answer_result = await self.answer_generator.generate_answer_async(
                    user_input,
                    sql_result["sql"],
                    execution_result["columns"],
                    execution_result["rows"]
                )
                result["answer_generation"] = answer_result
                
                if answer_result.get("error"):
                    result["logs"].append(f"답변 생성 실패: {answer_result['error']}")
                    result["final_answer"] = f"총 {execution_result['row_count']}건의 데이터가 조회되었습니다."
                else:
                    result["logs"].append("답변 생성 완료")
                    result["final_answer"] = answer_result["answer"]
                    
            else:
                # 일반 채팅인 경우
                result["logs"].append("2단계: 일반 대화로 인식되어 간단한 응답을 생성합니다.")
                answer_result = await self.answer_generator.generate_answer_async(user_input)
                result["answer_generation"] = answer_result
                result["final_answer"] = answer_result["answer"]
                
        except Exception as e:
            error_msg = f"처리 중 예상치 못한 오류 발생: {str(e)}"
            result["logs"].append(error_msg)
            result["error"] = error_msg
            result["final_answer"] = "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            
        return result
    
    def get_service_status(self) -> Dict[str, Any]:
        """
        서비스 상태 정보 반환
        
        Returns:
            서비스 상태 딕셔너리
        """
        print("🔍 [DEBUG] get_service_status() 호출됨")
        
        openai_available = bool(os.getenv("OPENAI_API_KEY"))
        anthropic_available = bool(os.getenv("ANTHROPIC_API_KEY"))
        google_available = bool(os.getenv("GOOGLE_API_KEY"))
        
        status = {
            "service": "Text2SQL for Nurse Rostering",
            "agents": {
                "query_analyzer": "ready",
                "sql_generator": "ready", 
                "answer_generator": "ready"
            },
            "database": {
                "engine": "mysql+pymysql",
                "status": "connected" if self.db_engine else "disconnected"
            },
            "llm_providers": {
                "openai": openai_available,
                "anthropic": anthropic_available,
                "google": google_available
            }
        }
        
        print(f"🔍 [DEBUG] 서비스 상태: {status}")
        return status 