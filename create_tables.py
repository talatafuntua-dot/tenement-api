from app.database import engine
from app.models import Base

print("Creating missing database tables...")

Base.metadata.create_all(bind=engine)

print("Database tables are ready.")
