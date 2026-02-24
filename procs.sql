CREATE OR REPLACE FUNCTION extract_passage_terms(p_tsv tsvector)
RETURNS TABLE(term text)
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT
        trim(both '''' FROM split_part(token, ':', 1)) AS term
    FROM unnest(string_to_array(p_tsv::text, ' ')) AS token;
$$;


SELECT extract_passage_terms((SELECT passage_tsv FROM passage LIMIT 1));


CREATE OR REPLACE FUNCTION tsv_doclen(tsv TSVECTOR)
RETURNS INT
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT count(*)
    FROM unnest(string_to_array(tsv::TEXT, ' ')) AS term,
         unnest(
             string_to_array(
                 split_part(term, ':', 2),
                 ','
             )
         ) AS pos
$$;


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





-- Function to calculate IDF (Inverse Document Frequency)
--
-- CREATE OR REPLACE FUNCTION BM25_Okapi_IDF(q STRING)
-- RETURNS FLOAT
-- LANGUAGE SQL
-- AS $$
--   WITH n AS (
--     SELECT count(*)::FLOAT AS corpus_size
--     FROM passage
--     WHERE passage_tsv IS NOT NULL
--   )
--   SELECT
--     CASE
--       WHEN t.freq IS NULL OR t.freq = 0 THEN 0.0
--       ELSE ln((n.corpus_size - t.freq::FLOAT + 0.5) / (t.freq::FLOAT + 0.5))
--     END
--   FROM n
--   LEFT JOIN passage_passage_tsv_terms AS t
--     ON t.term = q
-- $$;


---
--- Okapi BM25
--- https://en.wikipedia.org/wiki/Okapi_BM25#:~:text=In%20information%20retrieval%2C%20Okapi%20BM25,functions%20used%20in%20document%20retrieval.
---
CREATE OR REPLACE FUNCTION BM25_Okapi_IDF(queries STRING[])
RETURNS FLOAT[]
LANGUAGE SQL
AS $$
  WITH n AS (
    SELECT count(*)::FLOAT AS corpus_size
    FROM passage
    WHERE passage_tsv IS NOT NULL
  ),
  -- Unnest the input array while tracking the original index
  input_terms AS (
    SELECT term, ord
    FROM unnest(queries) WITH ORDINALITY AS t(term, ord)
  )
  SELECT array_agg(
    ln(1 +
        (n.corpus_size - coalesce(tf.freq, 0)::FLOAT + 0.5) /
        (coalesce(tf.freq, 0)::FLOAT + 0.5)
    )
    ORDER BY it.ord -- Ensure the output array matches the input order
  )
  FROM n, input_terms AS it
  LEFT JOIN passage_passage_tsv_terms AS tf
    ON tf.term = it.term
$$;

SELECT BM25_Okapi_IDF(ARRAY['apple', 'banana', 'cherry']) AS idf;
SELECT BM25_Okapi_IDF('{"apple", "banana", "cherry"}'::STRING[]) AS idf;


