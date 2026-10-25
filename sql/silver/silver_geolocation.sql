-- description: One coordinate per zip prefix: de-duplicated, points outside Brazil removed, city names normalised
-- indexes: zip_prefix
WITH cleaned AS (
    SELECT DISTINCT
        substr('00000' || trim(geolocation_zip_code_prefix), -5, 5)                       AS zip_prefix,
        CAST(geolocation_lat AS REAL)                                                    AS lat,
        CAST(geolocation_lng AS REAL)                                                    AS lng,
        norm_city(geolocation_city) AS city,
        upper(trim(geolocation_state))                                                   AS state
    FROM {{ ref('bronze_geolocation') }}
)
SELECT
    zip_prefix,
    AVG(lat)            AS lat,
    AVG(lng)            AS lng,
    MIN(city)           AS city,
    MIN(state)          AS state,
    COUNT(*)            AS n_points
FROM cleaned
-- Brazil's bounding box; the source has points in Europe and the Atlantic
WHERE lat BETWEEN -33.75 AND 5.27 AND lng BETWEEN -73.99 AND -34.79
GROUP BY zip_prefix
