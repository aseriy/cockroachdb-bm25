CREATE OR REPLACE FUNCTION BM25_candidates(
  query STRING,
  limit_n INT
)
RETURNS TABLE(id UUID)
LANGUAGE SQL
AS $$
  SELECT id
  FROM passage
  WHERE passage_tsv @@ plainto_tsquery('english', query)
  LIMIT limit_n
$$;
