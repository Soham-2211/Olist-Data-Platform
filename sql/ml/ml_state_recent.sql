-- description: For every (customer state, day): late rate of deliveries completed in the 30 days BEFORE that day. Captures regional carrier disruptions
-- indexes: state, day
WITH RECURSIVE days(day) AS (
    SELECT (SELECT date(MIN(purchased_at)) FROM {{ ref('fact_orders') }})
    UNION ALL
    SELECT date(day, '+1 day') FROM days
    WHERE day < (SELECT date(MAX(purchased_at), '+1 day') FROM {{ ref('fact_orders') }})
),
states AS (SELECT DISTINCT ship_state AS state FROM {{ ref('fact_orders') }} WHERE ship_state IS NOT NULL),
daily AS (
    SELECT f.ship_state AS state, date(f.delivered_at) AS day, COUNT(*) AS n, SUM(f.is_late) AS late
    FROM {{ ref('fact_orders') }} f
    WHERE f.is_late IS NOT NULL
    GROUP BY 1, 2
),
grid AS (
    SELECT s.state, d.day, COALESCE(x.n, 0) AS n, COALESCE(x.late, 0) AS late
    FROM states s CROSS JOIN days d
    LEFT JOIN daily x ON x.state = s.state AND x.day = d.day
),
rolled AS (
    SELECT state, day,
           -- window = the 30 days strictly before `day`
           SUM(n)    OVER (PARTITION BY state ORDER BY day ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS n_30d,
           SUM(late) OVER (PARTITION BY state ORDER BY day ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) AS late_30d
    FROM grid
)
SELECT state, day, COALESCE(n_30d, 0) AS n_30d, COALESCE(late_30d, 0) AS late_30d
FROM rolled
