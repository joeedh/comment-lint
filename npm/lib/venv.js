'use strict';
// Creates and reuses a venv keyed by the hash of requirements-runtime.txt, so
// installs with identical dependencies share one venv across every project
// and every copy of the bundled release that pins the same versions.
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const { findBasePython } = require('./pyfind');

const MARKER = 'install-complete';
const LOCK_RETRY_MS = 500;
const LOCK_TIMEOUT_MS = 5 * 60 * 1000;

function commentlintHome() {
  return process.env.COMMENTLINT_HOME || path.join(os.homedir(), '.commentlint');
}

function hashRequirements(requirementsPath) {
  const bytes = fs.readFileSync(requirementsPath);
  return crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 8);
}

function venvDirFor(requirementsPath) {
  const hash = hashRequirements(requirementsPath);
  return path.join(commentlintHome(), 'pylib', hash);
}

function venvPython(venvDir) {
  return process.platform === 'win32'
    ? path.join(venvDir, 'Scripts', 'python.exe')
    : path.join(venvDir, 'bin', 'python');
}

function sleepSync(ms) {
  const buf = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(buf), 0, 0, ms);
}

function acquireLock(venvDir) {
  const lockDir = venvDir + '.lock';
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  for (;;) {
    try {
      fs.mkdirSync(lockDir, { recursive: true });
      return lockDir;
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
      if (Date.now() > deadline) {
        throw new Error(`commentlint: timed out waiting for venv lock at ${lockDir}`);
      }
      sleepSync(LOCK_RETRY_MS);
    }
  }
}

function releaseLock(lockDir) {
  fs.rmSync(lockDir, { recursive: true, force: true });
}

function ensureVenv(requirementsPath, { forceInstall = false } = {}) {
  const venvDir = venvDirFor(requirementsPath);
  const markerPath = path.join(venvDir, MARKER);
  if (!forceInstall && fs.existsSync(markerPath)) {
    return venvDir;
  }

  const lockDir = acquireLock(venvDir);
  try {
    if (!forceInstall && fs.existsSync(markerPath)) {
      return venvDir; // another process finished while we waited on the lock
    }

    if (!fs.existsSync(venvDir)) {
      const base = findBasePython();
      if (!base) {
        throw new Error(
          'commentlint: no Python interpreter found (looked for py -3, python3, python)'
        );
      }
      const created = spawnSync(base.cmd, [...base.args, '-m', 'venv', venvDir], {
        stdio: 'inherit',
      });
      if (created.status !== 0) {
        throw new Error(`commentlint: failed to create venv at ${venvDir}`);
      }
    }

    const installed = spawnSync(
      venvPython(venvDir),
      ['-m', 'pip', 'install', '-q', '-r', requirementsPath],
      { stdio: 'inherit' }
    );
    if (installed.status !== 0) {
      throw new Error(`commentlint: failed to install dependencies into ${venvDir}`);
    }
    fs.writeFileSync(markerPath, '');
    return venvDir;
  } finally {
    releaseLock(lockDir);
  }
}

module.exports = { commentlintHome, hashRequirements, venvDirFor, venvPython, ensureVenv };
