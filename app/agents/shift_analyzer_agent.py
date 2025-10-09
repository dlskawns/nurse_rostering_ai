import json
from pydantic import BaseModel
from typing import List, TypedDict, Annotated, operator, Dict
from google import genai
from google.genai import types
from langgraph.graph import StateGraph, END
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
import os
from langchain_core.messages import SystemMessage, HumanMessage
import dotenv
from datetime import datetime
try:
    import tiktoken
except Exception:
    tiktoken = None
            # * 답변 시 알 수 없는 정보를 요구한다면, 아래 도구 목록을 참고해, 필요하다면 한 번에 하나의 tool 을 호출할 수 있습니다. 
            # 도구 호출이 적절치 않을 경우 직접 답변만 작성하세요.  
            # {tools[0]}
            # * 답변 작성을 위한 processor는 도구가 필요함을 캐치하고, 어떤 도구와 어떤 인자가 필요할 지 정확히 명시해야 합니다.

dotenv.load_dotenv()


def collector(state):
    """
    information collector
    """
    return state


def init_data(state):
    """
    initialize data
    """
    return state


# ------------------------------
# 비용/토큰 유틸리티
# ------------------------------
def _krw_per_usd() -> float:
    try:
        return float(os.getenv("KRW_PER_USD", "1350"))
    except Exception:
        return 1350.0


def _pricing_per_1k(model_name: str) -> tuple[float, float]:
    name = (model_name or "").lower()
    input_usd, output_usd = 0.003, 0.009
    if "claude" in name:
        input_usd, output_usd = 0.003, 0.015
    elif "gpt-4o" in name:
        input_usd, output_usd = 0.005, 0.015
    elif "gemini" in name:
        input_usd, output_usd = 0.00035, 0.00105
    return input_usd, output_usd


def _encoding_for_model(model_name: str):
    name = (model_name or "").lower()
    try:
        if "gpt" in name or "o" in name:
            return tiktoken.get_encoding("o200k_base")
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _count_tokens(text: str, model_name: str) -> int:
    if not text:
        return 0
    enc = _encoding_for_model(model_name)
    if enc is None:
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


class ShiftSubgraph(TypedDict):
    requests: List[str]
    n_requests: int
    phase: int
    # mcp_agent: object
    shift_result: Annotated[list, operator.add]
    model: object
    # mcp_tools: object
    year: int
    month: int
    weekend_holiday: Dict[str, List[str]]

class shiftResponse(TypedDict):
    shift: str 
    date: List[int] 
    score: List[float] 

class shiftAnalyzer(BaseModel):
    processor: str
    request_type: str | None 
    request_type_reason: str 
    request_importance: str | None 
    request_importance_reason: str | None 
    result: shiftResponse | None 

class shiftAnalyzerPrompt:
    def __init__(self, context, year: int, month: int, weekend_holiday: Dict[str, List[str]] | None = None):
        """
        프롬프트 클래스
        """
        self.system = f"""
            # GOAL:
            You are the "Preference & Avoidance Score Extractor" for the nurse scheduling system.  
            Input sentences (Korean/English/mixed natural language) ➜ must be converted into structured JSON.

            ## 1. Request Type (Weight Modifier)
            | Type    | Description                          | Modifier |
            |---------|--------------------------------------|----------|
            | off     | Forced OFF (weight preserved)        | × 2      |
            | shift   | Specific Shift assignment            | × 1.9    |
            | keep    | Recurring request (weekly, etc.)     | × 1.8    |
            | pattern | Rules like "DD→N", "N followed by O" | × 1.7    |
            | other   | Non-policy items (no weight applied) | –        |

            ---

            ## 2. Request Importance (Base Weight)
            | Score | Priority/Reason (Examples)                   | Allowed Type                  | Rationale Summary            |
            |-------|----------------------------------------------|-------------------------------|------------------------------|
            | 5     | Legal/Hospital mandatory (e.g., pregnancy night-ban, reduced hours) | shift / keep / off | Risk of regulation violation |
            | 4     | Life/Health crisis (family critical illness, chemo, emergency surgery) | off / shift | Safety & absence prevention |
            | 3     | Social/Family duties (wedding, funeral, education, mentoring) | off / shift / pattern | Must be recognized by unit   |
            | 2     | Important personal plans (family event, long commute, study) | off / shift / keep / pattern | Should be considered if possible |
            | 1     | Preference/Convenience ("with a close colleague", vague liking) | keep / pattern | Efficiency < higher priorities |
            | 0     | Out of policy/unsupported (too many offs, fixed ward request) | other | Head nurse direct coordination (Hard 0) |

            **Final weight = Importance Score × Type Modifier**

            ---

            ## 3. Mandatory Mapping Rules
            * "Day shift" → "D", "Evening" → "E", "Night" → "N", "Off" → "O"
            * Weight range: 0 ~ 5 (decimals allowed)

            [Exclusion/NOT Rules]
            - For negative expressions such as "X 말고/빼고/제외/안 돼", do NOT infer alternatives.  
            - "X or Y 말고" → Both X and Y are excluded.  
            - If exclusion and preference conflict in the same scope, exclusion takes priority.

            ---

            ## 4. Output JSON Schema
            ```json
            {{
            "request_type": "off|shift|keep|pattern|other",
            "request_type_reason": "string",
            "request_importance": 0-5,
            "request_importance_reason": "string",
            "processor": "Explain why this interpretation was made",
            "result": {{
                "D": {{ "1":2.5, "3":2.5, ... }},
                "E": {{ ... }},
                "N": {{ ... }},
                "O": {{ ... }}
            }}}}
            ```
            5. Processing Steps
            Identify request type and importance score from utterance, and record reasons.
            Calculate final weight = Importance Score × Type Modifier.
            Specify date/shift details → fill result.
            (For periods like "second week of May", assume date module has pre-converted them.)
            If interpretation is not possible or expression is ambiguous → set request_type="other".


            ### Input Example
            "5월 12일은 아들 발표회니까 꼭 쉬고 싶어요"

            ### Output Example
            {{
                "processor": "5월 12일 OFF 요청 반영",
                "request_type": "off",
                "request_type_reason": "특정 날짜 OFF 요청",
                "request_importance": 3,
                "request_importance_reason": "자녀 학교행사 → Score 3",
                "result": {{ "O": {{ "12": 3.0 }} }}
                }}

            이 지침을 충실히 따르세요. 추가 설명·주석은 포함하지 마십시오.

            # CONTEXT:
                "웬만하면 E로 줘"

            # OUTPUT:
                {{"processor": "웬만하면이라는 기간이 확정되지 않는 상황이며, 5월은 31일이므로 31일 전체에 원하는 shift E를 부여",
                "request_type": "keep",
                "request_type_reason": "특별한 이유는 없지만, E로 달라고 하는 것을 볼 수 있음",
                "request_importance": "1",
                "request_importance_reason": "특별한 이유를 이야기 하지 않음",
                "result": {{
                    "shift": "E",
                    "date": [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31],
                    "score":[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]"
                }}
                }}

            # CONTEXT:
                "5월 12일은 아들 어린이집 발표회라서 꼭 OFF 부탁드려요."

            # OUTPUT:
                {{"processor": "5월 12일자에 자녀 학교 행사로 OFF 가중치 3을 적용",
                "request_type": "off",
                "request_type_reason": "발표회로 인해 OFF를 요청하고 있음",
                "request_importance": "3",
                "request_importance_reason": "자녀 학교행사 등에 포함되어 3의 가중치를 선정",
                "result":{{"shift": "O", "date":[12], "score":[3.0]}}}}

            # CONTEXT:
                "23일은 off뺴고 다 좋아"

            # OUTPUT:
                {{"processor": "off 제외 건이므로 추론 하지 않을 것",
                "request_type": None,
                "request_type_reason": "제외 건은 추론 하지 않을 것",
                "request_importance": None,
                "request_importance_reason": None,
                "result":None}}

            """
        
        weekends_json = json.dumps((weekend_holiday or {}).get("weekends", []), ensure_ascii=False)
        holidays_json = json.dumps((weekend_holiday or {}).get("holidays", []), ensure_ascii=False)
        self.human=f"""
            # CONTEXT: 
                {year}년 {month}월 기준 근무 희망 요청입니다.
                주말은 {weekends_json} 입니다.
                공휴일은 {holidays_json} 입니다.

                {context}
            # OUTPUT:
            """

async def shift_analyzer(state):
    phase = state['phase']
    context = state['requests'][phase]
    # tools = state['mcp_tools']
    year = state['year']
    month = state['month']
    weekend_holiday = state['weekend_holiday']
    
    shift_analyzer_prompt = shiftAnalyzerPrompt(context, year, month, weekend_holiday)
    print(f'\n\n\n\n\nshift_analyzer_prompt, {shift_analyzer_prompt.human}\n\n\n\n\n')
    # 백업 모델들 순서대로 시도
    models_to_try = [
        # 1차: Anthropic (기본)
        # ChatAnthropic(
        #     model="claude-sonnet-4-20250514",
        #     anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        # ),

        # 2차: OpenAI (백업)
        ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        ),
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
    
    sr = None
    used_model_name = ""
    for i, client in enumerate(models_to_try):
        try:
            print(f"Shift Analyzer: {i+1}차 모델 시도 중..., 모델: {client}")
            # agent = create_react_agent(client, tools, response_format=shiftAnalyzer)
            llm = client.with_structured_output(shiftAnalyzer)
            response = await llm.ainvoke([
                SystemMessage(content=shift_analyzer_prompt.system), 
                HumanMessage(content=shift_analyzer_prompt.human)
            ])

            # result = await agent.ainvoke({
            #     "messages": [
            #         SystemMessage(content=shift_analyzer_prompt.system), 
            #         HumanMessage(content=shift_analyzer_prompt.human)
            #     ]
            # })
            # print('response', response)
            sr = response
            print(f"Shift Analyzer1111: {sr}")
                
            used_model_name = getattr(client, "model", "") or used_model_name
            print(f"Shift Analyzer: {i+1}차 모델 성공!")
            break
            
        except Exception as e:
            error_msg = str(e).lower()
            print(f"Shift Analyzer: {i+1}차 모델 오류 - {e}")
            
            # 429 (Rate limit) 또는 529 (Service unavailable) 에러인지 확인
            if ("429" in error_msg or "rate" in error_msg or 
                "529" in error_msg or "service unavailable" in error_msg or
                "quota" in error_msg or "limit" in error_msg):
                
                if i < len(models_to_try) - 1:
                    print(f"Shift Analyzer: {i+2}차 백업 모델로 재시도...")
                    continue
                else:
                    print("Shift Analyzer: 모든 백업 모델 실패, 기본값 사용")
                    # 기본값 설정
                    from types import SimpleNamespace
                    sr = SimpleNamespace()
                    sr.result = {"shift": "O", "date": [], "score": []}
                    break
            else:
                # 다른 에러는 즉시 백업 모델로 시도
                if i < len(models_to_try) - 1:
                    print(f"Shift Analyzer: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                    continue
                else:
                    print("Shift Analyzer: 모든 모델 실패, 기본값 사용")
                    # 기본값 설정
                    from types import SimpleNamespace
                    sr = SimpleNamespace()
                    sr.result = {"shift": "O", "date": [], "score": []}
                    break
    
    # 토큰/비용 계산
    model_name_for_calc = used_model_name or (getattr(models_to_try[0], "model", "") or "")
    prompt_tokens = _count_messages_tokens([shift_analyzer_prompt.system, shift_analyzer_prompt.human], model_name_for_calc)
    completion_json = json.dumps(sr.result if sr else {"shift": "O", "date": [], "score": []}, ensure_ascii=False)
    completion_tokens = _count_tokens(completion_json, model_name_for_calc)
    cost_info = _compute_cost(prompt_tokens, completion_tokens, model_name_for_calc)
    print(f"토큰 사용량(Shift): {cost_info['usage']}, 비용(USD/KRW): {cost_info['cost_usd']} / {cost_info['cost_krw']}")
    # print(f"Shift Analyzer: {sr.result}")
    sr.result['request'] = [context] * len(sr.result['date'])
    # print(f'\n\n\n\n\nshift_result, {sr.result}\n\n\n\n\n')
    if sr.result is None:
        return {"shift_result": []}
    else:
        return {"shift_result": [sr.result]}

from services.holiday_pack import tool_get_weekends, tool_get_holidays
from services.holiday_pack import get_weekends as _get_weekends, get_korean_public_holidays as _get_holidays, serialise as _serialise
from langchain_core.tools import tool
from agents.query_analyzer_agent import query_analyzer

# from services.holiday_pack import get_weekends as _get_weekends, get_korean_public_holidays as _get_holidays, serialise as _serialise
# from langchain_core.tools import Tool


async def create_shift_analyzer(parent_state):
    """
    Shift 분석기 생성 및 실행
    
    Args:
        parent_state: 부모 그래프의 상태
        
    Returns:
        Dict: shift_results를 포함한 결과
        
    Notes:
        - case_results가 있으면 LLM 호출 없이 바로 반환
        - query_shift가 없으면 빈 결과 반환
    """
    # ======================================================================
    # case_results가 있으면 LLM 호출 없이 바로 반환
    # ======================================================================
    case_results = parent_state.get('case_results')
    if case_results is not None:
        print(f"Shift Analyzer: case_results 감지 - LLM 호출 생략, 데이터 직접 반환")
        print(f"case_results: {case_results}")
        
        # case_results를 shift_results 형태로 변환
        # case_results 형태: [{'date': 11, 'shift': 'D', 'score': 1.0, 'request': '단순 희망'}]
        # shift_results 형태: [[{'shift_result': [{'shift': 'D', 'date': [11], 'score': [1.0], 'request': ['단순 희망']}]}]]
        
        from collections import defaultdict
        shift_groups = defaultdict(lambda: {'date': [], 'score': [], 'request': []})
        
        for item in case_results:
            shift_type = item.get('shift')
            date_val = item.get('date')
            score_val = item.get('score', 1.0)
            request_val = item.get('request', '단순 희망')
            
            shift_groups[shift_type]['date'].append(date_val)
            shift_groups[shift_type]['score'].append(score_val)
            shift_groups[shift_type]['request'].append(request_val)
        
        shift_result_list = [
            {
                'shift': shift_type,
                'date': data['date'],
                'score': data['score'],
                'request': data['request']
            }
            for shift_type, data in shift_groups.items()
        ]
        
        return {"shift_results": [{'shift_result': shift_result_list}]}

    # ======================================================================
    # 일반 경로: LLM을 사용한 shift 분석
    # ======================================================================
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )

    # llm = ChatAnthropic(
    #         model="claude-sonnet-4-20250514",
    #         anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
    #     ),
    requests = parent_state['query_shift']         # Shift List ex. ["9/9: D", "9/10: D", "9/16: OFF", "9/9, 9/10, 9/16 외에 웬만하면 E로 줘"]
    client = parent_state['model']

    # 기본 제공 도구: 주말/공휴일 + 질의 정규화
    # tools = [tool_get_weekends, tool_get_holidays, tool_analyze_query]
    year = parent_state['year']
    month = parent_state['month']
    n_requests = len(requests)

    # 주말/공휴일 정보 미리 계산하여 상태에 주입
    try:
        weekends = tool_get_weekends(year, month)
        holidays = tool_get_holidays(year, month)
        # 일요일만 필터링해서 holidays에 추가
        for d in weekends:
            if datetime.strptime(d, "%Y-%m-%d").weekday() == 6:  # 일요일: 6
                if d not in holidays:  # 중복 방지
                    holidays.append(d)
        weekend_holiday = {"weekends": weekends, "holidays": holidays}
    except Exception as e:
        print(f"주말/공휴일 계산 오류: {e}")
        weekend_holiday = {"weekends": [], "holidays": []}
    if n_requests == 0:
        print('shift_analyzer 답변 없음')
        return {"shift_results": []}
    graph = StateGraph(ShiftSubgraph)
    graph.add_node("init_data", init_data)
    graph.add_node("collector", collector)
    graph.set_entry_point('init_data')
    for n in range(n_requests):
        def create_shift_node(n):
            async def wrapped_shift(state):
                state['phase']= n
                return await shift_analyzer(state)
            return wrapped_shift
        graph.add_node('shift_analyzer' +str(n), create_shift_node(n))
        graph.add_edge('init_data', 'shift_analyzer' +str(n))
        graph.add_edge('shift_analyzer'+ str(n), "collector")
    graph.add_edge('collector', END)
    graph_app = graph.compile()
    print('weekend_holiday', weekend_holiday)
    try:
        result = await graph_app.ainvoke({
            "requests": requests,
            "model": llm,
            # "mcp_tools": tools,
            "year": year,
            "month": month,
            "weekend_holiday": weekend_holiday,
        })
    except Exception as e:
        print(f"shift_analyzer 처리오류: {e}")
        
    print(f'\n\n\n\n\nshift_results, {result}\n\n\n\n\n')
    return {"shift_results": [result]}
