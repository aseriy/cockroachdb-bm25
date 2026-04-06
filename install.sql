-- System-wide constants
\i sql/BM25_consts.sql

-- Install TSVECTOR utility functions
\i sql/tsvector.sql


-- Install BM25_Okapi functions
\i sql/BM25_candidates.sql
\i sql/BM25_Okapi_IDF.sql
\i sql/BM25_Okapi_rank.sql


-- Install BM25 BMW functions
\i sql/BM25_BMW_blocks.sql


-- Install TSV sync function and trigger
DROP TRIGGER IF EXISTS bm25_sync ON passage;
\i sql/trigger.sql
