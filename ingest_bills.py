'''Stage 1 — Discovery
    GovInfo /collections/BILLS?congress=119
    Paginate through all packages
    Filter: introduced versions only (ih, is)
    Filter: skip ceremonial (hres/sres + skip patterns)
    Output: list of {packageId, billType, billNumber, summary_url}

Stage 2 — Metadata fetch
    For each package → /packages/{id}/summary
    Extract: sponsor, committees, chamber, title, date
    Store in Postgres bills table
    Output: bills table populated

Stage 3 — Text fetch
    For each bill → /packages/{id}/htm
    Strip HTML tags
    Strip header boilerplate (everything before "Be it enacted" or "Resolved")
    Output: clean plain text per bill

Stage 4 — Chunking
    Split by section (§, "SEC.", "SECTION")
    Each chunk: section number + title + text
    Max chunk size: ~500 tokens
    Overlap: 50 tokens between chunks
    Output: chunks with metadata

Stage 5 — Embedding
    Batch embed chunks via OpenAI text-embedding-3-small
    Store in Supabase pgvector
    Output: vector table populated

Stage 6 — Index
    Build search index on congress, bill_number, section
    Output: ready for RAG queries'''

import requests
import os
import time
import re
from bs4 import BeautifulSoup
from supabase import create_client
import voyageai
from dotenv import load_dotenv

load_dotenv()

GOVINFO_KEY = os.getenv("GovInfo_API_KEY")
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_API_KEY"))
voyage = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))

SKIP_PATTERNS = [
    "expressing support", "recognizing the", "honoring the",
    "congratulating", "acknowledging", "commemorating",
    "proclaiming", "celebrating", "designating",
    "supporting the designation"
]

INTRODUCED_VERSIONS = {"ih", "is"}  # introduced house, introduced senate

# ── Stage 1: Discovery ──

def discover_bills(congress=119):
    print(f"[INGEST] Discovering bills for {congress}th Congress...")
    url = "https://api.govinfo.gov/collections/BILLS"
    params = {
        "api_key": GOVINFO_KEY,
        "pageSize": 100,
        "offsetMark": "*",
        "congress": congress
    }
    
    # Use date range for 119th Congress
    base_url = f"https://api.govinfo.gov/collections/BILLS/2025-01-01T00:00:00Z"
    
    packages = []
    offset = "*"
    page = 0
    
    while True:
        url = f"{base_url}?api_key={GOVINFO_KEY}&pageSize=100&offsetMark={offset}"
        
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                print(f"[INGEST] Error {r.status_code}")
                break
            
            data = r.json()
            batch = data.get("packages", [])
            
            for pkg in batch:
                package_id = pkg.get("packageId", "")
                title = pkg.get("title", "").lower()
                
                # Extract version from package ID
                # e.g. BILLS-119hr1234ih → ih
                version_match = re.search(r'([a-z]+)$', package_id.replace("BILLS-119", ""))
                version = version_match.group(1) if version_match else ""
                
                # Only introduced versions
                if version not in INTRODUCED_VERSIONS:
                    continue
                
                # Skip ceremonial
                if any(p in title for p in SKIP_PATTERNS):
                    continue
                
                packages.append(pkg)
            
            page += 1
            print(f"[INGEST] Page {page}: {len(batch)} packages, {len(packages)} kept so far")
            
            next_page = data.get("nextPage")
            if not next_page:
                break
            
            # Extract offsetMark from next page URL
            offset_match = re.search(r'offsetMark=([^&]+)', next_page)
            if not offset_match:
                break
            offset = offset_match.group(1)
            
            time.sleep(0.5)  # be nice to the API
            
        except Exception as e:
            print(f"[INGEST] Discovery error: {e}")
            break
    
    print(f"[INGEST] Discovery complete: {len(packages)} bills to ingest")
    return packages


# ── Stage 2: Metadata ──

def fetch_metadata(package_id):
    url = f"https://api.govinfo.gov/packages/{package_id}/summary"
    params = {"api_key": GOVINFO_KEY}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print(f"[INGEST] Metadata error for {package_id}: {e}")
        return None


def store_bill_metadata(pkg, metadata):
    if not metadata:
        return None
    
    bill_type = metadata.get("billType", "")
    bill_number = metadata.get("billNumber", "")
    
    sponsor = None
    for member in metadata.get("members", []):
        if member.get("role") == "SPONSOR":
            sponsor = member.get("bioGuideId")
            break
    
    record = {
        "package_id": metadata.get("packageId"),
        "congress": int(metadata.get("congress", 119)),
        "bill_type": bill_type,
        "bill_number": int(bill_number) if bill_number else 0,
        "title": metadata.get("title", ""),
        "sponsor_bioguide": sponsor,
        "chamber": metadata.get("originChamber", ""),
        "date_issued": metadata.get("dateIssued"),
        "bill_version": metadata.get("billVersion", ""),
        "is_ceremonial": False,
        "text_fetched": False,
        "embedded": False,
    }
    
    try:
        result = supabase.table("bills").upsert(record).execute()
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        print(f"[INGEST] Store metadata error: {e}")
        return None


# ── Stage 3: Text fetch ──

def fetch_bill_text(package_id):
    url = f"https://api.govinfo.gov/packages/{package_id}/htm"
    params = {"api_key": GOVINFO_KEY}
    
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            return None
        
        # Strip HTML
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text()
        
        # Strip header boilerplate — everything before the actual bill text
        for marker in ["Be it enacted", "Resolved,", "RESOLUTION", "A BILL"]:
            idx = text.find(marker)
            if idx > 0:
                text = text[idx:]
                break
        
        # Clean whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        return text.strip()
        
    except Exception as e:
        print(f"[INGEST] Text fetch error for {package_id}: {e}")
        return None


# ── Stage 4: Chunking ──

def chunk_bill_text(text, package_id, congress, bill_type, bill_number):
    chunks = []
    
    # Split by section markers
    section_pattern = re.compile(
        r'(?=(?:SEC(?:TION)?\.?\s+\d+|§\s*\d+)[\.\s])',
        re.IGNORECASE
    )
    
    sections = section_pattern.split(text)
    
    # If no sections found, chunk by size
    if len(sections) <= 1:
        sections = chunk_by_size(text, max_tokens=500)
    
    for i, section in enumerate(sections):
        section = section.strip()
        if not section or len(section) < 50:
            continue
        
        # Extract section number and title from first line
        lines = section.split('\n')
        first_line = lines[0].strip()
        section_number = ""
        section_title = ""
        
        sec_match = re.match(r'(SEC(?:TION)?\.?\s+\d+)[.\s]+(.{0,100})', first_line, re.IGNORECASE)
        if sec_match:
            section_number = sec_match.group(1)
            section_title = sec_match.group(2).strip()
        
        chunks.append({
            "package_id": package_id,
            "congress": congress,
            "bill_type": bill_type,
            "bill_number": bill_number,
            "section_number": section_number,
            "section_title": section_title,
            "chunk_index": i,
            "chunk_text": section[:3000],  # hard cap
            "token_count": len(section.split()),
        })
    
    return chunks


def chunk_by_size(text, max_tokens=500):
    words = text.split()
    chunks = []
    overlap = 50
    
    i = 0
    while i < len(words):
        chunk = ' '.join(words[i:i+max_tokens])
        chunks.append(chunk)
        i += max_tokens - overlap
    
    return chunks


# ── Stage 5: Embedding ──

def embed_chunks(chunks):
    if not chunks:
        return chunks
    
    texts = [c["chunk_text"] for c in chunks]
    
    try:
        result = voyage.embed(
            texts,
            model="voyage-law-2",
            input_type="document"
        )

        for i, chunk in enumerate(chunks):
            chunk["embedding"] = result.embeddings[i]

        return chunks

    except Exception as e:
        print(f"[INGEST] Embedding error: {e}")
        return chunks


def embed_query(text: str) -> list[float]:
    result = voyage.embed([text], model="voyage-law-2", input_type="query")
    return result.embeddings[0]


def store_chunks(bill_id, chunks):
    for chunk in chunks:
        if "embedding" not in chunk:
            continue
        
        record = {
            "bill_id": bill_id,
            **{k: chunk[k] for k in [
                "package_id", "congress", "bill_type", "bill_number",
                "section_number", "section_title", "chunk_index",
                "chunk_text", "token_count", "embedding"
            ]}
        }
        
        try:
            supabase.table("bill_chunks").insert(record).execute()
        except Exception as e:
            print(f"[INGEST] Store chunk error: {e}")


# ── Main pipeline ──

def run_pipeline(congress=119, limit=None):
    print(f"[INGEST] Starting pipeline for {congress}th Congress")
    
    # Stage 1
    packages = discover_bills(congress)
    if limit:
        packages = packages[:limit]
    
    print(f"[INGEST] Processing {len(packages)} bills")
    
    success = 0
    failed = 0
    
    for i, pkg in enumerate(packages):
        package_id = pkg["packageId"]
        print(f"[INGEST] {i+1}/{len(packages)} — {package_id}")
        
        # Stage 2 — metadata
        metadata = fetch_metadata(package_id)
        bill_id = store_bill_metadata(pkg, metadata)
        if not bill_id:
            failed += 1
            continue
        
        # Stage 3 — text
        text = fetch_bill_text(package_id)
        if not text:
            failed += 1
            continue
        
        # Stage 4 — chunks
        bill_type = metadata.get("billType", "")
        bill_number = int(metadata.get("billNumber", 0) or 0)
        chunks = chunk_bill_text(text, package_id, congress, bill_type, bill_number)
        
        if not chunks:
            failed += 1
            continue
        
        # Stage 5 — embed
        chunks = embed_chunks(chunks)
        store_chunks(bill_id, chunks)
        
        # Mark as complete
        supabase.table("bills").update({
            "text_fetched": True,
            "embedded": True
        }).eq("id", bill_id).execute()
        
        success += 1
        
        # Rate limiting — GovInfo allows ~1000 req/hour
        time.sleep(0.5)
        
        # Progress report every 100 bills
        if (i + 1) % 100 == 0:
            print(f"[INGEST] Progress: {success} success, {failed} failed")
    
    print(f"[INGEST] Complete: {success} success, {failed} failed")


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_pipeline(congress=119, limit=limit)