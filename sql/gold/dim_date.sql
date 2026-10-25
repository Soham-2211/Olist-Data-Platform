-- description: Calendar dimension covering every purchase date
-- indexes: date_key
WITH RECURSIVE days(d) AS (
    SELECT date(MIN(purchased_at)) FROM {{ ref('silver_orders') }}
    UNION ALL
    SELECT date(d, '+1 day') FROM days
    WHERE d < (SELECT date(MAX(COALESCE(delivered_at, purchased_at)), '+60 day') FROM {{ ref('silver_orders') }})
)
SELECT
    d                                       AS date_key,
    CAST(strftime('%Y', d) AS INTEGER)      AS year,
    CAST(strftime('%m', d) AS INTEGER)      AS month,
    strftime('%Y-%m', d)                    AS year_month,
    CAST(strftime('%w', d) AS INTEGER)      AS day_of_week,
    CASE WHEN strftime('%w', d) IN ('0', '6') THEN 1 ELSE 0 END AS is_weekend
FROM days
