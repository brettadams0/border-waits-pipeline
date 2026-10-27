-- The newest stored CBSA history file, typed.
select
    trim("Port of Entry") as port_of_entry,
    trim("Month") as month_name,
    trim("Fiscal Year") as fiscal_year,
    cast(replace(trim("Percentage Met Service Standard"), '%', '') as double) as pct_met
from {{ source('raw', 'cbsa_land_history') }}
where filename = (select max(filename) from {{ source('raw', 'cbsa_land_history') }})
