-- Casts the stored rows, keeps the standard lane groups, and resolves each
-- source's published local time to an instant in that side's zone.
with raw as (
    select * from {{ source('raw', 'readings') }}
    -- excluded_snapshots.path is the path on the data branch (snapshots/...); filename carries the datastore prefix
    where not exists (
        select 1 from {{ ref('excluded_snapshots') }} x
        where filename = x.path or ends_with(filename, '/' || x.path))
      and lane_type = 'standard'
),

zoned as (
    select
        r.*,
        case r.source when 'cbsa' then c.cbsa_iana_zone else c.cbp_iana_zone end as iana_zone,
        case r.source
            when 'cbsa' then strptime(substr(r.source_updated_raw, 1, 16), '%Y-%m-%d %H:%M')
            else strptime(
                regexp_replace(
                    replace(replace(r.source_updated_raw, ' At Noon ', ' At 12:00 pm '), ' At Midnight ', ' At 12:00 am '),
                    ' [A-Z]{3}$', ''),
                '%m/%d/%Y At %I:%M %p')
        end as local_raw
    from raw r
    left join {{ ref('dim_crossing') }} c
        on (r.source = 'cbsa' and r.source_crossing_name = c.cbsa_csv_name)
        or (r.source = 'cbp' and r.cbp_port_number = c.cbp_port_number)
),

offsets as (
    select
        *,
        {{ tz_offset('iana_zone', "timezone('UTC', local_raw - interval 12 hour)") }} as o1,
        {{ tz_offset('iana_zone', "timezone('UTC', local_raw + interval 12 hour)") }} as o2
    from zoned
),

-- CBP gives a time on the port's date: a late-evening time more than 15 minutes
-- after an early-morning fetch belongs to the day before (midnight rollover).
-- CBP also stamps updates with the coming hour ('At 4:00 pm' fetched at 15:53),
-- so other times a little ahead of the fetch are kept as published.
rolled as (
    select
        * exclude (local_raw),
        case
            when source = 'cbp' and timezone('UTC', local_raw - greatest(o1, o2)) > fetched_at + interval 15 minute
                 and hour(local_raw) >= 20 and hour(timezone(iana_zone, fetched_at)) < 4
                then local_raw - interval 1 day
            else local_raw
        end as local_updated
    from offsets
),

candidates as (
    select
        *,
        timezone('UTC', local_updated - o1) as c1,
        timezone('UTC', local_updated - o2) as c2
    from rolled
),

checked as (
    select
        *,
        {{ tz_offset('iana_zone', 'c1') }} = o1 as c1_valid,
        {{ tz_offset('iana_zone', 'c2') }} = o2 as c2_valid,
        o1 <> o2 as offsets_differ
    from candidates
),

resolved as (
    select
        *,
        case
            when local_updated is null or iana_zone is null then null
            when c1_valid <> c2_valid or (c1_valid and not offsets_differ) then 'zone'
            when c1_valid and c2_valid
                 and source_tz_abbrev like '_DT' and (case when o1 > o2 then c1 else c2 end) <= fetched_at then 'abbrev'
            when c1_valid and c2_valid
                 and source_tz_abbrev like '_ST' and (case when o1 > o2 then c2 else c1 end) <= fetched_at then 'abbrev'
            else 'rule'
        end as tz_resolved_by
    from checked
),

final as (
select
    run_id,
    schema_version,
    fetched_at,
    source,
    source_crossing_name,
    source_location,
    cbp_port_number,
    port_status,
    direction,
    lane,
    lane_type,
    status_raw,
    delay_min,
    is_open,
    lanes_open,
    source_updated_raw,
    source_tz_abbrev,
    iana_zone,
    local_updated,
    case tz_resolved_by
        when 'zone' then case when c1_valid then c1 else c2 end
        when 'abbrev' then case when (source_tz_abbrev like '_DT') = (o1 > o2) then c1 else c2 end
        when 'rule' then case
            when greatest(c1, c2) <= fetched_at then greatest(c1, c2)
            else least(c1, c2)
        end
    end as source_updated_at,
    tz_resolved_by,
    filename
from resolved
)

-- The abbreviation says daylight or standard time; compare it with the zone's
-- own offset at that instant (Port Huron's 'EST' in October fails this).
select
    *,
    case when source_updated_at is null or source_tz_abbrev is null then null
    else (source_tz_abbrev like '_DT') = (
        {{ tz_offset('iana_zone', 'source_updated_at') }} > least(
            {{ tz_offset('iana_zone', "timezone('UTC', make_timestamp(year(source_updated_at), 1, 15, 12, 0, 0))") }},
            {{ tz_offset('iana_zone', "timezone('UTC', make_timestamp(year(source_updated_at), 7, 15, 12, 0, 0))") }}))
    end as tz_abbrev_matches_zone
from final
