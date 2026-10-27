-- Published names with no dim_crossing row: each needs a crosswalk row.
select source, source_crossing_name, cbp_port_number, max(fetched_at) as last_seen, count(*) as readings
from {{ ref('stg_readings') }} r
where not exists (
    select 1 from {{ ref('dim_crossing') }} c
    where (r.source = 'cbsa' and r.source_crossing_name = c.cbsa_csv_name)
       or (r.source = 'cbp' and r.cbp_port_number = c.cbp_port_number))
group by all
