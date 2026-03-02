---
--- Okapi BM25
--- https://en.wikipedia.org/wiki/Okapi_BM25#:~:text=In%20information%20retrieval%2C%20Okapi%20BM25,functions%20used%20in%20document%20retrieval.
---
CREATE OR REPLACE FUNCTION BM25_Okapi_IDF(queries STRING[])
RETURNS FLOAT[]
LANGUAGE SQL
AS $$
  WITH n AS (
    SELECT n::FLOAT AS corpus_size
    FROM _tsv_corpus
    WHERE table_name ='passage' AND column_name = 'passage'
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
  LEFT JOIN _tsv_terms AS tf
    ON tf.term = it.term
    AND tf.table_name = 'passage' 
    AND tf.column_name = 'passage'
$$;

-- SELECT BM25_Okapi_IDF(ARRAY['apple', 'banana', 'cherry']) AS idf;
-- SELECT BM25_Okapi_IDF('{"apple", "banana", "cherry"}'::STRING[]) AS idf;


-- CREATE OR REPLACE FUNCTION BM25_Okapi_IDF(
--     src_table TEXT,
--     tsv_column TEXT,
--     stats_table TEXT,
--     queries STRING[]
-- ) RETURNS FLOAT[] LANGUAGE PLpgSQL AS $$
-- DECLARE
--     result_array FLOAT[];
-- BEGIN
--     -- %I safely escapes the table name as a SQL identifier
--     EXECUTE format('
--         WITH n AS (
--             SELECT count(*)::FLOAT AS corpus_size 
--             FROM %I 
--             WHERE %I IS NOT NULL
--         ),
--         input_terms AS (
--             SELECT term, ord FROM unnest($1) WITH ORDINALITY AS t(term, ord)
--         )
--         SELECT array_agg(
--             ln(1 + (n.corpus_size - coalesce(tf.freq, 0)::FLOAT + 0.5) / 
--                    (coalesce(tf.freq, 0)::FLOAT + 0.5)
--             ) ORDER BY it.ord
--         )
--         FROM n, input_terms AS it
--         LEFT JOIN %I AS tf ON tf.term = it.term
--         ',
--         src_table, tsv_column, stats_table
--     )
--     USING queries 
--     INTO result_array;

--     RETURN result_array;
-- END;
-- $$;


