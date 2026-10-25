-- description: Sellers typed and normalised
-- indexes: seller_id
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY seller_id ORDER BY _batch_id DESC, CAST(_row_num AS INTEGER) DESC) AS rn
    FROM {{ ref('bronze_sellers') }}
)
SELECT
    seller_id,
    substr('00000' || trim(seller_zip_code_prefix), -5, 5)                      AS zip_prefix,
    norm_city(seller_city)                      AS city,
    upper(trim(seller_state))                                                   AS state,
    _batch_id                                                                   AS loaded_batch
FROM ranked
WHERE rn = 1
