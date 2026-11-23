# Production AI Agents for Generative Media

Coursework, homework implementations, and multimodal agent pipelines for [DataTalks.Club's Production AI Agents for Generative Media](https://github.com/DataTalksClub/production-ai-agents-for-media-generation) course (Cohort 2026).

**Student:** Carlos Saritama  
**Platform Infrastructure:** Nebius AI Cloud (Serverless GPUs) & Nebius Token Factory (LLM APIs)  
**Cost Constraint:** $0.00 Out-of-Pocket (Funded via Nebius AI Builder Program Credits)

---

## Course Navigation & Submissions

| Module | Title | Deliverable Link | Primary Stack | Status |
| :--- | :--- | :--- | :--- | :--- |
| **01** | **Consistent Media Generation on Serverless GPUs** | [Homework 1](cohorts/2026/homework/01-consistent-media-generation-on-serverless-gpus/) | Sana 1.6B (fp16), NVIDIA® L40S spot, REST client | **SUBMITTED** |
| **02** | **Media Agent Pipeline & Multimodal Judging** | *In Progress* | PydanticAI, Nebius Token Factory (Gemma/Qwen), Wan2.2-I2V | Ready |
| **03** | **Batch Workflows & Video Evaluation** | *Planned* | 10 Parallel Spot Jobs, Slurm/Job API | Planned |
| **Capstone** | **Autonomous Myth & Media Factory** | [Proposal Draft](cohorts/2026/homework/01-consistent-media-generation-on-serverless-gpus/) | Multi-agent orchestrated media pipeline | Planned |

---

## Module 1 Showcase: The 10 Celestial Archetypes

An empirical benchmark evaluating generation latency and marginal compute costs on **NVIDIA® L40S** spot ($0.79/h):

![Arc 01 - The Sovereign Sun](cohorts/2026/homework/01-consistent-media-generation-on-serverless-gpus/assets/arc01.png)

* **Model**: `Efficient-Large-Model/Sana_1600M_1024px_diffusers` (1024x1024 PNG)
* **Median Generation Latency**: **3.74 seconds**
* **Projected Unit Cost at N = 1000**: **$0.0009 USD**
* **Breakeven vs Commercial APIs (Fal.ai @ $0.0050)**: Cheaper starting at **$N \ge 14$ assets** (over 82% cost reduction in production).

For complete technical methodology, full image gallery, and question-by-question submission details, see [Homework 1 README](cohorts/2026/homework/01-consistent-media-generation-on-serverless-gpus/README.md).
