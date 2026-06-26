"""
database.py — SQLAlchemy database configuration
================================================
Sets up the PostgreSQL connection for the application:

* ``engine``       — connection pool created from the ``DATABASE_URL`` env variable.
* ``SessionLocal`` — session factory used to create per-request DB sessions.
* ``Base``         — declarative base class that all ORM models inherit from.

The ``DATABASE_URL`` value is loaded from the project ``.env`` file via
``python-dotenv``.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# Load the .env file
load_dotenv()

# The connection string tells SQLAlchemy how to reach PostgreSQL or SQLite
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./medical_db.db')

# 'engine' is the actual connection pool to the database
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

# SessionLocal is a factory that creates database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is the parent class all our table-models inherit from
Base = declarative_base()

# This function is used by FastAPI to give each request its own DB session
def get_db():
    """
    FastAPI dependency that yields a database session for the duration of a
    single request, then closes it in the ``finally`` block to prevent leaks.

    Usage::

        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
