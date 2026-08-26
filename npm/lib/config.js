'use strict';
// Finds the nearest .commentlintrc.json (+ sibling .commentlintrc.local.json)
// and reads its "npm" key. The Python side type-checks that key without
// reading its nested shape -- this schema belongs here.
const fs = require('fs');
const path = require('path');

const CONFIG_NAME = '.commentlintrc.json';
const LOCAL_CONFIG_NAME = '.commentlintrc.local.json';

function findConfig(startDir) {
  let dir = path.resolve(startDir);
  for (;;) {
    const candidate = path.join(dir, CONFIG_NAME);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return null;
    }
    dir = parent;
  }
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return {};
  }
}

function readNpmConfig(startDir) {
  const configPath = findConfig(startDir);
  if (!configPath) {
    return {};
  }
  const base = readJson(configPath);
  const localPath = path.join(path.dirname(configPath), LOCAL_CONFIG_NAME);
  const local = fs.existsSync(localPath) ? readJson(localPath) : {};
  return { ...(base.npm || {}), ...(local.npm || {}) };
}

module.exports = { findConfig, readNpmConfig };
