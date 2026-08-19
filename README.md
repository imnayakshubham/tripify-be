# Multi-Agent Travel Planner — API

You send something like *"a five day trip somewhere warm in Europe for under 1500 pounds"* and get back one plan. Behind it are three agents — destination, itinerary and budget — that run in order, each building on what the last produced. The response names the agents that contributed, and every run is written to an audit trail.

**Live app: [tripify-fe.vercel.app](https://tripify-fe.vercel.app)**  ·  API: [tripify-be.onrender.com](https://tripify-be.onrender.com)

FastAPI + LangGraph + Postgres, with a React 18 + TypeScript frontend in its own repository.

| | Repository |
| --- | --- |
| Backend (this repo) | [imnayakshubham/tripify-be](https://github.com/imnayakshubham/tripify-be) |
| Frontend | [imnayakshubham/tripify-fe](https://github.com/imnayakshubham/tripify-fe) |

The API is on Render's free tier, which sleeps after 15 minutes idle. `scripts/keepalive.py` pings `/health` every 14 minutes so the first request isn't a 50-second cold start.

---

## Running it

You need Python 3.13+, [uv](https://docs.astral.sh/uv/), a Groq API key (the free tier is fine) and a Postgres URL.

```bash
cp .env.example .env      # fill in GROQ_API_KEY and DATABASE_URL
uv sync
uv run python main.py     # http://127.0.0.1:8000, interactive docs at /docs
```

Tables are created on startup, so there is no migration step.

Two things that will cost you ten minutes if you hit them cold:

**Run from the repository root.** `pyproject.toml` has no `[build-system]`, so uv treats this as a virtual project and never installs it. `from app.configs import ...` resolves only because `app/` sits in the working directory. Launch from anywhere else and the imports break.

**Use `uv run`, not bare `python`.** If Anaconda is first on your PATH you will get a `ModuleNotFoundError` for a package that is definitely installed in `.venv`.

## Environment

| Variable | Required | Notes |
| --- | --- | --- |
| `GROQ_API_KEY` | yes | free tier at console.groq.com |
| `DATABASE_URL` | yes | Postgres. I used Neon's free tier |
| `MODEL_NAME` | no | defaults to `openai/gpt-oss-20b` |
| `CORS_ORIGINS` | yes | comma-separated; no default, see `.env.example` |

`CORS_ORIGINS` has **no default** — with it unset no browser origin is allowed and `lifespan` logs a warning. `.env.example` ships the Vite dev server on both 5173 and 5174, because Vite silently falls back to 5174 when 5173 is taken and the resulting preflight rejection surfaces as "could not reach the API" — which reads as the backend being down.

---

## How the orchestration works

A supervisor reads the request and decides which specialists it actually needs. If a destination was named, the destination agent is skipped. If the request is not about travel at all, no specialist runs. Whatever it picks runs in a fixed order, because the dependencies are real: you cannot plan days without a destination, and you cannot cost a plan that does not exist yet.

```mermaid
flowchart TD
    START([START]) --> SUP[supervisor]
    SUP -->|route_from_supervisor| DEST[destination_agent]
    SUP -.->|destination already named| ITIN[itinerary_agent]
    SUP -.->|cost-only question| BUD[budget_agent]
    SUP == "not a trip — supervisor already answered" ==> END([END])
    DEST -->|route_after_agent| ITIN
    DEST -.-> BUD
    ITIN -->|route_after_agent| BUD
    ITIN -.-> SYN
    BUD -->|route_after_agent| SYN[synthesis]
    SYN --> END
```

Solid edges are the full chain; dotted edges are the skips a conditional edge can take when the supervisor did not select an agent. The thick edge is the scope guard: this system plans trips and nothing else, so a greeting or an off-topic question ends the run at the supervisor rather than being handed to an agent that would invent a trip to justify itself.

The whole graph is five nodes and two static edges — `START → supervisor` and `synthesis → END`. Everything between them is conditional.

### One request, end to end

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant FE as React UI
    participant API as POST /plans/stream
    participant G as travel_graph
    participant S as supervisor
    participant A as Specialist agents
    participant Y as synthesis
    participant DB as Postgres

    U->>FE: types a request, hits enter
    FE->>API: user_query (+ plan_id when continuing)
    API->>DB: start_request(...) — new plan only
    API-->>FE: event: start
    API->>G: invoke/stream, thread_id = plan_id

    Note over G,DB: continuing a plan? the checkpointer<br/>replays this thread into state

    G->>S: route
    S->>S: pick agents, extract constraints
    S->>DB: agent_invocations row (@audited)
    API-->>FE: event: routed (the real chain)

    alt not a travel request
        S-->>G: no agents, writes final_response
        G-->>API: END — no specialist runs
    else a trip to plan
        loop destination, then itinerary, then budget
            G->>A: run
            A->>DB: agent_invocations row (@audited)
            API-->>FE: event: agent (name, status, ms)
        end
        G->>Y: synthesise
        Y->>DB: agent_invocations row (@audited)
    end

    API->>DB: finish_request(...) — rolls cost up
    API-->>FE: event: done (full PlanResponse)
    FE-->>U: trip page, or a plain answer
```

Every arrow to Postgres is written by the `@audited` decorator, so the audit trail cannot
disagree with what the user was shown. The `routed` frame carries the supervisor's actual
selection, which is why the progress display is real rather than a timer.

**The API seeds the state.** `POST /plans` mints a `plan_id` and invokes the graph with `messages`, `plan_id`, `user_id` and `user_query`. That `plan_id` is also the LangGraph thread id — see [Re-opening a plan](#re-opening-a-plan) for why that matters.

**The supervisor makes the only routing decision** (`app/agents/supervisor.py`). It asks the model once for a selection plus the extracted constraints, then does three things to what comes back — two of them defensive:

1. Filters the picks against `KNOWN_AGENTS`, so an invented agent name is dropped rather than routed to.
2. Appends `budget_agent` whenever `to_number(trip_constraints["budget_amount"])` parses. The model is free to return a budget while omitting the agent that checks it — well-formed, but contradictory, and a budget that is never checked is the worst version of "silently exceeded". This is a routing override, not just a prompt rule. It runs *before* step 3, because a stated budget means the request really is a trip.
3. If nothing is selected after that, the supervisor answers directly. It writes `final_response` from the model's `direct_reply` (falling back to a fixed string, since the UI renders that field) and the graph ends. There is deliberately no "pick one anyway" fallback: an empty selection used to become `["itinerary_agent"]`, which meant a bare `"hi"` reached the itinerary agent with `Destination: None` and got a fabricated day-by-day plan back.

**Routing walks the chain** (`app/graph.py`). `route_from_supervisor` returns the first of `selected_agents_in_order(state)`, or `END` if the list is empty — nothing was produced, so there is nothing to synthesise and the supervisor's own reply stands. After each specialist, `route_after_agent(name)` scans `AGENT_ORDER` **forward only** — `AGENT_ORDER[current_position + 1:]` — for the next selected agent, and falls through to synthesis when there isn't one. All four conditional edges share one path map, `ROUTE_TARGETS`.

Two things follow from "forward only": the graph cannot loop, and skipping needs no special case — an unselected agent is simply never a routing target. `selected_agents_in_order` re-sorts the supervisor's list into `AGENT_ORDER`, which is why appending `budget_agent` in step 3 above cannot break sequencing.

These routers are pure functions of state. That is what makes the chain debuggable rather than emergent — you can read the path a request will take without running a model.

**Synthesis writes the answer** (`app/agents/synthesis.py`). It reads `destination_results`, `itinerary` and `budget_results` — the markdown strings only, never the structured dicts — and names the agents that contributed. A *successful* supervisor is excluded from that list, because orchestration is not a knowledge contribution; a *failed* one is still reported, because it means no specialist ran at all.

### How state moves between agents

`TravelState` (`app/schema/state.py`) is a LangGraph `TypedDict`. Only two fields accumulate. `messages` uses `operator.add`, so a continued conversation keeps its history. `contributing_agents` uses `add_turn_agents`, which accumulates within a turn but starts fresh at each supervisor label — otherwise a follow-up would re-report the previous turn's agents and name the supervisor twice. **Everything else is last-write-wins**, and that is the mechanism the chain runs on rather than an incidental detail: the destination agent returns `{**trip_constraints, "destination": recommended}`, replacing the dict wholesale, so itinerary and budget just read the resolved destination out of the state they were handed.

Each specialist writes two keys — the structure it produced, and a markdown rendering of it:

| Agent | Structured | Markdown | Also writes |
| --- | --- | --- | --- |
| `destination_agent` | `destination_choice` | `destination_results` | `trip_constraints` (overwritten) |
| `itinerary_agent` | `itinerary_plan` | `itinerary` | |
| `budget_agent` | `budget_assessment` | `budget_results` | |

The markdown is a view of the structure, not the source. Synthesis consumes the markdown; the React UI consumes the structure. An agent that stopped emitting its markdown would silently degrade the final answer, which is why the `_format()` helpers are load-bearing rather than cosmetic.

### When an agent fails

The run does not die. `@audited` in `app/agents/base.py` wraps every node: it catches the exception, records the invocation as `failed`, returns an empty delta, and appends `"<name> (failed)"` to `contributing_agents`.

Because that list accumulates within the turn, one string is the single source for two consumers — synthesis reads it to tell the model which sections are missing, and `_agent_status` in the streaming route reads it to set the SSE status. Neither invents an outcome, so what the user sees, what the stream reports, and what the audit log says cannot drift apart.

### Adding a fourth agent

Sequential by design, but not closed. A new specialist means touching:

- `app/agents/<name>.py` and `app/agents/__init__.py`
- `app/prompts/<name>.py`
- `AGENT_ORDER`, `ROUTE_TARGETS` and a node registration in `app/graph.py`
- `AGENT_SEQUENCE` in `app/agents/base.py`
- the agent list in the supervisor prompt
- the output keys in `TravelState`

Nothing else — routing picks it up from `AGENT_ORDER` automatically.

## Where the behavioural rules are enforced

The brief says these agents "must never" do certain things. A prompt instruction is not a guarantee, so wherever a rule is mechanically checkable it is checked in code.

**Destination** (`app/agents/destination.py`) — discards any candidate the model itself flagged as breaking a hard constraint *before* choosing, and re-picks if its own recommendation is not viable. This fires in practice; the model does emit violating candidates. The rejected list and the reason are kept, so the filtering is visible rather than claimed.

**Budget** (`app/agents/budget.py`) — recomputes the verdict and **fails closed**:

- the comparison is anchored on the budget the *user* stated. The model echoes one back and that echo can drift upward; trusting it would stamp a verified-looking pass on a real overage.
- `within_budget` is tri-state. `None` means "could not verify" — an unparseable figure, or a currency mismatch — and is never conflated with `True`.
- the resolved budget is written back into the assessment, so a client compares against the same number the verdict used.
- the cheaper alternative's savings are summed and checked against the shortfall. One that falls short is reported as insufficient rather than presented as the fix.

**Supervisor** (`app/agents/supervisor.py`) — forces `budget_agent` into the selection whenever a budget was extracted. The model can otherwise return a `budget_amount` while omitting the agent: well-formed, but contradictory, and a budget that is never checked is the worst version of "silently exceeded".

**Itinerary** — realistic timings and stated uncertainty are a judgement only the model can make, so that one lives in the prompt. It does have somewhere to land: every segment carries an `uncertainty` field, so the doubt is addressable data rather than a phrase buried in a paragraph.

Attribution and audit come from one place. The `@audited` decorator in `app/agents/base.py` times each agent, writes its `agent_invocations` row, captures the provider's real token counts, and appends to `contributing_agents` — so what a caller sees and what the log says cannot drift apart.

---

## API

| Method | Path | Who | What |
| --- | --- | --- | --- |
| POST | `/plans` | anyone | runs the chain, returns the finished answer |
| POST | `/plans/stream` | anyone | the same run as SSE, one event per agent |
| GET | `/plans/{id}/result` | anyone | re-open a finished plan |
| GET | `/plans/{id}` | anyone | the audit record for a run |
| GET | `/audit/requests` | anyone | request log, scoped to you unless admin |
| GET | `/audit/invocations` | admin | flat per-agent log across all requests |
| GET | `/metrics` | admin | counts, timings and token usage |
| GET | `/health` | anyone | |

### Streaming

`POST /plans/stream` takes the same body and headers as `POST /plans` and emits:

```text
start   → { plan_id }
routed  → { selected_agents, supervisor_reasoning }
agent   → { agent_name, status, duration_ms }     (one per node)
done    → the full PlanResponse
error   → { detail }
```

Two details make the progress real rather than decorative. `routed` carries the supervisor's own `selected_agents`, so a client knows the actual chain from the first event. And each `agent` status is read off the `(failed)` suffix the audit decorator writes — not invented.

Once the 200 and headers are sent a failure cannot be an HTTP status, so it arrives as an `error` event; a `finally` closes the audit row if the client disconnects mid-run.

`POST /plans` is the simpler blocking path and the easiest way to try the API from curl. Both build their payload with the same `_plan_response()`, so the two cannot drift.

### Continuing a conversation

Both POST routes take an optional `plan_id`:

```jsonc
{ "user_query": "make it cheaper, around 800", "plan_id": "a7787e4e-…" }
```

Send it and the turn runs under that id instead of a new one. Because `plan_requests.id`
**is** the LangGraph thread id, reusing it resumes that thread: the checkpointer restores
`messages`, `trip_constraints` and whatever the specialists produced last time, so the
supervisor sees the conversation and routes a *change* rather than a fresh plan. Ask for a
cheaper version of a Lisbon trip and only the budget agent runs — the destination and the
day count carry forward.

Two details make that work rather than merely resume:

- `_merge_constraints` in `app/agents/supervisor.py` merges the new extraction over the old
  one and ignores empty values. State is last-write-wins, so without this a follow-up
  carrying no destination would blank the one already chosen.
- The prompt is given the earlier turns and told to treat the new message as a change,
  carrying forward anything the user did not ask to alter.

No schema change was needed for any of this, and there is still one id: the plan, its
thread, and its conversation are the same thing. The trade-off is that cost and token
counts on `plan_requests` roll up across the whole conversation rather than per turn —
per-turn detail is still in `agent_invocations`, which timestamps every row.

### Re-opening a plan

`GET /plans/{id}/result` replays a finished plan from the LangGraph checkpoint. The answer was never duplicated into the audit tables — it is reachable because `plan_requests.id` **is** the thread id — so there is no second copy that can fall out of step. Non-admins are scoped by the audit row first, so this cannot be used to read someone else's thread by guessing an id.

### The contract with the frontend

`PlanResponse` returns `destination_choice`, `itinerary_plan` and `budget_assessment` as loose `dict[str, Any] | None`, deliberately not as nested pydantic models. This is unvalidated model output: a cost may arrive as `1200` or `"£1,200"`, and any key may be missing. Strict models would turn a model quirk into a 500 on a run that otherwise succeeded.

The shape is enforced on the client instead, in the frontend repository's `src/types/api.ts`, where being wrong is a compile error rather than a failed request. **With the two repositories separate, nothing structurally ties them together** — if you change one of these payloads, change the types over there in the same breath.

`null` on any of the three means that agent did not run.

---

## Auth

There isn't any. You claim an identity with an `X-User-Email` header and the server believes you. Anyone who can set a header can be an admin.

That is deliberate — the brief asks for a stub and explicitly says not to build enterprise identity. What is real is the shape: roles live on the user row in the database rather than in the request, the check happens in one place (`app/api/deps.py`), and non-admins are scoped by a SQL `WHERE` clause rather than by filtering rows after the fact. Swapping in real auth means replacing `current_user` and nothing else.

Admins see two things ordinary users do not: cost and per-agent timing on a plan, and everyone's rows instead of only their own.

## Data model

Four tables, declared in `app/db/models.py` and applied by the Alembic migration in `alembic/versions/`.

- **`plan_requests.id` is the LangGraph thread id.** One identifier, so there is no alias to keep in sync. The join to the library-owned checkpoint tables is by that shared id, deliberately not a foreign key.
- **`agent_invocations`** is one row per agent run, with real token counts from `response.usage_metadata` — measured, not estimated. `output_summary` is truncated, because the full state already lives in the checkpoint under the same id.
- **Cost is rolled up onto `plan_requests`**, so "what did this request cost" is one row read while "which agent is expensive" is one aggregate.
- **`users.id` is a surrogate UUID.** Email and username both change, and a primary key that changes breaks every foreign key pointing at it. Login uniqueness is a functional index on `lower(email)`.

## Layout

```text
main.py         uvicorn launcher for app.api.server:api_app
app/
  graph.py      orchestration — routing and chaining
  agents/       one file per agent, plus base.py (LLM calls, @audited, coercion)
  prompts/      one file per agent; behavioural constraints live here
  api/          routes.py, server.py, deps.py (the auth stub)
  schema/       state.py (TravelState) + api.py (pydantic models)
  db/           engine, checkpointer, models, migrate, audit repository, metrics
  configs/      env values only
  llms/         chat-model factory
scripts/        keepalive.py, started from the lifespan hook
alembic/        one baseline migration; run_migrations() applies it at boot
```

---

## Decision note

### 1. A supervisor picks, then a fixed order

I could have let the agents hand off to each other and decide when to stop. I did not, because the order is not up for debate. You cannot build an itinerary without a destination, or cost one that does not exist yet.

So the supervisor has one job: deciding which agents a request needs. The order is fixed in code, and routing walks to the next selected agent, then falls through to synthesis. If you name a destination yourself, that agent is skipped and the itinerary agent goes first, so there are fewer model calls and less to go wrong. It also stays easy to debug, because routing is a plain function I can read, not something emerging from five prompts.

State is a LangGraph `TypedDict` where only `messages` and `contributing_agents` build up. Everything else is last write wins, which lets the destination agent write its choice into `trip_constraints` for later agents to read.

### 2. Rules in code where possible

The brief says the agents "must never" do certain things. A line in a prompt is not a guarantee, so wherever a rule can be checked in code, I check it. The destination agent throws away any candidate the model itself flagged as breaking a hard constraint, picks from what is left, and picks again if its own recommendation did not survive. This really does happen. The budget agent works out `within_budget` from the numbers instead of trusting the model's flag, and writes the overage warning itself when one is missing.

The itinerary rule, flagging uncertain timings, cannot be checked in code, so it lives in the prompt. I would rather be clear about which is which than imply all three are enforced.

### 3. Attribution and audit from one place

The `@audited` decorator times each agent, writes its audit row, records the real token counts, and adds the agent to `contributing_agents`. Because it is one decorator, what the user sees and what the log says cannot drift apart. It also absorbs failures. A failed agent is recorded, labelled `(failed)`, and the chain carries on instead of a 500.

### What I cut

Tests. Real auth. Visual polish. And `GET /plans/{id}` returns the audit record rather than the plan text, so you cannot open an old plan from history. I flagged that in the UI instead of faking a detail page.

---

## Production architecture note

Running this on Azure for 500 or more concurrent users. The frontend stays on Vercel.

Proposed, not the current deployment:

```mermaid
flowchart TD
    B[Browser<br/>React app on Vercel] --> ACA[Container Apps<br/>scales on concurrent requests]
    ACA --> A1[API replica]
    ACA --> A2[API replica]
    ACA --> A3[API replica]
    A1 & A2 & A3 --> PG[(Postgres Flexible Server<br/>PgBouncer)]
    A1 & A2 & A3 --> GROQ[Groq API]
    A1 & A2 & A3 --> KV[Key Vault]
    A1 & A2 & A3 -.OTel.-> AI[Application Insights]
```

### Provisioning

Bicep, deployed from GitHub Actions with OIDC, so environments are reproducible.

Azure Container Apps for the FastAPI backend, because it can scale on concurrent HTTP requests. The work here is waiting on the model, not CPU. Azure Database for PostgreSQL Flexible Server, using its built in PgBouncer. Key Vault for secrets, read with a managed identity.

### Getting to 500 concurrent users

Each request holds a worker thread for the whole chain, ten to sixty seconds of blocking calls, so replicas are the scaling unit. I would set the concurrent request target per replica from a load test, and cap max replicas above the measured peak.

Two limits would show up before compute does. The model provider's rate limit, and the 240 second default cap Container Apps puts on a request, which matters because `/plans/stream` holds the connection open for the whole run. Front Door does not support server sent events, so it would not sit in front of the API.

### Authentication and access control

Identity today is an `X-User-Email` header the server believes. That is a stub, not security. It would be replaced with whatever identity provider is already in use, validating a signed token instead of a header.

What carries over is structural. Roles live on the user row, the role check sits in one dependency, and non admin scoping is a SQL where clause rather than filtering after the fact.

### Monitoring

OpenTelemetry into Application Insights, a trace per request with a span per agent. The audit tables already record duration and tokens per agent, so cost reporting could come from Postgres. Alerts on agent failure rate, p95 latency and spend per tenant.
