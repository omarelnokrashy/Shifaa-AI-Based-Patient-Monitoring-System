"""
fix_blood_types.py — Back-fill blood type data
===============================================
One-time utility script that assigns a random, valid ABO/Rh blood type to
every patient record that was imported without one (e.g. from Synthea CSVs
that do not include blood type information).

Run directly::

    python fix_blood_types.py
"""
import random
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from backend import models

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def randomize_blood_types():
    """
    Connect to the database, iterate over all ``Patient`` rows, and assign a
    randomly chosen ABO/Rh blood type (e.g. ``'O+'``, ``'AB-'``) to each one.
    Changes are committed in a single transaction.
    """
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    blood_types = ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-']
    patients = session.query(models.Patient).all()
    
    print(f"Randomizing blood types for {len(patients)} patients...")
    for p in patients:
        p.blood_type = random.choice(blood_types)
    
    session.commit()
    print("Done!")

if __name__ == "__main__": randomize_blood_types()
