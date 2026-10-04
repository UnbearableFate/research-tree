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

test('a shell command writing the database file is refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: 'ran', stderr: '', interrupted: false } } as never))
  const denied = await $.tool.call({ tool: 'Bash', command: 'rm demo/research/P-x/research_tree.db' })
  expect(denied.deny).toContain('research_db')
  const allowed = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(allowed.isError).toBeUndefined()
})

const RUN = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: true, columns: 160 } }

test('without a project here the command points to init', async $ => {
  const ran = await $.command.run({ command: 'research-tree', args: '', ...RUN })
  expect(ran.text).toContain('/research-tree init')
})

test('init reads the plan, the Python version and the project id', () => {
  expect(internals.parseInit(['plans/goal.md'])).toEqual({ plan: 'plans/goal.md', python: '3.13' })
  expect(internals.parseInit(['plans/goal.md', '--python', '3.12', '--id', 'my-study']))
    .toEqual({ plan: 'plans/goal.md', python: '3.12', id: 'my-study' })
  expect(internals.parseInit(['--python=3.11', 'goal.md'])).toEqual({ plan: 'goal.md', python: '3.11' })
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

test('only the UI agent records a confirmation', async $ => {
  const ran = await $.tool.call({ tool: 'mcp__research-tree__confirm_plan', words: '同意' } as never)
  expect(ran.isError).toBe(true)
  expect(String(ran.result)).toContain('只能由研究对话窗口的 UI agent')
})

test('the UI window hands the message to a UI agent run with the conversation', async ($, on) => {
  const spawns: { type?: string; prompt: string }[] = []
  on('agent.spawn', ($, e) => {
    // Beneath the plugins the spawn arrives as the Agent tool's input (subagent_type). Only the real
    // engine starts a run and sets agentId, so the answer path (turn.complete) needs a live session.
    spawns.push({ type: (e as unknown as { subagent_type?: string }).subagent_type ?? e.subagentType, prompt: e.prompt })
    return { model: 'test-model' }
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...UI, surface })
    expect(await ui.find({ type: 'Text', text: /还没有消息/ })).toBeDefined()
    await ui.unmount()
  }

  const ui = await $.ui.mount({ ...UI, surface: 'terminal' })
  await ui.input({ key: 'ask', text: '现在进度如何？' })
  await ui.input({ key: 'ask', text: '只看GO候选' })
  expect(spawns.map(s => s.type)).toEqual(['research-tree:ui', 'research-tree:ui'])
  expect(spawns[0]?.prompt).toContain('## 用户的新消息\n现在进度如何？')
  expect(spawns[0]?.prompt).toContain('User Interface（UI）agent')
  expect(spawns[0]?.prompt).toContain('当前目录没有研究项目')
  // The second run sees the first message in the recent conversation.
  expect(spawns[1]?.prompt).toContain('[user] 现在进度如何？')
  expect(await ui.find({ type: 'Text', text: /只看GO候选/ })).toBeDefined()
  await ui.unmount()
})

test('the main model is never offered the UI agent', async $ => {
  const offered = await $.agent.offer({
    agent: 'research-tree:ui', description: 'UI', source: 'plugin',
    provider: { plugin: 'research-tree', tier: 'user' },
  } as never)
  expect(offered.isOffered).toBe(false)
})
