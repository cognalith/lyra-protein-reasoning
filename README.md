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
pip install openai requests
```

### Configuration
```bash
# Set your Azure OpenAI credentials
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your-key-here"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
```

### Run Lyra
```bash
cd agents
python3 orchestrator.py
```

Or use in code:
```python
from agents.orchestrator import analyze

result = analyze("Is protein Q8I3H7 a viable drug target for malaria?")
print(result)
```

## 📁 Project Structure
```
lyra-protein-reasoning/
├── README.md
├── agents/
│   ├── orchestrator.py      # Magnetic orchestration manager
│   ├── query_agent.py       # Question parsing + protein fetching
│   ├── structure_agent.py   # pLDDT analysis + druggable regions
│   ├── reasoning_agent.py   # Multi-step reasoning + self-reflection
│   ├── critic_agent.py      # Hypothesis verification + cross-referencing
│   └── synthesis_agent.py   # Research brief compilation
├── mcp_servers/
│   └── alphafold_mcp.py     # AlphaFold API interface
├── evaluation/              # Test questions + results (coming)
├── docs/                    # Architecture docs (coming)
└── demo/                    # Demo video (coming)
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
