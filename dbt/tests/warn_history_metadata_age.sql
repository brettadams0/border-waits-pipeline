{{ config(severity='warn', tags=['freshness']) }}
-- CBSA's history file: warn when CKAN metadata_modified (the stored file's name) is over 120 days old.
select max(filename) as newest_file
from {{ source('raw', 'cbsa_land_history') }}
having cast(regexp_extract(max(filename), '(\d{4}-\d{2}-\d{2})T[^/]*\.csv$', 1) as date) < current_date - interval 120 day
