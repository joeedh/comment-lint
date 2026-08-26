'use strict';
// Locates a base Python interpreter to build a venv with. Platform-aware for
// the same reason bin/commentlint.cmd already branches: the python.org
// installer puts the `py` launcher on Windows PATH by default, not a
// PATH-visible python3/python.
const { spawnSync } = require('child_process');

function works(cmd, args) {
  try {
    const res = spawnSync(cmd, args, { stdio: 'ignore' });
    return res.status === 0;
  } catch {
    return false;
  }
}

function findBasePython() {
  const candidates =
    process.platform === 'win32'
      ? [['py', ['-3']], ['python', []], ['python3', []]]
      : [['python3', []], ['python', []]];
  for (const [cmd, args] of candidates) {
    if (works(cmd, [...args, '--version'])) {
      return { cmd, args };
    }
  }
  return null;
}

module.exports = { findBasePython };
