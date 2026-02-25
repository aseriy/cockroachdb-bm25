-- BM25 Okapi rank for a single document (passage row) vs. a query string.
--
-- Assumptions (per spec):
--  - passage(pk) exists and has non-NULL passage_tsv and passage_tsv_len.
--  - query is treated as a set of unique terms (duplicates ignored).
--  - IDF is obtained from BM25_Okapi_IDF(STRING[]) which uses corpus DF in passage_passage_tsv_terms.
--  - avgdl and corpus size are computed from passage where passage_tsv is not NULL.
--
-- Signature:
--   BM25_Okapi_rank(pk UUID, query STRING, k1 FLOAT, b FLOAT) -> FLOAT

CREATE OR REPLACE FUNCTION BM25_Okapi_rank(
  pk UUID,
  query STRING,
  k1 FLOAT,
  b FLOAT
)
RETURNS TABLE(pk UUID, score FLOAT)
LANGUAGE SQL

AS $$
  WITH
  -- Fetch the document (pk) vector and length
  doc AS (
    SELECT
      passage_tsv AS tsv, passage_tsv_len::FLOAT AS dl
    FROM passage
    WHERE id = pk
  ),

  -- Corpus stats
  stats AS (
    SELECT
      count(*) AS n,
      avg(passage_tsv_len)::FLOAT AS avgdl
    FROM passage
    WHERE passage_tsv IS NOT NULL
  ),

  -- Put terms into an array (needed for BM25_Okapi_IDF)
  q_arr AS (
    SELECT array_agg(term) AS terms
    FROM (SELECT extract_passage_terms(to_tsvector(query)) AS term)
  ),

  q AS (
    SELECT t.term, t.idf::FLOAT
    FROM q_arr,
        unnest(
          coalesce(q_arr.terms, ARRAY[]::STRING[]), 
          coalesce(BM25_Okapi_IDF(q_arr.terms), ARRAY[]::FLOAT[])
        ) AS t(term, idf)
  ),

  -- Parse document tsvector text into per-term tf by counting positions.
  -- tsv::text looks like:  'term':1,5,9 'other':2 ...
  -- We split on spaces to get each token; then split on ':' to separate term and positions.
  -- Positions part may contain weights like 1A,2B,...; strip letters before counting.
  doc_tf AS (
    SELECT tf.term, tf.freq
    FROM doc, extract_passage_terms_freq(doc.tsv) AS tf
  )

  SELECT
      pk,
      coalesce(
          sum(
              q.idf * (
                  (doc_tf.freq::FLOAT * (k1 + 1.0))
                  /
                  (doc_tf.freq::FLOAT + k1 * (1.0 - b + b * (doc.dl / stats.avgdl)))
              )
          ),
          0
      )
  FROM q
      JOIN doc ON true
      JOIN stats ON true
      LEFT JOIN doc_tf
  ON doc_tf.term = q.term
  WHERE coalesce(doc_tf.freq, 0) > 0
$$;
