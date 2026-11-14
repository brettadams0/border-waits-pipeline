{{ config(severity='warn') }}
-- A featured crossing that a feed normally lists but this run did not include.
-- 25 crossings per source can pass while the three the page is about are absent.
select c.crossing_id, s.source
from {{ ref('dim_crossing') }} c
cross join (values ('cbsa'), ('cbp')) as s(source)
where c.featured
  and ((s.source = 'cbsa' and c.cbsa_csv_name is not null) or (s.source = 'cbp' and c.cbp_port_number is not null))
  and not exists (
      select 1 from {{ ref('int_readings_matched') }} r
      where r.crossing_id = c.crossing_id and r.source = s.source and {{ this_run('r.run_id') }})
