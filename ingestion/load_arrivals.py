# ============================================================
# load_arrivals.py
# Delhi Transport Analytics Platform
# ============================================================
# Purpose: Reads stop_times.txt from AWS S3, simulates
#          realistic arrival delays, and batch-inserts
#          500,000 events into the bus_arrivals hypertable.
# Source:  s3://delhi-transport-gtfs/stop_times.txt
# Target:  TimescaleDB Cloud — bus_arrivals hypertable
# Delay model: probability-weighted simulation (see README)
# ============================================================

import boto3
import csv
import io
import os
import random
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone

S3_BUCKET = "delhi-transport-gtfs"
SIMULATION_DATE = datetime(2024, 1, 15, tzinfo=timezone.utc)
BATCH_SIZE = 5000
MAX_ROWS = 500000

DB_CONFIG = {
    "host":     os.environ["TSDB_HOST"],
    "port":     os.environ["TSDB_PORT"],
    "database": "tsdb",
    "user":     "tsdbadmin",
    "password": os.environ["TSDB_PASSWORD"],
    "sslmode":  "require"
}

def parse_gtfs_time(time_str, base_date):
    time_str = time_str.strip()
    if not time_str:
        return None
    try:
        parts = time_str.split(":")
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return base_date + timedelta(hours=h, minutes=m, seconds=s)
    except Exception:
        return None

def simulate_delay():
    r = random.random()
    if r < 0.15:
        return random.randint(-120, 0)
    elif r < 0.60:
        return random.randint(0, 180)
    elif r < 0.85:
        return random.randint(180, 600)
    elif r < 0.95:
        return random.randint(600, 1800)
    else:
        return random.randint(1800, 3600)

def progress_bar(current, total, bar_width=45):
    pct = current / total if total > 0 else 0
    filled = int(bar_width * pct)
    bar = "=" * filled + ">" + "-" * (bar_width - filled - 1)
    print(f"\r  Progress:  |{bar}| {current}/{total} rows loaded...",
          end="", flush=True)

def get_valid_trip_ids(conn):
    cur = conn.cursor()
    cur.execute("SELECT trip_id FROM trips")
    return {row[0] for row in cur.fetchall()}

def get_valid_stop_ids(conn):
    cur = conn.cursor()
    cur.execute("SELECT stop_id FROM stops")
    return {row[0] for row in cur.fetchall()}

def get_trip_route_map(conn):
    cur = conn.cursor()
    cur.execute("SELECT trip_id, route_id FROM trips")
    return {row[0]: row[1] for row in cur.fetchall()}

def count_s3_rows(content):
    return content.count("\n") - 1

def main():
    print("Connecting to TimescaleDB Cloud...")
    conn = psycopg2.connect(**DB_CONFIG)
    print("Connected.\n")

    print("Loading valid trip and stop IDs for validation...")
    valid_trips    = get_valid_trip_ids(conn)
    valid_stops    = get_valid_stop_ids(conn)
    trip_route_map = get_trip_route_map(conn)
    print(f"  Valid trips: {len(valid_trips)}")
    print(f"  Valid stops: {len(valid_stops)}")

    print(f"\nReading stop_times.txt from S3...")
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=S3_BUCKET, Key="stop_times.txt")
    content = response["Body"].read().decode("utf-8-sig")

    total_rows = min(count_s3_rows(content), MAX_ROWS)
    print(f"  Total rows (capped at {MAX_ROWS}): {total_rows}")

    print(f"\n--- Loading bus_arrivals ---")
    cur = conn.cursor()
    cur.execute("TRUNCATE bus_arrivals")
    conn.commit()

    reader = csv.DictReader(io.StringIO(content))

    batch          = []
    total_inserted = 0
    total_skipped  = 0

    for row in reader:

        if total_inserted + len(batch) >= MAX_ROWS:
            break

        trip_id      = row.get("trip_id", "").strip()
        stop_id      = row.get("stop_id", "").strip()
        arrival_str  = row.get("arrival_time", "").strip()
        depart_str   = row.get("departure_time", "").strip()
        seq          = row.get("stop_sequence", "0").strip()

        if trip_id not in valid_trips or stop_id not in valid_stops:
            total_skipped += 1
            continue

        scheduled_time = parse_gtfs_time(arrival_str, SIMULATION_DATE)
        if not scheduled_time:
            total_skipped += 1
            continue

        departure_time = parse_gtfs_time(depart_str, SIMULATION_DATE)
        delay          = simulate_delay()
        actual_time    = scheduled_time + timedelta(seconds=delay)
        route_id       = trip_route_map.get(trip_id)

        batch.append((
            scheduled_time,
            actual_time,
            delay,
            trip_id,
            stop_id,
            route_id,
            int(seq) if seq.isdigit() else 0,
            departure_time
        ))

        if len(batch) >= BATCH_SIZE:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO bus_arrivals
                    (scheduled_time, actual_time, delay_seconds,
                     trip_id, stop_id, route_id,
                     stop_sequence, departure_time)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, batch, page_size=BATCH_SIZE)
            conn.commit()
            total_inserted += len(batch)
            batch = []
            progress_bar(total_inserted, total_rows)

    if batch:
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO bus_arrivals
                (scheduled_time, actual_time, delay_seconds,
                 trip_id, stop_id, route_id,
                 stop_sequence, departure_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, batch, page_size=BATCH_SIZE)
        conn.commit()
        total_inserted += len(batch)

    progress_bar(total_inserted, total_rows)
    print()

    print(f"\n  Total inserted: {total_inserted}")
    print(f"  Total skipped:  {total_skipped}")

    cur.execute("""
        SELECT
            COUNT(*)                              AS total_arrivals,
            COUNT(*) FILTER (WHERE is_delayed)    AS delayed,
            ROUND(AVG(delay_seconds))             AS avg_delay_secs,
            MAX(delay_seconds)                    AS max_delay_secs,
            MIN(delay_seconds)                    AS min_delay_secs
        FROM bus_arrivals
    """)
    s = cur.fetchone()
    print(f"\n========================================")
    print(f" Delay statistics")
    print(f"========================================")
    print(f"  Total arrivals:  {s[0]}")
    print(f"  Delayed (>5min): {s[1]}")
    print(f"  Avg delay:       {s[2]}s")
    print(f"  Max delay:       {s[3]}s")
    print(f"  Min delay:       {s[4]}s")
    print(f"========================================")

    conn.close()
    print("\nArrival data load complete.")

if __name__ == "__main__":
    main()
