#!/usr/bin/env node
const fs = require('fs');

const filePath = process.argv[2];
if (!filePath) {
  console.error('missing file path');
  process.exit(1);
}

const source = fs.readFileSync(filePath, 'utf8');
const lines = source.split(/\r?\n/);
const symbols = [];
const references = [];
const classStack = [];
let braceDepth = 0;

function pushSymbol(name, kind, lineIndex, container = null) {
  const symbol = {
    name,
    kind,
    line_start: lineIndex + 1,
    line_end: lineIndex + 1,
    container,
    brace_anchor_depth: null,
    brace_anchor_line: null,
  };
  symbols.push(symbol);
  return symbol;
}

for (let i = 0; i < lines.length; i += 1) {
  const line = lines[i];
  const trimmed = line.trim();
  const currentContainer = classStack.length ? classStack[classStack.length - 1].name : null;
  const definitionNames = new Set();

  let match = trimmed.match(/^export\s+class\s+([A-Za-z_$][\w$]*)/) || trimmed.match(/^class\s+([A-Za-z_$][\w$]*)/);
  if (match) {
    const symbol = pushSymbol(match[1], 'class', i, null);
    if (line.includes('{')) {
      symbol.brace_anchor_depth = braceDepth;
      symbol.brace_anchor_line = i + 1;
    }
    definitionNames.add(match[1]);
    classStack.push({ name: match[1], depth: braceDepth });
  } else if ((match = trimmed.match(/^export\s+(async\s+)?function\s+([A-Za-z_$][\w$]*)/)) || (match = trimmed.match(/^(async\s+)?function\s+([A-Za-z_$][\w$]*)/))) {
    const symbol = pushSymbol(match[2], match[1] ? 'async_function' : 'function', i, null);
    if (line.includes('{')) {
      symbol.brace_anchor_depth = braceDepth;
      symbol.brace_anchor_line = i + 1;
    }
    definitionNames.add(match[2]);
  } else if ((match = trimmed.match(/^export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*(async\s*)?\(/)) || (match = trimmed.match(/^const\s+([A-Za-z_$][\w$]*)\s*=\s*(async\s*)?\(/))) {
    const symbol = pushSymbol(match[1], match[2] ? 'async_function' : 'function', i, null);
    if (line.includes('{')) {
      symbol.brace_anchor_depth = braceDepth;
      symbol.brace_anchor_line = i + 1;
    }
    definitionNames.add(match[1]);
  } else if ((match = trimmed.match(/^export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*(async\s*)?[^=]*=>/)) || (match = trimmed.match(/^const\s+([A-Za-z_$][\w$]*)\s*=\s*(async\s*)?[^=]*=>/))) {
    const symbol = pushSymbol(match[1], match[2] ? 'async_function' : 'function', i, null);
    if (line.includes('{')) {
      symbol.brace_anchor_depth = braceDepth;
      symbol.brace_anchor_line = i + 1;
    }
    definitionNames.add(match[1]);
  } else if (currentContainer && (match = trimmed.match(/^(async\s+)?([A-Za-z_$][\w$]*)\s*\(/)) && !trimmed.startsWith('if ') && !trimmed.startsWith('for ') && !trimmed.startsWith('while ') && !trimmed.startsWith('switch ') && !trimmed.startsWith('catch ')) {
    const symbol = pushSymbol(match[2], match[1] ? 'async_method' : 'method', i, currentContainer);
    if (line.includes('{')) {
      symbol.brace_anchor_depth = braceDepth;
      symbol.brace_anchor_line = i + 1;
    }
    definitionNames.add(match[2]);
  }

  const identifierPattern = /\b[A-Za-z_$][\w$]*\b/g;
  let identifierMatch;
  while ((identifierMatch = identifierPattern.exec(line)) !== null) {
    const identifier = identifierMatch[0];
    const column = identifierMatch.index;
    if (definitionNames.has(identifier)) {
      continue;
    }
    references.push({
      name: identifier,
      line: i + 1,
      column,
      preview: trimmed.length > 160 ? `${trimmed.slice(0, 159).trimEnd()}…` : trimmed,
    });
  }

  const opens = (line.match(/\{/g) || []).length;
  const closes = (line.match(/\}/g) || []).length;
  braceDepth += opens - closes;
  for (const symbol of symbols) {
    if (symbol.line_end !== symbol.line_start) continue;
    if (symbol.brace_anchor_depth === null) continue;
    if (i + 1 <= symbol.brace_anchor_line) continue;
    if (braceDepth <= symbol.brace_anchor_depth) {
      symbol.line_end = i + 1;
    }
  }
  while (classStack.length && braceDepth <= classStack[classStack.length - 1].depth) {
    classStack.pop();
  }
}

for (const symbol of symbols) {
  delete symbol.brace_anchor_depth;
  delete symbol.brace_anchor_line;
}

console.log(JSON.stringify({ symbols, references }));
