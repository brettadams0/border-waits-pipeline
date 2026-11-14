{{ config(severity='warn') }}
-- CBP leaves the update time off closed, pending and n/a lanes; that is expected. An
-- estimate with no update time is not: it is kept (timed by its fetch), and this says so.
select source, source_crossing_name, cbp_port_number, lane, status_raw, delay_min
from {{ ref('stg_readings') }}
where {{ this_run() }} and delay_min is not null and source_updated_raw is null
