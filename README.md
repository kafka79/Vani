# IndicSync — Indic Phonetic Similarity Detector

IndicSync is a production-grade phonetic similarity engine optimized for transliterated Indian Names and Place Entities (e.g. cities, states, address fields). It addresses spelling variations, historical aliases, and transliteration noise common in Indian datasets.

## 🌟 Why IndicSync? (Comparison vs. Standard Algorithms)

Traditional phonetic algorithms (like Soundex or Metaphone) fail on Indian names due to distinct linguistic properties:

| Feature / Algorithm | Soundex | Metaphone | Double Metaphone | Jaro-Winkler | **IndicSync** |
|---------------------|---------|-----------|------------------|--------------|---------------|
| **Vowel Compression** | Discards vowels after first letter | Collapses vowels | Ignores vowel shifts | Token-based character matches | **Preserves phonetic vowel markers** (distinguishes *Amit* vs. *Umit*) |
| **B/V/W Alternations** | Mapped differently (B=7, V=7, W ignored) | Distinct codes | Distinct codes | String distance penalty | **Phonetically grouped** (Vikram/Bikram matches) |
| **Sanskrit Conjuncts** | Fails on 'KSH' / 'Laxmi' | Harsh phonetic breaks | Breaks phonetic consistency | String distance mismatch | **Normalized** (Lakshmi matches Laxmi) |
| **Historical Aliases** | No alias mapping | No alias mapping | No alias mapping | String distance 0.0 | **Bidirectional & Transitive mappings** (Varanasi / Benares / Kashi) |
| **M/N Separation** | Collides often | Collides often | Collides often | High collision risk | **Distinct codes** to prevent *Sam* vs *San* collision |

---

## 🛠️ Key Features
- **Unicode-Native Transliteration**: Implements first-principles Indic-to-Latin transliteration using Unicode letter character names, skipping viramas and resolving conjuncts.
- **Symmetric & Transitive Aliases**: Parses administrative and historical synonyms (e.g. *Kolkata* $\leftrightarrow$ *Calcutta*, *Bombay* $\leftrightarrow$ *Mumbai*) and handles transitive connections.
- **Async Concurrency & Non-Blocking Loops**: Offloads batch processing tasks to worker thread pools to guarantee high API concurrency.
- **Rate-Limiting & Security Hardened**: IP-based sliding window rate-limiting protects endpoints, and input validation is sanitized to avoid string reflection log injections.
- **Prometheus Metrics**: Exposes structured Prometheus performance metrics compatible with multi-worker deployments.
- **Interactive UI**: Sleek, themeable glassmorphism web interface with light/dark theme persistence and custom threshold tuning.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Pip package manager

### Installation & Run Local
1. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
2. Run the application:
   ```bash
   python backend/main.py
   ```
3. Open your browser and navigate to: `http://localhost:8000`

### Run via Docker
1. Build the Docker image:
   ```bash
   docker build -t indicsync .
   ```
2. Run the container:
   ```bash
   docker run -p 8000:8000 indicsync
   ```

---

## 📡 API Reference

### 1. Compare Names (`POST /compare`)
Compares two names or places and returns a similarity score.
* **Payload**:
  ```json
  {
    "name1": "Varanasi",
    "name2": "Benares",
    "enable_aliases": true,
    "threshold": 75.0
  }
  ```
* **Response**:
  ```json
  {
    "name1": "Varanasi",
    "name2": "Benares",
    "code1": "BARNAS",
    "code2": "BARNAS",
    "score": 100.0,
    "is_similar": true,
    "match_type": "alias",
    "processing_time_ms": 0.42
  }
  ```

### 2. Compare Batch (`POST /compare-batch`)
Compare up to 1000 pairs concurrently.
* **Payload**:
  ```json
  {
    "pairs": [
      {"name1": "Amit", "name2": "Ameet"},
      {"name1": "Kolkata", "name2": "Calcutta"}
    ],
    "enable_aliases": true,
    "threshold": 75.0
  }
  ```

### 3. Hot-Reload Aliases (`POST /admin/reload-aliases`)
Reloads the `aliases.json` configurations without restarting the server.
* **Headers**: `X-API-Key: admin-secret-key-change-me`

### 4. Metrics (`GET /metrics`)
Exposes Prometheus formatted metrics for scrapers.

---

## 📈 Accuracy Benchmarks

We maintain a labeled dataset representing real-world spelling changes, transliterations, and distinct name variations. To run the benchmark:

```bash
python backend/benchmark.py
```

### Metrics Measured:
- **Accuracy**: Overall classification correctness.
- **Precision**: Ratio of true similarity classifications to all similarity classifications.
- **Recall**: Ratio of true similarity classifications to all expected similarity pairs.
- **F1 Score**: Harmonic mean of Precision and Recall.
- **p95 Latency**: 95th percentile response time for search comparison checks.
