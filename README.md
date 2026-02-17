# Lyra: Multi-Agent Protein Reasoning System

**Agents League 2026 — Reasoning Agents Track**

Lyra is a multi-agent system that analyzes protein structures from AlphaFold to answer complex drug target research questions. Given a natural language query, Lyra's agents collaborate to fetch protein data, analyze structural confidence, reason about druggability, critique findings, and deliver a comprehensive research brief.

## 🎯 What It Does

Ask Lyra a question like:

> "Is protein Q8I3H7 a viable drug target for malaria treatment?"

Lyra will:
1. **Parse** the question and identify proteins to analyze
2. **Fetch** protein data from AlphaFold and UniProt
3. **Analyze** structural confidence and identify druggable regions
4. **Reason** about function, druggability, and risks (with self-reflection)
5. **Critique** its own conclusions using external evidence
6. **Synthesize** a final research brief with confidence scores

## 🏗️ Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    LYRA ORCHESTRATOR                        │
│              (Magnetic Orchestration Pattern)               │
│         Manages task list, coordinates all agents           │
└────────────┬──────────┬──────────┬──────────┬──────────────┘
             │          │          │          │
      ┌──────▼───┐ ┌────▼────┐ ┌───▼────┐ ┌───▼─────┐
      │  QUERY   │ │STRUCTURE│ │REASON- │ │ CRITIC  │
      │  AGENT   │ │  AGENT  │ │ING     │ │ AGENT   │
      │          │ │         │ │AGENT   │ │         │
      │Interprets│ │Analyzes │ │Multi-  │ │Cross-   │
      │questions,│ │pLDDT,   │ │step    │ │checks   │
      │fetches   │ │finds    │ │scientif│ │findings,│
      │proteins  │ │druggable│ │ic      │ │challenges│
      │          │ │regions  │ │reasoning│ │claims   │
      └──────┬───┘ └────┬────┘ └───┬────┘ └───┬─────┘
             │          │          │          │
      ┌──────▼──────────▼──────────▼──────────▼──────┐
      │              SYNTHESIS AGENT                  │
      │   Compiles final research brief with          │
      │   confidence scores & reasoning chains        │
      └───────────────────────────────────────────────┘
```

## 🧠 Reasoning Patterns Demonstrated

| Pattern | Implementation |
|---------|----------------|
| **Planner-Executor** | Orchestrator decomposes questions → assigns to agents |
| **Multi-Step Reasoning** | Reasoning Agent analyzes function → structure → druggability → risks |
| **Self-Reflection** | Reasoning Agent examines its own logic for gaps and biases |
| **Critic/Verifier** | Critic Agent challenges hypotheses with external evidence |
| **Confidence Calibration** | Confidence adjusted through critique (e.g., 0.85 → 0.65) |
| **Magnetic Orchestration** | Orchestrator dynamically adjusts task list based on findings |

## 🛡️ Resilience & Error Handling

| Feature | Details |
|---------|---------|
| **Task Failure Isolation** | A failed protein doesn't crash the pipeline — remaining proteins complete successfully |
| **Defensive Query Handling** | Input validation, type checking, and structured error returns from all MCP calls |
| **HTTP Retry with Backoff** | Exponential backoff on 429/5xx errors; immediate fail on 4xx client errors |
| **Centralized Timeouts** | All HTTP calls use configured timeouts via `config/http_config.py` |
| **Structured Logging** | All modules use `logging.getLogger(__name__)` — no print statements |

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Azure OpenAI API access (via Microsoft Foundry)

### Installation
```bash
# Clone the repo
git clone https://github.com/cognalith/lyra-protein-reasoning.git
cd lyra-protein-reasoning

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration
```bash
# Set your Azure OpenAI credentials
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your-key-here"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"

# Optional: override API version (defaults to 2024-02-15-preview)
export AZURE_OPENAI_API_VERSION="2024-02-15-preview"
```

### Run Lyra
```bash
# Interactive mode
cd agents
python3 lyra.py

# Single question from command line
python3 lyra.py "Is protein Q8I3H7 a viable drug target for malaria?"

# Health check (verifies APIs + credentials)
python3 -c "from lyra import health_check; health_check()"
```

Or use in code:
```python
from agents.lyra import run_safe

result = run_safe("Is protein Q8I3H7 a viable drug target for malaria?")
if result["success"]:
    print(result["result"])
```

## 📁 Project Structure
```
lyra-protein-reasoning/
├── README.md
├── requirements.txt
├── test_agent.py             # Standalone smoke test
├── agents/
│   ├── lyra.py               # Main entry point (interactive + CLI)
│   ├── orchestrator.py       # Magnetic orchestration manager
│   ├── query_agent.py        # Question parsing + defensive protein fetching
│   ├── structure_agent.py    # pLDDT analysis + druggable regions
│   ├── reasoning_agent.py    # Multi-step reasoning + self-reflection
│   ├── critic_agent.py       # Hypothesis verification + cross-referencing
│   ├── synthesis_agent.py    # Research brief compilation
│   └── test_proteins.py      # Multi-protein integration test
├── mcp_servers/
│   ├── alphafold_mcp.py      # AlphaFold API interface
│   └── uniprot_mcp.py        # UniProt API interface
├── config/
│   ├── http_config.py        # Centralized timeout + retry settings
│   └── http_client.py        # Resilient HTTP client with backoff
├── docs/                     # PRDs and architecture decisions
└── demo/                     # Demo video (coming)
```

## 📊 Example Output

**Question:** "Is protein Q8I3H7 a viable drug target for malaria treatment?"

**Result (summarized):**

| Metric | Value |
|--------|-------|
| **Verdict** | 🟡 CAUTIOUS |
| **Confidence** | 0.65 (adjusted from 0.85 after critique) |
| **Structure Quality** | 86.06/100 |
| **Druggable Regions** | 3 excellent candidates identified |
| **Key Risk** | No experimental validation of function |

## 🔬 Data Sources

- **AlphaFold** — Protein structure predictions (CC-BY-4.0)
- **UniProt** — Protein annotations and cross-references

## 🛠️ Technology Stack

| Component | Technology |
|-----------|------------|
| Agent Framework | Custom Python orchestration |
| LLM Backend | Azure OpenAI (GPT-4o) via Microsoft Foundry |
| Protein Data | AlphaFold API + UniProt API |
| HTTP Resilience | Custom retry client with exponential backoff |
| Development | VS Code + AI Toolkit |

## 📅 Competition Timeline

- **Track:** Reasoning Agents
- **Build Period:** Feb 16–27, 2026
- **Submission:** GitHub repo + demo video

## 🙏 Acknowledgments

- Microsoft Agents League for the competition framework
- DeepMind/EMBL-EBI for AlphaFold database
- UniProt Consortium for protein annotations

---

**Built for Microsoft Agents League 2026**
