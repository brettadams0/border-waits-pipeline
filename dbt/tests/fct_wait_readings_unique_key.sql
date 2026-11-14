select crossing_id, direction, lane, time_basis, reading_at, count(*) as n
from {{ ref('fct_wait_readings') }}
group by all
having count(*) > 1
