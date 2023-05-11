DO $$ DECLARE

i record;
max_id INTEGER;
sequence_name TEXT;

BEGIN
FOR i IN SELECT
    nsp.nspname AS schema,
    seq.relname AS sequence,
    tab.relname AS table,
    attr.attname AS column,
		pseq.start_value,
		pseq.last_value
FROM
    pg_class seq
INNER JOIN
    pg_depend dep ON (dep.objid = seq.oid)
INNER JOIN
    pg_class tab ON (dep.refobjid = tab.oid)
INNER JOIN
    pg_attribute attr ON (attr.attnum = dep.refobjsubid AND attr.attrelid = tab.oid)
INNER JOIN
    pg_namespace nsp ON (nsp.oid = tab.relnamespace)
INNER JOIN
    pg_index ind ON (ind.indrelid = tab.oid AND ind.indisprimary)
INNER JOIN
    pg_sequences pseq ON (pseq.schemaname = nsp.nspname and pseq.sequencename = seq.relname)
WHERE
    seq.relkind = 'S'
LOOP

EXECUTE format (
'SELECT max(%I) from %I.%I',
i.column,
i.schema,
i.table
) INTO max_id;

IF
max_id IS NULL
OR ( i.last_value IS NULL AND i.start_value > max_id )
OR i.last_value >= max_id THEN
CONTINUE;
END IF;

EXECUTE format (
'SELECT setval(%L, %L)',
i.schema || '.' || i.sequence,
max_id
);
RAISE NOTICE'%, (%) --> (%)',
i.schema || '.' || i.table,
i.last_value,
max_id;

END LOOP;

END $$;
