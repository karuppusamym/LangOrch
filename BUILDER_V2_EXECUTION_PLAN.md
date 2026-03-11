# Builder V2 Execution Plan

Last updated: 2026-03-08

## 1. Purpose

This file is the concrete execution plan for building LangOrch Builder V2.

It exists to answer these questions before implementation starts:

1. what exactly are we building
2. in what order we are building it
3. what is explicitly out of scope for phase 1
4. how we will know each phase is complete

This plan is intended to remove ambiguity before code work begins.

## 2. What we are building

We are building an automation-first visual workflow builder for LangOrch that is:

- business-friendly in default usage
- technically strong underneath
- compatible with CKP as the canonical runtime contract
- separated from the live execution graph concerns
- ready for future Dify-like expansion without becoming a Dify clone

Builder V2 is not just a UI rewrite.

It is a structured product rebuild with these foundations:

- typed builder draft model
- draft lifecycle
- validation and compile preview
- publish flow
- simple mode and advanced mode
- live graph integration path

## 3. What phase 1 is not

Phase 1 is not:

- a full Dify replacement
- a collaborative multi-user builder
- a complete AI app studio
- a full RAG authoring system
- a tenant-aware workspace platform
- a marketplace ecosystem

If we try to build those now, the sequence will fail.

## 4. Source documents that define the build

This execution plan depends on these repo documents:

- `VISUAL_BUILDER_REBUILD_REFERENCE.md`
- `BUSINESS_BUILDER_V1_REQUIREMENTS.md`
- `frontend/src/builder-v2/reference-contract.ts`

These three documents together define:

- architecture
- business-user target
- starting data contracts

## 5. Phase sequence

### Phase 0: foundation lock

Goal:

Confirm contracts and scope before major implementation.

Deliverables:

1. builder execution plan
2. business builder requirements
3. reference contract for builder draft and node registry

Completion gate:

- product scope is written down
- v1 audience is explicit
- phase-1 non-goals are explicit

Status:

- complete

### Phase 1: legacy extraction

Goal:

Reduce risk by extracting key logic from the current builder without changing user-facing behavior yet.

Tasks:

1. extract `ckpToRf` from legacy builder
2. extract `rfToCkp` from legacy builder
3. extract node palette definitions
4. extract templates
5. isolate reusable builder types

Primary files likely affected:

- `frontend/src/components/WorkflowBuilder.tsx`
- new transform and config files under `frontend/src/builder-v2/` or shared builder modules

Completion gate:

- current builder still works
- transform logic exists outside the monolith
- no TypeScript regressions introduced

### Phase 2: builder-v2 shell

Goal:

Create the new builder structure without requiring full feature parity immediately.

Tasks:

1. scaffold builder-v2 folder structure
2. create `BuilderShell`
3. create central builder store
4. create canvas container
5. create inspector container
6. create palette container
7. wire mode toggle for simple and advanced mode

Primary result:

- a navigable Builder V2 shell with typed state

Completion gate:

- shell renders
- builder state flows through central store
- no coupling back into legacy monolith beyond transforms

### Phase 3: draft lifecycle

Goal:

Stop editing raw CKP in transient component state.

Tasks:

1. define builder draft document shape in code
2. map CKP to builder draft
3. map builder draft to CKP
4. add dirty state tracking
5. add local autosave placeholder or API contract wiring

Completion gate:

- builder edits draft model, not raw CKP directly
- save path is deterministic
- draft conversion is testable

### Phase 4: business-friendly authoring

Goal:

Make V2 usable for business users.

Tasks:

1. implement simple mode
2. add guided node forms for v1 node types
3. add plain-language labels and summaries
4. add template-driven starting flows
5. hide advanced runtime controls behind expansion

V1 guided node types:

1. sequence
2. logic
3. human_approval
4. transform
5. subflow
6. terminate

Completion gate:

- a business user can build a basic approval flow without CKP editing

### Phase 5: validation and compile preview

Goal:

Add trust and safety before publish.

Tasks:

1. builder validation panel
2. error and warning grouping by node
3. compile preview contract
4. likely execution path summary
5. publish blocker versus warning distinction

Completion gate:

- users can validate before publish
- validation messages are understandable
- publish is guarded by checks

### Phase 6: publish flow

Goal:

Make publishing understandable and safe.

Tasks:

1. draft-to-CKP publish path
2. publish review screen or modal
3. changed nodes summary
4. approval path changes summary
5. release impact summary

Completion gate:

- users can publish without touching raw source
- dangerous changes are highlighted

### Phase 7: live graph integration

Goal:

Connect builder-v2 to monitoring and runtime visibility.

Tasks:

1. define live-graph state mapper
2. connect run event stream to graph overlay model
3. keep execution graph separate from authoring interactions
4. support node status overlays and replay mode

Completion gate:

- live run state is understandable visually
- graph and timeline stay aligned

## 6. Detailed task inventory

### Frontend tasks

1. create builder-v2 module structure
2. create draft document state shape
3. create transform modules
4. create node registry and node definitions
5. create simple mode inspector forms
6. create advanced settings pattern
7. create validation and preview panels
8. connect publish flow
9. connect live graph overlay inputs

### Backend tasks

1. define builder draft API contract
2. define compile preview API contract
3. expose validation response in builder-friendly shape
4. optionally add draft persistence table in later step if not immediate

### UX tasks

1. define simple mode copy and labels
2. define template cards
3. define validation message copy rules
4. define publish warning patterns

## 7. Coverage checklist

This is the detail coverage we must not miss.

### Core architecture

- CKP remains canonical
- builder draft separated from runtime contract
- authoring graph separated from live graph
- simple mode and advanced mode both exist

### Business-user coverage

- templates
- plain-language labels
- guided forms
- safe defaults
- understandable validation
- publish confidence

### Operational coverage

- approval paths
- retry and timeout semantics
- failure paths
- live graph overlays
- replay mode

### Extensibility coverage

- builder-v2 does not block future AppSpec or Dify-like layer
- registry-based node architecture
- contracts separated from UI components

## 8. Risks if sequence is ignored

If we skip the sequence, the likely failures are:

1. another monolithic builder
2. business users still dislike the UX
3. live graph gets bolted on badly
4. draft and publish semantics remain muddy
5. future AI-app extension becomes messy

## 9. Decision checkpoint before coding

Before major implementation begins, the answer to these should be yes.

1. Are we building automation-first builder v2 first? Yes.
2. Are we keeping CKP canonical? Yes.
3. Are we separating draft model from runtime model? Yes.
4. Are we treating business friendliness as a build requirement? Yes.
5. Are we keeping live graph as a first-class capability? Yes.
6. Are Dify-like features deferred into a later layer instead of forced into phase 1? Yes.

## 10. Proceed recommendation

Yes, the plan is coherent enough to proceed.

The next correct implementation step is Phase 1:

1. extract legacy transforms
2. scaffold builder-v2 shell and store
3. start the draft-based authoring path

That is the lowest-risk, highest-signal place to begin.