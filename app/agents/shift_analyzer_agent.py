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
    mcp_tools: object

class shiftResponse(TypedDict):
    shift: str 
    date: List[int] 
    score: List[float] 

class shiftAnalyzer(BaseModel):
    processor: str
    request_type: str 
    request_type_reason: str 
    request_importance: str 
    request_importance_reason: str 
    result: shiftResponse

class shiftAnalyzerPrompt:
    def __init__(self, context):
        """
        프롬프트 클래스
        """
        self.system = f"""
            # GOAL:
            당신은 간호사 근무표 시스템의 "희망·비선호 스코어 추출기"입니다.  
            입력 문장(자연어) ➜ 구조화 JSON 으로 변환해 주세요.

            1. Request Type  (가중치 보정치)
            | Type    | 설명                              | Modifier |
            |-|-|-:|
            | off     | 강제 OFF (가중치 유지)            | × 2 |
            | shift   | 특정 Shift 지정                   | × 1.9 |
            | keep    | 주기 요청(매주 같은 요일 등)      | × 1.8 |
            | pattern | "DD→N" " N 후 OFF" 같은 규칙      | × 1.7 |
            | other   | 정책외 항목 (가중치 계산 안함)     | – |

            2. Request Importance  (기본 가중치)
            | Score | 우선순위·사유(예시)                            | 허용 Type                | 근거 요약                    |
            |-:|-|-|-|
            | 5 | 법·병원 필수(임신 야간금지, 단축근무 등)       | shift / keep / off       | 법규·지침 미준수 리스크      |
            | 4 | 생명·건강 위기(가족 중증, 항암, 응급수술)      | off / shift              | 안전·장기결근 예방           |
            | 3 | 사회·가족 의무·직무(결혼·장례·교육·멘토링)    | off / shift / pattern    | 조직도 인지 필수 일정        |
            | 2 | 중요 개인계획(가족 행사, 장거리 통근, 학업)    | off / shift / keep / pattern | 가능 시 배려            |
            | 1 | 선호·편의("친한 동료랑", 막연한 선호)         | keep / pattern           | 효율 < 상위 우선순위         |
            | 0 | 정책외/미지원(휴무 초과, 병동 고정 요청 등)    | other                    | 수간호사 직접 조율(Hard 0)   |

            최종 가중치 = Importance Score × Type Modifier

            3. 필수 매핑 규칙
            * 'Day shift' → "D", 'Evening' → "E", 'Night' → "N", 'Off' → "O"
            * weight 범위 : 0 ~ 5 (소수점 허용)

            4. 출력 JSON 스키마
            ```json
            {{
            "request_type": "off|shift|keep|pattern|other",
            "request_type_reason": "string",
            "request_importance": 0-5,
            "request_importance_reason": "string",
            "processor": "GPT가 해석한 간단 설명",
            "result": {{
                "D"  : {{ "1":2.5, "3":2.5, ... }},
                "E"  : {{ ... }},
                "N"  : {{ ... }},
                "O": {{ ... }}
            }}
            }}
            ```
            5. 처리 절차

            * 발화에서 Request 유형과 중요도를 판정하고 이유를 기록.
            * 중요도 점수 × 유형 Modifier 로 최종 weight 계산.
            * 날짜/Shift 구체화 → result 채우기.
            * (기간형 "5월 둘째 주" 등은 별도 날짜모듈에서 변환되었다고 가정)
            * 해석 불가 문장·모호 표현은 request_type="other" 로.



            ### 입력 예시
            "5월 12일은 아들 발표회니까 꼭 쉬고 싶어요"

            ### 출력 예시
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

            """
                
        self.human=f"""
            # CONTEXT: 
                {context}
            # OUTPUT:
            """

async def shift_analyzer(state):
    print('여기_shift')
    # client = state['model']
    # client = ChatAnthropic(
    #     model="claude-3-7-sonnet-20250219",
    #     anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
    # )
    phase = state['phase']
    context = state['requests'][phase]
    tools = state['mcp_tools']
    
    shift_analyzer_prompt = shiftAnalyzerPrompt(context)
    
    # 백업 모델들 순서대로 시도
    models_to_try = [
        # 1차: Anthropic (기본)
        ChatAnthropic(
            model="claude-3-7-sonnet-20250219",
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        ),
        # 2차: OpenAI (백업)
        ChatOpenAI(
            model="gpt-4o",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
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
            print(f"Shift Analyzer: {i+1}차 모델 시도 중...")
            
            agent = create_react_agent(client, tools, response_format=shiftAnalyzer)
            result = await agent.ainvoke({
                "messages": [
                    SystemMessage(content=shift_analyzer_prompt.system), 
                    HumanMessage(content=shift_analyzer_prompt.human)
                ]
            })
            
            sr = result["structured_response"]
            used_model_name = getattr(client, "model", "") or used_model_name
            print(f"Shift Analyzer: {i+1}차 모델 성공!")
            print('\n\n\n\n\n\nsr: ',sr.result,'\n\n\n\n\n\n')
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
    
    return {"shift_result": [sr.result]}


async def create_shift_analyzer(parent_state):
    mcp_client = MultiServerMCPClient(
        {
            "weather": {
                "url": "http://localhost:8005/sse",  # 서버 포트와 일치
                "transport": "sse",
            }
        }
    )
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )
    # print('여기', mcp_client.get_tools())
    requests = parent_state['query_shift']         # Shift List ex. ["9/9: D", "9/10: D", "9/16: OFF", "9/9, 9/10, 9/16 외에 웬만하면 E로 줘"]
    client = parent_state['model']

    tools = await mcp_client.get_tools()
    # print('툴즈~~~', tools)
    n_requests = len(requests)
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

    result = await graph_app.ainvoke({"requests": requests, "model": llm, "mcp_tools": tools})
    print('shift_analyzer 답변: ', result)
    return {"shift_results": [result]}
