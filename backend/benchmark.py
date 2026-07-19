import time
import numpy as np
import json
import os
from phonetic_engine import engine

# Load local aliases to calculate is_alias_match for benchmark comparison (mimicking Redis)
aliases_map = {}
aliases_path = os.path.join(os.path.dirname(__file__), "aliases.json")
try:
    with open(aliases_path, "r", encoding="utf-8") as f:
        raw_aliases = json.load(f)
        for k, v in raw_aliases.items():
            group = [k] + v
            normalized_group = {engine.normalize(x).lower() for x in group}
            for member in normalized_group:
                if member not in aliases_map:
                    aliases_map[member] = set()
                aliases_map[member].update(normalized_group - {member})
except Exception:
    pass

# Labeled dataset of Indic name pairs for phonetic similarity verification
# Format: (Name 1, Name 2, expected_is_similar, description)
BENCHMARK_DATA = [
    # Exact Matches
    ("Sanjay", "Sanjay", True, "Exact match"),
    ("Amit Kumar", "Amit Kumar", True, "Multi-word exact match"),
    
    # Alias / Synonym Matches (Bidirectional & Transitive)
    ("Varanasi", "Benares", True, "Common city alias"),
    ("Benares", "Kashi", True, "Transitive city alias"),
    ("Trivandrum", "Thiruvananthapuram", True, "Long city alias"),
    ("Kolkata", "Calcutta", True, "Colonial/modern city alias"),
    ("Mumbai", "Bombay", True, "City alias"),
    
    # Phonetic Variations (Indic Translits)
    ("Amit", "Ameet", True, "Short vowel variation"),
    ("Sunita", "Suneeta", True, "Double vowel variation"),
    ("Vikram", "Bikram", True, "B/V/W sound interchange"),
    ("Mukherjee", "Mookherjee", True, "Syllable spelling variation"),
    ("Lakshmi", "Laxmi", True, "Sanskrit conjunct spelling variant"),
    ("Sanjay", "Sunjay", True, "Vowel shift variation (A vs U)"),
    ("Geeta", "Gita", True, "Common vowel spelling shift (EE vs I)"),
    ("Chandra", "Sander", False, "Spelling difference with distinct phonetic codes"),
    
    # Distinct Entities (Should NOT match)
    ("Sanjay", "Sanjeev", False, "Distinct names starting with same prefix"),
    ("Amit", "Umit", False, "Vowel compression collision prevention (Amit vs Umit)"),
    ("Sam", "San", False, "M/N separation check (Sam vs San)"),
    ("Sector 2", "Sector 3", False, "Numerical entity separation"),
    ("Harish", "Arish", False, "H-prefix separation"),
    ("Rajesh", "Rajeev", False, "Distinct names starting with same prefix"),
    ("Ramesh", "Suresh", False, "Different rhyming names"),
    ("Patel", "Pathil", False, "Distinct surnames"),
]

# Attempt to load external dataset if available
dataset_path = os.path.join(os.path.dirname(__file__), "dataset.csv")
if os.path.exists(dataset_path):
    try:
        import csv
        with open(dataset_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            external_data = []
            for row in reader:
                if len(row) >= 3:
                    expected = str(row[2]).strip().lower() in ('true', '1', 'yes', 'y')
                    desc = row[3] if len(row) > 3 else ""
                    external_data.append((row[0], row[1], expected, desc))
            if external_data:
                BENCHMARK_DATA = external_data
                print(f"Loaded {len(BENCHMARK_DATA)} pairs from external dataset.csv")
    except Exception as e:
        print(f"Failed to load external dataset: {e}. Falling back to default.")

def run_benchmarks():
    print("=" * 60)
    print(" IndicSync Phonetic Similarity Accuracy & Performance Benchmark")
    print("=" * 60)
    
    y_true = []
    y_pred = []
    latencies = []
    
    tp, fp, tn, fn = 0, 0, 0, 0
    
    print(f"{'Name 1':<20} | {'Name 2':<20} | {'True':<5} | {'Pred':<5} | {'Score':<6} | {'Time (ms)':<9} | {'Status'}")
    print("-" * 90)

    for name1, name2, expected, desc in BENCHMARK_DATA:
        start_time = time.perf_counter()
        
        # Calculate is_alias_match
        is_alias_match = False
        norm1 = engine.normalize(name1).lower()
        norm2 = engine.normalize(name2).lower()
        if norm1 in aliases_map and norm2 in aliases_map[norm1]:
            is_alias_match = True
            
        res = engine.compare(name1, name2, enable_aliases=True, is_alias_match=is_alias_match)
        duration_ms = (time.perf_counter() - start_time) * 1000
        latencies.append(duration_ms)
        
        pred = res["is_similar"]
        score = res["score"]
        
        y_true.append(expected)
        y_pred.append(pred)
        
        if expected and pred:
            tp += 1
            status = "TP (Hit)"
        elif not expected and not pred:
            tn += 1
            status = "TN (Correct Reject)"
        elif not expected and pred:
            fp += 1
            status = "FP (False Positive)"
        else:
            fn += 1
            status = "FN (Miss)"

            
        print(f"{name1:<20} | {name2:<20} | {str(expected):<5} | {str(pred):<5} | {score:<6.1f} | {duration_ms:<9.3f} | {status}")

    # Metrics computation
    total = len(BENCHMARK_DATA)
    accuracy = (tp + tn) / total
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    mean_latency = np.mean(latencies)
    p50_latency = np.percentile(latencies, 50)
    p95_latency = np.percentile(latencies, 95)
    
    print("=" * 60)
    print(" Summary Metrics")
    print("=" * 60)
    print(f"Total Evaluated Pairs: {total}")
    print(f"Accuracy             : {accuracy:.2%}")
    print(f"Precision            : {precision:.2%}")
    print(f"Recall (Sensitivity) : {recall:.2%}")
    print(f"F1 Score             : {f1:.2%}")
    print("-" * 60)
    print(f"Latency (Mean)       : {mean_latency:.3f} ms")
    print(f"Latency (p50/Median) : {p50_latency:.3f} ms")
    print(f"Latency (p95)        : {p95_latency:.3f} ms")
    print("=" * 60)

    print("=" * 60)

if __name__ == "__main__":
    run_benchmarks()
