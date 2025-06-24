
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
import os
from langchain_core.messages import SystemMessage, HumanMessage
            # * 답변 시 알 수 없는 정보를 요구한다면, 아래 도구 목록을 참고해, 필요하다면 한 번에 하나의 tool 을 호출할 수 있습니다. 
            # 도구 호출이 적절치 않을 경우 직접 답변만 작성하세요.  
            # {tools[0]}
            # * 답변 작성을 위한 processor는 도구가 필요함을 캐치하고, 어떤 도구와 어떤 인자가 필요할 지 정확히 명시해야 합니다.


def collector(state):
    """
    information collector
    """

def init_data(state):
    """
    initialize data
    """
    return state

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
    score: List[int] 

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
            당신은 간호사 근무표 시스템의 “희망·비선호 스코어 추출기”입니다.  
            입력 문장(자연어) ➜ 구조화 JSON 으로 변환해 주세요.

            1. Request Type  (가중치 보정치)
            | Type    | 설명                              | Modifier |
            |-|-|-:|
            | off     | 강제 OFF (가중치 유지)            | × 1.0 |
            | shift   | 특정 Shift 지정                   | × 0.9 |
            | keep    | 주기 요청(매주 같은 요일 등)      | × 0.8 |
            | pattern | “DD→N” “ N 후 OFF” 같은 규칙      | × 0.7 |
            | other   | 정책외 항목 (가중치 계산 안함)     | – |

            2. Request Importance  (기본 가중치)
            | Score | 우선순위·사유(예시)                            | 허용 Type                | 근거 요약                    |
            |-:|-|-|-|
            | 5 | 법·병원 필수(임신 야간금지, 단축근무 등)       | shift / keep / off       | 법규·지침 미준수 리스크      |
            | 4 | 생명·건강 위기(가족 중증, 항암, 응급수술)      | off / shift              | 안전·장기결근 예방           |
            | 3 | 사회·가족 의무·직무(결혼·장례·교육·멘토링)    | off / shift / pattern    | 조직도 인지 필수 일정        |
            | 2 | 중요 개인계획(가족 행사, 장거리 통근, 학업)    | off / shift / keep / pattern | 가능 시 배려            |
            | 1 | 선호·편의(“친한 동료랑”, 막연한 선호)         | keep / pattern           | 효율 < 상위 우선순위         |
            | 0 | 정책외/미지원(휴무 초과, 병동 고정 요청 등)    | other                    | 수간호사 직접 조율(Hard 0)   |

            최종 가중치 = Importance Score × Type Modifier

            3. 필수 매핑 규칙
            * ‘Day shift’ → "D", ‘Evening’ → "E", ‘Night’ → "N", ‘Off’ → "OFF"
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
                "OFF": {{ ... }}
            }}
            }}
            ```
            5. 처리 절차

            * 발화에서 Request 유형과 중요도를 판정하고 이유를 기록.
            * 중요도 점수 × 유형 Modifier 로 최종 weight 계산.
            * 날짜/Shift 구체화 → result 채우기.
            * (기간형 “5월 둘째 주” 등은 별도 날짜모듈에서 변환되었다고 가정)
            * 해석 불가 문장·모호 표현은 request_type="other" 로.



            ### 입력 예시
            “5월 12일은 아들 발표회니까 꼭 쉬고 싶어요”

            ### 출력 예시
            {{
                "processor": "5월 12일 OFF 요청 반영",
                "request_type": "off",
                "request_type_reason": "특정 날짜 OFF 요청",
                "request_importance": 3,
                "request_importance_reason": "자녀 학교행사 → Score 3",
                "result": {{ "OFF": {{ "12": 3.0 }} }}
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
                "result":{{"shift": "OFF", "date":[12], "score":[3.0]}}}}

            """
                
        self.human=f"""
            # CONTEXT: 
                {context}
            # OUTPUT:
            """

async def shift_analyzer(state):
    print('여기_shift')
    client = state['model']
    client = ChatAnthropic(
        model="claude-3-7-sonnet-20250219",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    phase = state['phase']
    context = state['requests'][phase]
    # context = "일단 문선생님이랑은 무조건 따로 하고싶고, 천간호사랑 계속 같이 있고싶어요.. 진짜 많이 도와줘서 행복해요.. 그리고 웬만하면 D는 안하고 싶어요 ㅠ"
    print('\n\n\n여까진옴\n\n\n')
    tools = state['mcp_tools']
    # print('\n\n\n\n\n\n',type(tools[0]),'\n\n\n\n\n\n')
    shift_analyzer_prompt = shiftAnalyzerPrompt(context)
    # print('\n\n\n\n\n\n',shift_analyzer_prompt.human,'\n\n\n\n\n\n')
    # print('\n\n\n\n\n\n',shift_analyzer_prompt.system,'\n\n\n\n\n\n')
    agent = create_react_agent(client, tools, response_format=shiftAnalyzer)
    # response = client.models.generate_content(
    #     model="gemini-2.0-flash",
    #     contents=[shift_analyzer_prompt.human],                       # or [pil_img, information]
    #     config=types.GenerateContentConfig(
    #         # response_mime_type="application/json",
    #         # response_schema=shiftAnalyzer,      # ★ 핵심: Root 모델
    #         system_instruction=shift_analyzer_prompt.system,

    #     ),
    # )
    print('\n\n\n\n\n\n완료11\n\n\n\n\n\n')
    result = await agent.ainvoke({"messages": [SystemMessage(content=shift_analyzer_prompt.system), HumanMessage(content=shift_analyzer_prompt.human)]})
    # parts = response.candidates[0].content.parts
    print('\n\n\n\n\n\n완료\n\n\n\n\n\n')
    sr: shiftAnalyzer = result["structured_response"]
    print('\n\n\n\n\n\nsr: ',sr.result,'\n\n\n\n\n\n')
    # print('\n\n\n\n\n\n',parts[0].text,'\n\n\n\n\n\n')
    # print(json.loads(parts[0].text))
    # json_answer = json.loads(parts[0].text)
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
    print('툴즈~~~', tools)
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
