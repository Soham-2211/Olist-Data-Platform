-- description: One row per order with everything known AT PURCHASE TIME, plus the label once delivered. Point-in-time correct
-- indexes: order_id; purchased_at
WITH base AS (
    SELECT
        f.order_id, f.purchased_at, date(f.purchased_at) AS purchase_date, f.order_status,
        f.estimated_delivery_date, f.delivered_at, f.is_late, f.delay_days,
        f.customer_unique_id, f.ship_state AS customer_state,
        os.seller_id, os.seller_state, os.distance_km, os.same_state, os.category,
        os.total_weight_kg, os.total_volume_l, os.max_item_weight_kg, os.n_products,
        os.shipping_limit_jd - julianday(f.purchased_at)               AS seller_handling_days_allowed,
        f.promised_days, f.n_items, f.n_sellers, f.items_value, f.freight_value,
        f.freight_value / NULLIF(f.items_value, 0)                     AS freight_ratio,
        f.installments, f.n_payments,
        ROW_NUMBER() OVER (PARTITION BY f.customer_unique_id ORDER BY f.purchased_at) - 1 AS customer_prior_orders
    FROM {{ ref('fact_orders') }} f
    JOIN {{ ref('ml_order_seller') }} os ON os.order_id = f.order_id
),
main_payment AS (
    SELECT order_id, payment_type FROM (
        SELECT order_id, payment_type,
               ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY payment_value DESC) AS rn
        FROM {{ ref('silver_payments') }})
    WHERE rn = 1
)
SELECT
    b.*,
    COALESCE(mp.payment_type, 'unknown')                                AS payment_type,
    CAST(strftime('%w', b.purchased_at) AS INTEGER)                     AS purchase_dow,
    CAST(strftime('%H', b.purchased_at) AS INTEGER)                     AS purchase_hour,
    CAST(strftime('%m', b.purchased_at) AS INTEGER)                     AS purchase_month,

    -- Seller track record: only deliveries completed before the purchase DAY
    COALESCE(sh.cum_deliveries, 0)                                      AS seller_prior_deliveries,
    (COALESCE(sh.cum_late, 0) + 1.0) / (COALESCE(sh.cum_deliveries, 0) + 15.0) AS seller_prior_late_rate_smoothed,
    sh.cum_delay_days / NULLIF(sh.cum_deliveries, 0)                    AS seller_prior_avg_delay_days,

    -- Seller workload: orders received in the 30 days before the purchase day
    COALESCE(sv_now.cum_orders, 0) - COALESCE(sv_then.cum_orders, 0)    AS seller_orders_prev_30d,

    -- Regional disruption: late rate of deliveries to this state in the previous 30 days
    sr.n_30d                                                            AS state_deliveries_prev_30d,
    (sr.late_30d + 0.5) / (sr.n_30d + 7.0)                              AS state_late_rate_prev_30d
FROM base b
LEFT JOIN main_payment mp ON mp.order_id = b.order_id
LEFT JOIN {{ ref('ml_seller_history') }} sh
       ON sh.seller_id = b.seller_id
      AND sh.day = (SELECT MAX(day) FROM {{ ref('ml_seller_history') }} x
                    WHERE x.seller_id = b.seller_id AND x.day < b.purchase_date)
LEFT JOIN {{ ref('ml_seller_volume') }} sv_now
       ON sv_now.seller_id = b.seller_id
      AND sv_now.day = (SELECT MAX(day) FROM {{ ref('ml_seller_volume') }} x
                        WHERE x.seller_id = b.seller_id AND x.day < b.purchase_date)
LEFT JOIN {{ ref('ml_seller_volume') }} sv_then
       ON sv_then.seller_id = b.seller_id
      AND sv_then.day = (SELECT MAX(day) FROM {{ ref('ml_seller_volume') }} x
                         WHERE x.seller_id = b.seller_id AND x.day < date(b.purchase_date, '-30 day'))
LEFT JOIN {{ ref('ml_state_recent') }} sr ON sr.state = b.customer_state AND sr.day = b.purchase_date
