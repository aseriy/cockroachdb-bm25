CREATE TABLE IF NOT EXISTS _tsv_terms (
    table_name STRING NOT NULL,
    column_name STRING NOT NULL,
    term STRING NOT NULL,
    freq INT DEFAULT 0,
    PRIMARY KEY (table_name, column_name, term) USING HASH WITH (bucket_count=16)
);

CREATE TABLE IF NOT EXISTS _tsv_corpus (
    table_name STRING NOT NULL,
    column_name STRING NOT NULL,
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

