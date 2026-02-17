CREATE OR REPLACE PROCEDURE passage_rebuild_all_terms(batch_size INT)
LANGUAGE plpgsql
AS $$
DECLARE
    rows_processed INT := 0;
    total_rows INT;
    current_offset INT := 0;
BEGIN
    -- 1. Reset all frequencies to 0 before starting the recalculation
    RAISE NOTICE 'Resetting frequencies...';
    UPDATE passage_passage_tsv_terms SET freq = 0;
    
    -- Commit the reset so the loop starts fresh
    COMMIT;

    -- 2. Get total count for the loop
    SELECT count(*) INTO total_rows FROM passage;

    WHILE current_offset < total_rows LOOP
        -- Process one chunk of the 'passage' table
        INSERT INTO passage_passage_tsv_terms (term, freq)
        SELECT 
            trim(both '''' FROM split_part(token, ':', 1)) AS term,
            COUNT(*) AS freq
        FROM (
            SELECT passage_tsv FROM passage 
            ORDER BY id 
            LIMIT batch_size OFFSET current_offset
        ) AS subquery,
        LATERAL unnest(string_to_array(passage_tsv::TEXT, ' ')) AS token
        GROUP BY 1
        ON CONFLICT (term) 
        DO UPDATE SET freq = passage_passage_tsv_terms.freq + EXCLUDED.freq;

        current_offset := current_offset + batch_size;
        
        -- Commit after every batch to release locks and clear WAL
        COMMIT; 
        
        RAISE NOTICE 'Processed % of % rows...', current_offset, total_rows;
    END LOOP;
END;
$$;
