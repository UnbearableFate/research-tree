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

test('cp sources are reads and directory destinations are writes, for the database and the configuration alike', () => {
  const config = '/w/study/research-tree.yaml'
  expect(internals.writesDatabase('cp research/p/research_tree.db /tmp/bak.db')).toBe(false)
  expect(internals.writesDatabase('cp -a research/p/research_tree.db research/p/research_tree.db-wal /tmp/backup/')).toBe(false)
  for (const command of ['cp ~/bak/research_tree.db research/p/', 'cp ~/bak/research_tree.db research/p',
    'cp -t research/p ~/bak/research_tree.db', 'cp --target-directory=research/p /tmp/research_tree.db',
    'mv research/p/research_tree.db /tmp/']) {
    expect(internals.writesDatabase(command)).toBe(true)
  }
  for (const command of ['cp /tmp/x/research-tree.yaml /w/study/', 'cp /tmp/x/research-tree.yaml /w/study',
    'cp -t /w/study /tmp/x/research-tree.yaml']) {
    expect(internals.writesConfig(command, config)).toBe(true)
  }
  expect(internals.writesConfig(`cp ${config} /tmp/research-tree.backup.yaml`, config)).toBe(false)  // a source is read
  expect(internals.writesConfig('cp -T /tmp/x/research-tree.yaml /w/study/other.yaml', config)).toBe(false)
  expect(internals.writeTargets('cp a b c /dest/')).toEqual(['/dest/', '/dest/a', '/dest/b', '/dest/c'])
  expect(internals.writeTargets('mv a b /dest')).toEqual(['a', 'b', '/dest', '/dest/a', '/dest/b'])  // mv removes its sources
})

test('the RLD edits the configuration on the user\'s request and applies it with their words; a subagent never does', async () => {
  const { host } = uiHost({})
  const config = '/w/study/research-tree.yaml'
  const next = async () => ({ result: 'ran' })
  // the main session's write still passes the database's file guards
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  const run = h.process.run
  h.process.run = async argv => argv.includes('--summary')
    ? { exitCode: 0, stderr: '', stdout: JSON.stringify({ db_path: '/w/study/research/p/research_tree.db', guards: { frozen_docs: [], harness: [] } }) }
    : run(argv)
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

test('config apply needs non-empty user words however its arguments are ordered or spelled', async () => {
  const tool = '.venv/bin/python /plug/tools/research_tree.py'
  const unworded = [`${tool} config --actor rld/main apply`, `${tool} config --require-project apply`,
    `${tool} config apply --words ""`, `${tool} config apply --words=`, `${tool} config apply --words '  '`,
    'uv run python /plug/tools/research_tree.py config apply']
  for (const command of unworded) expect(internals.configApply(command)).toBe('')
  expect(internals.configApply(`${tool} config --words='把总预算调到 20 node·h' apply`)).toBe('把总预算调到 20 node·h')
  expect(internals.configApply(`${tool} config apply --word "同意改为 3 个 seed"`)).toBe('同意改为 3 个 seed')  // argparse's unique prefix
  expect(internals.configApply(`${tool} config --words apply`)).toBeUndefined()  // "apply" is the words; the action is show
  expect(internals.configApply('grep -n apply /plug/tools/research_tree.py')).toBeUndefined()
  const { host } = uiHost({})
  let ran = 0
  const next = async () => { ran += 1; return { result: 'ran' } }
  for (const command of unworded) {
    expect((await registeredTool('Bash')(host, { command } as never, next)).deny).toContain('--words')
  }
  expect(ran).toBe(0)
})

test('applying the configuration reloads agents only from a configuration read, and a failed reload keeps the command\'s result', async () => {
  const { host, files } = uiHost({})
  files.set('/w/study/.research-tree.json', JSON.stringify({ format_version: 3, project_id: 'p', phase: 'confirmed', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' }))
  const registered: { name: string; model: string }[] = []
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> }; agent: { register: (spec: { name: string; model: string }) => Promise<void> } }
  h.agent.register = async spec => { registered.push(spec) }
  let shown: unknown = { ok: false, error: 'research-tree.yaml: invalid' }
  h.process.run = async argv => ({ exitCode: 0, stderr: '', stdout: JSON.stringify(argv[2] === 'config' ? shown : { ok: true, result: [] }) })
  const bash = registeredTool('Bash')
  const command = ".venv/bin/python /plug/tools/research_tree.py config apply --words '把总预算调到 20 node·h'"
  const next = async () => ({ result: 'ran' })
  expect((await bash(host, { command } as never, next)).result).toBe('ran')
  expect(registered).toEqual([])  // nothing read: the agents keep their models, never the 'inherit' defaults
  const models = Object.fromEntries(['ui', 'worker', 'architect', 'explorer', 'analyst'].map(role => [role, { model: `${role}-model`, effort: null }]))
  shown = { ok: true, result: { effective: { version: 3, models, platform: { dev: 'local', experiment: 'CPU', skills: [] } } } }
  expect((await bash(host, { command } as never, next)).result).toBe('ran')
  expect(registered.map(a => a.model).sort()).toEqual(['analyst-model', 'architect-model', 'explorer-model', 'ui-model', 'worker-model'])
  h.agent.register = async () => { throw new Error('host closed') }
  expect((await bash(host, { command } as never, next)).result).toBe('ran')  // the command ran: its result stands
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
  for (const actor of ['rld/main', 'worker/h0001', 'explorer/main']) {
    expect(internals.subagentCallBlock(internals.researchCalls(`${db} --actor ${actor} context_pack '{}'`), undefined))
      .toContain('未绑定身份')
  }
  expect(internals.subagentCallBlock(internals.researchCalls(`${db} --actor explorer/main context_pack '{}'`), 'explorer/main'))
    .toBeUndefined()
  expect(internals.subagentCallBlock(internals.researchCalls('python tools/research_tree.py phase --set confirmed'), 'worker/h0001'))
    .toContain('research_tree.py phase')
  expect(internals.subagentCallBlock(internals.researchCalls("python tools/research_tree.py query get '{}'"), undefined)).toBeUndefined()
})

test('only running a research tool is a tool call: reading or listing its file is not', async () => {
  for (const command of ['grep -n "def assign_worker" /plug/tools/research_db.py', 'sed -n 1,40p /plug/tools/research_tree.py',
    'cat /plug/tools/review_call.py | head -20', 'ls -l /plug/tools/research_db.py', 'wc -l tools/research_db.py',
    'python -m py_compile /plug/tools/research_db.py', 'uv run pytest tests/research_db.py']) {
    expect(internals.researchCalls(command)).toEqual([])
  }
  expect(internals.researchCalls("uv run python /plug/tools/research_tree.py query get '{}'")).toEqual([{ script: 'research_tree.py', method: 'query' }])
  expect(internals.researchCalls("cd /w/study && ./tools/research_db.py --actor worker/h1 get '{}' > out.json"))
    .toEqual([{ script: 'research_db.py', actor: 'worker/h1', method: 'get' }])
  expect(internals.researchCalls("if python3 -u /plug/tools/research_db.py --actor=worker/h1 find '{}'; then echo ok; fi"))
    .toEqual([{ script: 'research_db.py', actor: 'worker/h1', method: 'find' }])
  const { host, state } = uiHost({})
  state.set('agents', { 'bound-worker': 'worker/h1' })
  let ran = 0
  const next = async () => { ran += 1; return { result: 'ran' } }
  for (const command of ['grep -n "def assign_worker" /plug/tools/research_db.py', 'sed -n 1,40p /plug/tools/research_tree.py']) {
    expect((await registeredTool('Bash')(host, { agentId: 'bound-worker', command } as never, next)).deny).toBeUndefined()
  }
  expect(ran).toBe(2)
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
  expect(internals.subagentCallBlock(internals.researchCalls('python tools/review_call.py --kind code_review --brief b --about P'), 'worker/h0001'))
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
    'python tools/review_call.py --kind code_review --brief b --about P',
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
  const project = { format_version: 3, project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' }
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

test('a failed scope preflight leaves no durable confirmation request or UI message', async () => {
  const { host, state, window } = uiHost({})
  state.set('project', { format_version: 3, project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' })
  const calls: string[][] = []
  const processHost = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  processHost.process.run = async argv => {
    calls.push(argv)
    return { exitCode: 0, stderr: '', stdout: argv[1]!.endsWith('send_message.py')
      ? '{"id":"rld-0001","type":"confirm_request"}'
      : JSON.stringify({ ok: true, result: { blocked: 'Scope preflight unavailable' } }) }
  }
  const result = await registeredTool('mcp__research-tree__post_to_ui')(host, {
    type: 'confirm_request', text: 'Please confirm the plan.', docs: ['project/reports/plan.v1.md'],
  } as never)
  expect(result.isError).toBe(true)
  expect(String(result.result)).toContain('Scope preflight unavailable')
  expect(calls).toHaveLength(1)
  expect(calls[0]![2]).toBe('discovery')
  expect((state.get('project') as { phase: string }).phase).toBe('planning')
  expect(window()).toEqual([])
})

test('Explorer runs record requested and observed models while their bound identity remains read only', async () => {
  const { host, state } = uiHost({})
  state.set('project', { format_version: 3, project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' })
  const conf = { version: 3, models: { explorer: { model: 'inherit', effort: 'medium' } } }
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
  const spawned = { agentId: 'explorer-model-log-test', model: 'requested-explorer-model' }
  expect(await spawn!(host, { subagentType: 'research-tree:explorer', prompt: 'Read the plan and propose a falsifiable candidate.' } as never, async () => spawned)).toEqual(spawned)
  expect((state.get('agents') as Record<string, string> | undefined)?.[spawned.agentId]).toBe('explorer/main')
  await complete!(host, { agentId: spawned.agentId, usage: { model: 'observed-explorer-model' } } as never, async () => ({}))
  const logs = calls.filter(argv => argv[2] === 'agent-log')
  expect(logs).toHaveLength(2)
  for (const [index, event, model] of [[0, 'requested', spawned.model], [1, 'observed', 'observed-explorer-model']] as const) {
    const argv = logs[index]!
    expect(argv[argv.indexOf('--actor') + 1]).toBe('explorer/main')
    expect(argv[argv.indexOf('--agent') + 1]).toBe(spawned.agentId)
    expect(argv[argv.indexOf('--event') + 1]).toBe(event)
    expect(argv[argv.indexOf('--model') + 1]).toBe(model)
  }
  expect(logs[0]![logs[0]!.indexOf('--effort') + 1]).toBe('medium')
  const before = calls.length
  const denied = await registeredTool('mcp__research-tree__research_db')(host, { agentId: spawned.agentId, method: 'update_project', kwargs: { title: 'forged' } } as never)
  expect(denied.isError).toBe(true)
  expect(String(denied.result)).toContain('只读')
  const bash = await registeredTool('Bash')(host, { agentId: spawned.agentId, command: "python tools/research_db.py --actor explorer/main update_project '{}'" } as never, async () => ({ result: 'ran' }))
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

test('removed lens and unknown research roles are rejected before any spawn', async () => {
  const { host, state } = uiHost({})
  type Hook = (host: never, event: never, next: (event: never) => Promise<Record<string, unknown>>) => Promise<Record<string, unknown>>
  let spawn: Hook | undefined
  register(((event: string, fn: Hook) => { if (event === 'agent.spawn') spawn = fn }) as never, {})
  let called = 0
  for (const type of ['research-tree:lens', 'research-tree:web_builder', 'research-tree:reviewer']) {
    expect((await spawn!(host, { subagentType: type, prompt: 'Read the plan.' } as never,
      async () => { called += 1; return { agentId: 'forbidden' } })).deny).toContain('不支持的研究角色')
  }
  expect(called).toBe(0)
  expect(state.get('agents')).toBeUndefined()
})

test('the registered role set has no lens or fallback model aliases', async () => {
  const agents: { name: string; model: string; prompt: string; tools?: string[] }[] = []
  const models = Object.fromEntries(['ui', 'worker', 'architect', 'explorer', 'analyst'].map(role =>
    [role, { model: `${role}-model`, effort: null }]))
  await internals.registerAgents({ agent: { register: async (agent: never) => { agents.push(agent) } } } as never,
    { version: 3, models, platform: { dev: 'local', experiment: 'CPU', skills: [] } } as never)
  expect(agents.map(a => a.name).sort()).toEqual(['analyst', 'architect', 'explorer', 'ui', 'worker'])
  for (const agent of agents) expect(agent.model).toBe(`${agent.name}-model`)
  expect(agents.find(a => a.name === 'explorer')!.prompt).toContain('source:"explorer/main"')
})

test('worker identities resolve to their node, and bound sessions to their identity', () => {
  const worker = (id: string | null, agent: string | null) => ({ id, agent_id: agent, session_at: null, resume: [] })
  const s = {
    project: { id: 'my-study', architect: worker('root', 'agent-root') },
    nodes: [{ id: 'H-0001', worker: worker('h0001', 'agent-1') }, { id: 'H-0002', worker: worker(null, null) }],
  } as unknown as ResearchSummary
  expect(internals.workerNode(s, 'architect/root')).toBe('my-study')
  expect(internals.workerNode(s, 'worker/h0001')).toBe('H-0001')
  expect(internals.workerNode(s, 'worker/h0002')).toBeUndefined()
  expect(internals.workerNode(null, 'worker/h0001')).toBeUndefined()
  expect(internals.workerActor(s, 'agent-1')).toBe('worker/h0001')
  expect(internals.workerActor(s, 'agent-root')).toBe('architect/root')
  expect(internals.workerActor(s, 'agent-x')).toBeUndefined()
  expect(internals.workerNode(s, 'worker/root')).toBeUndefined()
  expect(internals.workerNode(s, 'root')).toBeUndefined()
  expect(internals.workerNode(s, 'architect/h0001')).toBeUndefined()
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
  const project = { format_version: 3, project_id: 'p', root: '/w/study/research/p', db: '/w/study/research/p/research_tree.db' } as
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
  const state = new Map<string, unknown>([['project', { format_version: 3, project_id: 'p', phase: 'confirmed', root, db: `${root}/research_tree.db` }]])
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
      stdout: argv[1]!.endsWith('send_message.py') ? '{"id":"ui--ui-0001","type":"question"}'
        : argv.includes('inbox') ? JSON.stringify({ ok: true, result: answered.has('ui--ui-0001') ? []
          : [{ kind: 'awaiting_reply', id: null, text: 'ui--ui-0001（question）尚无RLD回执：…' }] })
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
  answered.add('ui--ui-0001')  // the RLD answered it (re=ui--ui-0001) before the queued delivery ran
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

test('Explorer and Analyst have real read-only registrations, while Architect uses its root role', async () => {
  const agents: { name: string; prompt: string; tools?: string[] }[] = []
  await internals.registerAgents({ agent: { register: async (agent: never) => { agents.push(agent) } } } as never, null)
  for (const role of ['explorer', 'analyst']) {
    const agent = agents.find(a => a.name === role)!
    expect(agent.prompt).toContain(`${role}/main`)
    expect(agent.tools).toContain('mcp__research-tree__research_db')
    for (const writeTool of ['Write', 'Edit', 'Bash', 'Agent']) expect(agent.tools).not.toContain(writeTool)
    expect(agent.prompt).toContain('不能修改文件')
  }
  expect(agents.find(a => a.name === 'architect')!.prompt).toContain('architect/<id>')
  expect(agents.find(a => a.name === 'architect')!.prompt).toContain('仅根节点')
})

test('advisory sessions cannot mutate records, edit files, use shell execution or initiate reviews', async () => {
  const { host, state, spawns } = uiHost({})
  let writes = 0
  const next = async () => { writes += 1; return { result: 'ran' } }
  for (const role of ['explorer', 'analyst']) {
    state.set('agents', { advisor: `${role}/main` })
    const refused = await registeredTool('mcp__research-tree__research_db')(host, { agentId: 'advisor', method: 'update_project', kwargs: {} } as never)
    expect(refused.isError).toBe(true)
    expect(String(refused.result)).toContain('只读')
    const read = await registeredTool('mcp__research-tree__research_db')(host, { agentId: 'advisor', method: 'get', kwargs: { entity_id: 'p' } } as never)
    expect(read.isError).toBeUndefined()
    for (const tool of ['Write', 'Edit', 'NotebookEdit', 'Bash']) {
      const result = await registeredTool(tool)(host, { agentId: 'advisor', file_path: '/tmp/x', notebook_path: '/tmp/x', command: 'touch /tmp/x' } as never, next)
      expect(result.deny).toContain('只读研究顾问')
    }
    const review = await registeredTool('mcp__research-tree__research_review')(host, { agentId: 'advisor', kind: 'code_review' } as never)
    expect(review.isError).toBe(true)
  }
  expect(writes).toBe(0)
  expect(spawns).toEqual([])
})

const LIGHT_SUMMARY = {
  meta: { data_version: 3, generated_at: 'fixture', eligibility_checked: false }, db_path: '/w/study/research/p/research_tree.db',
  project: { id: 'p', title: 'Study', status: 'active', stage: 'search', architect: { id: 'root', agent_id: null }, sota_experiment_id: null },
  counts: { status: {}, exp_status: {}, go: null, node_hours: 0, screen_seeds: 1 },
  nodes: [{ id: 'H-0001', title: 'Idea', parent: 'p', worker: { id: 'h1', agent_id: null }, go: null }],
  attention: [], busy_workers: [], guards: { frozen_docs: [], harness: [] },
} as unknown as ResearchSummary

test('a burst coalesces lightweight display refresh and a failed display cannot fail a scientific write', async () => {
  const { host, state } = uiHost({})
  const timers: (() => void)[] = [], calls: string[][] = []
  const h = host as unknown as { clock: { after: (ms: number, fn: () => void) => void }; process: { run: (argv: string[]) => Promise<unknown> } }
  h.clock.after = (_ms, fn) => { timers.push(fn) }
  h.process.run = async argv => {
    calls.push(argv)
    return { exitCode: 0, stderr: '', stdout: JSON.stringify(argv[1]!.endsWith('build_site.py') ? LIGHT_SUMMARY : { ok: true, result: { id: 'T-0001' } }) }
  }
  const write = registeredTool('mcp__research-tree__research_db')
  for (let i = 0; i < 3; i += 1) {
    expect((await write(host, { method: 'update_task', kwargs: { task_id: 'T-0001', status: 'in_progress' } } as never)).isError).toBeUndefined()
  }
  expect(calls.filter(argv => argv[1]!.endsWith('build_site.py'))).toHaveLength(0)
  expect(timers).toHaveLength(1)
  timers.shift()!()
  await new Promise(resolve => setTimeout(resolve, 10))
  expect(calls.filter(argv => argv[1]!.endsWith('build_site.py'))).toHaveLength(1)
  expect(calls.at(-1)).toContain('--summary')
  expect((state.get('summary') as ResearchSummary).counts.go).toBe(null)
  h.clock.after = () => { throw new Error('display closed') }
  expect((await write(host, { method: 'update_task', kwargs: {} } as never)).isError).toBeUndefined()
})

test('file writes see committed document, harness and worktree guards before the deferred display refresh', async () => {
  const { host, state } = uiHost({})
  state.set('summary', LIGHT_SUMMARY)  // the display still says every path is writable
  const timers: (() => void)[] = [], calls: string[][] = []
  const h = host as unknown as {
    clock: { after: (ms: number, fn: () => void) => void };
    process: { run: (argv: string[]) => Promise<unknown> };
    ui: { status: () => void };
  }
  h.clock.after = (_ms, fn) => { timers.push(fn) }
  h.ui.status = () => { throw new Error('display unavailable') }
  const doc = '/w/study/research/p/docs/current.v1.md'
  const harness1 = '/w/study/worktrees/H-0001/harness', harness2 = '/w/study/worktrees/H-0002/harness'
  const current = { frozen_docs: [] as string[], harness: [] as string[] }
  h.process.run = async argv => {
    calls.push(argv)
    if (argv[1]!.endsWith('research_db.py')) {
      if (argv[6] === 'set_document_current') current.frozen_docs.push(doc)
      if (argv[6] === 'update_project') current.harness.push(harness1)
      if (argv[6] === 'create_branch') current.harness.push(harness2)
      return { exitCode: 0, stderr: '', stdout: '{"ok":true,"result":"committed"}' }
    }
    return { exitCode: 0, stderr: '', stdout: JSON.stringify({ ...LIGHT_SUMMARY, guards: current }) }
  }
  let writes = 0
  const next = async () => { writes += 1; return { result: 'ran' } }
  const db = registeredTool('mcp__research-tree__research_db')
  for (const [method, path] of [['set_document_current', doc], ['update_project', `${harness1}/stats.py`], ['create_branch', `${harness2}/stats.py`]]) {
    const committed = await db(host, { method, kwargs: {} } as never)
    expect(committed.isError).toBeUndefined()
    expect(String(committed.result)).toContain('committed')
    for (const tool of ['Write', 'Edit', 'NotebookEdit']) {
      const result = await registeredTool(tool)(host, { file_path: path, notebook_path: path } as never, next)
      expect(result.deny).toContain(method === 'set_document_current' ? '新版本' : '冻结的实验框架')
    }
  }
  expect(writes).toBe(0)
  expect(state.get('summary')).toBe(LIGHT_SUMMARY)
  expect(timers).toHaveLength(1)  // no presentation callback was required for any guard
  const reads = calls.filter(argv => argv[1]!.endsWith('build_site.py'))
  expect(reads).toHaveLength(9)
  for (const argv of reads) expect(argv.slice(2)).toEqual(['--db', LIGHT_SUMMARY.db_path, '--summary'])
  expect((await registeredTool('Write')(host, { file_path: '/w/study/methods/new.py' } as never, next)).deny).toBeUndefined()
  expect(writes).toBe(1)  // an unavailable display does not block an authoritatively permitted path
  timers.shift()!()
  await new Promise(resolve => setTimeout(resolve, 10))
})

test('each file mutation rechecks external guard changes instead of trusting either stale cache outcome', async () => {
  const { host, state } = uiHost({})
  const path = '/w/study/research/p/docs/shared.v1.md'
  state.set('summary', { ...LIGHT_SUMMARY, guards: { frozen_docs: [path], harness: [] } })
  let frozen = false, reads = 0, writes = 0
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  h.process.run = async () => {
    reads += 1
    return { exitCode: 0, stderr: '', stdout: JSON.stringify({ ...LIGHT_SUMMARY, guards: { frozen_docs: frozen ? [path] : [], harness: [] } }) }
  }
  const next = async () => { writes += 1; return { result: 'ran' } }
  for (const tool of ['Write', 'Edit', 'NotebookEdit']) {
    const call = registeredTool(tool)
    for (const state of [false, true, false]) {
      frozen = state  // another session changed the DB, without scheduling our presentation timer
      const result = await call(host, { file_path: path, notebook_path: path } as never, next)
      if (frozen) expect(result.deny).toContain('新版本')
      else expect(result.deny).toBeUndefined()
    }
  }
  expect(reads).toBe(9)
  expect(writes).toBe(6)
})

test('unavailable or invalid authoritative guards fail closed without undoing a successful DB write', async () => {
  const { host, state, files } = uiHost({})
  state.set('summary', LIGHT_SUMMARY)
  const h = host as unknown as {
    clock: { after: () => void };
    process: { run: (argv: string[]) => Promise<unknown> };
  }
  h.clock.after = () => { throw new Error('display timer unavailable') }
  const failures = [
    async () => { throw new Error('guard subprocess unavailable') },
    async () => ({ exitCode: 1, stderr: 'database locked', stdout: '' }),
    ...['not JSON', 'null', '{}',
      JSON.stringify({ ...LIGHT_SUMMARY, guards: { frozen_docs: [] } }),
      JSON.stringify({ ...LIGHT_SUMMARY, guards: { frozen_docs: [42], harness: [] } }),
      JSON.stringify({ ...LIGHT_SUMMARY, guards: { frozen_docs: [], harness: ['relative/path'] } }),
      JSON.stringify({ ...LIGHT_SUMMARY, db_path: '/another/research_tree.db' }),
    ].map(stdout => async () => ({ exitCode: 0, stderr: '', stdout })),
  ]
  let writes = 0
  const next = async () => { writes += 1; return { result: 'ran' } }
  const db = registeredTool('mcp__research-tree__research_db')
  for (const failure of failures) {
    h.process.run = async argv => argv[1]!.endsWith('research_db.py')
      ? { exitCode: 0, stderr: '', stdout: '{"ok":true,"result":"committed"}' } : failure()
    const committed = await db(host, { method: 'set_document_current', kwargs: {} } as never)
    expect(committed.isError).toBeUndefined()
    expect(String(committed.result)).toContain('committed')
    for (const tool of ['Write', 'Edit', 'NotebookEdit']) {
      const result = await registeredTool(tool)(host, { file_path: '/w/study/new.py', notebook_path: '/w/study/new.ipynb' } as never, next)
      expect(result.deny).toContain('无法核验最新的研究文件保护状态')
    }
    expect(state.get('summary')).toBe(LIGHT_SUMMARY)
  }
  files.delete('/w/study/.venv/bin/python')
  expect((await registeredTool('Write')(host, { file_path: '/w/study/new.py' } as never, next)).deny).toContain('无法核验')
  // a subagent's configuration write is refused without reading the database
  expect((await registeredTool('Write')(host, { agentId: 'w1', file_path: '/w/study/research-tree.yaml' } as never, next)).deny).toContain('按用户指示的 RLD')
  expect(writes).toBe(0)
})

test('file guard discovers an uncached project and refuses unreadable markers while allowing nonproject files', async () => {
  const { host, state, files } = uiHost({})
  const project = state.get('project')
  const path = '/w/study/research/p/docs/discovered.v1.md'
  state.delete('project')
  files.set('/w/study/.research-tree.json', JSON.stringify(project))
  let reads = 0, writes = 0
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  h.process.run = async () => {
    reads += 1
    return { exitCode: 0, stderr: '', stdout: JSON.stringify({ ...LIGHT_SUMMARY, guards: { frozen_docs: [path], harness: [] } }) }
  }
  const next = async () => { writes += 1; return { result: 'ran' } }
  const write = registeredTool('Write')
  expect((await write(host, { file_path: path } as never, next)).deny).toContain('新版本')
  expect(reads).toBe(1)
  state.delete('project')
  files.set('/w/study/.research-tree.json', '{invalid marker')
  expect((await write(host, { file_path: path } as never, next)).deny).toContain('无法核验')
  state.delete('project')
  files.delete('/w/study/.research-tree.json')
  expect((await write(host, { file_path: '/w/study/new.py' } as never, next)).deny).toBeUndefined()
  expect(reads).toBe(1)
  expect(writes).toBe(1)
})

test('review start and collection use immediate durable tickets without opening a UI', async () => {
  const { host, spawns } = uiHost({})
  const calls: string[][] = []
  const h = host as unknown as { clock: { after: (ms: number, fn: () => void) => void }; process: { run: (argv: string[]) => Promise<unknown> } }
  h.clock.after = () => undefined
  h.process.run = async argv => {
    calls.push(argv)
    return { exitCode: 0, stderr: '', stdout: '{"ok":true,"pending":true,"ticket":"RJ-0123456789ab"}' }
  }
  const review = registeredTool('mcp__research-tree__research_review')
  const started = await review(host, { kind: 'code_review', brief: 'docs/review.v1.md', about: 'H-0001' } as never)
  expect(started.isError).toBeUndefined()
  expect(String(started.result)).toContain('RJ-0123456789ab')
  const first = calls.find(a => a[1]!.endsWith('review_call.py'))!
  expect(first).toContain('--background')
  expect(first[first.indexOf('--wait-s') + 1]).toBe('0')
  const collected = await review(host, { ticket: 'RJ-0123456789ab' } as never)
  expect(collected.isError).toBeUndefined()
  expect(calls.at(-1)).not.toContain('--background')
  expect(calls.at(-1)![calls.at(-1)!.indexOf('--wait-s') + 1]).toBe('0')
  const bad = await review(host, { ticket: 'RJ-0123456789ab', kind: 'code_review' } as never)
  expect(bad.isError).toBe(true)
  expect(spawns).toEqual([])
})

test('Architect is confirmation-gated and root-only; root-worker aliases are rejected', async () => {
  const { host, state } = uiHost({})
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  h.process.run = async argv => ({ exitCode: 0, stderr: '', stdout: JSON.stringify(argv[1]!.endsWith('build_site.py')
    ? LIGHT_SUMMARY : { ok: true, result: [] }) })
  type Hook = (host: never, event: never, next: (event: never) => Promise<Record<string, unknown>>) => Promise<Record<string, unknown>>
  let spawn: Hook | undefined, complete: Hook | undefined
  register(((event: string, fn: Hook) => {
    if (event === 'agent.spawn') spawn = fn
    if (event === 'turn.complete') complete = fn
  }) as never, {})
  const next = async () => ({ agentId: 'architect-root', model: 'fixture' })
  state.set('project', { format_version: 3, project_id: 'p', phase: 'planning', root: '/w/study/research/p', db: LIGHT_SUMMARY.db_path })
  expect((await spawn!(host, { subagentType: 'research-tree:architect', prompt: '你是 architect/root' } as never, next)).deny).toContain('尚未经用户确认')
  state.set('project', { format_version: 3, project_id: 'p', phase: 'confirmed', root: '/w/study/research/p', db: LIGHT_SUMMARY.db_path })
  expect((await spawn!(host, { subagentType: 'research-tree:architect', prompt: '你是 architect/h1' } as never, next)).deny).toContain('根节点')
  expect((await spawn!(host, { subagentType: 'research-tree:architect', prompt: '你是 architect/root' } as never, next)).agentId).toBe('architect-root')
  expect((state.get('agents') as Record<string, string>)['architect-root']).toBe('architect/root')
  expect((await spawn!(host, { subagentType: 'research-tree:worker', prompt: '你是 worker/root' } as never, next)).deny).toContain('worker仅负责假说节点')
  expect((await spawn!(host, { subagentType: 'research-tree:architect', prompt: '你是 architect/root' } as never, next)).deny).toContain('已有会话')
  await complete!(host, { agentId: 'architect-root' } as never, async () => ({}))
  // a finished turn does not free the node: its session is continued, or a stopped one explicitly taken over
  expect((await spawn!(host, { subagentType: 'research-tree:architect', prompt: '你是 architect/root' } as never, next)).deny).toContain('SendMessage')
  expect((await spawn!(host, { subagentType: 'research-tree:architect', prompt: '你是 architect/root。接手会话 architect-root' } as never, next)).agentId).toBe('architect-root')
})

test('fast planning has per-candidate admission, lightweight design and final confirmation after screening', () => {
  const project = { format_version: 3, project_id: 'p', root: '/r/p', plan_instruction: { path: 'project/plan.v1.md' } } as Parameters<typeof internals.planningPrompt>[0]
  const effective = { version: 3,
    platform: { dev: 'local', experiment: 'CPU', skills: [] }, budget: { per_run: { nodes: 1, walltime: 10 }, screen_node_h: 1 }, models: {} }
  const view = { effective, db_fields: { gate_seeds: 3, seeds: [1, 2, 3] } } as unknown as Parameters<typeof internals.planningPrompt>[2]
  const prompt = internals.planningPrompt(project, '/plug', view)
  expect(prompt).toContain('gate --candidate')
  expect(prompt).toContain('A就绪即可执行')
  expect(prompt).toContain('资源上限、停止与继续条件')
  expect(prompt).toContain('research-tree:architect')
  expect(prompt).toContain('主会话的明确确认同样有效')
  expect(prompt).not.toContain('D5 查新')
  expect(internals.workerPrompt(effective as never)).toContain('不逐次等待新模型代码审查')
  for (const text of [prompt, internals.workerPrompt(effective as never), internals.WORKFLOW]) {
    for (const removed of ['workflow.mode', 'discovery.mode', 'strict/旧项目', 'research-tree:lens', 'D5 查新']) expect(text).not.toContain(removed)
  }
  expect(prompt).toContain('assign_architect')
  expect(prompt).toContain('proposals/*.json')
  expect(prompt).toContain('version 3')
  expect(internals.statusText(LIGHT_SUMMARY)).toContain('未核验')
  expect(internals.statusLine(LIGHT_SUMMARY, { phase: 'confirmed' } as never)).toContain('未核验')
})

test('main-session confirmation authorizes Architect without opening or starting UI', async () => {
  const { host, state, files, spawns, prompts } = uiHost({})
  const project = { format_version: 3, project_id: 'p', phase: 'awaiting_confirmation', root: '/w/study/research/p', db: LIGHT_SUMMARY.db_path }
  state.set('project', project)
  files.set('/w/study/.research-tree.json', JSON.stringify(project))
  const calls: string[][] = []
  const h = host as unknown as {
    process: { run: (argv: string[]) => Promise<unknown> };
    agent: { register?: (value: unknown) => Promise<void> };
    ui: { open: () => Promise<void> };
  }
  h.agent.register = async () => undefined
  h.ui.open = async () => { throw new Error('confirmation must not open UI') }
  h.process.run = async argv => {
    calls.push(argv)
    if (argv[2] === 'phase') files.set('/w/study/.research-tree.json', JSON.stringify({ ...project, phase: 'confirmed' }))
    const conf = { models: { ui: { model: 'fixture' }, worker: { model: 'fixture' } }, platform: { dev: 'local', experiment: 'CPU', skills: [] } }
    return { exitCode: 0, stderr: '', stdout: argv[1]!.endsWith('build_site.py') ? JSON.stringify(LIGHT_SUMMARY)
      : argv[1]!.endsWith('send_message.py') ? '{"id":"ui--ui-0001","type":"instruction"}'
      : JSON.stringify({ ok: true, result: argv[2] === 'instruction' ? { doc_id: 'D-0020', path: 'project/instructions/confirm.v1.md' }
        : argv[2] === 'config' ? { effective: conf } : {} }) }
  }
  const words = '同意这个最小范围计划'
  const answer = await internals.confirmPlan(host, { actor: 'rld/main' }, words)
  expect(answer).toContain('Experiment Architect')
  expect((state.get('project') as { phase: string }).phase).toBe('confirmed')
  expect(calls.find(argv => argv[2] === 'instruction')).toContain(words)
  expect(prompts[0]).toContain('research-tree:architect')
  expect(spawns).toEqual([])
})


test('unsupported project formats are refused without writes or role launches', async () => {
  const { host, state, files, spawns, prompts } = uiHost({})
  state.delete('project')
  const marker = JSON.stringify({ project_id: 'legacy', phase: 'confirmed', root: '/w/study/research/legacy', db: '/w/study/research/legacy/research_tree.db' })
  files.set('/w/study/.research-tree.json', marker)
  const before = [...files.entries()]
  let writes = 0
  const result = await registeredTool('Write')(host, { file_path: '/w/study/new.py' } as never,
    async () => { writes += 1; return { result: 'written' } })
  expect(result.deny).toContain('UNSUPPORTED_PROJECT_VERSION')
  expect(writes).toBe(0)
  expect([...files.entries()]).toEqual(before)
  expect(spawns).toEqual([])
  expect(prompts).toEqual([])
})

test('removed persisted actor identities never fall back to a writable role', async () => {
  const { host, state } = uiHost({})
  let calls = 0
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  h.process.run = async () => { calls += 1; return { exitCode: 0, stdout: '{}', stderr: '' } }
  for (const actor of ['assistant/lens_old', 'assistant/web_builder', 'worker/root', 'architect/h1']) {
    state.set('agents', { stale: actor })
    const db = await registeredTool('mcp__research-tree__research_db')(host, { agentId: 'stale', method: 'get' } as never)
    expect(db.isError).toBe(true)
    expect(String(db.result)).toContain('不支持的研究身份')
    const write = await registeredTool('Write')(host, { agentId: 'stale', file_path: '/tmp/x' } as never,
      async () => { calls += 1; return { result: 'written' } })
    expect(write.deny).toContain('不支持的研究身份')
    expect(internals.subagentCallBlock(internals.researchCalls(`python research_db.py --actor ${actor} get '{}'`), actor)).toContain('不支持的研究身份')
  }
  expect(calls).toBe(0)
})


test('deprecated configurable main actors are rejected rather than reinterpreted', () => {
  let refused = 0
  for (const actor of ['rld/main', 'worker/root', 'architect/root']) {
    try { register((() => undefined) as never, { actor } as never) }
    catch (error) {
      expect(String(error)).toContain('UNSUPPORTED_ROLE_CONFIGURATION')
      refused += 1
    }
  }
  expect(refused).toBe(3)
})

test('shell writes face the same authoritative document and harness guards as Edit and Write', async () => {
  const { host, state } = uiHost({})
  state.set('agents', { 'bound-worker': 'worker/h1' })
  const doc = '/w/study/research/p/docs/project/goal.v1.md', harness = '/w/study/worktrees/H-0001/harness'
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  let reads = 0, available = true
  h.process.run = async () => {
    reads += 1
    return available ? { exitCode: 0, stderr: '', stdout: JSON.stringify({ ...LIGHT_SUMMARY, guards: { frozen_docs: [doc], harness: [harness] } }) }
      : { exitCode: 1, stderr: 'database locked', stdout: '' }
  }
  let ran = 0
  const next = async () => { ran += 1; return { result: 'ran' } }
  const bash = registeredTool('Bash')
  for (const agentId of [undefined, 'bound-worker']) {
    for (const command of [
      'echo x >> research/p/docs/project/goal.v1.md',  // relative to the session directory
      `cd /tmp && echo x > ${doc}`, `sed -i s/a/b/ ${harness}/stats.py`, `sed -Ei.bak s/a/b/ ${harness}/stats.py`,
      `sed --in-place -e s/a/b/ ${doc}`, `perl -pi -e s/a/b/ ${doc}`, `echo x | tee -a ${harness}/stats.py`,
      `dd if=/dev/zero of=${doc} count=1`, `truncate -s 0 ${doc}`, `rm -f ${doc}`, `mv ${doc} /tmp/goal.md`,
      `cp /tmp/goal.md ${doc}`, `cp /tmp/stats.py ${harness}/`, 'cp -t /w/study/research/p/docs/project /tmp/goal.v1.md',
    ]) {
      expect((await bash(host, { agentId, command } as never, next)).deny).toMatch(/新版本|冻结的实验框架/)
    }
  }
  expect(ran).toBe(0)
  for (const command of [`cp ${doc} /tmp/goal-copy.md`, `cat ${doc} > /tmp/goal-copy.md`, `sed -n 1p ${harness}/stats.py`,
    'python train.py > /w/study/worktrees/H-0001/methods/log.txt 2>/dev/null']) {
    expect((await bash(host, { command } as never, next)).deny).toBeUndefined()
  }
  expect(ran).toBe(4)
  const before = reads
  expect((await bash(host, { command: 'ls -l > /dev/null' } as never, next)).deny).toBeUndefined()
  expect(reads).toBe(before)  // nothing written: no guard read
  available = false  // fail closed, as Edit and Write do
  expect((await bash(host, { command: 'echo x > /w/study/notes.txt' } as never, next)).deny).toContain('无法核验')
  expect((await bash(host, { command: 'git status' } as never, next)).deny).toBeUndefined()
})

test('one session per node: a bound session is continued, a takeover is explicit and leaves the old session no identity', async () => {
  const { host, state } = uiHost({})
  const binding: { worker: string | null } = { worker: null }
  const dbCalls: string[][] = []
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> }; agent: { list?: () => Promise<{ id: string; status: string }[]> } }
  h.process.run = async argv => {
    if (argv[1]!.endsWith('research_db.py')) {
      dbCalls.push(argv)
      if (argv[6] === 'bind_worker_session') binding.worker = (JSON.parse(argv[7]!) as { agent_id: string }).agent_id
      return { exitCode: 0, stderr: '', stdout: '{"ok":true,"result":"done"}' }
    }
    return { exitCode: 0, stderr: '', stdout: JSON.stringify(argv[1]!.endsWith('build_site.py')
      ? { ...LIGHT_SUMMARY, nodes: [{ ...LIGHT_SUMMARY.nodes[0], worker: { id: 'h1', agent_id: binding.worker, session_at: null, resume: [] } }] }
      : { ok: true, result: [] }) }
  }
  type Hook = (host: never, event: never, next: (event: never) => Promise<Record<string, unknown>>) => Promise<Record<string, unknown>>
  let spawn: Hook | undefined
  register(((event: string, fn: Hook) => { if (event === 'agent.spawn') spawn = fn }) as never, {})
  const start = (prompt: string, agentId: string, extra: Record<string, unknown> = {}) =>
    spawn!(host, { subagentType: 'research-tree:worker', prompt, ...extra } as never, async () => ({ agentId, model: 'fixture' }))
  // the identity opens the task and ends before punctuation; a later mention is not it
  expect((await start('接手 worker/h1 的分支；你是 worker/h2', 'w-x')).deny).toContain('开头')
  expect((await start('You are worker/h1.', 'w-old')).agentId).toBe('w-old')
  expect(binding.worker).toBe('w-old')
  expect((state.get('agents') as Record<string, string>)['w-old']).toBe('worker/h1')
  // a subagent inherits the Agent tool but never starts an executor
  expect((await start('你是 worker/h1。接手会话 w-old', 'w-sub', { parentAgentId: 'w-old' })).deny).toContain('只有 RLD')
  // its turn ended: the node's session is continued with SendMessage, not started a second time
  expect((await start('你是 worker/h1。继续 T-0002', 'w-dup')).deny).toContain('SendMessage')
  h.agent.list = async () => [{ id: 'w-old', status: 'running' }]
  expect((await start('你是 worker/h1。接手会话 w-old', 'w-new')).deny).toContain('正在运行')
  h.agent.list = async () => [{ id: 'w-old', status: 'completed' }]
  expect((await start('你是 worker/h1。接手会话 w-ol', 'w-new')).deny).toContain('接手会话 w-old')
  expect((await start('你是 worker/h1。接手会话 w-old，用 resume_package 恢复', 'w-new')).agentId).toBe('w-new')
  expect(binding.worker).toBe('w-new')
  expect(state.get('agents')).toEqual({ 'w-new': 'worker/h1' })
  // the replaced session has no identity left, even where a stale record still names it
  state.set('agents', { 'w-old': 'worker/h1', 'w-new': 'worker/h1' })
  const db = registeredTool('mcp__research-tree__research_db')
  const old = await db(host, { agentId: 'w-old', method: 'update_task', kwargs: {} } as never)
  expect(old.isError).toBe(true)
  expect(String(old.result)).toContain('已绑定')
  const current = await db(host, { agentId: 'w-new', method: 'update_task', kwargs: {} } as never)
  expect(current.isError).toBeUndefined()
  expect(dbCalls.at(-1)!.slice(4, 6)).toEqual(['--actor', 'worker/h1'])
})

test('a message sent while a UI run is starting waits for that run instead of replacing it', async () => {
  const cfg = { actor: 'rld/main' }
  const { host, state, files, spawns, window } = uiHost({})
  type Hook = (host: never, event: never, next: (event: never) => Promise<Record<string, unknown>>) => Promise<Record<string, unknown>>
  let complete: Hook | undefined
  register(((event: string, fn: Hook) => { if (event === 'turn.complete') complete = fn }) as never, {})
  const h = host as unknown as { agent: { spawn: (input: { prompt: string }) => Promise<{ agentId: string }> } }
  const spawn = h.agent.spawn
  let release: () => void = () => undefined
  const starting = new Promise<void>(resolve => { release = resolve })
  h.agent.spawn = async input => { await starting; return spawn(input) }
  const first = internals.askUi(host, cfg, '第一条：现在进度如何？')
  await internals.askUi(host, cfg, '第二条：再加一个 seed')  // arrives while the first run is still starting
  release()
  await first
  expect(spawns).toHaveLength(1)
  expect(spawns[0]).toContain('第一条：现在进度如何？')
  expect(state.get('uiAgentId')).toBe('a1')
  const finish = async (agentId: string, reply: string) => {
    const { run } = state.get('uiRun') as { run: string }
    files.set(`/w/study/research/p/cache/ui/${run}.jsonl`, `${JSON.stringify({ type: 'reply', text: reply })}\n`)
    await complete!(host, { agentId, answer: '', isAborted: false } as never, async () => ({ text: '' }))
  }
  await finish('a1', '进度正常')
  expect(spawns).toHaveLength(2)  // the first run's outbox was carried out; the waiting message got the next run
  expect(spawns[1]).toContain('## 用户的新消息（w-0002）\n第二条：再加一个 seed')
  expect(state.get('uiAgentId')).toBe('a2')
  await finish('a2', '已记下')
  expect(state.get('uiAgentId')).toBe(null)
  expect(window()).toEqual(['第一条：现在进度如何？', '第二条：再加一个 seed', 'UI 还在处理上一条消息；这条已记下，随后处理。', '进度正常', '已记下'])
})

test('a confirmation the user gives in the main conversation is registered verbatim through post_to_ui, never a phase edit', async () => {
  const { host, state, files, prompts, window } = uiHost({})
  const project = { format_version: 3, project_id: 'p', phase: 'awaiting_confirmation', root: '/w/study/research/p', db: LIGHT_SUMMARY.db_path }
  state.set('project', project)
  files.set('/w/study/.research-tree.json', JSON.stringify(project))
  const calls: string[][] = []
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  h.process.run = async argv => {
    calls.push(argv)
    if (argv[2] === 'phase') files.set('/w/study/.research-tree.json', JSON.stringify({ ...project, phase: argv[argv.indexOf('--set') + 1] }))
    const conf = { models: { ui: { model: 'fixture' }, worker: { model: 'fixture' } }, platform: { dev: 'local', experiment: 'CPU', skills: [] } }
    return { exitCode: 0, stderr: '', stdout: argv[1]!.endsWith('build_site.py') ? JSON.stringify(LIGHT_SUMMARY)
      : JSON.stringify({ ok: true, result: argv[2] === 'instruction' ? { doc_id: 'D-0020', path: 'instructions/UI-0001.v1.md' }
        : argv[2] === 'config' ? { effective: conf } : {} }) }
  }
  const post = registeredTool('mcp__research-tree__post_to_ui')
  for (const words of [undefined, '', '  ']) {
    expect((await post(host, { type: 'confirm', text: '用户同意最小范围计划', words } as never)).isError).toBe(true)
  }
  expect((await post(host, { type: 'notice', text: '进展', words: '同意' } as never)).isError).toBe(true)
  expect(calls).toEqual([])
  const words = '同意，按这个最小范围开始'
  const confirmed = await post(host, { type: 'confirm', text: '用户同意最小范围计划', words } as never)
  expect(confirmed.isError).toBeUndefined()
  expect(String(confirmed.result)).toContain('research-tree:architect')  // the start instructions come with the answer
  expect((state.get('project') as { phase: string }).phase).toBe('confirmed')
  const apply = calls.find(argv => argv[2] === 'config' && argv[3] === 'apply')!
  expect(apply[apply.indexOf('--words') + 1]).toBe(words)  // the configuration takes effect on the user's words
  expect(calls.find(argv => argv[2] === 'instruction')).toContain(words)
  expect(prompts).toEqual([])
  expect(window().at(-1)).toContain('D-0020')
  // afterwards, consent to a later request is registered as the user's words of kind 确认
  const later = await post(host, { type: 'confirm', text: '同意追加 10 node·h 预算', words: '可以，加 10 个 node·h' } as never)
  expect(later.isError).toBeUndefined()
  const consent = calls.filter(argv => argv[2] === 'instruction').at(-1)!
  expect(consent[consent.indexOf('--text') + 1]).toBe('可以，加 10 个 node·h')
  expect(consent[consent.indexOf('--kind') + 1]).toBe('确认')
  expect(consent[consent.indexOf('--understanding') + 1]).toBe('同意追加 10 node·h 预算')
  // the phase and the model log are the mod's to write: never from a shell, for any actor
  for (const agentId of [undefined, 'w1']) {
    for (const command of ['python /plug/tools/research_tree.py phase --set confirmed',
      '.venv/bin/python /plug/tools/research_tree.py agent-log --agent main --actor rld/main --event observed --model m']) {
      expect((await registeredTool('Bash')(host, { agentId, command } as never, async () => ({ result: 'ran' }))).deny).toContain('post_to_ui(type=confirm')
    }
  }
})

test('a confirmation request after the plan points to a consent that registers, and the window\'s consent reaches the RLD', async () => {
  const { host, state, files, prompts, window } = uiHost({ r1: '{"type": "reply", "text": "好的，已转交"}\n{"type": "confirm"}\n' })
  files.set('/w/study/.research-tree.json', JSON.stringify(state.get('project')))  // confirmed
  const calls: string[][] = []
  const h = host as unknown as { process: { run: (argv: string[]) => Promise<unknown> } }
  h.process.run = async argv => {
    calls.push(argv)
    return { exitCode: 0, stderr: '', stdout: argv[1]!.endsWith('send_message.py') ? '{"id":"ui--ui-0001","type":"instruction"}'
      : argv.includes('inbox') ? JSON.stringify({ ok: true, result: [{ kind: 'awaiting_reply', id: null, text: 'ui--ui-0001（instruction）尚无RLD回执：…' }] })
      : JSON.stringify({ ok: true, result: argv[2] === 'instruction' ? { doc_id: 'D-0031', path: 'instructions/UI-0003.v1.md' } : { blocked: null } }) }
  }
  const post = registeredTool('mcp__research-tree__post_to_ui')
  expect((await post(host, { type: 'confirm_request', text: '需要追加 10 node·h 预算', docs: ['project/reports/budget.v1.md'] } as never)).isError).toBeUndefined()
  expect(window().at(-1)).toContain('告诉 RLD')
  expect(window().at(-1)).not.toContain('/research-tree confirm')  // that command confirms the start-up plan only
  await internals.carryOutUi(host, { actor: 'rld/main' }, { run: 'r1', message: '同意追加', messageId: 'w-0002', attempt: 1 }, '', false)
  await new Promise(resolve => setTimeout(resolve, 10))  // delivery checks the receipt first
  const consent = calls.find(argv => argv[2] === 'instruction')!
  expect(consent[consent.indexOf('--text') + 1]).toBe('同意追加')
  expect(consent[consent.indexOf('--kind') + 1]).toBe('确认')
  expect(consent[consent.indexOf('--understanding') + 1]).toContain('需要追加 10 node·h 预算')
  expect(calls.some(argv => argv[2] === 'phase' || (argv[2] === 'config' && argv[3] === 'apply'))).toBe(false)
  const relayed = calls.find(argv => argv[1]!.endsWith('send_message.py') && argv.includes('ui/ui') && argv[argv.indexOf('--from') + 1] === 'ui/ui')!
  expect(relayed[relayed.indexOf('--text') + 1]).toContain('D-0031')
  expect(prompts).toHaveLength(1)
  expect(window().at(-1)).toContain('D-0031')
})
