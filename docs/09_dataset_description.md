# 09 — Dataset Description

## 9.1 Overview

The project uses **Synthea** — a synthetic patient population simulator developed by The MITRE Corporation — to generate realistic but entirely fictional patient medical records.

**Why Synthea?**
- Produces clinically realistic data with real ICD-10 codes, drug names, and SNOMED CT identifiers
- Zero privacy concerns (all data is synthetic)
- Widely used in academic medical AI research
- Produces linked records (conditions, medications, observations, etc.) that reference the same patients

---

## 9.2 Dataset Files

Located at: `/media/omar/Graduation Project/GP/Project/Data/`

| Filename | Size | Records (approx) | Imported? |
|----------|------|-------------------|-----------|
| `patients_localized.csv` | 660 KB | ~1,000 patients | ✅ → `patients` |
| `conditions.csv` | 14.5 MB | ~15,000 conditions | ✅ → `diagnoses` |
| `medications.csv` | 43.7 MB | ~50,000 prescriptions | ✅ → `medications` |
| `observations.csv` | 409 MB | ~1M+ observations | ✅ → `lab_results` (numeric only) |
| `allergies.csv` | 379 KB | ~3,000 allergies | ✅ → `allergies` |
| `encounters.csv` | 55.8 MB | ~60,000 encounters | ❌ (not imported) |
| `procedures.csv` | 97.8 MB | ~100,000 procedures | ❌ (not imported) |
| `imaging_studies.csv` | 135 MB | — | ❌ |
| `claims.csv` | 128 MB | — | ❌ |
| `claims_transactions.csv` | 1.3 GB | — | ❌ |
| `careplans.csv` | 1.7 MB | — | ❌ |
| `devices.csv` | 3.7 MB | — | ❌ |
| `immunizations.csv` | 4.9 MB | — | ❌ |
| `payer_transitions.csv` | 15.8 MB | — | ❌ |
| `payers.csv` | 2 KB | — | ❌ |
| `providers.csv` | 190 KB | — | ❌ |
| `organizations.csv` | 159 KB | — | ❌ |
| `supplies.csv` | 10.6 MB | — | ❌ |

**Total dataset size on disk:** ~2.25 GB

---

## 9.3 Data Schema Mapping

### Patients (`patients_localized.csv` → `patients` table)

| Synthea Column | DB Column | Transformation |
|----------------|-----------|----------------|
| `Id` | *(used as UUID key, not stored)* | UUID → auto-increment int via `uuid_map` dict |
| `FIRST` + `LAST` | `name` | Concatenated with space |
| `BIRTHDATE` | `dob` | Parsed to `date` |
| `GENDER` | `gender` | Direct (M/F) |
| `PHONE` | `phone` | Truncated to 20 chars |
| *(none)* | `blood_type` | Randomly assigned from `['O+','O-','A+','A-','B+','B-','AB+','AB-']` |

### Conditions → Diagnoses

| Synthea Column | DB Column | Transformation |
|----------------|-----------|----------------|
| `PATIENT` | `patient_id` | UUID → int via uuid_map |
| `DESCRIPTION` | `description` | Direct |
| `CODE` | `icd10_code` | Direct (SNOMED or ICD-10) |
| `START` | `diagnosed_on` | Parsed to `date` |
| `STOP` | `is_active` | `NULL` = still active (True) |
| *(none)* | `severity` | Default = `"moderate"` |

### Medications

| Synthea Column | DB Column | Transformation |
|----------------|-----------|----------------|
| `PATIENT` | `patient_id` | UUID → int |
| `DESCRIPTION` | `drug_name` | Direct |
| `START` | `start_date` | Parsed to `date` |
| `STOP` | `end_date` + `is_active` | NULL STOP → active |
| *(none)* | `dose` | Default = `"As directed"` |

### Observations → Lab Results

| Synthea Column | DB Column | Transformation |
|----------------|-----------|----------------|
| `PATIENT` | `patient_id` | UUID → int |
| `DESCRIPTION` | `test_name` | Direct |
| `VALUE` | `value` | `pd.to_numeric()` — non-numeric rows dropped |
| `UNITS` | `unit` | Direct |
| `DATE` | `test_date` | Parsed to `date` |
| *(none)* | `is_abnormal` | Default = `False` |
| *(none)* | `reference` | Empty string |

> **Note:** The `observations.csv` file contains ~1 million records including non-numeric observations (e.g., text descriptions, image findings). Only rows with numeric `VALUE` fields are imported into `lab_results`.

### Allergies

| Synthea Column | DB Column | Transformation |
|----------------|-----------|----------------|
| `PATIENT` | `patient_id` | UUID → int |
| `DESCRIPTION` | `allergen` | Direct |
| `REACTION1` | `reaction` | Direct (if column exists) |
| `SEVERITY1` | `severity` | Direct, defaulting to `"moderate"` |

---

## 9.4 Localization Note

The file `patients_localized.csv` (as opposed to the default Synthea output) includes Arabic/localized patient names to make the demo more relevant to the target deployment context (Arabic-speaking medical environments). This is the only difference from standard Synthea output.

---

## 9.5 Import Performance

Measured on a typical development machine (8-core CPU, 16GB RAM, SSD):

| Stage | Records | Import Time |
|-------|---------|-------------|
| Patients | ~1,000 | ~5 seconds |
| Conditions (diagnoses) | ~15,000 | ~30 seconds |
| Medications | ~50,000 | ~2 minutes |
| Observations (numeric only) | ~200,000 | ~8 minutes |
| Allergies | ~3,000 | ~15 seconds |
| **Total** | | **~11 minutes** |

Processing uses chunked reading (`chunksize=10,000`) to keep memory usage under ~500MB despite the large CSV files.

---

## 9.6 Seed Data (Development Alternative)

For development without running the full Synthea import, `backend/seed.py` generates a smaller controlled dataset:

| Entity | Count | Details |
|--------|-------|---------|
| Doctors | 1 | `doctor@hospital.com` / `doctor123` |
| Patients | 10 | Random age 30-75, random blood types |
| Diagnoses per patient | 2 | Random from 5 common conditions |
| Medications per patient | 2 | Random from 6 common drugs |
| Visits per patient | 3 | Random dates within last year |
| Lab results per patient | 2 | Random from 5 common tests |
| Allergies | ~50% chance | Random allergen + reaction |

---

## 9.7 Clinical Conditions in Dataset

Common conditions appearing in the Synthea dataset:

| Condition | ICD-10 |
|-----------|--------|
| Type 2 Diabetes Mellitus | E11 |
| Hypertension | I10 |
| Hyperlipidemia | E78 |
| Coronary Artery Disease | I25 |
| Chronic Kidney Disease | N18 |
| Asthma | J45 |
| COPD | J44 |
| Hypothyroidism | E03 |
| Atrial Fibrillation | I48 |
| Osteoarthritis | M19 |

---

## 9.8 Data Quality Considerations

| Issue | Description | Handling |
|-------|-------------|----------|
| Missing blood types | Synthea doesn't generate blood types | Randomly assigned with realistic distribution |
| Non-numeric observations | ~60% of observations are text-based | Filtered out during import |
| Missing dose information | Synthea medications lack detailed dosing | Default: `"As directed"` |
| SNOMED codes vs ICD-10 | Synthea conditions use SNOMED CT, not ICD-10 | Stored in `icd10_code` field as-is |
| Duplicate patient names | Possible with large datasets | No deduplication (IDs are unique) |

---

## 9.9 Dataset Citation

```bibtex
@software{synthea,
  author = {Walonoski, Jason and others},
  title = {Synthea: An approach, method, and software mechanism for generating synthetic patients and the synthetic electronic health care record},
  year = {2018},
  journal = {Journal of the American Medical Informatics Association},
  doi = {10.1093/jamia/ocx079}
}
```

---

*← [Benchmarks & Evaluation](08_benchmarks_and_evaluation.md)*
