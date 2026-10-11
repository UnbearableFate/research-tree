# Claude adapter validation

## Native validation

From the repository root, assemble the current sources and use a supported Claude installation:

```sh
python3 scripts/build_plugins.py --target claude
claude plugin validate dist/claude
claude plugin validate dist/claude/plugins/research-tree
claude plugin test dist/claude/plugins/research-tree
```

The native commands validate the installed host/SDK path. A real-model research scenario is a separate check under the repository's scenario protocol and requires its own authorization and evidence. Do not label fixture tests as native, real-model, or scientific-efficacy validation.

## Deterministic fixture-only runner

When the native Claude SDK is unavailable, the repository script can still execute the callbacks in `tests/register.test.ts` that take no host arguments. These callbacks exercise exported functions and hooks against their own in-memory host fixtures. The runner supplies a small assertion adapter, state helpers and JSX objects; it does not render the host UI.

With Node.js 18 or newer, run both the source adapter and the newly assembled package:

```sh
node scripts/run_claude_fixtures.cjs
python3 scripts/build_plugins.py --target claude
node scripts/run_claude_fixtures.cjs dist/claude/plugins/research-tree
```

A plugin directory or an explicit test file is accepted. The default source location is relative to the script, so it does not depend on the current working directory. Relative arguments are relative to the current working directory.

### Use an already-installed compiler

The runner installs nothing and uses no fixed machine-specific compiler path. It searches ordinary Node module paths, the current workspace, the script/target locations, and the current Node runtime for:

1. An installed Playwright bundle exporting `babelTransform`
2. An installed `@babel/core` with `@babel/preset-typescript`, `@babel/plugin-transform-react-jsx`, and `@babel/plugin-transform-modules-commonjs`

Point to an existing compiler explicitly when automatic discovery does not match the local setup:

```sh
node scripts/run_claude_fixtures.cjs --compiler /absolute/path/to/babelBundle.js
RESEARCH_TREE_BABEL_MODULE=/absolute/path/to/babelBundle.js node scripts/run_claude_fixtures.cjs
node scripts/run_claude_fixtures.cjs --compiler @babel/core dist/claude/plugins/research-tree
```

An explicit unavailable or incompatible compiler is a setup error; the runner does not silently substitute another compiler. The resolved compiler filename is printed in every run. Playwright's bundled compiler is an internal API, so incompatible versions fail with an actionable setup error rather than claiming a pass. Babel transpilation checks syntax, not TypeScript types.

### Interpret the result

Every executed callback is labeled `FIXTURE-ONLY PASS` or `FIXTURE-ONLY FAIL`. Callbacks with native host arguments are listed individually as `NATIVE-SDK-NOT-RUN`. The final line reports passed, failed, unrun native callbacks, and the total registered count; use those actual counts rather than a fixed historical total.

- Exit `0`: the selected deterministic fixture callbacks passed; native validation remains **NOT RUN**
- Exit `1`: a fixture assertion failed or a callback timed out
- Exit `2`: setup, compiler, argument, or test-loading failure

Each fixture has a 10-second default deadline, configurable with `--timeout-ms`. A timeout aborts the run and explicitly leaves remaining callbacks unrun. The harness executes trusted repository test code and is not a sandbox. Unsupported test/assertion APIs fail instead of being silently ignored.

The fixture runner does **not** validate the native Claude SDK, native UI rendering/events, SDK type compatibility, plugin installation, real-model calls, real research scenarios, or scientific search quality. Keep those statuses separate even when both source and packaged fixture runs pass.
