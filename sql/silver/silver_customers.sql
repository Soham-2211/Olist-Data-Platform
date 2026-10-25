-- description: Customers typed and normalised; customer_id is per order, customer_unique_id is the person
-- indexes: customer_id; customer_unique_id
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY _batch_id DESC, CAST(_row_num AS INTEGER) DESC) AS rn
    FROM {{ ref('bronze_customers') }}
)
SELECT
    customer_id,
    customer_unique_id,
    substr('00000' || trim(customer_zip_code_prefix), -5, 5)                    AS zip_prefix,
    norm_city(customer_city)                    AS city,
    upper(trim(customer_state))                                                 AS state,
    _batch_id                                                                   AS loaded_batch
FROM ranked
WHERE rn = 1
