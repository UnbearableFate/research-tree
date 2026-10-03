import { expect, test } from 'claude-code/testing'

import { internals } from '../hooks/register'
import type { ResearchSummary } from '../types'

const PANE_PROPS = {
  title: '研究对话（UI）', isFocused: true, bodyColumns: 80, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 30 }, view: {},
}
const UI = { plugin: 'research-agent', component: 'Pane' as const, requestId: 'research-ui', props: PANE_PROPS }

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

test('only direct writes to the database file count as database writes', () => {
  expect(internals.writesDatabase('rm demo/research/P-x/research_tree.db')).toBe(true)
  expect(internals.writesDatabase('sqlite3 research_tree.db "delete from x"')).toBe(true)
  expect(internals.writesDatabase('cp backup.db research_tree.db')).toBe(true)
  expect(internals.writesDatabase('ls -l research_tree.db')).toBe(false)
  expect(internals.writesDatabase('.venv/bin/python tools/research_db.py --db research_tree.db decide "{}" > out.json')).toBe(false)
  expect(internals.writesDatabase('rm -rf build/')).toBe(false)
})

test('a shell command writing the database file is refused', async ($, on) => {
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: 'ran', stderr: '', interrupted: false } } as never))
  const denied = await $.tool.call({ tool: 'Bash', command: 'rm demo/research/P-x/research_tree.db' })
  expect(denied.deny).toContain('research_db')
  const allowed = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(allowed.isError).toBeUndefined()
})

test('without a configured project the command says what to set', { options: { projectDb: '' } }, async $ => {
  const ran = await $.command.run({
    command: 'research', args: '', origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 160 },
  })
  expect(ran.text).toContain('projectDb 未配置')
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
  expect(spawns.map(s => s.type)).toEqual(['research-agent:ui', 'research-agent:ui'])
  expect(spawns[0]?.prompt).toContain('## 用户的新消息\n现在进度如何？')
  expect(spawns[0]?.prompt).toContain('User Interface（UI）agent')
  // The second run sees the first message in the recent conversation.
  expect(spawns[1]?.prompt).toContain('[user] 现在进度如何？')
  expect(await ui.find({ type: 'Text', text: /只看GO候选/ })).toBeDefined()
  await ui.unmount()
})

test('the main model is never offered the UI agent', async $ => {
  const offered = await $.agent.offer({
    agent: 'research-agent:ui', description: 'UI', source: 'plugin',
    provider: { plugin: 'research-agent', tier: 'user' },
  } as never)
  expect(offered.isOffered).toBe(false)
})
