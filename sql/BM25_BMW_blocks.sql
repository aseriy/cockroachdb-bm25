CREATE OR REPLACE FUNCTION BM25_BMW_split_block(
    block_id UUID,
    p_term STRING,
    p_doc_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    v_block_first UUID;
    v_block_last UUID;

    v_left_first UUID;
    v_left_last UUID;
    v_left_count INT8;
    v_left_ub FLOAT8;

    v_right_first UUID;
    v_right_last UUID;
    v_right_count INT8;
    v_right_ub FLOAT8;
BEGIN
    SELECT
        doc_id_first,
        doc_id_last
    INTO
        v_block_first,
        v_block_last
    FROM _tsv_bmw_131_3
    WHERE term = p_term
      AND doc_id_first = block_id;

    WITH ordered AS (
        SELECT
            doc_id,
            tc,
            row_number() OVER (ORDER BY doc_id) AS rn,
            count(*) OVER () AS n
        FROM _tsv_term_tc_131_3
        WHERE term = p_term
          AND doc_id >= v_block_first
          AND doc_id <= v_block_last
    ),
    halves AS (
        SELECT
            doc_id,
            tc,
            CASE
                WHEN rn <= n / 2 THEN 0
                ELSE 1
            END AS side
        FROM ordered
    ),
    agg AS (
        SELECT
            side,
            min(doc_id) AS doc_id_first,
            max(doc_id) AS doc_id_last,
            count(*)::INT8 AS doc_count,
            max(tc) AS ub
        FROM halves
        GROUP BY side
    )
    SELECT
        l.doc_id_first,
        l.doc_id_last,
        l.doc_count,
        l.ub,
        r.doc_id_first,
        r.doc_id_last,
        r.doc_count,
        r.ub
    INTO
        v_left_first,
        v_left_last,
        v_left_count,
        v_left_ub,
        v_right_first,
        v_right_last,
        v_right_count,
        v_right_ub
    FROM agg AS l
    JOIN agg AS r
      ON l.side = 0
     AND r.side = 1;

    UPDATE _tsv_bmw_131_3
    SET
        doc_id_last = v_left_last,
        doc_count = v_left_count,
        ub = v_left_ub
    WHERE term = p_term
      AND doc_id_first = v_block_first;

    INSERT INTO _tsv_bmw_131_3 (
        term,
        doc_id_first,
        doc_id_last,
        doc_count,
        ub
    )
    VALUES (
        p_term,
        v_right_first,
        v_right_last,
        v_right_count,
        v_right_ub
    );

    IF p_doc_id <= v_left_last THEN
        RETURN v_left_first;
    END IF;

    RETURN v_right_first;
END;
$$;



CREATE OR REPLACE FUNCTION BM25_BMW_find_block(
    p_term STRING,
    p_doc_id UUID
)
RETURNS UUID
LANGUAGE plpgsql
VOLATILE -- STABLE
AS $$
DECLARE
    v_doc_id_first UUID;
    v_can_accept BOOLEAN;
    v_blocks_json JSONB;
    v_block_list UUID[];
    v_block_list_size INT;
    v_idx INT;
    v_block_max INT := BM25_BMW_block_size();
    v_result UUID := NULL;
BEGIN

    IF NOT EXISTS (
        SELECT 1 FROM _tsv_bmw_131_3 WHERE term = p_term LIMIT 1
    ) THEN
        RAISE NOTICE 'No blocks found for term: %', p_term;
        RETURN NULL; 
    END IF;

    WITH
    blocks AS (
        SELECT
            b.doc_id_first,
            b.doc_id_last,
            b.doc_count
        FROM _tsv_bmw_131_3 AS b
        WHERE b.term = p_term
    )
    SELECT
        jsonb_object_agg(doc_id_first::STRING, to_jsonb(doc_count)),
        array_agg(x)
    INTO
        v_blocks_json,
        v_block_list
    FROM blocks, unnest(ARRAY[doc_id_first, doc_id_last]) AS x;

    v_block_list_size := array_length(v_block_list,1);
    RAISE NOTICE 'v_block_list_size: %', v_block_list_size;


    RAISE NOTICE 'v_blocks_json: %', v_blocks_json;
    RAISE NOTICE 'v_blcok_list: %', v_block_list;

    SELECT count(*) INTO v_idx
    FROM unnest(v_block_list) AS t(x) 
        WHERE x < p_doc_id;

    RAISE NOTICE 'v_idx: %', v_idx;

    -- Document is below the first block
    IF v_idx = 0 THEN
        RAISE NOTICE 'Below first block';
        IF (v_blocks_json ->> (v_block_list[1]::TEXT))::INT < v_block_max THEN
            v_result := v_block_list[1];
        END IF;


    -- Document is above the last block
    ELSIF v_idx = v_block_list_size THEN
        RAISE NOTICE 'Above last block';
        IF (v_blocks_json ->> (v_block_list[v_idx-1]::TEXT))::INT < v_block_max THEN
            v_result := v_block_list[v_idx-1];
        END IF;
        


    -- Document falls into an existing block
    ELSIF v_idx % 2 = 1 THEN
        RAISE NOTICE 'Inside block %', (v_idx);
        IF (v_blocks_json ->> (v_block_list[v_idx]::TEXT))::INT < v_block_max THEN
            v_result := v_block_list[v_idx];
        ELSE
            v_result := BM25_BMW_split_block(v_block_list[v_idx], p_term, p_doc_id);
        END IF;


    -- Document falls between two existing blocks
    ELSE
        RAISE NOTICE 'In between blocks % and %', v_block_list[v_idx-1], v_block_list[v_idx+1];
        IF (v_blocks_json ->> (v_block_list[v_idx-1]::TEXT))::INT < v_block_max THEN
            v_result := v_block_list[v_idx-1];
        ELSIF (v_blocks_json ->> (v_block_list[v_idx+1]::TEXT))::INT < v_block_max THEN
            v_result := v_block_list[v_idx+1];
        END IF;
        

    END IF;

    RETURN v_result;
END;
$$;



CREATE OR REPLACE FUNCTION BM25_BMW_create_block(
    term STRING,
    doc_id UUID,
    tc FLOAT8
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO _tsv_bmw_131_3 (
        term,
        doc_id_first,
        doc_id_last,
        doc_count,
        ub
    )
    VALUES (
        term,
        doc_id,
        doc_id,
        1,
        tc
    );
END;
$$;





CREATE OR REPLACE FUNCTION BM25_BMW_add_to_block(
    p_block_id UUID,
    p_term STRING,
    p_doc_id UUID,
    p_tc FLOAT8
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE _tsv_bmw_131_3
    SET
        doc_id_first = LEAST(doc_id_first, p_doc_id),
        doc_id_last  = GREATEST(doc_id_last, p_doc_id),
        doc_count    = doc_count + 1,
        ub           = GREATEST(ub, p_tc)
    WHERE term = p_term
      AND doc_id_first = p_block_id;
END;
$$;