'use strict';
// Fetches a GitHub ref (tag or commit SHA) as a runnable source tree, for
// `npm.fetch.ref` in .commentlintrc.json. Goes through `git clone` + `git lfs
// pull` rather than GitHub's archive-zip endpoint: the zip endpoint serves
// Git LFS files (model_linear/*.joblib) as pointer stubs, not their real
// binary content, which crashes joblib.load with an unpickling error the
// pointer text's first byte ('v' of "version https://...") happens to
// resemble a corrupt pickle rather than a missing LFS object.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const { commentlintHome } = require('./venv');

const REPO_URL = 'https://github.com/joeedh/comment-lint.git';

function installDirFor(ref) {
  return path.join(commentlintHome(), 'installs', ref);
}

function git(args, cwd) {
  execFileSync('git', args, { cwd, stdio: 'inherit' });
}

async function ensureFetched(ref) {
  const dest = installDirFor(ref);
  if (fs.existsSync(dest)) {
    return dest;
  }

  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const cloneRoot = dest + '.cloning';
  fs.rmSync(cloneRoot, { recursive: true, force: true });
  fs.mkdirSync(cloneRoot, { recursive: true });

  try {
    git(['init', '-q'], cloneRoot);
    git(['remote', 'add', 'origin', REPO_URL], cloneRoot);
    git(['fetch', '--depth', '1', 'origin', ref], cloneRoot);
    git(['checkout', '-q', 'FETCH_HEAD'], cloneRoot);
    git(['lfs', 'pull'], cloneRoot);
    fs.rmSync(path.join(cloneRoot, '.git'), { recursive: true, force: true });
  } catch (err) {
    fs.rmSync(cloneRoot, { recursive: true, force: true });
    throw new Error(`commentlint: fetch failed for ref '${ref}': ${err.message || err}`);
  }

  fs.renameSync(cloneRoot, dest);
  return dest;
}

module.exports = { installDirFor, ensureFetched };
