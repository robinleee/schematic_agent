"""
Datasheet PDF 批量导入 ChromaDB 脚本

解析 /data/schematic_agent/datasheets/ 下的 PDF，
切片后嵌入 all-MiniLM-L6-v2 (384-dim) 存入 ChromaDB。

用法:
    cd /data/schematic_agent/hardware_ai_expert
    source /data/schematic_agent/.venv/bin/activate
    python -m agent_system.import_datasheets
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any

import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import chromadb

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path("/data/schematic_agent/datasheets")
COLLECTION_NAME = "hardware_knowledge"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 600
OVERLAP = 100


def extract_pdf_text(pdf_path: str) -> List[Dict[str, Any]]:
    """提取 PDF 每页文本"""
    pages = []
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc):
        text = page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        if text.strip():
            pages.append({"page": i + 1, "text": text})
    doc.close()
    return pages


def chunk_text_simple(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> List[str]:
    """简单可靠的切片：按段落/换行切，保证不无限循环"""
    if not text.strip():
        return []
    
    # 先按双换行分段
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        # 如果当前 chunk + 这段不超过限制，合并
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = (current_chunk + "\n\n" + para).strip() if current_chunk else para
        else:
            # 保存当前 chunk
            if current_chunk:
                chunks.append(current_chunk)
            # 如果单段超长，按固定长度切
            if len(para) > chunk_size:
                start = 0
                while start < len(para):
                    end = min(start + chunk_size, len(para))
                    # 尝试在换行处断开
                    if end < len(para):
                        nl = para.rfind('\n', start + chunk_size // 2, end)
                        if nl > start:
                            end = nl
                    chunk = para[start:end].strip()
                    if chunk:
                        chunks.append(chunk)
                    start = end
                current_chunk = ""
            else:
                current_chunk = para
    
    # 最后一个 chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def import_datasheets(data_dir: Path = DEFAULT_DATA_DIR, project_id: str = "default"):
    """批量导入 Datasheet PDF 到 ChromaDB
    
    Args:
        data_dir: Datasheet PDF 目录
        project_id: 项目 ID，用于多项目数据隔离
    """
    
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL} (CPU)")
    embedder = SentenceTransformer(EMBEDDING_MODEL, device='cpu')
    
    client = chromadb.HttpClient(host='localhost', port=8000)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    existing_count = collection.count()
    logger.info(f"ChromaDB '{COLLECTION_NAME}': {existing_count} existing chunks")
    
    pdf_files = sorted(data_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning(f"No PDF files in {data_dir}")
        return
    
    logger.info(f"Found {len(pdf_files)} PDFs")
    total_new = 0
    
    for pdf_path in pdf_files:
        mpn = pdf_path.stem.upper().replace("-", "")
        logger.info(f"\n--- {pdf_path.name} (MPN: {mpn}) ---")
        
        # Skip if already imported
        existing = collection.get(where={"mpn": mpn})
        if existing and len(existing['ids']) > 0:
            logger.info(f"  Already {len(existing['ids'])} chunks, skip")
            continue
        
        pages = extract_pdf_text(str(pdf_path))
        if not pages:
            logger.warning(f"  No text extracted")
            continue
        
        full_text = "\n\n".join(f"[Page {p['page']}] {p['text']}" for p in pages)
        logger.info(f"  {len(full_text)} chars, {len(pages)} pages")
        
        chunks = chunk_text_simple(full_text)
        logger.info(f"  {len(chunks)} chunks")
        if not chunks:
            continue
        
        # Embed in batches of 50
        batch_size = 50
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            embeddings = embedder.encode(batch, show_progress_bar=False).tolist()
            ids = [f"{mpn}_chunk_{i+j}" for j in range(len(batch))]
            metadatas = [
                {"mpn": mpn, "source": pdf_path.name, "chunk_index": i+j, "type": "datasheet", "char_count": len(batch[j]), "project_id": project_id}
                for j in range(len(batch))
            ]
            collection.add(ids=ids, documents=batch, embeddings=embeddings, metadatas=metadatas)
        
        total_new += len(chunks)
        logger.info(f"  ✅ {len(chunks)} chunks imported")
    
    final_count = collection.count()
    logger.info(f"\n{'='*40}")
    logger.info(f"Done! New: {total_new}, Total: {final_count} (was {existing_count})")
    
    # Quick verify
    if final_count > 0:
        logger.info("\nVerify: 'TPS63070 input voltage range'")
        results = collection.query(query_texts=["TPS63070 input voltage range"], n_results=2)
        for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
            logger.info(f"  [{meta['mpn']}] {doc[:150]}...")


if __name__ == "__main__":
    import_datasheets()
