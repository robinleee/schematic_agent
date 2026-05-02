# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Hardware AI Expert System for schematic review and fault diagnosis using EDA heterogeneous data graph + GraphRAG + LangGraph-style Agent.

**Core services:**
- Neo4j (bolt://localhost:7687) — graph database storing component/net/pin topology
- ChromaDB (http://localhost:8000) — vector database for knowledge retrieval (currently empty)
- Ollama (http://localhost:11434, model: gemma4:26b) — LLM backend (planned for Phase 3)

**Current completion: ~65%**

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

# Agent Core validation
python3 agent_system/agent_core.py

# ETL validation
python3 etl_pipeline/run_etl_validation.py

# Run real ETL
python3 etl_pipeline/run_real_etl.py
```

## Architecture

```
User Input → Agent Core (agent_core.py)
                ├── task_classifier: review / diagnosis / spec_query
                ├── reasoning: generates strategy
                ├── tool_executor: calls graph_tools or knowledge_router
                ├── review_specific: invokes ReviewRuleEngine
                └── report_generator: Markdown output

ReviewRuleEngine (review_engine/engine.py)
    ├── RuleConfigManager → loads rules from config/default_rules.yaml (13 rules)
    ├── TemplateRegistry → 5 templates (decap, pullup, esd, amr, pinmux)
    ├── WhitelistManager → filters false positives
    └── context → RuleContext(neo4j_driver) for Cypher queries

Graph Tools (graph_tools.py)
    ├── get_component_nets → Component→Pin→Net
    ├── get_net_components → Net→Component/Pin
    ├── get_power_domain → voltage-level grouped view
    ├── get_i2c_devices → nets containing I2C/SDA/SCL
    ├── get_signal_path → shortestPath between pins
    └── get_graph_summary → statistics

Knowledge Router (knowledge_router.py)
    ├── Tier 1: ChromaDB semantic search (empty)
    ├── Tier 2: PLM API (stub)
    └── Tier 3: Octopart API (stub)

ETL Pipeline (etl_pipeline/)
    ├── chip_parser → pstchip.dat (components)
    ├── prt_parser → pstxprt.dat (pins)
    ├── net_parser → pstxnet.dat (nets)
    ├── main_etl → orchestrates parse → Pydantic validation → Neo4j UNWIND MERGE
    └── run_real_etl → executes ETL on real netlist (Beet7: 49,570 pins, 8,159 nets)
```

## Critical Data Quality Issues

| Issue | Impact | Root Cause |
|-------|--------|------------|
| Pin.Type = None (100%) | PinMux/POWER/GND checks fail | ETL doesn't write PINUSE from pstchip.dat |
| No [:POWERED_BY] edges | Power tree diagnosis fails | ETL doesn't generate power relationships |
| IC PartType unclassified | MCU/FPGA/PMIC识别失败 | PartType is Cadence library name, needs mapping |

## Key Design Decisions

- State machine: simplified custom (not LangGraph) — lower dependency, complexity manageable
- Review engine: 3-layer (Template + Config + Knowledge) per PRD requirements
- LLM: local Ollama (gemma4:26b) for data security — **agent_core currently uses hardcoded keyword matching, LLM integration is Phase 3**
- Rule config: `review_engine/config/default_rules.yaml` — edit this to add/modify rules

## File Locations

```
hardware_ai_expert/
├── agent_system/
│   ├── agent_core.py          # State machine (entry→classifier→reasoning→tool→specific→report→end)
│   ├── graph_tools.py         # 6 Cypher-based tools, truncated at MAX_RESULTS=50
│   ├── knowledge_router.py    # 3-tier search (ChromaDB stub / PLM stub / Octopart stub)
│   ├── amr_engine.py          # AMR derating calculations
│   ├── review_engine/
│   │   ├── engine.py          # ReviewRuleEngine orchestrator
│   │   ├── whitelist.py       # WhitelistManager for false-positive filtering
│   │   ├── config/default_rules.yaml  # 13 rules
│   │   └── templates/         # 5 rule templates (decap, pullup, esd, amr, pinmux)
│   └── schemas/               # Pydantic models (ComponentNode, PinNode, NetNode, Violation, AgentState, etc.)
├── etl_pipeline/
│   ├── chip_parser.py         # pstchip.dat parser
│   ├── prt_parser.py          # pstxprt.dat parser
│   ├── net_parser.py          # pstxnet.dat parser
│   ├── main_etl.py            # ETL orchestration
│   └── run_real_etl.py        # Execute on Beet7 netlist
netlist_parser/                 # Standalone parser for other netlist formats
```