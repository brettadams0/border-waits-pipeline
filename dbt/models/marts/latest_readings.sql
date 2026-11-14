-- What each series said in the newest poll that included it: one whole stored
-- row per crossing x direction x lane, never a mix of columns from different
-- readings. A newer 'Update Pending' or 'Lanes Closed' row therefore replaces an
-- older number instead of inheriting it.
--
-- Newest means the newest fetch (observed_at), not the newest source time: CBP
-- gives closed and pending lanes no update time at all, and stamps others with
-- the coming hour. Two rows from one fetch can only come from a re-run; the
-- later run_id wins, then the later source time.
select
    crossing_id,
    direction,
    lane,
    source,
    status_raw,
    delay_min,
    is_open,
    lanes_open,
    source_updated_at,
    fetched_at as observed_at,
    run_id
from {{ ref('int_readings_matched') }}
where quality_issue is null
qualify row_number() over (
    partition by crossing_id, direction, lane
    order by fetched_at desc, run_id desc, source_updated_at desc nulls last) = 1
order by crossing_id, direction, lane
