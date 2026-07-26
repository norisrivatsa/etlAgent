CREATE STREAM ORDERS_RAW (
  order_id BIGINT,
  customer_id BIGINT,
  status VARCHAR,
  total DOUBLE,
  created_at BIGINT
) WITH (
  KAFKA_TOPIC='pg-orders',
  VALUE_FORMAT='JSON',
  TIMESTAMP='created_at'
);

CREATE STREAM ORDERS_PARTITIONED AS
  SELECT *
  FROM ORDERS_RAW
  PARTITION BY CAST(order_id AS VARCHAR);

CREATE STREAM ORDERS_NORMALIZED AS
  SELECT
    order_id,
    customer_id,
    status,
    total,
    TIMESTAMPTOSTRING(ROWTIME, 'yyyy-MM-dd') AS order_date,
    ROWTIME AS event_ts
  FROM ORDERS_PARTITIONED;

CREATE TABLE DAILY_SALES AS
  SELECT
    order_date,
    SUM(total) AS total_sales
  FROM ORDERS_NORMALIZED
  GROUP BY order_date;

CREATE TABLE STATUS_COUNTS AS
  SELECT
    status,
    COUNT(*) AS status_count
  FROM ORDERS_NORMALIZED
  GROUP BY status;

CREATE STREAM ORDERS_BY_DATE AS
  SELECT *
  FROM ORDERS_NORMALIZED
  PARTITION BY order_date;

CREATE STREAM ORDERS_WITH_DAILY AS
  SELECT
    o.order_id,
    o.customer_id,
    o.status,
    o.total,
    o.order_date,
    o.event_ts,
    ds.total_sales
  FROM ORDERS_BY_DATE o
  LEFT JOIN DAILY_SALES ds
    ON o.order_date = ds.order_date;

CREATE STREAM ORDERS_BY_STATUS AS
  SELECT *
  FROM ORDERS_WITH_DAILY
  PARTITION BY status;

CREATE STREAM ORDERS_ENRICHED AS
  SELECT
    o.order_id,
    o.customer_id,
    o.status,
    o.total,
    o.order_date,
    o.event_ts,
    o.total_sales,
    sc.status_count
  FROM ORDERS_BY_STATUS o
  LEFT JOIN STATUS_COUNTS sc
    ON o.status = sc.status;
