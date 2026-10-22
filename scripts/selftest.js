#!/usr/bin/env node
'use strict';

// Checks the package is complete and the launcher works.
// Run with: npm test

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
let failed = 0;

function check(label, ok, detail) {
  console.log((ok ? 'ok   ' : 'FAIL ') + label + (detail ? '  -> ' + detail : ''));
  if (!ok) failed++;
}

function run(cmd, args) {
  return spawnSync(cmd, args, { cwd: root, encoding: 'utf8' });
}

// package.json is valid and has the fields npm needs
let pkg = null;
try {
  pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  check('package.json parses', true);
} catch (err) {
  check('package.json parses', false, err.message);
}

if (pkg) {
  check('has a name', typeof pkg.name === 'string' && pkg.name.length > 0, pkg.name);
  check('has a version', /^\d+\.\d+\.\d+/.test(pkg.version || ''), pkg.version);
  check('has a bin entry', !!(pkg.bin && Object.keys(pkg.bin).length));
  check('publishConfig access is public', pkg.publishConfig && pkg.publishConfig.access === 'public');
  check(
    'bin target exists',
    fs.existsSync(path.join(root, pkg.bin.enzo)),
    pkg.bin && pkg.bin.enzo
  );
}

// the files the package ships are all there
for (const file of ['ai_cli.py', 'bin/enzocli.js', 'scripts/setup-deps.py', 'scripts/postinstall.js', 'scripts/publish.js', 'scripts/test_stream.py', 'scripts/test_connect.py']) {
  check('ships ' + file, fs.existsSync(path.join(root, file)));
}

// the launcher answers --version and --help
const version = run(process.execPath, [path.join(root, 'bin/enzocli.js'), '--version']);
check('launcher prints the version', version.status === 0 && version.stdout.trim() === pkg.version, version.stdout.trim());

const help = run(process.execPath, [path.join(root, 'bin/enzocli.js'), '--help']);
check('launcher prints help', help.status === 0 && help.stdout.includes('Usage: enzo'));

// the python app still compiles
const py = run('python3', ['-m', 'py_compile', 'ai_cli.py']);
if (py.error) {
  const py2 = run('python', ['-m', 'py_compile', 'ai_cli.py']);
  check('ai_cli.py compiles', !py2.error && py2.status === 0, py2.stderr);
} else {
  check('ai_cli.py compiles', py.status === 0, py.stderr);
}

// the python tests
for (const [file, label] of [
  ['scripts/test_stream.py', 'streaming text repair works'],
  ['scripts/test_connect.py', 'the /connect panel works'],
]) {
  let result = run('python3', [file]);
  if (result.error) {
    result = run('python', [file]);
  }
  check(label, !result.error && result.status === 0, result.stdout + result.stderr);
}

console.log('');
if (failed) {
  console.log(failed + ' check(s) failed');
  process.exit(1);
}
console.log('all checks passed');
