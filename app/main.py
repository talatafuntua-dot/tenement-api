from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers.properties import router as properties_router
from app.routers import pdf

app = FastAPI(
title="Tenement Rate Management API",
version="1.0.0"
)

app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

app.include_router(properties_router)
app.include_router(pdf.router)

@app.get("/")
def home():
return {
"message": "Welcome to the Tenement Rate Management API"
}
