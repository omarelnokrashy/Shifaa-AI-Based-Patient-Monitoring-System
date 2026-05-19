import random
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from backend import models

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def randomize_blood_types():
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
