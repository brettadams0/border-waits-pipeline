-- One row per crossing x direction x lane x reading time, eligible rows only
-- (stg_readings.quality_issue is null).
--
-- reading_at is the source's own update time. CBP publishes closed, pending and
-- not-applicable lanes without one, so those rows use the fetch time instead
-- (time_basis = 'fetch') and each poll of such a lane is one row.
--
-- Each crossing updates on its own clock while the feed is polled about hourly,
-- so the same update is usually fetched several times. Those fetches are one row:
--   fetched_at, run_id   the first fetch that saw the update
--   last_fetched_at      the last fetch that still showed it
--   observations         how many fetches showed it
--   the values           from the last fetch. CBP has changed a value under an
--                        unchanged update time (2 of 4,124 updates by 2026-11-14);
--                        the later value is the agency's last word, and revised marks it.
with eligible as (
    select
        *,
        coalesce(source_updated_at, fetched_at) as reading_at,
        case when source_updated_at is null then 'fetch' else 'source' end as time_basis
    from {{ ref('int_readings_matched') }}
    where quality_issue is null
),

observed as (
    select
        *,
        row_number() over (
            partition by crossing_id, direction, lane, time_basis, reading_at
            order by fetched_at desc, run_id desc) as rn,
        first_value(fetched_at) over seen as first_fetched_at,
        first_value(run_id) over seen as first_run_id,
        max(fetched_at) over seen as last_fetched_at,
        count(*) over seen as observations,
        min(coalesce(status_raw, '')) over seen <> max(coalesce(status_raw, '')) over seen
            or min(coalesce(delay_min, -1)) over seen <> max(coalesce(delay_min, -1)) over seen as revised
    from eligible
    window seen as (
        partition by crossing_id, direction, lane, time_basis, reading_at
        order by fetched_at, run_id
        rows between unbounded preceding and unbounded following)
)

select * exclude (rn, first_fetched_at, first_run_id)
    replace (first_fetched_at as fetched_at, first_run_id as run_id)
from observed
where rn = 1
order by crossing_id, reading_at
