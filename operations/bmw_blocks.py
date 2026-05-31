from typing import Optional, Any


def find_block(pool, term: str, doc_id, doc_id_type: str) -> Optional[Any]:
    """Find which BMW block a (term, doc_id) pair belongs to.

    Args:
        pool: Database connection pool
        term: The search term
        doc_id: Document ID (type varies by table)
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")

    Returns:
        block_id (doc_id_first) or None if no block exists
    """
    pass


def create_block(pool, term: str, doc_id, tc: float, doc_id_type: str) -> Any:
    """Create a new BMW block for a term.

    Args:
        pool: Database connection pool
        term: The search term
        doc_id: Document ID for the first document in the block
        tc: Term contribution value
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")

    Returns:
        The newly created block_id (doc_id_first)
    """
    pass


def split_block(pool, block_id, term: str, doc_id, doc_id_type: str) -> Any:
    """Split an overfull BMW block into two halves.

    Args:
        pool: Database connection pool
        block_id: The block to split (doc_id_first)
        term: The search term
        doc_id: Document ID that triggered the split
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")

    Returns:
        The block_id (doc_id_first) that should contain doc_id after the split
    """
    pass


def add_to_block(pool, block_id, term: str, doc_id, tc: float, doc_id_type: str) -> None:
    """Add a (doc_id, tc) entry to an existing BMW block.

    Args:
        pool: Database connection pool
        block_id: The block identifier (doc_id_first)
        term: The search term
        doc_id: Document ID to add to the block
        tc: Term contribution value
        doc_id_type: SQL type name for doc_id (e.g., "uuid", "int8")

    Returns:
        None (raises exception on failure)
    """
    pass
