'use strict';
// Downloads and caches a GitHub ref (tag or commit SHA) as a runnable source
// tree, for `npm.fetch.ref` in .commentlintrc.json. codeload.github.com serves
// both tags and commit SHAs at the same URL shape, so no branch/tag/sha
// disambiguation is needed here.
const fs = require('fs');
const https = require('https');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const { commentlintHome } = require('./venv');

const REPO_ZIP_URL = (ref) =>
  `https://github.com/joeedh/comment-lint/archive/${ref}.zip`;

function installDirFor(ref) {
  return path.join(commentlintHome(), 'installs', ref);
}

function download(url, destFile) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destFile);
    https
      .get(url, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          file.close();
          fs.rmSync(destFile, { force: true });
          download(res.headers.location, destFile).then(resolve, reject);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`commentlint: fetch failed (${res.statusCode}) for ${url}`));
          return;
        }
        res.pipe(file);
        file.on('finish', () => file.close(resolve));
      })
      .on('error', reject);
  });
}

async function ensureFetched(ref) {
  const dest = installDirFor(ref);
  if (fs.existsSync(dest)) {
    return dest;
  }

  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const tmpZip = path.join(os.tmpdir(), `commentlint-${ref.replace(/[^a-zA-Z0-9_.-]/g, '_')}.zip`);
  await download(REPO_ZIP_URL(ref), tmpZip);

  const extractRoot = dest + '.extracting';
  fs.rmSync(extractRoot, { recursive: true, force: true });
  fs.mkdirSync(extractRoot, { recursive: true });
  extractZip(tmpZip, extractRoot);
  fs.rmSync(tmpZip, { force: true });

  // GitHub's archive zip has one top-level dir (repo-ref/); flatten it.
  const entries = fs.readdirSync(extractRoot);
  const topLevel = entries.length === 1 ? path.join(extractRoot, entries[0]) : extractRoot;
  fs.renameSync(topLevel, dest);
  fs.rmSync(extractRoot, { recursive: true, force: true });
  return dest;
}

function extractZip(zipPath, destDir) {
  if (process.platform === 'win32') {
    execFileSync('powershell.exe', [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      `Expand-Archive -LiteralPath '${zipPath}' -DestinationPath '${destDir}' -Force`,
    ]);
  } else {
    execFileSync('unzip', ['-q', zipPath, '-d', destDir]);
  }
}

module.exports = { installDirFor, ensureFetched };
