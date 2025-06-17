from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import roster, auth, nurses

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(nurses.router)
app.include_router(roster.router) 