-- Mart: revenue summed by day and sales channel. This is the table finance reads.
create or replace table mart.daily_revenue as
select
    cast(ordered_at as date) as day,
    channel,
    sum(amount) as revenue
from staging.stg_orders
group by 1, 2;
