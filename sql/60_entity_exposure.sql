-- 60_entity_exposure.sql: limit exposure per entity of the run (needed to choose heads).
-- A record counts toward the entity it is linked to, else toward its own U: pseudo-entity.

TRUNCATE TABLE RESOLVE.W_ENTITY_EXPOSURE_RUN;

INSERT INTO RESOLVE.W_ENTITY_EXPOSURE_RUN (entity_key, exposure)
SELECT COALESCE(l.entity_key, 'U:' || f.rec_key), SUM(f.exposure_amount)
FROM RESOLVE.W_FACT_RUN f
LEFT JOIN RESOLVE.W_RECORD_ENTITY_RUN l ON l.rec_key = f.rec_key
GROUP BY COALESCE(l.entity_key, 'U:' || f.rec_key);
