#!/usr/bin/env node
'use strict';

// npm postinstall hook: install the Python packages the CLI needs.
//
// It must never break `npm install`, so every path exits 0. If Python is not
// there yet the user gets a message with the command to run later.

const { spawnSync } = require('child_process');
const path = require('path');

const PYTHON_NAMES = ['python3', 'python'];

function findPython() {
  for (const name of PYTHON_NAMES) {
    const r = spawnSync(
      name,
      ['-c', 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)'],
      { stdio: ['ignore', 'ignore', 'ignore'] }
    );
    if (r.status === 0) return name;
  }
  return null;
}

const python = findPython();

if (!python) {
  console.log('ai-cli: Python 3 not found yet. Install it, then run: pip install textual httpx');
  process.exit(0);
}

const result = spawnSync(python, [path.join(__dirname, 'setup-deps.py')], { stdio: 'inherit' });

if (result.status !== 0) {
  console.log('ai-cli: dependency setup did not finish. Run: pip install textual httpx');
}

process.exit(0);
