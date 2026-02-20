import json
import time
import atexit
import random
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import execute_values
from .common import build_conn_kwargs, main_get_conn, get_primary_key_column


_WORKER_POOL = None


def worker_init(db_url):
    global _WORKER_POOL
    if _WORKER_POOL is None:
        _WORKER_POOL = SimpleConnectionPool(
            minconn=1,
            maxconn=2,
            **build_conn_kwargs(db_url)
        )
        atexit.register(_WORKER_POOL.closeall)


def worker_get_conn(db_url):
    global _WORKER_POOL
    conn = _WORKER_POOL.getconn()
    conn.autocommit = False
    return conn


def worker_put_conn(conn):
    global _WORKER_POOL
    _WORKER_POOL.putconn(conn)



def fetch_null_output_pks(pool, table_name, output_column, primary_key, limit, verbose=False):
    max_retries = 10
    ids = None
    for attempt in range(1, max_retries + 1):
        try:
            conn = main_get_conn(pool)
            with conn.cursor() as cur:
                cur.execute(f"""
                            SELECT "{primary_key}" FROM "{table_name}"
                            WHERE "{output_column}" IS NULL
                            LIMIT %s
                            """,
                            (limit,))
                ids = [row[0] for row in cur.fetchall()]

            pool.putconn(conn)

        except Exception as e:
            if attempt < max_retries:
                print(f"[WARN] Retry {attempt}/{max_retries} on fetch_null_vector_ids: {e}", flush=True)
                time.sleep(0.5 * attempt + random.uniform(0, 0.3))
            else:
                raise

    return ids




def batch_touch(
                db_url,
                table_name, input_column,
                primary_key, primary_key_type,
                pks,
                verbose, batch_index=0
            ):
    
    warnings = []
    errors = []

    # TODO: not sure if this is correct!!!
    if not pks:
        return None

    conn = worker_get_conn(db_url)

    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL bm25.reset = 'true'")
                sql = f'''
                    UPDATE "{table_name}"
                    SET "{input_column}" = "{input_column}"
                    WHERE "{primary_key}" = ANY(%s)
                '''
                print(sql)
                cur.execute(sql, (pks,))
            conn.commit()
            break
        except Exception as e:
            conn.rollback()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if attempt < max_retries:
                warnings.append(f"[{timestamp}] [WARN] (batch {batch_index}) Retry {attempt}/{max_retries} after failure: {e}")
                time.sleep(0.5 * attempt + random.uniform(0, 0.3))
            else:
                errors.append(f"[{timestamp}] [ERROR] Failed after {max_retries} retries: {e}")
    

    worker_put_conn(conn)
    return errors, warnings
    





def run_reset(args):
    if args["verbose"]:
        print(json.dumps(args, indent=2))
    
    executor = ProcessPoolExecutor(
        max_workers=min(args['workers'], multiprocessing.cpu_count()),
        initializer=worker_init, initargs=(args['url'],)
    )
    
    conn_pool = SimpleConnectionPool(minconn=0, maxconn=args['workers'], **build_conn_kwargs(args['url']))
    atexit.register(conn_pool.closeall)

    batch_counter = 0

    primary_key, primary_key_type = get_primary_key_column(conn_pool, args['table'])
    print(f"PK: {primary_key} ({primary_key_type})")

    # ensure_vector_column(
    #     conn_pool,
    #     args['table'],
    #     primary_key,
    #     args['output'],
    #     args['dry_run'],
    #     show_info=not args['progress']
    # )

    pbar = None

    futures = []
    warnings = []
    errors = []

    # Backoff state
    # idle_wait = max(0.001, float(args['min_idle']))   # seconds
    # idle_spent = 0.0                               # seconds
    # idle_budget = max(0.0, float(args['max_idle']) * 60.0)  # seconds (0 = unlimited)

    start = time.time() if args['verbose'] else None

    # Per-run counters (1-based for human-friendly logs)
    run_counter = 1
    batch_in_run = 1

    while True:
        # Stop after N batches per run (default 1) unless following
        if (not args['follow']) and batch_in_run > args['num_batches']:
            break

        # if args['progress'] and batch_in_run == 1:
        #     total_rows = args['batch_size'] * args['num_batches']
        #     if args['follow']:
        #         total_rows = get_null_vector_row_count(conn_pool, args['table'], args['output'], primary_key)

        #     pbar = tqdm(
        #                 total=total_rows,
        #                 desc="Vectorizing",
        #                 unit="rows",
        #                 smoothing=0.01
        #             )

        #     def _on_done_embed(fut):
        #         try:
        #             embeddings = fut.result()
        #         except Exception:
        #             return
        #         if embeddings:
        #             pbar.update(len(embeddings))


        # Fetch one page of IDs (no wait on start or after successful work)
        pks = fetch_null_output_pks(conn_pool, args['table'], args['output'], primary_key, args['batch_size'])
        print(json.dumps(pks, indent=2))

        chunk_size = int(0.5 + len(pks) / args['workers'])
        print(f"chunk_size: {chunk_size}")
        futures = []

        # Run one batch (via pool for per-process model reuse)
        if args['verbose']:
            print(f"[INFO] Run {run_counter}, Batch {batch_in_run} starting ({len(pks)} rows)")


    #     embeddings = []

        for i in range(0, len(pks), chunk_size):
            pk_chunk = pks[i : i + chunk_size]

    #         # Got work → reset backoff
    #         idle_wait = max(0.001, float(args['min_idle']))
    #         idle_spent = 0.0

            fut = executor.submit(
                batch_touch,
                args['url'],
                args['table'], args['input'],
                primary_key, primary_key_type,
                pk_chunk,
                args['verbose'], batch_in_run
            )

            # if args['progress']:
            #     fut.add_done_callback(_on_done_embed)
            
            futures.append(fut)
            
        for fut in as_completed(futures):
            worker_errors, worker_warnings = fut.result()
            errors.extend(worker_errors)
            warnings.extend(worker_warnings)

    #     # for e in embeddings:
    #     #     print(json.dumps(e, indent=2))

    #     worker_count, worker_errors, worker_warnings = batch_update(
    #             conn_pool, args['table'], args['output'],
    #             primary_key, primary_key_type,
    #             embeddings,
    #             args['dry_run'], args['verbose'], batch_in_run
    #         )
    #     errors.extend(worker_errors)
    #     warnings.extend(worker_warnings)


        batch_counter += 1
        batch_in_run += 1
    #     if args['follow'] and batch_in_run > args['num_batches']:
    #         if args['verbose']:
    #             print(f"[INFO] Run {run_counter} complete ({args['num_batches']} batches).")

    #         if args['progress'] and pbar is not None:
    #             pbar.close()
    #             pbar = None

    #         run_counter += 1
    #         batch_in_run = 1

    #     continue

    #     # No work returned → back off or exit if max idle reached
    #     if idle_budget > 0.0 and idle_spent >= idle_budget:
    #         if args['verbose']:
    #             print(f"[INFO] Max idle reached ({args['max_idle']} min). Exiting.")
    #         break

    #     # Sleep current backoff and then double it (exponential), cap by remaining budget if any
    #     to_sleep = idle_wait
    #     if idle_budget > 0.0:
    #         remaining = max(0.0, idle_budget - idle_spent)
    #         to_sleep = min(to_sleep, remaining)
    #     time.sleep(to_sleep)
    #     idle_spent += to_sleep
    #     idle_wait = idle_wait * 2.0

    # if args['verbose']:
    #     print("Done in", time.time() - start, "seconds")


    # if args['verbose']:
    #     print("[INFO] Embedding complete.")

    if (args['progress'] or args['verbose']) and (warnings or errors):
        from datetime import datetime
        print("\n[WARNINGS SUMMARY]", flush=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"warnings_{timestamp}.log"
        with open(log_filename, "w") as f:
            for w in warnings:
                print(w)
                f.write(w + "\n")
        print(f"Total warnings: {len(warnings)}")
        print("\n[ERROR SUMMARY]", flush=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"errors_{timestamp}.log"
        with open(log_filename, "w") as f:
            for w in errors:
                print(w)
                f.write(w + "\n")
        print(f"Total errors: {len(errors)}")

