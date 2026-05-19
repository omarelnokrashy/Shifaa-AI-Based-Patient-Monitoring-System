import pandas as pd
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from backend import models


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DATA_DIR = "/media/omar/Graduation Project/GP/Project/Data"

def import_data():
    engine = create_engine(DATABASE_URL)
    print("Starting full Synthea mapping import...")

    # 1. Load Patients and keep UUID map
    print("Reading patients...")
    raw_patients = pd.read_csv(os.path.join(DATA_DIR, "patients_localized.csv"))
    
    # We'll use a unique identifier for mapping. Synthea 'Id' is a UUID.
    # We'll add it to our DB temporarily or just use a mapping dictionary if memory allows.
    # For speed, let's just use the name + DOB as a key if we don't want to change schema.
    # Better: Use a dictionary mapping UUID -> DB ID.
    
    # First, clear existing seeded data to avoid duplicates if preferred, 
    # but user said 'add', so we'll append.
    
    patients_to_add = pd.DataFrame({
        'name': raw_patients['FIRST'] + ' ' + raw_patients['LAST'],
        'dob': pd.to_datetime(raw_patients['BIRTHDATE'], errors='coerce').dt.date,
        'gender': raw_patients['GENDER'],
        'phone': raw_patients.get('PHONE', None),
        'blood_type': None
    })
    
    # We need to know which DB ID corresponds to which Synthea UUID.
    # We'll import one by one to get IDs, or use a temp table.
    # Given the scale (likely < 1000 patients in a demo set), one by one is fine for patients.
    
    Session = sessionmaker(bind=engine)
    session = Session()

    import random
    blood_types = ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-']

    uuid_map = {}
    print("Inserting Patients and building UUID map...")
    for i, row in raw_patients.iterrows():
        dob_val = pd.to_datetime(row['BIRTHDATE'], errors='coerce')
        p = models.Patient(
            name=f"{row['FIRST']} {row['LAST']}",
            dob=dob_val.date() if pd.notna(dob_val) else None,
            gender=row['GENDER'],
            phone=str(row.get('PHONE', ''))[:20],
            blood_type=random.choice(blood_types)
        )

        session.add(p)
        session.flush()
        uuid_map[row['Id']] = p.id
        if i % 100 == 0:
            print(f"  Processed {i} patients...")
    session.commit()
    print(f"Total Patients Imported: {len(uuid_map)}")

    # 2. Helper to import related data
    def import_related(filename, target_table, mapping_func):
        print(f"Processing {filename}...")
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            return
        
        # For large files like observations, use chunks
        chunksize = 10000 
        for chunk in pd.read_csv(path, chunksize=chunksize):
            # Filter for rows where PATIENT is in our map
            chunk = chunk[chunk['PATIENT'].isin(uuid_map.keys())].copy()
            if chunk.empty:
                continue
            chunk['patient_id'] = chunk['PATIENT'].map(uuid_map)
            
            # Apply specific mapping
            import_df = mapping_func(chunk)
            import_df.to_sql(target_table, engine, if_exists='append', index=False, method='multi', chunksize=1000)
            print(f"  Inserted a chunk into {target_table}...")
        print(f"  Done {target_table}.")


    # 3. Import Conditions -> Diagnoses
    import_related("conditions.csv", "diagnoses", lambda df: pd.DataFrame({
        'patient_id': df['patient_id'],
        'description': df['DESCRIPTION'],
        'icd10_code': df['CODE'],
        'diagnosed_on': pd.to_datetime(df['START'], errors='coerce').dt.date,
        'is_active': df['STOP'].isna(),
        'severity': 'moderate'
    }))

    # 4. Import Medications
    import_related("medications.csv", "medications", lambda df: pd.DataFrame({
        'patient_id': df['patient_id'],
        'drug_name': df['DESCRIPTION'],
        'dose': 'As directed',
        'start_date': pd.to_datetime(df['START'], errors='coerce').dt.date,
        'end_date': pd.to_datetime(df['STOP'], errors='coerce').dt.date,
        'is_active': df['STOP'].isna()
    }))

    # 5. Import Observations -> LabResults
    # Filtering for common lab results
    import_related("observations.csv", "lab_results", lambda df: pd.DataFrame({
        'patient_id': df['patient_id'],
        'test_name': df['DESCRIPTION'],
        'value': pd.to_numeric(df['VALUE'], errors='coerce'),
        'unit': df['UNITS'].fillna(''),
        'reference': '',
        'test_date': pd.to_datetime(df['DATE'], errors='coerce').dt.date,
        'is_abnormal': False
    }).dropna(subset=['value']))

    # 6. Import Allergies
    import_related("allergies.csv", "allergies", lambda df: pd.DataFrame({
        'patient_id': df['patient_id'],
        'allergen': df['DESCRIPTION'],
        'reaction': df.get('REACTION1', 'Unknown'),
        'severity': df.get('SEVERITY1', 'moderate').fillna('moderate')
    }))

    print("Synthea import finished successfully!")

if __name__ == "__main__":
    import_data()
