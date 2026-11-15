-- RadarAO — lakehouse Databricks (ADR-005). Variables remplacées par worker/lakehouse : ${catalog}, ${schema}.
CREATE SCHEMA IF NOT EXISTS `${catalog}`.`${schema}`
  COMMENT 'RadarAO : historique des données ouvertes du SEAO (CC-BY 4.0). Aucune donnée personnelle de client.';

CREATE VOLUME IF NOT EXISTS `${catalog}`.`${schema}`.`seao_raw`
  COMMENT 'Fichiers SEAO bruts convertis en NDJSON (une publication par ligne).';

-- Bronze : publications brutes, une ligne par (ocid, release_id). Idempotent par MERGE.
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`bronze_releases` (
  ocid STRING NOT NULL,
  release_id STRING NOT NULL,
  tags ARRAY<STRING>,
  release_date STRING,
  raw STRING COMMENT 'Publication OCDS complète (JSON)',
  source_file STRING,
  ingested_at TIMESTAMP
) CLUSTER BY (ocid)
  COMMENT 'Couche bronze : publications OCDS du SEAO telles que publiées.';

-- Référence : région administrative déduite de la RTA (3 premiers caractères du code postal).
CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.`ref_fsa_region` (
  prefix STRING NOT NULL,
  region_code STRING NOT NULL
) COMMENT 'Correspondance approximative RTA -> région administrative (voir ADR-003).';
