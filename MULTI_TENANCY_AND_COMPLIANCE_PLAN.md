# LangOrch Multi-Tenancy and Compliance Plan

Last updated: 2026-03-08

## 1. Purpose

This document defines the next platform trust-layer plan for:

- multi-tenant isolation
- tenant-aware identity and authorization boundaries
- tenant-scoped data, secrets, audit, and quotas
- compliance controls for PII, retention, erase, and policy gates
- operational controls required for regulated or enterprise deployments

This document complements:

- `IDENTITY_RBAC_AND_BUILDER_REBUILD_PLAN.md`
- `ENTERPRISE_READINESS_GAP_ANALYSIS.md`
- `IMPLEMENTATION_STATUS.md`

The identity/RBAC document covers who gets access and how. This document covers how that access is partitioned, governed, and proven safe across tenants and regulated data.

---

## 2. Current State Summary

LangOrch is still fundamentally a single-tenant platform.

What exists today:

- strong role-based endpoint gating
- SSO onboarding and role mapping
- manual user management
- static API key support
- project-level grouping on procedures, runs, cases, and some queue-related records
- structured logging already has a `tenant_id` context slot available

What does not exist yet:

- first-class `tenant` entity
- tenant-scoped auth claims and request resolution
- row-level tenant isolation across core tables
- tenant-specific quotas and rate limits
- tenant-scoped secrets and encryption policy
- tenant admin boundaries and delegated governance
- compliance workflows for erase/export/legal hold
- policy gates for LLM/data handling before publish or deploy

Important clarification:

- `project_id` is a useful operational grouping field today, but it is not a security boundary and must not be treated as a tenant model.

---

## 3. Why This Layer Is Needed Next

LangOrch already has a strong runtime. The main remaining trust gaps are no longer basic execution features. They are:

1. keeping one customer or business boundary isolated from another
2. proving how sensitive data is handled before it reaches LLMs or external systems
3. supporting enterprise onboarding without making every deployment effectively single-customer and custom-governed

Without multi-tenancy and compliance controls, the platform can still run workflows, but it cannot cleanly support:

- multiple customers on one control plane
- multiple internal business units with enforced boundaries
- delegated tenant administration
- regulated data handling and audit expectations
- platform-level commercialization beyond single-tenant deployments

---

## 4. Recommended Tenancy Strategy

### 4.1 Define the tenancy unit clearly

LangOrch should define a tenant as the highest isolation boundary for:

- identities
- procedures
- runs
- cases
- approvals
- artifacts
- secrets
- audit records
- quotas

Recommended examples of what a tenant could represent:

- one external customer organization
- one internal legal entity
- one regulated business boundary that requires separate governance

Do not use tenant to mean:

- team
- project
- environment
- AD group

Those are lower-level scope dimensions inside a tenant.

### 4.2 Recommended deployment modes

LangOrch should support two operating modes over time:

1. dedicated single-tenant deployment
2. shared control plane with strict tenant isolation

Recommended delivery sequence:

- support dedicated single-tenant deployments immediately
- design shared-control-plane tenancy into the schema and auth model now
- add stronger database-native isolation later when PostgreSQL becomes the default enterprise path

### 4.3 Recommended isolation model

Near-term recommendation:

- application-enforced tenant isolation with explicit `tenant_id` on core records

Medium-term recommendation:

- PostgreSQL row-level security or equivalent policy-backed enforcement for critical tables

This avoids blocking the roadmap on a full database redesign while still forcing the platform into an honest tenancy model.

---

## 5. Tenant Resolution Model

Every request should resolve a tenant context before business logic runs.

### 5.1 Human users

Recommended resolution order for SSO users:

1. trusted tenant claim from IdP mapping or app registration metadata
2. local tenant membership table lookup
3. explicit admin-selected tenant if the user belongs to multiple tenants

The platform should never infer tenant only from a mutable UI parameter.

### 5.2 API keys and machine identities

API keys should resolve tenant from the key record itself, not from request headers.

Each key should bind to:

- one tenant
- one identity type
- one owner system
- explicit permissions and scopes

### 5.3 Manual users

Local users must be bound to one default tenant or an explicit multi-tenant admin relationship.

### 5.4 Trusted routing hints

Subdomain, host, or gateway headers may help route the request, but they should only act as trusted hints after validation against a tenant binding record.

---

## 6. Core Tenant Data Model

Add first-class entities for:

- `tenants`
- `tenant_domains`
- `tenant_identity_provider_bindings`
- `tenant_memberships`
- `tenant_role_bindings`
- `tenant_permission_overrides`
- `tenant_api_keys`
- `tenant_quotas`
- `tenant_audit_policies`
- `tenant_data_policies`

Add `tenant_id` to all core business records that must be isolated, including:

- procedures
- runs
- run events
- approvals
- cases
- case events
- webhook subscriptions and deliveries
- secrets
- system settings that should become tenant-scoped
- artifacts and retention records

Recommended invariant:

- any user-visible business record must either have a `tenant_id` or be globally platform-managed by explicit design

### 6.1 Global vs tenant-scoped tables

Global platform tables may remain global only if they represent shared platform metadata, for example:

- permission definitions
- node schema registry definitions
- platform release metadata

Tenant-scoped tables should contain customer or operational data.

### 6.2 Do not confuse tenant and project

Recommended hierarchy:

- tenant
- project
- LOB or team scope
- workflow object

Projects can stay as a useful grouping construct inside a tenant, but must not substitute for security isolation.

---

## 7. Request Context and Enforcement Model

Every authenticated request should resolve an effective context like this:

```json
{
  "tenant_id": "tenant-acme",
  "tenant_slug": "acme",
  "identity": "alice@acme.com",
  "identity_type": "sso_user",
  "roles": ["manager"],
  "permissions": ["runs.read", "procedures.write"],
  "scopes": {
    "project": ["claims-modernization"],
    "environment": ["dev", "qa"]
  }
}
```

The request pipeline should enforce three checks in this order:

1. authentication
2. tenant resolution
3. authorization within that tenant

### 7.1 Enforcement rules

- all list queries must be tenant-filtered by default
- all primary-key fetches must verify tenant ownership before returning data
- background loops must preserve tenant boundaries in replay, retry, and dispatch paths
- cache keys, idempotency keys, and dedupe records must include tenant context where collisions are possible
- logs, metrics, and traces should include tenant identifiers where safe and permitted

### 7.2 Platform admin exception

Support a platform-super-admin mode only for tightly controlled operations such as:

- tenant provisioning
- platform migrations
- platform support break-glass actions

Cross-tenant access by platform admins must be explicit, audited, and difficult to do accidentally.

---

## 8. Secrets, Config, and Key Segregation

Multi-tenancy is incomplete if secrets and config remain global.

Recommended target state:

- tenant-scoped secrets store or tenant partition inside the existing secrets model
- tenant-scoped external connector credentials
- tenant-scoped webhook signing secrets
- tenant-scoped LLM gateway headers and provider policy
- tenant-scoped quota and cost controls

Recommended rules:

1. one tenant must never be able to read another tenant's secret metadata or usage history
2. secret encryption policy should be centrally enforced but tenant ownership must be explicit
3. API keys must be created, rotated, and revoked within tenant boundary

---

## 9. Quotas and Fairness Controls

Shared control-plane multi-tenancy requires anti-noise-neighbor controls.

Add tenant-scoped controls for:

- max concurrent runs
- queue depth limits
- artifact storage budget
- LLM token and cost budget
- webhook throughput
- agent pool usage ceilings where pools are shared

Recommended behavior:

- soft limits with warnings first
- hard limits for abusive or dangerous load
- tenant-aware dashboards so operators can explain throttling decisions

---

## 10. Compliance Strategy

Compliance should be treated as product behavior, not only deployment paperwork.

LangOrch should implement compliance in five layers:

1. data classification
2. data minimization and tokenization
3. retention and erase workflows
4. audit and evidence
5. policy gates before publish or deploy

---

## 11. Data Classification and Sensitive Data Handling

### 11.1 Recommended classification levels

At minimum classify data as:

- public
- internal
- confidential
- regulated

Allow higher-risk flags such as:

- contains PII
- contains financial data
- contains health data
- export restricted

### 11.2 Where classification should live

Classification can be attached to:

- procedure metadata
- variable schema fields
- secrets
- artifacts
- tenant policy defaults

### 11.3 Expected behavior

If a workflow variable or artifact is marked sensitive, the platform should be able to:

- redact it in default logs
- prevent unsafe display in UI without elevated permission
- block it from unsupported providers or channels
- require tokenization before LLM dispatch when policy says so

---

## 12. PII Tokenization Before LLM Calls

This is the most important compliance gap called out in the current platform analysis.

### 12.1 Target behavior

Before sending high-risk data to an LLM or third-party service, LangOrch should support:

- detect sensitive fields from variable schema and policy
- tokenize or mask configured values
- keep a secure re-identification map only where policy allows
- record that tokenization occurred in the audit trail

### 12.2 Practical rollout

Start with deterministic policy-driven tokenization for known fields, not full AI-based DLP.

Examples:

- customer name -> token
- account number -> token
- email address -> token or masked form
- national identifier -> token only

### 12.3 Provider policy tie-in

Per tenant or per environment, define which providers may receive:

- no regulated data
- tokenized regulated data only
- approved confidential data

---

## 13. Retention, Erase, and Legal Hold

### 13.1 Retention policies

Retention should become tenant-scoped and object-scoped.

Policies should cover:

- runs and run events
- artifacts
- cases and case events
- webhook deliveries and DLQ data
- approval records
- audit records where legally allowed

### 13.2 GDPR and equivalent erase workflow

The platform should support a governed erase flow that can:

- find records related to a subject or case reference
- delete or anonymize eligible data
- preserve non-erasable audit evidence where policy requires it
- produce an erase report showing what was deleted, anonymized, skipped, or blocked

### 13.3 Legal hold

Erase must be blockable by legal hold or regulatory retention requirements.

---

## 14. Audit, Evidence, and Explainability

Enterprise deployments need proof, not just controls.

Add auditable evidence for:

- who accessed what tenant
- who changed permissions or group mappings
- who created or rotated API keys
- what policy set was active at publish or deploy time
- whether tokenization/redaction was applied
- what data was erased or exempted under legal hold

Recommended evidence model:

- immutable audit event stream where possible
- actor, tenant, action, target object, before/after summary, reason, request correlation ID

---

## 15. Policy-as-Code Gates

LangOrch should add policy checks before publish, promote, or production deployment.

### 15.1 Example policy gates

- deny publish if regulated variable has no classification metadata
- deny production publish if LLM step uses non-approved provider for that tenant
- deny workflow promotion if retention policy is missing
- deny deployment if human approval is required but missing for high-risk category
- warn when workflow exports confidential data to webhook or email without explicit allow rule

### 15.2 Recommended design

Keep the first version simple:

- compile workflow metadata
- evaluate deterministic rules
- emit pass, warn, or deny result
- store evidence with publish or promotion history

---

## 16. Operational Model for Regulated Tenants

For stricter environments, support tenant policy features such as:

- environment restrictions by tenant
- approved connector/provider allowlists
- stronger approval requirements for production changes
- regional routing and data residency flags
- support-only break-glass workflow with mandatory audit reason

These do not need to all ship in one phase, but the data model should not block them.

---

## 17. Recommended Delivery Phases

### Phase A: tenancy foundation

- create `tenants` and membership model
- add `tenant_id` to new and highest-value core records first
- resolve tenant in auth dependency and request context
- tenant-filter list and read paths

### Phase B: isolation hardening

- tenant-aware API keys and secrets
- tenant-scoped config and quotas
- tenant-aware metrics and audit context
- backfill `tenant_id` across historical data where possible

### Phase C: compliance foundation

- data classification metadata
- policy-driven redaction and tokenization hooks
- retention policy model
- erase workflow skeleton and audit evidence

### Phase D: policy enforcement

- compile/publish policy gates
- provider restrictions by tenant and environment
- legal hold and exemption handling
- tenant admin views and compliance dashboards

### Phase E: stronger shared-control-plane posture

- database-native isolation for PostgreSQL path
- regional and residency controls
- tenant support tooling with break-glass workflows

---

## 18. Immediate Backlog Recommendations

1. Add first-class `tenants` and `tenant_memberships` before more customer-facing governance features are layered on top.
2. Add `tenant_id` to procedures, runs, run events, cases, approvals, artifacts, secrets, and API keys.
3. Extend request auth context from identity plus role to identity plus tenant plus permissions.
4. Replace global static API keys with managed tenant-bound service identities.
5. Add tenant-aware secret ownership and metadata filtering.
6. Add variable classification metadata and start deterministic redaction/tokenization hooks for LLM calls.
7. Define retention and erase policy objects before expanding enterprise customer onboarding.
8. Add policy checks to publish and promotion flows.

---

## 19. Final Recommendation

LangOrch should treat multi-tenancy and compliance as the next platform trust layer after identity/RBAC.

Recommended stance:

- tenants are explicit first-class security boundaries
- projects remain sub-tenant organization only
- every request resolves tenant before authorization
- every sensitive workflow can declare and enforce data-handling policy
- every enterprise deployment can explain who accessed what, under which tenant and policy context

If LangOrch wants to support multiple customers, multiple internal business boundaries, or regulated automation at scale, this layer cannot remain implicit.