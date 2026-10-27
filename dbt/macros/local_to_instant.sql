{#
  Resolves a naive local timestamp in an IANA zone to an instant (spec: stg_readings).
  o1 and o2 are the zone's UTC offsets 12 h either side; a candidate instant
  local - o is valid when the zone's offset at that instant is o.
    one valid candidate               -> it, 'zone'
    two (the fall-back hour)          -> the one the abbreviation names, if exactly one
                                         is not after fetched_at, 'abbrev'
    otherwise (incl. the spring gap)  -> the candidate not after fetched_at closest to it, 'rule'
#}
{% macro tz_offset(zone, instant) -%}
  (timezone({{ zone }}, {{ instant }}) - timezone('UTC', {{ instant }}))
{%- endmacro %}
