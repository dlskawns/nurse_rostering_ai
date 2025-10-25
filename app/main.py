from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import sys, os
from fastapi.middleware.cors import CORSMiddleware
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from routers import roster, auth, nurses, dates, wanted, preferences, roster_create, shifts, health, dashboard, legacy, teams
from routers import daily_shift as daily_shift_router

app = FastAPI()


origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,         # "*" 쓰지 말 것 (credentials 쓰면 불가)
    allow_credentials=True,        # 쿠키/세션 쓰면 True
    allow_methods=["*"],           # 또는 ["POST","GET","OPTIONS",...]
    allow_headers=["*"],           # Authorization, Content-Type 등 허용
)


app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(nurses.router)
# app.include_router(schedules.router)
app.include_router(roster.router)
app.include_router(dates.router) 
app.include_router(wanted.router) 
app.include_router(preferences.router) 
app.include_router(roster_create.router) 
app.include_router(shifts.router)
app.include_router(health.router)
app.include_router(dashboard.router)
app.include_router(legacy.router)
app.include_router(daily_shift_router.router)
app.include_router(teams.router)



import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) 
