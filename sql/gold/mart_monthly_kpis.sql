-- description: Business KPIs per purchase month (what a BI dashboard would read)
SELECT
    strftime('%Y-%m', purchased_at)                                       AS year_month,
    COUNT(*)                                                              AS orders,
    COUNT(DISTINCT customer_unique_id)                                    AS customers,
    ROUND(SUM(CASE WHEN order_status NOT IN ('canceled', 'unavailable') THEN items_value END), 2) AS gmv,
    ROUND(AVG(CASE WHEN order_status NOT IN ('canceled', 'unavailable') THEN items_value END), 2) AS avg_order_value,
    ROUND(AVG(is_late), 4)                                                AS late_rate,
    ROUND(AVG(actual_days), 2)                                            AS avg_delivery_days,
    ROUND(AVG(review_score), 3)                                           AS avg_review,
    ROUND(AVG(CASE WHEN is_late = 1 THEN review_score END), 3)            AS avg_review_late,
    ROUND(AVG(CASE WHEN is_late = 0 THEN review_score END), 3)            AS avg_review_on_time
FROM {{ ref('fact_orders') }}
GROUP BY 1
ORDER BY 1
