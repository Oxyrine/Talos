-- 51_components_init.sql: every entity of the run starts with its own key as its label.

TRUNCATE TABLE RESOLVE.W_COMPONENT_RUN;

INSERT INTO RESOLVE.W_COMPONENT_RUN (entity_id, label)
SELECT entity_key, entity_key
FROM RESOLVE.W_ENTITY_RUN;
