DO $$ DECLARE
i record;
max_id INTEGER;
sequence_name TEXT;
_start_value INTEGER;
_last_value INTEGER;
BEGIN
		FOR i IN SELECT TABLE_NAME
		,
		TABLE_SCHEMA,
		COLUMN_NAME,
		COLUMN_DEFAULT
	FROM
		information_schema.COLUMNS
	WHERE
		column_default LIKE'%nextval%'
		LOOP
		sequence_name = reverse (
			split_part(
				reverse ( SPLIT_PART( i.column_default, '''', 2 ) ),
				'.',
				1
			)
		);
	EXECUTE format (
		'SELECT max(%I) from %I.%I',
		i.COLUMN_NAME,
		i.TABLE_SCHEMA,
		i.TABLE_NAME
	) INTO max_id;
	EXECUTE format ( 'SELECT last_value, start_value FROM pg_sequences where schemaname=$1 and sequencename=$2' ) INTO _last_value,
	_start_value USING i.TABLE_SCHEMA,
	sequence_name;
	IF
		max_id IS NULL
		OR ( _last_value IS NULL AND _start_value > max_id )
		OR _last_value >= max_id THEN
			CONTINUE;

	END IF;
	EXECUTE format (
		'SELECT setval(%L, %L)',
		i.TABLE_SCHEMA || '.' || sequence_name,
		max_id
	);
	RAISE NOTICE'%, (%) --> (%)',
	i.TABLE_SCHEMA || '.' || i.TABLE_NAME,
	_last_value,
	max_id;

END LOOP;

END $$;