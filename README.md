# cockroachdb-bm25

Yes. In CockroachDB, do it in two steps: **add a STORED computed column**, then **add an inverted index** on that column. ([Cockroach Labs][1])

### 1) Add `passage_tsv TSVECTOR` column

```sql
ALTER TABLE passage
ADD COLUMN passage_tsv TSVECTOR
```


### 2) Index it (inverted index)

```sql
CREATE INVERTED INDEX passage_tsv_idx ON passage (passage_tsv);
```

* In CRDB, `CREATE INVERTED INDEX` is the GIN-style index primitive. ([Cockroach Labs][2])

### 3) Quick sanity check query (optional)

```sql
SELECT id, passage
FROM nextgenreporting.public.passage
WHERE passage_tsv @@ plainto_tsquery('english', 'how to get internet')
LIMIT 10;
```

(Using `@@` is what lets the inverted index be considered for the filter.)

[1]: https://www.cockroachlabs.com/docs/stable/computed-columns?utm_source=chatgpt.com "Computed Columns - CockroachDB Docs"
[2]: https://www.cockroachlabs.com/docs/stable/inverted-indexes?utm_source=chatgpt.com "Generalized Inverted Indexes - CockroachDB Docs"






Everything _initialize() computes can be expressed as:

Per-document term frequency

Per-document length

Term → document frequency

Corpus size

Average document length

All of that can live in relational tables and be maintained incrementally.

If you design:

doc_stats(id, doc_len)

term_stats(term, doc_freq)

corpus_stats(total_docs, avgdl)

Then:

On INSERT:

Extract lexemes from passage_tsv

Update doc_stats

Increment term_stats for distinct terms

Increment corpus counters

On UPDATE:

Diff old vs new lexemes

Adjust stats

On DELETE:

Decrement accordingly

That logic can absolutely live in:

A stored procedure

Or trigger-invoked procedure

Or lightweight CDC consumer writing back into the same cluster

You’re correct: this is cleaner than rebuilding corpus state in Python.

What remains in Python (or Go, ideally) would just be:

Fetch candidate doc IDs

Fetch TF, IDF, doc_len

Apply scoring formula

Sort top-K

That separation is much more production-aligned:

Database → state + stats
Application → ranking math

And yes — doing the stats incrementally prevents the “full corpus rebuild” noise.

The main engineering challenges will be:

Handling hot terms

Efficient diffing on UPDATE

Avoiding write amplification

But architecturally, your direction is coherent.




Mapping BM25 internals to DB structures

## doc_stats

Purpose:
Stores per-document term count (token count).

Equivalent to:
self.doc_len in the BM25 class.

Meaning:
Total number of lexeme occurrences in the document.
Derived from number of positions in tsvector.

## term_stats

Purpose: Stores document frequency per term.

```sql
CREATE TABLE IF NOT EXISTS passage_passage_tsv_terms (
    term STRING PRIMARY KEY USING HASH WITH (bucket_count=16),
    freq INT,
    idf_bm25okapi FLOAT8
);
```

RESET tracking table:

```sql
DELETE FROM passage_passage_tsv_terms;
```

To test the trigger/term_stats update:

```sql
BEGIN;
SET LOCAL bm25.reset = 'true';
UPDATE passage SET pid = 'msmarco_passage_00_100000577' WHERE id='9c0f4b37-beb6-40d4-8347-32295173211f';
COMMIT;
```

Helper:

```sql
DROP TRIGGER sync_passage_terms ON passage;
```

Verify the updated term_stats:

```sql
SELECT * FROM passage_passage_tsv_terms ORDER by term;
```


The below is the template for future mass reset of the stats:

```sql
-- Set the session to READ COMMITTED
SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED;
BEGIN;
SELECT 1 FROM passage WHERE 1=1 FOR SHARE;
-- Run your read-heavy proc here
COMMIT;
SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL SERIALIZABLE;
```

To select only the rows that need to be "touched" to reset counts:

```sql
SELECT id FROM passage 
AS OF SYSTEM TIME '1771323271468449663.0000000002'
LIMIT 10;
```

Equivalent to:
nd in _initialize()
Later used to compute idf.

Meaning:
Number of documents containing the term.
Not total term occurrences across corpus.
One row per distinct term.


## corpus_stats

Purpose:
Stores global aggregates needed for scoring.

Equivalent to:
self.corpus_size

```sql
CREATE INDEX IF NOT EXISTS passage_passage_tsv_id_null_idx ON passage(id ASC) WHERE passage_tsv IS NULL;
CREATE INDEX IF NOT EXISTS passage_passage_tsv_id_not_null_idx ON passage(id ASC) WHERE passage_tsv IS NOT NULL;
```

```sql
SELECT COUNT(id) FROM passage WHERE passage_tsv IS NOT NULL;
```


self.avgdl

Meaning:
total_docs → number of indexed documents (This is length in token)

```sql
SELECT count(id) FROM passage WHERE passage_tsv IS NOT NULL;
```

avgdl → average document length (in tokens).
Derived from sum(doc_len) / total_docs.

```sql
SELECT sum(passage_tsv_len) FROM passage WHERE passage_tsv IS NOT NULL;
```


```sql
CREATE OR REPLACE FUNCTION get_tsvector_total_occurrences(p_tsv tsvector) 
RETURNS integer LANGUAGE sql IMMUTABLE AS $$
    SELECT count(pos)::integer 
    FROM unnest(p_tsv) AS t(lexeme, positions),
         unnest(positions) AS pos;
$$;
```

```sql
SELECT count(*) AS doclen
FROM unnest(
        string_to_array(
            (SELECT passage_tsv::text FROM passage LIMIT 1),
            ' '
        )
     ) AS term,
     unnest(
        string_to_array(
            split_part(term, ':', 2),
            ','
        )
     ) AS pos;
```


```sql
CREATE FUNCTION tsv_doclen(tsv TSVECTOR)
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
```

```sql
SELECT to_tsvector('english', passage)::TEXT FROM passage LIMIT 10;
```

```sql
UPDATE passage SET passage_tsv = to_tsvector('english', passage)
WHERE id IN (SELECT id FROM passage WHERE passage_tsv IS NULL LIMIT 10);
```

```sql
BEGIN;
SET LOCAL bm25.reset = 'true';
UPDATE passage SET pid = pid
WHERE id IN (SELECT id FROM passage WHERE passage_tsv IS NULL LIMIT 10);
COMMIT;
```



```sql
ALTER TABLE passage ADD COLUMN passage_tsv_len INT;
```


Key distinctions clarified

Per-document term frequency (TF)
→ comes from tsvector positions
→ equivalent to frequencies in _initialize()

Document frequency (DF)
→ comes from counting documents containing a term
→ equivalent to nd

Distinct term count
→ COUNT(*) FROM term_stats
→ equals number of unique lexemes in corpus
→ corresponds to len(self.idf)




```sql
UPDATE "passage" AS t
SET "passage" = t."passage"
FROM (VALUES 
  ('0004cdbd-015f-40a7-acf2-dca408d9a772'),
  ('0004d3a7-10dc-4ab3-aa4b-4521f8bd29fb'),
  ('0004f6cd-1e71-4b9e-8a4e-2cefbd1be226'),
  ('0004f9fd-b84f-4622-a51c-a15e52df437c'),
  ('0004fd5e-e9cf-46f5-9983-5825460c1681'),
  ('00050524-db3a-4db9-9079-67c77a3db44c'),
  ('00051bcb-9dbf-4193-9461-809c651ecf1f'),
  ('00051dec-66fd-4a82-9e88-26b6667d5a8d'),
  ('0005219a-573b-49ac-b739-b0ca96fa5ddc'),
  ('00052621-9f6b-4d7d-8101-97e7fc9197fd')
) AS v("id")
WHERE t."id" = v."id"::UUID;
```



# spiration

```sql
SELECT id,
       bm25_score(...) AS score
FROM passage
WHERE passage_tsv @@ plainto_tsquery('english', 'february weather')
ORDER BY score DESC
LIMIT 10;
```


```sql
CREATE FUNCTION bm25_score(...)
RETURNS FLOAT AS ...
```

```sql
bm25_idf(df INT, N INT)
RETURNS FLOAT
```

```bash
ln((N - df + 0.5) / (df + 0.5))
```



# Debugging `BM25_Okapi_rank()`

```sql
SELECT id
FROM passage
WHERE passage_tsv @@ plainto_tsquery('english', 'february weather')
LIMIT 10;
```

```sql
                   id
----------------------------------------
  0205baa5-3b8b-4e4d-b832-3fd3eb02bb7a
  027c5538-3ff2-4156-bf96-a130d2a13282
  05604524-bfad-405f-8033-8e4269ecb36c
  097943c7-cee0-41ad-9591-c035e53439c0
  099a55f0-c370-469d-8867-62ddc3938204
  0c51ec83-535a-4338-90bb-89f27c821210
  12d1d285-3275-4c71-b6d9-e027e115dc76
  134b1931-da4b-4eb1-922d-1e2d5a746e83
  1355a719-a49e-4a78-a191-f8f6fa1e63a4
  15504cf5-bf78-475b-978d-fc961beeb2ed
(10 rows)
```

This is the candidate document `doc`:

```sql
SELECT
    passage_tsv AS tsv, passage_tsv_len::FLOAT AS dl
FROM passage
WHERE id = '0205baa5-3b8b-4e4d-b832-3fd3eb02bb7a';
```

```sql
      tsv                                                                                                                                                     | dl
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+-----
  '3':26 '4':27 'assur':50 'best':52 'caus':34 'chanc':53 'day':28 'decemb':42 'delay':36 'even':9 'expect':24 'fair':47 'februari':43 'flyer':2 'freez':21 'make':16 'nocturn':4 'rain':19 'releas':6,31,37 'rememb':1 'sure':17 'surviv':55 'temperatur':22 'usual':11 'wait':45 'watch':12 'weather':14,48 | 30
(1 row)
```

Corpus `stats`:

```sql
SELECT
    count(*) AS n,
    avg(passage_tsv_len) AS avgdl
FROM passage
WHERE passage_tsv IS NOT NULL;
```

```sql
     n    |         avgdl
----------+------------------------
  1476385 | 29.050345946348682762
(1 row)
```

```sql
SELECT extract_passage_terms(to_tsvector('february weather'));
```

```sql
  extract_passage_terms
-------------------------
  februari
  weather
(2 rows)
```

```sql
SELECT array_agg(term) AS terms
FROM unnest(ARRAY['februari', 'weather']) AS term;
```


```sql
SELECT t.term, t.ord, t.idf::FLOAT
FROM (SELECT ARRAY['februari', 'weather']::STRING[] AS terms),
    unnest(
        coalesce(ARRAY['februari', 'weather']::STRING[], ARRAY[]::STRING[]), 
        coalesce(BM25_Okapi_IDF(ARRAY['februari', 'weather']::STRING[]), ARRAY[]::FLOAT[])
    ) WITH ORDINALITY AS t(term, idf, ord);
```

`q` is now:

```sql
    term   | ord |        idf
-----------+-----+--------------------
  februari |   1 | 5.327838513858024
  weather  |   2 | 5.482578050454234
(2 rows)
```

Now, the candidate documewnts `doc_tf`:

```sql
SELECT unnest(
    extract_passage_terms_freq(
        (
            SELECT
                passage_tsv AS tsv
            FROM passage
            WHERE id = '0205baa5-3b8b-4e4d-b832-3fd3eb02bb7a'
        )
    ) AS (term, tf)
);
```

```sql
     term    | tf
-------------+-----
  3          |  1
  4          |  1
  assur      |  1
  best       |  1
  caus       |  1
  chanc      |  1
  day        |  1
  decemb     |  1
  delay      |  1
  even       |  1
  expect     |  1
  fair       |  1
  februari   |  1
  flyer      |  1
  freez      |  1
  make       |  1
  nocturn    |  1
  rain       |  1
  releas     |  3
  rememb     |  1
  sure       |  1
  surviv     |  1
  temperatur |  1
  usual      |  1
  wait       |  1
  watch      |  1
  weather    |  2
(27 rows)
```

Finally:

```sql
SELECT
    coalesce(
        sum(
            q.idf * (
                (doc_tf.tf::FLOAT * (1.2::FLOAT + 1.0))
                /
                (doc_tf.tf::FLOAT + 1.2::FLOAT * (1.0 - 0.75::FLOAT + 0.75::FLOAT * (doc.dl / stats.avgdl::FLOAT)))
            )
        ),
        0
    ) AS rank
FROM (
        VALUES 
            ('februari', 1, 5.327838513858024::FLOAT),
            ('weather', 2, 5.482578050454234::FLOAT)
    ) AS q(term, ord, idf)
JOIN (
    SELECT
        passage_tsv AS tsv, passage_tsv_len::FLOAT AS dl
    FROM passage
    WHERE id = '0205baa5-3b8b-4e4d-b832-3fd3eb02bb7a'
) AS doc ON true
JOIN (
    VALUES
        (1476385, 29.050345946348682762::FLOAT)
) AS stats(n,avgdl) ON true
LEFT JOIN (
    VALUES 
        ('3', 1), ('4', 1), ('assur', 1), ('best', 1), ('caus', 1), 
        ('chanc', 1), ('day', 1), ('decemb', 1), ('delay', 1), ('even', 1), 
        ('expect', 1), ('fair', 1), ('februari', 1), ('flyer', 1), ('freez', 1), 
        ('make', 1), ('nocturn', 1), ('rain', 1), ('releas', 3), ('rememb', 1), 
        ('sure', 1), ('surviv', 1), ('temperatur', 1), ('usual', 1), ('wait', 1), 
        ('watch', 1), ('weather', 2)
) AS doc_tf(term, tf)
ON doc_tf.term = q.term
WHERE coalesce(doc_tf.tf, 0) > 0;
```



The final stored function:

```sql
SELECT BM25_Okapi_rank(
    '0205baa5-3b8b-4e4d-b832-3fd3eb02bb7a',
    'february weather',
    1.2, 0.75
) AS rank;
```
