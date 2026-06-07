from urllib.parse import urlparse
from urllib.parse import parse_qs
from typing import Optional, Any
from psycopg2.extensions import connection


def build_conn_kwargs(db_url) -> dict[str, Any]:
    parsed = urlparse(db_url)

    # 1. Parse the query string into a dictionary
    query_params = parse_qs(parsed.query) if parsed.query else {}

    # 2. Extract single values (parse_qs returns lists by default)
    ssl_mode = query_params.get("sslmode", ["require"])[0]

    connection_dict = dict (
        dbname=parsed.path[1:],
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 26257,
        sslmode=ssl_mode
    )

    # 3. Dynamically add the SSL certificate parameters if they exist in the URI
    ssl_keys = ["sslrootcert", "sslcert", "sslkey"]
    for key in ssl_keys:
        if key in query_params:
            connection_dict[key] = query_params[key][0]

    return connection_dict





def main_get_conn(pool) -> connection:
    conn = pool.getconn()
    conn.autocommit = False
    return conn



def get_table_id(pool, schema_name, table_name) -> int:
    conn = main_get_conn(pool)
    table_id = None

    query = f"""
        SELECT table_id                                         
        FROM crdb_internal.tables                               
        WHERE name = '{table_name}'
    """

    if schema_name is not None:
        query += f"""
                AND
                schema_name = '{schema_name}'
        """

    with conn.cursor() as cur:
        cur.execute(query)
        result = cur.fetchone()
        if result:
            table_id = result[0]

    pool.putconn(conn)

    return table_id



def get_index_id(pool, schema_name, table_name, index_name = None) -> int | list[int]:
    conn = main_get_conn(pool)
    table_id = get_table_id(pool, schema_name, table_name)
    index_id = None

    if table_id:
        if schema_name is None:
            query = f"""
                SELECT index_id
                FROM crdb_internal.table_indexes
                WHERE
                    descriptor_name = '{table_name}'
            """

            if index_name:
                query += f"""
                        AND
                        index_name = '{index_name}'
                """

        else:
            query = f"""
                SELECT i.index_id
                FROM crdb_internal.table_indexes i
                JOIN crdb_internal.tables t ON t.table_id = i.descriptor_id
                WHERE t.name = '{table_name}'
                AND t.schema_name = '{schema_name}'
            """

            if index_name:
                query += f"""
                        AND
                        i.index_name = '{index_name}'
            """

        with conn.cursor() as cur:
            cur.execute(query)
            if index_name:
                result = cur.fetchone()
                index_id = result[0]
            else:
                result = cur.fetchall()
                index_id = [r[0] for r in result]

    pool.putconn(conn)

    return index_id



def get_primary_key_column(pool, schema_name, table_name) -> dict:
    conn = main_get_conn(pool)

    pk_result = None

    query = f"""
            SELECT
                a.attname AS column_name,
                t.typname AS column_type
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_type t ON a.atttypid = t.oid
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE {"n.nspname = %s AND" if schema_name is not None else ""}
                c.relname = %s AND
                i.indisprimary
        """

    with conn.cursor() as cur:
        if schema_name is not None:
            cur.execute(query, (schema_name, table_name,))
        else:
            cur.execute(query, (table_name,))
        pk_result = cur.fetchone()

    pool.putconn(conn)

    if not pk_result:
        if schema_name is not None:
            table_name = f"{schema_name}.{table_name}"
        raise RuntimeError(f"No primary key found for table '{table_name}'")

    pk_name, pk_type = pk_result
    return pk_name, pk_type



def get_column_id(pool, schema_name: str, table_name: str, column_name: str) -> int:
    conn = main_get_conn(pool)

    sql = f"""
        SELECT a.attnum AS column_id
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_attribute a ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
        WHERE {"n.nspname = %s AND" if schema_name is not None else ""}
              c.relname = %s
              AND a.attname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
    """

    with conn.cursor() as cur:
        if schema_name is not None:
            cur.execute(sql, (schema_name, table_name, column_name))
        else:
            cur.execute(sql, (table_name, column_name))
        result = cur.fetchone()

    pool.putconn(conn)

    if not result:
        if schema_name is not None:
            table_name = f"{schema_name}.{table_name}"
        raise RuntimeError(f"Column '{column_name}' not found in table '{table_name}'")

    return result[0]



def get_column_type(
        pool,
        schema_name: str,
        table_name: str,
        column_name: str
    ) -> Optional[str]:

    conn = main_get_conn(pool)

    sql = f'''
            SELECT
                CASE 
                    WHEN t.typname = 'vector' AND a.atttypmod > 0 THEN 'vector(' || a.atttypmod || ')'
                    ELSE format_type(a.atttypid, a.atttypmod)
                END AS full_type
            FROM pg_attribute a
            JOIN pg_type t ON a.atttypid = t.oid
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE {"n.nspname = %s AND" if schema_name is not None else ""}
                c.relname = %s AND
                a.attname = %s;
        '''

    column_type = None
    with conn.cursor() as cur:
        if schema_name is None:
            cur.execute(sql, (table_name, column_name))
        else:
            cur.execute(sql, (schema_name, table_name, column_name))

        existing = cur.fetchone()
        if existing:
            column_type = existing[0]

    pool.putconn(conn)
    return column_type
