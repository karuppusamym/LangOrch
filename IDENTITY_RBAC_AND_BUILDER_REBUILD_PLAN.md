# LangOrch Identity, RBAC, and Builder Rebuild Plan

Last updated: 2026-03-08

## 1. Purpose

This document defines the next-generation plan for:

- SSO-first user onboarding
- proper RBAC and permission management
- Entra ID / Azure AD group mapping for LOB, business, and technical teams
- manual user exceptions where needed
- API key identity and authorization model
- a full rebuild of the workflow builder so it becomes usable, modern, and understandable

This is a forward-looking design and product direction document. It is based on the current implementation in:

- `backend/app/api/auth.py`
- `backend/app/auth/deps.py`
- `backend/app/auth/roles.py`
- `backend/app/api/users.py`
- `frontend/src/lib/auth.ts`
- `frontend/src/components/WorkflowBuilder.tsx`

The intent is to stop treating identity/access and the builder as incremental patch areas and instead treat them as platform pillars.

---

## 2. Current State Summary

### 2.1 Identity and auth today

LangOrch currently supports:

- local username/password login
- Azure AD / OIDC SSO callback flow
- automatic SSO user provisioning on first login
- static API keys from config
- role-gated endpoints using `require_role()`

### 2.2 Role model today

The current platform role hierarchy is:

- `viewer`
- `approver`
- `operator`
- `manager`
- `admin`

This model is simple and workable, but it is still too coarse for enterprise environments where multiple business lines, technical teams, service identities, and regional or LOB boundaries must coexist.

### 2.3 SSO mapping today

Current SSO mapping is based on a single JSON config value:

- `SSO_ROLE_MAPPING`

This is enough for basic role assignment from AD group IDs or app roles, but it is not enough for ongoing group governance, LOB segmentation, scoped permissions, or delegated administration.

### 2.4 Manual user management today

Current user management supports:

- create user
- update user
- deactivate user
- delete user

This is useful, but it should become an exception path rather than the primary onboarding path for enterprise users.

### 2.5 API key model today

Current API keys are:

- static values from `settings.API_KEYS`
- all mapped to `operator`
- not individually named, scoped, expired, or audited as separate identities

This is acceptable for early development, but not acceptable for enterprise service-to-service governance.

### 2.6 Builder today

The current visual builder is based on React Flow / XYFlow and proves the concept, but it is not yet a production-grade authoring experience.

The main problems are:

- too much complexity in one component
- not friendly for non-expert users
- editing model is too close to raw graph structure
- inspector/form experience is not strong enough
- drag-and-drop is present, but the authoring workflow is still technical
- it does not yet feel like Dify, modern n8n, or other polished workflow tools

Conclusion:

- the current builder should not be evolved forever
- it should be rebuilt from base with a new UX and architecture

---

## 3. Target Identity Strategy

LangOrch should become **SSO-first, RBAC-governed, group-managed, and policy-auditable**.

The platform should support four identity sources:

1. SSO users
2. manually managed local users
3. service principals / app registrations
4. API keys for machine access

### 3.1 Guiding principles

1. SSO is the default onboarding path for humans.
2. Manual local users are exceptions, not the norm.
3. AD groups should drive most access assignments.
4. Individual user overrides must be supported, but tightly governed.
5. API keys must become first-class identities with explicit scopes and expiry.
6. Permissions should not depend only on a single coarse role string.

---

## 4. Target Authorization Model

LangOrch should move from simple hierarchical roles toward **Role + Permission + Scope**.

### 4.1 Keep platform roles, but narrow their purpose

The five current roles are still useful as platform base roles:

- `viewer`
- `approver`
- `operator`
- `manager`
- `admin`

But these should become **baseline bundles**, not the full authorization model.

### 4.2 Add explicit permission bundles

Permissions should be defined as named capabilities, for example:

- `runs.read`
- `runs.create`
- `runs.cancel`
- `runs.retry`
- `procedures.read`
- `procedures.write`
- `procedures.promote`
- `approvals.decide`
- `agents.manage`
- `users.read`
- `users.manage`
- `secrets.read_metadata`
- `secrets.write`
- `config.manage`
- `audit.read`
- `cases.read`
- `cases.claim`
- `cases.manage`
- `builder.edit`
- `builder.publish`

### 4.3 Add scope dimensions

Permissions should eventually be assignable with scope such as:

- global
- LOB
- business team
- technical team
- project
- procedure set
- environment (`dev`, `qa`, `prod`)

Examples:

- `procedures.write` on `LOB=Retail`
- `runs.read` on `project=claims-modernization`
- `approvals.decide` on `environment=prod`
- `cases.manage` on `team=Operations-NorthAmerica`

### 4.4 Recommended model

Use a hybrid model:

- RBAC for baseline role bundles
- group-to-role and group-to-permission mapping for enterprise onboarding
- limited ABAC-style scoping for LOB/team/project boundaries

This keeps the system understandable without turning it into an unmaintainable policy engine too early.

---

## 5. Azure AD / Entra ID Group Strategy

### 5.1 Why groups must become first-class

The expected future state includes:

- more AD groups for each LOB
- more groups for business teams
- more groups for technical teams
- possibly regional or environment-based separation

This means group mapping cannot remain a single static JSON blob forever.

### 5.2 Recommended group taxonomy

Use clear, managed naming conventions in Entra ID. Example:

- `LGO-Global-Admins`
- `LGO-Global-Platform-Managers`
- `LGO-LOB-Retail-Operators`
- `LGO-LOB-Banking-Approvers`
- `LGO-Team-Claims-Tech-Builders`
- `LGO-Team-Servicing-Business-Approvers`
- `LGO-API-Integration-SAP-Prod`

### 5.3 Group categories

Use three categories of groups:

1. Platform governance groups
2. Business/LOB operational groups
3. Technical team and integration groups

Examples:

#### Platform governance groups

- platform admin
- security admin
- audit/compliance read access
- production release approvers

#### Business/LOB groups

- LOB operators
- LOB approvers
- LOB managers
- case queue managers for specific departments

#### Technical team groups

- builder authors
- procedure publishers
- agent integration maintainers
- environment support team

### 5.4 Group mapping should support both role and permission assignment

Each AD group should be able to map to:

- one or more platform roles
- one or more explicit permissions
- optional scope constraints

Example target mapping:

```json
{
  "group_id": "aad-group-claims-ops",
  "display_name": "LGO-LOB-Claims-Operators",
  "roles": ["operator"],
  "permissions": ["runs.create", "runs.cancel", "cases.claim"],
  "scopes": {
    "lob": ["claims"]
  }
}
```

### 5.5 Group resolution precedence

Recommended precedence:

1. explicit deny rules if introduced later
2. direct individual override assignments
3. AD group assignments
4. default fallback role

The platform should never silently collapse conflicting group assignments without audit visibility.

---

## 6. Manual Users and Individual Exceptions

Manual users should still exist, but only for controlled cases.

### 6.1 Valid use cases for manual users

- break-glass emergency admin
- isolated lab/demo environment
- partner user not in corporate tenant
- temporary migration window
- non-SSO local integration test accounts

### 6.2 Individual override support

There will be real cases where a single user needs more or less than what their AD group provides.

The platform should support:

- direct role assignment
- direct permission grant
- direct permission revoke
- temporary elevated access with expiry

Every individual override must be:

- time-bound when possible
- auditable
- visible in UI
- reviewable by admins

### 6.3 Recommended governance rule

Default policy:

- group-managed access first
- individual override only by admin or delegated security admin
- all overrides require reason and expiry for elevated access

---

## 7. API Key and Service Identity Model

### 7.1 Current issue

Current API keys are static and all inherit the same operator-level behavior. This is too coarse.

### 7.2 Target API key model

API keys should become first-class records with:

- key ID
- display name
- owner
- source system
- created_at / expires_at
- revoked_at
- allowed roles
- allowed permissions
- allowed scopes
- optional IP restrictions
- optional environment restrictions
- audit history

### 7.3 Recommended identity types

Support these machine identity classes:

1. internal service key
2. external integration key
3. agent bootstrap key
4. CI/CD deployment key

### 7.4 Recommended API key authorization examples

Examples:

- SAP integration key: `runs.create`, `runs.read`, `cases.read`
- deployment pipeline key: `procedures.promote`, `builder.publish`
- agent bootstrap key: `agents.manage`, `agents.sync`

### 7.5 API keys should not default to operator forever

That behavior should be replaced by:

- explicit scopes and permissions per key
- individual revocation
- rotation support
- secret-value display only at creation time

---

## 8. Proposed Data Model Evolution

To support the target identity model, add first-class tables or equivalent entities for:

- `identity_providers`
- `directory_groups`
- `group_role_bindings`
- `group_permission_bindings`
- `user_role_overrides`
- `user_permission_overrides`
- `api_keys`
- `api_key_permission_bindings`
- `permission_definitions`
- `scope_assignments`

This should remain incremental. Do not try to build a full IAM suite in one sprint.

---

## 9. Recommended Onboarding Flow

### 9.1 Human users

Target onboarding flow:

1. user signs in with Entra ID / OIDC
2. platform resolves group memberships and app roles
3. platform computes effective roles and permissions
4. platform provisions or updates local profile
5. platform stores identity source, group links, effective auth snapshot, and audit trail

### 9.2 Manual users

Target onboarding flow:

1. admin creates local user only when justified
2. user is flagged as `local` identity source
3. access review can report all non-SSO identities

### 9.3 Machine identities

Target onboarding flow:

1. admin creates API key or service credential
2. key gets explicit scopes and expiry
3. audit logs capture usage by key ID and owner system

---

## 10. Effective Access Model

Every request should eventually resolve an effective access object like this:

```json
{
  "identity": "alice@company.com",
  "identity_type": "sso_user",
  "roles": ["operator"],
  "permissions": ["runs.create", "cases.claim", "procedures.read"],
  "scopes": {
    "lob": ["claims"],
    "environment": ["dev", "qa"]
  },
  "groups": [
    "LGO-LOB-Claims-Operators",
    "LGO-Team-Claims-Tech-Builders"
  ],
  "overrides": [
    {
      "type": "direct_permission_grant",
      "permission": "builder.publish",
      "expires_at": "2026-06-30T00:00:00Z"
    }
  ]
}
```

This should be inspectable in the UI for support, audit, and troubleshooting.

---

## 11. Builder Rebuild Decision

### 11.1 Decision

The current builder should be treated as a transitional prototype.

The strategic decision is:

- rebuild from base
- keep CKP as canonical contract
- separate graph editing from node configuration
- make authoring easy enough for analysts and technical operators, not just engineers

### 11.2 Product benchmark direction

The target builder experience should feel closer to:

- Dify
- modern n8n
- polished internal flow designers

This means:

- drag and drop is not enough
- the whole authoring journey must be easy to understand
- forms must feel guided, not raw
- edges, branches, approvals, and loop setup must be visually obvious

---

## 12. Problems With the Current Builder

The current builder is valuable as a technical proof, but not good enough as a platform authoring product.

Key issues:

1. The component is too large and too coupled.
2. Canvas operations and inspector logic are mixed together.
3. CKP concepts leak directly into the UI too early.
4. The UX is not progressive enough for non-technical authors.
5. The system does not yet provide enough guided templates, node forms, or validation flow.
6. The builder is graph-centric, not author-centric.

---

## 13. Rebuild Principles

### 13.1 Keep CKP as source of truth

The builder must not invent a separate workflow contract. It should edit a user-friendly representation that compiles to CKP.

### 13.2 Use schema-driven node forms

Each node type should define:

- display metadata
- form schema
- validation schema
- default values
- help text
- examples

This lets the inspector become stable and maintainable.

### 13.3 Separate the three layers

Rebuild the builder as three clean layers:

1. canvas graph model
2. node config form model
3. CKP import/export compiler layer

### 13.4 Prefer guided authoring over raw editing

For many node types the user should not start from blank JSON fields. The system should provide:

- sensible defaults
- pickers and dropdowns
- dynamic forms
- inline examples
- required-field hints
- validation before save/publish

---

## 14. Target Builder UX

### 14.1 Layout

Recommended layout:

- left rail: searchable node palette and templates
- main center canvas: graph editor
- right inspector: structured configuration panel for selected node/edge
- bottom panel: validation, compile output, test run, errors, warnings

### 14.2 Core authoring interactions

Must support:

- drag node onto canvas
- connect nodes visually
- label branches clearly
- configure node through forms
- preview generated CKP
- validate before publish
- save as draft
- publish/promotion flow later

### 14.3 Must-have usability features

- undo / redo
- copy / paste node blocks
- keyboard shortcuts
- auto-layout
- zoom-to-fit
- minimap
- autosave draft
- inline validation
- branch and loop visual clarity
- node templates and examples

### 14.4 Node-level UX expectations

Examples:

- `human_approval` should have an obvious approval card form
- `logic` should have rule builder UI, not raw arrays first
- `loop` should visually explain iterator and body
- `llm_action` should expose prompt, model, output parsing, and cost hints clearly
- `subflow` should support search/select of procedures, not free-text only

---

## 15. Recommended Builder Technical Architecture

### 15.1 Suggested frontend architecture

Break the builder into dedicated modules:

- graph state store
- node schema registry
- inspector form renderer
- edge/branch editor
- layout service
- CKP adapter layer
- validation service
- template library

### 15.2 Suggested libraries

Reasonable direction:

- keep a graph canvas library only if it remains a thin rendering layer
- use a proper form system for inspector rendering
- use a schema-based validation layer
- avoid keeping all authoring logic inside one monolithic ReactFlow component

### 15.3 Recommended data flow

1. user edits visual graph state
2. inspector writes structured node config
3. graph model compiles into CKP draft
4. validator produces warnings/errors
5. publish path stores CKP artifact

---

## 16. Suggested Rebuild Phases

### Phase A: foundation

- define node schema registry
- define builder domain state model
- define CKP adapter layer
- define inspector component system

### Phase B: core authoring UX

- rebuild canvas + palette + inspector
- support sequence, logic, human approval, terminate first
- support draft autosave and validation

### Phase C: advanced authoring

- loop, parallel, subflow, llm_action, verification
- templates
- test-run from builder
- change tracking / diff view

### Phase D: platform-grade polish

- accessibility
- collaboration readiness
- role-aware authoring/publishing
- environment-aware publishing flow

---

## 17. Immediate Backlog Recommendations

### Identity / RBAC

1. Document current role-to-endpoint matrix.
2. Add first-class permission catalog.
3. Replace `SSO_ROLE_MAPPING` single JSON blob with persistent group mapping records.
4. Add AD group admin UI and effective-access viewer.
5. Add user override model with audit and expiry.
6. Replace static API key list with managed API key entities.

### Builder

1. Freeze major investment in the current builder except critical fixes.
2. Create a new builder architecture RFC and component breakdown.
3. Build node schema registry first.
4. Rebuild the inspector and form system before rebuilding all canvas features.
5. Deliver a modern MVP with 4 to 5 highest-use node types first.

---

## 18. Final Recommendation

LangOrch should move to this identity and authoring stance:

- **SSO-first for humans**
- **AD-group managed by default**
- **manual users only as exceptions**
- **API keys as first-class service identities**
- **roles kept as coarse bundles, permissions added for real governance**
- **builder rebuilt from base as a modern, guided workflow authoring tool**

This is the right direction if LangOrch is expected to support:

- multiple business lines
- multiple technical teams
- multiple AD groups
- delegated operational ownership
- enterprise onboarding and governance
- less technical workflow authors over time

Without these two upgrades, identity/access and workflow authoring will remain the biggest friction points even if the runtime keeps getting stronger.

---

## 19. Related Platform Trust Layers

This document intentionally focuses on identity, RBAC, API keys, and authoring UX.

Two adjacent platform layers also need to move forward in parallel:

1. multi-tenant isolation
2. compliance controls

Those areas should not be treated as optional follow-up cleanup because they directly affect how identity and authorization behave in production.

Specifically:

- group-managed RBAC becomes incomplete if users are not resolved inside an explicit tenant boundary
- API keys become unsafe if they are not tenant-bound and audit-scoped
- delegated administration becomes risky without tenant-scoped visibility and quotas
- builder publish flows eventually need policy checks for data handling, environment rules, and compliance gates

See `MULTI_TENANCY_AND_COMPLIANCE_PLAN.md` for the companion trust-layer plan covering tenant boundaries, tenant-scoped request context, secret segregation, PII tokenization, retention, erase workflows, and policy-as-code publish controls.