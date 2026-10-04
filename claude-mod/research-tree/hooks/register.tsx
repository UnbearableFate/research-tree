import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { ResearchChatEntry, ResearchConfig, ResearchConfigView, ResearchNode, ResearchProject, ResearchSummary } from '../types'

const PLUGIN = 'research-tree'
const COMMAND = 'research-tree'
const PANE = 'research-progress'
const UI_PANE = 'research-ui'
const UI_AGENT = 'research-tree:ui'
const WORKER_AGENT = 'research-tree:worker'
const TOOL = 'mcp__research-tree__research_db'
const POST_TOOL = 'mcp__research-tree__post_to_ui'
const VENV_PYTHON = '.venv/bin/python'
const MARKER = '.research-tree.json'
const DEFAULT_PYTHON = '3.13'
const DEPENDENCIES = ['latticedb==0.15.0', 'jsonschema>=4.26', 'pyyaml>=6.0']
const CONFIG_FILE = 'research-tree.yaml'
const ALERT_KIND = 'usage_alert'
const READ_ONLY = /^(help|get|find|edges|children|history|go_candidates|latest_result|screen_seed_count|export_snapshot|verify_document|resume_package|cleanup_due)$/

const summaryRef = { plugin: 'research-tree', key: 'summary' } as const
const errorRef = { plugin: 'research-tree', key: 'error' } as const
const refreshedRef = { plugin: 'research-tree', key: 'refreshedAt' } as const
const chatRef = { plugin: 'research-tree', key: 'chat' } as const
const uiAgentRef = { plugin: 'research-tree', key: 'uiAgentId' } as const
const uiRunRef = { plugin: 'research-tree', key: 'uiRun' } as const
const projectRef = { plugin: 'research-tree', key: 'project' } as const
const agentsRef = { plugin: 'research-tree', key: 'agents' } as const
const configRef = { plugin: 'research-tree', key: 'config' } as const
const alertedRef = { plugin: 'research-tree', key: 'alertedAt' } as const
const summaryAtom = atom(summaryRef, null)
const errorAtom = atom(errorRef, null)
const refreshedAtom = atom(refreshedRef, null)
const chatAtom = atom(chatRef, [])
const uiAgentAtom = atom(uiAgentRef, null)
const projectAtom = atom(projectRef, null)
const agentsAtom = atom(agentsRef, {})

type Config = { actor: string }

/** Where the plugin keeps its Python tools, schema and rules: its own directory. */
const RULES = 'rules/research-tree-rules.md'

const LABEL: Record<string, string> = {
  pending: '待验证', verifying: '验证中', expandable: '可拓展', prunable: '可消灭',
  todo: '未开始', running: '进行中', no_gain: '无提升', beats_parent: '优于父节点', beats_sota: '优于SOTA',
  close: '差不多', needs_rld: '需要RLD复核', active: '进行中', go: 'GO', not_go: 'NOT GO', stopped: '已停止',
  planning: 'RLD规划中', awaiting_confirmation: '等待用户确认', confirmed: '已确认',
}
const STATUS_COLOR: Record<string, string> = { pending: 'gray', verifying: 'yellow', expandable: 'green', prunable: 'red' }
const L = (k: string | null | undefined) => (k ? (LABEL[k] ?? k) : '未知')
const signed = (x: number | null) => (x === null ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(3)}`)
const now = () => new Date().toISOString().slice(0, 19).replace('T', ' ')

function config(options: PluginOptions): Config {
  return {
    actor: String(options.actor || 'rld/main'),
  }
}

// ---------------------------------------------------------------------------
// The project of the session's directory, and running the Python tools with its own .venv
// ---------------------------------------------------------------------------

/** Reads .research-tree.json in the session's directory into state; null when there is no project here. */
async function loadProject($: EngineInterface): Promise<ResearchProject | null> {
  let project: ResearchProject | null = null
  try {
    const cwd = await $.session.cwd()
    if (await $.fs.exists(`${cwd}/${MARKER}`)) project = JSON.parse(await $.fs.read(`${cwd}/${MARKER}`)) as ResearchProject
  } catch {
    project = null
  }
  await $.state.set(projectRef, project)
  return project
}

/** The session directory's .venv interpreter, or why it cannot be used. */
async function venv($: EngineInterface): Promise<{ python: string } | { problem: string }> {
  let cwd = '当前目录'
  try {
    cwd = await $.session.cwd()
    if (await $.fs.exists(`${cwd}/${VENV_PYTHON}`)) return { python: `${cwd}/${VENV_PYTHON}` }
  } catch {
    // no file system here: treated as missing
  }
  return {
    problem: `${cwd} 下还没有 ${VENV_PYTHON}：先运行 /${COMMAND} init <计划.md>，它会用 uv 建立本目录的项目环境。`,
  }
}

/** Runs one of the research-tree Python tools with the session directory's .venv, in that directory. */
async function runTool($: EngineInterface, cfg: Config, script: string, args: string[], timeoutMs = 60_000) {
  const env = await venv($)
  if ('problem' in env) return { exitCode: 127, stdout: '', stderr: env.problem }
  return $.process.run([env.python, `${$.plugin.root}/tools/${script}`, ...args], { timeoutMs })
}

async function refresh($: EngineInterface, cfg: Config): Promise<ResearchSummary | null> {
  const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
  if (!project) {
    await $.state.set(errorRef, `当前目录没有研究项目：运行 /${COMMAND} init <计划.md>`)
    $.ui.status(undefined)
    return null
  }
  try {
    const out = await runTool($, cfg, 'build_site.py', ['--db', project.db, '--summary'], 30_000)
    if (out.exitCode !== 0) throw new Error(out.stderr.trim() || `exit ${out.exitCode}`)
    const summary = JSON.parse(out.stdout) as ResearchSummary
    await $.state.set(summaryRef, summary)
    await $.state.set(errorRef, null)
    await $.state.set(refreshedRef, now())
    $.ui.status(statusLine(summary, project))
    await alertUsage($, summary)
    return summary
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    await $.state.set(errorRef, `读取研究数据库失败：${message.slice(0, 300)}`)
    $.ui.status(`${COMMAND}: 读取失败`)
    return null
  }
}

/** Tells the person, once per threshold, that recorded usage reached alert_node_h (new experiments now wait). */
async function alertUsage($: EngineInterface, summary: ResearchSummary): Promise<void> {
  const alert = summary.attention.find(a => a.kind === ALERT_KIND)
  const threshold = summary.project?.alert_node_h ?? null
  const alerted = (await $.state.get(alertedRef)).value ?? null
  if (!alert) {
    if (alerted !== null) await $.state.set(alertedRef, null)
    return
  }
  if (alerted === threshold) return
  await $.state.set(alertedRef, threshold)
  await say($, 'note', `【需要你决定】${alert.text}`)
  $.ui.toast('研究用量达到提醒阈值，见“研究对话”窗口')
  void $.ui.open({ id: UI_PANE, title: '研究对话（UI）' })
}

/** Records the model an agent run asked for (requested, at its start) or ran on (observed, as the API reports
 *  it): rule 2's model records, in the project's logs/agent_models.jsonl. */
async function logAgentModel($: EngineInterface, cfg: Config, agent: string, actor: string,
  event: 'requested' | 'observed', model: string | undefined, effort?: string | number | null): Promise<void> {
  await tree($, cfg, ['agent-log', '--agent', agent, '--actor', actor, '--event', event, '--model', model ?? '',
    ...(effort != null ? ['--effort', String(effort)] : [])])
}

// Agent runs whose observed model is logged already, with that model: one record per run and model.
const observedModels = new Map<string, string>()

/** One of the research_tree.py subcommands; its JSON answer. */
async function tree($: EngineInterface, cfg: Config, args: string[]): Promise<{ ok: boolean; result?: any; error?: string }> {
  const out = await runTool($, cfg, 'research_tree.py', args)
  try {
    return JSON.parse(out.stdout)
  } catch {
    return { ok: false, error: (out.stderr || out.stdout).trim() || `exit ${out.exitCode}` }
  }
}

/** Reads the project configuration in effect into state; null without a project environment. */
async function readConfig($: EngineInterface, cfg: Config): Promise<ResearchConfigView | null> {
  const shown = 'python' in (await venv($)) ? await tree($, cfg, ['config']) : null
  const view = shown?.ok ? (shown.result as ResearchConfigView) : null
  await $.state.set(configRef, view)
  return view
}

/** The UI and worker agent types, with the models and the platform of the configuration in effect. */
async function registerAgents($: EngineInterface, conf: ResearchConfig | null | undefined): Promise<void> {
  const choice = (m: ResearchConfig['models']['ui'] | undefined) =>
    ({ model: m?.model ?? 'inherit', ...(m?.effort != null ? { effort: m.effort } : {}) })
  await $.agent.register({
    name: 'ui',
    description: 'research-tree 的 User Interface：在“研究对话”窗口与用户对话（只由 research-tree mod 启动）',
    prompt: UI_ROLE,
    tools: ['Read', 'Grep', 'Glob', 'Bash'],
    ...choice(conf?.models.ui),
  })
  await $.agent.register({
    name: 'worker',
    description: 'research-tree 的 worker：实现被委派的研究任务（根节点框架、节点代码与实验），通过 research_db 登记与交付',
    prompt: workerPrompt(conf),
    ...choice(conf?.models.worker),
    ...(conf?.platform.skills.length ? { skills: conf.platform.skills } : {}),
  })
}

/** /research-tree config show: the effective configuration and pending changes. */
function configText(view: ResearchConfigView): string {
  const m = view.effective.models
  const model = (x: typeof m.ui) => `${x.model}${x.effort != null ? ` / ${x.effort}` : ''}`
  const source = view.source === 'file' ? `${CONFIG_FILE}（确认立项时登记）`
    : view.source === 'template' ? '默认值（没有可用的配置文件）' : `${view.source}（docs/${view.registered?.path}）`
  const lines = [
    `生效中的项目配置：${source}`,
    budgetText(view),
    `模型：UI ${model(m.ui)}；worker ${model(m.worker)}`,
    platformText(view.effective),
  ]
  if (view.file_error) lines.push(`⚠ ${view.file} 有错误，修正前不能生效：${view.file_error}`)
  else if (view.pending) lines.push(`${view.file} 有尚未生效的改动：运行 /${COMMAND} config apply 生效。`)
  return lines.join('\n')
}

function statusLine(s: ResearchSummary, p: ResearchProject): string {
  return `${COMMAND} ${s.project?.id ?? p.project_id} · ${L(p.phase)} · v${s.meta.data_version} · 节点${s.nodes.length} · ` +
    `优于SOTA ${s.counts.exp_status.beats_sota ?? 0} · GO候选 ${s.counts.go} · 待处理 ${s.attention.length}`
}

function statusText(s: ResearchSummary, p?: ResearchProject | null): string {
  if (!s.project) return `${p?.project_id ?? '项目'}：${L(p?.phase)}；RLD 尚未建立项目记录。`
  const byStatus = Object.entries(s.counts.status).map(([k, v]) => `${L(k)} ${v}`).join('，')
  const go = s.nodes.filter(n => n.go).map(n => `${n.id} ${n.title}`)
  const lines = [
    `${s.project.title}（${s.project.id}，${L(s.project.status)}${p ? `，${L(p.phase)}` : ''}，data_version ${s.meta.data_version}）`,
    `节点：${byStatus || '无'}；GO候选：${go.length ? go.join('；') : '无'}`,
    `SOTA：${s.project.sota_experiment_id ?? '未设置'}；筛选seed数：${s.counts.screen_seeds ?? '未知'}；已用资源 ${s.counts.node_hours} node·h` +
      `${s.project.alert_node_h != null ? `（提醒阈值 ${s.project.alert_node_h}）` : ''}；有任务的worker ${s.busy_workers.length}` +
      `${s.project.max_parallel_workers != null ? `/${s.project.max_parallel_workers}` : ''}`,
  ]
  if (s.attention.length) lines.push('待处理：', ...s.attention.map(a => `- [${a.label}] ${a.text}`))
  return lines.join('\n')
}

type InitArgs = { plan: string; python: string; id?: string; config?: string; updateUv?: true }

/** `init <plan.md> [--python 3.13] [--id NAME] [--update-uv]`: the plan path, the uv Python request, the project
 *  id, and whether to run `uv self update` first. */
function parseInit(args: string[]): InitArgs | { usage: string } {
  const usage = `用法：/${COMMAND} init path/to/计划.md [--python ${DEFAULT_PYTHON}] [--id 项目ID] [--config 配置.yaml] [--update-uv]` +
    `（项目ID默认为 uv 项目名，即当前目录名；不给 --config 时从默认配置开始；--update-uv 先运行 uv self update）`
  let plan: string | undefined
  let python = DEFAULT_PYTHON
  let id: string | undefined
  let configFile: string | undefined
  let updateUv = false
  for (let i = 0; i < args.length; i++) {
    const [flag, inline] = args[i]!.split(/=(.*)/s, 2) as [string, string | undefined]
    if (args[i] === '--update-uv') {
      updateUv = true
    } else if (flag === '--python' || flag === '--id' || flag === '--config') {
      const value = inline ?? args[++i]
      if (!value || value.startsWith('-')) return { usage }
      if (flag === '--python') python = value
      else if (flag === '--config') configFile = value
      else id = value
    } else if (args[i]!.startsWith('-') || plan) {
      return { usage }
    } else {
      plan = args[i]
    }
  }
  return plan
    ? { plan, python, ...(id ? { id } : {}), ...(configFile ? { config: configFile } : {}), ...(updateUv ? { updateUv: true as const } : {}) }
    : { usage }
}

/** uv must exist; update it when asked, make this directory a uv project for the requested Python, add the
 *  tools' dependencies. Returns what was done, line by line. */
async function setUpEnvironment($: EngineInterface, python: string, updateUv: boolean): Promise<{ ok: boolean; log: string[] }> {
  const log: string[] = []
  const run = async (argv: string[], timeoutMs: number) => {
    try {
      return await $.process.run(argv, { timeoutMs })
    } catch (err) {
      return { exitCode: 127, stdout: '', stderr: err instanceof Error ? err.message : String(err) }
    }
  }
  const tail = (r: { stdout: string; stderr: string }) => (r.stderr || r.stdout).trim().split('\n').slice(-3).join(' ')
  const version = await run(['uv', '--version'], 20_000)
  if (version.exitCode !== 0) {
    log.push('需要 uv，但当前环境找不到它。安装：curl -LsSf https://astral.sh/uv/install.sh | sh，然后重开会话。')
    return { ok: false, log }
  }
  log.push(`uv：${version.stdout.trim()}`)
  if (updateUv) {
    const updated = await run(['uv', 'self', 'update'], 120_000)
    log.push(updated.exitCode === 0 ? `uv self update：${tail(updated) || '完成'}` : `uv self update 未成功（继续）：${tail(updated)}`)
  }
  const cwd = await $.session.cwd()
  if (await $.fs.exists(`${cwd}/pyproject.toml`)) {
    log.push('已有 pyproject.toml：沿用现有 uv 项目，跳过 uv init。')
  } else {
    // Standalone even inside another uv project, so this directory gets its own .venv.
    const made = await run(['uv', 'init', '.', '--no-workspace', `--python=${python}`], 600_000)
    if (made.exitCode !== 0) {
      log.push(`uv init . --no-workspace --python=${python} 失败：${tail(made)}`)
      return { ok: false, log }
    }
    log.push(`uv init . --no-workspace --python=${python}：完成`)
  }
  const added = await run(['uv', 'add', '--project', '.', ...DEPENDENCIES], 600_000)
  if (added.exitCode !== 0) {
    log.push(`uv add ${DEPENDENCIES.join(' ')} 失败：${tail(added)}`)
    return { ok: false, log }
  }
  log.push(`uv add ${DEPENDENCIES.join(' ')}：完成`)
  return { ok: true, log }
}

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------

/** The project's code directory: the research root research/<id>/ lives in it, beside research-tree.yaml. */
function projectDir(project: ResearchProject): string {
  return project.root.replace(/\/research\/[^/]+$/, '')
}

const CONFIG_REASON = `${CONFIG_FILE} 由用户修改：请用户自己编辑它，再运行 /${COMMAND} config apply 生效；需要变更时向用户说明理由。`

/** Paths a write must not touch: current/superseded documents, the harness inside node worktrees, and the
 *  project configuration (`config`, its absolute path). */
function guardReason(s: ResearchSummary | null | undefined, path: string, config?: string): string | undefined {
  if (config && path === config) return CONFIG_REASON
  if (!s || !path) return undefined
  if (s.guards.frozen_docs.includes(path)) {
    return `${path} 是已生效的文档，不能原地修改：写 vN+1 新版本文件，用 research_db 的 register_document 登记，再用 supersede_document 取代旧版本。`
  }
  const harness = s.guards.harness.find(prefix => path === prefix || path.startsWith(`${prefix}/`))
  if (harness) {
    return `${path} 属于冻结的实验框架与统计代码（${harness}），节点代码中不能改动；更换框架须由RLD决定并重跑SOTA基线。`
  }
  return undefined
}

async function guard($: EngineInterface, path: string): Promise<{ deny: string } | undefined> {
  const project = (await $.state.get(projectRef)).value
  const reason = guardReason((await $.state.get(summaryRef)).value, path, project ? `${projectDir(project)}/${CONFIG_FILE}` : undefined)
  return reason ? { deny: `${PLUGIN}: ${reason}` } : undefined
}

// A project database lives at research/<project-id>/research_tree.db (its write-ahead log beside it).
const PROJECT_DB = /(^|[=/])research\/[^\s/]+\/research_tree\.db/
// Commands that write or remove the files named among their arguments.
const DB_WRITERS = new Set(['rm', 'mv', 'cp', 'dd', 'truncate', 'sqlite3', 'shred', 'tee'])
// Editors that write the files they name when given -i.
const IN_PLACE = new Set(['sed', 'perl'])
// Prefixes that run the next word as the command.
const WRAPPERS = new Set(['sudo', 'env', 'command', 'exec', 'nice', 'nohup', 'time', 'timeout', 'xargs'])

type ShellToken = { word: string } | { op: string }

/** The words and operators of a shell command, quotes removed. Heredoc bodies and comments are dropped: they
 *  are text, not commands (a commit message may well mention a database and `>`). */
function shellTokens(command: string): ShellToken[] {
  const tokens: ShellToken[] = []
  const heredocs: { delim: string; tabs: boolean }[] = []
  const n = command.length
  let word = ''
  let inWord = false
  let i = 0
  const flush = () => {
    if (inWord) tokens.push({ word })
    word = ''
    inWord = false
  }
  while (i < n) {
    const c = command[i]!
    if (c === "'") {
      const end = command.indexOf("'", i + 1)
      word += command.slice(i + 1, end < 0 ? n : end)
      inWord = true
      i = end < 0 ? n : end + 1
    } else if (c === '"') {
      inWord = true
      for (i++; i < n && command[i] !== '"'; i++) {
        if (command[i] === '\\' && i + 1 < n) i++
        word += command[i]
      }
      i++
    } else if (c === '\\' && i + 1 < n) {
      if (command[i + 1] !== '\n') {
        word += command[i + 1]
        inWord = true
      }
      i += 2
    } else if (c === '\n') {
      flush()
      tokens.push({ op: ';' })
      i++
      for (const h of heredocs.splice(0)) {
        while (i < n) {
          const eol = command.indexOf('\n', i)
          const end = eol < 0 ? n : eol
          const line = command.slice(i, end)
          i = end + 1
          if ((h.tabs ? line.replace(/^\t+/, '') : line) === h.delim) break
        }
      }
    } else if (c === ' ' || c === '\t') {
      flush()
      i++
    } else if (c === '#' && !inWord) {
      const eol = command.indexOf('\n', i)
      i = eol < 0 ? n : eol
    } else {
      const op = /^(<<<|<<-|<<|>>|>\||&>>|&>|&&|\|\||;;|[;&|()<>])/.exec(command.slice(i))?.[0]
      if (!op) {
        word += c
        inWord = true
        i++
        continue
      }
      flush()
      i += op.length
      if (op === '<<' || op === '<<-') {
        const m = /^[ \t]*(['"]?)([^\s'"<>;&|()]+)\1/.exec(command.slice(i))
        if (m) {
          heredocs.push({ delim: m[2]!, tabs: op === '<<-' })
          i += m[0].length
        }
        tokens.push({ op: '<<' })
      } else {
        tokens.push({ op: op === '>|' || op === '&>' ? '>' : op === '&>>' ? '>>' : op })
      }
    }
  }
  flush()
  return tokens
}

/** A shell command that writes a project database directly instead of going through the tools. The database is
 *  the current project's, or any research/<id>/research_tree.db; other files that happen to be named
 *  research_tree.db (a scratch or test database) are not protected. */
function writesDatabase(command: string, projectDb?: string | null): boolean {
  return writesTo(command, w => PROJECT_DB.test(w) || (!!projectDb && w.includes(projectDb)))
}

/** A shell command that writes the project configuration: research-tree.yaml named relatively, or by `config`,
 *  its absolute path. */
function writesConfig(command: string, config?: string): boolean {
  return writesTo(command, w => w.split('/').pop() === CONFIG_FILE && (!w.startsWith('/') || w === config))
}

/** A shell command that writes a file `isTarget` picks: a redirection into it, or a writing command (rm, cp,
 *  sqlite3, sed -i, ...) naming it. */
function writesTo(command: string, isTarget: (word: string) => boolean): boolean {
  const tokens = shellTokens(command)
  let start = true
  let wrapped = false
  let writer = false
  for (let k = 0; k < tokens.length; k++) {
    const t = tokens[k]!
    if ('op' in t) {
      if (t.op === '>' || t.op === '>>') {
        const target = tokens[k + 1]
        if (target && 'word' in target && isTarget(target.word)) return true
        k++
      } else if (t.op === '<' || t.op === '<<<') {
        k++
      } else if (t.op !== '<<') {
        start = true
        wrapped = false
        writer = false
      }
      continue
    }
    if (start) {
      if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(t.word) || (wrapped && /^(-|\d+[smhd]?$)/.test(t.word))) continue
      if (WRAPPERS.has(t.word)) {
        wrapped = true
        continue
      }
      const name = t.word.split('/').pop() ?? ''
      writer = DB_WRITERS.has(name) || (IN_PLACE.has(name) && inPlace(tokens, k + 1))
      start = false
      continue
    }
    if (writer && isTarget(t.word)) return true
  }
  return false
}

/** Whether the command starting before token `from` has an -i option (an in-place edit). */
function inPlace(tokens: ShellToken[], from: number): boolean {
  for (let k = from; k < tokens.length; k++) {
    const t = tokens[k]!
    if ('op' in t) {
      if (!['>', '>>', '<', '<<<', '<<'].includes(t.op)) return false
      continue
    }
    if (/^-i/.test(t.word)) return true
  }
  return false
}

type ToolCall = { script: 'research_db.py' | 'research_tree.py'; actor?: string; method?: string }

/** The research_db.py and research_tree.py calls in a shell command: the actor named, and the method (the
 *  subcommand for research_tree.py). */
function researchCalls(command: string): ToolCall[] {
  const tokens = shellTokens(command)
  const calls: ToolCall[] = []
  for (let k = 0; k < tokens.length; k++) {
    const t = tokens[k]!
    const script = 'word' in t ? t.word.split('/').pop() : undefined
    if (script !== 'research_db.py' && script !== 'research_tree.py') continue
    const call: ToolCall = { script }
    for (let j = k + 1; j < tokens.length; j++) {
      const a = tokens[j]!
      if ('op' in a) break
      const [flag, inline] = a.word.split(/=(.*)/s, 2) as [string, string | undefined]
      if (flag === '--actor' || flag === '--db' || flag === '--root') {
        const value = inline ?? (tokens[j + 1] && 'word' in tokens[j + 1]! ? (tokens[++j] as { word: string }).word : undefined)
        if (flag === '--actor') call.actor = value
      } else if (!a.word.startsWith('-') && call.method === undefined) {
        call.method = a.word
      }
    }
    calls.push(call)
  }
  return calls
}

/** Why a subagent's shell command may not run: a worker acts only as itself, and the RLD's other helpers only
 *  read; research_tree.py (the mod's and the UI's entry) is not theirs except to query. `worker` is the
 *  subagent's worker/<id>, if it is a node's worker. */
function subagentCallBlock(calls: ToolCall[], worker: string | undefined): string | undefined {
  for (const c of calls) {
    if (c.script === 'research_tree.py' && c.method !== 'query') {
      return `子代理不运行 research_tree.py ${c.method ?? ''}：它是 mod 与 UI 的入口；研究数据库用 ${TOOL} 工具读写。`
    }
    if (c.script !== 'research_db.py') continue
    if (worker && c.actor !== worker) {
      return `${worker} 只能以自己的身份调用 research_db（--actor ${worker}）；用 ${TOOL} 工具时 mod 自动固定身份。`
    }
    if (!worker && !READ_ONLY.test(c.method ?? '')) {
      return `RLD 委派的辅助子代理只读研究数据库（${c.method ?? '未知方法'} 会写入）；写入由 RLD 或节点的 worker 完成。`
    }
  }
  return undefined
}

/** The node (hypothesis id, or the project for the root) whose assigned worker identity is `workerId`. */
function workerNode(s: ResearchSummary | null | undefined, workerId: string): string | undefined {
  if (!s) return undefined
  if (s.project?.worker?.id === workerId) return s.project.id
  return s.nodes.find(n => n.worker?.id === workerId)?.id
}

/** worker/<id> for an agent session the database binds to a node (sessions bound in an earlier session too). */
function workerActor(s: ResearchSummary | null | undefined, agentId: string): string | undefined {
  if (!s) return undefined
  const found = s.project?.worker?.agent_id === agentId ? s.project.worker : s.nodes.find(n => n.worker?.agent_id === agentId)?.worker
  return found?.id ? `worker/${found.id}` : undefined
}

/** Why a worker may not start yet, or undefined once the user confirmed the plan. */
function workerBlock(project: ResearchProject | null | undefined): string | undefined {
  if (!project) return `当前目录没有研究项目；先运行 /${COMMAND} init <计划.md>。`
  if (project.phase !== 'confirmed') {
    return `立项计划尚未经用户确认（当前：${L(project.phase)}）。请用 post_to_ui(type=confirm_request) 请用户确认，确认后再启动 worker。`
  }
  return undefined
}

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

const UI_ROLE = `你是研究项目的 User Interface（UI）agent，运行在 Claude Code 的“研究对话”窗口里，直接与用户对话。Research Leader（RLD）是主会话，负责研究管理与执行；你不是RLD的worker。每条用户消息由 research-tree mod 启动你一次，任务说明里有本次的命令。`

/** The UI agent's task for one message: its role, what it may run, and the outbox commands of this run. The
 *  agent has no plugin tools (the engine does not route a plugin-spawned agent's calls to the plugin's hooks):
 *  it reads with the CLI and leaves its reply and actions in the run's outbox, which the mod carries out. */
function uiPrompt(pluginRoot: string, project: ResearchProject, run: string, python: string): string {
  const tool = (script: string) => `${python} ${pluginRoot}/tools/${script}`
  const outbox = `${tool('research_tree.py')} ui`
  const dir = projectDir(project)
  return `${UI_ROLE}

职责：
1. 理解和澄清用户意图；区分讨论、问题、偏好、明确决定和行动指令；只追问会改变执行的缺口。
2. 回答进度与结果问题：依据共享记录（下面的项目摘要、研究数据库的只读查询、文档库 ${project.root}/docs 中的文档），注明数据版本；不自行查询作业，不调度worker。
3. 不派发、暂停或重分配worker，不替RLD作研究决定，不修改研究数据库、文档库和代码。
4. 用中文简洁回复，说明哪些是已记录的事实、哪些是你的理解。

在项目目录 ${dir} 运行命令。查询研究数据库只用 query（只读：get、find、edges、children、history、latest_result、go_candidates、screen_seed_count、resume_package、help）：
  ${tool('research_tree.py')} query get '{"entity_id": "H-0001"}'

处理每条用户消息时按下面的顺序判断，选第一条符合的：
1. 立即生效的指令（停止、暂停、收回授权、纠正重大约束）：用 instruction 立即登记转交，不先追问。
2. 立项计划正等待确认，且用户明确表示同意：用 confirm。用户对计划提出修改，按第4条处理，不要确认。
3. 只是问题（进度、结果、规则）：查共享记录后回答；需要RLD回答时用 question。
4. 其他要求、偏好或变更：先判断是否清楚——只凭用户说过的话，目标和范围能否直接执行，而不必猜测频率、对象、程度、期限等关键细节。
   - 不清楚：不要登记，也不要替用户假设。回复里只问最关键的一两个问题，同时把已明确的部分写进需求草稿（新建或更新）。
   - 清楚：更新草稿（列出依据的全部消息编号）并 submit；剩下的非关键缺口写进待决定项。
   普通讨论记进草稿，到决策点再提交，不逐句打扰RLD。

你的回复与动作只通过本次的发件箱交给 mod（本次编号 ${run}），mod 在你结束后执行；参数用单引号括起：
- 回复用户（必须有，可多次，按顺序显示）：${outbox} reply --run ${run} --text '<给用户的回复>'
- 确认立项计划：${outbox} confirm --run ${run}
- 立即生效的指令：${outbox} instruction --run ${run} --understanding '<你的理解、生效范围、取代的旧指令>' --kind <停止|暂停|收回授权|约束纠正> --about <相关的节点或项目ID>
- 向RLD提问：${outbox} question --run ${run} --text '<不超过200字的问题>' --about <ID>
- 提交澄清完成的需求：${outbox} submit --run ${run} --req REQ-<编号>
mod 会把用户的原话登记为确认、指令或需求文档，你不必也不能转述原话。
结束本次运行（SubagentHandback）之前，必须已经运行过 reply；SubagentHandback 的内容不会显示给用户，也不会转交RLD。答不了的问题，reply 说明情况并用 question 转交RLD。

需求草稿（你的工作记录，立即保存，不交给任何人）：
  ${tool('research_tree.py')} requirement draft [--req REQ-<编号>] --title '<一句话>' --goal '<目标与理由>' --scope '<范围：包含与排除>' --constraints '<约束>' --acceptance '<验收>' --priority '<优先级>' --open '<授权与待决定项、明示假设>' --changes '<相对上一版的变化>' --messages <依据的用户消息编号 w-…> --about <ID>
不带 --req 时新建一份；只更新给出的字段，消息编号累加。已提交的需求再变化时，在原编号上更新草稿并再次提交（生成新版本）。
RLD 收到需求或指令后会在窗口回执（理解、可执行部分、缺口）；回执列出的缺口与用户继续澄清，更新草稿后再提交。

规则文件：${pluginRoot}/${RULES}。`
}

/** Where development and experiments run, as research-tree.yaml says; handed to the RLD and every worker. */
function platformText(conf: ResearchConfig | null | undefined): string {
  if (!conf) return `项目还没有可用的 ${CONFIG_FILE}：按用户的说明运行，不确定时先问。`
  const skills = conf.platform.skills.length ? `\n预加载的技能：${conf.platform.skills.join('、')}` : ''
  return `开发（写代码、单元测试、小规模检查）：\n${conf.platform.dev.trim()}\n实验（训练、评测等计算类工作）：\n${conf.platform.experiment.trim()}${skills}`
}

function workerPrompt(conf: ResearchConfig | null | undefined): string {
  return `你是 research-tree 项目的 worker，由 Research Leader（RLD）委派；你的身份（worker/<id>）写在任务说明开头。一个节点一个 worker：你从头负责这个节点直到它完成，RLD 会用 SendMessage 把后续步骤交给你。
- 开始时用 mcp__research-tree__research_db 调用 resume_package（node_id 为你的节点，根节点为项目ID），读完其中列出的全部文档：这是你的工作依据；之后可能由另一个会话以同一身份接手，所以重要的中间结论要写成文档，并用 add_resume_docs 加进节点的恢复文档。
- 只在认领的任务范围内工作：先读取任务（get）和请求文档，再用 update_task 把任务改为 in_progress。
- 代码改动只在任务指定的仓库分支或worktree中进行并提交；除根节点框架任务外，不改动冻结的实验框架与统计代码。
- 测试、训练、推理等工作按下面“开发与实验平台”的规定运行；规定没有覆盖、又可能占用大量资源的操作，先问RLD。
- 实验、运行与判定只通过 research_db 登记（create_experiment、create_run、update_run、record_verdict），不编造数字；工程失败如实记录，不当作科学结论。单次运行上限和累计用量提醒由 research_db 检查，被拒绝时交RLD，不绕过。
- 每个 seed 的运行：create_run 后用 update_run 把 exec_status 从 planned 推进到 submitted（running）再到 succeeded，在 succeeded 时写入 valid=true 和 metric_value、secondary、nodes_used、walltime_used_s 以及 output_path（运行的输出目录）和 log_path；验收不通过时设 valid=false 并写 invalid_reason。全部 seed 有效后由实验 owner 调用 record_verdict（基线只记指标，不给判定）。
- record_verdict 之后立即调用 run_cleanup(experiment_id) 清理该实验的产物（权重、checkpoint 等，证据保留），不必请示；交付前必须完成。后续实验要用这些产物（例如在其权重上继续训练）时，在 create_experiment 时用 keep 与 keep_reason 声明，事后无法恢复。清理什么由项目目录的 research-tree-cleanup.py 决定，可按项目的输出调整它。
- 不确定 research_db 的方法或参数时调用 method="help"（kwargs {"method": "<方法名>"} 看完整说明），不要猜；按错误信息改正。
- 交付：写 tasks/<任务ID>/delivery.v1.md，章节为“实际改动与版本、运行与产物、验证结果、资源观测、未完成与未知项”（各章节内容见规则第4节），登记并设为现行，再 update_task(status=delivered, delivery_doc_id)；最终回复只给简短说明和文档引用。
- 不自行改变研究目标、选择新的研究分支或接管他人任务；范围变化交RLD。

## 开发与实验平台（${CONFIG_FILE}）
${platformText(conf)}`
}

/** The budget and gates of research-tree.yaml in words, for the RLD's planning. */
function budgetText(view: ResearchConfigView | null | undefined): string {
  if (!view) return `（读取不到 ${CONFIG_FILE}）`
  const b = view.effective.budget
  const s = view.effective.stage1
  return `单次运行上限 ${b.per_run.nodes} nodes × ${b.per_run.walltime}；筛选预算 ${b.screen_node_h} node·h；` +
    `同时有任务的worker ${b.max_parallel_workers ?? '不限'}；用量提醒 ${b.alert_node_h === null ? '无' : `${b.alert_node_h} node·h`}；` +
    `优于SOTA门槛：${s.gate_seeds} 个seed、主指标领先超过 ${s.go_margin}；每个节点至少引用 ${s.min_related_work} 篇相关研究`
}

function planningPrompt(project: ResearchProject, pluginRoot: string, view: ResearchConfigView | null): string {
  const instr = project.plan_instruction
  const fields = view ? Object.entries(view.db_fields).map(([k, v]) => `${k}=${v === null ? 'null' : v}`).join('，') : ''
  return `研究项目已由 /${COMMAND} init 在 ${project.root} 建立：项目 ${project.project_id}（数据库 ${project.db}）。用户的研究目标与初始方案已逐字登记为用户指令 ${instr.doc_id}（docs/${instr.path}，原文件 ${project.plan}）。

项目配置 ${view?.file ?? CONFIG_FILE}（用户可在确认前修改；确认时 mod 把它登记为生效版本，并把预算与门槛写入项目记录）：
${budgetText(view)}
${platformText(view?.effective)}

请作为 Research Leader 完成立项规划。本阶段不要启动 worker，也不要提交任何作业：
1. 读原文。写 docs/project/goal.v1.md（研究目标）和 docs/project/min-setup.v1.md（最小实验设定：模型、数据、训练量、评测、主指标及优劣方向、其他比较指标、${view?.effective.stage1.gate_seeds ?? 3}个统一seed、计划的实验框架与判定规则；单次运行上限、筛选预算与门槛照抄上面的项目配置）；用 research_db 登记（register_document）并设为现行。原文的预算或门槛与项目配置不一致时，在立项计划中指出，请用户改配置文件，不要自行取舍。
2. create_project：id 为 ${project.project_id}，repo_path 为本项目代码仓库的绝对路径（原文未给出就在 ${project.root}/../.. 下合适的位置新建 git 仓库）；预算与门槛参数取自项目配置（${fields}），其余参数取自最小实验设定。
3. 为原文中的每个初始假说检索并缓存相关研究（docs/literature/，每个节点至少${view?.effective.stage1.min_related_work ?? 3}篇，原文缓存到 cache/literature/），写假说文档（创建理由、计划的代码改动、实验计划），create_hypothesis 建初始节点（状态为待验证）。所有初始假说都不指定 parent_id：它们都是根节点的直接子节点、彼此平级，即使原文暗示了先后或包含关系也不在初始假说之间建立父子关系（只有验证完成、可拓展的节点才能派生子节点）。
4. 根节点只存放 baselines：写 docs/tasks/T-0001/request.v1.md（章节为“任务与节点、问题与预测、干预与对照、范围与权限、资源与预算、验收与停止条件、交付”，内容见规则第4节），说明要实现的实验骨架与统计代码、按框架的输出调整项目目录的清理脚本 research-tree-cleanup.py（哪些文件是可删的权重、checkpoint 等），以及要运行的SOTA与其他基线方案；create_task(kind=harness, assignee_role=worker)，先不指派。
5. 写 docs/project/reports/init-plan.v1.md 汇总以上（目标、设定、初始节点、基线与根节点方案、预计资源），登记并设为现行，然后调用 post_to_ui(type=confirm_request, docs=["project/reports/init-plan.v1.md"]) 请用户在研究对话窗口确认。
用户确认之前 mod 会拒绝启动 worker。规则文件：${pluginRoot}/${RULES}。`
}

function startPrompt(project: ResearchProject, confirmation: { doc_id: string; path: string }): string {
  return `用户已确认 ${project.project_id} 的立项计划（用户指令 ${confirmation.doc_id}，docs/${confirmation.path}）。
请开始实现根节点：用 research_db 的 assign_worker（node_id=${project.project_id}）为根节点指派 worker（默认 root），用 update_task 把根节点任务（kind=harness，通常是 T-0001）指派给它（assignee_id=root），然后用 Agent 工具启动 subagent_type="${WORKER_AGENT}" 的子代理，任务说明以“你是 worker/root”开头，写明任务ID、请求文档和交付要求。worker 交付后，按规则审核框架与基线结果并冻结框架（update_project harness_ref/harness_paths），设置SOTA基线后再推进各节点。`
}

const WORKFLOW = `## research-tree 工作流（由 research-tree mod 注入）
- 研究项目的状态、节点、实验、判定和决定都在当前目录 research/<项目ID>/ 的 LatticeDB 研究数据库里；只能通过 ${'`'}${TOOL}${'`'} 工具（或 tools/research_db.py）读写，不要直接改数据库文件。
- 实验优先：每个节点都要有实质性代码改动和实验；节点结论跟随冻结统计代码的判定（无提升→可消灭，优于父节点→可拓展，优于SOTA→RLD复核新颖性与理论正确性）。
- 搜索树的根节点只存放 baselines（冻结框架、SOTA与其他基线实验）；用户的初始假说都是根节点的直接子节点；只有验证完成、可拓展的节点才能派生子节点。
- 已生效的文档不可修改，改动写新版本；节点代码中不能改动冻结框架。
- 不确定 research_db 的方法或参数时，先调用 method="help"（kwargs {"method": "<方法名>"} 看完整说明），不要猜；接口拒绝时按错误信息改正，不要绕过。
- 一个节点一个 worker：先用 assign_worker 为节点指派身份（假说节点默认 h<编号>，根节点 root），启动 ${WORKER_AGENT} 时任务说明以“你是 worker/<id>”开头；mod 会把会话的 agent ID 记进节点（worker_agent_id）。节点的后续步骤用 SendMessage 续接这个 agent；无法续接或上下文过长时，用 resume_package 取恢复包，以同一身份新起一个 worker 接手。
- 立项计划须经用户确认后才能启动 ${WORKER_AGENT} 子代理；需要用户决定的事用 post_to_ui；用户在研究对话窗口说的话由 mod 原文登记后送达。
- 开发与实验平台、资源预算、阶段1门槛和子代理模型由项目目录的 ${CONFIG_FILE} 决定，用户改动后经 /${COMMAND} config apply 生效；不要自行改这个文件。同时有任务的worker数（max_parallel_workers）和累计用量提醒（alert_node_h）由 research_db 与 mod 执行：达到提醒阈值后新实验与扩展seed暂停，向用户报告进展与所需预算，由用户决定。
- /${COMMAND} 查看进度；/${COMMAND} ui 打开研究对话窗口；/${COMMAND} pane 打开进度面板；/${COMMAND} build 生成离线进度页面。`

// ---------------------------------------------------------------------------
// UI window
// ---------------------------------------------------------------------------

/** Queues a prompt for the main session (the RLD). The engine refuses $.prompt.submit inside the hooks that
 *  hold a turn (command.run, tool.call, ...), so it is submitted from a timer once the hook has returned; the
 *  prompt then runs as soon as the session is idle. */
function submitLater($: EngineInterface, prompt: { text: string }): void {
  $.clock.after(0, () => {
    void $.prompt.submit(prompt).catch(err => {
      void say($, 'note', `未能把消息交给 RLD：${err instanceof Error ? err.message : String(err)}`)
    })
  })
}

// Window log writes, one after another: each rewrites messages/window.jsonl whole (the plugin file system has no
// append), so two at once would lose a line or reuse an id.
let windowWrites: Promise<unknown> = Promise.resolve()

/** Adds a line to the research window: shown at once, and kept in the project's window log
 *  (messages/window.jsonl) under an id (w-<n>) the UI cites and requirement documents quote. */
async function say($: EngineInterface, role: ResearchChatEntry['role'], text: string): Promise<string | undefined> {
  const at = now()
  const project = (await $.state.get(projectRef)).value
  let id: string | undefined
  if (project) {
    const file = `${project.root}/messages/window.jsonl`
    const write = windowWrites.then(async () => {
      const old = (await $.fs.exists(file)) ? await $.fs.read(file) : ''
      id = `w-${String(old.split('\n').filter(Boolean).length + 1).padStart(4, '0')}`
      await $.fs.write(file, `${old}${JSON.stringify({ id, ts: new Date().toISOString().slice(0, 19) + 'Z', role, text })}\n`)
    })
    windowWrites = write.catch(() => undefined)
    try {
      await write
    } catch {
      id = undefined  // shown but not logged; the window still works
    }
  }
  await update($, chatAtom, list => [...(list ?? []), { role, text, at, ...(id ? { id } : {}) }].slice(-200))
  return id
}

/** The research window's conversation from the project's window log, after a restart. */
async function loadChat($: EngineInterface, project: ResearchProject): Promise<void> {
  if (((await $.state.get(chatRef)).value ?? []).length) return
  const file = `${project.root}/messages/window.jsonl`
  if (!(await $.fs.exists(file))) return
  const entries: ResearchChatEntry[] = []
  for (const line of (await $.fs.read(file)).split('\n').filter(Boolean).slice(-200)) {
    try {
      const e = JSON.parse(line) as { id: string; ts: string; role: ResearchChatEntry['role']; text: string }
      entries.push({ role: e.role, text: e.text, at: e.ts.replace('T', ' ').replace('Z', ''), id: e.id })
    } catch {
      // a damaged line is skipped; the file stays as it is
    }
  }
  await $.state.set(chatRef, entries)
}

type UiRun = { run: string; message: string; messageId?: string; attempt: number }

/** Hands the person's message to a fresh UI subagent run with the recent conversation and the project view. */
async function askUi($: EngineInterface, cfg: Config, text: string): Promise<void> {
  const message = text.trim()
  if (!message) return
  if ((await $.state.get(uiAgentRef)).value) {
    await say($, 'note', 'UI 还在处理上一条消息，请稍候。')
    return
  }
  const messageId = await say($, 'user', message)
  const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
  const env = await venv($)
  if (!project || 'problem' in env) {
    await say($, 'note', project ? (env as { problem: string }).problem : `当前目录没有研究项目：先运行 /${COMMAND} init <计划.md>。`)
    return
  }
  await startUi($, cfg, { message, messageId, attempt: 1 })
}

/** Starts one UI run for the person's message; false when it could not start (said in the window). A later
 *  attempt is told that the one before ended without a reply. */
async function startUi($: EngineInterface, cfg: Config, ask: Omit<UiRun, 'run'>): Promise<boolean> {
  const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
  const env = await venv($)
  if (!project || 'problem' in env) return false
  const run = `r${Date.now().toString(36)}`
  const summary = (await $.state.get(summaryRef)).value
  const history = ((await $.state.get(chatRef)).value ?? [])
    .filter(h => !(h.role === 'user' && h.id === ask.messageId && h.text === ask.message)).slice(-30)
  const listed = await tree($, cfg, ['requirement', 'list'])
  const drafts = (listed.ok ? listed.result : []) as { id: string; title: string; status: string; version: number }[]
  const open = drafts.filter(d => d.status === 'open')
  const prompt = [
    uiPrompt($.plugin.root, project, run, env.python),
    `## 当前项目\n${project.project_id}，阶段：${L(project.phase)}` + (summary ? `\n${statusText(summary, project)}` : ''),
    `## 需求草稿\n` + (open.length ? `正在澄清：${JSON.stringify(open)}` : '没有正在澄清的需求。') +
      (drafts.length > open.length ? `\n已提交：${drafts.filter(d => d.status !== 'open').map(d => `${d.id} v${d.version} ${d.title}`).join('；')}` : ''),
    history.length ? `## 最近的对话\n${history.map(h => `[${h.id ? `${h.id} ` : ''}${h.role}] ${h.text}`).join('\n')}` : '',
    ask.attempt > 1 ? '## 注意\n上一次处理这条消息的运行结束时发件箱是空的：用户没有收到回复，消息也没有转交。这一次先用 reply 回复，再结束。' : '',
    `## 用户的新消息（${ask.messageId ?? '未记录编号'}）\n${ask.message}`,
  ].filter(Boolean).join('\n\n')
  const spawned = await $.agent.spawn({ subagentType: UI_AGENT, prompt, description: 'UI 回复用户' })
  if (spawned.deny !== undefined || !spawned.agentId) {
    await say($, 'note', `无法启动 UI agent：${spawned.deny ?? `未返回 agentId（${JSON.stringify(spawned).slice(0, 200)}）`}`)
    return false
  }
  await $.state.set(uiAgentRef, spawned.agentId)
  await $.state.set(uiRunRef, { ...ask, run })
  await logAgentModel($, cfg, spawned.agentId, 'ui/ui', 'requested', spawned.model,
    (await $.state.get(configRef)).value?.effective.models.ui.effort)
  return true
}

/** Passes one message from the UI to the RLD: logged through tools/send_message.py, then queued as a prompt. */
async function relayToRld($: EngineInterface, cfg: Config, type: 'instruction' | 'question', text: string,
  docs: string[], about: string[]): Promise<string | undefined> {
  const args = ['--from', 'ui/ui', '--to', 'rld/main', '--type', type, '--text', text.slice(0, 200)]
  if (docs.length) args.push('--docs', ...docs)
  if (about.length) args.push('--about', ...about)
  const logged = await logMessage($, cfg, args)
  if (!logged.ok) return `未能转交RLD：${logged.error}`
  submitLater($, {
    text: `来自研究对话窗口（UI）的消息：\n${logged.line}\n请按 research-tree 规则处理：先读取引用的文档。` +
      (type === 'instruction'
        ? `收到需求或指令后，用 post_to_ui(type=reply, re=该消息的 id, docs=[引用的文档]) 回执：你理解的版本与内容、可以执行的部分、关键缺口或需要用户决定的事；然后按规则落实。`
        : '这是用户的问题：用 post_to_ui(type=reply, re=该消息的 id) 在研究对话窗口回答。'),
  })
  return undefined
}

type UiEntry = { type: 'reply' | 'confirm' | 'instruction' | 'question' | 'submit'; text?: string; understanding?: string;
  kind?: string; about?: string[]; docs?: string[]; req?: string }

/** What a UI run left in its outbox, carried out in order once the run ended: replies shown in the window, the
 *  person's message registered verbatim as a confirmation or an instruction, questions passed to the RLD. A run
 *  that ended with an empty outbox (not interrupted) is retried once; if that one leaves nothing either, the
 *  person's message goes to the RLD verbatim, so a message is never left unanswered and unforwarded. */
async function carryOutUi($: EngineInterface, cfg: Config, run: UiRun, answer: string, aborted: boolean): Promise<void> {
  const project = (await $.state.get(projectRef)).value
  const file = project ? `${project.root}/cache/ui/${run.run}.jsonl` : ''
  const entries: UiEntry[] = []
  if (file && (await $.fs.exists(file))) {
    for (const line of (await $.fs.read(file)).split('\n')) {
      try {
        if (line.trim()) entries.push(JSON.parse(line) as UiEntry)
      } catch {
        await say($, 'note', `UI 发件箱有一行无法解析：${line.slice(0, 120)}`)
      }
    }
  }
  if (!entries.length && !aborted) {
    if (run.attempt < 2) {
      await say($, 'note', 'UI 没有留下回复，正在重新处理这条消息。')
      if (await startUi($, cfg, { message: run.message, messageId: run.messageId, attempt: run.attempt + 1 })) return
    }
    const id = run.messageId ? `${run.messageId}，` : ''
    const failed = await relayToRld($, cfg, 'question',
      `用户在研究对话窗口的消息（${id}UI 未能处理，原文转交；全文见 messages/window.jsonl）：${run.message}`, [], [])
    await say($, 'note', failed ?? 'UI 没能处理这条消息；已把原文转交RLD，RLD 会在这里回复。')
    return
  }
  if (!entries.some(x => x.type === 'reply')) {
    await say($, 'ui', answer.trim() || (aborted ? '（UI 被中断）' : '（UI 没有给出回复）'))
  }
  for (const entry of entries) {
    if (entry.type === 'reply') {
      await say($, 'ui', entry.text ?? '')
    } else if (entry.type === 'confirm') {
      await say($, 'note', await confirmPlan($, cfg, run.message))
    } else if (entry.type === 'instruction') {
      const about = entry.about ?? []
      const registered = await tree($, cfg, ['instruction', '--text', run.message, '--kind', entry.kind || '指令',
        '--understanding', entry.understanding || run.message, ...(about.length ? ['--about', ...about] : [])])
      if (!registered.ok) {
        await say($, 'note', `指令未能登记：${registered.error}`)
        continue
      }
      const failed = await relayToRld($, cfg, 'instruction', `用户指令 ${registered.result.doc_id}：${entry.understanding ?? ''}`,
        [registered.result.path], about)
      await say($, 'note', failed ?? `已登记为用户指令 ${registered.result.doc_id} 并转交RLD。`)
    } else if (entry.type === 'submit') {
      const submitted = await tree($, cfg, ['requirement', 'submit', '--req', entry.req ?? ''])
      if (!submitted.ok) {
        await say($, 'note', `需求未能提交：${submitted.error}`)
        continue
      }
      const r = submitted.result as { req: string; version: number; doc_id: string; path: string; title: string }
      const failed = await relayToRld($, cfg, 'instruction', `需求 ${r.req} v${r.version}（${r.doc_id}）：${r.title}`, [r.path], [])
      await say($, 'note', failed ?? `需求 ${r.req} v${r.version} 已登记（${r.doc_id}）并交给RLD，等待RLD回执。`)
    } else if (entry.type === 'question') {
      const failed = await relayToRld($, cfg, 'question', entry.text ?? '', entry.docs ?? [], entry.about ?? [])
      await say($, 'note', failed ?? `已转交RLD：${entry.text ?? ''}`)
    }
  }
}

/** A plugin tool's answer when its hook fails: the error itself, rather than the engine's "no hook answered". */
function toolFailure(err: unknown) {
  return { result: `${PLUGIN} 内部错误：${err instanceof Error ? err.message : String(err)}`, isError: true as const }
}

/** Logs a message through tools/send_message.py; returns the logged line or the error. */
async function logMessage($: EngineInterface, cfg: Config, args: string[]) {
  const project = (await $.state.get(projectRef)).value
  if (!project) return { ok: false, line: '', error: '当前目录没有研究项目' }
  const out = await runTool($, cfg, 'send_message.py', ['--root', project.root, ...args])
  return { ok: out.exitCode === 0, line: out.stdout.trim(), error: (out.stderr || out.stdout).trim() }
}

/** The user's confirmation of the plan: registered verbatim, phase confirmed, the RLD told to start. */
async function confirmPlan($: EngineInterface, cfg: Config, words: string): Promise<string> {
  const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
  if (!project) return `当前目录没有研究项目；先运行 /${COMMAND} init <计划.md>。`
  if (project.phase === 'confirmed') return '立项计划已经确认过。'
  if (project.phase !== 'awaiting_confirmation') return 'RLD 还没有提交立项计划，暂时无需确认。'
  // The configuration the plan was made with goes into effect with it: registered, and written into the record.
  const applied = await tree($, cfg, ['config', 'apply', '--actor', cfg.actor, '--require-project'])
  if (!applied.ok) return `确认未完成：项目配置未能生效（${applied.error}）。`
  await registerAgents($, (await readConfig($, cfg))?.effective)
  const registered = await tree($, cfg, ['instruction', '--text', words, '--kind', '确认（立项计划）',
    '--understanding', '用户确认RLD提交的立项计划，同意启动worker实现根节点。', '--about', project.project_id])
  if (!registered.ok) return `确认未能登记：${registered.error}`
  const phased = await tree($, cfg, ['phase', '--set', 'confirmed'])
  if (!phased.ok) return `确认已登记，但阶段未能更新：${phased.error}`
  await loadProject($)
  await refresh($, cfg)
  // The RLD answers a confirmation by starting the root's worker, not with a receipt.
  const logged = await logMessage($, cfg, ['--from', 'ui/ui', '--to', 'rld/main', '--type', 'instruction', '--need', 'none',
    '--text', '用户确认立项计划，请启动worker实现根节点。', '--docs', registered.result.path, '--about', project.project_id])
  submitLater($, { text: startPrompt(project, registered.result) + (logged.ok ? `\n消息记录：${logged.line}` : '') })
  return `已确认立项计划（${registered.result.doc_id}）；RLD 将启动 worker 实现根节点。`
}

/** Why worker/<named> may not start now: max_parallel_workers others already have a task in hand. */
function parallelBlock(s: ResearchSummary | null | undefined, named: string): string | undefined {
  const limit = s?.project?.max_parallel_workers
  if (!s || limit == null || s.busy_workers.includes(named) || s.busy_workers.length < limit) return undefined
  return `同时有任务的 worker 已达上限 ${limit}（${s.busy_workers.map(w => `worker/${w}`).join('、')}）；` +
    `等其中一个交付，或请用户在 ${CONFIG_FILE} 调高 max_parallel_workers 后 /${COMMAND} config apply。`
}

/** `/research-tree config [show|apply]`. Applying registers the file as the configuration in effect, writes its
 *  budget and gates into the project record, re-registers the agents and tells the RLD. */
async function configCommand($: EngineInterface, cfg: Config, action = ''): Promise<string> {
  if (!action) {
    const out = await $.process.run(['sh', `${$.plugin.root}/tools/copy_config.sh`, await $.session.cwd()], { timeoutMs: 10_000 })
    return (out.stdout || out.stderr).trim() || `复制配置失败：exit ${out.exitCode}`
  }
  if (action !== 'show' && action !== 'apply') return `用法：/${COMMAND} config [show|apply]`
  const env = await venv($)
  if ('problem' in env) return env.problem
  if (action === 'show') {
    const view = await readConfig($, cfg)
    return view ? configText(view) : `读取不到项目配置 ${CONFIG_FILE}。`
  }
  const project = await loadProject($)
  if (!project) return `当前目录没有研究项目：运行 /${COMMAND} init <计划.md>`
  const applied = await tree($, cfg, ['config', 'apply', '--actor', cfg.actor, '--words', `/${COMMAND} config apply`])
  if (!applied.ok) return `配置未生效：${applied.error}`
  await loadProject($)
  const view = await readConfig($, cfg)
  await registerAgents($, view?.effective)
  await refresh($, cfg)
  const r = applied.result as { config: { doc_id: string; path: string }; new_version: boolean;
    updated_fields: Record<string, unknown>; instruction: { doc_id: string } | null }
  const changed = Object.keys(r.updated_fields)
  if (!r.new_version && !changed.length) return `项目配置没有变化（${r.config.doc_id}）。`
  const note = `项目配置已生效：${r.config.doc_id}（docs/${r.config.path}）` +
    (changed.length ? `；项目记录更新了 ${changed.join('、')}` : '') +
    (r.instruction ? `；登记为用户指令 ${r.instruction.doc_id}` : '')
  await say($, 'note', note)
  submitLater($, {
    text: `用户更新了项目配置。${note}。之后启动的 worker 使用新的模型、平台说明和预加载技能；对正在用 SendMessage 续接的 worker，` +
      `把平台或预算的变化转告它们。立项计划尚未确认时，按新配置更新计划。\n${view ? configText(view) : ''}`,
  })
  return note
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export const register: Register = (on, options) => {
  const cfg = config(options)
  registerUiPane(on, cfg)
  registerProgressPane(on, cfg)

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: '研究树：config（复制默认YAML）、config show/apply、init <计划.md> [--python 3.13] [--id 项目ID] [--config 配置.yaml] [--update-uv]、confirm、status（默认）、ui、pane、refresh、build、check',
    })
    await $.tool.register({
      name: 'research_db',
      description:
        'Call one method of the research database API (tools/research_db.py) on the research project of the ' +
        'current directory: reads (get, find, edges, children, history, go_candidates, latest_result, ' +
        'screen_seed_count, export_snapshot) and writes (register_document, set_document_current, create_project, ' +
        'create_hypothesis, create_task, create_experiment, update_run, record_verdict, decide, ...). The API ' +
        'enforces the workflow rules and permissions and answers JSON {ok, result} or {ok: false, error}. ' +
        'method "help" lists every method with its parameters; help with kwargs {"method": "<name>"} gives one ' +
        "method's full description. Call it instead of guessing a method or its arguments.",
      inputSchema: {
        type: 'object',
        properties: {
          method: { type: 'string', description: 'ResearchDB method name, e.g. "find" or "decide"' },
          kwargs: { type: 'object', description: 'Keyword arguments of the method as JSON' },
          actor: { type: 'string', description: '<role>/<agent-id>; worker runs are fixed by the mod' },
        },
        required: ['method'],
      },
    })
    await $.tool.register({
      name: 'post_to_ui',
      description:
        'RLD: post a message into the research UI window the person reads. type confirm_request (with the ' +
        'registered document that explains the decision) asks the person to decide; the start-up plan is ' +
        'confirmed this way before any worker starts.',
      inputSchema: {
        type: 'object',
        properties: {
          type: { type: 'string', enum: ['confirm_request', 'reply', 'notice'] },
          text: { type: 'string', description: 'Short note, at most 200 characters' },
          re: { type: 'string', description: 'reply: the id of the message answered (e.g. ui-0003)' },
          docs: { type: 'array', items: { type: 'string' }, description: 'Versioned paths relative to docs/' },
        },
        required: ['type', 'text'],
      },
    })
    const project = await loadProject($)
    if (project) await loadChat($, project)
    await registerAgents($, project ? (await readConfig($, cfg))?.effective : null)
    const started = await next(e)
    if (project) await refresh($, cfg)
    return started
  })

  // The UI agent is the window's own: the main model never delegates to it.
  on('agent.offer', { agent: UI_AGENT }, () => ({ isOffered: false }))

  // Workers start only after the user confirmed the plan; each run gets a worker identity.
  on('agent.spawn', async ($, e, next) => {
    const type = e.subagentType ?? (e as unknown as { subagent_type?: string }).subagent_type
    if (type !== WORKER_AGENT) return next(e)
    const blocked = workerBlock((await $.state.get(projectRef)).value)
    if (blocked) return { deny: `${PLUGIN}: ${blocked}` }
    // A worker is a node's: the prompt names the node's assigned identity, and the new session is bound to it.
    const named = /worker\/([A-Za-z0-9_.]+)/.exec(e.prompt)?.[1]
    if (!named) {
      return { deny: `${PLUGIN}: 任务说明开头要写“你是 worker/<id>”，<id> 是节点的 worker_id（用 research_db 的 assign_worker 指派）。` }
    }
    const summary = await refresh($, cfg)
    const node = workerNode(summary, named)
    if (!node) return { deny: `${PLUGIN}: worker/${named} 没有指派给任何节点；先用 research_db 的 assign_worker 为节点指派。` }
    const busy = parallelBlock(summary, named)
    if (busy) return { deny: `${PLUGIN}: ${busy}` }
    const spawned = await next(e)
    if (spawned.agentId) {
      const agentId = spawned.agentId
      await update($, agentsAtom, map => ({ ...(map ?? {}), [agentId]: `worker/${named}` }))
      await logAgentModel($, cfg, agentId, `worker/${named}`, 'requested', spawned.model,
        (await $.state.get(configRef)).value?.effective.models.worker.effort)
      const project = (await $.state.get(projectRef)).value
      if (project) {
        await runTool($, cfg, 'research_db.py', ['--db', project.db, '--actor', cfg.actor, 'bind_worker_session',
          JSON.stringify({ node_id: node, agent_id: agentId })])
        await refresh($, cfg)
      }
    }
    return spawned
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId && e.usage?.model && observedModels.get(e.agentId) !== e.usage.model) {
      const actor = e.agentId === (await $.state.get(uiAgentRef)).value ? 'ui/ui'
        : (await $.state.get(agentsRef)).value?.[e.agentId] ?? workerActor((await $.state.get(summaryRef)).value, e.agentId)
      if (actor) {
        observedModels.set(e.agentId, e.usage.model)
        await logAgentModel($, cfg, e.agentId, actor, 'observed', e.usage.model)
      }
    }
    if (e.agentId && e.agentId === (await $.state.get(uiAgentRef)).value) {
      const run = (await $.state.get(uiRunRef)).value
      await $.state.set(uiAgentRef, null)
      await $.state.set(uiRunRef, null)
      if (run) await carryOutUi($, cfg, run, e.answer, e.isAborted)
    }
    return done
  })

  on('command.run', { command: COMMAND }, async ($, e) => {
    const words = e.args.trim().split(/\s+/).filter(Boolean)
    const sub = words[0] ?? 'status'
    if (sub === 'init') {
      const parsed = parseInit(words.slice(1))
      if ('usage' in parsed) return { text: parsed.usage }
      const existing = await loadProject($)
      if (existing) return { text: `当前目录已经有研究项目 ${existing.project_id}（${existing.root}）。` }
      const env = await setUpEnvironment($, parsed.python, !!parsed.updateUv)
      if (!env.ok) return { text: env.log.join('\n') }
      const made = await tree($, cfg, ['init', parsed.plan, ...(parsed.id ? ['--project-id', parsed.id] : []),
        ...(parsed.config ? ['--config', parsed.config] : [])])
      if (!made.ok) return { text: [...env.log, `初始化失败：${made.error}`].join('\n') }
      const project = await loadProject($)
      if (!project) return { text: [...env.log, '初始化完成，但读取不到 .research-tree.json。'].join('\n') }
      const view = await readConfig($, cfg)
      await registerAgents($, view?.effective)
      await refresh($, cfg)
      await $.ui.open({ id: UI_PANE, title: '研究对话（UI）' })
      await say($, 'note', `已建立 ${project.project_id}；计划已登记为 ${project.plan_instruction.doc_id}。RLD 正在整理立项计划，完成后会在这里请你确认。` +
        `开发与实验平台、预算和模型见 ${CONFIG_FILE}，确认前可以修改。`)
      submitLater($, { text: planningPrompt(project, $.plugin.root, view) })
      return {
        text: [...env.log, `已在 ${project.root} 建立研究项目 ${project.project_id}：目录、数据库、通信登记表已就绪，` +
          `计划原文登记为 ${project.plan_instruction.doc_id}。研究对话窗口已打开；RLD 将据计划建立目标、初始节点和根节点方案，并请你确认。`,
          `项目配置：${view?.file ?? CONFIG_FILE}（${parsed.config ? `取自 ${parsed.config}` : '默认配置'}；开发与实验平台、资源预算、阶段1门槛、子代理模型）。确认立项前改动直接生效，之后改动用 /${COMMAND} config apply 生效。`].join('\n'),
      }
    }
    if (sub === 'confirm') {
      const confirmed = await confirmPlan($, cfg, words.slice(1).join(' ') || `/${COMMAND} confirm`)
      await say($, 'note', confirmed)
      return { text: confirmed }
    }
    if (sub === 'config') {
      return { text: await configCommand($, cfg, words[1]) }
    }
    if (sub === 'ui') {
      await $.ui.open({ id: UI_PANE, title: '研究对话（UI）', focus: true })
      return { text: '研究对话窗口已打开：在窗口的输入框里与 UI agent 对话。' }
    }
    if (sub === 'pane') {
      await $.ui.open({ id: PANE, title: '研究进度' })
      await refresh($, cfg)
      return { text: '研究进度面板已打开。' }
    }
    if (sub === 'build' || sub === 'check') {
      const project = await loadProject($)
      if (!project) return { text: `当前目录没有研究项目：运行 /${COMMAND} init <计划.md>` }
      const out = await runTool($, cfg, 'build_site.py', ['--db', project.db, ...(sub === 'check' ? ['--check'] : [])])
      await refresh($, cfg)
      return { text: (out.stdout || out.stderr).trim() || `exit ${out.exitCode}` }
    }
    if (sub !== 'status' && sub !== 'refresh') {
      return { text: `未知子命令 ${sub}；可用：init、confirm、config、status、ui、pane、refresh、build、check` }
    }
    await loadProject($)
    const summary = await refresh($, cfg)
    if (!summary) return { text: (await $.state.get(errorRef)).value ?? '没有可显示的研究进度。' }
    return { text: statusText(summary, (await $.state.get(projectRef)).value) }
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    try {
      const input = e as unknown as { method?: unknown; kwargs?: unknown; actor?: unknown }
      if (typeof input.method !== 'string' || !/^[a-z_]+$/.test(input.method)) {
        return { result: 'research_db: method must be a ResearchDB method name', isError: true as const }
      }
      const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
      if (!project) return { result: `当前目录没有研究项目：运行 /${COMMAND} init <计划.md>`, isError: true as const }
      // Worker runs act as themselves whatever they pass.
      const fixed = e.agentId === undefined ? undefined
        : (await $.state.get(agentsRef)).value?.[e.agentId] ?? workerActor((await $.state.get(summaryRef)).value, e.agentId)
      const actor = fixed ?? (typeof input.actor === 'string' && input.actor ? input.actor : cfg.actor)
      // A cleanup deletes run outputs: it may take a while on shared storage.
      const out = await runTool($, cfg, 'research_db.py', [
        '--db', project.db, '--actor', actor, input.method, JSON.stringify(input.kwargs ?? {}),
      ], input.method === 'run_cleanup' ? 1_800_000 : 60_000)
      if (!READ_ONLY.test(input.method)) await refresh($, cfg)
      const text = (out.stdout || out.stderr).trim()
      return out.exitCode === 0 ? { result: text } : { result: text || `exit ${out.exitCode}`, isError: true as const }
    } catch (err) {
      return toolFailure(err)
    }
  })

  on('tool.call', { tool: POST_TOOL }, async ($, e) => {
    try {
      const input = e as unknown as { type?: string; text?: string; docs?: string[]; re?: string }
      let logged = ''
      if (input.type === 'reply' && !input.re) {
        return { result: 'post_to_ui: reply 需要 re（所回复消息的 id）。', isError: true as const }
      }
      if ((input.docs?.length || input.re) && input.type !== 'notice') {
        const args = ['--from', 'rld/main', '--to', 'ui/ui', '--type', String(input.type), '--text', String(input.text ?? ''),
          ...(input.re ? ['--re', input.re] : []), ...(input.docs?.length ? ['--docs', ...input.docs] : [])]
        const out = await logMessage($, cfg, args)
        if (!out.ok) return { result: `post_to_ui 被拒绝：${out.error}`, isError: true as const }
        logged = out.line
      }
      const project = (await $.state.get(projectRef)).value
      if (input.type === 'confirm_request' && project?.phase === 'planning') {
        const phased = await tree($, cfg, ['phase', '--set', 'awaiting_confirmation'])
        if (phased.ok) {
          await loadProject($)
          await refresh($, cfg)
        }
      }
      const refs = input.docs?.length ? `\n引用：${input.docs.join('，')}` : ''
      await say($, 'rld', `${input.type === 'confirm_request' ? '【需要你决定】' : ''}${input.text ?? ''}${refs}` +
        (input.type === 'confirm_request' ? `\n同意请在此回复，或运行 /${COMMAND} confirm。` : ''))
      $.ui.toast(input.type === 'confirm_request' ? 'RLD 需要你的决定，见“研究对话”窗口' : 'RLD 在“研究对话”窗口留言')
      void $.ui.open({ id: UI_PANE, title: '研究对话（UI）' })
      return { result: logged ? `已发送到UI窗口并记录：${logged}` : '已发送到UI窗口。' }
    } catch (err) {
      return toolFailure(err)
    }
  })

  on('tool.call', { tool: 'Edit' }, async ($, e, next) => (await guard($, e.file_path)) ?? next(e))
  on('tool.call', { tool: 'Write' }, async ($, e, next) => (await guard($, e.file_path)) ?? next(e))
  on('tool.call', { tool: 'NotebookEdit' }, async ($, e, next) => (await guard($, e.notebook_path)) ?? next(e))

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const project = (await $.state.get(projectRef)).value
    if (writesDatabase(e.command, project?.db)) {
      return { deny: `${PLUGIN}: 不要直接改动研究项目的数据库文件；通过 research_db 工具或 tools/research_db.py 写入，它会检查规则并记录决定。` }
    }
    if (project && writesConfig(e.command, `${projectDir(project)}/${CONFIG_FILE}`)) return { deny: `${PLUGIN}: ${CONFIG_REASON}` }
    // A subagent is never the RLD: a worker acts as itself, other helpers read. (The UI's run has its own outbox.)
    if (e.agentId !== undefined && e.agentId !== (await $.state.get(uiAgentRef)).value) {
      const worker = (await $.state.get(agentsRef)).value?.[e.agentId] ?? workerActor((await $.state.get(summaryRef)).value, e.agentId)
      const blocked = subagentCallBlock(researchCalls(e.command), worker)
      if (blocked) return { deny: `${PLUGIN}: ${blocked}` }
    }
    const ran = await next(e)
    if (/\b(research_db|send_message|make_demo|build_site|research_tree)\.py\b/.test(e.command)) await refresh($, cfg)
    return ran
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    const project = (await $.state.get(projectRef)).value
    const summary = (await $.state.get(summaryRef)).value
    const conf = (await $.state.get(configRef)).value
    const status = project
      ? `\n\n当前项目：${project.project_id}（${L(project.phase)}，${project.root}）` + (summary ? `\n${statusText(summary, project)}` : '') +
        `\n\n### 开发与实验平台（${CONFIG_FILE}）\n${platformText(conf?.effective)}`
      : `\n\n当前目录没有研究项目（/${COMMAND} init <计划.md> 可新建）。`
    return { sections: [...composed.sections, { id: `${PLUGIN}:workflow`, text: WORKFLOW + status, scope: 'session' as const }] }
  })
}

// ---------------------------------------------------------------------------
// Panes
// ---------------------------------------------------------------------------

const ROLE: Record<ResearchChatEntry['role'], { name: string; color?: string }> = {
  user: { name: '你', color: 'cyan' },
  ui: { name: 'UI', color: 'green' },
  rld: { name: 'RLD', color: 'magenta' },
  note: { name: '·' },
}

function registerUiPane(on: Parameters<Register>[0], cfg: Config): void {
  on('ui.render', { component: 'Pane', requestId: UI_PANE }, async ($, e) => {
    const elements = $.ui.resolve(e)
    const { Box, Text } = elements
    const Input = 'Input' in elements ? elements.Input : undefined  // a surface without text input (mobile)
    const chat = (await read($, chatAtom)) ?? []
    const running = await read($, uiAgentAtom)
    const project = await read($, projectAtom)
    const room = Math.max(3, (e.viewport?.rows ?? 30) - 8)
    return (
      <Box flexDirection="column">
        <Text dimColor wrap="truncate">
          {project ? `${project.project_id} · ${L(project.phase)}` : '当前目录没有研究项目'} · 指令先登记为文档再转交 RLD
        </Text>
        {chat.length === 0 && <Text dimColor>还没有消息。</Text>}
        {chat.slice(-room).map((m, i) => (
          <Text key={`m${i}`} dimColor={m.role === 'note'}>
            <Text bold color={ROLE[m.role].color}>{ROLE[m.role].name}</Text> {m.text}
          </Text>
        ))}
        {running && <Text color="yellow">UI 正在回复…</Text>}
        {Input
          ? <Input key="ask" autoFocus value="" placeholder="对 UI 说…" submitLabel="发送"
              onSubmit={(value: string) => void askUi($, cfg, value)} />
          : <Text dimColor>此界面不能输入，请在终端或桌面端打开。</Text>}
      </Box>
    )
  })
}

function registerProgressPane(on: Parameters<Register>[0], cfg: Config): void {
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const summary = await read($, summaryAtom)
    const error = await read($, errorAtom)
    const refreshedAt = await read($, refreshedAtom)
    const project = await read($, projectAtom)
    const width = e.props.bodyColumns ?? 60
    const buttons = (
      <Box flexDirection="row" gap={1}>
        <Button key="refresh" hotkey="r" onPress={() => void refresh($, cfg)}>刷新</Button>
        <Button key="build" hotkey="b" onPress={async () => {
          if (!project) return
          const out = await runTool($, cfg, 'build_site.py', ['--db', project.db])
          $.ui.toast((out.stdout || out.stderr).trim().slice(0, 200))
          await refresh($, cfg)
        }}>生成页面</Button>
      </Box>
    )
    if (!summary || !summary.project) {
      return (
        <Box flexDirection="column">
          <Text color={summary ? undefined : 'red'}>
            {summary ? `${project?.project_id ?? ''}：${L(project?.phase)}，RLD 尚未建立项目记录。` : (error ?? '尚未读取研究数据库。')}
          </Text>
          {buttons}
        </Box>
      )
    }
    const children = new Map<string, ResearchNode[]>()
    for (const n of summary.nodes) children.set(n.parent, [...(children.get(n.parent) ?? []), n])
    const rows: { node: ResearchNode; depth: number }[] = []
    const walk = (parent: string, depth: number) => {
      for (const n of children.get(parent) ?? []) {
        rows.push({ node: n, depth })
        walk(n.id, depth + 1)
      }
    }
    walk(summary.project.id, 1)
    const room = Math.max(4, (e.viewport?.rows ?? 30) - 12 - Math.min(summary.attention.length, 6))
    return (
      <Box flexDirection="column">
        <Text bold wrap="truncate">{summary.project.title}</Text>
        <Text dimColor wrap="truncate">
          {summary.project.id} · {L(summary.project.status)} · {L(project?.phase)} · v{summary.meta.data_version} · 刷新于 {refreshedAt ?? '—'}
        </Text>
        <Text wrap="truncate">
          节点 {summary.nodes.length} · 优于SOTA {summary.counts.exp_status.beats_sota ?? 0} · GO候选 {summary.counts.go} · {summary.counts.node_hours} node·h
        </Text>
        <Text> </Text>
        <Text wrap="truncate">
          <Text bold>根节点 · baselines</Text> <Text dimColor>SOTA {summary.project.sota_experiment_id ?? '未设置'} · 框架 {summary.project.harness_ref ? summary.project.harness_ref.slice(0, 10) : '未冻结'}</Text>
        </Text>
        {rows.slice(0, room).map(({ node, depth }) => (
          <Text key={node.id} wrap="truncate">
            {'  '.repeat(depth)}
            <Text color={STATUS_COLOR[node.status]}>●</Text> {node.id} {node.title.slice(0, Math.max(6, width - 40 - depth * 2))}{' '}
            <Text dimColor>{L(node.exp_status)}{node.vs_sota !== null ? ` SOTA${signed(node.vs_sota)}` : ''}</Text>
            {node.go ? <Text color="magenta"> GO</Text> : ''}
          </Text>
        ))}
        {rows.length > room && <Text dimColor>… 另有 {rows.length - room} 个节点</Text>}
        <Text> </Text>
        <Text bold>待处理（{summary.attention.length}）</Text>
        {summary.attention.length === 0 && <Text dimColor>无</Text>}
        {summary.attention.slice(0, 6).map((a, i) => (
          <Text key={`a${i}`} wrap="truncate">[{a.label}] {a.text}</Text>
        ))}
        {error && <Text color="red" wrap="truncate">{error}</Text>}
        {buttons}
      </Box>
    )
  })
}

export const internals = {
  guardReason, writesDatabase, writesConfig, researchCalls, subagentCallBlock, statusText, statusLine, workerBlock, parseInit, workerNode, workerActor, parallelBlock,
  workerPrompt, platformText, uiPrompt, configCommand, carryOutUi,
}
