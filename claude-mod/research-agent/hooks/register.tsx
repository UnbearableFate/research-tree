import { atom, read, update } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { ResearchChatEntry, ResearchNode, ResearchSummary } from '../types'

const PLUGIN = 'research-agent'
const PANE = 'research-progress'
const TOOL = 'mcp__research-agent__research_db'
const summaryRef = { plugin: 'research-agent', key: 'summary' } as const
const errorRef = { plugin: 'research-agent', key: 'error' } as const
const refreshedRef = { plugin: 'research-agent', key: 'refreshedAt' } as const
const chatRef = { plugin: 'research-agent', key: 'chat' } as const
const uiAgentRef = { plugin: 'research-agent', key: 'uiAgentId' } as const
const summaryAtom = atom(summaryRef, null)
const chatAtom = atom(chatRef, [])
const uiAgentAtom = atom(uiAgentRef, null)
const UI_PANE = 'research-ui'
const UI_AGENT = 'research-agent:ui'
const RELAY_TOOL = 'mcp__research-agent__relay_to_rld'
const POST_TOOL = 'mcp__research-agent__post_to_ui'
const errorAtom = atom(errorRef, null)
const refreshedAtom = atom(refreshedRef, null)

type Config = { toolsDir: string; projectDb: string; python: string; actor: string }

const LABEL: Record<string, string> = {
  pending: '待验证', verifying: '验证中', expandable: '可拓展', prunable: '可消灭',
  todo: '未开始', running: '进行中', no_gain: '无提升', beats_parent: '优于父节点', beats_sota: '优于SOTA',
  close: '差不多', needs_rld: '需要RLD复核', active: '进行中', go: 'GO', not_go: 'NOT GO', stopped: '已停止',
}
const STATUS_COLOR: Record<string, string> = {
  pending: 'gray', verifying: 'yellow', expandable: 'green', prunable: 'red',
}
const L = (k: string | null | undefined) => (k ? (LABEL[k] ?? k) : '未知')
const signed = (x: number | null) => (x === null ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(3)}`)

function config(options: PluginOptions): Config {
  const toolsDir = String(options.toolsDir ?? '').replace(/\/+$/, '')
  return {
    toolsDir,
    projectDb: String(options.projectDb ?? ''),
    python: String(options.python || `${toolsDir}/.venv/bin/python`),
    actor: String(options.actor || 'rld/main'),
  }
}

/** Runs one of the project's Python tools; the tools hold every rule, the mod only calls them. */
async function runTool($: EngineInterface, cfg: Config, script: string, args: string[], timeoutMs = 60_000) {
  return $.process.run([cfg.python, `${cfg.toolsDir}/tools/${script}`, ...args], { cwd: cfg.toolsDir, timeoutMs })
}

async function refresh($: EngineInterface, cfg: Config): Promise<ResearchSummary | null> {
  if (!cfg.projectDb) {
    await $.state.set(errorRef, 'projectDb 未配置：在 /config 中设置 research-agent 的项目数据库路径')
    return null
  }
  try {
    const out = await runTool($, cfg, 'build_site.py', ['--db', cfg.projectDb, '--summary'], 30_000)
    if (out.exitCode !== 0) throw new Error(out.stderr.trim() || `exit ${out.exitCode}`)
    const summary = JSON.parse(out.stdout) as ResearchSummary
    await $.state.set(summaryRef, summary)
    await $.state.set(errorRef, null)
    await $.state.set(refreshedRef, new Date().toISOString().slice(0, 19).replace('T', ' '))
    $.ui.status(statusLine(summary))
    return summary
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    await $.state.set(errorRef, `读取研究数据库失败：${message.slice(0, 300)}`)
    $.ui.status('research: 读取失败')
    return null
  }
}

function statusLine(s: ResearchSummary): string {
  const nodes = s.nodes.length
  return `research ${s.project.id} · v${s.meta.data_version} · 节点${nodes} · 优于SOTA ${s.counts.exp_status.beats_sota ?? 0} · GO候选 ${s.counts.go} · 待处理 ${s.attention.length}`
}

function statusText(s: ResearchSummary): string {
  const byStatus = Object.entries(s.counts.status).map(([k, v]) => `${L(k)} ${v}`).join('，')
  const go = s.nodes.filter(n => n.go).map(n => `${n.id} ${n.title}`)
  const lines = [
    `${s.project.title}（${s.project.id}，${L(s.project.status)}，data_version ${s.meta.data_version}）`,
    `节点：${byStatus || '无'}；GO候选：${go.length ? go.join('；') : '无'}`,
    `SOTA：${s.project.sota_experiment_id ?? '未设置'}；筛选seed数：${s.counts.screen_seeds ?? '未知'}；已用资源 ${s.counts.node_hours} node·h`,
  ]
  if (s.attention.length) lines.push('待处理：', ...s.attention.map(a => `- [${a.kind}] ${a.text}`))
  return lines.join('\n')
}

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

const docsRoot = (cfg: Config) => cfg.projectDb.replace(/\/[^/]+$/, '') + '/docs'
const researchRoot = (cfg: Config) => cfg.projectDb.replace(/\/[^/]+$/, '')
const now = () => new Date().toISOString().slice(0, 19).replace('T', ' ')

function uiPrompt(cfg: Config): string {
  return `你是研究项目的 User Interface（UI）agent，运行在 Claude Code 的“研究对话”窗口里，直接与用户对话。Research Leader（RLD）是主会话，负责研究管理与执行；你不是RLD的worker。

职责：
1. 理解和澄清用户意图；区分讨论、问题、偏好、明确决定和行动指令；只追问会改变执行的缺口。
2. 回答进度与结果问题：依据共享记录（每条消息附带的项目摘要、research_db 只读方法 get/find/history/latest_result/go_candidates、文档库中的文档），注明数据版本；不自行查询作业，不调度worker。
3. 用户的指令（停止、暂停、改变目标或范围、授权、约束、放弃某个节点等）：先写用户指令文档 ${docsRoot(cfg)}/instructions/UI-<四位序号>.v1.md，内容为用户原话（逐字）、你的理解、类型、生效范围、取代的旧指令；再用 mcp__research-agent__research_db 调用 register_document（doc_type 为 user_instruction，about 填相关的节点或项目ID）和 set_document_current；最后用 relay_to_rld（type=instruction，docs 填该文档相对 docs/ 的路径）转交RLD。指令必须先登记再转交。
4. 需要RLD回答的问题用 relay_to_rld（type=question）；普通讨论和偏好记在回复里，到决策点再合并转交，不逐句打扰RLD。
5. 不派发、暂停或重分配worker，不替RLD作研究决定，不修改研究数据库中的节点、实验和项目状态。
6. 用中文简洁回复，说明哪些是已记录的事实、哪些是你的理解。

规则文件：${cfg.toolsDir}/reusable-research-agent-rules-20261003.md；文档库：${docsRoot(cfg)}。`
}

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
  const summary = (await $.state.get(summaryRef)).value
  const prompt = [
    uiPrompt(cfg),
    summary ? `## 当前项目摘要\n${statusText(summary)}` : '## 当前项目摘要\n（尚未读取研究数据库）',
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
  const out = await runTool($, cfg, 'send_message.py', ['--root', researchRoot(cfg), '--channel', 'native', ...args])
  return { ok: out.exitCode === 0, line: out.stdout.trim(), error: (out.stderr || out.stdout).trim() }
}

const DB_WRITE = /\b(rm|mv|cp|dd|truncate|sqlite3|shred|tee)\b|>/

/** A shell command that writes the database file directly instead of going through the tools. */
function writesDatabase(command: string): boolean {
  if (!/research_tree\.db/.test(command)) return false
  if (/\b(research_db|create_db|build_site|send_message|make_demo)\.py\b/.test(command)) return false
  return DB_WRITE.test(command)
}

const WORKFLOW = `## research-agent 工作流（由 research-agent mod 注入）
- 研究项目的状态、节点、实验、判定和决定都在 LatticeDB 研究数据库里；只能通过 ${'`'}mcp__research-agent__research_db${'`'} 工具（或 tools/research_db.py）读写，不要直接改数据库文件。
- 实验优先：每个节点都要有实质性代码改动和实验；节点结论跟随冻结统计代码的判定（无提升→可消灭，优于父节点→可拓展，优于SOTA→RLD复核新颖性与理论正确性）。
- 已生效的文档不可修改，改动写新版本；节点代码中不能改动冻结框架。
- agent 间消息用 tools/send_message.py：短说明加已登记文档的引用。
- /research 查看进度，/research pane 打开进度面板，/research build 生成离线进度页面。`

export const register: Register = (on, options) => {
  const cfg = config(options)
  registerUiPane(on, cfg)

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'research',
      description: '研究进度与对话：status（默认）、ui、pane、refresh、build、check',
    })
    await $.tool.register({
      name: 'research_db',
      description:
        'Call one method of the research database API (tools/research_db.py) on the configured project: ' +
        'reads (get, find, edges, children, history, go_candidates, latest_result, screen_seed_count, export_snapshot) ' +
        'and writes (register_document, set_document_current, create_hypothesis, create_experiment, update_run, ' +
        'record_verdict, decide, ...). The API enforces the workflow rules and permissions and answers JSON ' +
        '{ok, result} or {ok: false, error}.',
      inputSchema: {
        type: 'object',
        properties: {
          method: { type: 'string', description: 'ResearchDB method name, e.g. "find" or "decide"' },
          kwargs: { type: 'object', description: 'Keyword arguments of the method as JSON' },
          actor: { type: 'string', description: '<role>/<agent-id>; defaults to the configured actor' },
        },
        required: ['method'],
      },
    })
    await $.agent.register({
      name: 'ui',
      description: 'research-agent 的 User Interface：在“研究对话”窗口与用户对话（只由 research-agent mod 启动）',
      prompt: uiPrompt(cfg),
      tools: ['Read', 'Write', 'Bash', TOOL, RELAY_TOOL],
      model: 'inherit',
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
        'RLD: post a message into the research UI window the person reads, e.g. a decision you need from them ' +
        '(type confirm_request, with the registered document that explains it) or a reply to a UI question.',
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
    const started = await next(e)
    await refresh($, cfg)
    return started
  })

  // The UI agent is the window's own: the main model never delegates to it.
  on('agent.offer', { agent: UI_AGENT }, () => ({ isOffered: false }))

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    const running = (await $.state.get(uiAgentRef)).value
    if (e.agentId && e.agentId === running) {
      await $.state.set(uiAgentRef, null)
      await say($, 'ui', e.answer.trim() || (e.isAborted ? '（UI 被中断）' : '（UI 没有给出文字回复）'))
    }
    return done
  })

  on('tool.call', { tool: RELAY_TOOL }, async ($, e) => {
    const input = e as unknown as { type?: string; text?: string; docs?: string[]; about?: string[] }
    const args = ['--from', 'ui/ui', '--to', 'rld/main', '--type', String(input.type), '--text', String(input.text ?? '')]
    if (input.docs?.length) args.push('--docs', ...input.docs)
    if (input.about?.length) args.push('--about', ...input.about)
    const logged = await logMessage($, cfg, args)
    if (!logged.ok) return { result: `relay_to_rld 被拒绝：${logged.error}`, isError: true as const }
    await $.prompt.submit({
      text: `来自研究对话窗口（UI）的消息：\n${logged.line}\n请按 research-agent 规则处理：先读取引用的文档；需要用户决定时用 post_to_ui 回复。`,
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
    const refs = input.docs?.length ? `\n引用：${input.docs.join('，')}` : ''
    await say($, 'rld', `${input.type === 'confirm_request' ? '【需要你决定】' : ''}${input.text ?? ''}${refs}`)
    $.ui.toast(input.type === 'confirm_request' ? 'RLD 需要你的决定，见“研究对话”窗口' : 'RLD 在“研究对话”窗口留言')
    void $.ui.open({ id: UI_PANE, title: '研究对话（UI）' })
    return { result: logged ? `已发送到UI窗口并记录：${logged}` : '已发送到UI窗口。' }
  })

  on('command.run', { command: 'research' }, async ($, e) => {
    const sub = e.args.trim().split(/\s+/)[0] || 'status'
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
      const out = await runTool($, cfg, 'build_site.py', ['--db', cfg.projectDb, ...(sub === 'check' ? ['--check'] : [])])
      await refresh($, cfg)
      return { text: (out.stdout || out.stderr).trim() || `exit ${out.exitCode}` }
    }
    if (sub !== 'status' && sub !== 'refresh') {
      return { text: `未知子命令 ${sub}；可用：status、ui、pane、refresh、build、check` }
    }
    const summary = await refresh($, cfg)
    if (!summary) return { text: (await $.state.get(errorRef)).value ?? '没有可显示的研究进度。' }
    return { text: statusText(summary) }
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    const input = e as unknown as { method?: unknown; kwargs?: unknown; actor?: unknown }
    if (typeof input.method !== 'string' || !/^[a-z_]+$/.test(input.method)) {
      return { result: 'research_db: method must be a ResearchDB method name', isError: true as const }
    }
    const uiRun = (await $.state.get(uiAgentRef)).value
    const actor = e.agentId && e.agentId === uiRun
      ? 'ui/ui'
      : typeof input.actor === 'string' && input.actor ? input.actor : cfg.actor
    const out = await runTool($, cfg, 'research_db.py', [
      '--db', cfg.projectDb, '--actor', actor, input.method, JSON.stringify(input.kwargs ?? {}),
    ])
    if (!input.method.match(/^(get|find|edges|children|history|go_candidates|latest_result|screen_seed_count|export_snapshot|verify_document)$/)) {
      await refresh($, cfg)
    }
    const text = (out.stdout || out.stderr).trim()
    return out.exitCode === 0 ? { result: text } : { result: text || `exit ${out.exitCode}`, isError: true as const }
  })

  on('tool.call', { tool: 'Edit' }, async ($, e, next) => (await guard($, e.file_path)) ?? next(e))
  on('tool.call', { tool: 'Write' }, async ($, e, next) => (await guard($, e.file_path)) ?? next(e))
  on('tool.call', { tool: 'NotebookEdit' }, async ($, e, next) => (await guard($, e.notebook_path)) ?? next(e))

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (writesDatabase(e.command)) {
      return { deny: `${PLUGIN}: 不要直接改动研究数据库文件；通过 research_db 工具或 tools/research_db.py 写入，它会检查规则并记录决定。` }
    }
    const ran = await next(e)
    if (/\b(research_db|send_message|make_demo|build_site)\.py\b/.test(e.command)) await refresh($, cfg)
    return ran
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    const summary = (await $.state.get(summaryRef)).value
    const status = summary ? `\n\n当前项目：${statusText(summary)}` : ''
    return { sections: [...composed.sections, { id: `${PLUGIN}:workflow`, text: WORKFLOW + status, scope: 'session' as const }] }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const summary = await read($, summaryAtom)
    const error = await read($, errorAtom)
    const refreshedAt = await read($, refreshedAtom)
    const width = e.props.bodyColumns ?? 60
    const buttons = (
      <Box flexDirection="row" gap={1}>
        <Button key="refresh" hotkey="r" onPress={() => void refresh($, cfg)}>刷新</Button>
        <Button key="build" hotkey="b" onPress={async () => {
          const out = await runTool($, cfg, 'build_site.py', ['--db', cfg.projectDb])
          $.ui.toast((out.stdout || out.stderr).trim().slice(0, 200))
          await refresh($, cfg)
        }}>生成页面</Button>
      </Box>
    )
    if (!summary) {
      return (
        <Box flexDirection="column">
          <Text color="red">{error ?? '尚未读取研究数据库。'}</Text>
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
          {summary.project.id} · {L(summary.project.status)} · v{summary.meta.data_version} · 刷新于 {refreshedAt ?? '—'}
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
    const room = Math.max(3, (e.viewport?.rows ?? 30) - 8)
    return (
      <Box flexDirection="column">
        <Text dimColor wrap="truncate">与 UI agent 对话；指令会先登记为文档再转交 RLD。</Text>
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

export const internals = { guardReason, writesDatabase, statusText, statusLine }
