-- description: City-level centroid, used as a fallback when a zip prefix is missing from the geolocation table
-- indexes: city, state
SELECT city, state, AVG(lat) AS lat, AVG(lng) AS lng, COUNT(*) AS n_zips
FROM {{ ref('silver_geolocation') }}
GROUP BY city, state
