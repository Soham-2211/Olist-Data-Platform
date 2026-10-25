-- description: One review per order (latest answer wins); a review_id can legitimately cover several orders
-- indexes: order_id
WITH dedup AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY review_id, order_id ORDER BY _batch_id DESC) AS rn
    FROM {{ ref('bronze_order_reviews') }}
),
per_order AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY review_answer_timestamp DESC, review_id) AS rn_order
    FROM dedup WHERE rn = 1
)
SELECT
    order_id,
    review_id,
    CAST(review_score AS INTEGER)                                       AS review_score,
    CASE WHEN trim(review_comment_message) <> '' THEN 1 ELSE 0 END      AS has_comment,
    datetime(review_creation_date)                                      AS created_at,
    datetime(review_answer_timestamp)                                   AS answered_at
FROM per_order
WHERE rn_order = 1
