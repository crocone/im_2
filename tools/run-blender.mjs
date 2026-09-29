#!/usr/bin/env node
// Locates Blender and runs a Python script in background mode:
//   node tools/run-blender.mjs tools/blender/build_all.py [-- script args]
//
// Lookup order:
//   1. $BLENDER / $BLENDER_PATH (full path to blender executable)
//   2. `blender` on PATH
//   3. project-local portable copy in tools/.blender/<any>/blender(.exe)
//   4. common install locations (Windows / macOS / Linux)
//
// The script is executed with --factory-startup so that user preferences and
// third-party add-ons can never change the output (reproducible builds).
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { delimiter, join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const isWin = process.platform === 'win32';
const exeName = isWin ? 'blender.exe' : 'blender';

function candidates() {
  const list = [];
  for (const key of ['BLENDER', 'BLENDER_PATH']) if (process.env[key]) list.push(process.env[key]);
  for (const dir of (process.env.PATH || '').split(delimiter)) if (dir) list.push(join(dir, exeName));
  const local = join(root, 'tools', '.blender');
  if (existsSync(local)) {
    for (const d of readdirSync(local)) {
      list.push(join(local, d, exeName));
      list.push(join(local, d, 'Blender.app', 'Contents', 'MacOS', 'Blender'));
    }
  }
  if (isWin) {
    for (const base of [process.env.ProgramFiles, process.env['ProgramFiles(x86)']]) {
      if (!base) continue;
      const bf = join(base, 'Blender Foundation');
      if (existsSync(bf)) for (const d of readdirSync(bf).sort().reverse()) list.push(join(bf, d, exeName));
    }
  } else if (process.platform === 'darwin') {
    list.push('/Applications/Blender.app/Contents/MacOS/Blender');
  } else {
    list.push('/usr/bin/blender', '/snap/bin/blender', '/usr/local/bin/blender');
  }
  return list;
}

export function findBlender() {
  return candidates().find((p) => p && existsSync(p));
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const [script, ...rest] = process.argv.slice(2);
  if (!script) {
    console.error('usage: node tools/run-blender.mjs <script.py> [args...]');
    process.exit(2);
  }
  const blender = findBlender();
  if (!blender) {
    console.error(
      '[assets] Blender executable not found.\n' +
        '  Set the BLENDER environment variable to the full path of blender(.exe), put blender on PATH,\n' +
        '  or unzip a portable Blender build into tools/.blender/ (see README.md).',
    );
    process.exit(1);
  }
  console.log(`[assets] Blender: ${blender}`);
  const args = ['-b', '--factory-startup', '--python-exit-code', '1', '-P', resolve(root, script)];
  if (rest.length) args.push('--', ...rest);
  const res = spawnSync(blender, args, {
    stdio: 'inherit',
    cwd: root,
    env: { ...process.env, PYTHONHASHSEED: '0', PYTHONIOENCODING: 'utf-8' },
  });
  process.exit(res.status ?? 1);
}
