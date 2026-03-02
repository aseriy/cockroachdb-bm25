-- BM25 Okapi rank for a single document (passage row) vs. a query string.
--
-- Assumptions (per spec):
--  - passage(pk) exists and has non-NULL passage_tsv and passage_tsv_len.
--  - query is treated as a set of unique terms (duplicates ignored).
--  - IDF is obtained from BM25_Okapi_IDF(STRING[]) which uses corpus DF in _tsv_terms.
--  - avgdl and corpus size are computed from passage where passage_tsv is not NULL.
--
-- Signature:
--   BM25_Okapi_rank(pk UUID, query STRING, k1 FLOAT, b FLOAT) -> FLOAT

CREATE OR REPLACE FUNCTION BM25_Okapi_rank(
  query STRING,
  limit_n INT,
  k1 FLOAT,
  b FLOAT
)
RETURNS TABLE(pk UUID, score FLOAT)
LANGUAGE SQL

AS $$
  WITH
  candidates AS (
    SELECT id
    FROM BM25_candidates(query, limit_n)
  ),

  -- Corpus stats
  stats AS (
    SELECT n::FLOAT, avgdl
    FROM _tsv_corpus
    WHERE table_name ='passage' AND column_name = 'passage'
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

  -- Fetch document data for ALL candidates (the "Loop")
  docs AS (
    SELECT
      p.id AS doc_pk, p.passage_tsv AS tsv, p.passage_tsv_len::FLOAT AS dl
    FROM passage AS p
    INNER JOIN candidates c ON p.id = c.id -- This creates the iteration
  ),

  -- Term frequencies for all candidates
  docs_tf AS (
    SELECT d.doc_pk, tf.term, tf.freq
    FROM docs AS d, extract_passage_terms_freq(d.tsv) AS tf
  )

  -- Final Calculation grouped by each candidate ID
  SELECT
      d.doc_pk AS pk,
      coalesce(
          sum(
              q.idf * (
                  (dtf.freq::FLOAT * (k1 + 1.0))
                  /
                  (dtf.freq::FLOAT + k1 * (1.0 - b + b * (d.dl / stats.avgdl)))
              )
          ),
          0
      ) AS score
  FROM docs AS d
      CROSS JOIN stats
      CROSS JOIN q
      LEFT JOIN docs_tf AS dtf ON dtf.doc_pk = d.doc_pk AND dtf.term = q.term
  GROUP BY d.doc_pk
  ORDER BY score DESC
$$;


CREATE OR REPLACE FUNCTION BM25_Okapi_rank(
  query STRING,
  limit_n INT
)
RETURNS TABLE(pk UUID, score FLOAT)
LANGUAGE SQL
AS $$

    -- Simply passes through to the 4-arg version with your chosen defaults
    SELECT * FROM BM25_Okapi_rank(query, limit_n, 1.2, 0.75);

$$;


