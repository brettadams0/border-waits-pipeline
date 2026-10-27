-- The same with local weekday added, for the SQL console only: weekday medians
-- can't be combined into an all-days median, so the chart never uses this.
select
    crossing_id,
    direction,
    lane,
    dayofweek(timezone(iana_zone, source_updated_at)) as local_weekday,
    hour(timezone(iana_zone, source_updated_at)) as local_hour,
    count(delay_min) as n,
    count(distinct cast(timezone(iana_zone, source_updated_at) as date)) as days,
    median(delay_min) as median_delay_min,
    quantile_cont(delay_min, 0.9) as p90_delay_min
from "bwt"."main"."fct_wait_readings"
group by all
order by all