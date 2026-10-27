{% test source_lag(model, source_value, max_minutes) %}
select '{{ source_value }}' as source, max(fetched_at) as fetched_at, max(source_updated_at) as newest_update,
       date_diff('minute', max(source_updated_at), max(fetched_at)) as lag_minutes
from {{ model }}
where source = '{{ source_value }}' and {{ this_run() }}
having date_diff('minute', max(source_updated_at), max(fetched_at)) > {{ max_minutes }}
{% endtest %}
