{{ config(severity='warn') }}
-- Every status value seen in the fixtures; anything else needs a look.
select source, status_raw, count(*) as n
from {{ ref('stg_readings') }}
where not (
    (source = 'cbsa' and (status_raw in ('No Delay', 'Closed', 'Not Applicable') or regexp_matches(status_raw, '^\d+ minutes?$')))
    or (source = 'cbp' and status_raw in ('delay', 'no delay', 'Lanes Closed', 'N/A', 'Update Pending')))
group by all
