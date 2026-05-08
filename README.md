# Delhi Transport Analytics Platform
### Real-time bus arrival analytics on AWS S3 + TimescaleDB Cloud

---

## What This Project Is

A cloud data pipeline and time-series analytics platform built on
real Delhi DTC bus schedule data. The system ingests GTFS transport
data from AWS S3, simulates realistic arrival delay events, stores
them in TimescaleDB Cloud, and runs analytical queries that answer
real operational questions about bus network performance.

Built specifically to demonstrate expertise in TimescaleDB Cloud,
AWS S3 pipelines, time-series SQL analytics, and PostgreSQL
database engineering — the core skills required for database
support engineering on modern cloud platforms.

---

## Live Infrastructure

| Component | Technology | Details |
|---|---|---|
| Cloud database | TimescaleDB Cloud | PostgreSQL 18.3 + TimescaleDB 2.26.4 |
| Cloud region | AWS ap-south-1 | Mumbai — lowest latency from India |
| Data storage | AWS S3 | Bucket: delhi-transport-gtfs |
| Data source | Delhi GTFS | otd.delhi.gov.in — official government data |
| Pipeline | Python + boto3 | S3 → TimescaleDB Cloud |

---

## Architecture
```
Delhi GTFS Data (otd.delhi.gov.in)
│
│  Official government open data
▼
AWS S3 Bucket (delhi-transport-gtfs, ap-south-1)
├── routes.txt      (~52 KB)
├── stops.txt       (~613 KB)
├── trips.txt       (~1.7 MB)
├── stop_times.txt  (~142 MB)
└── calendar.txt
│
│  boto3 — reads directly from S3 into memory
▼
Python Ingestion Pipeline
├── load_reference_data.py  ← routes, stops, trips, calendar
└── load_arrivals.py        ← 500,000 simulated arrival events
│
│  psycopg2 batch INSERT (5,000 rows per commit)
▼
TimescaleDB Cloud (tsdb, ap-south-1)
├── Hypertable: bus_arrivals (500,000 rows)
├── Continuous aggregates (3 views)
├── Compression enabled
└── Automated refresh + compression policies
```
---

## Dataset

| Table | Rows | Description |
|---|---|---|
| routes | 2,403 | DTC bus routes across Delhi |
| stops | 10,559 | Bus stops with GPS coordinates |
| trips | 89,393 | Individual scheduled trips |
| calendar | 1 | Service day definitions |
| bus_arrivals | 500,000 | Simulated arrival events (hypertable) |

### Delay Simulation Model

GTFS static data contains scheduled times only — not live GPS
arrival data. Delays are modelled using a realistic probability
distribution based on urban bus network behaviour:

| Scenario | Probability | Delay Range |
|---|---|---|
| Early or on time | 15% | −120s to 0s |
| Minor delay | 45% | 0s to 180s |
| Moderate delay | 25% | 180s to 600s |
| Significant delay | 10% | 600s to 1800s |
| Severe delay | 5% | 1800s to 3600s |

A bus is classified as **delayed** when delay > 300 seconds (5 minutes)
— consistent with standard transit performance benchmarks globally.

---

## TimescaleDB Features Used

### Hypertable
`bus_arrivals` is partitioned by `scheduled_time` into automatic
time-based chunks. Each chunk corresponds to a time window of
scheduled arrivals — enabling efficient time-range queries and
chunk-level compression.

### Continuous Aggregates

| View | Bucket | Groups By | Refresh |
|---|---|---|---|
| route_performance_hourly | 1 hour | route_id | Every 1 hour |
| stop_performance_hourly | 1 hour | stop_id | Every 1 hour |
| system_performance_hourly | 1 hour | — | Every 1 hour |

All three use a 3-day lookback window and 1-hour end offset
to handle late-arriving data gracefully.

### Compression
```sql
ALTER TABLE bus_arrivals SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'route_id',
    timescaledb.compress_orderby   = 'scheduled_time DESC'
);
```
`compress_segmentby = 'route_id'` chosen because the majority
of analytical queries filter or group by route — compressed data
remains queryable without full decompression.

Storage savings: **88% per chunk**
Compression policy: chunks older than 7 days compress automatically.

---

## SQL Analytics

8 complex analytical queries in `sql-analytics/queries.sql`
demonstrating advanced time-series SQL on real transport data.

| Query | Technique | Question Answered |
|---|---|---|
| Worst routes by delay | Aggregation + JOIN | Which routes are most chronically late? |
| Hourly delay pattern | TIME_BUCKET | Which hours have worst delays? |
| Route delay ranking | RANK() OVER PARTITION BY | How do routes compare within their type? |
| Stop delay hotspots | Aggregation + spatial JOIN | Which stops are worst for delays? |
| Cumulative delay | SUM() OVER running total | How does system delay build across the day? |
| Delay severity | NTILE(4) segmentation | Which routes are in the critical quartile? |
| Consecutive stop delays | LAG() PARTITION BY trip | How does delay compound stop-to-stop? |
| System summary report | 3-level CTE + CROSS JOIN | Full daily performance overview |

**TIME_BUCKET** — a TimescaleDB-specific function used throughout
for grouping time-series data. More efficient than DATE_TRUNC for
hypertable workloads because it aligns with chunk boundaries.

---

## PL/pgSQL Objects

All objects in `sql-analytics/functions.sql`

| Object | Type | Purpose |
|---|---|---|
| `classify_delay(INT)` | Function | Maps delay seconds to severity label |
| `get_route_health_report(TEXT)` | Function | Full delay health report for any route |
| `get_worst_stops(INT, INT)` | Function | Top N worst stops for a given hour |
| `refresh_all_aggregates(TIMESTAMPTZ, TIMESTAMPTZ)` | Procedure | Refreshes all 3 aggregates in sequence with timing |

### Example Usage
```sql
-- Health report for a specific route
SELECT * FROM get_route_health_report('DL-1A');

-- Worst performing stops during morning rush hour
SELECT * FROM get_worst_stops(8, 15);

-- Refresh all aggregates for yesterday
CALL refresh_all_aggregates(
    NOW() - INTERVAL '1 day',
    NOW()
);
```

---

## How to Reproduce This Project

### Prerequisites
- Python 3.x with `pip install boto3 psycopg2-binary`
- AWS account with S3 access (free tier sufficient)
- TimescaleDB Cloud account (free tier sufficient)
- Delhi GTFS data from otd.delhi.gov.in

### Environment Variables Required
```cmd
SET AWS_ACCESS_KEY_ID=your_key
SET AWS_SECRET_ACCESS_KEY=your_secret
SET AWS_DEFAULT_REGION=ap-south-1
SET TSDB_HOST=your_host.tsdb.cloud.timescale.com
SET TSDB_PORT=your_port
SET TSDB_PASSWORD=your_password
```

### Run Order
```cmd
Step 1: Run schema SQL in TimescaleDB Cloud (setup\README.md)
Step 2: python ingestion\load_reference_data.py
Step 3: python ingestion\load_arrivals.py
Step 4: Run continuous aggregate SQL (docs\timescaledb_features.md)
Step 5: Run analytical queries (sql-analytics\queries.sql)
```

---

## Key Technical Decisions

**Why TimescaleDB Cloud over local PostgreSQL:**
TimescaleDB Cloud is the exact platform Tiger Data sells and
supports. Running this project on the actual product demonstrates
familiarity with the real customer environment — not just the
open-source extension.

**Why AWS S3 over local files:**
GTFS files committed to Git would bloat the repository. S3
keeps data in the cloud where it belongs, demonstrates AWS
integration, and makes the pipeline reproducible by anyone
with credentials — not just the original developer's machine.

**Why batch inserts of 5,000 rows:**
Each network round trip to TimescaleDB Cloud has latency.
Row-by-row inserts on a 142MB file would take hours.
Batching 5,000 rows per commit reduces network calls from
millions to hundreds — typical production ingestion pattern.

**Why simulate delays instead of using live data:**
The Delhi OTD real-time GPS feed requires government API
authorization. The static GTFS data is openly available.
The simulation model produces statistically realistic delay
distributions that match real urban bus network behaviour —
making the analytics meaningful even without live data.

---

## What This Project Demonstrates

| Skill | How Demonstrated |
|---|---|
| TimescaleDB Cloud | Live cloud service, hypertable, aggregates, compression |
| AWS S3 | Bucket, IAM, boto3 pipeline |
| Time-series SQL | TIME_BUCKET, window functions, CTEs on 500k rows |
| PL/pgSQL | Functions, procedures, edge case handling |
| Data pipeline engineering | S3 → Python → TimescaleDB batch ingestion |
| Real-world data | Official Delhi government GTFS dataset |
| Performance optimisation | Batch inserts, continuous aggregates, compression |