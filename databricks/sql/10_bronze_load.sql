-- Charge un fichier NDJSON du volume dans la couche bronze. ${file_path} et ${source_file} sont
-- générés par le code (noms validés), pas par un utilisateur.
MERGE INTO `${catalog}`.`${schema}`.`bronze_releases` AS t
USING (
  SELECT
    value:ocid::string AS ocid,
    value:id::string AS release_id,
    from_json(value:tag, 'array<string>') AS tags,
    value:date::string AS release_date,
    value AS raw,
    '${source_file}' AS source_file,
    current_timestamp() AS ingested_at
  FROM read_files('${file_path}', format => 'text')
  WHERE value:ocid IS NOT NULL AND value:id IS NOT NULL
) AS s
ON t.ocid = s.ocid AND t.release_id = s.release_id
WHEN NOT MATCHED THEN INSERT *;
