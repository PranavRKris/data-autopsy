-- Staging: orders joined to customers. The inner join silently drops orders with no matching customer.
-- {channel_expr} is filled in by run_pipeline.py.
create or replace table staging.stg_orders as
select
    o.order_id,
    o.customer_id,
    o.ordered_at,
    o.amount,
    {channel_expr} as channel
from raw.orders o
join raw.customers c on c.customer_id = o.customer_id;
