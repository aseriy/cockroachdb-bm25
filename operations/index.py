from psycopg2.pool import SimpleConnectionPool
import atexit
import time
import random
from .common import (
    build_conn_kwargs,
    main_get_conn,
    get_primary_key_column,
    get_column_type
)



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




# SELECT id FROM passage
# WHERE passage_tsv_jsonb IS NOT NULL
#   AND (passage_tsv_jsonb->>'idx')::BOOL IS NOT TRUE
# LIMIT 100;

def fetch_unindexed_doc_ids(
                            pool,
                            schema_name, table_name,
                            primary_key, output_column,
                            limit,
                            verbose=False
):

    max_retries = 10
    ids = None

    if schema_name is not None:
        table_name = f"{schema_name}.{table_name}"

    query = f"""
            SELECT {primary_key} FROM {table_name}
            WHERE {output_column} IS NOT NULL
            AND ({output_column}->>'idx')::BOOL IS NOT TRUE
            LIMIT %s
    """
    print(f"query: {query}")

    for attempt in range(1, max_retries + 1):
        try:
            conn = main_get_conn(pool)
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                ids = [row[0] for row in cur.fetchall()]

            pool.putconn(conn)

        except Exception as e:
            if attempt < max_retries:
                print(f"[WARN] Retry {attempt}/{max_retries} on fetch_null_vector_ids: {e}", flush=True)
                time.sleep(0.5 * attempt + random.uniform(0, 0.3))
            else:
                raise

    return ids




# def index_document(
#                     pool,
#                     doc_id, doc_id_type: str, jsonb_obj: dict,
#                     corpus: str, terms: str, terms_tc: str, bmw: str,
#                     verbose = False
#     ):
#     """Index a single document by updating BM25 index tables.

#     Args:
#         pool: Database connection pool
#         doc_id: Document primary key
#         doc_id_type: SQL type name for doc_id
#         jsonb_obj: JSONB object containing document term frequencies and metadata
#         corpus: Corpus statistics table name
#         terms: Terms frequency/upper bound table name
#         terms_tc: Term contribution table name
#         bmw: BMW blocks table name
#         verbose: Enable verbose logging
#     """


#     # update_bmw_blocks()

#     # update_term_frequency()
#     # update_term_contributions()
#     # update_corpus()


#     pass



def index_single_batch(
                    conn_pool: SimpleConnectionPool,
                    url: str, schema: str | None, table: str,
                    primary_key: str, primary_key_type: str,
                    doc_column: str, idx_column: str,
                    ids: list,
                    batch_counter: int,
                    verbose: bool = False
):


    # update_bmw_blocks()
    # update_term_frequency()
    # update_term_contributions()
    # update_corpus()


    return  update_count, worker_errors, worker_warnings





def run_index_n_batches(
    conn_pool: SimpleConnectionPool,
    url: str, schema: str | None, table: str,
    primary_key: str, primary_key_type: str,
    doc_column: str, doc_idx_column: str,
    batch_size: int, num_batches: int,
    verbose: bool = False
):

    start = time.time()

    for batch in range(1, num_batches+1):
        # Fetch one batchfull of IDs (no wait on start or after successful work)
        ids = fetch_unindexed_doc_ids(
                conn_pool,
                schema, table,
                primary_key, doc_idx_column,
                batch_size,
                verbose
            )

        if not ids:
            if verbose:
                print(f"[INFO] No work found. Exiting... ")
            break

        print(ids)

    
    print("Done in", time.time() - start, "seconds")
    return None



def run_index(args: dict):
    print(f"args: {args}")

    verbose = args["verbose"]

    conn_pool = SimpleConnectionPool(minconn=0, maxconn=10, **build_conn_kwargs(args['url']))
    atexit.register(conn_pool.closeall)

    primary_key, primary_key_type = get_primary_key_column(conn_pool, args['schema'], args['table'])
    if verbose:
        print(f"[INFO] PK: {primary_key} ({primary_key_type})")

    run_index_n_batches(
        conn_pool,
        args["url"], args["schema"], args["table"],
        primary_key, primary_key_type,
        args["input"], f"{args["input"]}_tsv_jsonb",
        args["batch_size"], args["num_batches"],
        verbose
    )

