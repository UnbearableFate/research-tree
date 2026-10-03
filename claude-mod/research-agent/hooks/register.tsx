import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { ResearchChatEntry, ResearchNode, ResearchProject, ResearchSummary } from '../types'

const PLUGIN = 'research-agent'
const COMMAND = 'research-tree'
const PANE = 'research-progress'
const UI_PANE = 'research-ui'
const UI_AGENT = 'research-agent:ui'
const WORKER_AGENT = 'research-agent:worker'
const TOOL = 'mcp__research-agent__research_db'
const RELAY_TOOL = 'mcp__research-agent__relay_to_rld'
const POST_TOOL = 'mcp__research-agent__post_to_ui'
const CONFIRM_TOOL = 'mcp__research-agent__confirm_plan'
const VENV_PYTHON = '.venv/bin/python'
const MARKER = '.research-tree.json'
const DEFAULT_PYTHON = '3.13'
const DEPENDENCIES = ['latticedb==0.15.0', 'jsonschema>=4.26']
const READ_ONLY = /^(get|find|edges|children|history|go_candidates|latest_result|screen_seed_count|export_snapshot|verify_document)$/

const summaryRef = { plugin: 'research-agent', key: 'summary' } as const
const errorRef = { plugin: 'research-agent', key: 'error' } as const
const refreshedRef = { plugin: 'research-agent', key: 'refreshedAt' } as const
const chatRef = { plugin: 'research-agent', key: 'chat' } as const
const uiAgentRef = { plugin: 'research-agent', key: 'uiAgentId' } as const
const projectRef = { plugin: 'research-agent', key: 'project' } as const
const agentsRef = { plugin: 'research-agent', key: 'agents' } as const
const summaryAtom = atom(summaryRef, null)
const errorAtom = atom(errorRef, null)
const refreshedAtom = atom(refreshedRef, null)
const chatAtom = atom(chatRef, [])
const uiAgentAtom = atom(uiAgentRef, null)
const projectAtom = atom(projectRef, null)
const agentsAtom = atom(agentsRef, {})

type Config = { toolsDir: string; actor: string }

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
    toolsDir: String(options.toolsDir ?? '').replace(/\/+$/, ''),
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

/** Runs one of the research-agent Python tools with the session directory's .venv, in that directory. */
async function runTool($: EngineInterface, cfg: Config, script: string, args: string[], timeoutMs = 60_000) {
  const env = await venv($)
  if ('problem' in env) return { exitCode: 127, stdout: '', stderr: env.problem }
  return $.process.run([env.python, `${cfg.toolsDir}/tools/${script}`, ...args], { timeoutMs })
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
    return summary
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    await $.state.set(errorRef, `读取研究数据库失败：${message.slice(0, 300)}`)
    $.ui.status(`${COMMAND}: 读取失败`)
    return null
  }
}

/** One of the research_tree.py subcommands; its JSON answer. */
async function tree($: EngineInterface, cfg: Config, args: string[]): Promise<{ ok: boolean; result?: any; error?: string }> {
  const out = await runTool($, cfg, 'research_tree.py', args)
  try {
    return JSON.parse(out.stdout)
  } catch {
    return { ok: false, error: (out.stderr || out.stdout).trim() || `exit ${out.exitCode}` }
  }
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
    `SOTA：${s.project.sota_experiment_id ?? '未设置'}；筛选seed数：${s.counts.screen_seeds ?? '未知'}；已用资源 ${s.counts.node_hours} node·h`,
  ]
  if (s.attention.length) lines.push('待处理：', ...s.attention.map(a => `- [${a.kind}] ${a.text}`))
  return lines.join('\n')
}

/** `init <plan.md> [--python 3.13] [--id NAME]`: the plan path, the uv Python request and the project id. */
function parseInit(args: string[]): { plan: string; python: string; id?: string } | { usage: string } {
  const usage = `用法：/${COMMAND} init path/to/计划.md [--python ${DEFAULT_PYTHON}] [--id 项目ID]（项目ID默认为 uv 项目名，即当前目录名）`
  let plan: string | undefined
  let python = DEFAULT_PYTHON
  let id: string | undefined
  for (let i = 0; i < args.length; i++) {
    const [flag, inline] = args[i]!.split(/=(.*)/s, 2) as [string, string | undefined]
    if (flag === '--python' || flag === '--id') {
      const value = inline ?? args[++i]
      if (!value || value.startsWith('-')) return { usage }
      if (flag === '--python') python = value
      else id = value
    } else if (args[i]!.startsWith('-') || plan) {
      return { usage }
    } else {
      plan = args[i]
    }
  }
  return plan ? { plan, python, ...(id ? { id } : {}) } : { usage }
}

/** uv must exist; update it, make this directory a uv project for the requested Python, add the tools'
 *  dependencies. Returns what was done, line by line. */
async function setUpEnvironment($: EngineInterface, python: string): Promise<{ ok: boolean; log: string[] }> {
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
  const updated = await run(['uv', 'self', 'update'], 120_000)
  log.push(updated.exitCode === 0 ? `uv self update：${tail(updated) || '完成'}` : `uv self update 未成功（继续）：${tail(updated)}`)
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

/** Paths a write must not touch: current/superseded documents and the harness inside node worktrees. */
function guardReason(s: ResearchSummary | null | undefined, path: string): string | undefined {
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
  const reason = guardReason((await $.state.get(summaryRef)).value, path)
  return reason ? { deny: `${PLUGIN}: ${reason}` } : undefined
}

const DB_WRITE = /\b(rm|mv|cp|dd|truncate|sqlite3|shred|tee)\b|>/

/** A shell command that writes the database file directly instead of going through the tools. */
function writesDatabase(command: string): boolean {
  if (!/research_tree\.db/.test(command)) return false
  if (/\b(research_db|create_db|build_site|send_message|make_demo|research_tree)\.py\b/.test(command)) return false
  return DB_WRITE.test(command)
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

function uiPrompt(cfg: Config, project: ResearchProject | null): string {
  const docs = project ? `${project.root}/docs` : '（尚无项目）'
  return `你是研究项目的 User Interface（UI）agent，运行在 Claude Code 的“研究对话”窗口里，直接与用户对话。Research Leader（RLD）是主会话，负责研究管理与执行；你不是RLD的worker。

职责：
1. 理解和澄清用户意图；区分讨论、问题、偏好、明确决定和行动指令；只追问会改变执行的缺口。
2. 回答进度与结果问题：依据共享记录（每条消息附带的项目摘要、research_db 只读方法 get/find/history/latest_result/go_candidates、文档库中的文档），注明数据版本；不自行查询作业，不调度worker。
3. 用户的指令（停止、暂停、改变目标或范围、授权、约束、放弃某个节点等）：先写用户指令文档 ${docs}/instructions/UI-<四位序号>.v1.md，内容为用户原话（逐字）、你的理解、类型、生效范围、取代的旧指令；再用 mcp__research-agent__research_db 调用 register_document（doc_type 为 user_instruction，about 填相关的节点或项目ID）和 set_document_current；最后用 relay_to_rld（type=instruction，docs 填该文档相对 docs/ 的路径）转交RLD。指令必须先登记再转交。
4. 立项计划等待用户确认时（项目阶段为“等待用户确认”），用户明确表示同意，就用 confirm_plan 记录确认（words 填用户原话）；用户提出修改意见时，按第3条登记为指令转交RLD，不要确认。
5. 需要RLD回答的问题用 relay_to_rld（type=question）；普通讨论和偏好记在回复里，到决策点再合并转交，不逐句打扰RLD。
6. 不派发、暂停或重分配worker，不替RLD作研究决定，不修改研究数据库中的节点、实验和项目状态。
7. 用中文简洁回复，说明哪些是已记录的事实、哪些是你的理解。

规则文件：${cfg.toolsDir}/reusable-research-agent-rules-20261003.md；文档库：${docs}。`
}

const WORKER_PROMPT = `你是 research-tree 项目的 worker，由 Research Leader（RLD）委派；你的身份（worker/<id>）写在任务说明开头。
- 只在认领的任务范围内工作：先用 mcp__research-agent__research_db 读取任务（get）和请求文档，再用 update_task 把任务改为 in_progress。
- 代码改动只在任务指定的仓库分支或worktree中进行并提交；除根节点框架任务外，不改动冻结的实验框架与统计代码。
- 在 Miyabi 上，测试、训练、推理等计算类工作必须在计算节点运行（miyabi-pbs-cmd 技能）。
- 实验、运行与判定只通过 research_db 登记（create_experiment、create_run、update_run、record_verdict），不编造数字；工程失败如实记录，不当作科学结论。
- 交付：写 tasks/<任务ID>/delivery.v1.md（实际做了什么、产出的文档与实验ID、未完成项和未知项），登记并设为现行，再 update_task(status=delivered, delivery_doc_id)；最终回复只给简短说明和文档引用。
- 不自行改变研究目标、选择新的研究分支或接管他人任务；范围变化交RLD。`

function planningPrompt(project: ResearchProject, cfg: Config): string {
  const instr = project.plan_instruction
  return `/${COMMAND} init 已在 ${project.root} 建立研究项目 ${project.project_id}（数据库 ${project.db}）。用户的研究目标与初始方案已逐字登记为用户指令 ${instr.doc_id}（docs/${instr.path}，原文件 ${project.plan}）。

请作为 Research Leader 完成立项规划。本阶段不要启动 worker，也不要提交任何作业：
1. 读原文。写 docs/project/goal.v1.md（研究目标）和 docs/project/min-setup.v1.md（最小实验设定：模型、数据、训练量、评测、主指标及优劣方向、其他比较指标、3个统一seed、单次运行上限与筛选预算、计划的实验框架与判定规则）；用 research_db 登记（register_document）并设为现行。
2. create_project：id 为 ${project.project_id}，repo_path 为本项目代码仓库的绝对路径（原文未给出就在 ${project.root}/../.. 下合适的位置新建 git 仓库），其余参数取自最小实验设定。
3. 为原文中的每个初始假说检索并缓存相关研究（docs/literature/，每个节点至少3篇，原文缓存到 cache/literature/），写假说文档（创建理由、计划的代码改动、实验计划），create_hypothesis 建初始节点（状态为待验证）。
4. 根节点：写 docs/tasks/T-0001/request.v1.md，说明要实现的实验骨架与统计代码，以及要运行的SOTA基线（baselines）方案；create_task(kind=harness, assignee_role=worker)，先不指派。
5. 写 docs/project/reports/init-plan.v1.md 汇总以上（目标、设定、初始节点、基线与根节点方案、预计资源），登记并设为现行，然后调用 post_to_ui(type=confirm_request, docs=["project/reports/init-plan.v1.md"]) 请用户在研究对话窗口确认。
用户确认之前 mod 会拒绝启动 worker。规则文件：${cfg.toolsDir}/reusable-research-agent-rules-20261003.md。`
}

function startPrompt(project: ResearchProject, confirmation: { doc_id: string; path: string }): string {
  return `用户已确认 ${project.project_id} 的立项计划（用户指令 ${confirmation.doc_id}，docs/${confirmation.path}）。
请开始实现根节点：用 research_db 的 update_task 把根节点任务（kind=harness，通常是 T-0001）指派给 worker（例如 assignee_id=w1），然后用 Agent 工具启动 subagent_type="${WORKER_AGENT}" 的子代理，任务说明以“你是 worker/w1”开头，写明任务ID、请求文档和交付要求。worker 交付后，按规则审核框架与基线结果并冻结框架（update_project harness_ref/harness_paths），设置SOTA基线后再推进各节点。`
}

const WORKFLOW = `## research-tree 工作流（由 research-agent mod 注入）
- 研究项目的状态、节点、实验、判定和决定都在当前目录 research/<项目ID>/ 的 LatticeDB 研究数据库里；只能通过 ${'`'}${TOOL}${'`'} 工具（或 tools/research_db.py）读写，不要直接改数据库文件。
- 实验优先：每个节点都要有实质性代码改动和实验；节点结论跟随冻结统计代码的判定（无提升→可消灭，优于父节点→可拓展，优于SOTA→RLD复核新颖性与理论正确性）。
- 已生效的文档不可修改，改动写新版本；节点代码中不能改动冻结框架。
- 立项计划须经用户确认后才能启动 ${WORKER_AGENT} 子代理；需要用户决定的事用 post_to_ui，用户的话经 UI 登记后由 relay_to_rld 送达。
- /${COMMAND} 查看进度；/${COMMAND} ui 打开研究对话窗口；/${COMMAND} pane 打开进度面板；/${COMMAND} build 生成离线进度页面。`

// ---------------------------------------------------------------------------
// UI window
// ---------------------------------------------------------------------------

async function say($: EngineInterface, role: ResearchChatEntry['role'], text: string): Promise<void> {
  await update($, chatAtom, list => [...(list ?? []), { role, text, at: now() }].slice(-200))
}

/** Hands the person's message to a fresh UI subagent run with the recent conversation and the project view. */
async function askUi($: EngineInterface, cfg: Config, text: string): Promise<void> {
  const message = text.trim()
  if (!message) return
  if ((await $.state.get(uiAgentRef)).value) {
    await say($, 'note', 'UI 还在处理上一条消息，请稍候。')
    return
  }
  const history = ((await $.state.get(chatRef)).value ?? []).slice(-12)
  await say($, 'user', message)
  const project = (await $.state.get(projectRef)).value ?? null
  const summary = (await $.state.get(summaryRef)).value
  const prompt = [
    uiPrompt(cfg, project),
    `## 当前项目\n${project ? `${project.project_id}，阶段：${L(project.phase)}` : '当前目录没有研究项目'}` +
      (summary ? `\n${statusText(summary, project)}` : ''),
    history.length ? `## 最近的对话\n${history.map(h => `[${h.role}] ${h.text}`).join('\n')}` : '',
    `## 用户的新消息\n${message}`,
  ].filter(Boolean).join('\n\n')
  const spawned = await $.agent.spawn({ subagentType: UI_AGENT, prompt, description: 'UI 回复用户' })
  if (spawned.deny !== undefined || !spawned.agentId) {
    await say($, 'note', `无法启动 UI agent：${spawned.deny ?? `未返回 agentId（${JSON.stringify(spawned).slice(0, 200)}）`}`)
    return
  }
  await $.state.set(uiAgentRef, spawned.agentId)
}

/** Logs a message through tools/send_message.py (native channel); returns the logged line or the error. */
async function logMessage($: EngineInterface, cfg: Config, args: string[]) {
  const project = (await $.state.get(projectRef)).value
  if (!project) return { ok: false, line: '', error: '当前目录没有研究项目' }
  const out = await runTool($, cfg, 'send_message.py', ['--root', project.root, '--channel', 'native', ...args])
  return { ok: out.exitCode === 0, line: out.stdout.trim(), error: (out.stderr || out.stdout).trim() }
}

/** The user's confirmation of the plan: registered verbatim, phase confirmed, the RLD told to start. */
async function confirmPlan($: EngineInterface, cfg: Config, words: string): Promise<string> {
  const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
  if (!project) return `当前目录没有研究项目；先运行 /${COMMAND} init <计划.md>。`
  if (project.phase === 'confirmed') return '立项计划已经确认过。'
  if (project.phase !== 'awaiting_confirmation') return 'RLD 还没有提交立项计划，暂时无需确认。'
  const registered = await tree($, cfg, ['instruction', '--text', words, '--kind', '确认（立项计划）',
    '--understanding', '用户确认RLD提交的立项计划，同意启动worker实现根节点。', '--about', project.project_id])
  if (!registered.ok) return `确认未能登记：${registered.error}`
  const phased = await tree($, cfg, ['phase', '--set', 'confirmed'])
  if (!phased.ok) return `确认已登记，但阶段未能更新：${phased.error}`
  await loadProject($)
  const logged = await logMessage($, cfg, ['--from', 'ui/ui', '--to', 'rld/main', '--type', 'instruction',
    '--text', '用户确认立项计划，请启动worker实现根节点。', '--docs', registered.result.path, '--about', project.project_id])
  await $.prompt.submit({ text: startPrompt(project, registered.result) + (logged.ok ? `\n消息记录：${logged.line}` : '') })
  await say($, 'note', `已登记用户确认（${registered.result.doc_id}），RLD 将启动 worker 实现根节点。`)
  return `已确认立项计划（${registered.result.doc_id}）；RLD 将启动 worker 实现根节点。`
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
      description: '研究树：init <计划.md> [--python 3.13] [--id 项目ID]、confirm、status（默认）、ui、pane、refresh、build、check',
    })
    await $.tool.register({
      name: 'research_db',
      description:
        'Call one method of the research database API (tools/research_db.py) on the research project of the ' +
        'current directory: reads (get, find, edges, children, history, go_candidates, latest_result, ' +
        'screen_seed_count, export_snapshot) and writes (register_document, set_document_current, create_project, ' +
        'create_hypothesis, create_task, create_experiment, update_run, record_verdict, decide, ...). The API ' +
        'enforces the workflow rules and permissions and answers JSON {ok, result} or {ok: false, error}.',
      inputSchema: {
        type: 'object',
        properties: {
          method: { type: 'string', description: 'ResearchDB method name, e.g. "find" or "decide"' },
          kwargs: { type: 'object', description: 'Keyword arguments of the method as JSON' },
          actor: { type: 'string', description: '<role>/<agent-id>; the UI and worker runs are fixed by the mod' },
        },
        required: ['method'],
      },
    })
    await $.tool.register({
      name: 'relay_to_rld',
      description:
        'UI agent only: send one message to the Research Leader (the main session). It is logged with ' +
        'tools/send_message.py (validated: short text, registered versioned docs) and queued as a prompt for the RLD.',
      inputSchema: {
        type: 'object',
        properties: {
          type: { type: 'string', enum: ['instruction', 'question', 'reply', 'alert'] },
          text: { type: 'string', description: 'Short note, at most 200 characters' },
          docs: { type: 'array', items: { type: 'string' }, description: 'Versioned paths relative to docs/' },
          about: { type: 'array', items: { type: 'string' }, description: 'Database entity ids' },
        },
        required: ['type', 'text'],
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
          docs: { type: 'array', items: { type: 'string' }, description: 'Versioned paths relative to docs/' },
        },
        required: ['type', 'text'],
      },
    })
    await $.tool.register({
      name: 'confirm_plan',
      description: 'UI agent only: record that the person confirmed the start-up plan, with their words verbatim.',
      inputSchema: {
        type: 'object',
        properties: { words: { type: 'string', description: "The person's confirmation, verbatim" } },
        required: ['words'],
      },
    })
    await $.agent.register({
      name: 'ui',
      description: 'research-tree 的 User Interface：在“研究对话”窗口与用户对话（只由 research-agent mod 启动）',
      prompt: uiPrompt(cfg, null),
      tools: ['Read', 'Write', 'Bash', TOOL, RELAY_TOOL, CONFIRM_TOOL],
      model: 'inherit',
    })
    await $.agent.register({
      name: 'worker',
      description: 'research-tree 的 worker：实现被委派的研究任务（根节点框架、节点代码与实验），通过 research_db 登记与交付',
      prompt: WORKER_PROMPT,
      model: 'inherit',
    })
    const started = await next(e)
    if (await loadProject($)) await refresh($, cfg)
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
    const named = /worker\/([A-Za-z0-9_.]+)/.exec(e.prompt)?.[1]
    const known = Object.values((await $.state.get(agentsRef)).value ?? {})
    let id = named
    for (let n = 1; !id; n++) if (!known.includes(`worker/w${n}`)) id = `w${n}`
    const spawned = await next(named ? e : { ...e, prompt: `你是 worker/${id}。\n\n${e.prompt}` })
    if (spawned.agentId) {
      const agentId = spawned.agentId
      await update($, agentsAtom, map => ({ ...(map ?? {}), [agentId]: `worker/${id}` }))
    }
    return spawned
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId && e.agentId === (await $.state.get(uiAgentRef)).value) {
      await $.state.set(uiAgentRef, null)
      await say($, 'ui', e.answer.trim() || (e.isAborted ? '（UI 被中断）' : '（UI 没有给出文字回复）'))
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
      const env = await setUpEnvironment($, parsed.python)
      if (!env.ok) return { text: env.log.join('\n') }
      const made = await tree($, cfg, ['init', parsed.plan, ...(parsed.id ? ['--project-id', parsed.id] : [])])
      if (!made.ok) return { text: [...env.log, `初始化失败：${made.error}`].join('\n') }
      const project = await loadProject($)
      if (!project) return { text: [...env.log, '初始化完成，但读取不到 .research-tree.json。'].join('\n') }
      await refresh($, cfg)
      await $.ui.open({ id: UI_PANE, title: '研究对话（UI）' })
      await say($, 'note', `已建立 ${project.project_id}；计划已登记为 ${project.plan_instruction.doc_id}。RLD 正在整理立项计划，完成后会在这里请你确认。`)
      await $.prompt.submit({ text: planningPrompt(project, cfg) })
      return {
        text: [...env.log, `已在 ${project.root} 建立研究项目 ${project.project_id}：目录、数据库、通信登记表已就绪，` +
          `计划原文登记为 ${project.plan_instruction.doc_id}。研究对话窗口已打开；RLD 将据计划建立目标、初始节点和根节点方案，并请你确认。`].join('\n'),
      }
    }
    if (sub === 'confirm') {
      return { text: await confirmPlan($, cfg, words.slice(1).join(' ') || `/${COMMAND} confirm`) }
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
      return { text: `未知子命令 ${sub}；可用：init、confirm、status、ui、pane、refresh、build、check` }
    }
    await loadProject($)
    const summary = await refresh($, cfg)
    if (!summary) return { text: (await $.state.get(errorRef)).value ?? '没有可显示的研究进度。' }
    return { text: statusText(summary, (await $.state.get(projectRef)).value) }
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    const input = e as unknown as { method?: unknown; kwargs?: unknown; actor?: unknown }
    if (typeof input.method !== 'string' || !/^[a-z_]+$/.test(input.method)) {
      return { result: 'research_db: method must be a ResearchDB method name', isError: true as const }
    }
    const project = (await $.state.get(projectRef)).value ?? (await loadProject($))
    if (!project) return { result: `当前目录没有研究项目：运行 /${COMMAND} init <计划.md>`, isError: true as const }
    // The UI and worker runs act as themselves whatever they pass.
    const fixed = e.agentId === undefined ? undefined
      : e.agentId === (await $.state.get(uiAgentRef)).value ? 'ui/ui'
      : (await $.state.get(agentsRef)).value?.[e.agentId]
    const actor = fixed ?? (typeof input.actor === 'string' && input.actor ? input.actor : cfg.actor)
    const out = await runTool($, cfg, 'research_db.py', [
      '--db', project.db, '--actor', actor, input.method, JSON.stringify(input.kwargs ?? {}),
    ])
    if (!READ_ONLY.test(input.method)) await refresh($, cfg)
    const text = (out.stdout || out.stderr).trim()
    return out.exitCode === 0 ? { result: text } : { result: text || `exit ${out.exitCode}`, isError: true as const }
  })

  on('tool.call', { tool: RELAY_TOOL }, async ($, e) => {
    const input = e as unknown as { type?: string; text?: string; docs?: string[]; about?: string[] }
    const args = ['--from', 'ui/ui', '--to', 'rld/main', '--type', String(input.type), '--text', String(input.text ?? '')]
    if (input.docs?.length) args.push('--docs', ...input.docs)
    if (input.about?.length) args.push('--about', ...input.about)
    const logged = await logMessage($, cfg, args)
    if (!logged.ok) return { result: `relay_to_rld 被拒绝：${logged.error}`, isError: true as const }
    await $.prompt.submit({
      text: `来自研究对话窗口（UI）的消息：\n${logged.line}\n请按 research-tree 规则处理：先读取引用的文档；需要用户决定时用 post_to_ui 回复。`,
    })
    await say($, 'note', `已转交RLD：${input.text}`)
    return { result: `已记录并转交RLD：${logged.line}` }
  })

  on('tool.call', { tool: POST_TOOL }, async ($, e) => {
    const input = e as unknown as { type?: string; text?: string; docs?: string[] }
    let logged = ''
    if (input.docs?.length && input.type !== 'notice') {
      const args = ['--from', 'rld/main', '--to', 'ui/ui', '--type', String(input.type), '--text', String(input.text ?? ''),
        '--docs', ...input.docs]
      const out = await logMessage($, cfg, args)
      if (!out.ok) return { result: `post_to_ui 被拒绝：${out.error}`, isError: true as const }
      logged = out.line
    }
    const project = (await $.state.get(projectRef)).value
    if (input.type === 'confirm_request' && project?.phase === 'planning') {
      const phased = await tree($, cfg, ['phase', '--set', 'awaiting_confirmation'])
      if (phased.ok) await loadProject($)
    }
    const refs = input.docs?.length ? `\n引用：${input.docs.join('，')}` : ''
    await say($, 'rld', `${input.type === 'confirm_request' ? '【需要你决定】' : ''}${input.text ?? ''}${refs}` +
      (input.type === 'confirm_request' ? `\n同意请在此回复，或运行 /${COMMAND} confirm。` : ''))
    $.ui.toast(input.type === 'confirm_request' ? 'RLD 需要你的决定，见“研究对话”窗口' : 'RLD 在“研究对话”窗口留言')
    void $.ui.open({ id: UI_PANE, title: '研究对话（UI）' })
    return { result: logged ? `已发送到UI窗口并记录：${logged}` : '已发送到UI窗口。' }
  })

  on('tool.call', { tool: CONFIRM_TOOL }, async ($, e) => {
    if (!e.agentId || e.agentId !== (await $.state.get(uiAgentRef)).value) {
      return { result: 'confirm_plan 只能由研究对话窗口的 UI agent 在用户同意时调用。', isError: true as const }
    }
    const words = String((e as unknown as { words?: string }).words ?? '').trim()
    if (!words) return { result: 'confirm_plan 需要用户的原话（words）。', isError: true as const }
    return { result: await confirmPlan($, cfg, words) }
  })

  on('tool.call', { tool: 'Edit' }, async ($, e, next) => (await guard($, e.file_path)) ?? next(e))
  on('tool.call', { tool: 'Write' }, async ($, e, next) => (await guard($, e.file_path)) ?? next(e))
  on('tool.call', { tool: 'NotebookEdit' }, async ($, e, next) => (await guard($, e.notebook_path)) ?? next(e))

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (writesDatabase(e.command)) {
      return { deny: `${PLUGIN}: 不要直接改动研究数据库文件；通过 research_db 工具或 tools/research_db.py 写入，它会检查规则并记录决定。` }
    }
    const ran = await next(e)
    if (/\b(research_db|send_message|make_demo|build_site|research_tree)\.py\b/.test(e.command)) await refresh($, cfg)
    return ran
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    const project = (await $.state.get(projectRef)).value
    const summary = (await $.state.get(summaryRef)).value
    const status = project
      ? `\n\n当前项目：${project.project_id}（${L(project.phase)}，${project.root}）` + (summary ? `\n${statusText(summary, project)}` : '')
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
    walk(summary.project.id, 0)
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
          <Text key={`a${i}`} wrap="truncate">[{a.kind}] {a.text}</Text>
        ))}
        {error && <Text color="red" wrap="truncate">{error}</Text>}
        {buttons}
      </Box>
    )
  })
}

export const internals = { guardReason, writesDatabase, statusText, statusLine, workerBlock, parseInit }
