import { expect, test } from 'claude-code/testing'

import { internals } from '../hooks/register'
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

test('the project configuration is the user\'s: edits and shell writes to it are refused', () => {
  const config = '/w/study/research-tree.yaml'
  expect(internals.guardReason(null, config, config)).toContain('由用户修改')
  expect(internals.guardReason(null, '/w/other/research-tree.yaml', config)).toBeUndefined()
  expect(internals.writesConfig('cat > research-tree.yaml <<EOF\nx\nEOF', config)).toBe(true)
  expect(internals.writesConfig(`sed -i 's/a/b/' ${config}`, config)).toBe(true)
  expect(internals.writesConfig('sed s/a/b/ research-tree.yaml', config)).toBe(false)
  expect(internals.writesConfig('cat research-tree.yaml', config)).toBe(false)
  expect(internals.writesConfig('cp /tmp/x/research-tree.yaml /tmp/y', config)).toBe(false)  // another project's
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
  expect(internals.subagentCallBlock(calls.slice(1), undefined)).toBeUndefined()
  expect(internals.subagentCallBlock(calls, undefined)).toContain('只读')
  expect(internals.subagentCallBlock(internals.researchCalls('python tools/research_tree.py phase --set confirmed'), 'worker/h0001'))
    .toContain('research_tree.py phase')
  expect(internals.subagentCallBlock(internals.researchCalls("python tools/research_tree.py query get '{}'"), undefined)).toBeUndefined()
})

test('a shell command writing the database file is refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: 'ran', stderr: '', interrupted: false } } as never))
  const denied = await $.tool.call({ tool: 'Bash', command: 'rm demo/research/P-x/research_tree.db' })
  expect(denied.deny).toContain('research_db')
  const allowed = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(allowed.isError).toBeUndefined()
})

const RUN = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 160 } }

test('bare config copies through the shared shell helper without a project or Python', async () => {
  const calls: string[][] = []
  const host = {
    plugin: { root: '/plugin root' },
    session: { cwd: async () => '/user project' },
    process: { run: async (argv: string[]) => {
      calls.push(argv)
      return { exitCode: 0, stdout: 'copied\n', stderr: '' }
    } },
  }
  expect(await internals.configCommand(host as never, { actor: 'rld/main' })).toBe('copied')
  expect(calls).toEqual([['sh', '/plugin root/tools/copy_config.sh', '/user project']])
})

test('without a project here the command points to init', async $ => {
  const ran = await $.command.run({ command: 'research-tree', args: '', ...RUN })
  expect(ran.text).toContain('/research-tree init')
})

test('init reads the plan, the Python version and the project id', () => {
  expect(internals.parseInit(['plans/goal.md'])).toEqual({ plan: 'plans/goal.md', python: '3.13' })
  expect(internals.parseInit(['plans/goal.md', '--python', '3.12', '--id', 'my-study']))
    .toEqual({ plan: 'plans/goal.md', python: '3.12', id: 'my-study' })
  expect(internals.parseInit(['--python=3.11', 'goal.md'])).toEqual({ plan: 'goal.md', python: '3.11' })
  expect(internals.parseInit(['goal.md', '--update-uv'])).toEqual({ plan: 'goal.md', python: '3.13', updateUv: true })
  expect(internals.parseInit(['goal.md', '--config', 'cluster.yaml'])).toEqual({ plan: 'goal.md', python: '3.13', config: 'cluster.yaml' })
  for (const bad of [[], ['--python'], ['a.md', 'b.md'], ['a.md', '--python', '--id'], ['a.md', '--venv']]) {
    expect('usage' in internals.parseInit(bad)).toBe(true)
  }
})

test('init needs uv before it touches the directory', async $ => {
  const usage = await $.command.run({ command: 'research-tree', args: 'init', ...RUN })
  expect(usage.text).toContain('用法')
  const ran = await $.command.run({ command: 'research-tree', args: 'init plans/goal.md --python 3.12', ...RUN })
  expect(ran.text).toContain('需要 uv')
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
function uiHost(outboxes: Record<string, string>) {
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
      stdout: argv[1]!.endsWith('send_message.py') ? '{"id":"ui-0001","type":"question"}' : '{"ok": true, "result": []}',
    }) },
    agent: { spawn: async (input: { prompt: string }) => (spawns.push(input.prompt), { agentId: `a${spawns.length}` }) },
    clock: { after: (_ms: number, fn: () => void) => fn() },
    prompt: { submit: async (input: { text: string }) => void prompts.push(input.text) },
    ui: { toast: () => undefined, open: async () => undefined, status: () => undefined },
  }
  const window = () => (files.get(`${root}/messages/window.jsonl`) ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l).text as string)
  return { host: host as never, state, spawns, prompts, window }
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
  expect(spawns.length).toBe(1)
  expect(prompts.length).toBe(1)
  expect(prompts[0]).toContain('post_to_ui(type=reply')
  expect(window().at(-1)).toContain('已把原文转交RLD')
})

test('a UI run that replied, or was interrupted, is not retried', async () => {
  const cfg = { actor: 'rld/main' }
  const { host, spawns, prompts, window } = uiHost({ r1: '{"type": "reply", "text": "已回答"}\n', r2: '' })
  await internals.carryOutUi(host, cfg, { run: 'r1', message: '进度？', attempt: 1 }, '', false)
  await internals.carryOutUi(host, cfg, { run: 'r2', message: '进度？', attempt: 1 }, '', true)
  expect(window()).toEqual(['已回答', '（UI 被中断）'])
  expect([spawns.length, prompts.length]).toEqual([0, 0])
})
