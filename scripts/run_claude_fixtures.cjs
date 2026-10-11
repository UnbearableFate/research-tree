#!/usr/bin/env node
'use strict';

// Runs the zero-argument callbacks in register.test.ts using explicit host fixtures.
// This is NOT the native Claude test runner or a TypeScript type checker.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { createRequire, globalPaths } = require('node:module');
const path = require('node:path');
const vm = require('node:vm');

const HELP = `Usage: node scripts/run_claude_fixtures.cjs [plugin-directory|test-file] [options]

Default target: claude-mod/research-tree/tests/register.test.ts in this repository
Options:
  --compiler MODULE_OR_FILE  Existing Playwright Babel bundle or @babel/core module
                            (also RESEARCH_TREE_BABEL_MODULE; no packages are installed)
  --timeout-ms INTEGER      Deadline for each fixture callback (default: 10000)
  --help                    Show this help

Auto-detection searches normal Node module paths for an installed Playwright Babel
bundle, then @babel/core with its TypeScript, JSX and CommonJS transforms.
Callbacks requesting the native host arguments are printed as NATIVE-SDK-NOT-RUN.
Exit 0 means fixture callbacks passed only; it does not mean native validation passed.
`;

function options(argv) {
  const result = { target: path.resolve(__dirname, '../claude-mod/research-tree'), timeout: 10000,
    compiler: process.env.RESEARCH_TREE_BABEL_MODULE, help: false };
  let positional = false;
  for (let i = 0; i < argv.length; i++) {
    const value = argv[i];
    if (value === '--help' || value === '-h') result.help = true;
    else if (value === '--compiler' || value === '--timeout-ms') {
      const argument = argv[++i];
      if (!argument || argument.startsWith('--')) throw new Error(`${value} needs a value`);
      if (value === '--compiler') result.compiler = argument;
      else {
        result.timeout = Number(argument);
        if (!Number.isSafeInteger(result.timeout) || result.timeout <= 0) throw new Error('--timeout-ms needs a positive integer');
      }
    } else if (value.startsWith('-') || positional) throw new Error(`unexpected argument: ${value}`);
    else { result.target = path.resolve(value); positional = true; }
  }
  return result;
}

function compilerFor(requested, testFile) {
  const search = [...new Set([process.cwd(), __dirname, path.dirname(testFile), path.dirname(process.execPath), ...globalPaths])];
  const resolve = name => require.resolve(name, { paths: search });
  const candidates = [];
  if (requested) candidates.push(path.isAbsolute(requested) || requested.startsWith('.') ? path.resolve(requested) : requested);
  else {
    for (const pkg of ['playwright', 'playwright-core']) {
      try { candidates.push(path.join(path.dirname(resolve(`${pkg}/package.json`)), 'lib/transform/babelBundle.js')); } catch { /* try the next installed compiler */ }
    }
    candidates.push('@babel/core');
  }
  const failures = [];
  for (const candidate of candidates) {
    try {
      const filename = resolve(candidate);
      const babel = require(filename);
      if (typeof babel.babelTransform === 'function') {
        return { filename, transform: (code, file) => babel.babelTransform(code, file, false, [], [])?.code };
      }
      if (typeof babel.transformSync === 'function') {
        const dependency = name => {
          const loaded = require(require.resolve(name, { paths: [path.dirname(filename), ...search] }));
          return loaded.default ?? loaded;
        };
        const typescript = dependency('@babel/preset-typescript');
        const jsx = dependency('@babel/plugin-transform-react-jsx');
        const commonjs = dependency('@babel/plugin-transform-modules-commonjs');
        return { filename, transform: (code, file) => babel.transformSync(code, {
          filename: file, babelrc: false, configFile: false, sourceMaps: false,
          presets: /\.[cm]?tsx?$/.test(file) ? [[typescript, { allExtensions: true, isTSX: file.endsWith('.tsx'), allowDeclareFields: true }]] : [],
          plugins: [[jsx, { runtime: 'automatic' }], commonjs],
        })?.code };
      }
      throw new Error('module exports neither babelTransform nor transformSync');
    } catch (error) { failures.push(`${candidate}: ${error.message}`); }
  }
  throw new Error(`No usable installed compiler. Set --compiler or RESEARCH_TREE_BABEL_MODULE to an existing compatible module.\n${failures.join('\n')}`);
}

function expect(value, negate = false) {
  const check = (condition, message) => assert.ok(negate ? !condition : condition, message);
  return {
    get not() { return expect(value, !negate); },
    toBe(expected) { check(Object.is(value, expected), `Actual ${JSON.stringify(value)}, ${negate ? 'not expected' : 'expected'} ${JSON.stringify(expected)}`); },
    toEqual(expected) {
      let same = true;
      try { assert.deepStrictEqual(value, expected); } catch { same = false; }
      check(same, `Actual ${JSON.stringify(value)}, ${negate ? 'not expected' : 'expected'} ${JSON.stringify(expected)}`);
    },
    toBeDefined() { check(value !== undefined, 'Expected defined'); },
    toBeUndefined() { check(value === undefined, `Expected undefined, got ${JSON.stringify(value)}`); },
    toContain(expected) {
      assert.ok(typeof value === 'string' || Array.isArray(value), 'toContain requires a string or array');
      check(value.includes(expected), `${JSON.stringify(value)} ${negate ? 'must not contain' : 'must contain'} ${JSON.stringify(expected)}`);
    },
    toMatch(expected) {
      assert.equal(typeof value, 'string', 'toMatch requires a string');
      check(expected instanceof RegExp ? expected.test(value) : value.includes(expected), `${JSON.stringify(value)} ${negate ? 'must not match' : 'must match'} ${expected}`);
    },
    toHaveLength(expected) { check(value.length === expected, `Length ${value.length}, expected ${expected}`); },
    toBeLessThanOrEqual(expected) { check(value <= expected, `${value} <= ${expected}`); },
  };
}

function collect(testFile, compiler) {
  const tests = [], cache = new Map();
  function load(filename) {
    filename = path.resolve(filename);
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = { filename, exports: {} };
    cache.set(filename, module);
    const transformed = compiler.transform(fs.readFileSync(filename, 'utf8'), filename);
    if (typeof transformed !== 'string') throw new Error(`Compiler returned no JavaScript for ${filename}`);
    const nativeRequire = createRequire(filename);
    const fixtureRequire = name => {
      if (name === 'claude-code/testing') return { expect, test: (title, fn) => {
        assert.equal(typeof fn, 'function', `test ${title} requires a callback`);
        tests.push({ title, fn });
      } };
      if (name === 'claude-code') return {
        atom: (ref, initial) => ({ ...ref, initial }),
        read: async ($, ref) => (await $.state.get(ref)).value ?? ref.initial,
        update: async ($, ref, fn) => $.state.set(ref, fn((await $.state.get(ref)).value ?? ref.initial)),
      };
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
      if (name.startsWith('.')) {
        const full = path.resolve(path.dirname(filename), name);
        const resolved = [full, ...['.tsx', '.ts', '.js', '.cjs'].map(ext => full + ext),
          ...['index.tsx', 'index.ts', 'index.js'].map(base => path.join(full, base))]
          .find(file => fs.existsSync(file) && fs.statSync(file).isFile());
        if (resolved && /\.[cm]?[jt]sx?$/.test(resolved)) return load(resolved);
      }
      return nativeRequire(name);
    };
    const wrapper = new vm.Script(`(function(require, exports, module, __filename, __dirname){${transformed}\n})`, { filename }).runInThisContext();
    wrapper(fixtureRequire, module.exports, module, filename, path.dirname(filename));
    return module.exports;
  }
  load(testFile);
  if (!tests.length) throw new Error(`No test callbacks registered in ${testFile}`);
  return tests;
}

async function main() {
  const config = options(process.argv.slice(2));
  if (config.help) { console.log(HELP); return; }
  const testFile = fs.statSync(config.target).isDirectory() ? path.join(config.target, 'tests/register.test.ts') : config.target;
  const compiler = compilerFor(config.compiler, testFile);
  console.log(`FIXTURE-ONLY: ${testFile}\nNode: ${process.version}\nCompiler: ${compiler.filename}`);
  console.log('LIMITATIONS: no native Claude SDK, host UI, TypeScript typechecking, installation smoke, or real-model scenarios are validated');
  const tests = collect(testFile, compiler);
  let passed = 0, failed = 0, skipped = 0;
  for (const { title, fn } of tests) {
    if (fn.length) { console.log(`NATIVE-SDK-NOT-RUN ${title}`); skipped++; continue; }
    const deadline = setTimeout(() => {
      console.error(`FIXTURE-ONLY TIMEOUT after ${config.timeout}ms: ${title}; remaining callbacks were not run`);
      process.exit(1);
    }, config.timeout);
    try { await fn(); console.log(`FIXTURE-ONLY PASS ${title}`); passed++; }
    catch (error) { console.error(`FIXTURE-ONLY FAIL ${title}\n${error.stack || error}`); failed++; }
    finally { clearTimeout(deadline); }
  }
  console.log(`FIXTURE-ONLY RESULT: ${passed} passed, ${failed} failed; ${skipped} NATIVE-SDK-NOT-RUN; ${tests.length} registered callbacks`);
  console.log('Native validation remains NOT RUN, including when this fixture-only command exits 0');
  process.exitCode = failed ? 1 : 0;
}

main().catch(error => { console.error(`FIXTURE-ONLY SETUP ERROR: ${error.stack || error}`); process.exitCode = 2; });
