CREATE OR REPLACE FUNCTION extract_passage_terms(tsv TSVECTOR)
RETURNS TABLE(term text)
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT
        trim(both '''' FROM split_part(token, ':', 1)) AS term
    FROM unnest(string_to_array(tsv::TEXT, ' ')) AS token;
$$;


CREATE OR REPLACE FUNCTION extract_passage_terms_freq(tsv TSVECTOR)
RETURNS TABLE(term text, freq INT)
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT
      trim(both '''' FROM split_part(tok, ':', 1)) AS term,
      count(*) AS tf
    FROM
        unnest(string_to_array(tsv::TEXT, ' ')) AS tok,
        unnest(
            string_to_array(
                split_part(tok, ':', 2),
                ','
            )
        ) AS pos
    GROUP BY 1
$$;


CREATE OR REPLACE FUNCTION tsv_doclen(tsv TSVECTOR)
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
