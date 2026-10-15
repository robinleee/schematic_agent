# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hardware AI Expert System for schematic review and fault diagnosis using EDA heterogeneous data graph + self-developed GraphRAG + ReAct Agent.

**Core services:**
- Neo4j 5.26 (bolt://localhost:7687) — graph database storing component/net/pin topology + native vector index (VectorChunk nodes). Credentials via `.env` (NEO4J_USER / NEO4J_PASSWORD), never hardcoded.
- Ollama (http://localhost:11434, model: gemma4:26b) — LLM + embedding backend, 51.9 tok/s
- FastAPI (http://localhost:8501) — backend API + WebSocket, docs at /docs
- React frontend (Vite dev :3000) — 7 page routes, Ant Design, WebSocket streaming chat; live seven-page validation is still pending

**Current completion: ~95%** (per `docs/product/PRD_GAP_ANALYSIS_V2.md`, 2026-10-14 cross-check — all four P0 items are done: BOM CSV import, embedding model switch to bge-m3, frontend/backend API schema audit, and HITL Datasheet-to-Neo4j persistence. P2 Cypher perf benchmark and the single full-chain E2E test are also done — the latter already existed in `tests/test_full_chain_e2e.py` and was previously mis-reported as missing. Remaining: P1 LlamaIndex bridge code disposition decision — `agent_system/llama_index_bridge.py` is a zero-reference, zero-test module in tension with the "self-developed GraphRAG, not LlamaIndex" architecture decision; see `docs/product/DEV_STATUS_AUDIT_2026-10-14.md`. Also pending: test coverage (43.99% measured, below the 60% target), vLLM (blocked on CUDA wheel version, not driver incompatibility as previously stated), Neo4j read-only DB account)

## Living Documents

- `docs/README.md` — Documentation navigation entry point
- `docs/product/PRD_V5.1.md` — Product Requirements (current baseline, tech selection writeback)
- `docs/architecture/TECHNICAL_IMPLEMENTATION_PLAN.md` — Technical plan V2.0 (code-accurate as of commit `d0c746d`)
- `docs/product/PRD_GAP_ANALYSIS_V2.md` — Latest gap analysis (single source of truth for remaining work)
- `archive/` — outdated analysis docs (PRD V4.0/V5.0, PROJECT_ANALYSIS, ROADMAP_NEXT, etc.)

## Commands

```bash
# Enter venv
source .venv/bin/activate

# Review engine test
cd hardware_ai_expert
python3 -c "
from agent_system.review_engine import ReviewRuleEngine
from agent_system.graph_tools import _get_driver
engine = ReviewRuleEngine(_get_driver())
violations = engine.run_rules()
print(f'Total violations: {len(violations)}')
"

# Agent end-to-end (ReActAgent, primary)
python3 -c "
from agent_system.react_agent import ReActAgent
agent = ReActAgent()
result = agent.run('检查板子上的去耦电容')
print(result)
"

# ETL validation
python3 etl_pipeline/run_etl_validation.py

# Run real ETL
python3 etl_pipeline/run_real_etl.py

# Full unit tests (283 cases in tests/ + 22 in root)
python3 -m pytest tests/ -v

# GraphRAG retrieval test
python3 -c "
from agent_system.graph_rag.pipeline import GraphRAGPipeline
pipe = GraphRAGPipeline()
result = pipe.query('TPS5430 输出电压范围', mode='auto')
print(result)
"

# Mainline: build React for FastAPI's single-port SPA, then start the services
cd /data/schematic_agent/frontend && npm run build
cd /data/schematic_agent && bash scripts/start_dev.sh
# Alternatively, run npm run dev from frontend/ for Vite at :3000 (proxy to FastAPI :8501).
```

## Architecture

```
React Frontend (frontend/) ──HTTP/WS──► FastAPI (:8501) api/main.py
                                          │
                              ┌───────────┴────────────┐
                              ▼                        ▼
                     AgentOrchestrator           WebSocket chat_ws.py
                  (agent_orchestrator.py)        (streaming chat)
                    │ routes by intent
        ┌───────────┼───────────┐
        ▼           ▼           ▼
  ReviewAgent  DiagnosisAgent  QueryAgent
  (9 tools)    (10 tools)      (8 tools)
        └───────────┼───────────┘
                    ▼ (fallback)
              ReActAgent (react_agent.py, primary)
              Thought→Action→Observation, MAX_STEPS=10
              16 graph tools + run_review + search_knowledge

ReviewRuleEngine (review_engine/engine.py)
    ├── RuleConfigManager → default_rules.yaml (24 rules)
    ├── TemplateRegistry → 9 templates (decap/pullup/esd/amr/pinmux
    │   /voltage_compat/power_integrity/connectivity/diff_pair)
    ├── WhitelistManager → filters false positives
    ├── per-project_id singleton + mtime hot-reload
    └── context → RuleContext(neo4j_driver) for Cypher queries

Graph Tools (graph_tools.py)
    ├── 16 Cypher tools, project_id isolation
    ├── CYPHER_ROW_LIMIT=500 + smart aggregation (no more MAX=50 truncation)
    ├── get_component_nets / get_net_components / get_power_domain
    ├── get_power_tree / get_i2c_devices / get_signal_path
    ├── discover_diff_pairs / trace_differential_pair (224 pairs)
    ├── get_common_cause_graph / common_cause_risk_score
    └── trace_power_chain / trace_fault_root

KnowledgeRouter (knowledge_router.py)
    ├── Tier 0: GraphRAG (threshold 0.3)
    ├── Tier 1: local knowledge base
    ├── Tier 2: PLM API (stub)
    └── Tier 3: tier3_retriever.py (9 supplier templates, pure Python)

Self-developed GraphRAG (agent_system/graph_rag/)
    ├── GraphRAGPipeline: query(mode=local/global/graph/auto)
    ├── Neo4jVectorIndexer: dual-track native vector index — legacy `chunk_embedding`
    │   (384-dim, all-MiniLM-L6-v2) + `chunk_embedding_v2` (1024-dim, bge-m3), side by side
    ├── HardwareEntityExtractor + CommunityDetector (Louvain, 22 communities)
    └── 7595 VectorChunk (1901 legacy 384-dim + 5694 bge-m3 1024-dim) / 10504 [:DESCRIBES] relations

ETL Pipeline (etl_pipeline/)
    ├── chip_parser / prt_parser / net_parser → Cadence netlist parse
    ├── part_type_standardizer / refine_passive_types → PartType UNKNOWN=1
    ├── expand_voltage_annotation → POWER net coverage 95.7%
    ├── generate_power_tree → 593 [:POWERED_BY] edges
    ├── quality_guard → PartType≥90% + core net recognition (network-level, V5.1)
    └── main_etl → orchestrates parse → Pydantic validation → Neo4j UNWIND MERGE
```

## Data Quality Status (Beet7 netlist)

| Metric | Value | Status |
|--------|-------|--------|
| Components / Pins / Nets | 12,688 / 49,570 / 8,159 | ✅ |
| Pin.Type coverage | 100% | ✅ fixed |
| PartType UNKNOWN | 1 | ✅ fixed |
| [:POWERED_BY] edges | 593 | ✅ created |
| VectorChunk | 7,595 (1,901 legacy 384-dim + 5,694 bge-m3 1024-dim) | ✅ bge-m3 index rebuilt |
| Core net recognition | 1068/1076 valid core nets (99.3%) | ✅ network-level check implemented; 8 suspicious stubs detected |
| POWER net voltage coverage | 95.7% | ✅ |
| AMR capacitor voltage coverage | 83.1% | ⚠️ target ≥95% |

## Key Design Decisions

- **Agent**: self-developed ReActAgent + AgentOrchestrator (not LangGraph) — LLM-driven, not hardcoded
- **GraphRAG**: self-developed graph_rag/ (not LlamaIndex) — Neo4j native vector index, not ChromaDB dual-write
- **LLM**: local Ollama gemma4:26b (not vLLM — T4 driver incompatible) for data security
- **Embedding**: sentence-transformers BAAI/bge-m3 (1024-dim, default since `c2fb8b0`); legacy all-MiniLM-L6-v2 (384-dim) index kept side by side as `chunk_embedding` for rollback, new data goes to `chunk_embedding_v2`
- **Frontend**: React + TypeScript / FastAPI is the mainline. `web_ui/app.py` is a legacy Streamlit fallback, not started by `scripts/start_dev.sh`; do not archive until the seven React pages have been validated live against their core flows.
- **Review engine**: 3-layer (Template + Config + Knowledge), 9 templates / 24 rules, mtime hot-reload
- **Multi-project isolation**: project_id propagated across full chain (ETL, graph, review, knowledge)
- **Read-only safety**: app-level READ_ONLY_MODE env var (Neo4j Community Edition lacks DB-level read-only users)
- Rule config: `review_engine/config/default_rules.yaml` — edit to add/modify rules (hot-reloads on mtime change)

## File Locations

```
hardware_ai_expert/
├── agent_system/
│   ├── react_agent.py          # ReActAgent (primary, 786 lines)
│   ├── agent_orchestrator.py   # AgentOrchestrator + 3 specialized agents (294 lines)
│   ├── agent_core.py           # Legacy HardwareAgent (1366 lines, fallback)
│   ├── graph_tools.py          # 16 Cypher tools, project_id isolation, CYPHER_ROW_LIMIT=500
│   ├── knowledge_router.py     # Tier0-3 search routing
│   ├── llm_client.py           # LLM client + cache TTL (1h + 50% eviction)
│   ├── amr_engine.py / mpn_decoder.py / tier3_retriever.py
│   ├── datasheet_parser.py / datasheet_hitl.py / hitl_workflow.py
│   ├── graph_rag/              # Self-developed GraphRAG
│   │   ├── pipeline.py         # GraphRAGPipeline (local/global/graph/auto)
│   │   ├── indexers/           # vector_indexer / entity_extractor / community_detector
│   │   └── retrievers/         # local / global / graph retrievers
│   ├── review_engine/
│   │   ├── engine.py           # ReviewRuleEngine (per-project_id singleton + mtime hot-reload)
│   │   ├── whitelist.py
│   │   ├── config/default_rules.yaml  # 24 rules
│   │   └── templates/          # 9 templates
│   └── schemas/                # Pydantic models
├── api/
│   ├── main.py                 # FastAPI app (:8501)
│   ├── routers/                # 7 routers (chat/review/hitl/knowledge/etl/graph/system)
│   └── websocket/chat_ws.py    # WebSocket streaming chat
├── etl_pipeline/
│   ├── chip_parser.py / prt_parser.py / net_parser.py
│   ├── main_etl.py / part_type_standardizer.py / refine_passive_types.py
│   ├── expand_voltage_annotation.py / generate_power_tree.py
│   └── quality_guard.py        # PartType≥90% + core net recognition
├── web_ui/app.py               # Legacy Streamlit (1973 lines, fallback)
├── tests/                      # 8 test files, 283 test cases
└── data/                       # chroma_db/ datasheets/ kb/ neo4j/ netlist_Beet7/ output/

frontend/                       # React + TypeScript frontend
├── src/
│   ├── pages/                  # 7 pages (Chat/Review/HITL/Knowledge/ETL/Graph/System)
│   ├── components/             # ReasoningChain / graph_viz
│   └── hooks/                  # useChatWebSocket
└── package.json / vite.config.ts
```
