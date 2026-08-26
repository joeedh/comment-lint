'use strict';
// Walks up from cwd looking for a project-local install of commentlint, so a
// global `commentlint` defers to a project's own pinned version.
const fs = require('fs');
const path = require('path');

function findLocalInstall(startDir, selfPath) {
  let dir = path.resolve(startDir);
  for (;;) {
    const candidate = path.join(dir, 'node_modules', 'commentlint', 'bin', 'commentlint.js');
    if (fs.existsSync(candidate)) {
      let candidateReal, selfReal;
      try {
        candidateReal = fs.realpathSync(candidate);
        selfReal = fs.realpathSync(selfPath);
      } catch {
        candidateReal = candidate;
        selfReal = selfPath;
      }
      if (candidateReal !== selfReal) {
        return candidate;
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return null;
    }
    dir = parent;
  }
}

module.exports = { findLocalInstall };
