{# At least `minimum` distinct values of column_name for each source in the run. #}
{% test min_distinct_per_run(model, column_name, source_value, minimum) %}
select '{{ source_value }}' as source, count(distinct {{ column_name }}) as n
from {{ model }}
where source = '{{ source_value }}' and {{ this_run() }}
having count(distinct {{ column_name }}) < {{ minimum }}
{% endtest %}
