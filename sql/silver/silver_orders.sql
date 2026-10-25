-- description: Latest known version of every order (orders are re-sent each time their status changes); impossible timestamps nulled and flagged
-- indexes: order_id; customer_id; purchased_at
WITH ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY _batch_id DESC, CAST(_row_num AS INTEGER) DESC) AS rn,
        COUNT(*)     OVER (PARTITION BY order_id)                                                         AS n_versions,
        MIN(_batch_id) OVER (PARTITION BY order_id)                                                       AS first_batch
    FROM {{ ref('bronze_orders') }}
),
typed AS (
    SELECT
        order_id, customer_id, lower(trim(order_status)) AS order_status,
        datetime(order_purchase_timestamp)                 AS purchased_at,
        datetime(NULLIF(order_approved_at, ''))            AS approved_at,
        datetime(NULLIF(order_delivered_carrier_date, '')) AS raw_carrier_at,
        datetime(NULLIF(order_delivered_customer_date,'')) AS delivered_at,
        date(order_estimated_delivery_date)                AS estimated_delivery_date,
        n_versions, first_batch, _batch_id AS latest_batch
    FROM ranked WHERE rn = 1
)
SELECT
    order_id, customer_id, order_status, purchased_at, approved_at,
    CASE WHEN raw_carrier_at < purchased_at THEN NULL ELSE raw_carrier_at END AS carrier_at,
    delivered_at, estimated_delivery_date,
    CASE WHEN raw_carrier_at < purchased_at THEN 1 ELSE 0 END                AS flag_carrier_before_purchase,
    CASE WHEN order_status = 'delivered' AND delivered_at IS NULL THEN 1 ELSE 0 END AS flag_delivered_without_date,
    n_versions, first_batch, latest_batch
FROM typed
