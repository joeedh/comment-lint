'use strict';
// Searches PATH for a distinct `commentlint` install, for `npm.preferSystem`.
// fs.realpath cannot detect self-reference on Windows: npm's global installer
// writes commentlint.cmd (and a .ps1 shim) as real files that invoke
// `node ...\commentlint\bin\commentlint.js` by path, not as a symlink, so
// realpath on the shim just returns the shim itself. Instead, anything found
// under `npm root -g` is treated as this install regardless of realpath.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function npmGlobalRoot() {
  try {
    const res = spawnSync('npm', ['root', '-g'], { encoding: 'utf8', shell: process.platform === 'win32' });
    if (res.status === 0) {
      return res.stdout.trim();
    }
  } catch {
    // fall through
  }
  return null;
}

function candidateNames() {
  return process.platform === 'win32' ? ['commentlint.cmd', 'commentlint.exe', 'commentlint'] : ['commentlint'];
}

function findSystemInstall(selfPath) {
  const globalRoot = npmGlobalRoot();
  const pathDirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const selfDir = path.dirname(path.resolve(selfPath));

  for (const dir of pathDirs) {
    for (const name of candidateNames()) {
      const candidate = path.join(dir, name);
      if (!fs.existsSync(candidate)) continue;

      if (globalRoot && path.resolve(candidate).startsWith(path.resolve(globalRoot))) {
        continue; // under the global npm root -- this install, not a distinct one
      }
      if (path.resolve(dir) === selfDir) {
        continue; // same directory as this script's own bin -- not distinct
      }
      return candidate;
    }
  }
  return null;
}

module.exports = { findSystemInstall };
