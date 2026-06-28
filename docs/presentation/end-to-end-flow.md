# Lab Tacit-Knowledge AI Agent — End-to-End Process Flow

> Presentation companion. Every diagram below is Mermaid. It renders in GitHub,
> VS Code (Mermaid preview), and most slide tools. Read top to bottom: each
> section zooms in one level deeper.

---

## 1. The 30-second story (read this slide first)

A new lab student asks a question in plain Japanese or English. The system
answers **only** from the lab's own uploaded documents. If the documents don't
contain the answer, it refuses to guess — it says so honestly and logs the
question for a professor to fill in later.

That honest "I don't know, and I wrote it down for a human" behavior is the
**signature feature**. It is the governance / anti-hallucination story.

```mermaid
flowchart LR
    Student(["👩‍🎓 New student<br/>asks a question"])
    Frontend["🖥️ Frontend<br/>(Next.js chat UI)"]
    Backend["⚙️ Backend<br/>(FastAPI)"]
    Bedrock["☁️ Amazon Bedrock<br/>RAG + LLM"]
    Docs[("📚 Lab documents<br/>manuals, notes, minutes")]
    Professor(["👨‍🏫 Professor<br/>reviews gaps"])

    Student -->|"types question"| Frontend
    Frontend -->|"POST /ask (JSON)"| Backend
    Backend -->|"retrieve + generate"| Bedrock
    Bedrock -. "grounded in" .-> Docs
    Bedrock -->|"answer + citations"| Backend
    Backend -->|"answer, steps, images"| Frontend
    Frontend -->|"shows answer +<br/>annotated diagram"| Student
    Backend -. "if no answer found:<br/>log knowledge gap" .-> Professor

    classDef human fill:#fde68a,stroke:#b45309,color:#000
    classDef sys fill:#bfdbfe,stroke:#1d4ed8,color:#000
    classDef cloud fill:#ddd6fe,stroke:#6d28d9,color:#000
    class Student,Professor human
    class Frontend,Backend sys
    class Bedrock,Docs cloud
```

---

## 2. System components — who talks to whom

This is the architectural map. The frontend never touches AWS directly; the
backend is the only thing holding credentials and calling Bedrock.

```mermaid
flowchart TB
    subgraph Client["🖥️ Browser — Next.js Frontend"]
        direction TB
        UI["Chat UI<br/>(page.tsx)"]
        Ctrl["useChatController<br/>state + history"]
        Svc["chatService.ts<br/>fetch wrapper + mock fallback"]
        LS[("localStorage<br/>session_id + chat history")]
        UI --> Ctrl --> Svc
        Ctrl <--> LS
    end

    subgraph Server["⚙️ Backend — FastAPI (main.py / app)"]
        direction TB
        Routes["api.py<br/>routes + validation + CORS + rate limit"]
        Service["services.py<br/>KnowledgeService orchestration"]
        Provider["providers.py<br/>Answer provider (Bedrock or Fixture)"]
        Repo["repositories.py<br/>SQLite / memory store"]
        Visuals["visuals.py + static_visuals.py<br/>PDF page / figure rendering"]
        Routes --> Service --> Provider
        Service --> Repo
        Routes --> Visuals
    end

    subgraph AWS["☁️ Amazon Bedrock (us-east-1)"]
        direction TB
        KB["Knowledge Base AJVVEPYMSH<br/>(retrieve)"]
        Aurora[("Aurora vector store<br/>Titan embeddings")]
        Sonnet["Claude Sonnet 4.6<br/>grounded answers"]
        Haiku["Claude Haiku 4.5<br/>onboarding guides"]
        KB --- Aurora
    end

    S3[("S3 bucket<br/>bedrock-docs-...<br/>source PDFs + figures")]
    DB[("app.db<br/>gaps, feedback, history")]

    Svc -->|"HTTPS JSON<br/>POST /ask /onboarding /feedback<br/>GET /gaps /faq /health /ready"| Routes
    Provider --> KB
    Provider --> Sonnet
    Provider --> Haiku
    Aurora -. "indexes" .-> S3
    Visuals --> S3
    Repo --> DB

    classDef fe fill:#bfdbfe,stroke:#1d4ed8,color:#000
    classDef be fill:#bbf7d0,stroke:#15803d,color:#000
    classDef cloud fill:#ddd6fe,stroke:#6d28d9,color:#000
    classDef store fill:#fed7aa,stroke:#c2410c,color:#000
    class UI,Ctrl,Svc fe
    class Routes,Service,Provider,Repo,Visuals be
    class KB,Aurora,Sonnet,Haiku cloud
    class S3,DB,LS store
```

**Key boundary:** the frontend speaks one simple JSON contract to the backend.
The backend owns all AWS credentials, the knowledge gap logic, and persistence.

---

## 3. The full `/ask` journey — detailed sequence

This is the heart of the system. Follow a single question from keystroke to
rendered answer.

```mermaid
sequenceDiagram
    autonumber
    actor User as 👩‍🎓 Student
    participant FE as Frontend<br/>(chatService.ts)
    participant API as FastAPI<br/>POST /ask
    participant SVC as KnowledgeService
    participant DB as Repository<br/>(SQLite)
    participant KB as Bedrock KB<br/>(retrieve)
    participant LLM as Claude Sonnet<br/>(converse)
    participant VIS as Visuals<br/>(S3 figures)

    User->>FE: type question + Enter
    Note over FE: attach session_id (localStorage),<br/>current_state.active_figure_id, lang
    FE->>API: POST /ask {message, session_id, current_state}

    API->>API: validate body (Pydantic)<br/>+ CORS / rate-limit checks
    API->>SVC: ask(message, session_id)
    SVC->>DB: get_history(session_id) → last 10 turns

    SVC->>KB: retrieve(query, top 5 chunks)
    Note over KB: optional bilingual<br/>query translation + merge
    KB-->>SVC: chunks + similarity scores

    alt top score < GAP_THRESHOLD (0.20)
        SVC->>DB: log_gap(message)
        SVC-->>API: honest "not documented" + is_gap=true
    else score OK → generate
        SVC->>LLM: system prompt + context + history<br/>+ JSON schema
        LLM-->>SVC: {answer_text, next_step_hint,<br/>is_supported, figure_id}
        alt is_supported = false (context only related)
            SVC->>DB: log_gap(message) + discard draft
            SVC-->>API: honest gap + is_gap=true
        else is_supported = true
            SVC->>DB: save_interaction(...)
            SVC-->>API: answer + citations + confidence
        end
    end

    API->>VIS: look up figure / static image for source page
    VIS->>VIS: filter images by relevance (Sonnet judge)
    VIS-->>API: presigned image URL(s) or none

    API-->>FE: AskResponse {answer_text, next_step_hint,<br/>visual_data, citations, confidence, is_gap}
    FE->>FE: adaptAskResponse → build steps + warnings
    FE-->>User: render answer, annotated diagram,<br/>citations, gap notice
```

---

## 4. Knowledge-gap detection — the governance gate (zoom in)

The whole credibility of the product lives here. There are **two gates** an
answer must pass; failing either one turns it into an honest, logged gap.

```mermaid
flowchart TD
    Q([Question arrives]) --> R["Retrieve top 5 chunks<br/>from Knowledge Base"]
    R --> G1{"Gate 1:<br/>top score ≥ 0.20?"}

    G1 -->|"No — weak/empty retrieval"| GAP
    G1 -->|"Yes"| GEN["Sonnet generates a<br/>draft answer from chunks"]

    GEN --> G2{"Gate 2:<br/>is_supported = true?<br/>(chunks directly support answer)"}
    G2 -->|"No — only loosely related"| GAP
    G2 -->|"Yes"| ANS

    ANS["✅ Grounded answer<br/>answer + citations + confidence<br/>is_gap = false"]
    GAP["🚩 Knowledge gap<br/>honest 'not documented yet' message<br/>confidence = 0.0, is_gap = true"]

    ANS --> SAVE[("Save interaction")]
    GAP --> LOG[("Log to gaps store")]
    LOG --> PROF([👨‍🏫 Professor reviews<br/>via GET /gaps])

    classDef ok fill:#bbf7d0,stroke:#15803d,color:#000
    classDef bad fill:#fecaca,stroke:#b91c1c,color:#000
    classDef gate fill:#fde68a,stroke:#b45309,color:#000
    class ANS,SAVE ok
    class GAP,LOG bad
    class G1,G2 gate
```

> Why two gates? The retrieval score alone is not trustworthy — an unrelated
> manual once scored higher than a correct match. So Sonnet itself must confirm
> the retrieved text *directly supports* the answer before it ships.

---

## 5. The API contract — one shape, every field always present

Frontend and backend were built in parallel against this fixed contract. Every
field always ships, even if a given frontend ignores some of them.

```mermaid
flowchart LR
    subgraph Req["Request → POST /ask"]
        direction TB
        r1["message (the question)"]
        r2["session_id (conversation key)"]
        r3["current_state.active_figure_id"]
        r4["lang (ja | en)"]
    end

    subgraph Res["Response ← AskResponse"]
        direction TB
        a1["answer_text — the answer or honest 'I don't know'"]
        a2["next_step_hint — suggested follow-up action"]
        a3["visual_data — figure_id, highlight_item,<br/>static_images, source page, caption"]
        a4["citations[] — source doc + snippet"]
        a5["confidence — retrieval score (0.0 on gap)"]
        a6["is_gap — true = undocumented, logged for prof"]
    end

    Req ==> Backend{{"FastAPI<br/>+ Bedrock"}} ==> Res

    classDef io fill:#e0e7ff,stroke:#4338ca,color:#000
    class r1,r2,r3,r4,a1,a2,a3,a4,a5,a6 io
```

Other endpoints share the same simple style:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ask` | POST | Main Q&A with citations, gap detection, visuals |
| `/onboarding` | POST | Role-tailored guide (routed to **Haiku**) |
| `/gaps` | GET | Professor's list of unanswered questions |
| `/faq` | GET | Static, deterministic FAQ (no model call) |
| `/feedback` | POST | Thumbs up/down on an answer |
| `/health` | GET | Liveness (no AWS call) |
| `/ready` | GET | DB + provider readiness (no paid AWS call) |

---

## 6. Frontend internals — how the chat UI handles a turn

```mermaid
flowchart TD
    Input["User types in ChatInput"] --> Send["useChatController.handleSend()"]
    Send --> Push["push user message to state<br/>+ set loading"]
    Push --> Call["chatService.sendChatMessage()"]

    Call --> Mode{"endpoint set<br/>& not FORCE_MOCK?"}
    Mode -->|"No"| Mock["Return mock SCENARIO<br/>(keyword match: laser/holder/focus...)"]
    Mode -->|"Yes"| Fetch["fetch POST /ask<br/>(45s timeout, AbortController)"]

    Fetch --> Shape{"valid AskResponse<br/>shape?"}
    Shape -->|"No"| Err["throw → show error banner"]
    Shape -->|"Yes"| Adapt["adaptAskResponse()<br/>build Step[] from visual_data"]
    Mock --> Adapt

    Adapt --> AImsg["create AI ChatMessage<br/>answer + steps + citations + warnings"]
    AImsg --> Render["ChatHistory renders:<br/>AnswerMessage, StepCard,<br/>AnnotationOverlay on diagram"]
    AImsg --> Persist[("save to localStorage<br/>(max 15 conversations)")]

    classDef fe fill:#bfdbfe,stroke:#1d4ed8,color:#000
    classDef dec fill:#fde68a,stroke:#b45309,color:#000
    class Input,Send,Push,Call,Fetch,Adapt,AImsg,Render,Mock fe
    class Mode,Shape dec
```

Notable resilience details to mention on stage:
- **Mock fallback:** if no backend URL is configured, the UI still demos with
  built-in scenarios — useful when the network is unreliable on stage.
- **Session persistence:** `session_id` and the last 15 conversations live in
  `localStorage`, so history survives refreshes.
- **Timeout guard:** requests abort after 45s with a clean error message.

---

## 7. How documents get in — the ingestion side (one-time / offline)

The Q&A flow above assumes documents are already searchable. Here is how they
got there.

```mermaid
flowchart LR
    Source["📄 Lab documents<br/>(equipment manuals,<br/>meeting minutes)"]
    Upload["Upload to S3<br/>bedrock-docs-..."]
    Sync["Press 'Sync' in<br/>Bedrock console"]
    Embed["Titan Text Embeddings v2<br/>chunk + vectorize"]
    Store[("Aurora vector store<br/>(managed by KB)")]
    Ready(["✅ Searchable via<br/>retrieve()"])

    Source --> Upload --> Sync --> Embed --> Store --> Ready

    classDef step fill:#ddd6fe,stroke:#6d28d9,color:#000
    class Source,Upload,Sync,Embed,Store,Ready step
```

> Until **Sync** runs, retrieval returns nothing and every question correctly
> reports a knowledge gap — that is honest behavior, not a bug.

---

## 8. Model routing — the right model for each job

```mermaid
flowchart LR
    Ask["/ask<br/>grounded Q&A"] --> Sonnet["Claude Sonnet 4.6<br/>(smart, structured output)"]
    Onb["/onboarding<br/>guide generation"] --> Haiku["Claude Haiku 4.5<br/>(fast, cheaper)"]
    Faq["/faq"] --> NoModel["No model call<br/>(static, deterministic)"]
    Trans["bilingual query<br/>translation"] --> Sonnet

    classDef ep fill:#bfdbfe,stroke:#1d4ed8,color:#000
    classDef m fill:#ddd6fe,stroke:#6d28d9,color:#000
    class Ask,Onb,Faq,Trans ep
    class Sonnet,Haiku,NoModel m
```

---

## Speaker cheat-sheet

- **One sentence:** "It answers lab questions only from the lab's own documents,
  and honestly flags and logs anything it can't answer for a professor."
- **The differentiator:** knowledge-gap detection with two gates (retrieval
  score + Sonnet's `is_supported` check). Demos in seconds.
- **Trust model:** frontend holds no secrets; backend owns Bedrock, persistence,
  and the gap logic. Static FAQ makes no model call at all.
- **Resilience:** mock-mode frontend, demo-fixture backend, timeouts, rate
  limits, and verified SQLite backups mean the demo survives a flaky stage.
- **Region gotcha:** everything is `us-east-1`. Sonnet is an inference profile.
```
