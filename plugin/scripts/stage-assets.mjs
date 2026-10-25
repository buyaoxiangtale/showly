/** npm pack/publish 前把仓库资产（skills/、profiles 模板、.env.example）拷进包内。 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(pluginRoot, '..');

function copy(relativeFrom, relativeTo) {
  const from = path.join(repoRoot, relativeFrom);
  const to = path.join(pluginRoot, relativeTo);
  if (!fs.existsSync(from)) {
    throw new Error(`缺少打包资产：${relativeFrom}`);
  }
  fs.cpSync(from, to, { recursive: true });
  console.log(`staged ${relativeFrom} -> plugin/${relativeTo}`);
}

copy('skills', 'skills');
copy(path.join('profiles', '_template'), path.join('profiles', '_template'));
copy('.env.example', '.env.example');

const builtinCount = fs.readdirSync(path.join(pluginRoot, 'skills', 'builtin'))
  .filter((name) => fs.existsSync(path.join(pluginRoot, 'skills', 'builtin', name, 'SKILL.md'))).length;
console.log(`技能数（SKILL.md）：${builtinCount}`);
if (builtinCount < 100) {
  throw new Error(`技能数异常（${builtinCount} < 100），中止打包`);
}
