-- Stored rows the marts leave out, by reason. The rows themselves stay in the
-- snapshots and in stg_readings (quality_issue); nothing is deleted or clipped.
select
    source,
    quality_issue,
    count(*) as stored_rows,
    count(distinct run_id) as runs,
    min(fetched_at) as first_seen,
    max(fetched_at) as last_seen
from {{ ref('stg_readings') }}
where quality_issue is not null
group by all
order by all
