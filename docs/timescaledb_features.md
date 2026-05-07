# TimescaleDB Features - Delhi Transport Analytics
---
## Continuous Aggregates

### -  `route_performance_hourly`
Pre-computes hourly delay stats per route.\
Refresh policy: every 1 hour, 3-day lookback.\
Raw query time:      **203.310 ms**\
Aggregate query time: **3.330 ms**\
Speedup: **61 x faster**

### -  `stop_performance_hourly`
Pre-computes hourly delay stats per stop.\
Refresh policy: every 1 hour, 3-day lookback.

### -  `system_performance_hourly`
Pre-computes system-wide hourly delay summary.\
Refresh policy: every 1 hour, 3-day lookback.

---
---
## Compression

### `bus_arrivals` Compression Settings
compress_segmentby: `route_id`\
compress_orderby:   `scheduled_time DESC`

Rationale: `route_id` chosen as segmentby because most analytical
queries filter or group by route - this keeps compressed data
queryable at speed without full decompression.

---
### Storage Savings
Total size before: **125 MB**
Total size after:  **14 MB**
Average savings per chunk: **88.8 %** 

---
### Compression Policy
Chunks older than **7 days** compressed automatically.

---
---
## Key Lesson
Continuous aggregates and compression work together -
aggregates serve fast pre-computed results while compression
reduces storage cost of the raw hypertable. Neither interferes
with the other.