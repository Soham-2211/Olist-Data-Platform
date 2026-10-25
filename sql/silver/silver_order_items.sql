-- description: Order lines, typed
-- indexes: order_id; product_id; seller_id
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id, order_item_id ORDER BY _batch_id DESC) AS rn
    FROM {{ ref('bronze_order_items') }}
)
SELECT
    order_id,
    CAST(order_item_id AS INTEGER)          AS order_item_id,
    product_id,
    seller_id,
    datetime(shipping_limit_date)           AS shipping_limit_at,
    CAST(price AS REAL)                     AS price,
    CAST(freight_value AS REAL)             AS freight_value
FROM ranked
WHERE rn = 1
