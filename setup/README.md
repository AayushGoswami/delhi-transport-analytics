# Setup - Schema Design & Project Architecture

## Database
**TimescaleDB Cloud** - Service: delhi-transport
PostgreSQL 18.3 + TimescaleDB 2.26.4
Region: AWS ap-south-1 (Mumbai)

## Data Source
**Delhi GTFS Static Data** - [otd.delhi.gov.in](https://otd.delhi.gov.in)

| File | Description | Size |
|---|---|---|
| `routes.txt` | All DTC bus routes | ~52 KB |
| `stops.txt` | All bus stops with GPS coordinates | ~613 KB |
| `trips.txt` | Individual scheduled trips per route | ~1.7 MB |
| `stop_times.txt` | Scheduled arrival/departure per stop per trip | ~142 MB |
| `calendar.txt` | Service day definitions | ~122 bytes |

Files not used: `fare_attributes.txt`, `fare_rules.txt` - not relevant
to arrival time analytics.

---

## Cloud Architecture

```
Delhi GTFS Data (otd.delhi.gov.in)
│
│  Manual download
▼
AWS S3 Bucket (delhi-transport-gtfs, ap-south-1)
├── routes.txt
├── stops.txt
├── trips.txt
├── stop_times.txt
└── calendar.txt
│
│  boto3 (Python AWS SDK)
▼
Python Pipeline (ingestion)
├── load_reference_data.py   ← routes, stops, trips, calendar
└── load_arrivals.py         ← bus_arrivals simulation
│
│  psycopg2 batch INSERT
▼
TimescaleDB Cloud (tsdb, ap-south-1)
```

---

## AWS Infrastructure

| Resource | Name | Purpose |
|---|---|---|
| S3 Bucket | `delhi-transport-gtfs` | Stores all GTFS source files |
| IAM User | `delhi-transport-pipeline` | Identity for Python pipeline |
| IAM Policy | `AmazonS3ReadOnlyAccess` | Read-only access to S3 |
| Region | `ap-south-1` (Mumbai) | Closest to India, lowest latency |

---

## Database Tables

### routes
DTC bus routes across Delhi.
Primary key: `route_id` (text - GTFS standard)
Includes: `agency_id`, `route_short_name`, `route_long_name`, `route_type`

### stops
All bus stops in Delhi with GPS coordinates.
Primary key: `stop_id`
Includes: `stop_code`, `stop_name`, `stop_lat`, `stop_lon`, `zone_id`
Coordinates stored as NUMERIC(10,6) for GPS precision.

### trips
Individual scheduled trips per route.
Primary key: `trip_id`
References routes via `route_id` FK.
Includes: `service_id`, `shape_id`

### calendar
Service day definitions - which days each service_id operates.
Primary key: `service_id`
Includes: day-of-week flags (monday–sunday), `start_date`, `end_date`

### bus_arrivals (Hypertable)
Core time-series table - one row per bus arrival event at a stop.
Partitioned by `scheduled_time` into TimescaleDB chunks.

| Column | Type | Description |
|---|---|---|
| `arrival_id` | `BIGSERIAL` | Auto-incrementing PK |
| `scheduled_time` | `TIMESTAMPTZ` | Original scheduled arrival time |
| `actual_time` | `TIMESTAMPTZ` | Simulated actual arrival time |
| `delay_seconds` | `INT` | Difference in seconds (actual − scheduled) |
| `trip_id` | `TEXT` | FK → trips |
| `stop_id` | `TEXT` | FK → stops |
| `route_id` | `TEXT` | FK → routes |
| `stop_sequence` | `INT` | Position of this stop on the trip |
| `departure_time` | `TIMESTAMPTZ` | Scheduled departure from this stop |
| is_d`elayed | `BOOLEAN GENERATED` | Auto-computed - true if delay > 300s |

---

## Indexes on bus_arrivals

| Index | Columns | Type | Purpose |
|---|---|---|---|
| `idx_arrivals_route` | (`route_id`, `scheduled_time DESC`) | B-tree | Route-level queries |
| `idx_arrivals_stop` | (`stop_id`, `scheduled_time DESC`) | B-tree | Stop-level queries |
| `idx_arrivals_trip` | (`trip_id`, `scheduled_time DESC`) | B-tree | Trip-level queries |
| `idx_arrivals_delayed` | `(is_delayed`, `scheduled_time DESC) WHERE is_delayed = true` | Partial | Delay-specific queries |

---

## TimescaleDB Features Configured

### Continuous Aggregates

| View | Partitioned By | Refresh Policy | Purpose |
|---|---|---|---|
| `route_performance_hourly` | 1 hour bucket + route_id | Every 1 hour, 3-day lookback | Route delay analytics |
| `stop_performance_hourly` | 1 hour bucket + stop_id | Every 1 hour, 3-day lookback | Stop hotspot analytics |
| `system_performance_hourly` | 1 hour bucket | Every 1 hour, 3-day lookback | System-wide summary |

### Compression

| Setting | Value | Reason |
|---|---|---|
| `compress_segmentby` | `route_id` | Most queries filter by route |
| `compress_orderby` | `scheduled_time DESC` | Optimises recent-data queries |
| Compression policy | Chunks older than 7 days | Automatic historical compression |
| Average storage savings | 88 % | Measured from chunk_compression_stats |

---

## Delay Simulation Model

Since GTFS static data contains scheduled times only - not live GPS
arrival data - delays are simulated using a realistic probability
distribution modelled on urban bus network behaviour:

| Scenario | Probability | Delay Range |
|---|---|---|
| Early / on time | 15% | −120s to 0s |
| Minor delay | 45% | 0s to 180s |
| Moderate delay | 25% | 180s to 600s |
| Significant delay | 10% | 600s to 1800s |
| Severe delay | 5% | 1800s to 3600s |

`is_delayed` is defined as delay > 300 seconds (5 minutes) -
consistent with standard transit performance benchmarks.

---

## Row Counts After Ingestion

| Table | Row Count |
|---|---|
| `routes` | 2,403 |
| `stops` | 10,559 |
| `trips` | 89,393 |
| `calendar` | 1 |
| `bus_arrivals` | 500,000 |

---

## Design Decisions

**TIMESTAMPTZ over TIMESTAMP** - all times are timezone-aware. Critical
for a transport system operating in IST (UTC+5:30).

**GENERATED ALWAYS AS for is_delayed** - computed automatically from
delay_seconds, never manually inserted. Ensures consistency across
all rows without application-level logic.

**Composite indexes with scheduled_time DESC** - matches the most common
query pattern: filter by route or stop, then order by most recent first.

**Partial index on is_delayed = true** - only indexes delayed arrivals.
Smaller index, faster for delay-specific analytical queries.

**compress_segmentby = route_id** - chosen because the vast majority
of analytical queries group or filter by route_id. Grouping compressed
data by this column means route-filtered queries avoid decompressing
irrelevant segments.

**S3 as data source over local files** - GTFS files stored in AWS S3
rather than committed to the repository. Demonstrates cloud data pipeline
architecture and keeps the repository clean of large binary files.
