#!/usr/bin/env node
'use strict';
// Resolution order: own flags, then local-defer, then config, then
// system-defer, then a Python root is resolved (fetched ref, bundled vendor,
// or the repo root in dev), a venv is ensured against it, and predict.py runs.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const { findLocalInstall } = require('../lib/find-local');
const { findSystemInstall } = require('../lib/find-system');
const { readNpmConfig } = require('../lib/config');
const { ensureFetched } = require('../lib/fetch');
const { ensureVenv, venvPython } = require('../lib/venv');

const SELF_PATH = __filename;
const PACKAGE_DIR = path.resolve(__dirname, '..');

function runPython(pyRoot, args) {
  const requirementsPath = path.join(pyRoot, 'requirements-runtime.txt');
  const venvDir = ensureVenv(requirementsPath);
  const result = spawnSync(venvPython(venvDir), [path.join(pyRoot, 'predict.py'), ...args], {
    stdio: 'inherit',
  });
  process.exit(result.status === null ? 1 : result.status);
}

async function resolvePyRoot(npmConfig) {
  if (npmConfig.fetch && npmConfig.fetch.ref) {
    return ensureFetched(npmConfig.fetch.ref);
  }
  const vendorDir = path.join(PACKAGE_DIR, 'vendor');
  if (fs.existsSync(vendorDir)) {
    return vendorDir;
  }
  // No release build present -- running npm/ directly against live source
  // (task.py test-npm, or local development).
  return path.resolve(PACKAGE_DIR, '..');
}

async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--print-dep-dir')) {
    const pyRoot = await resolvePyRoot(readNpmConfig(process.cwd()));
    const requirementsPath = path.join(pyRoot, 'requirements-runtime.txt');
    const { venvDirFor } = require('../lib/venv');
    console.log(venvDirFor(requirementsPath));
    process.exit(0);
  }
  if (args.includes('--install-deps') || args.includes('--check-deps')) {
    const force = args.includes('--install-deps') 
    const pyRoot = await resolvePyRoot(readNpmConfig(process.cwd()));
    const requirementsPath = path.join(pyRoot, 'requirements-runtime.txt');
    try {
      ensureVenv(requirementsPath, { forceInstall: force });
      process.exit(0);
    } catch (err) {
      console.error(String(err.message || err));
      process.exit(1);
    }
  }

  const localInstall = findLocalInstall(process.cwd(), SELF_PATH);
  if (localInstall) {
    const result = spawnSync(process.execPath, [localInstall, ...args], { stdio: 'inherit' });
    process.exit(result.status === null ? 1 : result.status);
  }

  const npmConfig = readNpmConfig(process.cwd());

  if (npmConfig.preferSystem) {
    const systemInstall = findSystemInstall(SELF_PATH);
    if (systemInstall) {
      const result = spawnSync(systemInstall, args, { stdio: 'inherit' });
      process.exit(result.status === null ? 1 : result.status);
    }
  }

  const pyRoot = await resolvePyRoot(npmConfig);
  runPython(pyRoot, args);
}

main().catch((err) => {
  console.error(String((err && err.message) || err));
  process.exit(1);
});
