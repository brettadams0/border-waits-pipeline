{{ config(severity='warn') }}
-- Readings stamped more than 15 minutes after their fetch, current run only.
select source, source_crossing_name, cbp_port_number, source_updated_raw, fetched_at, source_updated_at,
       date_diff('minute', fetched_at, source_updated_at) as minutes_ahead
from {{ ref('stg_readings') }}
where {{ this_run() }} and source_updated_at > fetched_at + interval 15 minute
