-- description: Payments, typed; 'not_defined' type and 0 installments repaired and flagged
-- indexes: order_id
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id, payment_sequential ORDER BY _batch_id DESC) AS rn
    FROM {{ ref('bronze_order_payments') }}
)
SELECT
    order_id,
    CAST(payment_sequential AS INTEGER)                                   AS payment_sequential,
    NULLIF(lower(trim(payment_type)), 'not_defined')                      AS payment_type,
    MAX(CAST(payment_installments AS INTEGER), 1)                         AS installments,
    CAST(payment_value AS REAL)                                           AS payment_value,
    CASE WHEN CAST(payment_installments AS INTEGER) = 0
           OR lower(trim(payment_type)) = 'not_defined' THEN 1 ELSE 0 END AS flag_repaired
FROM ranked
WHERE rn = 1
