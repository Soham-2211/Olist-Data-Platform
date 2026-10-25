-- description: Products with English categories (incl. seed overrides for untranslated ones), typo'd columns renamed, impossible weights nulled
-- indexes: product_id
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY _batch_id DESC, CAST(_row_num AS INTEGER) DESC) AS rn
    FROM {{ ref('bronze_products') }}
),
translation AS (
    SELECT trim(product_category_name) AS pt, trim(product_category_name_english) AS en
    FROM {{ ref('bronze_category_translation') }}
    UNION
    SELECT product_category_name, product_category_name_english FROM {{ ref('seed_category_translation_overrides') }}
)
SELECT
    p.product_id,
    NULLIF(trim(p.product_category_name), '')                                   AS category_pt,
    COALESCE(t.en, CASE WHEN NULLIF(trim(p.product_category_name), '') IS NULL THEN 'unknown' END,
             'untranslated')                                                    AS category,
    CAST(NULLIF(p.product_name_lenght, '') AS INTEGER)                          AS name_length,
    CAST(NULLIF(p.product_description_lenght, '') AS INTEGER)                   AS description_length,
    CAST(NULLIF(p.product_photos_qty, '') AS INTEGER)                           AS photos_qty,
    NULLIF(CAST(NULLIF(p.product_weight_g, '') AS REAL), 0)                     AS weight_g,
    CAST(NULLIF(p.product_length_cm, '') AS REAL)
      * CAST(NULLIF(p.product_height_cm, '') AS REAL)
      * CAST(NULLIF(p.product_width_cm, '') AS REAL)                            AS volume_cm3,
    p._batch_id                                                                 AS loaded_batch
FROM ranked p
LEFT JOIN translation t ON t.pt = trim(p.product_category_name)
WHERE p.rn = 1
