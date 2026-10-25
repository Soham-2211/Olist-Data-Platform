-- description: DELIBERATELY LEAKY features, used only to measure how much a naive feature pipeline inflates offline metrics. Never used for training the real model
-- indexes: order_id
WITH seller_all_time AS (
    -- seller late rate over ALL deliveries, including ones after this order and the order itself
    SELECT seller_id, AVG(is_late) AS late_rate, COUNT(*) AS n
    FROM {{ ref('ml_features') }}
    WHERE is_late IS NOT NULL
    GROUP BY seller_id
),
state_month AS (
    -- late rate of the whole purchase month in that state, including future days
    SELECT customer_state, strftime('%Y-%m', purchased_at) AS ym, AVG(is_late) AS late_rate
    FROM {{ ref('ml_features') }}
    WHERE is_late IS NOT NULL
    GROUP BY 1, 2
)
SELECT f.order_id,
       s.late_rate                     AS leaky_seller_late_rate,
       s.n                             AS leaky_seller_deliveries,
       sm.late_rate                    AS leaky_state_month_late_rate
FROM {{ ref('ml_features') }} f
LEFT JOIN seller_all_time s ON s.seller_id = f.seller_id
LEFT JOIN state_month sm ON sm.customer_state = f.customer_state
                        AND sm.ym = strftime('%Y-%m', f.purchased_at)
