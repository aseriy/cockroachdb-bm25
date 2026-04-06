CREATE OR REPLACE FUNCTION bm25_sync()
RETURNS trigger
LANGUAGE plpgsql
AS $$

DECLARE
    v_reset boolean := false;
    v_return passage := NULL;
    v_tsv_term_tc JSONB := NULL;
    v_tsv_json JSONB := NULL;

BEGIN
    -- RAISE NOTICE 'Trigger fired for operation: %', TG_OP;

    -- Session-level flag
    v_reset := coalesce(current_setting('bm25.reset', true), 'false') = 'true';
    -- RAISE NOTICE 'v_reset: %', v_reset;

    IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' AND v_reset THEN

        NEW.passage_tsv := to_tsvector('english', (NEW).passage);
        NEW.passage_tsv_len := tsv_doclen((NEW).passage_tsv);

        SELECT jsonb_agg(to_jsonb(t)) INTO v_tsv_term_tc
        FROM (
            SELECT
            (NEW).id,
            f.term,
            f.freq::FLOAT / (NEW).passage_tsv_len::FLOAT AS tc
            FROM extract_passage_terms_freq((NEW).passage_tsv) AS f
        ) AS t;

        SELECT jsonb_build_object(
            'tf',
            COALESCE(
                jsonb_object_agg(f.term, f.freq),
                '{}'::JSONB
            ),
            'dl',
            tsv_doclen((NEW).passage_tsv)
        )
        INTO v_tsv_json
        FROM extract_passage_terms_freq((NEW).passage_tsv) AS f;
        
        NEW.passage_tsv_jsonb := v_tsv_json;

        v_return := NEW;

        -- Increments term counters and updates upper bound
        INSERT INTO _tsv_terms_131_3 (term, freq, ub)
        SELECT term, 1, tc
        FROM jsonb_to_recordset(v_tsv_term_tc) 
            AS x(id UUID, term STRING, tc FLOAT)
        ON CONFLICT (term)
        DO UPDATE SET 
            freq = _tsv_terms_131_3.freq + 1,
            ub = GREATEST(_tsv_terms_131_3.ub, EXCLUDED.ub);
            

        -- Update BMW blocks
        WITH term_rows AS (
            SELECT *
            FROM jsonb_to_recordset(v_tsv_term_tc)
                AS x(id UUID, term STRING, tc FLOAT8)
        ),
        routed AS (
            SELECT
                id,
                term,
                tc,
                BM25_BMW_find_block(term, id) AS block_id
            FROM term_rows
        )
        SELECT
            CASE
                WHEN block_id IS NULL THEN BM25_BMW_create_block(term, id, tc)
                ELSE BM25_BMW_add_to_block(block_id, term, id, tc)
            END
        FROM routed;

        -- Add term contrib (TC) to _tsv_term_tc_<tbl_oid>_<col_oid>
        INSERT INTO _tsv_term_tc_131_3 (doc_id, term, tc)
        SELECT id, term, tc
        FROM jsonb_to_recordset(v_tsv_term_tc)
            AS x(id UUID, term STRING, tc FLOAT);

        -- Increment corpus stats
        UPDATE _tsv_corpus
            SET n = n + 1, total = total + (NEW).passage_tsv_len
            WHERE table_name ='passage' AND column_name = 'passage';


    ELSIF TG_OP = 'DELETE' THEN
        v_return := OLD;

        -- Decrement term counters
        UPDATE _tsv_terms_131_3
        SET freq = freq - 1
        FROM extract_passage_terms((OLD).passage_tsv) AS old_term
        WHERE term = old_term
            -- AND table_name ='passage' AND column_name = 'passage'
            ;

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
        UPDATE _tsv_terms_131_3 AS t
        SET freq = freq - 1
        FROM (
            SELECT term FROM extract_passage_terms((OLD).passage_tsv)
            EXCEPT
            SELECT term FROM extract_passage_terms((NEW).passage_tsv)
        ) AS removed
        WHERE t.term = removed.term
            -- AND t.table_name ='passage' AND t.column_name = 'passage'
            ;

        -- Second: Handle additions
        -- INSERT INTO _tsv_terms_131_3 (table_name, column_name, term, freq)
        -- SELECT 'passage', 'passage', term, 1 FROM (
        INSERT INTO _tsv_terms_131_3 (term, freq)
        SELECT term, 1 FROM (
            SELECT term FROM extract_passage_terms((NEW).passage_tsv)
            EXCEPT
            SELECT term FROM extract_passage_terms((OLD).passage_tsv)
        ) AS added
        -- ON CONFLICT (table_name, column_name, term)
        ON CONFLICT (term)
        DO UPDATE SET freq = _tsv_terms_131_3.freq + 1;

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



CREATE TRIGGER bm25_sync
    BEFORE INSERT OR UPDATE OR DELETE ON passage
    FOR EACH ROW
    EXECUTE FUNCTION bm25_sync();

