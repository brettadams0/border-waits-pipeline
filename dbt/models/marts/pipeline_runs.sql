-- One row per stored run, with the gap since the run before it. GitHub runs
-- scheduled workflows best-effort, so the gaps are the cadence actually achieved.
select
    run_id,
    fetched_at,
    date_diff('minute', lag(fetched_at) over (order by fetched_at), fetched_at) as minutes_since_previous
from (select run_id, min(fetched_at) as fetched_at from {{ ref('stg_readings') }} group by run_id)
order by fetched_at
