-- description: Product dimension
-- indexes: product_id
SELECT product_id, category, weight_g, volume_cm3, photos_qty, description_length
FROM {{ ref('silver_products') }}
