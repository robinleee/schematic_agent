"""
Datasheet processing pipeline.

End-to-end pipeline: PDF → text extraction → chunking → embedding → storage
in both ChromaDB (via KnowledgeRouter) and Neo4j VectorChunk nodes
(via GraphRAGBridge).
"""

from __future__ import annotations

import os
import re
import logging
import hashlib
from datetime import datetime
from typing import Optional

from agent_system.embedding import embed, embed_batch, EMBEDDING_DIM
from agent_system.graph_rag_bridge import GraphRAGBridge, VectorChunk
from agent_system.knowledge_router import KnowledgeRouter, DatasheetChunk

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split text into overlapping chunks of approximately chunk_size characters.

    Tries to break at sentence/line boundaries for cleaner chunks.
    """
    if not text or not text.strip():
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            # Try to break at a sentence or line boundary
            for sep in ['\n\n', '. ', '\n', '; ']:
                boundary = text.rfind(sep, start + chunk_size // 2, end)
                if boundary > start:
                    end = boundary + len(sep)
                    break

        chunk_content = text[start:end].strip()
        if chunk_content:
            chunks.append({
                "content": chunk_content,
                "char_start": start,
                "char_end": end,
            })

        start = end - overlap
        if start <= chunks[-1]["char_start"] if chunks else 0:
            start = end

    return chunks


class DatasheetPipeline:
    """
    Full datasheet processing pipeline.

    1. Extract text from PDF (via PyMuPDF or DatasheetParser)
    2. Chunk text into ~500 char segments
    3. Generate embeddings with unified sentence-transformers model
    4. Store in ChromaDB (via KnowledgeRouter) + Neo4j VectorChunk (via GraphRAGBridge)
    """

    def __init__(self, use_llm: bool = False):
        self.router = KnowledgeRouter()
        self.bridge = GraphRAGBridge()
        self.use_llm = use_llm

    def process_pdf(
        self,
        pdf_path: str,
        filename: str = "",
        component_hint: Optional[str] = None,
        mpn_hint: Optional[str] = None,
    ) -> dict:
        """
        Process a single PDF datasheet through the full pipeline.

        Returns dict with keys: success, mpn, chunks_indexed, error
        """
        filename = filename or os.path.basename(pdf_path)

        try:
            # Step 1: Extract text
            logger.info(f"Extracting text from {filename}")
            text, page_texts = self._extract_text(pdf_path)

            if not text.strip():
                return {"success": False, "mpn": "", "chunks_indexed": 0, "error": "No text extracted from PDF"}

            # Determine MPN
            mpn = mpn_hint or self._infer_mpn(filename, text)

            # Step 2: Also try structured parameter extraction
            params = {}
            try:
                params = self._extract_parameters(pdf_path, component_hint)
            except Exception as e:
                logger.warning(f"Parameter extraction failed for {filename}: {e}")

            # Step 3: Chunk text
            chunks = []
            for page_num, page_text in page_texts.items():
                page_chunks = chunk_text(page_text)
                for chunk in page_chunks:
                    chunk["page"] = page_num
                    chunks.append(chunk)

            if not chunks:
                # Fallback: chunk the entire text as one
                chunks = chunk_text(text)
                for chunk in chunks:
                    chunk["page"] = 0

            # Enrich first chunk with extracted parameters if available
            if params and chunks:
                param_text = self._params_to_text(params)
                chunks[0]["content"] = param_text + "\n\n" + chunks[0]["content"]

            logger.info(f"Created {len(chunks)} chunks for {filename} (MPN: {mpn})")

            # Step 4: Store in ChromaDB + Neo4j
            indexed = 0
            for i, chunk in enumerate(chunks):
                chunk_id = f"{mpn}_p{chunk.get('page', 0)}_{i:03d}"
                content = chunk["content"]
                page = chunk.get("page", 0)

                # ChromaDB
                ds_chunk = DatasheetChunk(
                    mpn=mpn,
                    page=page,
                    content=content,
                    chunk_type="datasheet",
                    content_hash=hashlib.md5(content.encode()).hexdigest(),
                )
                chroma_ok = self.router.tier1.add_chunk(ds_chunk)

                # Neo4j VectorChunk
                vc = VectorChunk(
                    chunk_id=chunk_id,
                    mpn=mpn,
                    content=content,
                    chunk_type="datasheet",
                    page=page,
                    source=filename,
                )
                neo4j_ok = self.bridge.index_datasheet_chunk(vc)

                if chroma_ok or neo4j_ok:
                    indexed += 1

            logger.info(f"Indexed {indexed}/{len(chunks)} chunks for {mpn}")

            return {
                "success": True,
                "mpn": mpn,
                "chunks_indexed": indexed,
                "total_chunks": len(chunks),
                "parameters": params,
            }

        except Exception as e:
            logger.error(f"Pipeline failed for {filename}: {e}")
            return {"success": False, "mpn": mpn_hint or "", "chunks_indexed": 0, "error": str(e)}

    def _extract_text(self, pdf_path: str) -> tuple[str, dict[int, str]]:
        """Extract text from PDF, return (full_text, {page_num: page_text})."""
        import fitz

        doc = fitz.open(pdf_path)
        full_parts = []
        page_texts = {}

        for i, page in enumerate(doc):
            text = page.get_text()
            page_texts[i] = text
            full_parts.append(text)

        doc.close()
        return "\n".join(full_parts), page_texts

    def _infer_mpn(self, filename: str, text: str) -> str:
        """Infer MPN from filename or first page text."""
        # Try filename first
        name = os.path.splitext(os.path.basename(filename))[0]
        # Clean up common prefixes
        name = re.sub(r'^(datasheet|spec|specification)_', '', name, flags=re.IGNORECASE)
        if len(name) > 3 and re.search(r'[0-9]', name):
            return name

        # Try to find MPN in first 2000 chars
        patterns = [
            r'(?:MPN|Part Number|Ordering Number)[:\s]+([A-Z0-9][A-Z0-9\-\.]+)',
            r'([A-Z]{2,4}[0-9]{3,}[A-Z0-9\-]*)',
        ]
        for pat in patterns:
            m = re.search(pat, text[:2000])
            if m:
                return m.group(1)

        return name

    def _extract_parameters(self, pdf_path: str, component_hint: str = "") -> dict:
        """Extract structured parameters using DatasheetParser."""
        try:
            from agent_system.datasheet_parser import DatasheetParser
            parser = DatasheetParser(use_llm=self.use_llm)
            result = parser.parse_pdf(pdf_path, component_hint=component_hint or "")

            params = {}
            for p in result.parameters:
                key = p.param_type.value if hasattr(p.param_type, 'value') else str(p.param_type)
                params[key] = {
                    "value": p.value,
                    "unit": p.unit,
                    "typical": p.typical_value,
                    "min": p.min_value,
                    "max": p.max_value,
                }
            return params
        except Exception as e:
            logger.warning(f"Parameter extraction failed: {e}")
            return {}

    @staticmethod
    def _params_to_text(params: dict) -> str:
        """Convert extracted parameters to searchable text."""
        lines = ["[Extracted Parameters]"]
        for key, val in params.items():
            if isinstance(val, dict):
                parts = [f"{key}: {val.get('value', '')}"]
                if val.get('unit'):
                    parts.append(val['unit'])
                if val.get('typical'):
                    parts.append(f"(typical: {val['typical']})")
                if val.get('max'):
                    parts.append(f"(max: {val['max']})")
                lines.append(" ".join(parts))
            else:
                lines.append(f"{key}: {val}")
        return "\n".join(lines)

    def close(self):
        self.bridge.close()


def process_datasheet_file(
    pdf_path: str,
    component_hint: str = "",
    mpn_hint: str = "",
) -> dict:
    """Convenience function to process a single datasheet."""
    pipeline = DatasheetPipeline()
    try:
        return pipeline.process_pdf(pdf_path, component_hint=component_hint, mpn_hint=mpn_hint)
    finally:
        pipeline.close()
