-- description: Grain = order line. Adds seller-to-customer distance
-- indexes: order_id; seller_id; product_id
SELECT
    i.order_id, i.order_item_id, i.product_id, i.seller_id,
    o.customer_unique_id,
    o.purchase_date,
    i.price, i.freight_value,
    haversine_km(s.lat, s.lng, o.ship_lat, o.ship_lng)              AS distance_km,
    CASE WHEN s.state = o.ship_state THEN 1 ELSE 0 END              AS same_state
FROM {{ ref('silver_order_items') }} i
JOIN {{ ref('fact_orders') }} o             ON o.order_id = i.order_id
LEFT JOIN {{ ref('dim_seller') }} s         ON s.seller_id = i.seller_id
