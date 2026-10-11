/** One hypothesis node as `build_site.py --summary` reports it. */
export type ResearchNode = {
  id: string
  title: string
  parent: string
  status: 'pending' | 'verifying' | 'expandable' | 'prunable'
  exp_status: 'todo' | 'running' | 'no_gain' | 'beats_parent' | 'beats_sota'
  novelty: 'pending' | 'pass' | 'fail'
  theory: 'pending' | 'pass' | 'fail'
  go: boolean | null
  eligibility_checked?: boolean
  verdict: string | null
  seeds: number | null
  vs_sota: number | null
  vs_parent: number | null
  concluded_at: string | null
  worker: ResearchWorker
}

/** A node's worker: identity, the agent session to continue, and the documents a new session resumes from. */
export type ResearchWorker = { id: string | null; agent_id: string | null; session_at: string | null; resume: string[] }

/** Something waiting on someone: an extension, an RLD decision, a task, a broken document. `kind` is a code
 *  (usage_alert, awaiting_reply, ...), `label` its display name. */
export type ResearchAttention = { kind: string; label: string; id: string | null; text: string }

/** The compact project view the pane, status line, prompt section and guards read. */
export type ResearchSummary = {
  meta: { data_version: number; generated_at: string; lightweight?: boolean; eligibility_checked?: boolean }
  db_path: string
  /** null until the RLD creates the project record (just after /research-tree init). */
  project: null | {
    id: string
    title: string
    status: string
    stage: string
    sota_experiment_id: string | null
    go_margin: number
    harness_ref: string | null
    repo_path: string | null
    max_parallel_workers: number | null
    alert_node_h: number | null
    config_doc_id: string | null
    worker: ResearchWorker
  }
  counts: {
    status: Record<string, number>
    exp_status: Record<string, number>
    go: number | null
    node_hours: number
    screen_seeds: number | null
  }
  nodes: ResearchNode[]
  attention: ResearchAttention[]
  /** Worker ids with a task in hand (assigned and not delivered, or sent back). */
  busy_workers: string[]
  guards: { frozen_docs: string[]; harness: string[] }
}

/** The research project of the session's directory, as .research-tree.json records it. */
export type ResearchProject = {
  project_id: string
  root: string
  db: string
  plan: string
  plan_instruction: { doc_id: string; path: string }
  phase: 'planning' | 'awaiting_confirmation' | 'confirmed'
  created_at: string
  confirmed_at: string | null
  /** The registered version of research-tree.yaml in effect; null until it is first applied. */
  config: { doc_id: string; path: string } | null
  /** Version 2: the metric_spec document registered from research-tree.yaml. */
  metric_spec?: { doc_id: string; path: string }
  reviewer_backend?: { checked_at: string; model: string | null; backend: string | null; ok: boolean; error: string | null }
  skills_check?: { checked_at: string; configured: string[]; missing: string[]; suggestions: Record<string, string[]>; searched: string[] }
}

/** One subagent's model choice in research-tree.yaml. */
export type ResearchModel = { model: string; effort: 'low' | 'medium' | 'high' | 'xhigh' | 'max' | number | null }

/** research-tree.yaml, completed from the template (tools/project_config.py). */
export type ResearchConfig = {
  /** Version 1 states the gate in `stage1`; version 2 in metric_specs and verification (01 §3). */
  version: 1 | 2
  platform: { dev: string; experiment: string; skills: string[] }
  budget: {
    per_run: { nodes: number; walltime: number | string }
    screen_node_h: number
    max_parallel_workers: number | null
    alert_node_h: number | null
    total_limit?: number | null
  }
  stage1?: { gate_seeds: number; go_margin: number; min_related_work: number }
  notify?: { url: string | null; timeout_s: number }
  discovery?: { mode: 'off' | 'precheck' | 'full' | 'incremental'; lenses: string[]; seed_lenses: string[] }
  workflow?: { mode: 'fast_screening' | 'strict' }
  models: { explorer?: ResearchModel; architect?: ResearchModel; analyst?: ResearchModel; ui: ResearchModel; worker: ResearchModel; lens_assistant?: ResearchModel; reviewer?: unknown }
}

/** `research_tree.py config`: the configuration in effect and the state of the file. */
export type ResearchConfigView = {
  file: string
  exists: boolean
  /** A config document id, "file" before the first apply, or "template" when there is no usable file. */
  source: string
  registered: { doc_id: string; path: string } | null
  /** The file differs from the registered version (changes not applied yet). */
  pending: boolean
  file_error: string | null
  effective: ResearchConfig
  /** The project record's fields the configuration sets. */
  db_fields: Record<string, number | number[] | boolean | null>
  /** Version 2: the metric_spec document init registered from the configuration. */
  metric_spec?: { doc_id: string; path: string } | null
  /** Version 2: the protocol fields the configuration fixes. */
  protocol_requirements?: Record<string, unknown> | null
}

/** One line of the UI window: the person, the UI agent, or the RLD (this main session). */
export type ResearchChatEntry = { role: 'user' | 'ui' | 'rld' | 'note'; text: string; at: string; id?: string }

declare module 'claude-code' {
  interface PluginState {
    'research-tree': {
      summary: ResearchSummary | null
      error: string | null
      refreshedAt: string | null
      chat: ResearchChatEntry[]
      /** The UI subagent run answering the person's last message, while it runs. */
      uiAgentId: string | null
      /** That run's outbox id, the person's message it answers (verbatim, with its window id) and which attempt
       *  at it this is (a run that left nothing is retried once). */
      uiRun: { run: string; message: string; messageId?: string; attempt: number } | null
      /** The project of the session's directory; null when there is none. */
      project: ResearchProject | null
      /** Subagent runs the mod started: agentId -> worker/architect node identity, explorer/main, analyst/main, or assistant/lens_<name>. */
      agents: Record<string, string>
      /** The project configuration in effect; null without a project environment. */
      config: ResearchConfigView | null
      /** The alert_node_h the person was last alerted at, so each threshold alerts once. */
      alertedAt: number | null
    }
  }
}
