# Data quality report

_Generated from `meta_dq_results`, `silver_quarantine` and `meta_batches`._

## Tests across all batches

| model | test | severity | batches_failed | batches_run | max_failing_rows |
|---|---|---|---|---|---|
| dim_customer | customer_geocoded | warn | 20 | 22 | 59 |
| dim_customer | unique(customer_unique_id) | error | 0 | 22 | 0 |
| dim_seller | seller_geocoded | warn | 0 | 22 | 0 |
| dim_seller | unique(seller_id) | error | 0 | 22 | 0 |
| fact_orders | delivered_orders_have_items | error | 0 | 22 | 0 |
| fact_orders | items_plus_freight_equal_payments | warn | 22 | 22 | 249 |
| fact_orders | relationships(customer_unique_id -> dim_customer.customer_unique_id) | error | 0 | 22 | 0 |
| fact_orders | relationships(purchase_date -> dim_date.date_key) | error | 0 | 22 | 0 |
| fact_orders | unique(order_id) | error | 0 | 22 | 0 |
| ml_features | label_only_when_delivered | error | 0 | 22 | 0 |
| ml_features | not_null(seller_id, promised_days, state_late_rate_prev_30d) | error | 0 | 22 | 0 |
| ml_features | range(seller_prior_late_rate_smoothed) | error | 0 | 22 | 0 |
| ml_features | unique(order_id) | error | 0 | 22 | 0 |
| silver_customers | unique(customer_id) | error | 0 | 22 | 0 |
| silver_customers | zip_prefix_has_5_digits | error | 0 | 22 | 0 |
| silver_geolocation | range(lat) | error | 0 | 22 | 0 |
| silver_geolocation | unique(zip_prefix) | error | 0 | 22 | 0 |
| silver_order_items | range(freight_value) | error | 0 | 22 | 0 |
| silver_order_items | range(price) | error | 0 | 22 | 0 |
| silver_order_items | relationships(order_id -> silver_orders.order_id) | error | 0 | 22 | 0 |
| silver_order_items | relationships(product_id -> silver_products.product_id) | error | 0 | 22 | 0 |
| silver_order_items | relationships(seller_id -> silver_sellers.seller_id) | error | 0 | 22 | 0 |
| silver_order_items | unique(order_id, order_item_id) | error | 0 | 22 | 0 |
| silver_orders | accepted_values(order_status) | error | 0 | 22 | 0 |
| silver_orders | carrier_after_purchase_after_repair | error | 0 | 22 | 0 |
| silver_orders | delivered_after_purchase | error | 0 | 22 | 0 |
| silver_orders | delivered_orders_have_date | warn | 0 | 22 | 0 |
| silver_orders | not_null(order_id, customer_id, purchased_at, estimated_delivery_date) | error | 0 | 22 | 0 |
| silver_orders | unique(order_id) | error | 0 | 22 | 0 |
| silver_payments | range(installments) | error | 0 | 22 | 0 |
| silver_payments | relationships(order_id -> silver_orders.order_id) | error | 0 | 22 | 0 |
| silver_payments | unique(order_id, payment_sequential) | error | 0 | 22 | 0 |
| silver_products | every_category_translated | error | 0 | 22 | 0 |
| silver_products | unique(product_id) | error | 0 | 22 | 0 |
| silver_reviews | range(review_score) | error | 0 | 22 | 0 |
| silver_reviews | unique(order_id) | error | 0 | 22 | 0 |

## Quarantined / repaired records

| source_table | reason | records |
|---|---|---|
| bronze_geolocation | coordinates outside Brazil | 42 |
| bronze_order_reviews | older duplicate review for the same order | 559 |
| silver_orders | carrier pickup before purchase (timestamp nulled) | 166 |
| silver_payments | payment type/installments repaired | 5 |

## Batch loads

| batch_id | cutoff | rows_loaded | seconds |
|---|---|---|---|
| batch_2017_01 | 2017-01-31 | 1006683 | 2.28 |
| batch_2017_02 | 2017-02-28 | 10531 | 0.03 |
| batch_2017_03 | 2017-03-31 | 15843 | 0.04 |
| batch_2017_04 | 2017-04-30 | 14320 | 0.04 |
| batch_2017_05 | 2017-05-31 | 22114 | 0.05 |
| batch_2017_06 | 2017-06-30 | 19316 | 0.05 |
| batch_2017_07 | 2017-07-31 | 23081 | 0.06 |
| batch_2017_08 | 2017-08-31 | 25692 | 0.07 |
| batch_2017_09 | 2017-09-30 | 25138 | 0.06 |
| batch_2017_10 | 2017-10-31 | 27359 | 0.07 |
| batch_2017_11 | 2017-11-30 | 40668 | 0.1 |
| batch_2017_12 | 2017-12-31 | 37156 | 0.1 |
| batch_2018_01 | 2018-01-31 | 41225 | 0.11 |
| batch_2018_02 | 2018-02-28 | 38923 | 0.11 |
| batch_2018_03 | 2018-03-31 | 43266 | 0.12 |
| batch_2018_04 | 2018-04-30 | 42693 | 0.12 |
| batch_2018_05 | 2018-05-31 | 41172 | 0.11 |
| batch_2018_06 | 2018-06-30 | 36741 | 0.1 |
| batch_2018_07 | 2018-07-31 | 35991 | 0.1 |
| batch_2018_08 | 2018-08-31 | 40097 | 0.14 |
| batch_2018_09 | 2018-09-30 | 739 | 0.0 |
| batch_2018_10 | 2018-10-31 | 51 | 0.0 |
