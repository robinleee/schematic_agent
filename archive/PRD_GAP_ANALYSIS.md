# PRD Gap Analysis — Hardware AI Expert System

> Date: 2026-05-14 | Baseline: PRD_V5.0 vs actual code as of commit `8d70e2d`
> Methodology: Cross-reference PRD_V5.0 requirements against source code, Neo4j data, and previous analysis (PROJECT_STATUS_ANALYSIS.md)

---

## 1. PRD Requirements Summary

### 1.1 Data Foundation (ETL) — PRD §4

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| D1 | Pin.Name mandatory capture with fallback | §4.1 |
| D2 | PartType intelligent standardization (NLP/dictionary, not regex) | §4.1 |
| D3 | Quality Guard: PartType coverage < 90% → block; core net recognition < 100% → block | §4.2 |
| D4 | BOM Description field import for PartType mapping | §4.1 |
| D5 | Network voltage annotation (currently 17.3%) | Implied by power domain analysis |

### 1.2 Agent Core & Intent Router — PRD §5

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| A1 | LLM Intent Router replacing keyword matching | §5.1 |
| A2 | Composite intent decomposition (task queue) | §5.1 |
| A3 | MAX_STEPS = 15 with Self-Correction node | §5.2 |
| A4 | LLM ReAct loop (not hardcoded state machine) | §5 (implicit from "task queue executor") |

### 1.3 Review Engine — PRD §5 (review branch)

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| R1 | Layer 3 (Knowledge): Datasheet-driven rule parameter injection | §7.2 |
| R2 | AMR capacitor voltage derating (currently skipped) | §7.2 |
| R3 | Whitelist HITL approval flow in Web UI | §7.2 |

### 1.4 Graph Tools & Smart Aggregation — PRD §6

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| G1 | Cypher computation pushdown replacing 50-node truncation | §6.1 |
| G2 | Feature aggregation for large networks (GND/VCC) | §6.1 |
| G3 | `trace_differential_pair(start_pin)` for PCIe/MIPI | §6.2 |
| G4 | `get_power_tree()` based on [:POWERED_BY] relationships | §6.2 |

### 1.5 True GraphRAG & Knowledge System — PRD §7

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| K1 | LlamaIndex + llama-index-graph-stores-neo4j integration | §3.2 |
| K2 | [:DESCRIBES] relationships: VectorChunk → Component | §7.1 |
| K3 | Joint retrieval: semantic + topology in single query | §7.1 |
| K4 | HITL rule precipitation: LLM extract → Pending_Review → Approve → inject into rules | §7.2 |
| K5 | Tier 1/2/3 knowledge retrieval with auto-caching | §8 (V4) |

### 1.6 Web UI & Visualization — PRD §8 (V4) / §3.1 (V5)

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| W1 | Streamlit interactive chat interface | §8/V4 |
| W2 | Reasoning chain visualization (Thought → Action → Observation) | §10.2/V4 |
| W3 | Neo4j subgraph visualization (PyVis/ECharts) | §10.2/V4 |
| W4 | HITL approval dashboard | §7.2/V5 |
| W5 | Review report with severity filtering and export | §10/V4 |

### 1.7 HITL Workflow — PRD §7.2

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| H1 | LLM-extracted AMR parameters → Pending_Review status | §7.2 |
| H2 | Engineer approval via Web UI | §7.2 |
| H3 | Approved parameters injected into `default_rules.yaml` and AMR engine | §7.2 |

### 1.8 Testing & Quality — PRD §12 (V4)

| # | Requirement | PRD Reference |
|---|-------------|---------------|
| T1 | Neo4j read-only account for graph_tools | §14.2/V4 |
| T2 | Unit test coverage > 60% | §F/V4 |
| T3 | E2E integration test: netlist → ETL → review → report | §F/V4 |
| T4 | Cypher query performance benchmark < 500ms | §12.2/V4 |

---

## 2. Implementation Status Matrix

### 2.1 Data Foundation (ETL)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| D1 | Pin.Name capture | ⚠️ Partial | `chip_parser.py` parses PINUSE for Type, but Pin.Name remains largely unmapped in Neo4j |
| D2 | PartType standardization | ✅ Done | `part_type_standardizer.py` (19.8KB, regex+dictionary), 99.1% coverage, UNKNOWN down to 0.9% |
| D3 | Quality Guard | ✅ Done | `quality_guard.py` (10.4KB) with circuit breaker, PartType < 90% → `QualityGuardException` |
| D4 | BOM import | ❌ Not Done | No CSV/BOM import module exists; `etl_import.py` UI page exists but handles netlists only |
| D5 | Network voltage annotation | ⚠️ Partial | `amr_engine.py:VoltageLevelExtractor` handles patterns, but only 17.3% of nets annotated |

### 2.2 Agent Core & Intent Router

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| A1 | LLM Intent Router | ✅ Done | `llm_intent_router.py` (492 lines), 12 intent types, structured JSON output, keyword fallback |
| A2 | Composite intent decomposition | ⚠️ Partial | `LLMIntentRouter` detects `COMPOSITE` intent and extracts `sub_queries`, but `agent_core.py` doesn't execute them sequentially — maps to `SPEC_QUERY` instead |
| A3 | MAX_STEPS + Self-Correction | ⚠️ Partial | `MAX_TOOL_CALLS=20`, `MAX_STEPS=30` exist. No Self-Correction node (LLM adjusting Cypher on empty results). ReAct engine has `MAX_REACT_STEPS=6` with force-final. |
| A4 | LLM ReAct loop | ⚠️ Partial | `ReActDiagnosisEngine` (lines 759-1179) implements full ReAct for **diagnosis only**. Review and query tasks still use hardcoded state machine. |

### 2.3 Review Engine

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| R1 | Layer 3 Knowledge | ❌ Not Done | `engine.py` has no knowledge-driven parameter injection. All rule params from YAML only. |
| R2 | AMR capacitor derating | ❌ Not Done | `CapacitorVoltageChecker` exists but `AMRDataSource.get_capacitor_voltage_rating()` returns None. `DatasheetHITLManager.save_approved_to_amr()` writes to `amr_data.yaml` but the loop is untested. |
| R3 | Whitelist HITL in Web UI | ✅ Done | `hitl_workflow.py` + Web UI HITL page with approve/reject/persist flow |

### 2.4 Graph Tools & Smart Aggregation

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| G1 | Cypher computation pushdown | ✅ Done | `graph_tools.py` removed `MAX_RESULTS=50` hard truncation; uses `DEFAULT_AGGREGATION_THRESHOLD=100` with Cypher-level `count()` + `collect(DISTINCT ...)[0..5]` |
| G2 | Feature aggregation | ✅ Done | `get_net_components()` returns aggregated summary by PartType when count > threshold |
| G3 | `trace_differential_pair` | 🔲 Stub | Function exists (line 560-580) but returns placeholder text: "Phase 3 实现计划" |
| G4 | `get_power_tree` | ✅ Done | 3 modes: by root_refdes, by voltage, overview. Uses Cypher to trace power paths. |

### 2.5 True GraphRAG & Knowledge System

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| K1 | LlamaIndex integration | ❌ Not Done | No `llama-index` or `llama-index-graph-stores-neo4j` in any import. Custom `GraphRAGBridge` uses Neo4j native approach. |
| K2 | [:DESCRIBES] relationships | ✅ Done | `graph_rag_bridge.py:253` creates `(VectorChunk)-[:DESCRIBES]->(Component)` with confidence and rel_type |
| K3 | Joint semantic + topology retrieval | ⚠️ Partial | `graph_rag_query()` supports refdes-based traversal and mpn-based vector search, but both use Python-layer cosine similarity, not Neo4j native vector index. `gds.similarity.cosine` is attempted but falls back to Python. |
| K4 | HITL rule precipitation | ⚠️ Partial | `datasheet_hitl.py` → `hitl_workflow.py` pipeline exists end-to-end. `save_approved_rules()` writes to YAML. But the full loop (Datasheet PDF → extract → review → inject into ReviewRuleEngine) is **untested with real data**. |
| K5 | Tier 1/2/3 retrieval | ⚠️ Partial | Tier 1 (ChromaDB): framework done, **3 records only**. Tier 2 (PLM): `self.tier2 = None`. Tier 3 (Public): `PublicMPNRetriever` exists but `enabled = False`. Auto-caching to Tier 1 implemented. |

### 2.6 Web UI & Visualization

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| W1 | Streamlit chat interface | ✅ Done | `app.py` (1617 lines), `render_chat()` with `HardwareAgent.review()`, typing indicator, message history |
| W2 | Reasoning chain visualization | ❌ Not Done | No `execution_trace` rendering in Web UI. `AgentState.execution_trace` exists but unused in frontend. |
| W3 | Neo4j subgraph visualization | ❌ Not Done | No PyVis/ECharts integration. Quick graph query section only shows text output. |
| W4 | HITL approval dashboard | ✅ Done | `render_hitl()` with pending/approved/rejected tabs, approve/reject buttons, persist-to-YAML |
| W5 | Review report + filtering + export | ✅ Done | `render_review_report()` with severity badges, filtering, bar charts, Markdown export |

### 2.7 HITL Workflow

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| H1 | AMR parameter extraction → Pending | ⚠️ Partial | `datasheet_parser.py` extracts parameters; `datasheet_hitl.py` puts them in Pending state. But the pipeline from **real PDF** through to Pending is unvalidated — parser uses regex, LLM extraction optional. |
| H2 | Engineer approval in Web UI | ✅ Done | Full approve/reject/modify UI in `render_datasheet_hitl()` |
| H3 | Approved → inject into rules/AMR | ⚠️ Partial | `save_approved_to_amr()` writes to `amr_data.yaml`; `save_approved_rules()` writes to `custom_rules.yaml`. But `AMRDataSource` reads from `FileBasedAMRSource` which may not auto-reload. And `ReviewRuleEngine` loads rules at init — no hot-reload. |

### 2.8 Testing & Quality

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| T1 | Neo4j read-only account | ❌ Not Done | `_get_driver()` uses `NEO4J_USER` (default "neo4j") — full admin access |
| T2 | Unit test coverage > 60% | ❌ Not Done | ~1,124 lines of test code across 5 files; estimated coverage < 40% |
| T3 | E2E integration test | ❌ Not Done | No automated E2E test; `run_etl_validation.py` validates ETL only |
| T4 | Cypher performance benchmark | ❌ Not Done | No benchmarking infrastructure; PRD target < 500ms unverified |

---

## 3. Detailed Gap Analysis

### 3.1 [P0] True GraphRAG — LlamaIndex Not Integrated

**PRD Requires (§7.1):** Use LlamaIndex + `llama-index-graph-stores-neo4j` to bridge ChromaDB document chunks with Neo4j entities via `[:DESCRIBES]` relationships, enabling joint semantic+topology retrieval in a single query.

**What Exists:** `graph_rag_bridge.py` (568 lines) implements a custom GraphRAG bridge using:
- Neo4j-native `VectorChunk` nodes (not ChromaDB) with embedding vectors stored as node properties
- Python-layer cosine similarity (not Neo4j GDS vector index)
- Local hash-based or Ollama embeddings (not a proper embedding model like `bge-large-zh-v1.5`)
- Attempted `gds.similarity.cosine` Cypher function but falls back to Python

**The Gap:**
1. No LlamaIndex dependency or integration anywhere
2. Embedding quality is poor — character-frequency hash vectors (lines 161-187) or Ollama `gemma4:26b` embeddings (not an embedding model)
3. `ChromaDB` has only 3 records — effectively empty, making Tier 1 retrieval useless
4. No proper embedding model (e.g., `bge-large-zh-v1.5`) for Chinese+English hardware specs

**Impact: P0** — Without quality embeddings and a populated vector store, the entire "knowledge brain" is non-functional. The agent cannot retrieve Datasheet specifications, making spec queries and AMR data lookup fail.

**Estimated Effort:** 3-5 days (install `llama-index` stack, configure proper embedding model, bulk-import datasheets)

### 3.2 [P0] Knowledge Base Is Empty — ChromaDB Has 3 Records

**PRD Requires (§7):** A populated knowledge base with Datasheet chunks enabling semantic retrieval.

**What Exists:** `knowledge_router.py` framework is complete, `datasheet_parser.py` (714 lines) can parse PDFs, `web_ui/pages/knowledge_base.py` (22.8KB) provides upload UI. But ChromaDB contains only 3 test records.

**The Gap:** The entire ingestion pipeline exists but has never been run with real data. No Datasheet PDFs have been bulk-imported.

**Impact: P0** — Tier 1 retrieval always returns "not found". The agent's spec_query and diagnosis capabilities degrade to graph-only queries.

**Estimated Effort:** 2-3 days (batch-import available datasheets, validate retrieval quality)

### 3.3 [P0] AMR Capacitor Derating Non-Functional

**PRD Requires (§5/§7.2):** Capacitor voltage derating checks with data sourced from Datasheet extraction → HITL approval → AMR data source.

**What Exists:** Full pipeline chain: `datasheet_parser.py` → `datasheet_hitl.py` → `amr_data.yaml` → `AMRDataSource`. But `AMRDataSource.get_capacitor_voltage_rating()` still returns `None` because:
1. No real datasheets have been parsed and approved through the HITL flow
2. `FileBasedAMRSource` reads from `amr_data.yaml` which is empty or doesn't exist
3. The complete cycle (PDF → extract → approve → write YAML → read in AMR check) is **untested end-to-end**

**Impact: P0** — One of the 5 review templates (AMR) is only partially functional. Capacitor voltage derating is the most common AMR check for hardware reliability.

**Estimated Effort:** 2-3 days (import 10-20 real datasheets, validate end-to-end, fix any breaks)

### 3.4 [P1] Composite Intent Not Executed as Task Queue

**PRD Requires (§5.1):** LLM Router outputs structured task queue for composite intents, executed sequentially.

**What Exists:** `LLMIntentRouter` detects `COMPOSITE` intent and extracts `sub_intents`. But `agent_core.py:task_classifier_node()` maps `IntentType.COMPOSITE` → `TaskType.SPEC_QUERY` (line 213), losing the decomposition. The sub-intents are stored in `state.context["sub_intents"]` but never executed.

**The Gap:** The router correctly identifies composite queries like "check I2C pullup + TPS5430 VOUT formula" but the execution engine treats it as a single generic query. No task queue, no sequential execution.

**Impact: P1** — Users asking multi-part questions get incomplete answers. Undermines the value of the LLM router.

**Estimated Effort:** 3-4 days (add task queue executor in `HardwareAgent._run()`, execute sub-intents sequentially, merge results)

### 3.5 [P1] No Reasoning Chain Visualization in Web UI

**PRD Requires (§10.2/V4):** Thought → Action → Observation visualization for agent transparency.

**What Exists:** `AgentState.execution_trace` and `ReActTraceStep` contain full step-by-step data. The Web UI chat page (`render_chat()`) only shows the final report text — no execution trace rendering.

**The Gap:** All the backend data exists. The frontend just doesn't display it.

**Impact: P1** — Engineers cannot verify how the agent reached its conclusions. Critical for trust and debugging.

**Estimated Effort:** 1-2 days (add collapsible trace section in chat response, render ReAct steps)

### 3.6 [P1] No Neo4j Graph Visualization

**PRD Requires (§10.2/V4):** Interactive graph visualization for query-related subgraphs (PyVis/ECharts).

**What Exists:** System status page has a "Quick Graph Query" section that returns text output. No visual graph rendering.

**The Gap:** No PyVis, ECharts, or `st.graphviz_chart` integration. The Web UI cannot render topology visually.

**Impact: P1** — Graph topology is the core value proposition. Text-only output limits usability for engineers who think visually about schematics.

**Estimated Effort:** 2-3 days (integrate PyVis/`streamlit-agraph`, add query-to-subgraph rendering)

### 3.7 [P1] BOM Standardization Import Not Implemented

**PRD Requires (§4.1/§12.3):** Standardized CSV BOM import template; BOM Description field for PartType mapping.

**What Exists:** `web_ui/pages/etl_import.py` (15.2KB) handles Cadence netlist upload only. No CSV BOM import. `part_type_standardizer.py` operates on existing Neo4j data, not on incoming BOM data.

**The Gap:** No BOM import pipeline. Engineers cannot import BOM data (MPN, Description, Manufacturer) which is the primary source for PartType classification and AMR parameter lookup.

**Impact: P1** — Without BOM data, the system relies entirely on netlist-derived attributes. MPN mapping and Datasheet linking are severely limited.

**Estimated Effort:** 3-4 days (BOM CSV parser, mapping to Component nodes, Description → PartType enhancement, UI upload flow)

### 3.8 [P1] Network Voltage Annotation at 17.3%

**PRD Requires (§4.2):** Core network (VCC/GND/3V3 etc.) recognition rate < 100% → block.

**What Exists:** `VoltageLevelExtractor` in `amr_engine.py` supports ~10 voltage patterns. Currently only 1,416 / 8,159 (17.3%) of nets have `VoltageLevel` annotated.

**The Gap:** The pattern list is too limited. Many real-world naming conventions are missing (e.g., `VDDQ`, `VPP`, `VTT`, `1V0_DDR`, project-specific names like `VCC_WL_1V8`).

**Impact: P1** — Power domain analysis and AMR checks are inaccurate for 82.7% of nets. The Quality Guard threshold (100% for core nets) is not enforced for voltage annotation.

**Estimated Effort:** 1-2 days (extend pattern list, add project-specific conventions, batch-annotate remaining nets)

### 3.9 [P1] Tier 2/3 Knowledge Retrieval Not Connected

**PRD Requires (§8/V4):** Tier 2 (PLM) and Tier 3 (public API) with auto-caching to Tier 1.

**What Exists:** `KnowledgeRouter.tier2 = None`, `PublicMPNRetriever.enabled = False`. The interface stubs are clean, but no real integration.

**The Gap:** No PLM API integration. No Octopart/Mouser/DigiKey API integration. The auto-caching mechanism (`_cache_to_tier1`) is implemented but never triggered.

**Impact: P1** — When Tier 1 (local) has no data (currently always), the system has no fallback. Cold-start problem for any component not in the local knowledge base.

**Estimated Effort:** 2-3 days per tier (API integration, rate limiting, caching, error handling)

### 3.10 [P2] No Self-Correction Node in Agent

**PRD Requires (§5.2):** When Graph Tools return empty results, LLM auto-adjusts Cypher query strategy (e.g., relax matching conditions), retry max 2 times.

**What Exists:** `ReActDiagnosisEngine` handles empty observations implicitly (LLM sees "not found" and can choose a different tool). The hardcoded state machine (`tool_executor_node`) does not retry.

**The Gap:** No explicit Self-Correction node. The ReAct engine's behavior depends on LLM quality — if gemma4:26b doesn't reason about adjusting queries, it won't.

**Impact: P2** — Minor for diagnosis (ReAct handles it implicitly). Significant for hardcoded review/query paths where there's no retry logic.

**Estimated Effort:** 2-3 days (add retry wrapper around `_run_cypher`, parameter relaxation heuristics)

### 3.11 [P2] Rule Hot-Reload Not Supported

**PRD Requires (§7.2):** Approved HITL parameters should be injected into running review engine.

**What Exists:** `save_approved_rules()` writes to `custom_rules.yaml`. `save_approved_to_amr()` writes to `amr_data.yaml`. But `ReviewRuleEngine` loads rules in `__init__()` and `AMRDataSource` reads `amr_data.yaml` in `__init__()`. No file watcher or reload mechanism.

**The Gap:** Rule changes require Agent restart. In the Web UI, after approving rules, the running Agent session still uses old rules until restart.

**Impact: P2** — Inconvenient but not blocking. Engineers can restart the session.

**Estimated Effort:** 1 day (add reload method, trigger on file change or after approval action)

### 3.12 [P2] Differential Pair Tracing Stub Only

**PRD Requires (§6.2):** `trace_differential_pair(start_pin)` for PCIe/MIPI differential signal consistency.

**What Exists:** Function exists in `graph_tools.py` (line 560-580) returning: `"[预留接口] trace_differential_pair 将在 Phase 3 实现。"`

**Impact: P2** — Only affects high-speed signal analysis (PCIe, MIPI, USB3). Not needed for basic schematic review.

**Estimated Effort:** 3-5 days (pin name P/N pairing logic, path tracing, length matching check)

---

## 4. Missing Features Priority List

| Priority | Feature | Gap ID | Effort | Dependency |
|----------|---------|--------|--------|------------|
| **P0** | Proper embedding model + bulk datasheet import | K1, K2 | 3-5d | GPU for embedding model |
| **P0** | Populate ChromaDB with real datasheet chunks | K5 | 2-3d | Embedding model |
| **P0** | End-to-end AMR capacitor derating validation | R2 | 2-3d | Datasheet import |
| **P1** | Composite intent task queue execution | A2 | 3-4d | None |
| **P1** | Execution trace visualization in Web UI | W2 | 1-2d | None |
| **P1** | Neo4j subgraph visualization | W3 | 2-3d | None |
| **P1** | BOM CSV import pipeline | D4 | 3-4d | None |
| **P1** | Network voltage annotation expansion | D5 | 1-2d | None |
| **P1** | Tier 2/3 API integration | K5 | 2-3d/tier | API keys |
| **P2** | Self-Correction node for empty Cypher results | A3 | 2-3d | None |
| **P2** | Rule hot-reload mechanism | H3 | 1d | None |
| **P2** | Differential pair tracing implementation | G3 | 3-5d | Pin.Name data |
| **P2** | Neo4j read-only account | T1 | 0.5d | DBA access |
| **P2** | Test coverage to 60% | T2 | 3-5d | None |
| **P2** | E2E integration test suite | T3 | 2-3d | None |

---

## 5. Architecture Debt

### 5.1 LlamaIndex vs Custom GraphRAG

**PRD Design:** LlamaIndex + `llama-index-graph-stores-neo4j` for standardized GraphRAG.

**Actual Implementation:** Custom `GraphRAGBridge` with Neo4j-native VectorChunk nodes and Python-layer cosine similarity.

**Debt Assessment:** The custom approach works for prototyping but has significant limitations:
- Embedding quality: hash-based vectors are not semantically meaningful
- Scalability: Python-layer similarity calculation won't scale past thousands of chunks
- Maintainability: Custom code vs. maintained library
- Feature parity: No chunk overlap, no metadata filtering, no hybrid search

**Recommendation:** Migrate to LlamaIndex when scaling beyond 1,000 document chunks. Current approach is acceptable for MVP.

### 5.2 Dual Vector Store (ChromaDB + Neo4j VectorChunk)

**PRD Design:** ChromaDB for document chunks, Neo4j for graph, LlamaIndex bridges them.

**Actual Implementation:** Both `knowledge_router.py` (ChromaDB) and `graph_rag_bridge.py` (Neo4j VectorChunk) store embeddings independently. They are not synchronized.

**Debt Assessment:** Two redundant vector stores with different embedding strategies (hash vs. Ollama vs. TF-IDF). Agent query path depends on which module is called.

**Recommendation:** Consolidate to a single vector store. Neo4j VectorChunk is preferred (single-database simplicity). Deprecate ChromaDB path or use it only as a cache layer.

### 5.3 Hardcoded State Machine vs. ReAct

**PRD Design:** LLM-driven task queue executor with Self-Correction.

**Actual Implementation:** Hybrid — hardcoded state machine for review/query, ReAct engine for diagnosis only. `use_react_diagnosis=True` by default, but review tasks bypass ReAct entirely.

**Debt Assessment:** Two parallel execution paths create maintenance burden. Review tasks in `tool_executor_node` contain hardcoded string checks (`if "R30002" in i2c_info`) that are Beet7-specific and fragile.

**Recommendation:** Extend ReAct to all task types, or keep current hybrid but remove hardcoded component-specific checks in `_execute_review_tools()`. The `review_specific_node` correctly delegates to `ReviewRuleEngine` — the hardcoded checks in `tool_executor_node` are redundant and should be removed.

### 5.4 Embedding Strategy Fragmentation

**Current State:** Four different embedding approaches across the codebase:
1. `knowledge_router.py:_simple_embed()` — character frequency hash (512-dim)
2. `graph_rag_bridge.py:_local_embed()` — weighted hash (768-dim)
3. `graph_rag_bridge.py:_ollama_embed()` — Ollama gemma4:26b (dim varies)
4. `graph_rag_bridge.py:_tfidf_embed()` — sklearn TF-IDF (768-dim, if available)

**Debt Assessment:** Incompatible vector spaces mean chunks indexed by one method cannot be queried by another. This is a correctness bug, not just a style issue.

**Recommendation:** Standardize on a single embedding approach. For MVP, use Ollama embedding endpoint (if model supports it) or install `sentence-transformers` with `bge-large-zh-v1.5`.

### 5.5 LLM Client Dual Import

**Current State:** `llm_intent_router.py` has an `OllamaClient` compatibility wrapper that delegates to `LLMClient`. Both `OllamaClient` and `LLMClient` are importable, creating confusion.

**Recommendation:** Remove `OllamaClient` wrapper, use `LLMClient` directly everywhere.

---

## 6. Recommendations

### 6.1 Short-Term (1-2 Weeks)

**Week 1: Unblock P0 items**

1. **Install proper embedding model** — Add `sentence-transformers` + `bge-large-zh-v1.5` to requirements. Update `GraphRAGBridge.embed()` to use it as primary. (2 days)
2. **Bulk-import datasheets** — Run `datasheet_parser.py` on available PDFs, index chunks via `GraphRAGBridge`. Target: 500+ chunks. (1 day)
3. **Validate AMR end-to-end** — Import 10 capacitor datasheets through the HITL flow, approve parameters, verify `amr_data.yaml` is read correctly by `AMRDataSource`. Fix any breaks. (2 days)

**Week 2: P1 features + data quality**

4. **Composite intent execution** — Add task queue in `HardwareAgent._run()` that iterates `sub_intents` and merges results. (3 days)
5. **Execution trace visualization** — Add collapsible "Reasoning Steps" section in Web UI chat response. (1 day)
6. **Expand voltage annotation** — Add 20+ voltage patterns to `VoltageLevelExtractor`, batch-annotate all nets. Target: > 80% coverage. (1 day)

### 6.2 Medium-Term (1-2 Months)

**Month 1: Knowledge + Visualization**

7. **BOM import pipeline** — CSV parser, MPN → Component mapping, Description → PartType enrichment, upload UI. (4 days)
8. **Neo4j graph visualization** — Integrate `streamlit-agraph` or PyVis for interactive subgraph rendering. (3 days)
9. **Tier 2 integration** — Connect to internal PLM API (if available) or mock it for testing. (3 days)
10. **LlamaIndex migration** — Replace custom GraphRAG with `llama-index` + `llama-index-graph-stores-neo4j`. (5 days)

**Month 2: Quality + Production**

11. **Test coverage** — Unit tests for all parsers, templates, graph tools. Target: > 60%. (5 days)
12. **E2E test suite** — Automated tests: netlist upload → ETL → review → report → HITL approve. (3 days)
13. **vLLM deployment** — Replace Ollama with vLLM for production-grade inference. (2 days)
14. **Neo4j read-only account** — Create `readonly` role, update `_get_driver()` in graph_tools. (0.5 days)
15. **Rule hot-reload** — File watcher or explicit reload trigger after HITL approval. (1 day)

---

## Appendix A: Status Summary by PRD Section

| PRD Section | Module | Overall Status | Key Blocker |
|-------------|--------|---------------|-------------|
| §4 Data Foundation | ETL Pipeline | ⚠️ 85% | BOM import missing, voltage annotation low |
| §5 Agent Core | Agent + Router | ⚠️ 75% | Composite intent not executed, ReAct review-only |
| §6 Graph Tools | Smart Tools | ✅ 90% | Diff pair is stub, aggregation done |
| §7 True GraphRAG | Knowledge System | ⚠️ 40% | No LlamaIndex, empty ChromaDB, poor embeddings |
| §7 HITL | Rule Precipitation | ⚠️ 70% | Pipeline exists, untested with real data |
| §8/10 Web UI | Streamlit | ⚠️ 65% | Chat+Report+HITL done, no graph viz or trace viz |
| §12 NFR | Testing/Security | ❌ 30% | No read-only account, low test coverage |
| §14 Security | Data Safety | ⚠️ 60% | Local LLM compliant, but no read-only DB access |

## Appendix B: File Reference Map

| PRD Module | Primary File(s) | Lines |
|------------|-----------------|-------|
| ETL Pipeline | `etl_pipeline/main_etl.py`, `quality_guard.py`, `part_type_standardizer.py` | 6.5K + 10.4K + 19.8K |
| Agent Core | `agent_system/agent_core.py` | 1,359 |
| LLM Router | `agent_system/llm_intent_router.py` | 492 |
| LLM Client | `agent_system/llm_client.py` | 442 |
| Review Engine | `agent_system/review_engine/engine.py` + 5 templates | ~50K total |
| Graph Tools | `agent_system/graph_tools.py` | 645 |
| GraphRAG Bridge | `agent_system/graph_rag_bridge.py` | 568 |
| Knowledge Router | `agent_system/knowledge_router.py` | 498 |
| AMR Engine | `agent_system/amr_engine.py` | 693 |
| HITL Workflow | `agent_system/hitl_workflow.py` | 469 |
| Datasheet HITL | `agent_system/datasheet_hitl.py` | 463 |
| Datasheet Parser | `agent_system/datasheet_parser.py` | 714 |
| Storage Dispatcher | `agent_system/storage_dispatcher.py` | 432 |
| Web UI | `web_ui/app.py` + 2 pages | 1,617 + 38K |
