import boto3
import csv
import io
import os
import psycopg2
import psycopg2.extras

S3_BUCKET = "delhi-transport-gtfs"

DB_CONFIG = {
    "host":     os.environ["TSDB_HOST"],
    "port":     os.environ["TSDB_PORT"],
    "database": "tsdb",
    "user":     "tsdbadmin",
    "password": os.environ["TSDB_PASSWORD"],
    "sslmode":  "require"
}

s3 = boto3.client("s3")

def read_s3_csv(key):
    print(f"Reading s3://{S3_BUCKET}/{key} ...")
    response = s3.get_object(Bucket=S3_BUCKET, Key=key)
    content = response["Body"].read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))

def progress_bar(current, total, bar_width=45):
    filled = int(bar_width * current / total) if total > 0 else 0
    bar = "=" * filled + ">" + "-" * (bar_width - filled - 1)
    print(f"\r  Progress:  |{bar}| {current}/{total} rows loaded...",
          end="", flush=True)

def batch_insert(conn, rows, sql, row_mapper, table_name, batch_size=1000):
    total = len(rows)
    print(f"  Total rows: {total}")
    inserted = 0
    skipped = 0
    cur = conn.cursor()
    batch = []

    for i, row in enumerate(rows):
        try:
            mapped = row_mapper(row)
            if mapped:
                batch.append(mapped)
        except Exception:
            skipped += 1
            continue

        if len(batch) >= batch_size:
            psycopg2.extras.execute_batch(cur, sql, batch, page_size=batch_size)
            conn.commit()
            inserted += len(batch)
            batch = []
            progress_bar(inserted, total)

    if batch:
        psycopg2.extras.execute_batch(cur, sql, batch, page_size=batch_size)
        conn.commit()
        inserted += len(batch)

    progress_bar(inserted, total)
    print()
    print(f"  Done — inserted: {inserted} | skipped: {skipped}")
    return inserted

def load_routes(conn):
    print("\n--- Loading routes ---")
    rows = read_s3_csv("routes.txt")
    cur = conn.cursor()
    cur.execute("TRUNCATE routes CASCADE")
    conn.commit()

    sql = """
        INSERT INTO routes (route_id, agency_id, route_short_name, route_long_name, route_type)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (route_id) DO NOTHING
    """

    def mapper(row):
        return (
            row["route_id"].strip(),
            row.get("agency_id", "").strip(),
            row.get("route_short_name", "").strip(),
            row.get("route_long_name", "").strip(),
            int(row.get("route_type", 3))
        )

    return batch_insert(conn, rows, sql, mapper, "routes")

def load_stops(conn):
    print("\n--- Loading stops ---")
    rows = read_s3_csv("stops.txt")
    cur = conn.cursor()
    cur.execute("TRUNCATE stops CASCADE")
    conn.commit()

    sql = """
        INSERT INTO stops (stop_id, stop_code, stop_name, stop_lat, stop_lon, zone_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (stop_id) DO NOTHING
    """

    def mapper(row):
        return (
            row["stop_id"].strip(),
            row.get("stop_code", "").strip(),
            row.get("stop_name", "").strip(),
            float(row["stop_lat"]) if row.get("stop_lat") else None,
            float(row["stop_lon"]) if row.get("stop_lon") else None,
            row.get("zone_id", "").strip()
        )

    return batch_insert(conn, rows, sql, mapper, "stops")

def load_trips(conn):
    print("\n--- Loading trips ---")
    rows = read_s3_csv("trips.txt")
    cur = conn.cursor()
    cur.execute("TRUNCATE trips CASCADE")
    conn.commit()

    sql = """
        INSERT INTO trips (trip_id, route_id, service_id, shape_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (trip_id) DO NOTHING
    """

    def mapper(row):
        return (
            row["trip_id"].strip(),
            row["route_id"].strip(),
            row.get("service_id", "").strip(),
            row.get("shape_id", "").strip()
        )

    return batch_insert(conn, rows, sql, mapper, "trips")

def load_calendar(conn):
    print("\n--- Loading calendar ---")
    rows = read_s3_csv("calendar.txt")
    cur = conn.cursor()
    cur.execute("TRUNCATE calendar")
    conn.commit()

    sql = """
        INSERT INTO calendar
            (service_id, monday, tuesday, wednesday, thursday,
             friday, saturday, sunday, start_date, end_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (service_id) DO NOTHING
    """

    def mapper(row):
        return (
            row["service_id"].strip(),
            int(row.get("monday", 0)),
            int(row.get("tuesday", 0)),
            int(row.get("wednesday", 0)),
            int(row.get("thursday", 0)),
            int(row.get("friday", 0)),
            int(row.get("saturday", 0)),
            int(row.get("sunday", 0)),
            row.get("start_date", "").strip(),
            row.get("end_date", "").strip()
        )

    return batch_insert(conn, rows, sql, mapper, "calendar")

def main():
    print("Connecting to TimescaleDB Cloud...")
    conn = psycopg2.connect(**DB_CONFIG)
    print("Connected.")

    routes_count   = load_routes(conn)
    stops_count    = load_stops(conn)
    trips_count    = load_trips(conn)
    calendar_count = load_calendar(conn)

    print("\n========================================")
    print(" Final row counts")
    print("========================================")
    print(f"  routes:   {routes_count}")
    print(f"  stops:    {stops_count}")
    print(f"  trips:    {trips_count}")
    print(f"  calendar: {calendar_count}")
    print("========================================")

    conn.close()
    print("\nReference data load complete.")

if __name__ == "__main__":
    main()
    
    
    
    
# import boto3
# import csv
# import io
# import os
# import psycopg2

# S3_BUCKET = "delhi-transport-gtfs"

# DB_CONFIG = {
#     "host":     os.environ["TSDB_HOST"],
#     "port":     os.environ["TSDB_PORT"],
#     "database": "tsdb",
#     "user":     "tsdbadmin",
#     "password": os.environ["TSDB_PASSWORD"],
#     "sslmode":  "require"
# }

# s3 = boto3.client("s3")

# def read_s3_csv(key):
#     print(f"Reading s3://{S3_BUCKET}/{key} ...")
#     response = s3.get_object(Bucket=S3_BUCKET, Key=key)
#     content = response["Body"].read().decode("utf-8-sig")
#     return list(csv.DictReader(io.StringIO(content)))

# def load_routes(conn):
#     rows = read_s3_csv("routes.txt")
#     cur = conn.cursor()
#     cur.execute("TRUNCATE routes CASCADE")
#     inserted = 0
#     for row in rows:
#         cur.execute("""
#             INSERT INTO routes (route_id, agency_id, route_short_name, route_long_name, route_type)
#             VALUES (%s, %s, %s, %s, %s)
#             ON CONFLICT (route_id) DO NOTHING
#         """, (
#             row["route_id"].strip(),
#             row.get("agency_id", "").strip(),
#             row.get("route_short_name", "").strip(),
#             row.get("route_long_name", "").strip(),
#             int(row.get("route_type", 3))
#         ))
#         inserted += 1
#     conn.commit()
#     print(f"  Routes inserted: {inserted}")

# def load_stops(conn):
#     rows = read_s3_csv("stops.txt")
#     cur = conn.cursor()
#     cur.execute("TRUNCATE stops CASCADE")
#     inserted = 0
#     for row in rows:
#         try:
#             cur.execute("""
#                 INSERT INTO stops (stop_id, stop_code, stop_name, stop_lat, stop_lon, zone_id)
#                 VALUES (%s, %s, %s, %s, %s, %s)
#                 ON CONFLICT (stop_id) DO NOTHING
#             """, (
#                 row["stop_id"].strip(),
#                 row.get("stop_code", "").strip(),
#                 row.get("stop_name", "").strip(),
#                 float(row["stop_lat"]) if row.get("stop_lat") else None,
#                 float(row["stop_lon"]) if row.get("stop_lon") else None,
#                 row.get("zone_id", "").strip()
#             ))
#             inserted += 1
#         except Exception as e:
#             print(f"  Skipping stop {row.get('stop_id')} — {e}")
#     conn.commit()
#     print(f"  Stops inserted: {inserted}")

# def load_trips(conn):
#     rows = read_s3_csv("trips.txt")
#     cur = conn.cursor()
#     cur.execute("TRUNCATE trips CASCADE")
#     inserted = 0
#     skipped = 0
#     for row in rows:
#         try:
#             cur.execute("""
#                 INSERT INTO trips (trip_id, route_id, service_id, shape_id)
#                 VALUES (%s, %s, %s, %s)
#                 ON CONFLICT (trip_id) DO NOTHING
#             """, (
#                 row["trip_id"].strip(),
#                 row["route_id"].strip(),
#                 row.get("service_id", "").strip(),
#                 row.get("shape_id", "").strip()
#             ))
#             inserted += 1
#         except Exception as e:
#             skipped += 1
#     conn.commit()
#     print(f"  Trips inserted: {inserted} | Skipped: {skipped}")

# def load_calendar(conn):
#     rows = read_s3_csv("calendar.txt")
#     cur = conn.cursor()
#     cur.execute("TRUNCATE calendar")
#     inserted = 0
#     for row in rows:
#         cur.execute("""
#             INSERT INTO calendar
#                 (service_id, monday, tuesday, wednesday, thursday,
#                  friday, saturday, sunday, start_date, end_date)
#             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
#             ON CONFLICT (service_id) DO NOTHING
#         """, (
#             row["service_id"].strip(),
#             int(row.get("monday", 0)),
#             int(row.get("tuesday", 0)),
#             int(row.get("wednesday", 0)),
#             int(row.get("thursday", 0)),
#             int(row.get("friday", 0)),
#             int(row.get("saturday", 0)),
#             int(row.get("sunday", 0)),
#             row.get("start_date", "").strip(),
#             row.get("end_date", "").strip()
#         ))
#         inserted += 1
#     conn.commit()
#     print(f"  Calendar entries inserted: {inserted}")

# def main():
#     print("Connecting to TimescaleDB Cloud...")
#     conn = psycopg2.connect(**DB_CONFIG)
#     print("Connected.\n")

#     print("Loading reference data from S3...")
#     load_routes(conn)
#     load_stops(conn)
#     load_trips(conn)
#     load_calendar(conn)

#     cur = conn.cursor()
#     cur.execute("""
#         SELECT 'routes' AS tbl, COUNT(*) FROM routes
#         UNION ALL SELECT 'stops', COUNT(*) FROM stops
#         UNION ALL SELECT 'trips', COUNT(*) FROM trips
#         UNION ALL SELECT 'calendar', COUNT(*) FROM calendar
#     """)
#     print("\nFinal row counts:")
#     for row in cur.fetchall():
#         print(f"  {row[0]}: {row[1]}")

#     conn.close()
#     print("\nReference data load complete.")

# if __name__ == "__main__":
#     main()
