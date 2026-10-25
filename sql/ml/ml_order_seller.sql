-- description: Primary seller of each order (largest share of item value), plus order-level shipment physics
-- indexes: order_id; seller_id
WITH by_seller AS (
    SELECT i.order_id, i.seller_id, SUM(i.price) AS value,
           MAX(i.distance_km) AS distance_km, MIN(i.same_state) AS same_state
    FROM {{ ref('fact_order_items') }} i
    GROUP BY i.order_id, i.seller_id
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY value DESC, seller_id) AS rn
    FROM by_seller
),
physics AS (
    SELECT i.order_id,
           SUM(p.weight_g) / 1000.0     AS total_weight_kg,
           SUM(p.volume_cm3) / 1000.0   AS total_volume_l,
           MAX(p.weight_g) / 1000.0     AS max_item_weight_kg,
           COUNT(DISTINCT i.product_id) AS n_products,
           MIN(p.category)              AS any_category,
           MAX(julianday(i2.shipping_limit_at)) AS shipping_limit_jd
    FROM {{ ref('fact_order_items') }} i
    JOIN {{ ref('silver_order_items') }} i2 ON i2.order_id = i.order_id AND i2.order_item_id = i.order_item_id
    LEFT JOIN {{ ref('dim_product') }} p ON p.product_id = i.product_id
    GROUP BY i.order_id
),
top_category AS (
    SELECT order_id, category FROM (
        SELECT i.order_id, p.category,
               ROW_NUMBER() OVER (PARTITION BY i.order_id ORDER BY i.price DESC, p.category) AS rn
        FROM {{ ref('fact_order_items') }} i
        LEFT JOIN {{ ref('dim_product') }} p ON p.product_id = i.product_id)
    WHERE rn = 1
)
SELECT r.order_id, r.seller_id, s.state AS seller_state, r.distance_km, r.same_state,
       ph.total_weight_kg, ph.total_volume_l, ph.max_item_weight_kg, ph.n_products, ph.shipping_limit_jd,
       COALESCE(tc.category, 'unknown') AS category
FROM ranked r
JOIN physics ph ON ph.order_id = r.order_id
LEFT JOIN top_category tc ON tc.order_id = r.order_id
LEFT JOIN {{ ref('dim_seller') }} s ON s.seller_id = r.seller_id
WHERE r.rn = 1
