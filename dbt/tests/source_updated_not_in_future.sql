-- After rollover handling, no update is after its fetch.
select * from {{ ref('stg_readings') }}
where {{ this_run() }} and source_updated_at > fetched_at
