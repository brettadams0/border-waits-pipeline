-- After rollover handling, no update is a day or more after its fetch: that can
-- only come from a parse or rollover bug. CBP stamps updates with the coming
-- hour and some ports run ahead, so smaller offsets are warnings
-- (warn_source_updated_ahead).
select * from {{ ref('stg_readings') }}
where {{ this_run() }} and source_updated_at > fetched_at + interval 24 hour
