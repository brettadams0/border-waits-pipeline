-- The last 14 days: the input of the browser's rebuild check.
select *
from {{ ref('fct_wait_readings') }}
where source_updated_at >= (select max(fetched_at) from {{ ref('fct_wait_readings') }}) - interval 14 day
order by crossing_id, source_updated_at
