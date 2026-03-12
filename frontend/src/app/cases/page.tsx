"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  claimCase,
  createCase,
  createRun,
  createCaseSlaPolicy,
  createCaseWebhook,
  getCaseQueueAnalytics,
  getCaseWebhookDlqCount,
  getCaseWebhookDeliverySummary,
  deleteCase,
  deleteCaseSlaPolicy,
  deleteCaseWebhook,
  getProcedure,
  listCaseEvents,
  listCaseQueue,
  listCaseSlaPolicies,
  listCaseWebhooks,
  listCaseWebhookDlq,
  listCases,
  listProcedures,
  listProjects,
  listRuns,
  replayCaseWebhookDelivery,
  replayCaseWebhookDlq,
  replayCaseWebhookDlqSelected,
  purgeCaseWebhookDlq,
  purgeCaseWebhookDlqSelected,
  releaseCase,
  updateCase,
  updateCaseSlaPolicy,
  isNotFoundError,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { flattenVariablesSchema, isFieldSensitive } from "@/lib/redact";
import type {
  Case,
  CaseEvent,
  CaseQueueItem,
  CaseQueueAnalytics,
  CaseSlaPolicy,
  CaseWebhookDelivery,
  CaseWebhookDeliverySummary,
  CaseWebhookSubscription,
  Procedure,
  Project,
  Run,
} from "@/lib/types";
import type { ProcedureDetail } from "@/lib/types";

type TabKey = "cases" | "queue" | "sla" | "webhooks";
const TAB_KEYS: TabKey[] = ["cases", "queue", "sla", "webhooks"];
const TAB_LABELS: Record<TabKey, string> = {
  cases: "Cases",
  queue: "Queue",
  sla: "SLA",
  webhooks: "Webhooks",
};

const STATUS_OPTIONS = ["open", "in_progress", "resolved", "closed", "escalated"];
const PRIORITY_OPTIONS = ["urgent", "high", "normal", "low"];
const WEBHOOK_EVENT_OPTIONS = [
  "*",
  "case_created",
  "case_updated",
  "case_claimed",
  "case_released",
  "case_sla_breached",
  "run_linked",
];

function fmtDate(value: string | null | undefined) {
  if (!value) return "-";
  const dt = new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString();
}

function parseMetadata(raw: string): Record<string, unknown> | null {
  if (!raw.trim()) return null;
  const parsed = JSON.parse(raw);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("metadata must be a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function Pill({ value }: { value: string }) {
  return <span className="rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs">{value}</span>;
}

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
  return sorted[idx] ?? 0;
}

function buildQueueAnalyticsFallback(items: CaseQueueItem[], riskWindowMinutes: number): CaseQueueAnalytics {
  const total = items.length;
  const unassigned = items.filter((item) => !item.owner).length;
  const breached = items.filter((item) => item.is_sla_breached).length;
  const riskWindowSeconds = Math.max(0, riskWindowMinutes) * 60;
  const riskCases = items.filter((item) => {
    if (item.is_sla_breached) return false;
    if (item.sla_remaining_seconds == null) return false;
    return item.sla_remaining_seconds <= riskWindowSeconds;
  }).length;
  const waits = items.map((item) => Math.max(0, item.age_seconds || 0));

  const waitByPriority: Record<string, { count: number; wait_p50_seconds: number; wait_p95_seconds: number }> = {};
  const waitByCaseType: Record<string, { count: number; wait_p50_seconds: number; wait_p95_seconds: number }> = {};

  const addGrouped = (
    bucket: Record<string, { count: number; wait_p50_seconds: number; wait_p95_seconds: number }>,
    key: string,
    wait: number
  ) => {
    const current = bucket[key] ?? { count: 0, wait_p50_seconds: 0, wait_p95_seconds: 0 };
    const raw = (bucket as any)[`${key}__raw`] as number[] | undefined;
    const values = raw ?? [];
    values.push(wait);
    bucket[key] = {
      count: values.length,
      wait_p50_seconds: percentile(values, 0.5),
      wait_p95_seconds: percentile(values, 0.95),
    };
    (bucket as any)[`${key}__raw`] = values;
  };

  for (const item of items) {
    const wait = Math.max(0, item.age_seconds || 0);
    addGrouped(waitByPriority, item.priority || "unknown", wait);
    addGrouped(waitByCaseType, item.case_type || "unknown", wait);
  }

  // Remove internal raw arrays used for local aggregation.
  for (const key of Object.keys(waitByPriority)) {
    if (key.endsWith("__raw")) delete (waitByPriority as any)[key];
  }
  for (const key of Object.keys(waitByCaseType)) {
    if (key.endsWith("__raw")) delete (waitByCaseType as any)[key];
  }

  return {
    total_active_cases: total,
    unassigned_cases: unassigned,
    breached_cases: breached,
    breach_risk_next_window_cases: riskCases,
    breach_risk_next_window_percent: total > 0 ? (riskCases / total) * 100 : 0,
    wait_p50_seconds: percentile(waits, 0.5),
    wait_p95_seconds: percentile(waits, 0.95),
    wait_by_priority: waitByPriority,
    wait_by_case_type: waitByCaseType,
    reassignment_rate_24h: 0,
    abandonment_rate_24h: 0,
  };
}

function CasesPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();

  const [tab, setTab] = useState<TabKey>("cases");
  const [projects, setProjects] = useState<Project[]>([]);
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [queueItems, setQueueItems] = useState<CaseQueueItem[]>([]);
  const [queueAnalytics, setQueueAnalytics] = useState<CaseQueueAnalytics | null>(null);
  const [events, setEvents] = useState<CaseEvent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [policies, setPolicies] = useState<CaseSlaPolicy[]>([]);
  const [webhooks, setWebhooks] = useState<CaseWebhookSubscription[]>([]);
  const [webhookDlq, setWebhookDlq] = useState<CaseWebhookDelivery[]>([]);
  const [webhookSummary, setWebhookSummary] = useState<CaseWebhookDeliverySummary | null>(null);
  const [webhookDlqTotal, setWebhookDlqTotal] = useState(0);
  const [replayingDeliveryId, setReplayingDeliveryId] = useState<string | null>(null);
  const [replayingAllDlq, setReplayingAllDlq] = useState(false);
  const [replayingSelectedDlq, setReplayingSelectedDlq] = useState(false);
  const [purgingDlq, setPurgingDlq] = useState(false);
  const [purgingSelectedDlq, setPurgingSelectedDlq] = useState(false);
  const [selectedDlqDeliveryIds, setSelectedDlqDeliveryIds] = useState<string[]>([]);

  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [claimOwner, setClaimOwner] = useState("");
  const [runProcedureRef, setRunProcedureRef] = useState("");
  const [creatingRunForCaseId, setCreatingRunForCaseId] = useState<string | null>(null);
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [runModalCase, setRunModalCase] = useState<Case | null>(null);
  const [runModalProcedure, setRunModalProcedure] = useState<ProcedureDetail | null>(null);
  const [runVarsForm, setRunVarsForm] = useState<Record<string, string>>({});
  const [runVarsErrors, setRunVarsErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const [caseProjectFilter, setCaseProjectFilter] = useState("");
  const [caseStatusFilter, setCaseStatusFilter] = useState("all");
  const [queueProjectFilter, setQueueProjectFilter] = useState("");
  const [queueUnassigned, setQueueUnassigned] = useState(false);
  const [queueTerminal, setQueueTerminal] = useState(false);
  const [slaProjectFilter, setSlaProjectFilter] = useState("");
  const [webhookProjectFilter, setWebhookProjectFilter] = useState("");

  const [createCaseOpen, setCreateCaseOpen] = useState(false);
  const [newCaseTitle, setNewCaseTitle] = useState("");
  const [newCaseProject, setNewCaseProject] = useState("");
  const [newCaseType, setNewCaseType] = useState("");
  const [newCaseExt, setNewCaseExt] = useState("");
  const [newCasePriority, setNewCasePriority] = useState("normal");
  const [newCaseOwner, setNewCaseOwner] = useState("");
  const [newCaseTags, setNewCaseTags] = useState("");
  const [newCaseMeta, setNewCaseMeta] = useState("");

  const [newPolicyName, setNewPolicyName] = useState("");
  const [newPolicyProject, setNewPolicyProject] = useState("");
  const [newPolicyType, setNewPolicyType] = useState("");
  const [newPolicyPriority, setNewPolicyPriority] = useState("");
  const [newPolicyDueMins, setNewPolicyDueMins] = useState("1440");
  const [newPolicyBreachStatus, setNewPolicyBreachStatus] = useState("escalated");

  const [newWebhookEvent, setNewWebhookEvent] = useState("*");
  const [newWebhookUrl, setNewWebhookUrl] = useState("");
  const [newWebhookProject, setNewWebhookProject] = useState("");
  const [newWebhookSecret, setNewWebhookSecret] = useState("");
  const [dlqPurgeOlderHours, setDlqPurgeOlderHours] = useState(24);
  const [dlqPurgeLimit, setDlqPurgeLimit] = useState(1000);
  const [dlqSubscriptionFilter, setDlqSubscriptionFilter] = useState("");
  const [dlqEventFilter, setDlqEventFilter] = useState("");
  const [dlqCaseFilter, setDlqCaseFilter] = useState("");
  const [dlqPage, setDlqPage] = useState(1);
  const [dlqPageSize, setDlqPageSize] = useState(25);
  const [dlqSortBy, setDlqSortBy] = useState<"updated_at" | "attempts">("updated_at");
  const [dlqSortDir, setDlqSortDir] = useState<"asc" | "desc">("desc");
  const [urlStateHydrated, setUrlStateHydrated] = useState(false);
  const queueAnalyticsFallbackNotifiedRef = useRef(false);

  const [deleteCaseTarget, setDeleteCaseTarget] = useState<Case | null>(null);
  const [deletePolicyTarget, setDeletePolicyTarget] = useState<CaseSlaPolicy | null>(null);
  const [deleteWebhookTarget, setDeleteWebhookTarget] = useState<CaseWebhookSubscription | null>(null);

  const selectedCase = useMemo(() => cases.find((c) => c.case_id === selectedCaseId) ?? null, [cases, selectedCaseId]);
  const launchableProcedures = useMemo(() => {
    const selected = selectedCase;
    const active = procedures.filter((p) => p.status !== "archived" && p.status !== "deprecated");
    if (!selected) return active;
    if (!selected.project_id) return active;
    const scoped = active.filter((p) => p.project_id === selected.project_id);
    return scoped.length > 0 ? scoped : active;
  }, [procedures, selectedCase]);

  const runModalSchema = useMemo(
    () => flattenVariablesSchema(((runModalProcedure?.ckp_json as any)?.variables_schema ?? {}) as Record<string, unknown>),
    [runModalProcedure]
  );
  const runModalSchemaEntries = useMemo(() => Object.entries(runModalSchema) as [string, any][], [runModalSchema]);
  const runModalMustFillEntries = useMemo(
    () => runModalSchemaEntries.filter(([, meta]) => !!meta?.required && meta?.default === undefined),
    [runModalSchemaEntries]
  );
  const runModalOverrideEntries = useMemo(
    () => runModalSchemaEntries.filter(([, meta]) => !meta?.required || meta?.default !== undefined),
    [runModalSchemaEntries]
  );
  const dlqTotalFailed = webhookDlqTotal;
  const dlqSelectionCount = selectedDlqDeliveryIds.length;
  const dlqVisibleCount = webhookDlq.length;
  const dlqHasFilters = Boolean(dlqSubscriptionFilter || dlqEventFilter || dlqCaseFilter);
  const dlqTotalPages = Math.max(1, Math.ceil(dlqTotalFailed / Math.max(1, dlqPageSize)));

  useEffect(() => {
    if (dlqPage > dlqTotalPages) {
      setDlqPage(dlqTotalPages);
    }
  }, [dlqPage, dlqTotalPages]);

  function isTabKey(value: string | null): value is TabKey {
    return value !== null && TAB_KEYS.includes(value as TabKey);
  }

  function syncTabToUrl(nextTab: TabKey) {
    const qs = new URLSearchParams(searchParams.toString());
    if (nextTab === "cases") qs.delete("tab");
    else qs.set("tab", nextTab);
    const query = qs.toString();
    router.replace(`/cases${query ? `?${query}` : ""}`, { scroll: false });
  }

  useEffect(() => {
    const requestedTab = searchParams.get("tab");
    setTab(isTabKey(requestedTab) ? requestedTab : "cases");
    setUrlStateHydrated(true);
  }, [searchParams]);

  useEffect(() => {
    void Promise.all([
      listProjects().then(setProjects),
      listProcedures().then(setProcedures),
    ]).catch(() => null);
  }, []);

  async function loadCases() {
    setLoading(true);
    try {
      const data = await listCases({
        project_id: caseProjectFilter || undefined,
        status: caseStatusFilter === "all" ? undefined : caseStatusFilter,
        order: "desc",
        limit: 100,
      });
      setCases(data);
      if (!selectedCaseId && data[0]) setSelectedCaseId(data[0].case_id);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load cases", "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadQueue() {
    setLoading(true);
    try {
      const riskWindowMinutes = 60;
      const [items, analytics] = await Promise.all([
        listCaseQueue({
          project_id: queueProjectFilter || undefined,
          only_unassigned: queueUnassigned,
          include_terminal: queueTerminal,
          limit: 100,
        }),
        getCaseQueueAnalytics({
          project_id: queueProjectFilter || undefined,
          risk_window_minutes: riskWindowMinutes,
        }).catch((err) => {
          const msg = err instanceof Error ? err.message : String(err);
          if (msg.includes("API 404")) return null;
          throw err;
        }),
      ]);
      setQueueItems(items);
      if (analytics) {
        setQueueAnalytics(analytics);
      } else {
        setQueueAnalytics(buildQueueAnalyticsFallback(items, riskWindowMinutes));
        if (!queueAnalyticsFallbackNotifiedRef.current) {
          toast("Queue analytics endpoint not available on this backend; showing computed fallback metrics.", "error");
          queueAnalyticsFallbackNotifiedRef.current = true;
        }
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load queue", "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadPolicies() {
    setLoading(true);
    try {
      setPolicies(await listCaseSlaPolicies({ project_id: slaProjectFilter || undefined }));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load SLA policies", "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadWebhooks() {
    setLoading(true);
    try {
      const [hookRows, dlqRows, dlqCount, summary] = await Promise.all([
        listCaseWebhooks({ project_id: webhookProjectFilter || undefined }),
        listCaseWebhookDlq({
          subscription_id: dlqSubscriptionFilter || undefined,
          event_type: dlqEventFilter || undefined,
          case_id: dlqCaseFilter || undefined,
          sort_by: dlqSortBy,
          order: dlqSortDir,
          limit: dlqPageSize,
          offset: (dlqPage - 1) * dlqPageSize,
        }),
        getCaseWebhookDlqCount({
          subscription_id: dlqSubscriptionFilter || undefined,
          event_type: dlqEventFilter || undefined,
          case_id: dlqCaseFilter || undefined,
        }),
        getCaseWebhookDeliverySummary({
          subscription_id: dlqSubscriptionFilter || undefined,
          event_type: dlqEventFilter || undefined,
          case_id: dlqCaseFilter || undefined,
        }),
      ]);
      setWebhooks(hookRows);
      setWebhookDlq(dlqRows);
      setWebhookDlqTotal(dlqCount.total);
      setWebhookSummary(summary);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load webhooks", "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadSelectedCaseActivity(caseId: string) {
    try {
      const [caseEvents, caseRuns] = await Promise.all([
        listCaseEvents(caseId, 200),
        listRuns({ case_id: caseId, limit: 100, order: "desc" }),
      ]);
      if (selectedCaseId === caseId) {
        setEvents(caseEvents);
        setRuns(caseRuns);
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load case activity", "error");
    }
  }

  useEffect(() => {
    if (!urlStateHydrated) return;

    if (tab === "cases") {
      void loadCases();
      return;
    }

    if (tab === "queue") {
      void loadQueue();
      return;
    }

    if (tab === "sla") {
      void loadPolicies();
      return;
    }

    void loadWebhooks();
  }, [
    urlStateHydrated,
    tab,
    caseProjectFilter,
    caseStatusFilter,
    queueProjectFilter,
    queueUnassigned,
    queueTerminal,
    slaProjectFilter,
    webhookProjectFilter,
    dlqSubscriptionFilter,
    dlqEventFilter,
    dlqCaseFilter,
    dlqPage,
    dlqPageSize,
    dlqSortBy,
    dlqSortDir,
  ]);

  useEffect(() => {
    if (!selectedCaseId) {
      setEvents([]);
      setRuns([]);
      return;
    }
    void loadSelectedCaseActivity(selectedCaseId);
  }, [selectedCaseId]);

  async function handleReplayDelivery(deliveryId: string) {
    setReplayingDeliveryId(deliveryId);
    try {
      const res = await replayCaseWebhookDelivery(deliveryId);
      toast(`Replayed ${res.replayed} delivery`, "success");
      await loadWebhooks();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to replay delivery", "error");
    } finally {
      setReplayingDeliveryId(null);
    }
  }

  async function handleReplayAllDlq() {
    setReplayingAllDlq(true);
    try {
      const res = await replayCaseWebhookDlq({
        subscription_id: dlqSubscriptionFilter || undefined,
        event_type: dlqEventFilter || undefined,
        case_id: dlqCaseFilter || undefined,
        limit: 100,
      });
      toast(`Replayed ${res.replayed} failed deliveries`, "success");
      await loadWebhooks();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to replay failed deliveries", "error");
    } finally {
      setReplayingAllDlq(false);
    }
  }

  async function handleReplaySelectedDlq() {
    if (selectedDlqDeliveryIds.length === 0) return;
    setReplayingSelectedDlq(true);
    try {
      const res = await replayCaseWebhookDlqSelected(selectedDlqDeliveryIds);
      const skipped = res.skipped_non_failed_ids?.length ?? 0;
      const notFound = res.not_found_ids?.length ?? 0;
      const parts = [
        `Replayed ${res.replayed}`,
        skipped > 0 ? `skipped ${skipped}` : null,
        notFound > 0 ? `not found ${notFound}` : null,
      ].filter(Boolean);
      toast(parts.join(" | "), "success");
      setSelectedDlqDeliveryIds([]);
      await loadWebhooks();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to replay selected deliveries", "error");
    } finally {
      setReplayingSelectedDlq(false);
    }
  }

  async function handlePurgeDlq() {
    const purgeLimit = Math.max(1, Math.min(dlqPurgeLimit, 5000));
    let preview;
    try {
      preview = await getCaseWebhookDlqCount({
        subscription_id: dlqSubscriptionFilter || undefined,
        event_type: dlqEventFilter || undefined,
        case_id: dlqCaseFilter || undefined,
        older_than_hours: dlqPurgeOlderHours,
      });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to preview purge impact", "error");
      return;
    }
    const purgeCount = Math.min(preview.total, purgeLimit);
    const confirm = window.confirm(
      `Purge up to ${purgeCount} failed deliveries (matches: ${preview.total}) older than ${dlqPurgeOlderHours}h for current DLQ filters?`
    );
    if (!confirm) return;

    setPurgingDlq(true);
    try {
      const res = await purgeCaseWebhookDlq({
        subscription_id: dlqSubscriptionFilter || undefined,
        event_type: dlqEventFilter || undefined,
        case_id: dlqCaseFilter || undefined,
        older_than_hours: dlqPurgeOlderHours,
        limit: purgeLimit,
      });
      toast(`Purged ${res.deleted} failed deliveries`, "success");
      setSelectedDlqDeliveryIds([]);
      await loadWebhooks();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to purge failed deliveries", "error");
    } finally {
      setPurgingDlq(false);
    }
  }

  async function handlePurgeSelectedDlq() {
    if (selectedDlqDeliveryIds.length === 0) return;
    const confirm = window.confirm(
      `Purge ${selectedDlqDeliveryIds.length} selected failed deliveries?`
    );
    if (!confirm) return;

    setPurgingSelectedDlq(true);
    try {
      const res = await purgeCaseWebhookDlqSelected(selectedDlqDeliveryIds);
      const skipped = res.skipped_non_failed_ids?.length ?? 0;
      const notFound = res.not_found_ids?.length ?? 0;
      const parts = [
        `Purged ${res.deleted}`,
        skipped > 0 ? `skipped ${skipped}` : null,
        notFound > 0 ? `not found ${notFound}` : null,
      ].filter(Boolean);
      toast(parts.join(" | "), "success");
      setSelectedDlqDeliveryIds([]);
      await loadWebhooks();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to purge selected deliveries", "error");
    } finally {
      setPurgingSelectedDlq(false);
    }
  }

  function idempotencyKeyForDelivery(d: CaseWebhookDelivery): string {
    if (d.case_event_id != null) {
      return `case_event:${d.case_event_id}:sub:${d.subscription_id}`;
    }
    return `delivery:${d.delivery_id}`;
  }

  async function handleCopyIdempotencyKey(d: CaseWebhookDelivery) {
    const key = idempotencyKeyForDelivery(d);
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(key);
        toast("Idempotency key copied", "success");
      } else {
        toast(key, "success");
      }
    } catch {
      toast("Failed to copy key", "error");
    }
  }

  function toggleDlqSelection(deliveryId: string) {
    setSelectedDlqDeliveryIds((prev) => (
      prev.includes(deliveryId)
        ? prev.filter((id) => id !== deliveryId)
        : [...prev, deliveryId]
    ));
  }

  function selectAllVisibleDlq() {
    setSelectedDlqDeliveryIds(webhookDlq.map((row) => row.delivery_id));
  }

  function clearDlqSelection() {
    setSelectedDlqDeliveryIds([]);
  }

  function resetDlqPaging() {
    setDlqPage(1);
    setSelectedDlqDeliveryIds([]);
  }

  async function handleCreateCase() {
    if (!newCaseTitle.trim()) return toast("Case title is required", "warning");
    try {
      await createCase({
        title: newCaseTitle.trim(),
        project_id: newCaseProject || null,
        case_type: newCaseType || null,
        external_ref: newCaseExt || null,
        priority: newCasePriority,
        owner: newCaseOwner || null,
        tags: newCaseTags.split(",").map((v) => v.trim()).filter(Boolean),
        metadata: parseMetadata(newCaseMeta),
      });
      setNewCaseTitle("");
      setNewCaseType("");
      setNewCaseExt("");
      setNewCaseOwner("");
      setNewCaseTags("");
      setNewCaseMeta("");
      setCreateCaseOpen(false);
      toast("Case created", "success");
      await loadCases();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to create case", "error");
    }
  }

  async function patchCase(caseId: string, patch: Record<string, unknown>) {
    try {
      await updateCase(caseId, patch);
      await loadCases();
      if (selectedCaseId === caseId) {
        await loadSelectedCaseActivity(caseId);
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update case", "error");
    }
  }

  async function handleClaim(caseId: string) {
    if (!claimOwner.trim()) return toast("Set claim owner first", "warning");
    try {
      await claimCase(caseId, claimOwner.trim(), true);
      await Promise.all([loadCases(), tab === "queue" ? loadQueue() : Promise.resolve()]);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to claim case", "error");
    }
  }

  async function handleRelease(caseId: string, owner?: string | null) {
    try {
      await releaseCase(caseId, owner ?? undefined, true);
      await Promise.all([loadCases(), tab === "queue" ? loadQueue() : Promise.resolve()]);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to release case", "error");
    }
  }

  function validateVarField(key: string, raw: string, meta: Record<string, any>): string {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const vtype = (meta?.type ?? "string") as string;
    if (meta?.required && !raw.trim()) return "This field is required";
    if (!raw) return "";
    if (validation.regex) {
      try {
        if (!new RegExp(`^(?:${validation.regex as string})$`).test(raw)) {
          return `Must match pattern: ${validation.regex as string}`;
        }
      } catch {
        // ignore malformed schema regex
      }
    }
    if (vtype === "number") {
      const num = Number(raw);
      if (validation.min !== undefined && num < (validation.min as number)) return `Minimum value is ${validation.min as number}`;
      if (validation.max !== undefined && num > (validation.max as number)) return `Maximum value is ${validation.max as number}`;
    }
    const allowed = validation.allowed_values as string[] | undefined;
    if (allowed && !allowed.includes(raw)) return `Must be one of: ${allowed.join(", ")}`;
    return "";
  }

  function handleRunVarChange(key: string, raw: string, meta: Record<string, any>) {
    setRunVarsForm((prev) => ({ ...prev, [key]: raw }));
    const err = validateVarField(key, raw, meta);
    setRunVarsErrors((prev) => {
      const next = { ...prev };
      if (err) next[key] = err;
      else delete next[key];
      return next;
    });
  }

  async function openStartRunForCase(caseItem: Case) {
    if (!runProcedureRef) {
      toast("Select a procedure first", "warning");
      return;
    }
    const [procedureId, version] = runProcedureRef.split("::");
    if (!procedureId || !version) {
      toast("Invalid procedure selection", "error");
      return;
    }
    try {
      const detail = await getProcedure(procedureId, version);
      const schema = flattenVariablesSchema(((detail.ckp_json as any)?.variables_schema ?? {}) as Record<string, unknown>);
      const defaults: Record<string, string> = {};
      for (const [key, meta] of Object.entries(schema)) {
        defaults[key] = (meta as any)?.default !== undefined ? String((meta as any).default) : "";
      }
      setRunVarsForm(defaults);
      setRunVarsErrors({});
      setRunModalCase(caseItem);
      setRunModalProcedure(detail);
      setRunModalOpen(true);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to prepare run", "error");
    }
  }

  async function submitStartRunForCase() {
    if (!runModalCase || !runModalProcedure) return;
    const allErrors: Record<string, string> = {};
    runModalSchemaEntries.forEach(([k, meta]) => {
      const e = validateVarField(k, runVarsForm[k] ?? "", meta);
      if (e) allErrors[k] = e;
    });
    if (Object.keys(allErrors).length > 0) {
      setRunVarsErrors(allErrors);
      return;
    }

    const parsed: Record<string, unknown> = {};
    let parseError = false;
    runModalSchemaEntries.forEach(([k, meta]) => {
      const raw = runVarsForm[k];
      if (meta?.type === "array" || meta?.type === "object") {
        if (!raw) return;
        try {
          parsed[k] = JSON.parse(raw);
        } catch {
          toast(`Invalid JSON for "${k}"`, "error");
          parseError = true;
        }
      } else {
        parsed[k] = meta?.type === "number" ? Number(raw) : raw;
      }
    });
    if (parseError) return;

    setCreatingRunForCaseId(runModalCase.case_id);
    try {
      const run = await createRun(
        runModalProcedure.procedure_id,
        runModalProcedure.version,
        parsed,
        {
          case_id: runModalCase.case_id,
          project_id: runModalCase.project_id ?? undefined,
        }
      );
      toast(`Run started for case: ${run.run_id.slice(0, 8)}...`, "success");
      setRunModalOpen(false);
      await loadSelectedCaseActivity(runModalCase.case_id);
    } catch (err) {
      if (isNotFoundError(err)) {
        toast("Case not found. It may have been deleted. Please refresh the page.", "error");
        void loadCases();
      } else {
        toast(err instanceof Error ? err.message : "Failed to start run for case", "error");
      }
    } finally {
      setCreatingRunForCaseId(null);
    }
  }

  function runFieldRow(key: string, meta: Record<string, any>, showDefault = false) {
    const validation = (meta?.validation ?? {}) as Record<string, any>;
    const allowed = validation.allowed_values as string[] | undefined;
    const isRequired = !!meta?.required;
    const hasDefault = meta?.default !== undefined;
    const sensitive = isFieldSensitive(meta as Record<string, unknown>);
    const currentVal = runVarsForm[key] ?? "";
    const isUsingDefault = hasDefault && currentVal === String(meta.default);
    const fieldErr = runVarsErrors[key];
    const borderCls = fieldErr
      ? "border-red-400 focus:border-red-500"
      : showDefault && isUsingDefault
        ? "border-neutral-200 bg-neutral-50 focus:border-sky-500 focus:bg-white"
        : "border-neutral-300 focus:border-sky-500";

    return (
      <div key={key}>
        <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
          <label className="text-xs font-semibold text-neutral-700">
            {key}{isRequired && <span className="ml-0.5 text-red-500">*</span>}
          </label>
          {meta?.type && <span className="text-[10px] uppercase tracking-wide text-neutral-400">{meta.type as string}</span>}
          {sensitive && <span className="text-[10px] font-medium text-yellow-600">sensitive</span>}
          {showDefault && hasDefault && !sensitive && (
            <span className="ml-auto text-[10px] text-neutral-400">
              default: <code className="font-mono">{String(meta.default)}</code>
              {!isUsingDefault && (
                <button
                  type="button"
                  onClick={() => handleRunVarChange(key, String(meta.default), meta)}
                  className="ml-1 text-sky-700 hover:underline"
                >
                  restore
                </button>
              )}
            </span>
          )}
        </div>
        {meta?.description && <p className="mb-1.5 text-xs text-neutral-400">{meta.description as string}</p>}
        {allowed ? (
          <select
            aria-label={key}
            value={currentVal}
            onChange={(e) => handleRunVarChange(key, e.target.value, meta)}
            className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
          >
            <option value="">- select -</option>
            {allowed.map((v: string) => <option key={v} value={v}>{v}</option>)}
          </select>
        ) : meta?.type === "array" || meta?.type === "object" ? (
          <textarea
            value={currentVal}
            onChange={(e) => handleRunVarChange(key, e.target.value, meta)}
            placeholder={meta?.type === "array" ? '["item1","item2"]' : '{"key":"value"}'}
            rows={3}
            className={`w-full rounded-lg border p-2 font-mono text-sm focus:outline-none ${borderCls}`}
          />
        ) : (
          <input
            type={sensitive ? "password" : meta?.type === "number" ? "number" : "text"}
            value={currentVal}
            onChange={(e) => handleRunVarChange(key, e.target.value, meta)}
            placeholder={hasDefault && !sensitive ? String(meta.default) : ""}
            autoComplete="off"
            className={`w-full rounded-lg border p-2 text-sm focus:outline-none ${borderCls}`}
          />
        )}
        {fieldErr ? (
          <p className="mt-1 text-xs text-red-500">{fieldErr}</p>
        ) : (
          <span className="mt-1 inline-flex gap-3">
            {validation.regex && <span className="text-xs text-neutral-400">Pattern: <code className="font-mono">{validation.regex as string}</code></span>}
            {validation.min !== undefined && <span className="text-xs text-neutral-400">Min: {validation.min as number}</span>}
            {validation.max !== undefined && <span className="text-xs text-neutral-400">Max: {validation.max as number}</span>}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-4 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Operations Workspace</p>
            <h1 className="mt-1 text-3xl font-bold text-neutral-900 dark:text-neutral-100">Cases</h1>
            <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">Case lifecycle, queue operations, SLA policy, and webhooks</p>
          </div>
          <input
            value={claimOwner}
            onChange={(e) => setClaimOwner(e.target.value)}
            placeholder="Claim owner"
            className="rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2 text-sm text-neutral-900 outline-none focus:border-blue-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-100"
          />
        </div>
      </section>

      <div className="flex flex-wrap gap-2">
        {(TAB_KEYS).map((key) => (
          <button
            key={key}
            onClick={() => {
              setTab(key);
              syncTabToUrl(key);
            }}
            className={`rounded-xl px-3 py-2 text-sm font-medium transition-colors ${tab === key ? "bg-blue-600 text-white" : "border border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"}`}
          >
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>

      {tab === "cases" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 rounded-2xl border border-neutral-200 bg-white p-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <select aria-label="Filter cases by project" value={caseProjectFilter} onChange={(e) => setCaseProjectFilter(e.target.value)} className="rounded-lg border border-neutral-200 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900">
              <option value="">All projects</option>
              {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
            </select>
            <select aria-label="Filter cases by status" value={caseStatusFilter} onChange={(e) => setCaseStatusFilter(e.target.value)} className="rounded-lg border border-neutral-200 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900">
              <option value="all">All status</option>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button onClick={() => setCreateCaseOpen((v) => !v)} className="ml-auto rounded-lg bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700">{createCaseOpen ? "Hide" : "New Case"}</button>
          </div>

          {createCaseOpen && (
            <div className="grid gap-2 rounded-2xl border bg-white dark:bg-neutral-900 p-3 sm:grid-cols-2 lg:grid-cols-4">
              <input value={newCaseTitle} onChange={(e) => setNewCaseTitle(e.target.value)} placeholder="Title *" className="rounded border px-2 py-1 text-sm" />
              <select aria-label="New case project" value={newCaseProject} onChange={(e) => setNewCaseProject(e.target.value)} className="rounded border px-2 py-1 text-sm">
                <option value="">No project</option>
                {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
              </select>
              <input value={newCaseType} onChange={(e) => setNewCaseType(e.target.value)} placeholder="Case type" className="rounded border px-2 py-1 text-sm" />
              <input value={newCaseExt} onChange={(e) => setNewCaseExt(e.target.value)} placeholder="External ref" className="rounded border px-2 py-1 text-sm" />
              <select aria-label="New case priority" value={newCasePriority} onChange={(e) => setNewCasePriority(e.target.value)} className="rounded border px-2 py-1 text-sm">
                {PRIORITY_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <input value={newCaseOwner} onChange={(e) => setNewCaseOwner(e.target.value)} placeholder="Owner" className="rounded border px-2 py-1 text-sm" />
              <input value={newCaseTags} onChange={(e) => setNewCaseTags(e.target.value)} placeholder="tags,comma,separated" className="rounded border px-2 py-1 text-sm" />
              <input value={newCaseMeta} onChange={(e) => setNewCaseMeta(e.target.value)} placeholder='{"source":"email"}' className="rounded border px-2 py-1 text-sm" />
              <button onClick={() => void handleCreateCase()} className="rounded bg-blue-600 px-3 py-1 text-sm text-white">Create</button>
            </div>
          )}

          <div className="grid gap-3 lg:grid-cols-[2fr_1fr]">
            <div className="overflow-auto rounded-2xl border border-neutral-200 bg-white shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
              {loading ? <p className="p-4 text-sm text-neutral-500">Loading...</p> : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 bg-neutral-50 text-left text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:border-neutral-800 dark:bg-neutral-900/50 dark:text-neutral-400">
                      <th className="p-2">Case</th>
                      <th>Status</th>
                      <th>Priority</th>
                      <th>Owner</th>
                      <th>SLA</th>
                      <th className="pr-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cases.map((c) => (
                      <tr key={c.case_id} className={`border-b ${selectedCaseId === c.case_id ? "bg-blue-50/40 dark:bg-blue-950/20" : ""}`}>
                        <td className="p-2">
                          <div className="text-left">
                            <button onClick={() => setSelectedCaseId(c.case_id)} className="block text-left">
                              <p className="font-medium">{c.title}</p>
                            </button>
                            <Link
                              href={`/cases/${encodeURIComponent(c.case_id)}`}
                              className="font-mono text-xs text-blue-600 hover:underline"
                            >
                              {c.case_id}
                            </Link>
                          </div>
                        </td>
                        <td><select aria-label={`Case ${c.case_id} status`} value={c.status} onChange={(e) => void patchCase(c.case_id, { status: e.target.value })} className="rounded border px-1 py-0.5 text-xs">{STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}</select></td>
                        <td><select aria-label={`Case ${c.case_id} priority`} value={c.priority} onChange={(e) => void patchCase(c.case_id, { priority: e.target.value })} className="rounded border px-1 py-0.5 text-xs">{PRIORITY_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}</select></td>
                        <td className="text-xs">{c.owner || "-"}</td>
                        <td className="text-xs">{fmtDate(c.sla_due_at)}</td>
                        <td className="pr-2 text-right">
                          {c.owner
                            ? <button onClick={() => void handleRelease(c.case_id, c.owner)} className="rounded border px-2 py-1 text-xs">Release</button>
                            : <button onClick={() => void handleClaim(c.case_id)} className="rounded border px-2 py-1 text-xs">Claim</button>}
                          <button onClick={() => setDeleteCaseTarget(c)} className="ml-1 rounded border border-red-300 px-2 py-1 text-xs text-red-600">Delete</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3 space-y-3">
              <h3 className="text-sm font-semibold">Case Timeline</h3>
              {!selectedCase ? <p className="text-sm text-neutral-500">Select a case</p> : (
                <>
                  <div className="text-xs space-y-1">
                    <p><span className="text-neutral-500">Case:</span> <span className="font-mono">{selectedCase.case_id}</span></p>
                    <p><span className="text-neutral-500">Project:</span> {selectedCase.project_id || "-"}</p>
                    <p><span className="text-neutral-500">Updated:</span> {fmtDate(selectedCase.updated_at)}</p>
                  </div>
                  <div className="space-y-2 rounded border border-neutral-200 dark:border-neutral-800 p-2">
                    <p className="text-xs font-medium text-neutral-600 dark:text-neutral-300">Start Run For This Case</p>
                    <select
                      aria-label="Select procedure for case run"
                      value={runProcedureRef}
                      onChange={(e) => setRunProcedureRef(e.target.value)}
                      className="w-full rounded border px-2 py-1 text-xs"
                    >
                      {launchableProcedures.length === 0 ? (
                        <option value="">No procedures available</option>
                      ) : (
                        launchableProcedures.map((proc) => (
                          <option key={`${proc.procedure_id}:${proc.version}`} value={`${proc.procedure_id}::${proc.version}`}>
                            {proc.name} ({proc.procedure_id} v{proc.version})
                          </option>
                        ))
                      )}
                    </select>
                    <button
                      onClick={() => void openStartRunForCase(selectedCase)}
                      disabled={launchableProcedures.length === 0 || creatingRunForCaseId === selectedCase.case_id}
                      className="w-full rounded border border-blue-300 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-blue-900 dark:bg-blue-950/20 dark:text-blue-300"
                    >
                      {creatingRunForCaseId === selectedCase.case_id ? "Starting..." : "Start Run"}
                    </button>
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase text-neutral-500">Runs ({runs.length})</p>
                    <div className="max-h-28 space-y-1 overflow-auto">
                      {runs.map((r) => <Link key={r.run_id} href={`/runs/${r.run_id}`} className="block rounded border px-2 py-1 text-xs font-mono hover:bg-neutral-50 dark:hover:bg-neutral-800">{r.run_id}</Link>)}
                    </div>
                  </div>
                  <div>
                    <p className="mb-1 text-xs uppercase text-neutral-500">Events ({events.length})</p>
                    <div className="max-h-56 space-y-1 overflow-auto">
                      {events.map((e) => <div key={e.event_id} className="rounded border px-2 py-1 text-xs"><p className="font-medium">{e.event_type}</p><p className="text-neutral-500">{fmtDate(e.ts)}</p></div>)}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "queue" && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2 rounded-2xl border bg-white dark:bg-neutral-900 p-3">
            <select aria-label="Filter queue by project" value={queueProjectFilter} onChange={(e) => setQueueProjectFilter(e.target.value)} className="rounded border px-2 py-1 text-sm">
              <option value="">All projects</option>
              {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
            </select>
            <label className="text-sm"><input type="checkbox" checked={queueUnassigned} onChange={(e) => setQueueUnassigned(e.target.checked)} className="mr-1" />Unassigned</label>
            <label className="text-sm"><input type="checkbox" checked={queueTerminal} onChange={(e) => setQueueTerminal(e.target.checked)} className="mr-1" />Include terminal</label>
          </div>
          <div className="grid gap-3 lg:grid-cols-4">
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Active Cases</p>
              <p className="mt-1 text-2xl font-semibold">{queueAnalytics?.total_active_cases ?? 0}</p>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Breached</p>
              <p className="mt-1 text-2xl font-semibold text-red-600">{queueAnalytics?.breached_cases ?? 0}</p>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Risk Next 60m</p>
              <p className="mt-1 text-2xl font-semibold text-amber-600">{queueAnalytics?.breach_risk_next_window_cases ?? 0}</p>
              <p className="mt-1 text-xs text-neutral-500">
                {(queueAnalytics?.breach_risk_next_window_percent ?? 0).toFixed(1)}% of active
              </p>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Wait P50 / P95</p>
              <p className="mt-1 text-xl font-semibold">
                {Math.round(queueAnalytics?.wait_p50_seconds ?? 0)}s / {Math.round(queueAnalytics?.wait_p95_seconds ?? 0)}s
              </p>
              <p className="mt-1 text-xs text-neutral-500">
                Unassigned: {queueAnalytics?.unassigned_cases ?? 0} | Reassign 24h: {(queueAnalytics?.reassignment_rate_24h ?? 0).toFixed(1)}% | Abandon 24h: {(queueAnalytics?.abandonment_rate_24h ?? 0).toFixed(1)}%
              </p>
            </div>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Wait By Priority</p>
              <div className="mt-2 space-y-1 text-xs">
                {Object.entries(queueAnalytics?.wait_by_priority ?? {}).length === 0 ? (
                  <p className="text-neutral-500">No data</p>
                ) : (
                  Object.entries(queueAnalytics?.wait_by_priority ?? {})
                    .sort((a, b) => b[1].count - a[1].count)
                    .map(([key, bucket]) => (
                      <p key={key}>
                        <span className="font-medium">{key}</span>: n={bucket.count}, p50={Math.round(bucket.wait_p50_seconds)}s, p95={Math.round(bucket.wait_p95_seconds)}s
                      </p>
                    ))
                )}
              </div>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Wait By Case Type</p>
              <div className="mt-2 space-y-1 text-xs">
                {Object.entries(queueAnalytics?.wait_by_case_type ?? {}).length === 0 ? (
                  <p className="text-neutral-500">No data</p>
                ) : (
                  Object.entries(queueAnalytics?.wait_by_case_type ?? {})
                    .sort((a, b) => b[1].count - a[1].count)
                    .slice(0, 6)
                    .map(([key, bucket]) => (
                      <p key={key}>
                        <span className="font-medium">{key}</span>: n={bucket.count}, p50={Math.round(bucket.wait_p50_seconds)}s, p95={Math.round(bucket.wait_p95_seconds)}s
                      </p>
                    ))
                )}
              </div>
            </div>
          </div>
          <div className="overflow-auto rounded-2xl border bg-white dark:bg-neutral-900">
            <table className="w-full text-sm">
              <thead><tr className="border-b text-left text-xs uppercase"><th className="p-2">Case</th><th>Priority</th><th>Owner</th><th>SLA</th><th className="pr-2 text-right">Actions</th></tr></thead>
              <tbody>
                {queueItems.map((c) => (
                  <tr key={c.case_id} className={`border-b ${c.is_sla_breached ? "bg-red-50/30 dark:bg-red-950/10" : ""}`}>
                    <td className="p-2"><p className="font-medium">{c.title}</p><p className="font-mono text-xs text-neutral-500">{c.case_id}</p></td>
                    <td><Pill value={c.priority} /></td>
                    <td className="text-xs">{c.owner || "-"}</td>
                    <td className="text-xs">{c.sla_remaining_seconds == null ? "-" : `${Math.round(c.sla_remaining_seconds)}s`}</td>
                    <td className="pr-2 text-right">
                      {c.owner
                        ? <button onClick={() => void handleRelease(c.case_id, c.owner)} className="rounded border px-2 py-1 text-xs">Release</button>
                        : <button onClick={() => void handleClaim(c.case_id)} className="rounded border px-2 py-1 text-xs">Claim</button>}
                      <Link href={`/cases/${encodeURIComponent(c.case_id)}`} className="ml-1 rounded border px-2 py-1 text-xs">Details</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "sla" && (
        <div className="space-y-2">
          <div className="grid gap-2 rounded-2xl border bg-white dark:bg-neutral-900 p-3 sm:grid-cols-2 lg:grid-cols-4">
            <input value={newPolicyName} onChange={(e) => setNewPolicyName(e.target.value)} placeholder="Name *" className="rounded border px-2 py-1 text-sm" />
            <select aria-label="New policy project" value={newPolicyProject} onChange={(e) => setNewPolicyProject(e.target.value)} className="rounded border px-2 py-1 text-sm"><option value="">Global</option>{projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select>
            <input value={newPolicyType} onChange={(e) => setNewPolicyType(e.target.value)} placeholder="Case type" className="rounded border px-2 py-1 text-sm" />
            <input value={newPolicyPriority} onChange={(e) => setNewPolicyPriority(e.target.value)} placeholder="Priority" className="rounded border px-2 py-1 text-sm" />
            <input value={newPolicyDueMins} onChange={(e) => setNewPolicyDueMins(e.target.value)} placeholder="Due minutes" className="rounded border px-2 py-1 text-sm" />
            <input value={newPolicyBreachStatus} onChange={(e) => setNewPolicyBreachStatus(e.target.value)} placeholder="Breach status" className="rounded border px-2 py-1 text-sm" />
            <button onClick={async () => {
              try {
                await createCaseSlaPolicy({ name: newPolicyName.trim(), project_id: newPolicyProject || null, case_type: newPolicyType || null, priority: newPolicyPriority || null, due_minutes: Number(newPolicyDueMins), breach_status: newPolicyBreachStatus, enabled: true });
                setNewPolicyName(""); await loadPolicies();
              } catch (err) { toast(err instanceof Error ? err.message : "Failed to create policy", "error"); }
            }} className="rounded bg-blue-600 px-3 py-1 text-sm text-white">Create Policy</button>
            <select aria-label="Filter SLA policies by project" value={slaProjectFilter} onChange={(e) => setSlaProjectFilter(e.target.value)} className="rounded border px-2 py-1 text-sm"><option value="">All projects</option>{projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select>
          </div>
          <div className="overflow-auto rounded-2xl border bg-white dark:bg-neutral-900">
            <table className="w-full text-sm">
              <thead><tr className="border-b text-left text-xs uppercase"><th className="p-2">Name</th><th>Scope</th><th>Due</th><th>Status</th><th className="pr-2 text-right">Actions</th></tr></thead>
              <tbody>
                {policies.map((p) => (
                  <tr key={p.policy_id} className="border-b">
                    <td className="p-2"><p className="font-medium">{p.name}</p><p className="font-mono text-xs text-neutral-500">{p.policy_id}</p></td>
                    <td className="text-xs">{p.project_id || "global"} / {p.case_type || "*"} / {p.priority || "*"}</td>
                    <td>{p.due_minutes}m</td>
                    <td>{p.enabled ? "enabled" : "disabled"}</td>
                    <td className="pr-2 text-right">
                      <button onClick={async () => { try { await updateCaseSlaPolicy(p.policy_id, { enabled: !p.enabled }); await loadPolicies(); } catch (err) { toast(err instanceof Error ? err.message : "Failed to update policy", "error"); } }} className="rounded border px-2 py-1 text-xs">Toggle</button>
                      <button onClick={() => setDeletePolicyTarget(p)} className="ml-1 rounded border border-red-300 px-2 py-1 text-xs text-red-600">Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "webhooks" && (
        <div className="space-y-2">
          <div className="grid gap-2 rounded-2xl border bg-white dark:bg-neutral-900 p-3 sm:grid-cols-2 lg:grid-cols-4">
            <select
              aria-label="Webhook event type"
              value={newWebhookEvent}
              onChange={(e) => setNewWebhookEvent(e.target.value)}
              className="rounded border px-2 py-1 text-sm"
            >
              {WEBHOOK_EVENT_OPTIONS.map((eventType) => (
                <option key={eventType} value={eventType}>{eventType}</option>
              ))}
            </select>
            <input value={newWebhookUrl} onChange={(e) => setNewWebhookUrl(e.target.value)} placeholder="Target URL *" className="rounded border px-2 py-1 text-sm sm:col-span-2" />
            <select aria-label="New webhook project" value={newWebhookProject} onChange={(e) => setNewWebhookProject(e.target.value)} className="rounded border px-2 py-1 text-sm"><option value="">Global</option>{projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select>
            <input value={newWebhookSecret} onChange={(e) => setNewWebhookSecret(e.target.value)} placeholder="Secret env var" className="rounded border px-2 py-1 text-sm" />
            <button onClick={async () => {
              const targetUrl = newWebhookUrl.trim();
              const eventType = (newWebhookEvent || "*").trim();
              if (!targetUrl) {
                toast("Webhook target URL is required", "warning");
                return;
              }
              try {
                // Validate URL client-side to avoid avoidable 422 roundtrips.
                new URL(targetUrl);
              } catch {
                toast("Webhook target URL must be a valid absolute URL", "warning");
                return;
              }
              try {
                await createCaseWebhook({
                  event_type: eventType,
                  target_url: targetUrl,
                  project_id: newWebhookProject || null,
                  secret_env_var: newWebhookSecret || null,
                  enabled: true,
                });
                setNewWebhookUrl(""); setNewWebhookSecret(""); await loadWebhooks();
              } catch (err) { toast(err instanceof Error ? err.message : "Failed to create webhook", "error"); }
            }} className="rounded bg-blue-600 px-3 py-1 text-sm text-white">Create Webhook</button>
            <select aria-label="Filter webhooks by project" value={webhookProjectFilter} onChange={(e) => setWebhookProjectFilter(e.target.value)} className="rounded border px-2 py-1 text-sm"><option value="">All projects</option>{projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}</select>
          </div>
          <div className="overflow-auto rounded-2xl border bg-white dark:bg-neutral-900">
            <table className="w-full text-sm">
              <thead><tr className="border-b text-left text-xs uppercase"><th className="p-2">Event</th><th>Target</th><th>Project</th><th>Status</th><th className="pr-2 text-right">Actions</th></tr></thead>
              <tbody>
                {webhooks.map((w) => (
                  <tr key={w.subscription_id} className="border-b">
                    <td className="p-2"><p className="font-medium">{w.event_type}</p><p className="font-mono text-xs text-neutral-500">{w.subscription_id}</p></td>
                    <td><a href={w.target_url} className="text-blue-600 hover:underline" target="_blank" rel="noreferrer">{w.target_url}</a></td>
                    <td className="text-xs">{w.project_id || "global"}</td>
                    <td>{w.enabled ? "enabled" : "disabled"}</td>
                    <td className="pr-2 text-right"><button onClick={() => setDeleteWebhookTarget(w)} className="rounded border border-red-300 px-2 py-1 text-xs text-red-600">Delete</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-3 lg:grid-cols-4">
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Deliveries Total</p>
              <p className="mt-1 text-2xl font-semibold">{webhookSummary?.total ?? 0}</p>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Failed (Last Hour)</p>
              <p className="mt-1 text-2xl font-semibold text-red-600">{webhookSummary?.recent_failures_last_hour ?? 0}</p>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Retrying</p>
              <p className="mt-1 text-2xl font-semibold text-amber-600">{webhookSummary?.by_status?.retrying ?? 0}</p>
            </div>
            <div className="rounded-2xl border bg-white dark:bg-neutral-900 p-3">
              <p className="text-xs uppercase text-neutral-500">Oldest Pending Age</p>
              <p className="mt-1 text-2xl font-semibold">{webhookSummary?.oldest_pending_age_seconds == null ? "-" : `${Math.round(webhookSummary.oldest_pending_age_seconds)}s`}</p>
            </div>
          </div>

          <div className="rounded-2xl border bg-white dark:bg-neutral-900">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b p-3">
              <div>
                <h3 className="text-sm font-semibold">Webhook DLQ</h3>
                <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
                  Failed deliveries only. Keep replay controls in the main toolbar and use cleanup tools only when pruning old rows.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-neutral-500 dark:text-neutral-400">
                <span className="rounded-full border px-2 py-1">Visible {dlqVisibleCount}</span>
                <span className="rounded-full border px-2 py-1">Selected {dlqSelectionCount}</span>
                <span className="rounded-full border px-2 py-1">Total failed {dlqTotalFailed}</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-b p-3">
              <button
                onClick={() => selectAllVisibleDlq()}
                disabled={webhookDlq.length === 0}
                className="rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-60"
              >
                Select All
              </button>
              <button
                onClick={() => clearDlqSelection()}
                disabled={dlqSelectionCount === 0}
                className="rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-60"
              >
                Clear
              </button>
              <button
                onClick={() => void handleReplaySelectedDlq()}
                disabled={replayingSelectedDlq || dlqSelectionCount === 0}
                className="rounded border border-blue-300 px-2 py-1 text-xs text-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {replayingSelectedDlq ? "Replaying Selected..." : `Replay Selected (${dlqSelectionCount})`}
              </button>
              <button
                onClick={() => void handlePurgeSelectedDlq()}
                disabled={purgingSelectedDlq || dlqSelectionCount === 0}
                className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {purgingSelectedDlq ? "Purging Selected..." : `Purge Selected (${dlqSelectionCount})`}
              </button>
              <div className="h-5 w-px bg-neutral-200 dark:bg-neutral-800" />
              <button
                onClick={() => void handleReplayAllDlq()}
                disabled={replayingAllDlq || webhookDlq.length === 0}
                className="rounded border border-blue-300 px-2 py-1 text-xs text-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {replayingAllDlq ? "Replaying..." : "Replay All Visible"}
              </button>
              <button
                onClick={() => void handlePurgeDlq()}
                disabled={purgingDlq || webhookDlqTotal === 0}
                className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {purgingDlq ? "Purging..." : "Purge Filtered Set"}
              </button>
            </div>
            <div className="grid gap-2 border-b p-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_auto]">
              <select
                aria-label="Filter DLQ by subscription"
                value={dlqSubscriptionFilter}
                onChange={(e) => {
                  setDlqSubscriptionFilter(e.target.value);
                  resetDlqPaging();
                }}
                className="rounded border px-2 py-1 text-sm"
              >
                <option value="">All subscriptions</option>
                {webhooks.map((w) => (
                  <option key={w.subscription_id} value={w.subscription_id}>
                    {w.subscription_id}
                  </option>
                ))}
              </select>
              <input
                value={dlqEventFilter}
                onChange={(e) => {
                  setDlqEventFilter(e.target.value);
                  resetDlqPaging();
                }}
                placeholder="Filter event_type"
                className="rounded border px-2 py-1 text-sm"
              />
              <input
                value={dlqCaseFilter}
                onChange={(e) => {
                  setDlqCaseFilter(e.target.value);
                  resetDlqPaging();
                }}
                placeholder="Filter case_id"
                className="rounded border px-2 py-1 text-sm"
              />
              <button
                onClick={() => {
                  setDlqSubscriptionFilter("");
                  setDlqEventFilter("");
                  setDlqCaseFilter("");
                  setDlqPage(1);
                  setSelectedDlqDeliveryIds([]);
                }}
                className="rounded border px-2 py-1 text-sm"
              >
                Clear Filters
              </button>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <label className="text-neutral-500">Sort</label>
                <select
                  aria-label="Sort DLQ rows by"
                  value={dlqSortBy}
                  onChange={(e) => setDlqSortBy(e.target.value as "updated_at" | "attempts")}
                  className="rounded border px-2 py-1"
                >
                  <option value="updated_at">Updated At</option>
                  <option value="attempts">Attempts</option>
                </select>
                <select
                  aria-label="Sort direction"
                  value={dlqSortDir}
                  onChange={(e) => setDlqSortDir(e.target.value as "asc" | "desc")}
                  className="rounded border px-2 py-1"
                >
                  <option value="desc">Desc</option>
                  <option value="asc">Asc</option>
                </select>
                <label className="text-neutral-500">Page Size</label>
                <select
                  aria-label="DLQ page size"
                  value={dlqPageSize}
                  onChange={(e) => {
                    setDlqPageSize(Number(e.target.value));
                    setDlqPage(1);
                  }}
                  className="rounded border px-2 py-1"
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                </select>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-neutral-500 dark:text-neutral-400">
                <span>{dlqHasFilters ? "Filtered view" : "All failed deliveries"}</span>
                <span>Page {dlqPage} of {dlqTotalPages}</span>
                <span>{dlqVisibleCount} visible</span>
                <button
                  onClick={() => setDlqPage((p) => Math.max(1, p - 1))}
                  disabled={dlqPage <= 1}
                  className="rounded border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Prev
                </button>
                <button
                  onClick={() => setDlqPage((p) => p + 1)}
                  disabled={dlqPage >= dlqTotalPages || dlqTotalFailed === 0}
                  className="rounded border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Next
                </button>
              </div>
            </div>
            <details className="border-b px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-neutral-600 dark:text-neutral-300">
                Cleanup Tools
              </summary>
              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-[auto_auto_1fr]">
                <div className="flex items-center gap-2 rounded border px-2 py-1 text-sm">
                  <span className="text-neutral-500">Purge Age</span>
                  <input
                    type="number"
                    aria-label="DLQ purge age in hours"
                    min={0}
                    max={24 * 365}
                    value={dlqPurgeOlderHours}
                    onChange={(e) => {
                      const next = Number.parseInt(e.target.value || "0", 10);
                      setDlqPurgeOlderHours(Number.isFinite(next) ? Math.max(0, next) : 0);
                    }}
                    className="w-20 rounded border px-2 py-1 text-sm"
                  />
                  <span className="text-neutral-500">hours</span>
                </div>
                <div className="flex items-center gap-2 rounded border px-2 py-1 text-sm">
                  <span className="text-neutral-500">Purge Limit</span>
                  <input
                    type="number"
                    aria-label="DLQ purge limit"
                    min={1}
                    max={5000}
                    value={dlqPurgeLimit}
                    onChange={(e) => {
                      const next = Number.parseInt(e.target.value || "1", 10);
                      setDlqPurgeLimit(Number.isFinite(next) ? Math.max(1, next) : 1);
                    }}
                    className="w-24 rounded border px-2 py-1 text-sm"
                  />
                  <span className="text-neutral-500">rows</span>
                </div>
                <p className="self-center text-xs text-neutral-500 dark:text-neutral-400">
                  Purge applies to the current DLQ filters and only removes rows older than the configured age.
                </p>
              </div>
            </details>
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs uppercase">
                    <th className="p-2">Select</th>
                    <th className="p-2">Delivery</th>
                    <th>Event</th>
                    <th>Case</th>
                    <th>Error</th>
                    <th>Attempts</th>
                    <th>Idempotency</th>
                    <th className="pr-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {webhookDlq.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="p-4 text-center text-xs text-neutral-500">No failed deliveries in DLQ.</td>
                    </tr>
                  ) : (
                    webhookDlq.map((d) => (
                      <tr key={d.delivery_id} className="border-b">
                        <td className="p-2">
                          <input
                            type="checkbox"
                            aria-label={`Select delivery ${d.delivery_id}`}
                            checked={selectedDlqDeliveryIds.includes(d.delivery_id)}
                            onChange={() => toggleDlqSelection(d.delivery_id)}
                          />
                        </td>
                        <td className="p-2">
                          <p className="font-mono text-xs">{d.delivery_id}</p>
                          <p className="text-[11px] text-neutral-500">{fmtDate(d.updated_at)}</p>
                        </td>
                        <td className="text-xs">{d.event_type}</td>
                        <td className="text-xs">{d.case_id || "-"}</td>
                        <td className="max-w-[320px] truncate text-xs text-red-600" title={d.last_error || ""}>{d.last_error || "-"}</td>
                        <td className="text-xs">{d.attempts}/{d.max_attempts}</td>
                        <td className="text-xs">
                          <button
                            onClick={() => void handleCopyIdempotencyKey(d)}
                            className="rounded border px-2 py-1 text-[11px]"
                          >
                            Copy Key
                          </button>
                        </td>
                        <td className="pr-2 text-right">
                          <button
                            onClick={() => void handleReplayDelivery(d.delivery_id)}
                            disabled={replayingDeliveryId === d.delivery_id}
                            className="rounded border border-blue-300 px-2 py-1 text-xs text-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {replayingDeliveryId === d.delivery_id ? "Replaying..." : "Replay"}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteCaseTarget !== null}
        title="Delete Case"
        message={deleteCaseTarget ? `Delete case ${deleteCaseTarget.case_id}?` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={async () => {
          if (!deleteCaseTarget) return;
          const id = deleteCaseTarget.case_id;
          setDeleteCaseTarget(null);
          try {
            await deleteCase(id);
            await loadCases();
          } catch (err) {
            toast(err instanceof Error ? err.message : "Failed to delete case", "error");
          }
        }}
        onCancel={() => setDeleteCaseTarget(null)}
      />
      <ConfirmDialog
        open={deletePolicyTarget !== null}
        title="Delete SLA Policy"
        message={deletePolicyTarget ? `Delete policy ${deletePolicyTarget.name}?` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={async () => {
          if (!deletePolicyTarget) return;
          const id = deletePolicyTarget.policy_id;
          setDeletePolicyTarget(null);
          try {
            await deleteCaseSlaPolicy(id);
            await loadPolicies();
          } catch (err) {
            toast(err instanceof Error ? err.message : "Failed to delete policy", "error");
          }
        }}
        onCancel={() => setDeletePolicyTarget(null)}
      />
      <ConfirmDialog
        open={deleteWebhookTarget !== null}
        title="Delete Webhook"
        message={deleteWebhookTarget ? `Delete webhook ${deleteWebhookTarget.subscription_id}?` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={async () => {
          if (!deleteWebhookTarget) return;
          const id = deleteWebhookTarget.subscription_id;
          setDeleteWebhookTarget(null);
          try {
            await deleteCaseWebhook(id);
            await loadWebhooks();
          } catch (err) {
            toast(err instanceof Error ? err.message : "Failed to delete webhook", "error");
          }
        }}
        onCancel={() => setDeleteWebhookTarget(null)}
      />

      {runModalOpen && runModalProcedure && runModalCase && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-0.5 text-base font-semibold text-neutral-900">
              {runModalMustFillEntries.length > 0
                ? `${runModalMustFillEntries.length} required field${runModalMustFillEntries.length !== 1 ? "s" : ""} need input`
                : "Review Run Variables"}
            </h3>
            <p className="mb-1 text-xs font-medium text-neutral-500">{runModalProcedure.name}</p>
            <p className="mb-4 text-xs text-neutral-400">
              {runModalMustFillEntries.length > 0
                ? "Fill in the required fields before starting."
                : "All fields have default values. Override any before starting."}
            </p>
            <div className="mb-3 rounded border border-blue-100 bg-blue-50 p-2 text-xs text-blue-700">
              Starting for case: <span className="font-mono">{runModalCase.case_id}</span>
            </div>
            <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
              {runModalMustFillEntries.map(([key, meta]) => runFieldRow(key, meta, false))}
              {runModalOverrideEntries.length > 0 && (
                runModalMustFillEntries.length > 0 ? (
                  <details className="group">
                    <summary className="flex list-none cursor-pointer select-none items-center gap-1 py-2 text-xs font-medium text-neutral-500 hover:text-neutral-700">
                      <span className="inline-block transition-transform group-open:rotate-90">▶</span>
                      {`${runModalOverrideEntries.length} field${runModalOverrideEntries.length !== 1 ? "s" : ""} have defaults - expand to override`}
                    </summary>
                    <div className="mt-3 space-y-4">
                      {runModalOverrideEntries.map(([key, meta]) => runFieldRow(key, meta, true))}
                    </div>
                  </details>
                ) : (
                  <div className="space-y-4">
                    {runModalOverrideEntries.map(([key, meta]) => runFieldRow(key, meta, true))}
                  </div>
                )
              )}
            </div>
            <div className="mt-5 flex gap-2">
              <button
                onClick={() => void submitStartRunForCase()}
                disabled={creatingRunForCaseId === runModalCase.case_id || Object.keys(runVarsErrors).length > 0}
                className="flex-1 rounded-lg bg-green-600 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
              >
                {creatingRunForCaseId === runModalCase.case_id ? "Starting..." : "Start Run"}
              </button>
              <button
                onClick={() => setRunModalOpen(false)}
                className="flex-1 rounded-lg border border-neutral-300 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CasesPageFallback() {
  return (
    <div className="space-y-4 p-6">
      <div className="h-8 w-40 animate-pulse rounded-lg bg-neutral-200 dark:bg-neutral-800" />
      <div className="h-24 animate-pulse rounded-2xl bg-neutral-100 dark:bg-neutral-900" />
      <div className="h-64 animate-pulse rounded-2xl bg-neutral-100 dark:bg-neutral-900" />
    </div>
  );
}

export default function CasesPage() {
  return (
    <Suspense fallback={<CasesPageFallback />}>
      <CasesPageContent />
    </Suspense>
  );
}
