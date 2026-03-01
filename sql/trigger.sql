CREATE OR REPLACE FUNCTION passage_passage_tsv_terms_sync()
RETURNS trigger
LANGUAGE plpgsql
AS $$

DECLARE
    v_reset boolean := false;
    v_return passage := NULL;

BEGIN
    -- RAISE NOTICE 'Trigger fired for operation: %', TG_OP;

    -- Session-level flag
    v_reset := coalesce(current_setting('bm25.reset', true), 'false') = 'true';
    -- RAISE NOTICE 'v_reset: %', v_reset;

    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' AND v_reset THEN

        NEW.passage_tsv := to_tsvector('english', (NEW).passage);
        NEW.passage_tsv_len := tsv_doclen((NEW).passage_tsv);
        v_return := NEW;

        -- Increments term counters
        INSERT INTO passage_passage_tsv_terms (term, freq)
        SELECT term, 1
        FROM extract_passage_terms((NEW).passage_tsv) AS term
        ON CONFLICT (term)
        DO UPDATE SET freq = passage_passage_tsv_terms.freq + 1;

        -- Increment corpus stats
        UPDATE _tsv_corpus
            SET n = n + 1, total = total + (NEW).passage_tsv_len
            WHERE table_name ='passage' AND column_name = 'passage';

    ELSIF TG_OP = 'DELETE' THEN
        v_return := OLD;

        -- Decrement term counters
        UPDATE passage_passage_tsv_terms AS t
        SET freq = t.freq - 1
        FROM extract_passage_terms((OLD).passage_tsv) AS term
        WHERE t.term = term.term;

        -- Decrement corpus stats
        UPDATE _tsv_corpus
            SET n = n - 1, total = total - (OLD).passage_tsv_len
            WHERE table_name ='passage' AND column_name = 'passage';

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

        -- Update corpus stats
        -- This doesn't change the document count (N)
        -- but we need to update total document size
        -- with the net change of this document length
        UPDATE _tsv_corpus
            SET total = total + ((NEW).passage_tsv_len - (OLD).passage_tsv_len)
            WHERE table_name ='passage' AND column_name = 'passage';

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

