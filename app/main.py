from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.properties import router as properties_router
from app.routers import pdf
from app.routers.reports import router as reports_router
from app.routers.data import router as data_router
from app.routers import templates



app = FastAPI(
    title="Tenement Rate Management API",
    version="1.0.0"
)

app.include_router(properties_router)
app.include_router(pdf.router)
app.include_router(reports_router)
app.include_router(data_router)
app.include_router(templates.router)

@app.get("/")
def home():
    return {
        "message": "Welcome to the Tenement Rate Management API"
    }
