from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import roster, auth, nurses, schedules, dates

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(nurses.router)
app.include_router(schedules.router)
app.include_router(roster.router)
app.include_router(dates.router) 