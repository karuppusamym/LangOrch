# Business Builder V1 Requirements

Last updated: 2026-03-08

## 1. Purpose

This file defines the minimum product requirements for a business-friendly version 1 of the LangOrch visual builder.

It exists to stop the rebuild from becoming only a technical refactor.

The target is a builder that business and operations users can understand, while still allowing technical users to access deeper orchestration controls when needed.

## 2. Primary audience for v1

The primary phase-1 audience should be:

1. operations managers
2. process owners
3. solution builders inside business teams
4. technical admins as secondary users

This means the product should optimize first for comprehension and confidence, not maximum flexibility on day one.

## 3. Product promise for v1

The builder should let a business user:

- start from a real template
- understand the flow visually
- edit common workflow behavior safely
- see approval and escalation paths clearly
- validate before publishing
- monitor a live run through the same visual flow

The builder does not need to expose every advanced runtime option by default.

## 4. V1 success definition

V1 is successful only if a business user can do the following without reading CKP JSON:

1. create a workflow from a template
2. rename steps in plain language
3. configure an approval flow
4. connect steps and understand the path
5. validate and publish with confidence
6. watch a run move through the graph live

## 5. V1 scope

### In scope

1. automation-first builder
2. template-based workflow creation
3. visual node editing
4. simple mode and advanced mode
5. draft autosave
6. validation panel
7. compile preview
8. publish flow
9. live graph monitoring
10. replay view for completed runs

### Out of scope

1. full Dify-like AI app studio
2. complex multi-user co-editing
3. tenant-aware collaborative workspaces
4. marketplace-level template ecosystem
5. full no-code knowledge-base management

## 6. V1 screens required

### 6.1 Builder home

This screen should help users start quickly.

Required elements:

- recent procedures
- start from template
- create blank procedure
- search existing workflows
- simple explanation of what the builder does

### 6.2 Builder canvas screen

This is the core authoring screen.

Required layout:

- left template or node palette
- center graph canvas
- right inspector panel
- top toolbar for validate, preview, publish, mode toggle
- bottom or side status area for errors and warnings

### 6.3 Validation and preview screen or panel

Required capabilities:

- error list by node
- warning list by node
- compile preview summary
- likely path explanation
- publish blocker vs non-blocker distinction

### 6.4 Live graph run screen

Required capabilities:

- current node highlight
- completed and failed states
- paused approval states
- retry indicators
- linked timeline
- replay mode for past runs

## 7. UX rules for business friendliness

### 7.1 Plain language first

Use labels that explain intent, not just engine concepts.

Prefer:

- Request Approval
- Check Customer Data
- Send API Update
- Wait for Callback

Avoid relying on raw internal names alone.

### 7.2 Progressive disclosure

Default to simple mode.

Show advanced runtime fields only when the user explicitly expands advanced settings.

Advanced fields include:

- retries
- timeouts
- expressions
- callback tuning
- agent routing
- resource controls

### 7.3 Safe defaults

Every guided node form should ship with reasonable defaults.

Examples:

- approval node has default decision flow
- terminate node has default success status
- logic node starts from a guided rule template
- sequence node starts from a suggested step block

### 7.4 Do not force JSON literacy

Business users should not need to understand `workflow_graph`, `retry_policy`, `IR`, or raw CKP fields to use the builder.

The source view can exist, but it must not be the normal authoring path.

## 8. Required mode split

### Simple mode

Simple mode should be the default.

Simple mode includes:

- plain-language labels
- guided forms
- template-based starting points
- visual next-step summaries
- friendly validation messages
- publish checks

### Advanced mode

Advanced mode is for technical builders.

Advanced mode includes:

- retry and timeout tuning
- variable and mapping detail
- expression editing
- agent routing
- callback controls
- runtime-specific options

## 9. Required node types for v1

These node types should have guided, business-friendly forms in v1:

1. sequence
2. logic
3. human_approval
4. transform
5. subflow
6. terminate

These can exist in v1 but may expose more technical UI initially:

1. loop
2. parallel
3. processing
4. verification
5. llm_action

## 10. Template requirements

Templates are critical for business adoption.

V1 should include a small set of strong templates instead of many weak ones.

Recommended templates:

1. invoice review and approval
2. customer onboarding review
3. case triage and escalation
4. callback-based API process
5. human review with retry and timeout

Each template should include:

- title
- business description
- who uses it
- what happens on success
- what happens on failure

## 11. Validation message rules

Validation messages must be understandable by non-engineers.

Good example:

- This approval step has no reject path. If a reviewer rejects it, the workflow will stop here.

Bad example:

- Missing `on_reject` transition.

Technical detail can still be shown, but only as secondary information.

## 12. Publish flow requirements

Publishing should feel safe and understandable.

Required publish checks:

1. show changed nodes
2. show new or removed approval paths
3. show missing failure paths
4. show warnings for timeout or retry changes
5. show release impact summary

Required publish actions:

1. validate
2. preview
3. publish draft
4. cancel

## 13. Live graph requirements

Business users must be able to understand run progress without reading raw logs.

Required live graph behavior:

1. clearly show current step
2. clearly show failed step
3. clearly show waiting approval step
4. show short human-readable reason for pauses or failures
5. sync with timeline and details panel
6. support replay for completed runs

## 14. Acceptance criteria

The builder is acceptable for business users only if all of the following are true.

1. A first-time user can create a template-based workflow in under 15 minutes.
2. A first-time user can identify the approval and failure paths visually.
3. A user can publish without touching source JSON.
4. A user can understand a validation error without engineering help.
5. A user can understand where a live run is blocked in under 30 seconds.

## 15. Design principle summary

The product should feel like:

- a process design tool for business users
- an operational workflow control surface
- a guided orchestration product

It should not feel like:

- a raw graph engine editor
- a developer-only schema surface
- a canvas full of unexplained system concepts

## 16. Proceed recommendation

Proceed with builder-v2 only if these principles are treated as build requirements, not optional polish.

If they are deferred, the platform may become technically impressive but adoption will remain narrow.