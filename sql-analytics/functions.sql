-- ============================================================
-- Function: classify_delay()
-- Purpose: Classifies delay seconds into severity category
-- Used by: get_route_health_report()
-- ============================================================

CREATE OR REPLACE FUNCTION classify_delay(delay_seconds INT)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
BEGIN
    IF delay_seconds < 0 THEN
        RETURN 'Early';
    ELSIF delay_seconds <= 60 THEN
        RETURN 'On time';
    ELSIF delay_seconds <= 300 THEN
        RETURN 'Minor delay';
    ELSIF delay_seconds <= 900 THEN
        RETURN 'Moderate delay';
    ELSIF delay_seconds <= 1800 THEN
        RETURN 'Significant delay';
    ELSE
        RETURN 'Severe delay';
    END IF;
END;
$$;

-- ============================================================
-- Function: get_route_health_report()
-- Purpose: Returns detailed delay health report for a route
-- Parameters:
--   p_route_id TEXT - the route to analyse
-- Returns: TABLE with delay breakdown and health score
-- ============================================================

CREATE OR REPLACE FUNCTION get_route_health_report(
    p_route_id TEXT
)
RETURNS TABLE (
    route_short_name    TEXT,
    total_arrivals      BIGINT,
    on_time_count       BIGINT,
    delayed_count       BIGINT,
    on_time_pct         NUMERIC,
    avg_delay_mins      NUMERIC,
    max_delay_mins      NUMERIC,
    health_score        NUMERIC,
    health_label        TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM routes WHERE route_id = p_route_id
    ) INTO v_exists;

    IF NOT v_exists THEN
        RAISE NOTICE 'Route % not found in database', p_route_id;
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        r.route_short_name,
        COUNT(*)                                        AS total_arrivals,
        COUNT(*) FILTER (WHERE b.delay_seconds <= 60)  AS on_time_count,
        COUNT(*) FILTER (WHERE b.is_delayed)           AS delayed_count,
        ROUND(
            COUNT(*) FILTER (WHERE b.delay_seconds <= 60)
            * 100.0 / NULLIF(COUNT(*), 0), 1
        )                                              AS on_time_pct,
        ROUND(AVG(b.delay_seconds) / 60.0, 2)         AS avg_delay_mins,
        ROUND(MAX(b.delay_seconds) / 60.0, 2)         AS max_delay_mins,
        ROUND(
            GREATEST(0,
                100 - (AVG(b.delay_seconds) / 60.0 * 5)
                    - (COUNT(*) FILTER (WHERE b.is_delayed)
                        * 100.0 / NULLIF(COUNT(*), 0) * 0.3)
            )::NUMERIC, 1
        )                                              AS health_score,
        CASE
            WHEN ROUND(GREATEST(0,
                100 - (AVG(b.delay_seconds) / 60.0 * 5)
                    - (COUNT(*) FILTER (WHERE b.is_delayed)
                        * 100.0 / NULLIF(COUNT(*), 0) * 0.3)
            )::NUMERIC, 1) >= 80 THEN 'Healthy'
            WHEN ROUND(GREATEST(0,
                100 - (AVG(b.delay_seconds) / 60.0 * 5)
                    - (COUNT(*) FILTER (WHERE b.is_delayed)
                        * 100.0 / NULLIF(COUNT(*), 0) * 0.3)
            )::NUMERIC, 1) >= 60 THEN 'Needs attention'
            ELSE 'Critical'
        END                                            AS health_label
    FROM bus_arrivals b
    JOIN routes r ON r.route_id = b.route_id
    WHERE b.route_id = p_route_id
    GROUP BY r.route_short_name;
END;
$$;

-- ============================================================
-- Function: get_worst_stops()
-- Purpose: Returns top N worst delay stops for a given hour
-- Parameters:
--   p_hour INT      - hour of day (0-23)
--   p_limit INT     - how many stops to return (default 10)
-- Returns: TABLE with stop name, location, delay stats
-- ============================================================

CREATE OR REPLACE FUNCTION get_worst_stops(
    p_hour  INT,
    p_limit INT DEFAULT 10
)
RETURNS TABLE (
    stop_name       TEXT,
    stop_lat        NUMERIC,
    stop_lon        NUMERIC,
    total_arrivals  BIGINT,
    delayed_count   BIGINT,
    avg_delay_mins  NUMERIC,
    delay_pct       NUMERIC
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_hour < 0 OR p_hour > 23 THEN
        RAISE EXCEPTION 'Hour must be between 0 and 23 — got: %', p_hour;
    END IF;

    RETURN QUERY
    SELECT
        s.stop_name,
        s.stop_lat,
        s.stop_lon,
        COUNT(*)                               AS total_arrivals,
        COUNT(*) FILTER (WHERE b.is_delayed)   AS delayed_count,
        ROUND(AVG(b.delay_seconds) / 60.0, 2) AS avg_delay_mins,
        ROUND(
            COUNT(*) FILTER (WHERE b.is_delayed)
            * 100.0 / NULLIF(COUNT(*), 0), 1
        )                                      AS delay_pct
    FROM bus_arrivals b
    JOIN stops s ON s.stop_id = b.stop_id
    WHERE EXTRACT(HOUR FROM b.scheduled_time) = p_hour
    GROUP BY s.stop_id, s.stop_name, s.stop_lat, s.stop_lon
    HAVING COUNT(*) > 3
    ORDER BY avg_delay_mins DESC
    LIMIT p_limit;
END;
$$;

-- ============================================================
-- Procedure: refresh_all_aggregates()
-- Purpose: Refreshes all three continuous aggregates in sequence
-- Parameters:
--   p_start TIMESTAMPTZ - refresh window start (NULL = full)
--   p_end   TIMESTAMPTZ - refresh window end   (NULL = full)
-- ============================================================

CREATE OR REPLACE PROCEDURE refresh_all_aggregates(
    p_start TIMESTAMPTZ DEFAULT NULL,
    p_end   TIMESTAMPTZ DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_start_time TIMESTAMPTZ := clock_timestamp();
    v_step_time  TIMESTAMPTZ;
BEGIN
    RAISE NOTICE 'Starting aggregate refresh at %', v_start_time;
    RAISE NOTICE 'Window: % to %',
        COALESCE(p_start::TEXT, 'beginning'),
        COALESCE(p_end::TEXT,   'now');

    v_step_time := clock_timestamp();
    RAISE NOTICE '[1/3] Refreshing route_performance_hourly...';
    CALL refresh_continuous_aggregate(
        'route_performance_hourly', p_start, p_end
    );
    RAISE NOTICE '  Done in %ms',
        ROUND(EXTRACT(MILLISECONDS FROM
            clock_timestamp() - v_step_time))::INT;

    v_step_time := clock_timestamp();
    RAISE NOTICE '[2/3] Refreshing stop_performance_hourly...';
    CALL refresh_continuous_aggregate(
        'stop_performance_hourly', p_start, p_end
    );
    RAISE NOTICE '  Done in %ms',
        ROUND(EXTRACT(MILLISECONDS FROM
            clock_timestamp() - v_step_time))::INT;

    v_step_time := clock_timestamp();
    RAISE NOTICE '[3/3] Refreshing system_performance_hourly...';
    CALL refresh_continuous_aggregate(
        'system_performance_hourly', p_start, p_end
    );
    RAISE NOTICE '  Done in %ms',
        ROUND(EXTRACT(MILLISECONDS FROM
            clock_timestamp() - v_step_time))::INT;

    RAISE NOTICE 'All aggregates refreshed. Total time: %ms',
        ROUND(EXTRACT(MILLISECONDS FROM
            clock_timestamp() - v_start_time))::INT;
END;
$$;

-- ============================================================
-- Delhi Transport Analytics — PL/pgSQL Objects
-- Database: TimescaleDB Cloud (tsdb)
-- ============================================================
-- Objects:
--   classify_delay(INT)                  → TEXT
--   get_route_health_report(TEXT)        → TABLE
--   get_worst_stops(INT, INT)            → TABLE
--   refresh_all_aggregates(TIMESTAMPTZ,  → void
--                          TIMESTAMPTZ)
-- ============================================================
