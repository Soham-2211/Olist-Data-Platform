# Model lineage

_Generated from the `{{ ref() }}` graph in `sql/`._

```mermaid
flowchart LR
    silver_city_geolocation --> dim_customer
    silver_customers --> dim_customer
    silver_geolocation --> dim_customer
    silver_orders --> dim_customer
    silver_orders --> dim_date
    silver_products --> dim_product
    silver_city_geolocation --> dim_seller
    silver_geolocation --> dim_seller
    silver_sellers --> dim_seller
    dim_seller --> fact_order_items
    fact_orders --> fact_order_items
    silver_order_items --> fact_order_items
    silver_city_geolocation --> fact_orders
    silver_customers --> fact_orders
    silver_geolocation --> fact_orders
    silver_order_items --> fact_orders
    silver_orders --> fact_orders
    silver_payments --> fact_orders
    silver_reviews --> fact_orders
    fact_orders --> mart_monthly_kpis
    fact_orders --> ml_features
    ml_order_seller --> ml_features
    ml_seller_history --> ml_features
    ml_seller_volume --> ml_features
    ml_state_recent --> ml_features
    silver_payments --> ml_features
    ml_features --> ml_leaky_features
    dim_product --> ml_order_seller
    dim_seller --> ml_order_seller
    fact_order_items --> ml_order_seller
    silver_order_items --> ml_order_seller
    fact_orders --> ml_seller_history
    ml_order_seller --> ml_seller_history
    fact_orders --> ml_seller_volume
    ml_order_seller --> ml_seller_volume
    fact_orders --> ml_state_recent
    silver_geolocation --> silver_city_geolocation
    bronze_customers --> silver_customers
    bronze_geolocation --> silver_geolocation
    bronze_order_items --> silver_order_items
    bronze_orders --> silver_orders
    bronze_order_payments --> silver_payments
    bronze_category_translation --> silver_products
    bronze_products --> silver_products
    seed_category_translation_overrides --> silver_products
    bronze_geolocation --> silver_quarantine
    bronze_order_reviews --> silver_quarantine
    silver_orders --> silver_quarantine
    silver_payments --> silver_quarantine
    bronze_order_reviews --> silver_reviews
    bronze_sellers --> silver_sellers
    subgraph SILVER
        silver_city_geolocation
        silver_customers
        silver_geolocation
        silver_order_items
        silver_orders
        silver_payments
        silver_products
        silver_quarantine
        silver_reviews
        silver_sellers
    end
    subgraph GOLD
        dim_customer
        dim_date
        dim_product
        dim_seller
        fact_order_items
        fact_orders
        mart_monthly_kpis
    end
    subgraph ML
        ml_features
        ml_leaky_features
        ml_order_seller
        ml_seller_history
        ml_seller_volume
        ml_state_recent
    end
```
