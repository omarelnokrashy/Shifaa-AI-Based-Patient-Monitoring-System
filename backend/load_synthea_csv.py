"""
load_synthea_csv.py — Bulk-import Synthea synthetic patient data
================================================================
Reads Synthea-generated CSV files from ``DATA_DIR`` and inserts the records
into the application database, mapping Synthea UUIDs to auto-incremented
postgresSQL IDs using an in-memory dictionary.

CSV files expected in ``DATA_DIR``:
  - ``patients_localized.csv``  → ``patients`` table
  - ``conditions.csv``          → ``diagnoses`` table
  - ``medications.csv``         → ``medications`` table
  - ``observations.csv``        → ``lab_results`` table
  - ``allergies.csv``           → ``allergies`` table

Run directly::

    python load_synthea_csv.py
"""
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
    """
    Orchestrate the full Synthea CSV import.

    Steps:
      1. Read ``patients_localized.csv``, insert each patient into the
         ``patients`` table, and build a ``uuid_map`` (Synthea UUID → DB id).
      2. Call ``import_related`` for conditions, medications, observations, and
         allergies, translating Synthea patient UUIDs via ``uuid_map`` before
         bulk-inserting each chunk.

    Large CSV files (e.g. observations) are processed in chunks of 10 000 rows
    to keep memory usage low.
    """
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
        """
        Read *filename* from ``DATA_DIR`` in chunks, filter rows to patients
        present in ``uuid_map``, apply *mapping_func* to produce a DataFrame
        with the correct column names, and bulk-insert each chunk into
        *target_table* using pandas ``to_sql``.

        Args:
            filename (str): CSV filename relative to ``DATA_DIR``.
            target_table (str): Database table name to insert into.
            mapping_func (callable): Takes a chunk DataFrame and returns a new
                DataFrame shaped for the target table.
        """
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
