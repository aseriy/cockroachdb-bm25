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
