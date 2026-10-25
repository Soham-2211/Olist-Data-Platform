-- description: Grain = order. Money reconciled between items and payments; per-order shipping address; delivery outcome and review attached
-- indexes: order_id; customer_unique_id; purchase_date
WITH items AS (
    SELECT order_id, COUNT(*) AS n_items, COUNT(DISTINCT seller_id) AS n_sellers,
           SUM(price) AS items_value, SUM(freight_value) AS freight_value
    FROM {{ ref('silver_order_items') }} GROUP BY order_id
),
pay AS (
    SELECT order_id, SUM(payment_value) AS payment_value, MAX(installments) AS installments,
           COUNT(*) AS n_payments
    FROM {{ ref('silver_payments') }} GROUP BY order_id
)
SELECT
    o.order_id,
    c.customer_unique_id,
    c.customer_id,
    c.zip_prefix                                                            AS ship_zip_prefix,
    c.state                                                                 AS ship_state,
    COALESCE(g.lat, cg.lat)                                                 AS ship_lat,
    COALESCE(g.lng, cg.lng)                                                 AS ship_lng,
    date(o.purchased_at)                                                    AS purchase_date,
    o.order_status, o.purchased_at, o.approved_at, o.carrier_at, o.delivered_at,
    o.estimated_delivery_date,
    COALESCE(i.n_items, 0)                                                  AS n_items,
    i.n_sellers, i.items_value, i.freight_value,
    p.payment_value, p.installments, p.n_payments,
    CASE WHEN i.order_id IS NOT NULL AND p.order_id IS NOT NULL
          AND abs(i.items_value + i.freight_value - p.payment_value) > 1.0 THEN 1 ELSE 0 END AS payment_mismatch,
    julianday(o.estimated_delivery_date) - julianday(date(o.purchased_at))  AS promised_days,
    julianday(o.delivered_at) - julianday(o.purchased_at)                   AS actual_days,
    CASE WHEN o.delivered_at IS NULL THEN NULL
         WHEN date(o.delivered_at) > o.estimated_delivery_date THEN 1 ELSE 0 END AS is_late,
    julianday(date(o.delivered_at)) - julianday(o.estimated_delivery_date)  AS delay_days,
    r.review_score
FROM {{ ref('silver_orders') }} o
JOIN {{ ref('silver_customers') }} c ON c.customer_id = o.customer_id
LEFT JOIN items i ON i.order_id = o.order_id
LEFT JOIN pay p   ON p.order_id = o.order_id
LEFT JOIN {{ ref('silver_reviews') }} r ON r.order_id = o.order_id
-- the address on THIS order (a customer's later address must not leak into older orders)
LEFT JOIN {{ ref('silver_geolocation') }} g ON g.zip_prefix = c.zip_prefix
LEFT JOIN {{ ref('silver_city_geolocation') }} cg ON cg.city = c.city AND cg.state = c.state
