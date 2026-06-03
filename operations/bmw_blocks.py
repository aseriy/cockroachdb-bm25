from typing import Optional, Any


def find_block(cursor, term: str, doc_id, doc_id_type: str, bmw_table: str, term_tc_table: str, block_size: int) -> Optional[Any]:
    """Find which BMW block a (term, doc_id) pair belongs to.

    Args:
        cursor: Database cursor
        term: The search term
        doc_id: Document ID (type varies by table)
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")
        bmw_table: BMW blocks table name
        term_tc_table: Term contribution table name
        block_size: Maximum block size

    Returns:
        block_id (doc_id_first) or None if no block exists
    """
    # Check if any blocks exist for this term
    sql = f"""
        SELECT 1 FROM {bmw_table} WHERE term = %s LIMIT 1
    """
    cursor.execute(sql, (term,))
    if not cursor.fetchone():
        return None

    # Fetch all blocks for this term
    sql = f"""
        SELECT doc_id_first, doc_id_last, doc_count
        FROM {bmw_table}
        WHERE term = %s
        ORDER BY doc_id_first
    """
    cursor.execute(sql, (term,))
    blocks = cursor.fetchall()

    # Build boundary list and lookup dict
    block_list = []
    blocks_dict = {}
    for first, last, count in blocks:
        block_list.extend([first, last])
        blocks_dict[first] = count

    # Find position of doc_id in boundary list
    idx = sum(1 for x in block_list if x < doc_id)

    # Case 1: Document is below the first block
    if idx == 0:
        first_block = block_list[0]
        if blocks_dict[first_block] < block_size:
            return first_block
        return None

    # Case 2: Document is above the last block
    elif idx == len(block_list):
        last_block = block_list[idx - 1]
        # Find the corresponding first_id
        for first, last, count in blocks:
            if last == last_block:
                if blocks_dict[first] < block_size:
                    return first
        return None

    # Case 3: Document falls inside an existing block (odd index)
    elif idx % 2 == 1:
        block_first = block_list[idx]
        if blocks_dict[block_first] < block_size:
            return block_first
        else:
            # Block is full, split it
            return split_block(cursor, block_first, term, doc_id, doc_id_type, bmw_table, term_tc_table)

    # Case 4: Document falls between two blocks (even index)
    else:
        prev_block_last = block_list[idx - 1]
        next_block_first = block_list[idx + 1] if idx + 1 < len(block_list) else None

        # Try previous block
        for first, last, count in blocks:
            if last == prev_block_last:
                if blocks_dict[first] < block_size:
                    return first
                break

        # Try next block
        if next_block_first and blocks_dict[next_block_first] < block_size:
            return next_block_first

        return None


def create_block(cursor, term: str, doc_id, tc: float, doc_id_type: str, bmw_table: str) -> Any:
    """Create a new BMW block for a term.

    Args:
        cursor: Database cursor
        term: The search term
        doc_id: Document ID for the first document in the block
        tc: Term contribution value
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")
        bmw_table: BMW blocks table name

    Returns:
        The newly created block_id (doc_id_first)
    """
    sql = f"""
        INSERT INTO {bmw_table} (term, doc_id_first, doc_id_last, doc_count, ub)
        VALUES (%s, %s::{doc_id_type}, %s::{doc_id_type}, 1, %s)
    """
    cursor.execute(sql, (term, doc_id, doc_id, tc))
    return doc_id


def split_block(cursor, block_id, term: str, doc_id, doc_id_type: str, bmw_table: str, term_tc_table: str) -> Any:
    """Split an overfull BMW block into two halves.

    Args:
        cursor: Database cursor
        block_id: The block to split (doc_id_first)
        term: The search term
        doc_id: Document ID that triggered the split
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")
        bmw_table: BMW blocks table name
        term_tc_table: Term contribution table name

    Returns:
        The block_id (doc_id_first) that should contain doc_id after the split
    """
    # Step 1: Fetch block bounds
    sql = f"""
        SELECT doc_id_first, doc_id_last
        FROM {bmw_table}
        WHERE term = %s AND doc_id_first = %s::{doc_id_type}
    """
    cursor.execute(sql, (term, block_id))
    v_block_first, v_block_last = cursor.fetchone()

    # Step 2: Fetch all docs in the block range
    sql = f"""
        SELECT doc_id, tc
        FROM {term_tc_table}
        WHERE term = %s
          AND doc_id >= %s::{doc_id_type}
          AND doc_id <= %s::{doc_id_type}
        ORDER BY doc_id
    """
    cursor.execute(sql, (term, v_block_first, v_block_last))
    docs = cursor.fetchall()

    # Step 3: Split in Python
    mid = len(docs) // 2
    left_docs = docs[:mid]
    right_docs = docs[mid:]

    # Compute left aggregates
    v_left_first = left_docs[0][0]
    v_left_last = left_docs[-1][0]
    v_left_count = len(left_docs)
    v_left_ub = max(tc for _, tc in left_docs)

    # Compute right aggregates
    v_right_first = right_docs[0][0]
    v_right_last = right_docs[-1][0]
    v_right_count = len(right_docs)
    v_right_ub = max(tc for _, tc in right_docs)

    # Step 4: Update left block
    sql = f"""
        UPDATE {bmw_table}
        SET doc_id_last = %s::{doc_id_type},
            doc_count = %s,
            ub = %s
        WHERE term = %s AND doc_id_first = %s::{doc_id_type}
    """
    cursor.execute(sql, (v_left_last, v_left_count, v_left_ub, term, v_block_first))

    # Step 5: Insert right block
    sql = f"""
        INSERT INTO {bmw_table} (term, doc_id_first, doc_id_last, doc_count, ub)
        VALUES (%s, %s::{doc_id_type}, %s::{doc_id_type}, %s, %s)
    """
    cursor.execute(sql, (term, v_right_first, v_right_last, v_right_count, v_right_ub))

    # Step 6: Return appropriate block
    if doc_id <= v_left_last:
        return v_left_first
    else:
        return v_right_first


def add_to_block(cursor, block_id, term: str, doc_id, tc: float, doc_id_type: str, bmw_table: str) -> None:
    """Add a (doc_id, tc) entry to an existing BMW block.

    Args:
        cursor: Database cursor
        block_id: The block identifier (doc_id_first)
        term: The search term
        doc_id: Document ID to add to the block
        tc: Term contribution value
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")
        bmw_table: BMW blocks table name

    Returns:
        None (raises exception on failure)
    """
    sql = f"""
        UPDATE {bmw_table}
        SET
            doc_id_first = LEAST(doc_id_first, %s::{doc_id_type}),
            doc_id_last  = GREATEST(doc_id_last, %s::{doc_id_type}),
            doc_count    = doc_count + 1,
            ub           = GREATEST(ub, %s)
        WHERE term = %s AND doc_id_first = %s::{doc_id_type}
    """
    cursor.execute(sql, (doc_id, doc_id, tc, term, block_id))
