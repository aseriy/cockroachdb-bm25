def update_term_frequency(
                    pool,
                    doc_id, doc_id_type: str, jsonb_obj: dict,
                    terms: str,
                    verbose = False
    ):


        # -- -- Increments term counters and updates upper bound
        # -- INSERT INTO _tsv_terms_131_3 (term, freq, ub)
        # -- SELECT term, 1, tc
        # -- FROM jsonb_to_recordset(v_tsv_term_tc) 
        # --     AS x(id UUID, term STRING, tc FLOAT)
        # -- ON CONFLICT (term)
        # -- DO UPDATE SET 
        # --     freq = _tsv_terms_131_3.freq + 1,
        # --     ub = GREATEST(_tsv_terms_131_3.ub, EXCLUDED.ub);
 
    pass



def update_bmw_blocks(
                    pool,
                    doc_id, doc_id_type: str, jsonb_obj: dict,
                    bmw: str,
                    verbose = False
    ):

        # -- -- Update BMW blocks
        # -- WITH term_rows AS (
        # --     SELECT *
        # --     FROM jsonb_to_recordset(v_tsv_term_tc)
        # --         AS x(id UUID, term STRING, tc FLOAT8)
        # -- ),
        # -- routed AS (
        # --     SELECT
        # --         id,
        # --         term,
        # --         tc,
        # --         BM25_BMW_find_block(term, id) AS block_id
        # --     FROM term_rows
        # -- )
        # -- SELECT
        # --     CASE
        # --         WHEN block_id IS NULL THEN BM25_BMW_create_block(term, id, tc)
        # --         ELSE BM25_BMW_add_to_block(block_id, term, id, tc)
        # --     END
        # -- FROM routed;


    pass



def update_corpus(
                    pool,
                    doc_id, doc_id_type: str, jsonb_obj: dict,
                    corpus: str,
                    verbose = False
    ):

        # -- -- Increment corpus stats
        # -- UPDATE _tsv_corpus
        # --     SET n = n + 1, total = total + (v_tsv_json->>'dl')::INT8
        # --     WHERE table_name ='passage' AND column_name = 'passage';


    pass



def update_term_contribution(
                    pool,
                    doc_id, doc_id_type: str, jsonb_obj: dict,
                    term_tc: str,
                    verbose = False
    ):

        # -- -- Add term contrib (TC) to _tsv_term_tc_<tbl_oid>_<col_oid>
        # -- INSERT INTO _tsv_term_tc_131_3 (doc_id, term, tc)
        # -- SELECT id, term, tc
        # -- FROM jsonb_to_recordset(v_tsv_term_tc)
        # --     AS x(id UUID, term STRING, tc FLOAT);

    pass






def index_document(
                    pool,
                    doc_id, doc_id_type: str, jsonb_obj: dict,
                    corpus: str, terms: str, terms_tc: str, bmw: str,
                    verbose = False
    ):
    """Index a single document by updating BM25 index tables.

    Args:
        pool: Database connection pool
        doc_id: Document primary key
        doc_id_type: SQL type name for doc_id
        jsonb_obj: JSONB object containing document term frequencies and metadata
        corpus: Corpus statistics table name
        terms: Terms frequency/upper bound table name
        terms_tc: Term contribution table name
        bmw: BMW blocks table name
        verbose: Enable verbose logging
    """


    # update_bmw_blocks()

    # update_term_frequency()
    # update_term_contributions()
    # update_corpus()


    pass



def run_index(args: dict):
    verbose = args["verbose"]

    print(f"args: {args}")

    pass

