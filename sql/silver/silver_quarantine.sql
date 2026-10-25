-- description: Every record excluded or repaired by the silver layer, with the reason, for auditing
SELECT 'bronze_geolocation' AS source_table,
       geolocation_zip_code_prefix AS record_key,
       'coordinates outside Brazil' AS reason,
       _batch_id AS batch_id
FROM {{ ref('bronze_geolocation') }}
WHERE NOT (CAST(geolocation_lat AS REAL) BETWEEN -33.75 AND 5.27
       AND CAST(geolocation_lng AS REAL) BETWEEN -73.99 AND -34.79)
UNION ALL
SELECT 'bronze_order_reviews', order_id || ':' || review_id,
       'older duplicate review for the same order', NULL
FROM (SELECT order_id, review_id,
             ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY review_answer_timestamp DESC, review_id) AS rn
      FROM {{ ref('bronze_order_reviews') }})
WHERE rn > 1
UNION ALL
SELECT 'silver_orders', order_id, 'carrier pickup before purchase (timestamp nulled)', latest_batch
FROM {{ ref('silver_orders') }} WHERE flag_carrier_before_purchase = 1
UNION ALL
SELECT 'silver_orders', order_id, 'status delivered but no delivery date', latest_batch
FROM {{ ref('silver_orders') }} WHERE flag_delivered_without_date = 1
UNION ALL
SELECT 'silver_payments', order_id || ':' || payment_sequential, 'payment type/installments repaired', NULL
FROM {{ ref('silver_payments') }} WHERE flag_repaired = 1
