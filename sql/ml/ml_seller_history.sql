-- description: Cumulative per-seller delivery history by day (for point-in-time lookups)
-- indexes: seller_id, day
WITH daily AS (
    SELECT os.seller_id,
           date(f.delivered_at)        AS day,
           COUNT(*)                     AS n,
           SUM(f.is_late)               AS late,
           SUM(f.delay_days)            AS delay
    FROM {{ ref('fact_orders') }} f
    JOIN {{ ref('ml_order_seller') }} os ON os.order_id = f.order_id
    WHERE f.is_late IS NOT NULL
    GROUP BY 1, 2
)
SELECT seller_id, day,
       SUM(n)     OVER w AS cum_deliveries,
       SUM(late)  OVER w AS cum_late,
       SUM(delay) OVER w AS cum_delay_days
FROM daily
WINDOW w AS (PARTITION BY seller_id ORDER BY day ROWS UNBOUNDED PRECEDING)
