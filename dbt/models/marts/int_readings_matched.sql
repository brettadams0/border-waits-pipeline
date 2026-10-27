select r.*, c.crossing_id, c.featured
from {{ ref('stg_readings') }} r
join {{ ref('dim_crossing') }} c
    on (r.source = 'cbsa' and r.source_crossing_name = c.cbsa_csv_name)
    or (r.source = 'cbp' and r.cbp_port_number = c.cbp_port_number)
