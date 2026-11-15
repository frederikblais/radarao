-- Or : repères de marché (F9, go / no-go) et prévisions de renouvellement de contrats.
CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.`gold_market_benchmarks` AS
WITH a AS (
  SELECT substr(unspsc_main, 1, 6) AS cls, coalesce(region_code, '00') AS rg, * EXCEPT (region_code)
  FROM `${catalog}`.`${schema}`.`silver_awards` WHERE unspsc_main IS NOT NULL
),
scoped AS (
  SELECT cls, rg, ocid, supplier_name, buyer_name, amount, award_date, number_of_tenderers FROM a
  UNION ALL
  SELECT cls, '**' AS rg, ocid, supplier_name, buyer_name, amount, award_date, number_of_tenderers FROM a
),
stats AS (
  SELECT cls, rg, count(DISTINCT ocid) AS contracts, avg(number_of_tenderers) AS avg_tenderers,
    percentile_approx(amount, 0.25) AS amount_p25, percentile_approx(amount, 0.5) AS amount_median,
    percentile_approx(amount, 0.75) AS amount_p75, min(award_date) AS period_start, max(award_date) AS period_end
  FROM scoped GROUP BY cls, rg
),
sup AS (
  SELECT cls, rg, collect_list(named_struct('name', supplier_name, 'contracts', n, 'amount', total)) AS top_suppliers
  FROM (SELECT cls, rg, supplier_name, count(*) AS n, sum(amount) AS total,
               row_number() OVER (PARTITION BY cls, rg ORDER BY count(*) DESC, sum(amount) DESC) AS rk
        FROM scoped GROUP BY cls, rg, supplier_name) WHERE rk <= 5 GROUP BY cls, rg
),
buy AS (
  SELECT cls, rg, collect_list(named_struct('name', buyer_name, 'contracts', n, 'amount', total)) AS top_buyers
  FROM (SELECT cls, rg, buyer_name, count(DISTINCT ocid) AS n, sum(amount) AS total,
               row_number() OVER (PARTITION BY cls, rg ORDER BY count(DISTINCT ocid) DESC) AS rk
        FROM scoped WHERE buyer_name IS NOT NULL GROUP BY cls, rg, buyer_name) WHERE rk <= 5 GROUP BY cls, rg
)
SELECT s.cls AS unspsc_prefix, s.rg AS region_code, s.contracts, s.avg_tenderers, s.amount_p25, s.amount_median,
       s.amount_p75, s.period_start, s.period_end, to_json(sup.top_suppliers) AS top_suppliers,
       to_json(buy.top_buyers) AS top_buyers, current_timestamp() AS computed_at
FROM stats s LEFT JOIN sup USING (cls, rg) LEFT JOIN buy USING (cls, rg)
WHERE s.contracts >= 3;

-- Un organisme qui rachète périodiquement le même type de contrat (même classe UNSPSC) va
-- probablement republier un avis : date prévue = dernière adjudication + intervalle médian.
CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.`gold_renewal_forecasts` AS
WITH ev AS (
  SELECT buyer_party_id, substr(unspsc_main, 1, 6) AS cls, ocid, min(award_date) AS d,
    any_value(buyer_name) AS buyer_name, any_value(unspsc_label) AS unspsc_label,
    any_value(region_code) AS region_code, any_value(main_category) AS main_category,
    max_by(supplier_name, award_date) AS supplier, sum(amount) AS amount
  FROM `${catalog}`.`${schema}`.`silver_awards`
  WHERE award_date IS NOT NULL AND buyer_party_id IS NOT NULL AND unspsc_main IS NOT NULL
  GROUP BY buyer_party_id, substr(unspsc_main, 1, 6), ocid
),
iv AS (
  SELECT *, datediff(d, lag(d) OVER (PARTITION BY buyer_party_id, cls ORDER BY d)) AS gap,
         row_number() OVER (PARTITION BY buyer_party_id, cls ORDER BY d DESC) AS rk
  FROM ev
),
st AS (
  SELECT buyer_party_id, cls, percentile_approx(gap, 0.5) AS med, stddev(gap) AS sd, count(*) + 1 AS n
  FROM iv WHERE gap > 90 GROUP BY buyer_party_id, cls
)
SELECT l.buyer_party_id, l.buyer_name, st.cls AS unspsc_prefix, l.unspsc_label, l.region_code, l.main_category,
  CAST(st.n AS INT) AS occurrences, CAST(st.med AS INT) AS median_interval_days, l.d AS last_award_date,
  CAST(date_add(l.d, CAST(st.med AS INT)) AS TIMESTAMP) AS predicted_date,
  CAST(greatest(30, least(120, coalesce(st.sd, st.med * 0.15))) AS INT) AS window_days,
  l.supplier AS last_supplier, l.amount AS last_amount,
  CASE WHEN st.n >= 4 AND coalesce(st.sd / st.med, 1) < 0.25 THEN 'high'
       WHEN st.n >= 3 AND coalesce(st.sd / st.med, 1) < 0.40 THEN 'medium' ELSE 'low' END AS confidence,
  current_timestamp() AS computed_at
FROM st JOIN iv l ON l.buyer_party_id = st.buyer_party_id AND l.cls = st.cls AND l.rk = 1
WHERE st.med BETWEEN 180 AND 2200
  AND date_add(l.d, CAST(st.med AS INT)) BETWEEN date_sub(current_date(), 60) AND date_add(current_date(), 540);
