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




CREATE OR REPLACE FUNCTION extract_passage_terms(p_tsv tsvector)
RETURNS TABLE(term text)
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT
        trim(both '''' FROM split_part(token, ':', 1)) AS term
    FROM unnest(string_to_array(p_tsv::text, ' ')) AS token;
$$;


SELECT extract_passage_terms((SELECT passage_tsv FROM passage LIMIT 1));




CREATE OR REPLACE FUNCTION passage_passage_tsv_terms_sync()
RETURNS trigger
LANGUAGE plpgsql
AS $$

DECLARE
    v_reset boolean := false;
    v_return passage := NULL;

BEGIN
    RAISE NOTICE 'Trigger fired for operation: %', TG_OP;

    -- Session-level flag
    v_reset := coalesce(current_setting('bm25.reset', true), 'false') = 'true';
    RAISE NOTICE 'v_reset: %', v_reset;

    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' AND v_reset THEN

        NEW.passage_tsv := to_tsvector('english', (NEW).passage);
        NEW.passage_tsv_len := tsv_doclen((NEW).passage_tsv);
        v_return := NEW;

        INSERT INTO passage_passage_tsv_terms (term, freq)
        SELECT term, 1
        FROM extract_passage_terms((NEW).passage_tsv) AS term
        ON CONFLICT (term)
        DO UPDATE SET freq = passage_passage_tsv_terms.freq + 1;


    ELSIF TG_OP = 'DELETE' THEN
        v_return := OLD;

        UPDATE passage_passage_tsv_terms AS t
        SET freq = t.freq - 1
        FROM extract_passage_terms((OLD).passage_tsv) AS term
        WHERE t.term = term.term;


    ELSIF TG_OP = 'UPDATE' THEN

        IF (NEW).passage <> (OLD).passage THEN
            NEW.passage_tsv := to_tsvector('english', (NEW).passage);
            NEW.passage_tsv_len := tsv_doclen((NEW).passage_tsv);
        END IF;
        v_return := NEW;

        -- First: Handle removals
        UPDATE passage_passage_tsv_terms AS t
        SET freq = t.freq - 1
        FROM (
            SELECT term FROM extract_passage_terms((OLD).passage_tsv)
            EXCEPT
            SELECT term FROM extract_passage_terms((NEW).passage_tsv)
        ) AS removed
        WHERE t.term = removed.term;

        -- Second: Handle additions
        INSERT INTO passage_passage_tsv_terms (term, freq)
        SELECT term, 1 FROM (
            SELECT term FROM extract_passage_terms((NEW).passage_tsv)
            EXCEPT
            SELECT term FROM extract_passage_terms((OLD).passage_tsv)
        ) AS added
        ON CONFLICT (term)
        DO UPDATE SET freq = passage_passage_tsv_terms.freq + 1;

    ELSE
        SELECT 1;

    END IF;

    RETURN v_return;
END;
$$;



CREATE TRIGGER sync_passage_terms
    BEFORE INSERT OR UPDATE OR DELETE ON passage
    FOR EACH ROW
    EXECUTE FUNCTION passage_passage_tsv_terms_sync();
