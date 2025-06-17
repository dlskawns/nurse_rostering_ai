from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import roster, view, auth, nurses
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(nurses.router)
app.include_router(roster.router, prefix="/roster", tags=["roster"])
app.include_router(view.router) 