"""
Standalone Chatbot Pipeline Benchmarker
======================================
Measures latencies for each stage and model in the medical chatbot RAG pipeline.
Does NOT modify any project files. Instruments the code dynamically.

Run via:
    .\\venv\\Scripts\\python.exe scripts/benchmark_standalone.py
"""

import os
import sys
import time
import json
import math
import argparse
from datetime import datetime

# Setup project root path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

# Import backend services
try:
    from backend.database import SessionLocal
    from backend import models
    import backend.services.intent as intent_service
    import backend.services.ner as ner_service
    import backend.services.retriever as retriever_service
    import backend.services.llm as llm_service
except ImportError as e:
    print(f"Error importing backend components: {e}")
    print("Please make sure you run this script from the project root with the correct python executable.")
    sys.exit(1)

# Global variables to capture model latencies dynamically from monkeypatched OpenAI client
last_intent_model_latency = 0.0
last_ner_model_latency = 0.0

# Store original OpenAI client chat completions create methods
original_intent_create = intent_service.client.chat.completions.create
original_ner_create = ner_service.client.chat.completions.create

def patch_openai_clients():
    """Monkeypatches client completions to capture raw model call latencies."""
    global original_intent_create, original_ner_create
    
    # Patch Intent Client
    def wrapped_intent_create(*args, **kwargs):
        global last_intent_model_latency
        t0 = time.perf_counter()
        res = original_intent_create(*args, **kwargs)
        last_intent_model_latency = time.perf_counter() - t0
        return res
    
    intent_service.client.chat.completions.create = wrapped_intent_create

    # Patch NER Client
    def wrapped_ner_create(*args, **kwargs):
        global last_ner_model_latency
        t0 = time.perf_counter()
        res = original_ner_create(*args, **kwargs)
        last_ner_model_latency = time.perf_counter() - t0
        return res
    
    ner_service.client.chat.completions.create = wrapped_ner_create


def calculate_stats(values):
    """Calculate mean, median, min, max, std dev for a list of numbers."""
    if not values:
        return {k: 0.0 for k in ['mean', 'median', 'min', 'max', 'std_dev', 'p95']}
    n = len(values)
    mean = sum(values) / n
    sorted_vals = sorted(values)
    median = sorted_vals[n // 2] if n % 2 != 0 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    p95 = sorted_vals[int(math.ceil((n * 0.95)) - 1)] if n > 0 else 0.0
    minimum = min(values)
    maximum = max(values)
    variance = sum((x - mean) ** 2 for x in values) / max(1, n - 1)
    std_dev = math.sqrt(variance)
    return {
        'mean': mean,
        'median': median,
        'min': minimum,
        'max': maximum,
        'std_dev': std_dev,
        'p95': p95
    }


def format_ms(val_seconds):
    """Format seconds into milliseconds string."""
    return f"{val_seconds * 1000:.1f}ms"


def run_pipeline_benchmark(queries, patient_id, num_runs=1):
    """Executes chatbot pipeline for specified queries and records execution latencies."""
    global last_intent_model_latency, last_ner_model_latency
    
    db = SessionLocal()
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        patient = db.query(models.Patient).first()
        if patient:
            print(f"Patient ID {patient_id} not found. Falling back to first patient: {patient.name} (ID: {patient.id})")
            patient_id = patient.id
        else:
            print("No patients found in database.")
            db.close()
            sys.exit(1)
        
    print(f"Benchmarking using Patient: {patient.name} (ID: {patient.id})")
    print(f"Number of queries: {len(queries)} | Runs per query: {num_runs}")
    print("Starting pipeline instrumentation...")
    
    patch_openai_clients()
    
    results = []
    
    for q_idx, (query, expected_intent) in enumerate(queries):
        print(f"\n[{q_idx+1}/{len(queries)}] Query: '{query}'")
        
        query_runs = []
        
        for run in range(num_runs):
            if num_runs > 1:
                print(f"  Run {run+1}/{num_runs}...", end="", flush=True)
            
            # Reset captured model latencies
            last_intent_model_latency = 0.0
            last_ner_model_latency = 0.0
            
            # Start timing full query
            t_start_query = time.perf_counter()
            
            # 1. Intent Stage
            t0 = time.perf_counter()
            intent_res = intent_service.classify_intent(query)
            intent = intent_res.get('intent', 'history_lookup')
            intent_stage_time = time.perf_counter() - t0
            intent_model_time = last_intent_model_latency
            
            # 2. NER Stage
            t0 = time.perf_counter()
            entities = ner_service.extract_entities(query)
            ner_stage_time = time.perf_counter() - t0
            ner_model_time = last_ner_model_latency
            
            # 3. Retrieval Stage
            t0 = time.perf_counter()
            records, sources = retriever_service.retrieve(patient_id, intent, entities, db)
            retrieval_stage_time = time.perf_counter() - t0
            
            # 4. LLM Generation Stage
            t_start_gen = time.perf_counter()
            generator = llm_service.generate_answer(query, intent, records, patient)
            
            first_token_time = None
            token_count = 0
            full_text = ""
            
            # Consume the generator to measure TTFT and generation latency
            for chunk in generator:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                full_text += chunk
                # Simple word/token estimation
                token_count += len(chunk.split())
                
            t_end_gen = time.perf_counter()
            
            # Calculate generation timings
            ttft_from_gen = first_token_time - t_start_gen if first_token_time else 0.0
            ttft_from_query = first_token_time - t_start_query if first_token_time else 0.0
            generation_stage_time = t_end_gen - t_start_gen
            generator_model_time = generation_stage_time  # equivalent for streaming path
            
            total_query_time = time.perf_counter() - t_start_query
            
            # Save metrics for this run
            run_metrics = {
                'run': run + 1,
                'intent_detected': intent,
                'intent_stage_ms': intent_stage_time * 1000,
                'intent_model_ms': intent_model_time * 1000,
                'ner_stage_ms': ner_stage_time * 1000,
                'ner_model_ms': ner_model_time * 1000,
                'retrieval_stage_ms': retrieval_stage_time * 1000,
                'generation_stage_ms': generation_stage_time * 1000,
                'generator_model_ms': generator_model_time * 1000,
                'ttft_from_gen_ms': ttft_from_gen * 1000,
                'ttft_from_query_ms': ttft_from_query * 1000,
                'total_query_ms': total_query_time * 1000,
                'tokens_generated': token_count,
                'tokens_per_sec': token_count / generation_stage_time if generation_stage_time > 0 else 0.0
            }
            query_runs.append(run_metrics)
            
            if num_runs > 1:
                print(f" Done ({total_query_time*1000:.0f}ms)")
                
        # Aggregate runs for this query
        agg_metrics = {
            'query': query,
            'expected_intent': expected_intent,
            'intent_detected': query_runs[-1]['intent_detected'],
            'intent_match': query_runs[-1]['intent_detected'] == expected_intent,
            'runs': query_runs,
            'averages': {
                'intent_stage_ms': sum(r['intent_stage_ms'] for r in query_runs) / num_runs,
                'intent_model_ms': sum(r['intent_model_ms'] for r in query_runs) / num_runs,
                'ner_stage_ms': sum(r['ner_stage_ms'] for r in query_runs) / num_runs,
                'ner_model_ms': sum(r['ner_model_ms'] for r in query_runs) / num_runs,
                'retrieval_stage_ms': sum(r['retrieval_stage_ms'] for r in query_runs) / num_runs,
                'generation_stage_ms': sum(r['generation_stage_ms'] for r in query_runs) / num_runs,
                'generator_model_ms': sum(r['generator_model_ms'] for r in query_runs) / num_runs,
                'ttft_from_gen_ms': sum(r['ttft_from_gen_ms'] for r in query_runs) / num_runs,
                'ttft_from_query_ms': sum(r['ttft_from_query_ms'] for r in query_runs) / num_runs,
                'total_query_ms': sum(r['total_query_ms'] for r in query_runs) / num_runs,
                'tokens_per_sec': sum(r['tokens_per_sec'] for r in query_runs) / num_runs
            }
        }
        
        # Print run summary
        avg = agg_metrics['averages']
        print(f"  Detected Intent:    {agg_metrics['intent_detected']} (Match: {agg_metrics['intent_match']})")
        print(f"  Total Latency:      {avg['total_query_ms']:.1f}ms")
        print(f"  Time to 1st Token:  {avg['ttft_from_gen_ms']:.1f}ms (from LLM start) | {avg['ttft_from_query_ms']:.1f}ms (from query start)")
        print(f"  Stage Latencies:    Intent: {avg['intent_stage_ms']:.1f}ms | NER: {avg['ner_stage_ms']:.1f}ms | Retrieval: {avg['retrieval_stage_ms']:.1f}ms | Gen: {avg['generation_stage_ms']:.1f}ms")
        print(f"  Model Latencies:    Intent LLM: {avg['intent_model_ms']:.1f}ms | NER LLM: {avg['ner_model_ms']:.1f}ms | Gen LLM: {avg['generator_model_ms']:.1f}ms")
        print(f"  Throughput:         {avg['tokens_per_sec']:.1f} tokens/sec")
        
        results.append(agg_metrics)
        
    db.close()
    return results


def print_overall_summary(results):
    """Calculates and prints statistical summaries across all runs and queries."""
    all_runs = []
    for r in results:
        all_runs.extend(r['runs'])
        
    intent_stages = [run['intent_stage_ms'] for run in all_runs]
    intent_models = [run['intent_model_ms'] for run in all_runs]
    ner_stages = [run['ner_stage_ms'] for run in all_runs]
    ner_models = [run['ner_model_ms'] for run in all_runs]
    retrievals = [run['retrieval_stage_ms'] for run in all_runs]
    generations = [run['generation_stage_ms'] for run in all_runs]
    gen_models = [run['generator_model_ms'] for run in all_runs]
    ttfts_gen = [run['ttft_from_gen_ms'] for run in all_runs]
    ttfts_query = [run['ttft_from_query_ms'] for run in all_runs]
    totals = [run['total_query_ms'] for run in all_runs]
    throughputs = [run['tokens_per_sec'] for run in all_runs if run['tokens_per_sec'] > 0]
    
    intent_acc = sum(1 for r in results if r['intent_match']) / len(results) if results else 0.0

    print("\n" + "="*80)
    print("                  OVERALL PIPELINE BENCHMARK SUMMARY")
    print("="*80)
    
    headers = ["Metric/Stage", "Mean (ms)", "Median (ms)", "Min (ms)", "Max (ms)", "Std Dev (ms)", "P95 (ms)"]
    rows = [
        ["Intent Stage", *[f"{v:.1f}" for v in calculate_stats(intent_stages).values()]],
        ["Intent Model", *[f"{v:.1f}" for v in calculate_stats(intent_models).values()]],
        ["NER Stage", *[f"{v:.1f}" for v in calculate_stats(ner_stages).values()]],
        ["NER Model", *[f"{v:.1f}" for v in calculate_stats(ner_models).values()]],
        ["Retrieval Stage", *[f"{v:.1f}" for v in calculate_stats(retrievals).values()]],
        ["LLM Gen Stage", *[f"{v:.1f}" for v in calculate_stats(generations).values()]],
        ["Gen Model (Stream)", *[f"{v:.1f}" for v in calculate_stats(gen_models).values()]],
        ["TTFT (from Gen)", *[f"{v:.1f}" for v in calculate_stats(ttfts_gen).values()]],
        ["TTFT (from Query)", *[f"{v:.1f}" for v in calculate_stats(ttfts_query).values()]],
        ["Total Query Latency", *[f"{v:.1f}" for v in calculate_stats(totals).values()]],
    ]
    
    # Calculate widths
    widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]
    
    # Print table
    header_line = " | ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print(" | ".join(f"{val:<{widths[i]}}" for i, val in enumerate(row)))
        
    print("="*80)
    t_stats = calculate_stats(throughputs)
    print(f"Generation Throughput: Mean {t_stats['mean']:.1f} tok/s | Median {t_stats['median']:.1f} tok/s | P95 {t_stats['p95']:.1f} tok/s")
    print(f"Intent Classification Accuracy: {intent_acc:.1%} ({sum(1 for r in results if r['intent_match'])}/{len(results)})")
    print("="*80)


def main():
    parser = argparse.ArgumentParser(description="Medical Chatbot Standalone Benchmark")
    parser.add_argument('--patient-id', type=int, default=1, help='Patient ID to run queries against (default: 1)')
    parser.add_argument('--runs', type=int, default=1, help='Number of runs per query to capture statistics (default: 1)')
    parser.add_argument('--output', '-o', default='standalone_benchmark_results.json', help='Save results to JSON file')
    args = parser.parse_args()

    # The suite of benchmark queries with expected intents
    benchmark_suite = [
        ("What medications is this patient taking?", "medication_check"),
        ("Show me the last HbA1c result", "lab_results"),
        ("Any drug allergies?", "allergy_check"),
        ("Last 3 visits summary", "visit_summary"),
        ("What conditions does this patient have?", "diagnosis_check"),
        ("Give me a brief medical history", "history_lookup"),
        ("Are there any concerning findings?", "risk_flag"),
        ("Is the patient on metformin?", "medication_check"),
        ("Lab results from last 6 months", "lab_results"),
    ]

    print("#"*80)
    print("      MEDICAL RETRIEVAL CHATBOT PIPELINE STANDALONE BENCHMARK")
    print(f"      Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("#"*80)
    
    results = run_pipeline_benchmark(benchmark_suite, args.patient_id, args.runs)
    print_overall_summary(results)
    
    # Save output to file
    with open(args.output, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'patient_id': args.patient_id,
            'runs_per_query': args.runs,
            'queries_benchmarked': results
        }, f, indent=2, default=str)
    print(f"\nDetailed latency metrics report saved to: {args.output}\n")


if __name__ == '__main__':
    main()
