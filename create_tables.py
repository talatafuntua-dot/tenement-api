from app.database import engine, Base
from app import models

print("Creating missing database tables...")

Base.metadata.create_all(bind=engine)

print("Database tables are ready.")
