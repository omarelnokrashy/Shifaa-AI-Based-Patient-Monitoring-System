from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# Load the .env file
load_dotenv()

# The connection string tells SQLAlchemy how to reach PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')

# 'engine' is the actual connection pool to the database
engine = create_engine(DATABASE_URL)

# SessionLocal is a factory that creates database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is the parent class all our table-models inherit from
Base = declarative_base()

# This function is used by FastAPI to give each request its own DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
