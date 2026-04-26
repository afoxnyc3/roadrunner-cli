# Roadrunner Workflow

How the tool works end-to-end — for operators bringing a new project to the loop and for agents executing inside it.

---

## 1. The Five Stages, End-to-End

Roadrunner drives a project through five stages. The first four are human-led setup; the fifth is the autonomous loop.

```mermaid
flowchart TD
    Start([Project idea or existing repo]) --> A

    subgraph A_["Stage A — Intake"]
        direction TB
        A[Read spec / SPEC.md<br/>Read ADRs, existing docs<br/>Walk the code tree]
    end

    subgraph B_["Stage B — Reconciliation"]
        direction TB
        B1[Read representative code files]
        B2[Categorize: REAL / STUB / PARTIAL / WRONG]
        B3[Surface architectural contradictions]
        B1 --> B2 --> B3
    end

    subgraph C_["Stage C — Draft tasks.yaml"]
        direction TB
        C1[Translate spec → roadrunner schema]
        C2[Split tasks &gt; ~4hr of work]
        C3[Add validation_commands<br/>strong / medium / weak tiering]
        C4[Set depends_on per task]
        C1 --> C2 --> C3 --> C4
    end

    subgraph D_["Stage D — Review Gate"]
        direction TB
        D1[User reviews tasks.yaml]
        D2[roadrunner analyze<br/>must exit 0]
        D1 --> D2
    end

    subgraph E_["Stage E — Scaffold"]
        direction TB
        E1[pip install roadrunner-cli + roadrunner init in target repo]
        E2[Merge hook registrations<br/>into .claude/settings.json]
        E3[Gitignore runtime state files]
        E4[Move reviewed YAML<br/>→ tasks/tasks.yaml]
        E1 --> E2 --> E3 --> E4
    end

    subgraph F_["Stage F — Execute"]
        direction TB
        F1[Open Claude Code in repo]
        F2[SessionStart injects snapshot]
        F3[Autonomous per-task loop]
        F4[Phase-boundary review + merge]
        F1 --> F2 --> F3 --> F4
    end

    A --> B_
    B_ --> C_
    C_ --> D_
    D_ -->|changes needed| C_
    D_ -->|approved| E_
    E_ --> F_
    F_ --> Done([All tasks done<br/>ROADMAP_COMPLETE])
```

**Stage B was the gap** before the entra-triage pilot surfaced it. Spec-shaped plans assume greenfield; real repos have partial implementations that contradict the spec. Stage B catches that before the loop burns iterations on false premises.

---

## 2. Per-Task Cycle

What happens inside a single task. This is the loop's atomic unit.

```mermaid
stateDiagram-v2
    [*] --> Eligible: roadrunner next

    Eligible --> InProgress: roadrunner start TASK-XXX<br/>(creates roadrunner/TASK-XXX branch)

    InProgress --> Validating: implement<br/>(edit files in files_expected)

    Validating --> FixErrors: validation_commands fail
    FixErrors --> Validating: retry

    Validating --> AutoBlock: same task failed 5×
    AutoBlock --> [*]: loop moves on<br/>(status = blocked)

    Validating --> Completing: all validation_commands exit 0
    Completing --> Linting: roadrunner complete TASK-XXX<br/>(status = done)

    Linting --> FixLint: lint fails
    FixLint --> Linting: retry

    Linting --> Committing: lint passes
    Committing --> Resetting: git commit<br/>on roadrunner/TASK-XXX

    Resetting --> NextBrief: roadrunner reset TASK-XXX

    NextBrief --> Eligible: Stop hook injects<br/>next task brief
    NextBrief --> [*]: no more eligible tasks<br/>→ ROADMAP_COMPLETE

    note right of Linting
        Stop hook guards here:
        dirty tree + no in_progress task
        → block stop until lint + commit done
    end note
```

The Stop hook enforces two invariants:
1. **Validation-as-gate.** The agent can't claim a task is done until `roadrunner validate` exits 0.
2. **Commit discipline.** The agent can't move to the next task with uncommitted work on a `roadrunner/*` branch — lint runs first; if it passes, commit; if it fails, fix lint first.

---

## 3. Stop Hook Decision Tree

The Stop hook fires after every Claude turn. Its job: decide whether the agent can stop, or must keep working.

```mermaid
flowchart TD
    Fire[Stop hook fires] --> Active{stop_hook_active<br/>already true?}
    Active -->|yes| AllowInf[Allow stop<br/>infinite-loop guard]

    Active -->|no| Branch{On roadrunner/*<br/>branch?}
    Branch -->|no| Delegate

    Branch -->|yes| Dirty{Working tree<br/>dirty?}
    Dirty -->|no| Delegate

    Dirty -->|yes| InProg{current_task_id<br/>set in state?}
    InProg -->|yes — mid-task| Delegate

    InProg -->|no — just completed| RunLint[Run project lint<br/>e.g. npm run lint]
    RunLint --> LintOK{lint<br/>passes?}

    LintOK -->|yes| BlockCommit[Block stop<br/>Instructions:<br/>git add -A<br/>git commit -m<br/>roadrunner reset]
    LintOK -->|no| BlockLint[Block stop<br/>Surfaces lint output<br/>+ fix instructions]

    Delegate[Delegate to<br/>roadrunner check-stop] --> CSDecide{check-stop<br/>decision}

    CSDecide -->|iteration cap hit| HardHalt[Hard halt<br/>continue: false]
    CSDecide -->|task in_progress| ResumeBrief[Block<br/>inject resume brief]
    CSDecide -->|eligible task| NextBrief[Block<br/>inject next-task brief]
    CSDecide -->|blocked tasks| BlockedReport[Block<br/>report blocked tasks]
    CSDecide -->|all done| DonePrompt[Block<br/>prompt for ROADMAP_COMPLETE]
    CSDecide -->|ROADMAP_COMPLETE<br/>output detected| AllowDone[Allow stop]
```

The decision order matters: the commit gate runs **before** `check-stop` delegation, so a dirty tree never proceeds to the next task. The Python `check-stop` command owns all loop-state logic; the bash wrapper only enforces the commit gate.

---

## 4. Worked Example — entra-triage Task DAG

The 18-task dependency graph for the first external pilot. Critical path is 10 tasks deep (ENTRA-001 → 002 → 003 → 010 → 011 → 020 → 040 → 080 → 081 → 090).

```mermaid
flowchart LR
    subgraph P1["Phase 1 — Reconcile & Foundation"]
        direction TB
        E001[ENTRA-001<br/>Reconcile entities<br/>single-tenant DB schema]
        E002[ENTRA-002<br/>npm install +<br/>monorepo build green]
        E003[ENTRA-003<br/>Drizzle ORM layer<br/>schema.ts/db.ts/migrate.ts]
        E001 --> E002 --> E003
    end

    subgraph P2["Phase 2 — Graph Connectors"]
        direction TB
        E010[ENTRA-010<br/>Real client<br/>pagination + 429/503 backoff]
        E011[ENTRA-011<br/>Mock client<br/>drop-in parity + P1/P2 variants]
        E010 --> E011
    end

    subgraph P3["Phase 3 — Pipeline"]
        direction TB
        E020[ENTRA-020<br/>Ingestion worker<br/>cursor + dedup + dead-letter]
        E030[ENTRA-030<br/>Agent base<br/>Anthropic tool use + confidence]
        E031[ENTRA-031<br/>Sign-in + identity-risk agents]
        E032[ENTRA-032<br/>Directory / baseline / response /<br/>research agents]
        E040[ENTRA-040<br/>Triage worker<br/>pre-filter + dispatch + dedup]
        E030 --> E031 --> E032
        E032 --> E040
        E020 --> E040
    end

    subgraph P4["Phase 4 — API + UI"]
        direction TB
        E050[ENTRA-050<br/>tRPC read routes<br/>incidents / cases / auditLog]
        E051[ENTRA-051<br/>tRPC write routes<br/>baseline / responseActions / ingestion]
        E060[ENTRA-060<br/>UI shell<br/>login / dashboard / incidents]
        E061[ENTRA-061<br/>UI<br/>baseline / approvals / settings]
        E050 --> E051
        E050 --> E060
        E051 --> E061
        E060 --> E061
    end

    subgraph P5["Phase 5 — Test Hardening"]
        direction TB
        E070[ENTRA-070<br/>Unit tests<br/>policy / parsers / dedup hash]
        E080[ENTRA-080<br/>Local dev<br/>docker-compose + dev-setup.sh]
        E081[ENTRA-081<br/>Integration tests<br/>ingestion + triage + response]
        E090[ENTRA-090<br/>Playwright E2E<br/>5 key flows]
        E070 --> E081
        E080 --> E081
        E081 --> E090
    end

    E003 --> E010
    E003 --> E030
    E003 --> E050
    E011 --> E020
    E032 --> E070
    E040 --> E080
    E061 --> E090
```

### Task phases at a glance

| Phase | Tasks | Why this grouping |
|---|---|---|
| **1. Reconcile & Foundation** | ENTRA-001, 002, 003 | Fix the spec/reality mismatch, install deps, add the DB layer. Nothing else can move until this is done. |
| **2. Graph Connectors** | ENTRA-010, 011 | Pagination, backoff, typed returns, mock parity. The data-source boundary. |
| **3. Pipeline** | ENTRA-020, 030, 031, 032, 040 | Ingestion → agents → triage. Where LLM cost and quality get shaped. |
| **4. API + UI** | ENTRA-050, 051, 060, 061 | tRPC routes first, then the pages that consume them. |
| **5. Test Hardening** | ENTRA-070, 080, 081, 090 | Unit + integration + E2E, plus the local-dev one-shot script. |

### Per-task breakdown

| ID | Phase | Scope | Validation tier |
|---|---|---|---|
| ENTRA-001 | 1 | Delete `tenant.ts` + `connector.ts`; strip `tenantId` from 12 entity files; fix `db/seed.sql` | Strong (grep + build) |
| ENTRA-002 | 1 | `npm install` + `npm run build` green across workspaces | Strong |
| ENTRA-003 | 1 | Create `packages/shared/src/db/{schema,db,migrate}.ts` | Medium + strong |
| ENTRA-010 | 2 | Graph client pagination, 429/503 backoff, typed Zod returns | Medium + strong |
| ENTRA-011 | 2 | Mock client drop-in parity; P1/P2 variants for ID Protection | Medium + strong |
| ENTRA-020 | 3 | Ingestion worker: checkpoint, dedup, dead-letter, pino redaction | Medium + strong |
| ENTRA-030 | 3 | `BaseAgent` refactor to Anthropic tool use + confidence scores | Medium + strong |
| ENTRA-031 | 3 | SignInTriage + IdentityRisk agents on new base | Medium + strong |
| ENTRA-032 | 3 | DirectoryChange + BaselineReview + ResponsePolicy + Research agents | Medium + strong |
| ENTRA-040 | 3 | Triage worker: pre-filter PASS/FLAG/AMBIGUOUS, dispatch, dedup, audit | Medium + strong |
| ENTRA-050 | 4 | tRPC read routes: `incidents`, `cases`, `auditLog` + JWT middleware | Medium + strong |
| ENTRA-051 | 4 | tRPC action routes: `baseline`, `responseActions`, `ingestion` — **no `execute` procedure per ADR 0006** | Medium + strong |
| ENTRA-060 | 4 | UI: login, dashboard layout, incidents page | Weak + strong |
| ENTRA-061 | 4 | UI: baseline, approvals (no Execute button per ADR 0006), settings | Weak + strong |
| ENTRA-070 | 5 | Vitest unit tests: policy engine + parsers + dedup hash | Strong |
| ENTRA-080 | 5 | `docker-compose.yml` + `scripts/dev-setup.sh` | Strong |
| ENTRA-081 | 5 | Integration tests (live Postgres) for ingestion, triage, response-action lifecycle | Strong |
| ENTRA-090 | 5 | Playwright E2E for 5 flows | Strong |

---

## 5. Operator Cheat Sheet

| Task | Command |
|---|---|
| Check queue | `roadrunner status` |
| Next eligible | `roadrunner next` |
| Validate a tasks.yaml | `roadrunner analyze [--tasks-file PATH]` |
| Scaffold a new project | `roadrunner init <dir> [--dry-run]` |
| Health snapshot | `roadrunner health` |
| Unblock a task | Edit `status` back to `todo` in `tasks/tasks.yaml`, then `roadrunner status` |

## 6. Related Docs

- [CLAUDE.md](../CLAUDE.md) — operating contract the agent follows
- [DESIGN.md](../DESIGN.md) — architectural rationale
- [docs/adr/](./adr/) — accepted decisions (ADR-001 through ADR-010)
