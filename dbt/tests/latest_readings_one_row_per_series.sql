select crossing_id, direction, lane, count(*) as n
from {{ ref('latest_readings') }}
group by all
having count(*) > 1
