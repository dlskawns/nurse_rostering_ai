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
print("🔍 [DEBUG] QueryAnalyzerAgent 모듈 로드됨")
print(f"🔍 [DEBUG] 환경변수 체크:")
print(f"  - OPENAI_API_KEY: {'설정됨' if os.getenv('OPENAI_API_KEY') else '없음'}")
print(f"  - ANTHROPIC_API_KEY: {'설정됨' if os.getenv('ANTHROPIC_API_KEY') else '없음'}")
print(f"  - GOOGLE_API_KEY: {'설정됨' if os.getenv('GOOGLE_API_KEY') else '없음'}")


class QueryAnalysis(BaseModel):
    """질의 분석 결과 모델"""
    type: str  # "query" or "chat"
    category: str  # "schedule_details", "statistics", "empty"
    confidence: float  # 0.0 ~ 1.0


class QueryAnalyzerPrompt:
    def __init__(self, context: str):
        """
        간호사 근무표 Text2SQL 질의 분석 프롬프트
        """
        self.system = """
            ## GOAL:
                당신은 "간호사 근무표 Text2SQL 질의 분석기" 입니다.
                한국어 자연어 입력을 받아 질의 유형을 분류하고 적절한 카테고리로 라우팅합니다.

            ## 1. 질의 유형 분류
                **query**: 데이터베이스에서 정보를 조회하는 질의
                **chat**: 일반 대화, 인사말, 시스템 설명 요청 등

            ## 2. 카테고리 분류 (query 타입인 경우)
                **schedule_details**: 구체적인 근무 일정, 교대 근무, 간호사별 스케줄 조회
                - 예: "2024년 7월 야간 근무 목록", "김간호사의 이번 달 스케줄", "특정 날짜 근무자"
                
                **statistics**: 통계, 분석, 요약 데이터 조회
                - 예: "가장 많은 야간 근무를 한 간호사", "만족도 통계", "근무 패턴 분석"

            ## 3. 신뢰도 평가 (confidence)
                - 1.0: 명확한 데이터 조회 질의
                - 0.8: 약간의 애매함이 있지만 데이터 조회로 판단
                - 0.6: 애매한 경우 (fallback 필요할 수 있음)
                - 0.4: 일반 대화에 가까움
                - 0.2: 명확한 일반 대화

            ## 4. 응답 형식
                JSON 형태로만 응답하세요. 설명이나 추가 텍스트는 포함하지 마세요.

            ## 예시
                입력: "2024년 7월에 야간 근무가 가장 많은 간호사는?"
                출력: {"type": "query", "category": "statistics", "confidence": 1.0}

                입력: "안녕하세요"
                출력: {"type": "chat", "category": "empty", "confidence": 0.2}

                입력: "김간호사의 이번 달 스케줄 보여줘"
                출력: {"type": "query", "category": "schedule_details", "confidence": 0.9}
        """
        
        self.human = f"""
            # 분석할 질의:
            {context}
            
            # JSON 응답:
        """


class QueryAnalyzerAgent:
    def __init__(self):
        """Query Analyzer 에이전트 초기화 (모델은 lazy 로딩)"""
        print("🔍 [DEBUG] QueryAnalyzerAgent.__init__() 호출됨")
        self._models = None

    def _get_models(self):
        """모델들을 lazy 초기화"""
        print("🔍 [DEBUG] _get_models() 호출됨")
        
        if self._models is None:
            print("🔍 [DEBUG] 모델들을 처음 초기화합니다...")
            self._models = []
            
            # 환경변수 재확인
            print(f"🔍 [DEBUG] 현재 환경변수 상태:")
            openai_key = os.getenv("OPENAI_API_KEY")
            anthropic_key = os.getenv("ANTHROPIC_API_KEY") 
            google_key = os.getenv("GOOGLE_API_KEY")
            
            print(f"  - OPENAI_API_KEY: {openai_key[:10] + '...' if openai_key else '없음'}")
            print(f"  - ANTHROPIC_API_KEY: {anthropic_key[:10] + '...' if anthropic_key else '없음'}")
            print(f"  - GOOGLE_API_KEY: {google_key[:10] + '...' if google_key else '없음'}")
            
            # 1차: OpenAI (기본)
            if openai_key:
                try:
                    print("🔍 [DEBUG] OpenAI 모델 초기화 시도...")
                    model = ChatOpenAI(
                        model="gpt-4o",
                        openai_api_key=openai_key,
                        temperature=0.1,
                    )
                    self._models.append(model)
                    print("✅ [DEBUG] OpenAI 모델 초기화 성공")
                except Exception as e:
                    print(f"❌ [DEBUG] OpenAI 초기화 실패: {e}")
            else:
                print("⚠️ [DEBUG] OPENAI_API_KEY가 없어서 OpenAI 모델 건너뜀")
            
            # 2차: Anthropic (백업)
            if anthropic_key:
                try:
                    print("🔍 [DEBUG] Anthropic 모델 초기화 시도...")
                    model = ChatAnthropic(
                        model="claude-3-5-sonnet-20241022",
                        anthropic_api_key=anthropic_key,
                        temperature=0.1,
                    )
                    self._models.append(model)
                    print("✅ [DEBUG] Anthropic 모델 초기화 성공")
                except Exception as e:
                    print(f"❌ [DEBUG] Anthropic 초기화 실패: {e}")
            else:
                print("⚠️ [DEBUG] ANTHROPIC_API_KEY가 없어서 Anthropic 모델 건너뜀")
            
            # 3차: Google Gemini (최종 백업)
            if google_key:
                try:
                    print("🔍 [DEBUG] Google 모델 초기화 시도...")
                    model = ChatGoogleGenerativeAI(
                        model="gemini-2.0-flash",
                        google_api_key=google_key,
                        temperature=0.1,
                    )
                    self._models.append(model)
                    print("✅ [DEBUG] Google 모델 초기화 성공")
                except Exception as e:
                    print(f"❌ [DEBUG] Google 초기화 실패: {e}")
            else:
                print("⚠️ [DEBUG] GOOGLE_API_KEY가 없어서 Google 모델 건너뜀")
                    
            print(f"🔍 [DEBUG] 총 {len(self._models)}개 모델이 초기화됨")
        else:
            print(f"🔍 [DEBUG] 기존에 초기화된 {len(self._models)}개 모델 재사용")
            
        return self._models

    async def analyze_query(self, user_input: str) -> Dict[str, Any]:
        """
        사용자 질의를 분석하여 타입과 카테고리를 반환
        
        Args:
            user_input: 사용자가 입력한 질의
            
        Returns:
            분석 결과 딕셔너리
        """
        print(f"🔍 [DEBUG] analyze_query() 호출됨 - 입력: '{user_input}'")
        
        models = self._get_models()
        
        if not models:
            print("❌ [DEBUG] 사용 가능한 모델이 없음!")
            return {
                "type": "chat",
                "category": "empty", 
                "confidence": 0.2,
                "model_used": None,
                "error": "No LLM models available"
            }

        print(f"🔍 [DEBUG] {len(models)}개 모델로 질의 분석 시작")
        prompt = QueryAnalyzerPrompt(user_input)
        
        messages = [
            SystemMessage(content=prompt.system),
            HumanMessage(content=prompt.human)
        ]
        
        # 기본값 설정
        result = {
            "type": "chat",
            "category": "empty", 
            "confidence": 0.2,
            "model_used": None,
            "error": None
        }
        
        for i, client in enumerate(models):
            try:
                print(f"🔍 [DEBUG] Query Analyzer: {i+1}차 모델 시도 중...")
                
                # JSON 구조화된 출력으로 호출
                llm = client.with_structured_output(QueryAnalysis)
                response = await llm.ainvoke(messages)
                
                # 성공 시 결과 업데이트
                result.update({
                    "type": response.type,
                    "category": response.category,
                    "confidence": response.confidence,
                    "model_used": f"model_{i+1}",
                    "error": None
                })
                
                print(f"✅ [DEBUG] Query Analyzer: {i+1}차 모델 성공! 결과: {result}")
                break
                
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ [DEBUG] Query Analyzer: {i+1}차 모델 오류 - {e}")
                
                # Rate limit 또는 Service unavailable 에러 확인
                if any(keyword in error_msg for keyword in [
                    "429", "rate", "529", "service unavailable", 
                    "quota", "limit", "too many requests"
                ]):
                    if i < len(models) - 1:
                        print(f"🔄 [DEBUG] Query Analyzer: {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("❌ [DEBUG] Query Analyzer: 모든 백업 모델 실패, 기본값 사용")
                        result["error"] = "All models failed due to rate limits"
                        break
                else:
                    # 다른 에러는 즉시 백업 모델로 시도
                    if i < len(models) - 1:
                        print(f"🔄 [DEBUG] Query Analyzer: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("❌ [DEBUG] Query Analyzer: 모든 모델 실패, 기본값 사용")
                        result["error"] = f"All models failed: {e}"
                        break
        
        print(f"🔍 [DEBUG] analyze_query() 최종 결과: {result}")
        return result

    def analyze_query_sync(self, user_input: str) -> Dict[str, Any]:
        """
        동기 버전의 질의 분석
        
        Args:
            user_input: 사용자가 입력한 질의
            
        Returns:
            분석 결과 딕셔너리
        """
        print(f"🔍 [DEBUG] analyze_query_sync() 호출됨 - 입력: '{user_input}'")
        
        models = self._get_models()
        
        if not models:
            print("❌ [DEBUG] 사용 가능한 모델이 없음!")
            return {
                "type": "chat",
                "category": "empty",
                "confidence": 0.2,
                "model_used": None,
                "error": "No LLM models available"
            }

        print(f"🔍 [DEBUG] {len(models)}개 모델로 동기 질의 분석 시작")
        prompt = QueryAnalyzerPrompt(user_input)
        
        messages = [
            SystemMessage(content=prompt.system),
            HumanMessage(content=prompt.human)
        ]
        
        # 기본값 설정
        result = {
            "type": "chat",
            "category": "empty",
            "confidence": 0.2,
            "model_used": None,
            "error": None
        }
        
        for i, client in enumerate(models):
            try:
                print(f"🔍 [DEBUG] Query Analyzer: {i+1}차 모델 시도 중...")
                
                # JSON 구조화된 출력으로 호출
                llm = client.with_structured_output(QueryAnalysis)
                response = llm.invoke(messages)
                
                # 성공 시 결과 업데이트
                result.update({
                    "type": response.type,
                    "category": response.category,
                    "confidence": response.confidence,
                    "model_used": f"model_{i+1}",
                    "error": None
                })
                
                print(f"✅ [DEBUG] Query Analyzer: {i+1}차 모델 성공! 결과: {result}")
                break
                
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ [DEBUG] Query Analyzer: {i+1}차 모델 오류 - {e}")
                
                # Rate limit 또는 Service unavailable 에러 확인
                if any(keyword in error_msg for keyword in [
                    "429", "rate", "529", "service unavailable", 
                    "quota", "limit", "too many requests"
                ]):
                    if i < len(models) - 1:
                        print(f"🔄 [DEBUG] Query Analyzer: {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("❌ [DEBUG] Query Analyzer: 모든 백업 모델 실패, 기본값 사용")
                        result["error"] = "All models failed due to rate limits"
                        break
                else:
                    # 다른 에러는 즉시 백업 모델로 시도
                    if i < len(models) - 1:
                        print(f"🔄 [DEBUG] Query Analyzer: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                        continue
                    else:
                        print("❌ [DEBUG] Query Analyzer: 모든 모델 실패, 기본값 사용")
                        result["error"] = f"All models failed: {e}"
                        break
        
        print(f"🔍 [DEBUG] analyze_query_sync() 최종 결과: {result}")
        return result 