-- description: One row per real person (customer_unique_id), located by zip prefix with a city-level fallback
-- indexes: customer_unique_id
WITH latest AS (
    SELECT c.*, o.purchased_at,
           ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id ORDER BY o.purchased_at DESC) AS rn,
           COUNT(*)     OVER (PARTITION BY c.customer_unique_id)                              AS n_orders,
           MIN(o.purchased_at) OVER (PARTITION BY c.customer_unique_id)                       AS first_order_at
    FROM {{ ref('silver_customers') }} c
    JOIN {{ ref('silver_orders') }} o USING (customer_id)
)
SELECT
    l.customer_unique_id,
    l.zip_prefix, l.city, l.state,
    COALESCE(g.lat, cg.lat)                                         AS lat,
    COALESCE(g.lng, cg.lng)                                         AS lng,
    CASE WHEN g.lat IS NOT NULL THEN 'zip'
         WHEN cg.lat IS NOT NULL THEN 'city' ELSE 'none' END        AS geo_source,
    l.n_orders,
    l.first_order_at
FROM latest l
LEFT JOIN {{ ref('silver_geolocation') }} g ON g.zip_prefix = l.zip_prefix
LEFT JOIN {{ ref('silver_city_geolocation') }} cg ON cg.city = l.city AND cg.state = l.state
WHERE l.rn = 1
