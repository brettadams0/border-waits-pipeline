{% test is_empty(model) %}
select * from {{ model }}
{% endtest %}
