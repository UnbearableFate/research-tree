/** One hypothesis node as `build_site.py --summary` reports it. */
export type ResearchNode = {
  id: string
  title: string
  parent: string
  status: 'pending' | 'verifying' | 'expandable' | 'prunable'
  exp_status: 'todo' | 'running' | 'no_gain' | 'beats_parent' | 'beats_sota'
  novelty: 'pending' | 'pass' | 'fail'
  theory: 'pending' | 'pass' | 'fail'
  go: boolean
  verdict: string | null
  seeds: number | null
  vs_sota: number | null
  vs_parent: number | null
  concluded_at: string | null
  worker: ResearchWorker
}

/** A node's worker: identity, the agent session to continue, and the documents a new session resumes from. */
export type ResearchWorker = { id: string | null; agent_id: string | null; session_at: string | null; resume: string[] }

/** Something waiting on someone: an extension, an RLD decision, a task, a broken document. */
export type ResearchAttention = { kind: string; id: string | null; text: string }

/** The compact project view the pane, status line, prompt section and guards read. */
export type ResearchSummary = {
  meta: { data_version: number; generated_at: string }
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
    go: number
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
}

/** One subagent's model choice in research-tree.yaml. */
export type ResearchModel = { model: string; effort: 'low' | 'medium' | 'high' | 'xhigh' | 'max' | number | null }

/** research-tree.yaml, completed from the template (tools/project_config.py). */
export type ResearchConfig = {
  version: 1
  platform: { dev: string; experiment: string; skills: string[] }
  budget: {
    per_run: { nodes: number; walltime: number | string }
    screen_node_h: number
    max_parallel_workers: number | null
    alert_node_h: number | null
  }
  stage1: { gate_seeds: number; go_margin: number; min_related_work: number }
  models: { ui: ResearchModel; worker: ResearchModel }
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
  db_fields: Record<string, number | null>
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
      /** Subagent runs the mod started as workers: agentId -> worker/<id>. */
      agents: Record<string, string>
      /** The project configuration in effect; null without a project environment. */
      config: ResearchConfigView | null
      /** The alert_node_h the person was last alerted at, so each threshold alerts once. */
      alertedAt: number | null
    }
  }
}
