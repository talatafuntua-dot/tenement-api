from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.properties import router as properties_router

app = FastAPI(
    title="Tenement Rate Management API",
    version="1.0.0"
)

# Allow requests from your WordPress site
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Change this later to your WordPress domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(properties_router)

@app.get("/")
def home():
    return {
        "message": "Welcome to the Tenement Rate Management API"
    }