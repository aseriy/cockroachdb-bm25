# cockroachdb-bm25

Yes. In CockroachDB, do it in two steps: **add a STORED computed column**, then **add an inverted index** on that column. ([Cockroach Labs][1])

### 1) Add the computed `TSVECTOR` column

```sql
ALTER TABLE passage
ADD COLUMN passage_tsv TSVECTOR
AS (to_tsvector('english', passage)) STORED;
```

* `STORED` means it’s computed on INSERT/UPDATE and persisted. ([Cockroach Labs][1])

### 2) Index it (inverted index)

```sql
CREATE INVERTED INDEX passage_tsv_idx
ON nextgenreporting.public.passage (passage_tsv);
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

1️⃣ doc_stats

Purpose:
Stores per-document term count (token count).

Equivalent to:
self.doc_len in the BM25 class.

Meaning:
Total number of lexeme occurrences in the document.
Derived from number of positions in tsvector.

2️⃣ term_stats

Purpose:
Stores document frequency per term.

```sql
SELECT id, token
FROM passage,
     LATERAL unnest(string_to_array(passage_tsv::TEXT, ' ')) AS token
LIMIT 10;
```

```sql
SELECT
    id,
    trim(both '''' FROM split_part(token, ':', 1)) AS term,
    split_part(token, ':', 2) AS positions_raw,
    array_length(
        string_to_array(split_part(token, ':', 2), ','),
        1
    ) AS freq
FROM passage,
     LATERAL unnest(string_to_array(passage_tsv::TEXT, ' ')) AS token
WHERE id = '00002c3d-6cd3-4cc5-a0a1-879812feca07';
```

```sql
SELECT
    trim(both '''' FROM split_part(token, ':', 1)) AS term,
    array_length(
        string_to_array(split_part(token, ':', 2), ','),
        1
    ) AS freq
FROM passage,
     LATERAL unnest(string_to_array(passage_tsv::TEXT, ' ')) AS token
WHERE id = $1;
```

```sql
CREATE TABLE IF NOT EXISTS passage_passage_tsv_terms (
    term STRING PRIMARY KEY USING HASH WITH (bucket_count=16),
    freq INT
);
```

RESET tracking table:

```sql
CREATE TABLE IF NOT EXISTS passage_passage_tsv_reset (
    id UUID PRIMARY KEY,
    done TIMESTAMP
)
```



```sql
INSERT INTO passage_passage_tsv_terms (term, freq)
SELECT term, 1
FROM (
    SELECT
        trim(both '\''' FROM split_part(token, ':', 1)) AS term
    FROM passage,
         LATERAL unnest(string_to_array(passage_tsv::TEXT, ' ')) AS token
    WHERE id = $1
) AS terms
ON CONFLICT (term)
DO UPDATE SET freq = passage_passage_tsv_terms.freq + 1;
```

Lock the table for write while RESET is running

```sql
BEGIN;
-- Set the session to READ COMMITTED
SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED;
SELECT 1 FROM passage WHERE 1=1 FOR SHARE;
-- Run your read-heavy proc here
COMMIT;
```

To reset:

```sql
UPDATE passage_passage_tsv_terms SET freq=0;
```

```sql
BEGIN;
SET LOCAL bm25.reset = 'true';
UPDATE passage SET pid = 'msmarco_passage_00_100000577' WHERE id='9c0f4b37-beb6-40d4-8347-32295173211f';
COMMIT;
```

```sql
SELECT * FROM passage_passage_tsv_terms ORDER BY term; 
DROP TRIGGER sync_passage_terms ON passage;
```


```sql
SELECT * FROM passage_passage_tsv_terms ORDER by term;
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

3️⃣ corpus_stats

Purpose:
Stores global aggregates needed for scoring.

Equivalent to:
self.corpus_size

```sql
SELECT COUNT(id) FROM passage WHERE passage_tsv IS NOT NULL;
```

self.avgdl

Meaning:
total_docs → number of indexed documents.
avgdl → average document length (in tokens).
Derived from sum(doc_len) / total_docs.


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




