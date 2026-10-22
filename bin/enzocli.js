#!/usr/bin/env node
'use strict';

// Launcher for the Enzo CLI. It finds a Python 3 interpreter, points it at
// ai_cli.py inside this package, and hands the terminal over to the app.
//
// The app is a Textual TUI, so it needs the real terminal: stdio is inherited
// and this wrapper keeps its hands off SIGINT so Ctrl+C reaches the app.

const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const PKG = require('../package.json');

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

function fail(message) {
  console.error('enzo: ' + message);
  process.exit(1);
}

function showHelp() {
  console.log(
    'enzo ' + PKG.version + '\n\n' +
    'Usage: enzo [options]\n\n' +
    'Starts the Enzo CLI in the current directory. The AI can read, write and run\n' +
    'commands there, and nowhere else.\n\n' +
    'Options:\n' +
    '  -v, --version   print the version\n' +
    '  -h, --help      show this help\n\n' +
    'Inside the app, type /help to see every slash command.'
  );
}

function main() {
  const args = process.argv.slice(2);

  if (args.includes('--version') || args.includes('-v')) {
    console.log(PKG.version);
    return;
  }
  if (args.includes('--help') || args.includes('-h')) {
    showHelp();
    return;
  }

  const script = path.join(__dirname, '..', 'ai_cli.py');
  if (!fs.existsSync(script)) {
    fail('ai_cli.py is missing from the package. The install looks broken.');
    return;
  }

  const python = findPython();
  if (!python) {
    fail(
      'Python 3 was not found.\n' +
      '  Termux:   pkg install python\n' +
      '  Debian:   sudo apt install python3\n' +
      '  macOS:    brew install python3\n' +
      '  Windows:  winget install Python.Python.3'
    );
    return;
  }

  const child = spawn(python, [script, ...args], { stdio: 'inherit' });

  child.on('error', (err) => fail('could not start Python: ' + err.message));

  child.on('exit', (code, signal) => {
    if (signal) {
      process.exitCode = 128;
    } else {
      process.exitCode = code === null ? 1 : code;
    }
  });

  // The TUI owns the terminal. Let the child decide what Ctrl+C means.
  process.on('SIGINT', () => {});
  process.on('SIGTERM', () => {});
}

main();
