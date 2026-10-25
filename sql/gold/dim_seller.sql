-- description: Sellers with coordinates (zip, else city centroid)
-- indexes: seller_id
SELECT
    s.seller_id, s.zip_prefix, s.city, s.state,
    COALESCE(g.lat, cg.lat)                                         AS lat,
    COALESCE(g.lng, cg.lng)                                         AS lng,
    CASE WHEN g.lat IS NOT NULL THEN 'zip'
         WHEN cg.lat IS NOT NULL THEN 'city' ELSE 'none' END        AS geo_source
FROM {{ ref('silver_sellers') }} s
LEFT JOIN {{ ref('silver_geolocation') }} g ON g.zip_prefix = s.zip_prefix
LEFT JOIN {{ ref('silver_city_geolocation') }} cg ON cg.city = s.city AND cg.state = s.state
