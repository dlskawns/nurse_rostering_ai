import json
import os
from pydantic import BaseModel
from typing import List, Dict, Any
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
import dotenv

dotenv.load_dotenv()

# 디버그 로깅 추가
print("🔍 [DEBUG] AnswerGeneratorAgent 모듈 로드됨")


class AnswerGeneration(BaseModel):
    """답변 생성 결과 모델"""
    answer: str  # 메인 답변
    summary: str  # 요약 정보
    insights: List[str]  # 주요 인사이트들
    confidence: float  # 0.0 ~ 1.0


class AnswerGeneratorPrompt:
    def __init__(self, user_question: str, sql_query: str = "", columns: List[str] = None, rows: List[List[Any]] = None):
        """
        간호사 근무표 Text2SQL 답변 생성 프롬프트
        """
        if not columns or not rows:
            # 데이터가 없는 경우
            self.system = """
                ## GOAL:
                    당신은 "간호사 근무표 Text2SQL 답변 생성기" 입니다.
                    사용자의 질의에 대해 도움이 되는 답변을 제공합니다.

                ## 1. 답변 스타일
                    - 친근하고 도움이 되는 톤
                    - 간호사 근무표 시스템에 대한 설명 제공
                    - 예시 질의 제안

                ## 2. 응답 형식
                    JSON 형태로만 응답하세요.
                    
                ## 예시
                    출력: {
                        "answer": "안녕하세요! 간호사 근무표 조회 시스템입니다...",
                        "summary": "시스템 소개",
                        "insights": ["간호사 스케줄 조회 가능", "통계 분석 제공"],
                        "confidence": 0.8
                    }
            """
            
            self.human = f"""
                # 사용자 질의:
                {user_question}
                
                # JSON 응답:
            """
        else:
            # 데이터가 있는 경우
            data_preview = "\n".join([
                f"{i+1}. " + " | ".join([f"{col}: {row[j]}" for j, col in enumerate(columns)])
                for i, row in enumerate(rows[:5])  # 최대 5개만 미리보기
            ])
            
            if len(rows) > 5:
                data_preview += f"\n... (총 {len(rows)}건 중 5건 표시)"
            
            self.system = """
                ## GOAL:
                    당신은 "간호사 근무표 Text2SQL 답변 생성기" 입니다.
                    SQL 쿼리 결과를 분석하여 사용자 친화적인 자연어 답변을 생성합니다.

                ## 1. 답변 생성 규칙
                    - 데이터를 명확하고 이해하기 쉽게 설명
                    - 숫자 데이터는 구체적으로 제시
                    - 패턴이나 특이사항이 있으면 언급
                    - 간호사 업무와 관련된 맥락 제공

                ## 2. 인사이트 생성
                    - 데이터에서 발견되는 주요 패턴
                    - 간호사 관리에 도움이 되는 정보
                    - 추가 분석 제안사항

                ## 3. 신뢰도 평가
                    - 1.0: 완벽한 데이터와 명확한 답변
                    - 0.8: 좋은 데이터, 약간의 추론 포함
                    - 0.6: 적절한 데이터, 일부 제한사항 있음
                    - 0.4: 제한적인 데이터

                ## 4. 응답 형식
                    JSON 형태로만 응답하세요.

                ## 예시
                    질의: "2024년 7월 야간 근무가 많은 간호사는?"
                    답변: {
                        "answer": "2024년 7월 야간 근무 분석 결과, 김간호사가 15회로 가장 많았습니다...",
                        "summary": "야간 근무 상위 3명: 김간호사(15회), 이간호사(12회), 박간호사(10회)",
                        "insights": ["김간호사가 다른 간호사보다 25% 많은 야간 근무", "평균 야간 근무 횟수는 8.5회"],
                        "confidence": 0.95
                    }
            """
            
            self.human = f"""
                # 사용자 질의:
                {user_question}
                
                # 실행된 SQL:
                {sql_query}
                
                # 조회된 데이터:
                컬럼: {', '.join(columns)}
                
                데이터:
                {data_preview}
                
                # JSON 응답:
            """


class AnswerGeneratorAgent:
    def __init__(self):
        """Answer Generator 에이전트 초기화 (모델은 lazy 로딩)"""
        print("🔍 [DEBUG] AnswerGeneratorAgent.__init__() 호출됨")
        self._models = None

    def _get_models(self):
        """모델들을 lazy 초기화"""
        print("🔍 [DEBUG] AnswerGeneratorAgent._get_models() 호출됨")
        
        if self._models is None:
            print("🔍 [DEBUG] 답변 생성 모델들을 처음 초기화합니다...")
            self._models = []
            
            # 환경변수 확인
            openai_key = os.getenv("OPENAI_API_KEY")
            anthropic_key = os.getenv("ANTHROPIC_API_KEY") 
            google_key = os.getenv("GOOGLE_API_KEY")
            
            # 1차: OpenAI (기본)
            if openai_key:
                try:
                    print("🔍 [DEBUG] OpenAI 답변 생성 모델 초기화 시도...")
                    model = ChatOpenAI(
                        model="gpt-4o",
                        openai_api_key=openai_key,
                        temperature=0.3,
                    )
                    self._models.append(model)
                    print("✅ [DEBUG] OpenAI 답변 생성 모델 초기화 성공")
                except Exception as e:
                    print(f"❌ [DEBUG] OpenAI 답변 생성 모델 초기화 실패: {e}")
            
            # 2차: Anthropic (백업)
            if anthropic_key:
                try:
                    print("🔍 [DEBUG] Anthropic 답변 생성 모델 초기화 시도...")
                    model = ChatAnthropic(
                        model="claude-3-5-sonnet-20241022",
                        anthropic_api_key=anthropic_key,
                        temperature=0.3,
                    )
                    self._models.append(model)
                    print("✅ [DEBUG] Anthropic 답변 생성 모델 초기화 성공")
                except Exception as e:
                    print(f"❌ [DEBUG] Anthropic 답변 생성 모델 초기화 실패: {e}")
            
            # 3차: Google Gemini (최종 백업)
            if google_key:
                try:
                    print("🔍 [DEBUG] Google 답변 생성 모델 초기화 시도...")
                    model = ChatGoogleGenerativeAI(
                        model="gemini-2.0-flash",
                        google_api_key=google_key,
                        temperature=0.3,
                    )
                    self._models.append(model)
                    print("✅ [DEBUG] Google 답변 생성 모델 초기화 성공")
                except Exception as e:
                    print(f"❌ [DEBUG] Google 답변 생성 모델 초기화 실패: {e}")
                    
            print(f"🔍 [DEBUG] 총 {len(self._models)}개 답변 생성 모델이 초기화됨")
        else:
            print(f"🔍 [DEBUG] 기존에 초기화된 {len(self._models)}개 답변 생성 모델 재사용")
            
        return self._models

    def generate_answer(self, user_question: str, sql_query: str = "", columns: List[str] = None, rows: List[List[Any]] = None) -> Dict[str, Any]:
        """
        SQL 실행 결과를 바탕으로 자연어 답변 생성
        
        Args:
            user_question: 사용자 원본 질의
            sql_query: 실행된 SQL 쿼리 (선택사항)
            columns: 조회된 컬럼명 리스트 (선택사항)
            rows: 조회된 데이터 행들 (선택사항)
            
        Returns:
            답변 생성 결과 딕셔너리
        """
        print(f"🔍 [DEBUG] generate_answer() 호출됨 - 질문: '{user_question}'")
        print(f"🔍 [DEBUG] 데이터 상태: columns={len(columns) if columns else 0}, rows={len(rows) if rows else 0}")
        
        # 데이터가 없는 경우 간단한 응답
        if not columns or not rows:
            print("🔍 [DEBUG] 데이터가 없어서 일반 대화 응답 생성")
            return {
                "answer": "안녕하세요! 간호사 근무표 조회 시스템입니다. 근무 일정이나 통계에 대해 질문해주세요.",
                "summary": "시스템 안내",
                "insights": ["간호사 스케줄 조회 가능", "근무 통계 분석 제공", "자연어로 질문 가능"],
                "confidence": 0.8,
                "model_used": None,
                "error": None
            }
        
        models = self._get_models()
        
        if not models:
            print("❌ [DEBUG] 사용 가능한 답변 생성 모델이 없음!")
            row_count = len(rows) if rows else 0
            return {
                "answer": f"총 {row_count}건의 결과가 조회되었습니다. 자세한 분석 결과를 생성하지 못했습니다.",
                "summary": "모델 없음으로 기본 응답",
                "insights": [],
                "confidence": 0.3,
                "model_used": None,
                "error": "No LLM models available"
            }

        print(f"🔍 [DEBUG] {len(models)}개 모델로 답변 생성 시작")
        prompt = AnswerGeneratorPrompt(user_question, sql_query, columns, rows)
        
        messages = [
            SystemMessage(content=prompt.system),
            HumanMessage(content=prompt.human)
        ]
        
        row_count = len(rows) if rows else 0
        
        # 기본값 설정
        result = {
            "answer": f"총 {row_count}건의 결과가 조회되었습니다.",
            "summary": "자세한 분석 결과를 생성하지 못했습니다.",
            "insights": [],
            "confidence": 0.3,
            "model_used": None,
            "error": None
        }
        
        for i, client in enumerate(models):
            try:
                print(f"🔍 [DEBUG] Answer Generator: {i+1}차 모델 시도 중...")
                
                # JSON 구조화된 출력으로 호출
                llm = client.with_structured_output(AnswerGeneration)
                response = llm.invoke(messages)
                
                # 성공 시 결과 업데이트
                result.update({
                    "answer": response.answer,
                    "summary": response.summary,
                    "insights": response.insights,
                    "confidence": response.confidence,
                    "model_used": f"model_{i+1}",
                    "error": None
                })
                
                print(f"✅ [DEBUG] Answer Generator: {i+1}차 모델 성공!")
                break
                
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ [DEBUG] Answer Generator: {i+1}차 모델 오류 - {e}")
                
                # Rate limit 또는 Service unavailable 에러 확인
                if any(keyword in error_msg for keyword in [
                    "429", "rate", "529", "service unavailable", 
                    "quota", "limit", "too many requests"
                ]):
                    if i < len(models) - 1:
                        print(f"🔄 [DEBUG] Answer Generator: {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("❌ [DEBUG] Answer Generator: 모든 백업 모델 실패, 기본값 사용")
                        result["error"] = "All models failed due to rate limits"
                        break
                else:
                    # 다른 에러는 즉시 백업 모델로 시도
                    if i < len(models) - 1:
                        print(f"🔄 [DEBUG] Answer Generator: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("❌ [DEBUG] Answer Generator: 모든 모델 실패, 기본값 사용")
                        result["error"] = f"All models failed: {e}"
                        break
        
        print(f"🔍 [DEBUG] generate_answer() 최종 결과: {result}")
        return result

    async def generate_answer_async(self, user_question: str, sql_query: str = "", columns: List[str] = None, rows: List[List[Any]] = None) -> Dict[str, Any]:
        """
        비동기 버전의 답변 생성
        
        Args:
            user_question: 사용자 원본 질의
            sql_query: 실행된 SQL 쿼리 (선택사항)
            columns: 조회된 컬럼명 리스트 (선택사항)
            rows: 조회된 데이터 행들 (선택사항)
            
        Returns:
            답변 생성 결과 딕셔너리
        """
        print(f"🔍 [DEBUG] generate_answer_async() 호출됨 - 질문: '{user_question}'")
        
        # 데이터가 없는 경우 간단한 응답
        if not columns or not rows:
            return {
                "answer": "안녕하세요! 간호사 근무표 조회 시스템입니다. 근무 일정이나 통계에 대해 질문해주세요.",
                "summary": "시스템 안내",
                "insights": ["간호사 스케줄 조회 가능", "근무 통계 분석 제공", "자연어로 질문 가능"],
                "confidence": 0.8,
                "model_used": None,
                "error": None
            }
        
        models = self._get_models()
        
        if not models:
            row_count = len(rows) if rows else 0
            return {
                "answer": f"총 {row_count}건의 결과가 조회되었습니다. 자세한 분석 결과를 생성하지 못했습니다.",
                "summary": "모델 없음으로 기본 응답",
                "insights": [],
                "confidence": 0.3,
                "model_used": None,
                "error": "No LLM models available"
            }

        prompt = AnswerGeneratorPrompt(user_question, sql_query, columns, rows)
        
        messages = [
            SystemMessage(content=prompt.system),
            HumanMessage(content=prompt.human)
        ]
        
        row_count = len(rows) if rows else 0
        
        # 기본값 설정
        result = {
            "answer": f"총 {row_count}건의 결과가 조회되었습니다.",
            "summary": "자세한 분석 결과를 생성하지 못했습니다.",
            "insights": [],
            "confidence": 0.3,
            "model_used": None,
            "error": None
        }
        
        for i, client in enumerate(models):
            try:
                print(f"Answer Generator: {i+1}차 모델 시도 중...")
                
                # JSON 구조화된 출력으로 호출
                llm = client.with_structured_output(AnswerGeneration)
                response = await llm.ainvoke(messages)
                
                # 성공 시 결과 업데이트
                result.update({
                    "answer": response.answer,
                    "summary": response.summary,
                    "insights": response.insights,
                    "confidence": response.confidence,
                    "model_used": f"model_{i+1}",
                    "error": None
                })
                
                print(f"Answer Generator: {i+1}차 모델 성공!")
                break
                
            except Exception as e:
                error_msg = str(e).lower()
                print(f"Answer Generator: {i+1}차 모델 오류 - {e}")
                
                # Rate limit 또는 Service unavailable 에러 확인
                if any(keyword in error_msg for keyword in [
                    "429", "rate", "529", "service unavailable", 
                    "quota", "limit", "too many requests"
                ]):
                    if i < len(models) - 1:
                        print(f"Answer Generator: {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("Answer Generator: 모든 백업 모델 실패, 기본값 사용")
                        result["error"] = "All models failed due to rate limits"
                        break
                else:
                    # 다른 에러는 즉시 백업 모델로 시도
                    if i < len(models) - 1:
                        print(f"Answer Generator: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("Answer Generator: 모든 모델 실패, 기본값 사용")
                        result["error"] = f"All models failed: {e}"
                        break
        
        return result 