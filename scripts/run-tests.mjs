import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';


function run(command, args, options = {}) {
  return spawnSync(command, args, { stdio: 'inherit', shell: false, ...options });
}


function pythonCandidates() {
  const candidates = [];
  if (process.env.INFO_COLLECTOR_PYTHON) {
    candidates.push([process.env.INFO_COLLECTOR_PYTHON, []]);
  }
  if (process.platform === 'win32') {
    candidates.push(['py', ['-3']], ['python', []], ['python3', []]);
    const root = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, 'Programs', 'Python');
    if (root && existsSync(root)) {
      for (const name of readdirSync(root).sort().reverse()) {
        const exe = join(root, name, 'python.exe');
        if (existsSync(exe)) candidates.push([exe, []]);
      }
    }
  } else {
    candidates.push(['python3', []], ['python', []]);
  }
  return candidates;
}


function findPython() {
  for (const [command, prefix] of pythonCandidates()) {
    const probe = spawnSync(command, [...prefix, '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'], {
      stdio: 'ignore',
      shell: false,
    });
    if (!probe.error && probe.status === 0) return [command, prefix];
  }
  return null;
}


const nodeResult = run(process.execPath, ['--test']);
if (nodeResult.status !== 0) process.exit(nodeResult.status ?? 1);

const python = findPython();
if (!python) {
  console.error('未找到 Python 3.9+。可设置 INFO_COLLECTOR_PYTHON 为 python.exe 的绝对路径。');
  process.exit(1);
}

const [pythonCommand, pythonPrefix] = python;
const pythonResult = run(pythonCommand, [...pythonPrefix, '-m', 'unittest', 'discover', '-s', 'test', '-p', '*_test.py']);
process.exit(pythonResult.status ?? 1);

