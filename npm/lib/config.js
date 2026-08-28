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

// Mirrors commentlint/config.py's _strip_json_comments: blanks out `//` and
// `/* */` comments that fall outside string literals, replacing each
// stripped character with a space so parse-error positions do not shift.
function stripJsonComments(text) {
  let out = '';
  let i = 0;
  const n = text.length;
  let inString = false;
  let escape = false;
  while (i < n) {
    const c = text[i];
    if (inString) {
      out += c;
      if (escape) {
        escape = false;
      } else if (c === '\\') {
        escape = true;
      } else if (c === '"') {
        inString = false;
      }
      i += 1;
      continue;
    }
    if (c === '"') {
      inString = true;
      out += c;
      i += 1;
      continue;
    }
    if (c === '/' && text[i + 1] === '/') {
      while (i < n && text[i] !== '\n') {
        out += ' ';
        i += 1;
      }
      continue;
    }
    if (c === '/' && text[i + 1] === '*') {
      out += '  ';
      i += 2;
      while (i < n && !(text[i] === '*' && text[i + 1] === '/')) {
        out += text[i] === '\n' ? '\n' : ' ';
        i += 1;
      }
      if (i < n) {
        out += '  ';
        i += 2;
      }
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

function readJson(filePath) {
  try {
    return JSON.parse(stripJsonComments(fs.readFileSync(filePath, 'utf8')));
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
