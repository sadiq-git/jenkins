# 🤖 Agentic Jenkins + Gemini AI Planner

This repository demonstrates an **AI-driven CI/CD pipeline** built with **Jenkins**, **Docker**, and **Google Gemini**.  
The AI Planner automatically generates pipeline steps based on the repository context, commit message, and branch type.

---

## 🧱 Architecture Overview

                   ┌────────────────────────────┐
                   │        Developer           │
                   │  commits to GitHub repo    │
                   └────────────┬───────────────┘
                                │
                                ▼
                   ┌────────────────────────────┐
                   │          Jenkins           │
                   │    (running in Docker)     │
                   │                            │
                   │ Jenkinsfile:               │
                   │  1️⃣ Checkout Code          │
                   │  2️⃣ Collect Context        │
                   │  3️⃣ Call AI Planner (Gemini)│
                   │  4️⃣ Execute AI Plan        │
                   └────────────┬───────────────┘
                                │
                      Network (Docker Bridge)
                                │
                                ▼
               ┌─────────────────────────────────────┐
               │        AI Planner (Flask App)       │
               │  agentic-jenkins-ai-planner         │
               │-------------------------------------│
               │  /healthz → 200 ✅                   │
               │  /plan → Gemini-generated plan 🧠     │
               │  Uses GEMINI_API_KEY                │
               │  Model: gemini-2.5-flash            │
               │  Returns JSON plan for CI/CD tasks  │
               └─────────────────────────────────────┘
                                │
                                ▼
                   ┌────────────────────────────┐
                   │       Gemini Model API     │
                   │  (Google GenAI Backend)    │
                   └────────────────────────────┘


### Components

| Component | Description |
|------------|-------------|
| **Jenkins (Docker)** | Runs the CI/CD pipeline and triggers AI Planner |
| **AI Planner (Flask)** | Python service that calls Gemini and generates JSON pipeline plans |
| **Gemini Model** | LLM (`gemini-2.5-flash`) that interprets context and suggests stages |
| **Node-CI Container** | Node.js build image used to execute AI-generated stages |

---

## 🚀 Workflow

1. Jenkins checks out the repository.
2. It builds `context.json` with:
   ```json
   {
     "branch": "master",
     "lastCommitMsg": "v4 4",
     "buildNumber": 46,
     "repoName": "first"
   }
