create or replace function match_bill_chunks(
    query_embedding vector(1024),
    match_count      int default 10,
    filter_congress  int default null,
    filter_bill_type text default null
)
returns table (
    id             bigint,
    bill_id        bigint,
    package_id     text,
    congress       int,
    bill_type      text,
    bill_number    int,
    section_number text,
    section_title  text,
    chunk_index    int,
    chunk_text     text,
    token_count    int,
    similarity     float
)
language sql stable
as $$
    select
        bc.id,
        bc.bill_id,
        bc.package_id,
        bc.congress,
        bc.bill_type,
        bc.bill_number,
        bc.section_number,
        bc.section_title,
        bc.chunk_index,
        bc.chunk_text,
        bc.token_count,
        1 - (bc.embedding <=> query_embedding) as similarity
    from bill_chunks bc
    where
        (filter_congress  is null or bc.congress  = filter_congress)
        and (filter_bill_type is null or bc.bill_type = filter_bill_type)
    order by bc.embedding <=> query_embedding
    limit match_count;
$$;
