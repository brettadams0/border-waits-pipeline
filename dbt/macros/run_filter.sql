{# Error-severity tests look at the current run only (var run_id); their warn copies look at all of history. #}
{% macro this_run(column='run_id') -%}
  {%- if var('run_id') %}{{ column }} = '{{ var("run_id") }}'{% else %}true{% endif -%}
{%- endmacro %}
