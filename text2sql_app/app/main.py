import os
import json
from typing import Dict, Any
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from .services.text2sql_service import Text2SQLService
from .db.schema_provider import reflect_or_static_schema

# 현재 파일의 절대 경로를 기준으로 디렉토리 설정
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(APP_DIR)
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
STATIC_DIR = os.path.join(APP_DIR, "static")

app = FastAPI(title="Text2SQL Nurse Roster API")

# 정적 파일 마운트
app.mount("/text2sql-static", StaticFiles(directory=STATIC_DIR), name="static")

# 템플릿 설정
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Text2SQL 서비스 초기화
_text2sql_service = Text2SQLService()

class ChatRequest(BaseModel):
    message: str

class StreamRequest(BaseModel):
    message: str

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """메인 페이지"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/schema")
async def get_schema():
    """데이터베이스 스키마 정보 반환"""
    schema = reflect_or_static_schema()
    return schema

@app.get("/api/status")
async def get_status():
    """서비스 상태 정보 반환"""
    status = _text2sql_service.get_service_status()
    return status

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """메인 Text2SQL 처리 엔드포인트"""
    result = _text2sql_service.process_query(req.message)
    
    # 클라이언트 응답 형식에 맞게 변환
    sql_generation = result.get("sql_generation") or {}
    sql_execution = result.get("sql_execution") or {}
    
    response = {
        "analysis": result.get("analysis"),
        "sql": sql_generation.get("sql", ""),
        "columns": sql_execution.get("columns", []),
        "rows": sql_execution.get("rows", []),
        "answer": result.get("final_answer", ""),
        "logs": result.get("logs", []),
        "error": result.get("error"),
        
        # 추가 디버그 정보
        "debug": {
            "sql_generation": result.get("sql_generation"),
            "sql_execution": result.get("sql_execution"),
            "answer_generation": result.get("answer_generation")
        }
    }
    
    return JSONResponse(response)

@app.post("/api/stream")
async def stream_chat(req: StreamRequest):
    """실시간 스트리밍 Text2SQL 처리 엔드포인트"""
    from fastapi.responses import StreamingResponse
    import asyncio
    import json
    
    async def generate_stream():
        """스트리밍 제너레이터"""
        try:
            # 스트리밍 처리 시작
            for step_data in _text2sql_service.process_query_stream(req.message):
                yield f"data: {json.dumps(step_data)}\n\n"
                # 각 단계 사이에 약간의 지연을 주어 UI가 업데이트될 시간 확보
                await asyncio.sleep(0.1)
                
        except Exception as e:
            error_data = {
                "type": "error",
                "message": f"처리 중 오류가 발생했습니다: {str(e)}"
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    ) 