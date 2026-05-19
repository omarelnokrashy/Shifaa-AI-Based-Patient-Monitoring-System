from .database import SessionLocal, engine, Base
from . import models
from faker import Faker
from passlib.context import CryptContext
from datetime import date, timedelta
import random

def run_seed():
    Base.metadata.create_all(engine)
    fake = Faker()
    pwd_ctx = CryptContext(schemes=['bcrypt'])
    db = SessionLocal()

    # --- Create one test doctor ---
    doctor = models.Doctor(
        name='Dr. Ahmed Hassan',
        email='doctor@hospital.com',
        password=pwd_ctx.hash('doctor123'),
        specialty='Internal Medicine'
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    print(f'Doctor created: {doctor.email}')

    # --- Create 10 test patients ---
    conditions = [
        ('Type 2 Diabetes Mellitus', 'E11'),
        ('Hypertension', 'I10'),
        ('Chronic Kidney Disease', 'N18'),
        ('Asthma', 'J45'),
        ('Hypothyroidism', 'E03'),
    ]

    meds_list = [
        ('Metformin', '500mg twice daily'),
        ('Amlodipine', '5mg once daily'),
        ('Atorvastatin', '20mg at night'),
        ('Levothyroxine', '50mcg once daily'),
        ('Salbutamol inhaler', '2 puffs as needed'),
        ('Lisinopril', '10mg once daily'),
    ]

    labs_list = [
        ('HbA1c', '%', '4.0-5.6'),
        ('Fasting Blood Glucose', 'mg/dL', '70-100'),
        ('Creatinine', 'mg/dL', '0.6-1.2'),
        ('Hemoglobin', 'g/dL', '13.5-17.5'),
        ('TSH', 'mIU/L', '0.4-4.0'),
    ]

    for i in range(10):
        patient = models.Patient(
            name=fake.name(),
            dob=fake.date_of_birth(minimum_age=30, maximum_age=75),
            gender=random.choice(['Male', 'Female']),
            blood_type=random.choice(['A+','A-','B+','B-','AB+','O+','O-']),
            phone=fake.phone_number()[:20]
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

        # Add 2 diagnoses
        for cond, code in random.sample(conditions, 2):
            db.add(models.Diagnosis(
                patient_id=patient.id,
                description=cond,
                icd10_code=code,
                diagnosed_on=fake.date_between(start_date='-3y', end_date='today'),
                is_active=True,
                severity=random.choice(['mild','moderate','severe'])
            ))

        # Add 2 medications
        for drug, dose in random.sample(meds_list, 2):
            db.add(models.Medication(
                patient_id=patient.id,
                drug_name=drug,
                dose=dose,
                start_date=fake.date_between(start_date='-2y', end_date='-30d'),
                is_active=True
            ))

        # Add 3 visits
        for _ in range(3):
            db.add(models.Visit(
                patient_id=patient.id,
                doctor_id=doctor.id,
                visit_date=fake.date_between(start_date='-1y', end_date='today'),
                chief_complaint=random.choice(['Routine check-up','Follow-up for diabetes','Blood pressure control','Fatigue','Shortness of breath']),
                notes=fake.paragraph(nb_sentences=4)
            ))

        # Add 2 lab results
        for test, unit, ref in random.sample(labs_list, 2):
            val = round(random.uniform(4.0, 12.0), 1)
            db.add(models.LabResult(
                patient_id=patient.id,
                test_name=test,
                value=val,
                unit=unit,
                reference=ref,
                test_date=fake.date_between(start_date='-6m', end_date='today'),
                is_abnormal=random.choice([True, False])
            ))

        # Add 1 allergy for some patients
        if random.random() > 0.5:
            db.add(models.Allergy(
                patient_id=patient.id,
                allergen=random.choice(['Penicillin','Sulfa drugs','Aspirin','Ibuprofen','Latex']),
                reaction=random.choice(['Rash','Anaphylaxis','Hives','Angioedema']),
                severity=random.choice(['mild','moderate','severe'])
            ))

        db.commit()
        print(f'Patient {i+1} created: {patient.name} (ID: {patient.id})')

    db.close()
    print('\nSeeding complete! 10 patients ready for testing.')

if __name__ == '__main__':
    run_seed()
