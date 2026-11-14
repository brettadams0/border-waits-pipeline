-- The last recent_days days (dbt_project.yml): what the by-hour chart is built
-- from, and the input of the browser's rebuild check.
select *
from {{ ref('fct_wait_readings') }}
where reading_at >= (select max(fetched_at) from {{ ref('fct_wait_readings') }}) - interval {{ var('recent_days') }} day
order by crossing_id, reading_at
