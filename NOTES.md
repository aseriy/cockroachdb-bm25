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
    freq INT DEFAULT 0
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
WHERE id IN (
    SELECT id FROM passage
        WHERE passage_tsv IS NULL
        AND to_tsvector('english', passage) @@ to_tsquery('english', 'use')
    LIMIT 1
);
COMMIT;
```

```sql
BEGIN;
SET LOCAL bm25.reset = 'true';
UPDATE passage SET pid = pid
WHERE id IN (
    SELECT id FROM passage
        WHERE passage_tsv IS NULL
    ORDER BY random()
    LIMIT 100
);
COMMIT;
```


```sql
BEGIN;
SET LOCAL bm25.reset = 'true';
UPDATE passage SET pid = pid
WHERE id IN (
    SELECT id FROM passage
        WHERE passage_tsv IS NULL
        AND to_tsvector('english', passage) @@ to_tsquery('english', 'use')
    ORDER BY id DESC
    LIMIT 1
);
COMMIT;
```

```sql
SELECT passage_tsv, passage_tsv_jsonb FROM passage WHERE passage_tsv IS NOT NULL; 
```

```sql
SELECT id, (passage_tsv_jsonb->>'dl')::INT AS doc_len FROM passage WHERE passage_tsv IS NOT NULL;
SELECT jsonb_object_keys(passage_tsv_jsonb->'tf') AS term
    FROM passage WHERE passage_tsv IS NOT NULL ORDER BY term;
```


```sql
DELETE FROM _tsv_bmw_131_3;
DELETE FROM _tsv_term_tc_131_3;
DELETE FROM _tsv_terms_131_3;
DELETE FROM _tsv_corpus;
UPDATE passage SET passage_tsv = NULL WHERE passage_tsv IS NOT NULL;
```

```sql
SELECT passage_tsv_jsonb FROM passage WHERE passage_tsv IS NOT NULL;
SELECT * FROM _tsv_term_tc_131_3;
SELECT*  FROM _tsv_terms_131_3;
SELECT * FROM _tsv_bmw_131_3;
SELECT * FROM _tsv_corpus;
```



NULLify

```sql
CREATE OR REPLACE PROCEDURE null_out_passage_tsv(batch_size INT DEFAULT 1000)
LANGUAGE PLpgSQL
AS $$
DECLARE
    rows_updated_c INT := 0;
BEGIN
    LOOP
        WITH rows_updated AS (
            WITH batch AS (
                SELECT id
                FROM passage
                WHERE passage_tsv IS NOT NULL
                ORDER BY id
                LIMIT batch_size
            )
            UPDATE passage
            SET passage_tsv = NULL
            FROM batch
            WHERE passage.id = batch.id
            RETURNING 1
        )
        SELECT count(*) INTO rows_updated_c
        FROM rows_updated;

        RAISE NOTICE 'Updated % rows', rows_updated_c;

        IF rows_updated_c < 1 THEN
            RAISE NOTICE 'Done.';
            EXIT;
        END IF;
    END LOOP;
END;
$$;
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



# Inspiration

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




```sql
SELECT * FROM BM25_Okapi_rank(
    'february weather',
    10,
    1.2, 0.75
);
```


```sql
SELECT * FROM BM25_candidates('february weather', 10);
```


```sql
SELECT passage FROM passage
    WHERE id in (
        (SELECT pk FROM BM25_Okapi_rank(
            'why not diesel cars',
            10, 1.2, 0.75
        ))
    );
```

```sql
SELECT r.score, p.passage
FROM passage AS p
INNER JOIN (
    SELECT pk, score 
    FROM BM25_Okapi_rank(
        'why not diesel cars'
        , 10, 1.2, 0.75)
) AS r ON p.id = r.pk
ORDER BY r.score DESC;
```

```sql
SELECT r.score, p.passage
FROM passage AS p
INNER JOIN (
    SELECT pk, score
    FROM BM25_Okapi_rank(
        'why not diesel cars',
        20
    )
) AS r ON p.id = r.pk
ORDER BY r.score DESC;
```



# Corpus Tracking

```sql
CREATE TABLE IF NOT EXISTS _tsv_corpus (
    table_name STRING,
    column_name STRING,
    n INT NOT NULL DEFAULT 0,
    total INT NOT NULL DEFAULT 0,
    avgdl FLOAT AS (
        CASE
            WHEN n = 0 THEN NULL
            ELSE total::FLOAT / n::FLOAT
        END
    ) STORED,
    PRIMARY KEY (table_name, column_name)
);
```


```sql
INSERT INTO _tsv_corpus (table_name,column_name,n,total) VALUES (
    'passage',
    'passage',
    (SELECT count(*) FROM passage WHERE passage_tsv IS NOT NULL),
    (SELECT sum(passage_tsv_len) FROM passage WHERE passage_tsv IS NOT NULL)
);
```

```sql
UPDATE _tsv_corpus SET
    n = (SELECT count(*) FROM passage WHERE passage_tsv IS NOT NULL),
    total = (SELECT sum(passage_tsv_len) FROM passage WHERE passage_tsv IS NOT NULL)
WHERE table_name ='passage' AND column_name = 'passage';
```



# Test corpus stats for DELETE and UPDATE

```sql
INSERT INTO passage (pid, passage, spans, docid) VALUES (
    'msmarco_passage_XX_000000000',
    'Some text to be deleted later',
    '(73,88),(89,108),(109,130),(131,149),(150,171),(172,195),(196,215),(216,234),(235,309)',
    'msmarco_doc_YY_zzzzzzzzzzz'
);
```

```sql
SELECT to_tsvector('Some text to be deleted later');
```

```sql
          to_tsvector
--------------------------------
  'delet':5 'later':6 'text':2
```

```sql
SELECT * FROM _tsv_terms
WHERE term IN ('delet', 'later', 'text')
AND table_name='passage' AND column_name='passage';
```

```sql
  term  | freq
--------+--------
  later | 27587
  text  | 15688
  delet |  4888

  term  | freq
--------+--------
  later | 27588
  text  | 15689
  delet |  4889
```

```sql
SELECT * FROM passage WHERE pid = 'msmarco_passage_XX_000000000';
```

```sql
SELECT to_tsvector('Now that RKO is behind us and we’re ready to crush FY27, your FY27 comp documents are now in your inbox. Please review the following important notes:');
```

```sql
                                                                            to_tsvector
-------------------------------------------------------------------------------------------------------------------------------------------------------------------
  'behind':5 'comp':16 'crush':12 'document':17 'follow':26 'fy27':13,15 'import':27 'inbox':22 'note':28 'pleas':23 're':9 'readi':10 'review':24 'rko':3 'us':6
```

```sql
SELECT * FROM _tsv_terms
WHERE term IN (
    'behind', 'comp', 'crush', 'document', 'follow', 'fy27', 'import', 'inbox',
    'note', 'pleas', 're', 'readi', 'review', 'rko', 'us')
AND table_name='passage' AND column_name='passage';
```

```sql
  term  | freq
--------+--------
  later | 27587
  text  | 15688
  delet |  4888

  term  | freq
--------+--------
  later | 27588
  text  | 15689
  delet |  4889
```

```sql
UPDATE passage SET passage = 
    'Now that RKO is behind us and we’re ready to crush FY27, your FY27 comp documents are now in your inbox. Please review the following important notes:'
    WHERE pid = 'msmarco_passage_XX_000000000';
```


```sql
DELETE FROM passage WHERE pid = 'msmarco_passage_XX_000000000';
```




```sql
SELECT extract_passage_terms((SELECT passage_tsv FROM passage WHERE passage_tsv IS NOT NULL LIMIT 1));
SELECT unnest(extract_passage_terms_freq((SELECT passage_tsv FROM passage WHERE passage_tsv IS NOT NULL LIMIT 1))) AS tf;
```


```sql
CREATE TABLE passage (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    pid STRING NOT NULL,
    passage STRING NOT NULL,
    spans STRING NOT NULL,
    docid STRING NOT NULL,
    passage_vector VECTOR(384) NULL,
    passage_openai VECTOR(1536) NULL,
    passage_tsv_len INT8 NULL,
    passage_tsv TSVECTOR NULL,
    CONSTRAINT passage_pkey PRIMARY KEY (id ASC),
    UNIQUE INDEX passage_pid_key (pid ASC),
    VECTOR INDEX passage_passage_vector_idx (passage_vector vector_cosine_ops) WHERE passage_vector IS NOT NULL,
    INDEX passage_passage_vector_id_null_idx (id ASC) WHERE passage_vector IS NULL,
    INDEX passage_passage_vector_id_not_null_idx (id ASC) WHERE passage_vector IS NOT NULL,
    VECTOR INDEX passage_passage_openai_idx (passage_openai vector_cosine_ops) WHERE passage_openai IS NOT NULL,
    INDEX passage_passage_openai_id_null_idx (id ASC) WHERE passage_openai IS NULL,
    INDEX passage_passage_openai_id_not_null_idx (id ASC) WHERE passage_openai IS NOT NULL,
    INVERTED INDEX passage_tsv_idx (passage_tsv),
    INDEX passage_passage_tsv_id_null_idx (id ASC) WHERE passage_tsv IS NULL,
    INDEX passage_passage_tsv_id_not_null_idx (id ASC) WHERE passage_tsv IS NOT NULL
) LOCALITY REGIONAL BY TABLE IN PRIMARY REGION;
```



Add a new column to `_tsv_terms` to track Max term contribution (normalized)

```sql
ALTER TABLE _tsv_terms ADD COLUMN upper_bound FLOAT DEFAULT 0;
```

```sql
CREATE TABLE _tsv_term_tc_131_3 (
    doc_id UUID NOT NULL,
    term STRING NOT NULL,
    tc FLOAT8,
    CONSTRAINT fk_doc_id
        FOREIGN KEY (doc_id)
        REFERENCES passage(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_term
        FOREIGN KEY (term)
        REFERENCES _tsv_terms_131_3(term)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX (doc_id),
    INDEX (term)
);
```

Table-Column to OIDs

```sql
SELECT                                                  
    c.oid AS table_oid,                                 
    a.attnum AS column_oid                              
FROM pg_catalog.pg_class c                              
JOIN pg_catalog.pg_attribute a ON c.oid = a.attrelid    
WHERE c.relname = 'passage'                             
AND a.attname = 'passage';                            
```

```sql
SELECT
    p.id AS doc_id,
    f.term,
    f.freq::FLOAT / p.passage_tsv_len::FLOAT AS tc
FROM (
    SELECT id, passage_tsv, passage_tsv_len
    FROM passage
    LIMIT 2
) AS p
CROSS JOIN extract_passage_terms_freq(p.passage_tsv) AS f;
```

First batch:

```sql
INSERT INTO _tsv_term_tc_131_3 (doc_id, term, tc)
SELECT
    p.id,
    f.term,
    f.freq::FLOAT8 / p.passage_tsv_len::FLOAT8 AS tc
FROM (
    SELECT id, passage_tsv, passage_tsv_len
    FROM passage
    WHERE id > '00000000-0000-0000-0000-000000000000'
    ORDER BY id
    LIMIT 100
) AS p
CROSS JOIN extract_passage_terms_freq(p.passage_tsv) AS f;
```

```sql
SELECT id, passage
FROM passage                                            
WHERE passage_tsv @@ plainto_tsquery('fenston'); 
```

```sql
UPDATE passage SET passage='' WHERE id = '00036188-31d9-4486-88af-9693485066a1';
UPDATE passage SET passage='xxx' WHERE id = '00036188-31d9-4486-88af-9693485066a1';
```


```sql
ALTER TABLE passage
ADD COLUMN passage_tsv TSVECTOR DEFAULT NULL;
ALTER TABLE passage
ADD COLUMN passage_tsv_jsonb JSONB DEFAULT NULL;
```



```sql
CREATE TABLE _tsv_bmw_131_3 (
    term STRING NOT NULL,
    doc_id_first UUID NOT NULL,
    doc_id_last UUID NOT NULL,
    doc_count INT NOT NULL DEFAULT 0,
    ub FLOAT8 NOT NULL,
    CONSTRAINT _tsv_bmw_131_3_pkey PRIMARY KEY (term, doc_id_first),
    CONSTRAINT _tsv_bmw_131_3_term_fkey
        FOREIGN KEY (term) REFERENCES _tsv_terms_131_3(term)
);
```



# Block-Max WAND (BMW) Execution Logic

## 1. The Pivot Selection Logic
The goal of the Pivot Selection is to identify the earliest possible document ID (**Pivot ID**) that could potentially enter the Top-K results based on **Global Upper Bounds (UBs)**.

### The Algorithm:
1. **Sort Cursors**: Sort all query terms ($t_1, t_2, ... t_n$) by their current `docID` in ascending order.
2. **Accumulate Global Bounds**: Iterate through the sorted terms and maintain a running sum of their **Global Max Scores**.
   - $Sum\_Global\_UB = \sum UB_{global}(t_i)$
3. **Identify the Pivot**: The process stops at the term $t_p$ where the $Sum\_Global\_UB$ first exceeds the current threshold ($\theta$).
   - **Pivot Term**: $t_p$
   - **Pivot ID**: The current `docID` of $t_p$.

### Logic:
Any document with an ID smaller than the **Pivot ID** is mathematically incapable of beating the threshold $\theta$, even if it contained every term preceding the pivot.

---

## 2. The Immediate Pivot (Initial State)
At the start of a query, the threshold ($\theta$) is initialized to **0**. This creates a "Warm-up" phase for the algorithm.

### Execution Flow at $\theta = 0$:
1. **Instant Satisfaction**: The very first term in the sorted list will have a $UB_{global} > 0$.
2. **Pivot Assignment**:
   - The first term becomes the **Pivot Term**.
   - Its current `docID` becomes the **Pivot ID**.
3. **Forced Deep Move**: Since the threshold is zero, both Global and Block-level checks will pass. The algorithm must perform a **Deep Move** (fully score the document).
4. **Threshold Inflation**:
   - Scored documents are added to a **Min-Heap** of size $K$.
   - Once the heap is full ($K$ documents found), $\theta$ is updated to the score of the $K$-th best document.
   - As $\theta$ increases, the **Pivot Selection Logic** begins to skip larger segments of the index.




```bash
while true; do
  rows=$(cockroach sql \
    --url postgresql://alex:201QGmH4VKAPh13jO2smJw@fleet-cuscus-11142.jxf.cockroachlabs.cloud:26257/nextgenreporting?sslmode=verify-full \
    --format=csv \
    --execute="
WITH batch AS (
    SELECT id
    FROM passage
    WHERE passage_tsv IS NOT NULL
    ORDER BY id
    LIMIT 100
),
upd AS (
    UPDATE passage
    SET passage_tsv = NULL
    FROM batch
    WHERE passage.id = batch.id
    RETURNING 1
)
SELECT count(*) AS rows_updated
FROM upd;
" | tail -n 1)

  echo "updated: $rows"

  if [ "$rows" = "0" ]; then
    break
  fi
done
```



```bash
while true; do
  rows=$(cockroach sql \
    --url "postgresql://alex:201QGmH4VKAPh13jO2smJw@fleet-cuscus-11142.jxf.cockroachlabs.cloud:26257/nextgenreporting?sslmode=verify-full" \
    --format=csv \
    --execute="
WITH batch AS (
    SELECT doc_id, term
    FROM \"_tsv_term_tc_131_3\"
    LIMIT 10000
),
del AS (
    DELETE FROM \"_tsv_term_tc_131_3\"
    WHERE (doc_id, term) IN (SELECT doc_id, term FROM batch)
    RETURNING 1
)
SELECT count(*) AS rows_deleted
FROM del;
" | tail -n 1)

  echo "deleted: $rows"

  if [ "$rows" = "0" ] || [ -z "$rows" ]; then
    break
  fi
done
```

```bash
while true; do
  rows=$(cockroach sql \
    --url "postgresql://alex:201QGmH4VKAPh13jO2smJw@fleet-cuscus-11142.jxf.cockroachlabs.cloud:26257/nextgenreporting?sslmode=verify-full" \
    --format=csv \
    --execute="
WITH batch AS (
    SELECT term
    FROM \"_tsv_terms_131_3\"
    LIMIT 10000
),
del AS (
    DELETE FROM \"_tsv_terms_131_3\"
    WHERE term IN (SELECT term FROM batch)
    RETURNING 1
)
SELECT count(*) AS rows_deleted
FROM del;
" | tail -n 1)

  echo "deleted: $rows"

  if [ "$rows" = "0" ] || [ -z "$rows" ]; then
    break
  fi
done
```


```sql
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0706c356-bcce-4945-9c87-452f91cd03ef'), 'oil', '0706c356-bcce-4945-9c87-452f91cd03ef', 0.07142857142857142);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0706f9fb-e6cb-42e3-b8a4-b86bcdd2a7e7'), 'oil', '0706f9fb-e6cb-42e3-b8a4-b86bcdd2a7e7', 0.029411764705882353);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '070ac0ce-0c63-45bd-afa7-4de7c248f003'), 'oil', '070ac0ce-0c63-45bd-afa7-4de7c248f003', 0.017241379310344827);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '070cdcb0-b96c-4ca8-b1ed-b3fb22e965e5'), 'oil', '070cdcb0-b96c-4ca8-b1ed-b3fb22e965e5', 0.058823529411764705);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '070e5248-8b85-443a-b818-f2f9e45b717c'), 'oil', '070e5248-8b85-443a-b818-f2f9e45b717c', 0.07692307692307693);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0710cf1a-41e8-4244-ae95-88ef30204aad'), 'oil', '0710cf1a-41e8-4244-ae95-88ef30204aad', 0.041666666666666664);


SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0710f7ec-d4f0-4e10-95e1-9f0e931bbffa'), 'oil', '0710f7ec-d4f0-4e10-95e1-9f0e931bbffa', 0.08571428571428572);


SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '071cf784-38c5-4e61-a3b7-cd674370317d'), 'oil', '071cf784-38c5-4e61-a3b7-cd674370317d', 0.043478260869565216);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '07217a59-62b7-4ad2-8d3e-3249e1305b61'), 'oil', '07217a59-62b7-4ad2-8d3e-3249e1305b61', 0.025);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '072326ba-9735-4772-b0fb-3bed54eedf8d'), 'oil', '072326ba-9735-4772-b0fb-3bed54eedf8d', 0.10714285714285714);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '072442b5-413d-44f4-a18d-36007d358a2c'), 'oil', '072442b5-413d-44f4-a18d-36007d358a2c', 0.029411764705882353);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0731683b-c0f6-4a44-9c2d-77061e249ba1'), 'oil', '0731683b-c0f6-4a44-9c2d-77061e249ba1', 0.05405405405405406);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0735f6f2-a1d9-49fa-9686-11dde2941c46'), 'oil', '0735f6f2-a1d9-49fa-9686-11dde2941c46', 0.03125);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '07378a77-aa66-4804-93a1-6259177bce26'), 'oil', '07378a77-aa66-4804-93a1-6259177bce26', 0.02631578947368421);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '07398bcc-d9d3-49a6-b609-fc4d770728d5'), 'oil', '07398bcc-d9d3-49a6-b609-fc4d770728d5', 0.06666666666666667);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '073a9a3f-8fe2-45d7-a878-7596b1c26558'), 'oil', '073a9a3f-8fe2-45d7-a878-7596b1c26558', 0.02702702702702703);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '073eded4-d7c9-4937-b208-358f21232c48'), 'oil', '073eded4-d7c9-4937-b208-358f21232c48', 0.02702702702702703);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '07413ea8-acf1-4b8b-932a-b0cfb2321d60'), 'oil', '07413ea8-acf1-4b8b-932a-b0cfb2321d60', 0.037037037037037035);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074437e8-6f30-4855-b2ca-9c18ca475d92'), 'oil', '074437e8-6f30-4855-b2ca-9c18ca475d92', 0.04);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074534ca-d2d5-4ebc-b024-4d16d5a25245'), 'oil', '074534ca-d2d5-4ebc-b024-4d16d5a25245', 0.125);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0745887e-7444-4728-86b3-bebb629c5382'), 'oil', '0745887e-7444-4728-86b3-bebb629c5382', 0.03571428571428571);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0745e347-3c25-417f-a8dc-5406c7642961'), 'oil', '0745e347-3c25-417f-a8dc-5406c7642961', 0.09375);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074882b5-31cd-4709-b6bc-332bf0b69762'), 'oil', '074882b5-31cd-4709-b6bc-332bf0b69762', 0.05555555555555555);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0748eb99-7a72-41ce-9c35-957f9de63bc4'), 'oil', '0748eb99-7a72-41ce-9c35-957f9de63bc4', 0.030303030303030304);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074a288b-85d7-4788-8a2c-aa97d19ffba0'), 'oil', '074a288b-85d7-4788-8a2c-aa97d19ffba0', 0.05263157894736842);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074a4549-baea-4c45-9599-f3221ca73446'), 'oil', '074a4549-baea-4c45-9599-f3221ca73446', 0.03225806451612903);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074a6fa0-8d1b-4f88-95fa-73063cc7639e'), 'oil', '074a6fa0-8d1b-4f88-95fa-73063cc7639e', 0.02857142857142857);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074d44fe-f8c2-48ef-b055-392647b48853'), 'oil', '074d44fe-f8c2-48ef-b055-392647b48853', 0.047619047619047616);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '074e9d77-3845-49a7-a78e-6d180220a5f1'), 'oil', '074e9d77-3845-49a7-a78e-6d180220a5f1', 0.08333333333333333);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '075305b4-0253-4a1c-84c9-0eafb06dfcd5'), 'oil', '075305b4-0253-4a1c-84c9-0eafb06dfcd5', 0.030303030303030304);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0759fd81-a36a-4e8c-9a22-4a5c7164d80c'), 'oil', '0759fd81-a36a-4e8c-9a22-4a5c7164d80c', 0.11538461538461539);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '075ba9fe-1dda-4c83-9b76-ce011b7ffa1a'), 'oil', '075ba9fe-1dda-4c83-9b76-ce011b7ffa1a', 0.13333333333333333);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '07635ee2-e6a1-4902-8ce0-40d6174c176f'), 'oil', '07635ee2-e6a1-4902-8ce0-40d6174c176f', 0.03225806451612903);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '076700bc-fa38-49a4-b64d-62d5878050fb'), 'oil', '076700bc-fa38-49a4-b64d-62d5878050fb', 0.10810810810810811);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0769d1aa-5481-4e55-bac6-1bee499b7f2a'), 'oil', '0769d1aa-5481-4e55-bac6-1bee499b7f2a', 0.05660377358490566);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '076e4e79-cf3f-4d4e-9f30-efe7b1478bd9'), 'oil', '076e4e79-cf3f-4d4e-9f30-efe7b1478bd9', 0.06451612903225806);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '076ee72f-d848-4eda-b43e-81d8462c5a0e'), 'oil', '076ee72f-d848-4eda-b43e-81d8462c5a0e', 0.08333333333333333);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '077b7e89-0602-4db9-9b2b-591d549a8060'), 'oil', '077b7e89-0602-4db9-9b2b-591d549a8060', 0.047619047619047616);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '077cfb52-cc9b-48cc-bddc-8b2c5cd9e76e'), 'oil', '077cfb52-cc9b-48cc-bddc-8b2c5cd9e76e', 0.1111111111111111);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '077d4c75-48ff-41c6-b1b5-99c0db9ec369'), 'oil', '077d4c75-48ff-41c6-b1b5-99c0db9ec369', 0.03333333333333333);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '077e1252-608e-4a81-83d9-50e43639c419'), 'oil', '077e1252-608e-4a81-83d9-50e43639c419', 0.02564102564102564);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '077e7d38-eef6-4ff1-96e2-f31825ea1928'), 'oil', '077e7d38-eef6-4ff1-96e2-f31825ea1928', 0.02857142857142857);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '078037a8-25b2-4a39-a8d1-eb6121e81567'), 'oil', '078037a8-25b2-4a39-a8d1-eb6121e81567', 0.041666666666666664);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0784b9e4-d9f6-4f9e-807e-67742a24be40'), 'oil', '0784b9e4-d9f6-4f9e-807e-67742a24be40', 0.02631578947368421);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0788fd9b-9df4-43b3-89de-568f1bc80211'), 'oil', '0788fd9b-9df4-43b3-89de-568f1bc80211', 0.027777777777777776);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '078a3f96-58fb-4191-9bea-92154fd0e469'), 'oil', '078a3f96-58fb-4191-9bea-92154fd0e469', 0.037037037037037035);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '078cde8f-60d3-4269-b559-51275349bc50'), 'oil', '078cde8f-60d3-4269-b559-51275349bc50', 0.038461538461538464);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '078d430b-4122-47e4-9d19-7e4d7f061d46'), 'oil', '078d430b-4122-47e4-9d19-7e4d7f061d46', 0.26666666666666666);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '07929310-38a8-4c2d-835f-0959b2422d04'), 'oil', '07929310-38a8-4c2d-835f-0959b2422d04', 0.030303030303030304);
SELECT BM25_BMW_add_to_block(BM25_BMW_find_block('oil', '0793df5a-40d3-496b-b18a-e39fca28374c'), 'oil', '0793df5a-40d3-496b-b18a-e39fca28374c', 0.02631578947368421);
```



Run `reset` on auto-pilot:

```bash
docker run --rm -d --name rank-reset -v $HOME/.postgresql:/root/.postgresql:ro -v $(pwd)/logs:/logs rank-reset -u <url>> -t passage -i passage -o passage_tsv -v -b 50 -w 1 -F 
```
