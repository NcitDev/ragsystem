# Product and production roadmap

Date: 2026-07-18

## Product thesis

The strongest initial product is a private code-context service for developers
and coding agents working across large, long-lived repositories. It should win
on deterministic context assembly, exact symbol navigation, explicit budgets,
fresh citations, and local/private deployment—not on pretending that another
chat interface is a moat.

Primary users:

1. Individual developers and agent-heavy teams that need reliable repository
   context without sending source code to a hosted embedding provider.
2. Platform/AI enablement teams that want one governed retrieval service behind
   several IDEs, CLIs, or coding agents.
3. Regulated or IP-sensitive organizations that require self-hosting,
   auditable access, retention controls, and an offline path.

Defer a broad consumer search product and a generic document-RAG platform.
They would expand ingestion, compliance, UI, and support surface before the
code-retrieval advantage is measurable.

## Differentiators to prove

- Hybrid exact/AST, lexical, and dense retrieval for code, with a measured
  fallback story when AST or model services are absent.
- Agent-safe context packs: hard byte/token/slice budgets, deterministic order,
  provenance, freshness, content digests, and citations.
- A private single-binary control plane with local Ollama/Qdrant options and no
  mandatory telemetry.
- Explainable quality: report why a slice was selected and continuously measure
  recall, ranking, citation validity, and freshness.
- Interoperability through stable native OpenAPI now and a standards-conformant
  MCP adapter once auth and schemas are stable.

These are hypotheses until repeated golden-corpus and user-task measurements
show better successful-agent-task rate or lower context cost than alternatives.

## Prioritized build/defer decisions

| Priority | Decision | Why / acceptance criterion |
| --- | --- | --- |
| P0 | Build versioned Qdrant collections with atomic alias cutover. | A full reindex must never create a partially searchable production corpus. Prove old collection remains queryable until the new one passes count/schema/sample checks. |
| P0 | Build durable indexing jobs with bounded queue, idempotency, cancellation, progress, and restart recovery. | Required for dependable automation and later A2A/task integration. Kill/restart and duplicate-submit tests must preserve one coherent result. |
| P0 | Build a tenant/auth domain before any shared hosted deployment. | API key maps to tenant and roles; every repo, SQLite row, Qdrant payload/shard, cache key, log, and export is tenant-scoped. Add adversarial cross-tenant tests. |
| P0 | Build snapshot-based backup/restore and run recovery drills. | Restore Qdrant vectors/config, SQLite registries, aliases, and job state to a documented RPO/RTO. Payload-only export is insufficient. |
| P1 | Build a versioned retrieval evaluation suite. | Gate recall@k, MRR/nDCG, citation accuracy, freshness, deterministic budgets, latency, memory, and index cost on representative public/private-approved corpora. |
| P1 | Build structured tracing/metrics and auditable usage events. | Correlate request/job/dependency IDs; expose saturation, queue depth, failures, and latency. Usage events contain tenant, operation, units, outcome, and timestamps—not source/query content by default. |
| P1 | Build scoped keys, RBAC, quotas, and fair overload behavior. | Separate read/query, index/write, and admin privileges. Enforce concurrent-job, request, storage, and model-token quotas with visible remaining/limit/reset metadata. |
| P1 | Build an MCP adapter as a separate thin boundary. | Implement the stable MCP lifecycle, tools/resources, Streamable HTTP Origin checks, schemas, auth mapping, cancellation, and protocol conformance tests. Reuse the native context-pack core. |
| P1 | Package supported deployment modes. | Publish a locked single-node Compose bundle first, then a Helm/operator path only after HA semantics are real. Include health checks, resource defaults, upgrade/rollback, and backups. |
| P2 | Build bounded batch/multi-repository retrieval. | Fan out with per-request concurrency and total context budgets; merge deterministically and preserve repo provenance. Do not restore the silently ignored `repos` field. |
| P2 | Build policy-based retention and deletion proofs. | Required for enterprise privacy and repository offboarding. Include caches, logs, snapshots, and vector payloads. |
| Defer | A2A Agent Card and task server. | Useful only after durable tasks, streaming, delegation, and auth exist. Advertising it earlier would overstate capability. |
| Defer | Payments inside the daemon. | Billing providers add compliance and support burden but no retrieval value. Meter auditable units first; integrate billing in a separate control plane only with customer demand. |
| Defer | Default opt-in telemetry or training on customer code. | Violates the privacy position. Diagnostics must be explicit, inspectable, minimal, and separable from product use. Never train on customer content without a distinct informed agreement. |

## Deployment modes

### Now: trusted local / single-team

- One daemon trust domain, loopback bind, local bearer token.
- Docker Qdrant or checksum-verified managed Qdrant; local Ollama.
- Suitable for a workstation or a tightly controlled single-team host.
- Not suitable for untrusted users or an Internet-exposed shared service.

### Build next: supported self-hosted team edition

- Reverse proxy/TLS, SSO/OIDC, scoped service keys, tenant/project RBAC.
- Qdrant API keys/TLS, versioned alias rebuilds, snapshots, SQLite backup.
- Compose reference deployment with explicit CPU/RAM/disk/model sizing,
  upgrade compatibility, secret injection, and offline artifacts/SBOM.

### Later: managed private service

- Per-tenant data plane or cryptographically and operationally strong shared
  isolation; regional residency; encrypted backups; on-call/SLOs.
- A control plane for organizations, keys, policies, metering, support, and
  upgrades. Source/query content stays out of billing events.
- Do not offer this until isolation, restore drills, abuse controls, and cost
  models pass independent review.

## Fair monetization

- Keep a useful local core available without forced accounts or telemetry.
- Paid team edition: supported packaging, upgrades, policy controls, SSO/RBAC,
  audit export, backups, and admin UX.
- Managed private edition: charge for reserved compute/storage/model capacity,
  indexed repository size, and support/SLO—not opaque “AI credits.”
- Enterprise: annual support, air-gapped releases, compliance evidence,
  deployment architecture review, and negotiated SLA.
- Offer predictable included quotas and hard/soft caps. Show usage and limits
  before enforcement; never create surprise overages or degrade retrieval to
  manipulate upgrades.

Foundational work in this audit supports that path without adding billing:
Qdrant secrets are environment-based and TLS-protected, request work is
bounded, request IDs are auditable, and context responses report actual budget
consumption. Tenant keys and metering were deliberately not bolted onto the
current single-principal auth model.

## Tenant, privacy, and security requirements

Before shared hosting:

- Authenticate a principal, resolve tenant/project/role once, and pass that
  typed context through every storage and external-service call.
- Namespace repository IDs, collections/aliases, lexical rows, embedding
  caches, jobs, exports, and logs. Never rely on caller-supplied filters as the
  isolation boundary.
- Support read, index, admin, and export permissions separately. Prefer
  short-lived/scoped keys and rotation with overlap.
- Encrypt transport and backups; integrate a secret manager/KMS; document key
  rotation and incident response.
- Default logs/metrics to metadata only. Make content capture a separately
  authorized, time-bounded diagnostic mode with redaction and deletion.
- Provide repository deletion, cache eviction, snapshot expiry, legal hold,
  residency, and verifiable completion.
- Threat-model prompt injection as untrusted retrieved data. Preserve source
  boundaries/provenance and never execute instructions found in code.
- Commission an independent security assessment before Internet exposure.

## Usage accounting and quotas

Recommended append-only usage event fields:

- event/request/job ID, tenant/project, operation and outcome;
- source bytes scanned, files/chunks considered/indexed, vectors written;
- context bytes/tokens/slices returned and model calls/token units where known;
- wall/CPU time class, timestamp, software/model/index version.

Do not record raw code, queries, prompts, answers, API keys, or embeddings in
metering by default. Sign or hash-chain billing exports if they become the
commercial source of truth. Reconcile events idempotently by event ID.

Initial quota dimensions should be concurrent requests/jobs, queued jobs,
repository/file bytes, indexed vectors, context bytes/tokens, and model-call
budget. Return machine-readable limit/current/reset data and distinguish
overload (retryable) from quota exhaustion (policy).

## Enterprise requirements and support burden

Enterprise table stakes include SSO/OIDC/SAML integration, SCIM or equivalent
provisioning, RBAC, scoped keys, immutable audit export, encryption/key
management, residency/retention, backups and restore evidence, HA/DR, change
management, SBOM/advisory response, signed artifacts, offline install,
documented upgrade/rollback, and support/SLO ownership.

The largest support costs will likely be model/GPU sizing, Qdrant operations,
repository-language edge cases, stale indexes, AST tool installation, proxy/TLS
configuration, and retrieval-quality disputes. Reduce them with a supported
compatibility matrix, diagnostic bundles that exclude code by default,
capacity calculators, deterministic job manifests, restore tooling, and a
small number of blessed deployment profiles.

## Success metrics

Quality:

- successful agent task rate on versioned real-world scenarios;
- recall@k, MRR/nDCG, definition/usage coverage, citation validity;
- stale/incorrect citation rate and deterministic replay rate;
- useful source tokens divided by total context tokens.

Reliability and operations:

- indexing success/recovery rate, queue wait, cancellation latency;
- search/context p50/p95/p99, saturation and dependency timeout rate;
- freshness lag from commit to searchable index;
- backup restore success, measured RPO/RTO, upgrade rollback success;
- cross-tenant isolation tests: zero failures is the only acceptable target.

Commercial and user value:

- time to first useful result, weekly active repositories/agents;
- retained teams after 4/12 weeks and expansion driven by active use;
- agent turns and model/context cost saved per successful task;
- support hours and infrastructure cost per active tenant;
- paid conversion tied to governance/support value, not artificial limits.

## Next release gate

Do not call a shared deployment production-ready until P0 items pass destructive
restart, concurrent indexing, isolation, and restore tests. For the next
single-team release, require the full Rust gate, RustSec audit, an end-to-end
temporary Qdrant/Ollama smoke run, a versioned quality corpus result, and a
documented upgrade/rollback rehearsal.
