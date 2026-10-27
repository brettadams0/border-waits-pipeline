-- Crossing x direction x lane x local hour, over all days: the chart's grain.
-- n counts non-null delays only (closed lanes are null).
select
    crossing_id,
    direction,
    lane,
    hour(timezone(iana_zone, source_updated_at)) as local_hour,
    count(delay_min) as n,
    count(distinct cast(timezone(iana_zone, source_updated_at) as date)) as days,
    median(delay_min) as median_delay_min,
    quantile_cont(delay_min, 0.9) as p90_delay_min
from "bwt"."main"."fct_wait_readings_recent"
group by all
order by all