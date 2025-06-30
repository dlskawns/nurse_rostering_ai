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

dotenv.load_dotenv()

print(dotenv.load_dotenv())
class queryAnalyzer(BaseModel):
    Chat: List[str] 
    Shift: List[str] 
    Preference: List[str]
    Others: List[str] 


class queryAnalyzerPrompt:
    def __init__(self, context):
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
                4. 절대 중복/혼합 금지: 한 요소에 OFF와 E 같이 넣지 마세요.
                5. 최종 JSON 키
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
                | Off/휴무    | "OFF" |
                | 날짜 구분     | `M/D`  또는 `M월 D일` 등 모두 허용, 출력은 원문 그대로 보존 |

            # CONTEXT:
                "5/5는 쉬고 싶고, 5/19는 나이트 후 OFF, 그리고 정간호사랑은 겹치기 싫어요"

            # OUTPUT:
                {{
                "Chat": [],
                "Shift": [
                    "5/5은 쉬고 싶고",
                    "5/19는 N,
                    "5/20은 OFF"
                ],
                "Preference": [
                    "정간호사랑은 겹치기 싫어요"
                ],
                "Others": []
                }}
        """
        
        self.human=f"""
            # CONTEXT: 
            {context}
            # OUTPUT:
        """


async def query_analyzer(state):
    # client = genai.Client()
    # context = state['request']
    # query_analyzer_prompt = queryAnalyzerPrompt(context)
    # response = client.models.generate_content(
    #     model="gemini-2.0-flash",
    #     contents=[query_analyzer_prompt.human],                       # or [pil_img, information]
    #     config=types.GenerateContentConfig(
    #         response_mime_type="application/json",
    #         response_schema=queryAnalyzer,      # ★ 핵심: Root 모델
    #         system_instruction=query_analyzer_prompt.system
    #     ),
    # )
    # parts = response.candidates[0].content.parts
    # print(json.loads(parts[0].text))
    # json_answer = json.loads(parts[0].text)
    # print('json_answer: ',json_answer)
    # chat = json_answer['Chat']
    # shift= json_answer['Shift']
    # preference = json_answer['Preference']
    # others = json_answer['Others']
    # print(f"Query Analyzer 답변: query_chat: {chat}, query_shift: {shift}, query_preference: {preference}, query_others: {others}")
    
    context = state['request']
    query_analyzer_prompt = queryAnalyzerPrompt(context)
    
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
    
    for i, client in enumerate(models_to_try):
        try:
            print(f"Query Analyzer: {i+1}차 모델 시도 중...")
            
            llm = client.with_structured_output(queryAnalyzer)
            response = await llm.ainvoke(messages)
            
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

    print(f"Query Analyzer 답변: query_chat: {chat}, query_shift: {shift}, query_preference: {preference}, query_others: {others}")
    return {"query_chat": chat, 'query_shift': shift, 'query_preference': preference, 'query_others': others, 'model': models_to_try[0]}


