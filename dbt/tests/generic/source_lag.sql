{# How old each source's updates were when this run fetched them: the median over the source's
   timestamped rows, so one fresh crossing can't make a stale feed look healthy. An update stamped
   after the fetch (CBP's coming-hour stamps) counts as 0 minutes old, not as negative lag. A run
   in which the source has no timestamped row at all also fails. #}
{% test source_lag(model, source_value, max_minutes) %}
select '{{ source_value }}' as source, count(*) as timestamped_rows,
       median(greatest(date_diff('minute', source_updated_at, fetched_at), 0)) as median_age_minutes
from {{ model }}
where source = '{{ source_value }}' and {{ this_run() }} and source_updated_at is not null
having count(*) = 0 or median(greatest(date_diff('minute', source_updated_at, fetched_at), 0)) > {{ max_minutes }}
{% endtest %}
