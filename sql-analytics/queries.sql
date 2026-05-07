-- ============================================================
-- Query 1: Worst performing routes by average delay
-- Technique: Aggregation + JOIN + ORDER BY
-- Purpose: Identify which bus routes are most chronically late
-- ============================================================

SELECT
    r.route_short_name,
    r.route_long_name,
    COUNT(*)                            AS total_arrivals,
    COUNT(*) FILTER (WHERE b.is_delayed) AS delayed_arrivals,
    ROUND(AVG(b.delay_seconds))         AS avg_delay_seconds,
    ROUND(AVG(b.delay_seconds) / 60.0, 1) AS avg_delay_minutes,
    MAX(b.delay_seconds)                AS worst_delay_seconds
FROM bus_arrivals b
JOIN routes r ON r.route_id = b.route_id
GROUP BY r.route_id, r.route_short_name, r.route_long_name
HAVING COUNT(*) > 10
ORDER BY avg_delay_seconds DESC
LIMIT 20;

-- Planning Time: 0.643 ms
-- Execution Time: 237.300 ms

-- ============================================================
-- Query 2: Hourly delay pattern across the day
-- Technique: TIME_BUCKET (TimescaleDB) + aggregation
-- Purpose: Find which hours of day have worst delays
-- ============================================================

SELECT
    TIME_BUCKET('1 hour', scheduled_time) AS hour_bucket,
    COUNT(*)                              AS total_arrivals,
    COUNT(*) FILTER (WHERE is_delayed)    AS delayed_count,
    ROUND(
        COUNT(*) FILTER (WHERE is_delayed) * 100.0 / COUNT(*),
    1)                                    AS delay_pct,
    ROUND(AVG(delay_seconds))             AS avg_delay_secs,
    ROUND(MAX(delay_seconds) / 60.0, 1)  AS max_delay_mins
FROM bus_arrivals
GROUP BY hour_bucket
ORDER BY hour_bucket;

-- Planning Time: 0.306 ms
-- Execution Time: 157.174 ms

-- ============================================================
-- Query 3: Route delay ranking using window function
-- Technique: RANK() OVER PARTITION BY
-- Purpose: Rank routes by delay within each route_type
-- ============================================================

WITH route_stats AS (
    SELECT
        b.route_id,
        r.route_short_name,
        r.route_type,
        COUNT(*)                              AS total_arrivals,
        ROUND(AVG(b.delay_seconds))           AS avg_delay,
        ROUND(AVG(b.delay_seconds) / 60.0, 1) AS avg_delay_mins
    FROM bus_arrivals b
    JOIN routes r ON r.route_id = b.route_id
    GROUP BY b.route_id, r.route_short_name, r.route_type
    HAVING COUNT(*) > 5
)
SELECT
    route_short_name,
    route_type,
    total_arrivals,
    avg_delay_mins,
    RANK() OVER (
        PARTITION BY route_type
        ORDER BY avg_delay DESC
    ) AS delay_rank_in_type
FROM route_stats
ORDER BY route_type, delay_rank_in_type
LIMIT 30;

-- Planning Time: 0.421 ms
-- Execution Time: 204.662 ms

-- ============================================================
-- Query 4: Stop-level delay hotspots
-- Technique: Aggregation + JOIN + filtering
-- Purpose: Find which stops have the worst delay patterns
-- ============================================================

SELECT
    s.stop_name,
    s.stop_lat,
    s.stop_lon,
    COUNT(*)                              AS total_arrivals,
    COUNT(*) FILTER (WHERE b.is_delayed)  AS delayed_count,
    ROUND(AVG(b.delay_seconds) / 60.0, 1) AS avg_delay_mins,
    ROUND(
        COUNT(*) FILTER (WHERE b.is_delayed) * 100.0 / COUNT(*),
    1)                                    AS delay_pct
FROM bus_arrivals b
JOIN stops s ON s.stop_id = b.stop_id
GROUP BY s.stop_id, s.stop_name, s.stop_lat, s.stop_lon
HAVING COUNT(*) > 5
ORDER BY avg_delay_mins DESC
LIMIT 20;

-- Planning Time: 0.419 ms
-- Execution Time: 202.120 ms

-- ============================================================
-- Query 5: Cumulative delay accumulation across the day
-- Technique: SUM() window function with ROWS frame
-- Purpose: Show how total system delay builds up hour by hour
-- ============================================================

WITH hourly AS (
    SELECT
        TIME_BUCKET('1 hour', scheduled_time) AS hour_bucket,
        ROUND(SUM(delay_seconds) / 60.0)      AS total_delay_mins,
        COUNT(*)                               AS arrivals
    FROM bus_arrivals
    GROUP BY hour_bucket
)
SELECT
    hour_bucket,
    arrivals,
    total_delay_mins,
    SUM(total_delay_mins) OVER (
        ORDER BY hour_bucket
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_delay_mins
FROM hourly
ORDER BY hour_bucket;

-- Planning Time: 0.259 ms
-- Execution Time: 143.471 ms

-- ============================================================
-- Query 6: Route delay severity segmentation
-- Technique: NTILE() window function
-- Purpose: Classify routes into delay severity quartiles
-- ============================================================

WITH route_delays AS (
    SELECT
        b.route_id,
        r.route_short_name,
        ROUND(AVG(b.delay_seconds))            AS avg_delay,
        COUNT(*)                               AS total_arrivals
    FROM bus_arrivals b
    JOIN routes r ON r.route_id = b.route_id
    GROUP BY b.route_id, r.route_short_name
    HAVING COUNT(*) > 5
)
SELECT
    route_short_name,
    avg_delay,
    total_arrivals,
    NTILE(4) OVER (ORDER BY avg_delay DESC) AS severity_quartile,
    CASE NTILE(4) OVER (ORDER BY avg_delay DESC)
        WHEN 1 THEN 'Critical — worst 25%'
        WHEN 2 THEN 'High — above average'
        WHEN 3 THEN 'Moderate — below average'
        ELSE        'Good — best 25%'
    END AS severity_label
FROM route_delays
ORDER BY avg_delay DESC;

-- Planning Time: 0.394 ms
-- Execution Time: 182.551 ms

-- ============================================================
-- Query 7: Consecutive stop delays using LAG()
-- Technique: LAG() window function PARTITION BY trip
-- Purpose: Find trips where delays compound stop after stop
-- ============================================================

SELECT
    trip_id,
    stop_sequence,
    stop_id,
    delay_seconds,
    LAG(delay_seconds) OVER (
        PARTITION BY trip_id
        ORDER BY stop_sequence
    ) AS prev_stop_delay,
    delay_seconds - LAG(delay_seconds) OVER (
        PARTITION BY trip_id
        ORDER BY stop_sequence
    ) AS delay_change
FROM bus_arrivals
WHERE trip_id IN (
    SELECT trip_id
    FROM bus_arrivals
    WHERE is_delayed = true
    GROUP BY trip_id
    HAVING COUNT(*) > 3
    LIMIT 5
)
ORDER BY trip_id, stop_sequence;

-- Planning Time: 0.486 ms
-- Execution Time: 0.610 ms

-- ============================================================
-- Query 8: Full delay summary report — multi-level CTE
-- Technique: Three chained CTEs + final aggregation
-- Purpose: Executive-level daily performance summary
-- ============================================================

WITH system_stats AS (
    SELECT
        COUNT(*)                              AS total_arrivals,
        COUNT(*) FILTER (WHERE is_delayed)    AS total_delayed,
        ROUND(AVG(delay_seconds))             AS system_avg_delay,
        ROUND(STDDEV(delay_seconds))          AS system_stddev
    FROM bus_arrivals
),
route_performance AS (
    SELECT
        b.route_id,
        r.route_short_name,
        COUNT(*)                              AS arrivals,
        COUNT(*) FILTER (WHERE b.is_delayed)  AS delayed,
        ROUND(AVG(b.delay_seconds))           AS avg_delay
    FROM bus_arrivals b
    JOIN routes r ON r.route_id = b.route_id
    GROUP BY b.route_id, r.route_short_name
    HAVING COUNT(*) > 5
),
classified AS (
    SELECT
        rp.*,
        ss.system_avg_delay,
        ss.total_arrivals,
        CASE
            WHEN rp.avg_delay > ss.system_avg_delay + ss.system_stddev
                THEN 'Above average delay'
            WHEN rp.avg_delay < ss.system_avg_delay - ss.system_stddev
                THEN 'Below average delay'
            ELSE 'Within normal range'
        END AS performance_vs_system
    FROM route_performance rp
    CROSS JOIN system_stats ss
)
SELECT
    route_short_name,
    arrivals,
    delayed,
    ROUND(delayed * 100.0 / arrivals, 1) AS delay_pct,
    avg_delay,
    performance_vs_system,
    system_avg_delay
FROM classified
ORDER BY avg_delay DESC
LIMIT 25;

-- Planning Time: 0.557 ms
-- Execution Time: 338.142 ms