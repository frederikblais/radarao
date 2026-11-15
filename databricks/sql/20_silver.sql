-- Argent : dernière version connue de chaque processus, puis adjudications aplaties.
CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.`silver_tenders` AS
WITH latest AS (
  SELECT * FROM `${catalog}`.`${schema}`.`bronze_releases`
  QUALIFY row_number() OVER (PARTITION BY ocid ORDER BY lpad(release_id, 20, '0') DESC) = 1
),
parsed AS (
  SELECT
    ocid, release_id, raw,
    raw:tender.id::string AS tender_id,
    raw:tender.title::string AS title,
    CASE WHEN array_contains(tags, 'tenderCancellation') THEN 'cancelled' ELSE raw:tender.status::string END AS status,
    coalesce(raw:tender.procuringEntity.id::string, raw:buyer.id::string) AS buyer_party_id,
    coalesce(raw:tender.procuringEntity.name::string, raw:buyer.name::string) AS buyer_name,
    raw:tender.mainProcurementCategory::string AS main_category,
    raw:tender.procurementMethod::string AS procurement_method,
    try_cast(raw:tender.numberOfTenderers::string AS INT) AS number_of_tenderers,
    try_to_timestamp(raw:tender.tenderPeriod.endDate::string) AS end_date,
    from_json(raw:tender.items, 'array<struct<classification:struct<id:string,description:string>>>') AS items,
    from_json(raw:parties, 'array<struct<id:string,name:string,address:struct<postalCode:string>>>') AS parties
  FROM latest
),
enriched AS (
  SELECT p.*,
    substr(p.items[0].classification.id, 1, 8) AS unspsc_main,
    p.items[0].classification.description AS unspsc_label,
    upper(regexp_replace(filter(p.parties, x -> x.id = p.buyer_party_id)[0].address.postalCode, '[^A-Za-z0-9]', ''))
      AS buyer_postal
  FROM parsed p
)
SELECT e.* EXCEPT (raw, items, parties),
  coalesce(r3.region_code, r2.region_code) AS region_code
FROM enriched e
LEFT JOIN `${catalog}`.`${schema}`.`ref_fsa_region` r3 ON r3.prefix = substr(e.buyer_postal, 1, 3)
LEFT JOIN `${catalog}`.`${schema}`.`ref_fsa_region` r2 ON r2.prefix = substr(e.buyer_postal, 1, 2);

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.`silver_awards` AS
WITH latest AS (
  SELECT ocid, raw FROM `${catalog}`.`${schema}`.`bronze_releases`
  WHERE raw:awards IS NOT NULL
  QUALIFY row_number() OVER (PARTITION BY ocid ORDER BY lpad(release_id, 20, '0') DESC) = 1
),
aw AS (
  SELECT ocid, a.*,
    from_json(raw:contracts, 'array<struct<id:string,awardID:string,value:struct<amount:double>>>') AS contracts
  FROM latest
  LATERAL VIEW explode(from_json(raw:awards,
    'array<struct<id:string,date:string,value:struct<amount:double>,suppliers:array<struct<id:string,name:string>>>>')) x AS a
)
SELECT
  aw.ocid, aw.id AS award_id, s.id AS supplier_party_id, s.name AS supplier_name,
  coalesce(aw.value.amount, aggregate(filter(aw.contracts, c -> coalesce(c.awardID, c.id) = aw.id),
           CAST(0 AS DOUBLE), (acc, c) -> acc + coalesce(c.value.amount, 0))) AS amount,
  try_to_timestamp(aw.date) AS award_date,
  t.buyer_party_id, t.buyer_name, t.unspsc_main, t.unspsc_label, t.region_code, t.main_category,
  t.procurement_method, t.number_of_tenderers
FROM aw
LATERAL VIEW explode(aw.suppliers) y AS s
JOIN `${catalog}`.`${schema}`.`silver_tenders` t ON t.ocid = aw.ocid
WHERE s.id IS NOT NULL;
