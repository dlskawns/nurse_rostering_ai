from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import roster, view
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(roster.router, prefix="/roster", tags=["roster"])
app.include_router(view.router, tags=["view"])

@app.get("/")
def read_root():
    return {"message": "Nurse Rostering API is running."} 