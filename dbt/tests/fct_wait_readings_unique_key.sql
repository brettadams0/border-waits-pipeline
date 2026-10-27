select crossing_id, direction, lane, source_updated_at, count(*) as n
from {{ ref('fct_wait_readings') }}
where {{ this_run() }}
group by all
having count(*) > 1
