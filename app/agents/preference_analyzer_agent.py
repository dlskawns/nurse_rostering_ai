import json
from pydantic import BaseModel
from typing import List, TypedDict, Annotated, operator
from google import genai
from google.genai import types
from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
import os
import dotenv
try:
    import tiktoken
except Exception:
    tiktoken = None

dotenv.load_dotenv()

class PreferenceSubgraph(TypedDict):
    requests: List[str]
    n_requests: int
    phase: int
    schema: object
    preference_result: Annotated[list, operator.add]
    model: object


def collector(state):
    """
    information collector
    """


def init_data(state):
    """
    initialize data
    """


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
    """
    name = (model_name or "").lower()
    input_usd, output_usd = 0.003, 0.009
    if "gpt-4o" in name:
        input_usd, output_usd = 0.005, 0.015
    elif "claude" in name:
        input_usd, output_usd = 0.003, 0.015
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


class preferenceAnalyzer(BaseModel):
    processor: str
    id : str
    weight : float
    reason : str
    request : str

class preferenceAnalyzerPrompt:
    def __init__(self, schem, query):
        """
        프롬프트 클래스
        """
        self.system = f"""
            # 역할
            당신은 "간호사 근무표 엔진"용 **선호 스코어 추출기**입니다.  
            입력으로 자연어 문장(한국어·영어·혼합)을 받으면, 간호사 간 pair-score 와 개인 shift-score 로 변환해 JSON 으로 출력합니다.

            # 입력 스키마
            - nurses : 객체 배열  
            ```json
            {{ "id": int, "name": str, "exp": float,
                "is_head": bool, "is_night_nurse": int }}
            ```
            * utterances : 문자열 배열
                (간호사들의 "같이 하고 싶어/싫어, 겹치지 말아줘" 등 자유 서술)

            # 출력 스키마
            ```json
            {{
                "processor": "분석 과정 설명",
                "id": "nurse_id",
                "weight": 0.0,
                "reason": "선호/기피 이유"
            }}
            ```

            # 가이드라인
                1. 매핑 규칙
                    | 표현 패턴        | 예시                       | weight               |
                    | ------------ | ------------------------ | -------------------- |
                    | **강한 선호**    | "꼭 ○○쌤이랑" "무조건 같이"       | +3.0                 |
                    | **보통 선호**    | "가능하면 ○○쌤" "같이 하고 싶어"    | +1.5                 |
                    | **보통 기피**    | "가급적 ○○쌤은 피하고"           | −1.5                 |
                    | **강한 기피**    | "절대 ○○쌤이랑 싫어" "제발 안 겹치게" | −2.0                 |
                    | **모호/농담/없음**    | "○○쌤이랑은 글쎄요ㅎㅎ"           | 0 |
                3. 규칙
                    * id 매핑은 이름 완전일치 우선, 이름도, 성도 찾지 못하면 ignored(0).
                    * 팩트 없는 추론·환상 (hallucination)은 금지.
                    * 정규화·후처리는 다운스트림 엔진이 수행하므로 weight 범위만 지켜라.
                4. 예시 입출력
                    <입력>
                    ```json
                        {{
                        "nurses":[
                        {{"nurse_id":"slfnam1","name":"김가희","exp":6,"is_head":false,"is_night_nurse":0}},
                        {{"nurse_id":"mlnwjk2","name":"박수정","exp":3,"is_head":false,"is_night_nurse":1}},
                        {{"nurse_id":"ooonsjk3","name":"이해린","exp":10,"is_head":true,"is_night_nurse":0}}
                        ],
                        "utterances":[
                        "저 박수정 쌤이랑은 제발 안 겹치게 해주세요…😭"
                        ]
                        }}
                    ```
                    <출력>
                    ```json
                        {{
                        "processor": "'박수정 쌤'은 정보상 nurse_id가 'mlnwjk2'이고, 강한 기피를 표현하니 가중치는 -2로 줘야할 것 같아.",
                        "id": "mlnwjk2",
                        "weight": -2.0,
                        "reason": "강한 기피 표현",
                        "request": "저 박수정 쌤이랑은 제발 안 겹치게 해주세요…😭"
                        }}
                    ```
                5. 출력 형식
                    * 반드시 위 JSON 구조만 반환 (불필요한 문장·주석 x)
                    * 여러 명이 언급되면 가장 중요한/명확한 한 명만 선택
            """
                
        self.human=f"""
            # INPUT SCHEMA: 
                {schem}
                * utterances:
                {query} 
            # OUTPUT:
            """

async def preference_analyzer(state):
    
    phase = state['phase']
    query = state['requests'][phase]
    data = state['schema']
    
    preference_analyzer_prompt = preferenceAnalyzerPrompt(data, query)
    
    # 백업 모델들 순서대로 시도
    models_to_try = [
        # 1차: OpenAI (기본)
        ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
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
        SystemMessage(content=preference_analyzer_prompt.system),
        HumanMessage(content=preference_analyzer_prompt.human)
    ]
    
    json_answer = {
        "processor": "기본값 설정",
        "id": "",
        "weight": 0.0,
        "reason": "처리 실패",
        "request": query
    }
    used_model_name = ""
    
    for i, client in enumerate(models_to_try):
        try:
            
            print(f"Preference Analyzer: {i+1}차 모델 시도 중...")
            
            llm = client.with_structured_output(preferenceAnalyzer)

            response = await llm.ainvoke(messages)
            used_model_name = getattr(client, "model", "") or used_model_name
            print('used_model_name', used_model_name)

            # 성공 시 데이터 추출
            json_answer = {
                "processor": response.processor,
                "id": response.id,
                "weight": response.weight,
                "reason": response.reason,
                "request": query
            }
            
            # ID 검증: schema에 존재하는 간호사인지 확인
            valid_nurse_ids = []
            if isinstance(data, list):
            
                valid_nurse_ids = [nurse.get('nurse_id', '') for nurse in data if isinstance(nurse, dict)]
            elif isinstance(data, dict) and 'nurses' in data:
            
                nurses = data.get('nurses', [])
                valid_nurse_ids = [nurse.get('nurse_id', '') for nurse in nurses if isinstance(nurse, dict)]
            
            # 추출된 id가 유효한 간호사 ID가 아니면 빈 값으로 처리
            if json_answer["id"] and json_answer["id"] not in valid_nurse_ids:
                print(f"Preference Analyzer: 무효한 간호사 ID '{json_answer['id']}' - 빈 값으로 처리")
                json_answer = {
                    "processor": f"언급된 간호사를 찾을 수 없어 무시됨: {response.processor}",
                    "id": "",
                    "weight": 0.0,
                    "reason": "해당하는 간호사가 스키마에 존재하지 않음",
                    "request": query
                }
            
            print(f"Preference Analyzer: {i+1}차 모델 성공!")
            break
            
        except Exception as e:
            error_msg = str(e).lower()
            print(f"Preference Analyzer: {i+1}차 모델 오류 - {e}")
            
            # 429 (Rate limit) 또는 529 (Service unavailable) 에러인지 확인
            if ("429" in error_msg or "rate" in error_msg or 
                "529" in error_msg or "service unavailable" in error_msg or
                "quota" in error_msg or "limit" in error_msg):
                
                if i < len(models_to_try) - 1:
                    print(f"Preference Analyzer: {i+2}차 백업 모델로 재시도...")
                    continue
                else:
                    print("Preference Analyzer: 모든 백업 모델 실패, 기본값 사용")
                    break
            else:
                # 다른 에러는 즉시 백업 모델로 시도
                if i < len(models_to_try) - 1:
                    print(f"Preference Analyzer: 예상치 못한 오류, {i+2}차 백업 모델로 재시도...")
                    continue
                else:
                    print("Preference Analyzer: 모든 모델 실패, 기본값 사용")
                    break
    
    # 토큰/비용 계산
    model_name_for_calc = used_model_name or (getattr(models_to_try[0], "model", "") or "")
    prompt_tokens = _count_messages_tokens([preference_analyzer_prompt.system, preference_analyzer_prompt.human], model_name_for_calc)
    completion_json = json.dumps(json_answer, ensure_ascii=False)
    completion_tokens = _count_tokens(completion_json, model_name_for_calc)
    cost_info = _compute_cost(prompt_tokens, completion_tokens, model_name_for_calc)
    print(f"토큰 사용량(Preference): {cost_info['usage']}, 비용(USD/KRW): {cost_info['cost_usd']} / {cost_info['cost_krw']}")
    
    return {'preference_result': [json_answer]}


async def create_preference_analyzer(parent_state):
    requests = parent_state['query_preference']         # Shift List ex. ["9/9: D", "9/10: D", "9/16: OFF", "9/9, 9/10, 9/16 외에 웬만하면 E로 줘"]
    schema = parent_state['schema']
    client = parent_state['model']
    n_requests = len(requests)
    if n_requests == 0:
        return {"preference_results": []}
    graph = StateGraph(PreferenceSubgraph)
    
    graph.add_node("init_data", init_data)
    graph.add_node("collector", collector)
    graph.set_entry_point('init_data')
    for n in range(n_requests):
        def create_preference_node(n):
            async def wrapped_shift(state):
                state['phase']= n
                return await preference_analyzer(state)
            return wrapped_shift
        graph.add_node('preference_analyzer' +str(n), create_preference_node(n))
        graph.add_edge('init_data', 'preference_analyzer' +str(n))
        graph.add_edge('preference_analyzer'+ str(n), "collector")

    graph.add_edge('collector', END)
    graph_app = graph.compile()

    result = await graph_app.ainvoke({"requests": requests, "schema": schema, "model": client})
    print(f'\n\n\n\n\npreference_results, {result}\n\n\n\n\n')
    return {"preference_results": [result]}

