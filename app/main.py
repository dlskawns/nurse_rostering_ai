from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import roster, auth, nurses, dates, wanted, preferences, roster_create, shifts, health

app = FastAPI()

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