select port_of_entry, fiscal_year, month_name, count(*) as n
from {{ ref('stg_cbsa_land_monthly') }}
group by all
having count(*) > 1
