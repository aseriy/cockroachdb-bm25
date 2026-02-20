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
    freq INT
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
