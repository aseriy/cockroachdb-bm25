from psycopg2.pool import SimpleConnectionPool
import atexit
import time
import random
from .common import (
    build_conn_kwargs,
    main_get_conn,
    get_primary_key_column,
    get_column_type,
    get_table_id,
    get_column_id
)

from enum import Enum, auto

class SQLOperation(Enum):
    INSERT = auto()
    UPDATE = auto()
    DELETE = auto()


def update_term_frequency(
    cursor,
    batch: list,
    doc_id_type: str,
    terms_table: str,
    verbose=False
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
    cursor,
    batch: list,
    doc_id_type: str,
    bmw_table: str,
    term_tc_table: str,
    block_size: int,
    verbose=False
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
    cursor,
    batch: list,
    corpus_table: str,
    verbose=False
):
    # -- -- Increment corpus stats
    # -- UPDATE _tsv_corpus
    # --     SET n = n + 1, total = total + (v_tsv_json->>'dl')::INT8
    # --     WHERE table_name ='passage' AND column_name = 'passage';

    pass



def update_term_contribution(
    cursor,
    batch: list,
    doc_id_type: str,
    term_tc_table: str,
    verbose=False
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






def index_single_batch(
    conn_pool: SimpleConnectionPool,
    schema: str | None, table: str,
    primary_key: str, primary_key_type: str,
    idx_column: str,
    ids: list,
    index_tables: dict,
    block_size: int,
    verbose: bool = False
) -> dict:
    """Index a single batch of documents by updating BM25 index tables.

    Args:
        conn_pool: Database connection pool
        schema: Schema name (optional)
        table: Table name
        primary_key: Primary key column name
        primary_key_type: Primary key SQL type
        idx_column: JSONB column name
        ids: List of document IDs to index
        index_tables: Dict of index table names
        block_size: BMW block size
        verbose: Enable verbose logging

    Returns:
        Dict with batch statistics
    """

    # Build qualified table name
    table_qualified = f"{schema}.{table}" if schema else table

    # Fetch JSONB data for batch
    conn = conn_pool.getconn()

    try:
        with conn.cursor() as cursor:
            sql = f"""
                SELECT {primary_key}, {idx_column}
                FROM {table_qualified}
                WHERE {primary_key} = ANY(%s::{primary_key_type}[])
            """
            cursor.execute(sql, (ids,))
            rows = cursor.fetchall()

            # Build batch list
            batch = []
            for pk_val, jsonb_data in rows:
                if "1" in jsonb_data:
                    operation = SQLOperation.UPDATE
                    tsv_dict = jsonb_data["1"]
                else:
                    operation = SQLOperation.INSERT
                    tsv_dict = jsonb_data["0"]

                batch.append((operation, pk_val, tsv_dict))

            if verbose:
                inserts = sum(1 for op, _, _ in batch if op == SQLOperation.INSERT)
                updates = sum(1 for op, _, _ in batch if op == SQLOperation.UPDATE)
                print(f"[INFO] Batch: {len(batch)} docs ({inserts} inserts, {updates} updates)")

            # Call update functions
            update_term_contribution(cursor, batch, primary_key_type, index_tables['term_tc'], verbose)
            update_bmw_blocks(cursor, batch, primary_key_type, index_tables['bmw'], index_tables['term_tc'], block_size, verbose)
            update_term_frequency(cursor, batch, primary_key_type, index_tables['terms'], verbose)
            update_corpus(cursor, batch, index_tables['corpus'], verbose)

        conn.commit()

        return {
            "batch_size": len(batch),
            "inserts": sum(1 for op, _, _ in batch if op == SQLOperation.INSERT),
            "updates": sum(1 for op, _, _ in batch if op == SQLOperation.UPDATE),
        }

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn_pool.putconn(conn)





def run_index_n_batches(
    conn_pool: SimpleConnectionPool,
    schema: str | None, table: str,
    primary_key: str, primary_key_type: str,
    idx_column: str,
    index_tables: dict,
    block_size: int,
    batch_size: int, num_batches: int,
    verbose: bool = False
):

    start = time.time()

    for batch in range(1, num_batches+1):
        # Fetch one batchfull of IDs (no wait on start or after successful work)
        ids = fetch_unindexed_doc_ids(
                conn_pool,
                schema, table,
                primary_key, idx_column,
                batch_size,
                verbose
            )

        if not ids:
            if verbose:
                print(f"[INFO] No work found. Exiting... ")
            break

        # Call index_single_batch
        result = index_single_batch(
            conn_pool,
            schema, table,
            primary_key, primary_key_type,
            idx_column,
            ids,
            index_tables,
            block_size,
            verbose
        )

        if verbose:
            print(f"[INFO] Batch {batch} result: {result}")


    print("Done in", time.time() - start, "seconds")
    return None



def run_index(args: dict):
    print(f"args: {args}")

    verbose = args["verbose"]

    conn_pool = SimpleConnectionPool(minconn=0, maxconn=10, **build_conn_kwargs(args['url']))
    atexit.register(conn_pool.closeall)

    # Get metadata
    primary_key, primary_key_type = get_primary_key_column(conn_pool, args['schema'], args['table'])
    table_id = get_table_id(conn_pool, args['schema'], args['table'])
    column_id = get_column_id(conn_pool, args['schema'], args['table'], args['input'])

    # Build index table names
    suffix = f"{table_id}_{column_id}"
    index_tables = {
        'corpus': '_tsv_corpus',
        'terms': f'_tsv_terms_{suffix}',
        'term_tc': f'_tsv_term_tc_{suffix}',
        'bmw': f'_tsv_bmw_{suffix}'
    }

    # Fetch block size from DB
    conn = conn_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT bm25_bmw_block_size()")
            block_size = cur.fetchone()[0]
    finally:
        conn_pool.putconn(conn)

    if verbose:
        print(f"[INFO] PK: {primary_key} ({primary_key_type})")
        print(f"[INFO] Index tables: {index_tables}")
        print(f"[INFO] Block size: {block_size}")

    run_index_n_batches(
        conn_pool,
        args["schema"], args["table"],
        primary_key, primary_key_type,
        f"{args['input']}_tsv_jsonb",
        index_tables,
        block_size,
        args["batch_size"], args["num_batches"],
        verbose
    )

