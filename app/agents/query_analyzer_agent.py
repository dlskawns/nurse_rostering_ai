import json
from pydantic import BaseModel
from typing import List, TypedDict, Annotated, operator
from google import genai
from google.genai import types
import dotenv
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
import pprint
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
import os
try:
    import tiktoken
except Exception:
    tiktoken = None

dotenv.load_dotenv()

class queryAnalyzer(BaseModel):
    Chat: List[str] 
    Shift: List[str] 
    Preference: List[str]
    Others: List[str] 


# ------------------------------
# 비용/토큰 유틸리티
# ------------------------------
def _krw_per_usd() -> float:
    try:
        return float(os.getenv("KRW_PER_USD", "1350"))
    except Exception:
        return 1350.0


def _pricing_per_1k(model_name: str) -> tuple[float, float]:
    """
    모델별 1K 토큰당 (입력, 출력) USD 비용을 반환.
    값은 최신 요금과 다를 수 있으니 환경에 맞게 조정 필요.
    """
    name = (model_name or "").lower()
    # 기본값 (보수적)
    input_usd, output_usd = 0.003, 0.009
    if "gpt-4o" in name:
        # OpenAI GPT-4o (약 $5/$15 per 1M)
        input_usd, output_usd = 0.005, 0.015
    elif "claude" in name:
        # Anthropic Claude Sonnet (약 $3/$15 per 1M)
        input_usd, output_usd = 0.003, 0.015
    elif "gemini" in name:
        # Google Gemini Flash (약 $0.35/$1.05 per 1M)
        input_usd, output_usd = 0.00035, 0.00105
    return input_usd, output_usd


def _encoding_for_model(model_name: str):
    name = (model_name or "").lower()
    try:
        if "gpt" in name or "o" in name:
            return tiktoken.get_encoding("o200k_base")
        # 범용 기본 인코딩
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _count_tokens(text: str, model_name: str) -> int:
    if not text:
        return 0
    enc = _encoding_for_model(model_name)
    if enc is None:
        # 대략적 근사치 (문자 수 / 4)
        return max(1, int(len(text) / 4))
    try:
        return len(enc.encode(text))
    except Exception:
        return max(1, int(len(text) / 4))


def _count_messages_tokens(messages: List[str], model_name: str) -> int:
    return sum(_count_tokens(m or "", model_name) for m in messages)


def _compute_cost(prompt_tokens: int, completion_tokens: int, model_name: str) -> dict:
    in_per_1k, out_per_1k = _pricing_per_1k(model_name)
    input_usd = (prompt_tokens / 1000.0) * in_per_1k
    output_usd = (completion_tokens / 1000.0) * out_per_1k
    total_usd = input_usd + output_usd
    rate = _krw_per_usd()
    return {
        "model": model_name,
        "pricing_per_1k_usd": {"input": in_per_1k, "output": out_per_1k},
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "cost_usd": {
            "input": round(input_usd, 6),
            "output": round(output_usd, 6),
            "total": round(total_usd, 6),
        },
        "cost_krw": {
            "input": int(round(input_usd * rate)),
            "output": int(round(output_usd * rate)),
            "total": int(round(total_usd * rate)),
            "krw_per_usd": rate,
        },
    }


class queryAnalyzerPrompt:
    def __init__(self, context, year, month):
        """
        프롬프트 클래스
        """
        self.system = f"""
            ## GOAL:
                당신은 "간호사 희망사항 전처리기" 입니다.  
                한국어 자연어 입력 ➜ 카테고리별 List(JSON) 로 분해·정규화해 주세요.

            ## 1. 작업 목표
                1. 한 문장 안에 여러 날짜·Shift·선호 가 섞여 있으면 의미 단위로 잘라 개별 항목화.
                2. Shift / Preference 항목의 각 요소에는 단일 내용만 존재해야 함.  
                예)  
                - "5/5는 쉬고 싶고, 5/6은 E로 줘" →  
                    `"Shift": ["5/5은 OFF로 줘", "5/6은 E로 줘"]`
                3. 날짜가 생략된 지시("그 외엔…")는 앞선 날짜를 보완하여 정보 손실 없이 재기술.  
                예) "5/5는 N, 그 외엔 E" →  
                    `"Shift": ["5/5은 N로 줘", "5/5 제외 나머지는 E로 줘"]`
                4. 반복적/패턴적 요청(예: "주말엔 쉬고 싶다", "매주 수요일은 OFF")은 
                절대로 모든 날짜로 분할하지 말고, **하나의 규칙형 항목**으로 기록.
                - 예) "주말엔 쉬고 싶다" → `"Shift": ["매주 주말은 O로 줘"]`
                - 예) "수요일은 OFF" → `"Shift": ["매주 수요일은 O로 줘"]`
                - 예) "평일엔 D, 주말엔 O" → `"Shift": ["평일은 D로 줘", "주말은 O로 줘"]`
                5. 절대 중복/혼합 금지: 한 요소에 OFF와 E 같이 넣지 마세요.
                6. 최종 JSON 키
                    Chat ― 근무와 무관한 잡담
                    Shift ― 날짜·교대·OFF 요청
                    Preference ― 다른 간호사 함께/회피 선호
                    Others ― 위 분류에 안 맞는 요청
                    * 빈 카테고리는 [] 로 남김.
                    * 요소 순서는 입력 흐름 유지.
            ## 2. 필수 규칙
                | 표현 | 변환 예시|
                | - | - |
                | Day shift | "D" |
                | Evening   | "E" |
                | Night     | "N" |
                | Off/휴무    | "O" |
                | 날짜 구분     | `M/D`  또는 `M월 D일` 등 모두 허용, 출력은 원문 그대로 보존 |
                | 주기 표현   | "매주", "주말", "평일", "격주" 등은 그대로 규칙형 항목으로 남김 |

            ## 3. 처리 지침
                * "매주/주말/평일" 같은 주기성 표현은 원문 그대로 유지하며, 절대로 날짜를 추측하여 쪼개지 마세요.
                * 해석 불가 문장·모호 표현은 Others에 넣으세요.
            
            # CONTEXT:
                "5/5는 쉬고 싶고, 5/19는 나이트 후 OFF, 그리고 정간호사랑은 겹치기 싫어요"

            # OUTPUT:
                {{
                "Chat": [],
                "Shift": [
                    "5/5은 쉬고 싶고",
                    "5/19는 N,
                    "5/20은 O"
                ],
                "Preference": [
                    "정간호사랑은 겹치기 싫어요"
                ],
                "Others": []
                }}
        """
        
        self.human=f"""
            # CONTEXT: 
            {year}년 {month}월의 근무표를 짜기 위해서 다음과 같은 요청을 받았습니다.
            {context}
            # OUTPUT:
        """


async def query_analyzer(state):
    context = state['request']
    year = state['year']
    month = state['month']
    query_analyzer_prompt = queryAnalyzerPrompt(context, year, month)
    
    # 백업 모델들 순서대로 시도
    models_to_try = [
        # 1차: OpenAI (기본)
        ChatOpenAI(
            model="gpt-4o",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        ),
        # 2차: Anthropic (백업)
        ChatAnthropic(
            model="claude-3-7-sonnet-20250219",
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        ),
        # 3차: Google Gemini (최종 백업)
        ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
    ]
    
    messages = [
        SystemMessage(content=query_analyzer_prompt.system),
        HumanMessage(content=query_analyzer_prompt.human)
    ]
    
    chat = []
    shift = []
    preference = []
    others = []
    used_model_name = ""

    # case 기반 수동 경로 (모델 미사용)
    if state['case'] != None:
        print(state['case'], state['request'])
        for content, rq in zip(state['case'], state['request']):
            date = content['date']
            shift_type = content['shift']
            shift.append(f"{date}에 {shift_type}을 원하고, 그 이유는 다음과 같습니다: {rq}")
        # 토큰/비용(모델 미사용 → 0)
        prompt_tokens = 0
        completion_json = json.dumps({
            "Chat": chat,
            "Shift": shift,
            "Preference": preference,
            "Others": others
        }, ensure_ascii=False)
        completion_tokens = 0 if not completion_json else 0
        cost_info = _compute_cost(prompt_tokens, completion_tokens, used_model_name)
        print(f"토큰 사용량(수동): {cost_info['usage']}, 비용(원): {cost_info['cost_krw']['total']}")
        return {
            "query_chat": chat,
            'query_shift': shift,
            'query_preference': preference,
            'query_others': others,
            'model': models_to_try[0],
            'date': date,
            'shift': shift
        }

    for i, client in enumerate(models_to_try):
        try:
            print(f"Query Analyzer: {i+1}차 모델 시도 중...")
            
            llm = client.with_structured_output(queryAnalyzer)
            response = await llm.ainvoke(messages)
            used_model_name = getattr(client, "model", "") or used_model_name
            
            # 성공 시 데이터 추출
            chat = response.Chat
            shift = response.Shift
            preference = response.Preference
            others = response.Others
            
            print(f"Query Analyzer: {i+1}차 모델 성공!")
            break
            
        except Exception as e:
            error_msg = str(e).lower()
            print(f"Query Analyzer: {i+1}차 모델 오류 - {e}")
            
            # 429 (Rate limit) 또는 529 (Service unavailable) 에러인지 확인
            if ("429" in error_msg or "rate" in error_msg or 
                "529" in error_msg or "service unavailable" in error_msg or
                "quota" in error_msg or "limit" in error_msg):
                
                if i < len(models_to_try) - 1:
                    print(f"Query Analyzer: {i+2}차 백업 모델로 재시도...")
                    continue
                else:
                    print("Query Analyzer: 모든 백업 모델 실패, 기본값 사용")
                    break
            else:
                # 다른 에러는 즉시 백업 모델로 시도
                if i < len(models_to_try) - 1:
                    print(f"Query Analyzer: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                    continue
                else:
                    print("Query Analyzer: 모든 모델 실패, 기본값 사용")
                    break

    # 토큰/비용 계산
    model_name_for_calc = used_model_name or (getattr(models_to_try[0], "model", "") or "")
    prompt_tokens = _count_messages_tokens([query_analyzer_prompt.system, query_analyzer_prompt.human], model_name_for_calc)
    completion_json = json.dumps({
        "Chat": chat,
        "Shift": shift,
        "Preference": preference,
        "Others": others
    }, ensure_ascii=False)
    completion_tokens = _count_tokens(completion_json, model_name_for_calc)
    cost_info = _compute_cost(prompt_tokens, completion_tokens, model_name_for_calc)

    print(f"Query Analyzer 답변: query_chat: {chat}, query_shift: {shift}, query_preference: {preference}, query_others: {others}")
    print(f"토큰 사용량: {cost_info['usage']}, 비용(USD/KRW): {cost_info['cost_usd']} / {cost_info['cost_krw']}")
    return {
        "query_chat": chat,
        'query_shift': shift,
        'query_preference': preference,
        'query_others': others,
        'model': models_to_try[0]
    }



