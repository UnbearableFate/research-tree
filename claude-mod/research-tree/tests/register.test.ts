import { expect, test } from 'claude-code/testing'

import { internals, register } from '../hooks/register'
import type { ResearchSummary } from '../types'

const PANE_PROPS = {
  title: '研究对话（UI）', isFocused: true, bodyColumns: 80, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 30 }, view: {},
}
const UI = { plugin: 'research-tree', component: 'Pane' as const, requestId: 'research-ui', props: PANE_PROPS }

const SUMMARY = {
  guards: {
    frozen_docs: ['/r/P-x/docs/hypotheses/H-0001/hypothesis.v1.md'],
    harness: ['/r/worktrees/H-0001/harness'],
  },
} as unknown as ResearchSummary

test('frozen documents and the frozen harness are guarded, other paths are not', () => {
  expect(internals.guardReason(SUMMARY, '/r/P-x/docs/hypotheses/H-0001/hypothesis.v1.md')).toContain('新版本')
  expect(internals.guardReason(SUMMARY, '/r/worktrees/H-0001/harness/stats.py')).toContain('冻结的实验框架')
  expect(internals.guardReason(SUMMARY, '/r/worktrees/H-0001/methods/new.py')).toBeUndefined()
  expect(internals.guardReason(SUMMARY, '/r/worktrees/H-0001/harness-notes.md')).toBeUndefined()
  expect(internals.guardReason(null, '/anything')).toBeUndefined()
})

test('only direct writes to a project database count as database writes', () => {
  const db = '/work/study/research/my-study/research_tree.db'
  expect(internals.writesDatabase('rm demo/research/P-x/research_tree.db')).toBe(true)
  expect(internals.writesDatabase('rm research/my-study/research_tree.db-wal')).toBe(true)
  expect(internals.writesDatabase(`sqlite3 ${db} "delete from x"`)).toBe(true)
  expect(internals.writesDatabase(`cp backup.db ${db}`, db)).toBe(true)
  // A database file outside research/<id>/ is not a project database.
  expect(internals.writesDatabase('rm research_tree.db research_tree.db-wal')).toBe(false)
  expect(internals.writesDatabase('rm /tmp/scratch/research_tree.db')).toBe(false)
  expect(internals.writesDatabase(`ls -l ${db}`, db)).toBe(false)
  expect(internals.writesDatabase(`.venv/bin/python tools/research_db.py --db ${db} decide "{}" > out.json`, db)).toBe(false)
  expect(internals.writesDatabase('rm -rf build/')).toBe(false)
})

test('redirections and wrapped commands into a project database count; quoted and heredoc text does not', () => {
  const db = 'research/my-study/research_tree.db'
  expect(internals.writesDatabase(`echo x > ${db}`)).toBe(true)
  expect(internals.writesDatabase(`cat dump >>"${db}-wal"`)).toBe(true)
  expect(internals.writesDatabase(`cd /tmp && sudo -n rm -f '${db}'`)).toBe(true)
  expect(internals.writesDatabase(`ls; FOO=1 timeout 10 /bin/rm ${db}`)).toBe(true)
  expect(internals.writesDatabase(`git commit -F - <<'EOF'\nNever rm ${db} or write > ${db}\nEOF\ngit log -1`)).toBe(false)
  expect(internals.writesDatabase(`git commit -m "guard: rm ${db} > x is refused"`)).toBe(false)
  expect(internals.writesDatabase(`grep -c rm ${db}.md > counts.txt  # rm ${db}`)).toBe(false)
  // A heredoc body ends at its delimiter; commands after it are checked again.
  expect(internals.writesDatabase(`cat <<EOF > notes.txt\nrm ${db}\nEOF\nrm ${db}`)).toBe(true)
})

test('the project configuration is not a subagent\'s: its edits and shell writes are refused', () => {
  const config = '/w/study/research-tree.yaml'
  expect(internals.guardReason(null, config, config)).toContain('按用户指示的 RLD')
  expect(internals.guardReason(null, '/w/other/research-tree.yaml', config)).toBeUndefined()
  expect(internals.writesConfig('cat > research-tree.yaml <<EOF\nx\nEOF', config)).toBe(true)
  expect(internals.writesConfig(`sed -i 's/a/b/' ${config}`, config)).toBe(true)
  expect(internals.writesConfig('sed s/a/b/ research-tree.yaml', config)).toBe(false)
  expect(internals.writesConfig('cat research-tree.yaml', config)).toBe(false)
  expect(internals.writesConfig('cp /tmp/x/research-tree.yaml /tmp/y', config)).toBe(false)  // another project's
})

test('the RLD edits the configuration on the user\'s request and applies it with their words; a subagent never does', async () => {
  const { host } = uiHost({})
  const config = '/w/study/research-tree.yaml'
  const next = async () => ({ result: 'ran' })
  for (const tool of ['Write', 'Edit']) {
    expect((await registeredTool(tool)(host, { file_path: config } as never, next)).deny).toBeUndefined()
    expect((await registeredTool(tool)(host, { agentId: 'w1', file_path: config } as never, next)).deny).toContain('按用户指示的 RLD')
  }
  const bash = registeredTool('Bash')
  expect((await bash(host, { command: `sed -i s/a/b/ ${config}` } as never, next)).deny).toBeUndefined()
  expect((await bash(host, { agentId: 'w1', command: `sed -i s/a/b/ ${config}` } as never, next)).deny).toContain('按用户指示的 RLD')
  expect((await bash(host, { command: '.venv/bin/python /plug/tools/research_tree.py config apply' } as never, next)).deny).toContain('--words')
  expect(internals.configApply('python tools/research_tree.py config show; echo apply')).toBeUndefined()
  const applied = await bash(host, { command: '.venv/bin/python /plug/tools/research_tree.py config apply --words "把总预算调到 20 node·h"' } as never, next)
  expect(applied.deny).toBeUndefined()
})

test('a subagent is never the RLD: a worker acts as itself, other helpers only read', () => {
  const db = '.venv/bin/python /p/tools/research_db.py --db research/p/research_tree.db'
  const calls = internals.researchCalls(`${db} --actor rld/main update_run '{}' && ${db} --actor=worker/h0001 get '{}'`)
  expect(calls).toEqual([
    { script: 'research_db.py', actor: 'rld/main', method: 'update_run' },
    { script: 'research_db.py', actor: 'worker/h0001', method: 'get' },
  ])
  expect(internals.subagentCallBlock(calls, 'worker/h0001')).toContain('只能以自己的身份')
  expect(internals.subagentCallBlock(calls.slice(1), 'worker/h0001')).toBeUndefined()
  expect(internals.subagentCallBlock(calls.slice(1), undefined)).toContain('未绑定身份')
  expect(internals.subagentCallBlock(calls, undefined)).toContain('未绑定身份')
  for (const actor of ['rld/main', 'worker/h0001', 'assistant/lens']) {
    expect(internals.subagentCallBlock(internals.researchCalls(`${db} --actor ${actor} context_pack '{}'`), undefined))
      .toContain('未绑定身份')
  }
  expect(internals.subagentCallBlock(internals.researchCalls(`${db} --actor assistant/lens context_pack '{}'`), 'assistant/lens'))
    .toBeUndefined()
  expect(internals.subagentCallBlock(internals.researchCalls('python tools/research_tree.py phase --set confirmed'), 'worker/h0001'))
    .toContain('research_tree.py phase')
  expect(internals.subagentCallBlock(internals.researchCalls("python tools/research_tree.py query get '{}'"), undefined)).toBeUndefined()
})

test('reviews go through research_review only: no direct pi or claude -p, no reviewer identity (09 §4)', () => {
  for (const command of ["pi -p --mode json --model openai/gpt-6-astra 'x'", "cd x && env A=1 pi -p 'x'",
    "claude -p --output-format json 'x'", "claude --print 'x'",
    ".venv/bin/python tools/research_db.py --db d --actor reviewer/pi register_review '{}'"]) {
    expect(internals.reviewerBypass(command)).toBeDefined()
  }
  for (const command of ['claude --version', 'echo pi', 'python tools/review_call.py --kind code_review --brief b --about H-0001']) {
    expect(internals.reviewerBypass(command)).toBeUndefined()
  }
  expect(internals.subagentCallBlock(internals.researchCalls('python tools/review_call.py --kind triage --brief b --about P'), 'worker/h0001'))
    .toContain('不发起评审')
})

test('a shell command writing the database file is refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: 'ran', stderr: '', interrupted: false } } as never))
  const denied = await $.tool.call({ tool: 'Bash', command: 'rm demo/research/P-x/research_tree.db' })
  expect(denied.deny).toContain('research_db')
  const allowed = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(allowed.isError).toBeUndefined()
})

test('research_db rejects a model-supplied actor before loading or running the project', async $ => {
  for (const actor of ['worker/w1', 'reviewer/pi', 'rld/main', '', null]) {
    const result = await $.tool.call({ tool: 'mcp__research-tree__research_db', method: 'get', kwargs: { entity_id: 'T-0001' }, actor } as never)
    expect(result.isError).toBe(true)
    expect(String(result.result)).toContain('actor')
  }
})

function registeredTool(tool: string) {
  let handler: ((host: never, event: never, next?: (event: never) => Promise<{ result: string }>) => Promise<{ result?: unknown; isError?: boolean; deny?: string }>) | undefined
  register(((event: string, filter: { tool?: string }, fn: typeof handler) => {
    if (event === 'tool.call' && filter?.tool === tool) handler = fn
  }) as never, {})
  expect(handler).toBeDefined()
  return handler!
}

test('research_db refuses unbound subagents and preserves bound worker and main identities', async () => {
  const { host, state, window } = uiHost({})
  const calls: string[][] = []
  const processHost = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  const run = processHost.process.run
  processHost.process.run = async argv => { calls.push(argv); return run(argv) }
  const call = registeredTool('mcp__research-tree__research_db')
  const result = await call(host, { agentId: 'unbound-helper', method: 'update_project', kwargs: { title: 'forged' } } as never)
  expect(result.isError).toBe(true)
  expect(String(result.result)).toContain('已绑定')
  expect(calls).toEqual([])
  expect(window()).toEqual([])
  expect((state.get('project') as { phase: string }).phase).toBe('confirmed')
  state.set('agents', { 'bound-worker': 'worker/w1' })
  const worker = await call(host, { agentId: 'bound-worker', method: 'get', kwargs: { entity_id: 'T-0001' } } as never)
  expect(worker.isError).toBeUndefined()
  expect(calls).toHaveLength(1)
  expect(calls[0]!.slice(4, 6)).toEqual(['--actor', 'worker/w1'])
  const main = await call(host, { method: 'get', kwargs: { entity_id: 'T-0001' } } as never)
  expect(main.isError).toBeUndefined()
  expect(calls).toHaveLength(2)
  expect(calls[1]!.slice(4, 6)).toEqual(['--actor', 'rld/main'])
})

test('worker and unbound subagents cannot post to the UI as the Leader', async () => {
  const { host, state, window } = uiHost({})
  state.set('agents', { 'bound-worker': 'worker/w1' })
  const calls: string[][] = []
  const processHost = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  const run = processHost.process.run
  processHost.process.run = async argv => { calls.push(argv); return run(argv) }
  const post = registeredTool('mcp__research-tree__post_to_ui')
  for (const agentId of ['bound-worker', 'unbound-helper']) {
    for (const type of ['notice', 'confirm_request']) {
      const result = await post(host, { agentId, type, text: 'forged Leader message' } as never)
      expect(result.isError).toBe(true)
      expect(String(result.result)).toContain('只有 RLD')
      expect((state.get('project') as { phase: string }).phase).toBe('confirmed')
    }
  }
  expect(calls).toEqual([])
  expect(window()).toEqual([])
})

test('the UI shell can query and write its outbox but cannot control or impersonate the Leader', async () => {
  const { host, state } = uiHost({})
  state.set('uiAgentId', 'ui-run')
  const bash = registeredTool('Bash')
  let ran = 0
  const next = async () => { ran += 1; return { result: 'ran' } }
  for (const command of [
    "python tools/research_db.py --actor rld/main decide '{}'",
    "python tools/research_db.py --actor ui/ui update_project '{}'",
    "python tools/research_db.py --actor rld/main get '{}'",
    'python tools/research_tree.py phase --set confirmed',
    'python tools/research_tree.py config apply',
    'python tools/review_call.py --kind triage --brief b --about P',
  ]) {
    const result = await bash(host, { agentId: 'ui-run', command } as never, next)
    expect(result.deny).toBeDefined()
  }
  expect(ran).toBe(0)
  for (const command of [
    "python tools/research_tree.py query get '{}'",
    'python tools/research_tree.py ui reply --run r1 --text answer',
    'python tools/research_tree.py ui confirm --run r1',
    'python tools/research_tree.py requirement draft --title request',
    "python tools/research_db.py --actor ui/ui get '{}'",
  ]) {
    const result = await bash(host, { agentId: 'ui-run', command } as never, next)
    expect(result.deny).toBeUndefined()
  }
  expect(ran).toBe(5)
})

test('post_to_ui validates the character boundary before any UI side effect', async () => {
  const { host, window } = uiHost({})
  const post = registeredTool('mcp__research-tree__post_to_ui')
  for (const text of ['', 'a'.repeat(201), null, 123]) {
    const result = await post(host, { type: 'notice', text } as never)
    expect(result.isError).toBe(true)
    expect(String(result.result)).toContain('1..200')
  }
  expect(window()).toEqual([])
  for (const text of ['a', '😀'.repeat(200)]) {
    const result = await post(host, { type: 'notice', text } as never)
    expect(result.isError).toBeUndefined()
  }
  expect(window()).toEqual(['a', '😀'.repeat(200)])
})

test('confirmation requests need document references before changing phase or notifying the UI', async () => {
  const { host, state, files, window } = uiHost({})
  const project = { project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' }
  state.set('project', project)
  files.set('/w/study/.research-tree.json', JSON.stringify(project))
  const calls: string[][] = []
  const processHost = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  processHost.process.run = async argv => {
    calls.push(argv)
    if (argv[2] === 'phase') {
      files.set('/w/study/.research-tree.json', JSON.stringify({ ...project, phase: argv[argv.indexOf('--set') + 1] }))
    }
    return { exitCode: 0, stderr: '', stdout: argv[1]!.endsWith('send_message.py')
      ? '{"id":"rld-0001","type":"confirm_request"}'
      : JSON.stringify({ ok: true, result: { blocked: null } }) }
  }
  const post = registeredTool('mcp__research-tree__post_to_ui')
  for (const docs of [undefined, []]) {
    const result = await post(host, { type: 'confirm_request', text: 'Please confirm the plan.', docs } as never)
    expect(result.isError).toBe(true)
    expect((state.get('project') as { phase: string }).phase).toBe('planning')
    expect(window()).toEqual([])
    expect(calls).toEqual([])
  }
  const result = await post(host, { type: 'confirm_request', text: 'Please confirm the plan.', docs: ['project/reports/plan.v1.md'] } as never)
  expect(result.isError).toBeUndefined()
  expect((state.get('project') as { phase: string }).phase).toBe('awaiting_confirmation')
  expect(calls[0]![2]).toBe('discovery')
  const message = calls.find(argv => argv[1]!.endsWith('send_message.py'))!
  expect(message.slice(-2)).toEqual(['--docs', 'project/reports/plan.v1.md'])
  expect(window()).toHaveLength(1)
  expect(window()[0]).toContain('project/reports/plan.v1.md')
})

test('a discovery refusal leaves no durable confirmation request or UI message', async () => {
  const { host, state, window } = uiHost({})
  state.set('project', { project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' })
  const calls: string[][] = []
  const processHost = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  processHost.process.run = async argv => {
    calls.push(argv)
    return { exitCode: 0, stderr: '', stdout: argv[1]!.endsWith('send_message.py')
      ? '{"id":"rld-0001","type":"confirm_request"}'
      : JSON.stringify({ ok: true, result: { blocked: 'Discovery incomplete' } }) }
  }
  const result = await registeredTool('mcp__research-tree__post_to_ui')(host, {
    type: 'confirm_request', text: 'Please confirm the plan.', docs: ['project/reports/plan.v1.md'],
  } as never)
  expect(result.isError).toBe(true)
  expect(String(result.result)).toContain('Discovery incomplete')
  expect(calls).toHaveLength(1)
  expect(calls[0]![2]).toBe('discovery')
  expect((state.get('project') as { phase: string }).phase).toBe('planning')
  expect(window()).toEqual([])
})

test('lens runs record requested and observed models while their bound identity remains read only', async () => {
  const { host, state } = uiHost({})
  state.set('project', { project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' })
  const conf = { discovery: { mode: 'full', lenses: ['method-transfer'], seed_lenses: [] }, models: { lens_assistant: { model: 'inherit', effort: 'medium' } } }
  const calls: string[][] = []
  const processHost = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  processHost.process.run = async argv => {
    calls.push(argv)
    return { exitCode: 0, stderr: '', stdout: JSON.stringify({ ok: true, result: argv[2] === 'config' ? { effective: conf } : [] }) }
  }
  type Hook = (host: never, event: never, next: (event: never) => Promise<Record<string, unknown>>) => Promise<Record<string, unknown>>
  let spawn: Hook | undefined, complete: Hook | undefined
  register(((event: string, fn: Hook) => {
    if (event === 'agent.spawn') spawn = fn
    if (event === 'turn.complete') complete = fn
  }) as never, {})
  const spawned = { agentId: 'lens-model-log-test', model: 'requested-lens-model' }
  expect(await spawn!(host, { subagentType: 'research-tree:lens', prompt: 'lens=method-transfer Read the plan.' } as never, async () => spawned)).toEqual(spawned)
  expect((state.get('agents') as Record<string, string> | undefined)?.[spawned.agentId]).toBe('assistant/lens_method_transfer')
  await complete!(host, { agentId: spawned.agentId, usage: { model: 'observed-lens-model' } } as never, async () => ({}))
  const logs = calls.filter(argv => argv[2] === 'agent-log')
  expect(logs).toHaveLength(2)
  for (const [index, event, model] of [[0, 'requested', spawned.model], [1, 'observed', 'observed-lens-model']] as const) {
    const argv = logs[index]!
    expect(argv[argv.indexOf('--actor') + 1]).toBe('assistant/lens_method_transfer')
    expect(argv[argv.indexOf('--agent') + 1]).toBe(spawned.agentId)
    expect(argv[argv.indexOf('--event') + 1]).toBe(event)
    expect(argv[argv.indexOf('--model') + 1]).toBe(model)
  }
  expect(logs[0]![logs[0]!.indexOf('--effort') + 1]).toBe('medium')
  const before = calls.length
  const denied = await registeredTool('mcp__research-tree__research_db')(host, { agentId: spawned.agentId, method: 'update_project', kwargs: { title: 'forged' } } as never)
  expect(denied.isError).toBe(true)
  expect(String(denied.result)).toContain('只读')
  const bash = await registeredTool('Bash')(host, { agentId: spawned.agentId, command: "python tools/research_db.py --actor assistant/lens_method_transfer update_project '{}'" } as never, async () => ({ result: 'ran' }))
  expect(bash.deny).toContain('只读')
  expect(calls).toHaveLength(before)
})

const RUN = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 160 } }

test('prepare runs the shared shell helper in the session directory, without a project or Python', async () => {
  const calls: string[][] = []
  const host = {
    plugin: { root: '/plugin root' },
    session: { cwd: async () => '/user project' },
    process: { run: async (argv: string[], init: { timeoutMs: number }) => {
      calls.push(argv)
      expect(init.timeoutMs).toBeLessThanOrEqual(600_000)  // the host refuses a longer wait
      return { exitCode: 0, stdout: '已生成研究计划：plan.md\n', stderr: '' }
    } },
  }
  expect(await internals.prepareCommand(host as never, ['--python=3.12'])).toBe('已生成研究计划：plan.md')
  expect(calls).toEqual([['sh', '/plugin root/tools/prepare.sh', '--python=3.12', '/user project']])
  expect(await internals.configCommand(host as never, { actor: 'rld/main' })).toContain('prepare')  // config only shows or applies
})

test('without a project here the command points to prepare and init', async $ => {
  const ran = await $.command.run({ command: 'research-tree', args: '', ...RUN })
  expect(ran.text).toContain('/research-tree prepare')
  expect(ran.text).toContain('/research-tree init')
})

test('init reads the plan (plan.md by default), the project id and a configuration file', () => {
  expect(internals.parseInit([])).toEqual({ plan: 'plan.md' })
  expect(internals.parseInit(['plans/goal.md', '--id', 'my-study'])).toEqual({ plan: 'plans/goal.md', id: 'my-study' })
  expect(internals.parseInit(['--config=cluster.yaml'])).toEqual({ plan: 'plan.md', config: 'cluster.yaml' })
  for (const bad of [['a.md', 'b.md'], ['--id'], ['a.md', '--python', '3.12'], ['--update-uv']]) {
    expect('usage' in internals.parseInit(bad)).toBe(true)
  }
})

test('init needs the environment prepare makes', async $ => {
  const usage = await $.command.run({ command: 'research-tree', args: 'init a.md b.md', ...RUN })
  expect(usage.text).toContain('用法')
  const ran = await $.command.run({ command: 'research-tree', args: 'init', ...RUN })
  expect(ran.text).toContain('/research-tree prepare')
})

test('no worker starts before the user confirmed the plan', async ($, on) => {
  let reached = 0
  on('agent.spawn', () => {
    reached += 1
    return { model: 'test-model' }
  })
  const denied = await $.agent.spawn({ subagentType: 'research-tree:worker', prompt: '你是 worker/w1。实现 T-0001。' } as never)
  expect((denied as { deny?: string }).deny).toContain('/research-tree init')
  expect(reached).toBe(0)
  // Other agent types are not held back.
  await $.agent.spawn({ subagentType: 'general-purpose', prompt: 'look around' } as never)
  expect(reached).toBe(1)
})

test('the start-up rule follows the confirmation phase', () => {
  const project = { phase: 'planning' } as Parameters<typeof internals.workerBlock>[0]
  expect(internals.workerBlock(null)).toContain('init')
  expect(internals.workerBlock(project)).toContain('尚未经用户确认')
  expect(internals.workerBlock({ ...project!, phase: 'awaiting_confirmation' })).toContain('等待用户确认')
  expect(internals.workerBlock({ ...project!, phase: 'confirmed' })).toBeUndefined()
})

test('lens starts only for configured full-discovery planning', () => {
  const project = { phase: 'planning' } as Parameters<typeof internals.lensBlock>[0]
  const conf = { discovery: { mode: 'full', lenses: ['method-transfer'], seed_lenses: ['variant'] },
    models: { lens_assistant: { model: 'inherit', effort: 'medium' } } } as Parameters<typeof internals.lensBlock>[1]
  expect(internals.lensBlock(null, conf, 'method-transfer')).toContain('planning')
  expect(internals.lensBlock({ ...project!, phase: 'confirmed' }, conf, 'method-transfer')).toContain('planning')
  expect(internals.lensBlock(project, { ...conf!, discovery: { ...conf!.discovery!, mode: 'off' } }, 'method-transfer')).toContain('full')
  expect(internals.lensBlock(project, conf, 'unknown')).toContain('已配置')
  expect(internals.lensBlock(project, conf, undefined)).toContain('已配置')
  expect(internals.lensBlock(project, { ...conf!, models: { ...conf!.models, lens_assistant: undefined } }, 'method-transfer')).toContain('lens_assistant')
  expect(internals.lensBlock(project, conf, 'method-transfer')).toBeUndefined()
  expect(internals.lensBlock(project, conf, 'variant')).toBeUndefined()
})

test('the registered lens has only read tools and returns candidates for the Leader', async () => {
  const agents: { name: string; tools?: string[]; prompt?: string }[] = []
  const host = { agent: { register: async (input: typeof agents[number]) => { agents.push(input) } } }
  await internals.registerAgents(host as never, null)
  const lens = agents.find(agent => agent.name === 'lens')!
  expect(lens.tools).toEqual(['Read', 'Grep', 'Glob'])
  expect(lens.prompt).toContain('你不写任何文件')
  expect(lens.prompt).toContain('最终回答只包含 JSON')
})

test('worker identities resolve to their node, and bound sessions to their identity', () => {
  const worker = (id: string | null, agent: string | null) => ({ id, agent_id: agent, session_at: null, resume: [] })
  const s = {
    project: { id: 'my-study', worker: worker('root', 'agent-root') },
    nodes: [{ id: 'H-0001', worker: worker('h0001', 'agent-1') }, { id: 'H-0002', worker: worker(null, null) }],
  } as unknown as ResearchSummary
  expect(internals.workerNode(s, 'root')).toBe('my-study')
  expect(internals.workerNode(s, 'h0001')).toBe('H-0001')
  expect(internals.workerNode(s, 'h0002')).toBeUndefined()
  expect(internals.workerNode(null, 'h0001')).toBeUndefined()
  expect(internals.workerActor(s, 'agent-1')).toBe('worker/h0001')
  expect(internals.workerActor(s, 'agent-root')).toBe('worker/root')
  expect(internals.workerActor(s, 'agent-x')).toBeUndefined()
})

test('a worker without a task in hand waits while max_parallel_workers others have one', () => {
  const s = (limit: number | null, busy: string[]) =>
    ({ project: { max_parallel_workers: limit }, busy_workers: busy }) as unknown as ResearchSummary
  expect(internals.parallelBlock(s(null, ['h0001', 'h0002']), 'h0003')).toBeUndefined()
  expect(internals.parallelBlock(s(2, ['h0001']), 'h0003')).toBeUndefined()
  expect(internals.parallelBlock(s(2, ['h0001', 'h0002']), 'h0002')).toBeUndefined()  // continues its own task
  expect(internals.parallelBlock(s(2, ['h0001', 'h0002']), 'h0003')).toContain('max_parallel_workers')
})

test('workers get the platform of research-tree.yaml, not a built-in site', () => {
  const conf = {
    platform: { dev: '在登录节点编辑。', experiment: '用 sbatch 提交到 gpu 分区。', skills: ['slurm'] },
  } as unknown as Parameters<typeof internals.workerPrompt>[0]
  const prompt = internals.workerPrompt(conf)
  expect(prompt).toContain('用 sbatch 提交到 gpu 分区。')
  expect(prompt).toContain('预加载的技能：slurm')
  expect(internals.workerPrompt(null)).toContain('research-tree.yaml')
  expect(prompt).not.toMatch(/miyabi|pbs/i)
})

test('without a project the UI window says so and starts no UI agent', async ($, on) => {
  let spawns = 0
  on('agent.spawn', () => {
    spawns += 1
    return { model: 'test-model' }
  })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...UI, surface })
    expect(await ui.find({ type: 'Text', text: /还没有消息/ })).toBeDefined()
    await ui.unmount()
  }
  const ui = await $.ui.mount({ ...UI, surface: 'terminal' })
  await ui.input({ key: 'ask', text: '现在进度如何？' })
  expect(await ui.find({ type: 'Text', text: /现在进度如何/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /当前目录没有研究项目/ })).toBeDefined()
  expect(spawns).toBe(0)
  await ui.unmount()
})

test('a UI run reads with the CLI and acts only through its own outbox', () => {
  const project = { project_id: 'p', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' } as
    Parameters<typeof internals.uiPrompt>[1]
  const prompt = internals.uiPrompt('/plug', project, 'r123', '/w/study/.venv/bin/python')
  expect(prompt).toContain('在项目目录 /w/study 运行命令')
  expect(prompt).toContain(`/w/study/.venv/bin/python /plug/tools/research_tree.py query get '{"entity_id": "H-0001"}'`)
  expect(prompt).not.toContain('research_db.py')  // no way to name another actor
  expect(prompt).toContain('/plug/tools/research_tree.py requirement draft')
  for (const action of ['reply', 'confirm', 'instruction', 'question', 'submit']) {
    expect(prompt).toContain(`/plug/tools/research_tree.py ui ${action} --run r123`)
  }
  expect(prompt).not.toMatch(/relay_to_rld|confirm_plan|mcp__/)
})

test('the main model is never offered the UI agent', async $ => {
  const offered = await $.agent.offer({
    agent: 'research-tree:ui', description: 'UI', source: 'plugin',
    provider: { plugin: 'research-tree', tier: 'user' },
  } as never)
  expect(offered.isOffered).toBe(false)
})

/** A host for the UI hand-off alone: state, files, the Python tools, spawns and prompts to the RLD, all in memory. */
function uiHost(outboxes: Record<string, string>, answered: Set<string> = new Set()) {
  const root = '/w/study/research/p'
  const state = new Map<string, unknown>([['project', { project_id: 'p', phase: 'confirmed', root, db: `${root}/research_tree.db` }]])
  const files = new Map<string, string>(Object.entries(outboxes).map(([run, text]) => [`${root}/cache/ui/${run}.jsonl`, text]))
  files.set('/w/study/.venv/bin/python', '')
  const spawns: string[] = []
  const prompts: string[] = []
  const host = {
    plugin: { root: '/plug' },
    session: { cwd: async () => '/w/study' },
    state: {
      get: async (ref: { key: string }) => ({ value: state.get(ref.key), version: 1 }),
      set: async (ref: { key: string }, value: unknown) => (state.set(ref.key, value), { isSet: true, version: 1 }),
    },
    fs: {
      exists: async (path: string) => files.has(path),
      read: async (path: string) => files.get(path) ?? '',
      write: async (path: string, text: string) => void files.set(path, text),
    },
    process: { run: async (argv: string[]) => ({
      exitCode: 0, stderr: '',
      stdout: argv[1]!.endsWith('send_message.py') ? '{"id":"ui-0001","type":"question"}'
        : argv.includes('inbox') ? JSON.stringify({ ok: true, result: answered.has('ui-0001') ? []
          : [{ kind: 'awaiting_reply', id: null, text: 'ui-0001（question）尚无RLD回执：…' }] })
        : '{"ok": true, "result": []}',
    }) },
    agent: { spawn: async (input: { prompt: string }) => (spawns.push(input.prompt), { agentId: `a${spawns.length}` }),
      register: async () => undefined },
    clock: { after: (_ms: number, fn: () => void) => fn() },
    prompt: { submit: async (input: { text: string }) => void prompts.push(input.text) },
    ui: { toast: () => undefined, open: async () => undefined, status: () => undefined },
  }
  const window = () => (files.get(`${root}/messages/window.jsonl`) ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l).text as string)
  return { host: host as never, state, files, spawns, prompts, window }
}

test('a UI run that leaves nothing is retried once, then the message goes to the RLD verbatim', async () => {
  const cfg = { actor: 'rld/main' }
  const message = 'RLD为什么需要读 research_db.py 的源码?'
  const { host, state, spawns, prompts, window } = uiHost({ r1: '', r2: '' })
  await internals.carryOutUi(host, cfg, { run: 'r1', message, messageId: 'w-0015', attempt: 1 }, '', false)
  expect(spawns.length).toBe(1)
  expect(spawns[0]).toContain('发件箱是空的')
  expect(spawns[0]).toContain(`## 用户的新消息（w-0015）\n${message}`)
  expect(state.get('uiAgentId')).toBe('a1')
  expect((state.get('uiRun') as { attempt: number }).attempt).toBe(2)
  expect(prompts).toEqual([])

  await internals.carryOutUi(host, cfg, { run: 'r2', message, messageId: 'w-0015', attempt: 2 }, '', false)
  await new Promise(resolve => setTimeout(resolve, 10))  // delivery checks the receipt first
  expect(spawns.length).toBe(1)
  expect(prompts.length).toBe(1)
  expect(prompts[0]).toContain('post_to_ui(type=reply')
  expect(window().at(-1)).toContain('已把原文转交RLD')
})

test('a message the RLD already answered is not delivered a second time (real-run-error #6, #13)', async () => {
  const cfg = { actor: 'rld/main' }
  const answered = new Set<string>()
  const { host, prompts } = uiHost({ r1: '{"type": "reply", "text": "转交"}\n{"type": "question", "text": "能否加 seed？"}\n' }, answered)
  answered.add('ui-0001')  // the RLD answered it (re=ui-0001) before the queued delivery ran
  await internals.carryOutUi(host, cfg, { run: 'r1', message: '能否加 seed？', attempt: 1 }, '', false)
  await new Promise(resolve => setTimeout(resolve, 10))
  expect(prompts).toEqual([])
  answered.clear()  // still waiting: delivered once, telling the RLD to check its inbox first
  await internals.carryOutUi(host, cfg, { run: 'r1', message: '能否加 seed？', attempt: 1 }, '', false)
  await new Promise(resolve => setTimeout(resolve, 10))
  expect(prompts.length).toBe(1)
  expect(prompts[0]).toContain('不要重复回执')
})

test('a UI run that replied, or was interrupted, is not retried', async () => {
  const cfg = { actor: 'rld/main' }
  const { host, spawns, prompts, window } = uiHost({ r1: '{"type": "reply", "text": "已回答"}\n', r2: '' })
  await internals.carryOutUi(host, cfg, { run: 'r1', message: '进度？', attempt: 1 }, '', false)
  await internals.carryOutUi(host, cfg, { run: 'r2', message: '进度？', attempt: 1 }, '', true)
  expect(window()).toEqual(['已回答', '（UI 被中断）'])
  expect([spawns.length, prompts.length]).toEqual([0, 0])
})


test('a prompt refused while a hook still holds the turn is submitted again, not lost', async () => {
  const { host, prompts, window } = uiHost({})
  let refusals = 2
  const h = host as unknown as { prompt: { submit: (input: { text: string }) => Promise<void> } }
  const submit = h.prompt.submit
  h.prompt.submit = async input => {
    if (refusals-- > 0) throw new Error('prompt.submit: called from a command.run hook, it would wait on the turn this hook is holding')
    return submit(input)
  }
  internals.submitLater(host, { text: '用户确认立项计划' })
  await new Promise(resolve => setTimeout(resolve, 10))
  expect(prompts).toEqual(['用户确认立项计划'])
  expect(window()).toEqual([])
})
