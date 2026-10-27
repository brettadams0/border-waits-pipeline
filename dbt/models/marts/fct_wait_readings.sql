-- One row per crossing x direction x lane x source update. Each crossing
-- updates on its own clock while the feed is polled hourly, so repeated
-- fetches of the same update keep the earliest.
select * exclude (rn)
from (
    select *, row_number() over (
        partition by crossing_id, direction, lane, source_updated_at
        order by fetched_at, run_id) as rn
    from {{ ref('int_readings_matched') }}
    where source_updated_at is not null
)
where rn = 1
order by crossing_id, source_updated_at
