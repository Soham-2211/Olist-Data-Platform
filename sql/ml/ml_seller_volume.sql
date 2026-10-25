-- description: Cumulative orders received per seller by day (workload / backlog signal)
-- indexes: seller_id, day
WITH daily AS (
    SELECT os.seller_id, date(f.purchased_at) AS day, COUNT(*) AS n
    FROM {{ ref('fact_orders') }} f
    JOIN {{ ref('ml_order_seller') }} os ON os.order_id = f.order_id
    GROUP BY 1, 2
)
SELECT seller_id, day,
       SUM(n) OVER (PARTITION BY seller_id ORDER BY day ROWS UNBOUNDED PRECEDING) AS cum_orders
FROM daily
