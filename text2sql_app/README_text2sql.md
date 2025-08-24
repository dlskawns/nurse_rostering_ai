### Text2SQL Standalone App (FastAPI + LangGraph)

- 독립 실행형 앱으로 현재 코드베이스/DB를 수정하지 않습니다.
- meditong_roster 스키마를 참고해 Text→SQL→DB조회→답변 파이프라인을 제공합니다.

#### 1) 준비

```bash
cd nurse_rostering
python -m venv .venv && source .venv/bin/activate
pip install -r text2sql_app/requirements-text2sql.txt
cp text2sql_app/.env.example text2sql_app/.env
# .env 내부에 DB Read-Only 계정과 LLM 키를 설정
```

#### 2) 실행

```bash
chmod +x text2sql_app/run_text2sql.sh
./text2sql_app/run_text2sql.sh
# http://localhost:8010 접속
```

#### 3) 보안/제한

- SQL 실행은 SELECT/SHOW/DESCRIBE/EXPLAIN(SELECT)만 허용합니다.
- 서버에서 생성된 SQL은 실행 전 정적 검증을 거칩니다.
- DB, 기존 코드에는 어떤 변경도 하지 않습니다.

#### 4) 구조

- `text2sql_app/app` FastAPI 앱, 라우트, UI 템플릿
- `text2sql_app/app/graph` LangGraph 상태/노드/프롬프트
- `text2sql_app/app/db` Read-Only MySQL, 스키마 제공
- `text2sql_app/app/llm_router.py` LLM 폴백(Gemini → OpenAI → Claude)

#### 5) UI

- 터미널풍 프로세스 패널 + 중앙 챗/SQL 탭 + 좌측 스키마 트리
- 생성된 SQL, 실행 로그, 결과를 단계별로 확인 가능

#### 6) 환경 변수

- `.env.example` 참고
