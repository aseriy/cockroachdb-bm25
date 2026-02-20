from urllib.parse import urlparse


def build_conn_kwargs(db_url):
    parsed = urlparse(db_url)
    return dict(
        dbname=parsed.path[1:],
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 26257,
        sslmode=(
            parsed.query.split("sslmode=")[1]
            if parsed.query and "sslmode=" in parsed.query
            else "require"
        )
    )


def main_get_conn(pool):
    conn = pool.getconn()
    conn.autocommit = True
    return conn


def get_primary_key_column(pool, table_name):
    conn = main_get_conn(pool)

    pk_result = None

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                a.attname AS column_name,
                t.typname AS column_type
            FROM pg_index i
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid
             AND a.attnum = ANY(i.indkey)
            JOIN pg_type t
              ON a.atttypid = t.oid
            WHERE i.indrelid = %s::regclass
              AND i.indisprimary
            """,
            (table_name,)
        )
        pk_result = cur.fetchone()

    pool.putconn(conn)

    if not pk_result:
        raise RuntimeError(f"No primary key found for table '{table_name}'")

    pk_name, pk_type = pk_result
    return pk_name, pk_type



