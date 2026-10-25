/** 安装器测试：合并幂等、卸载还原、署名自定义、四宿主布局。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { installHost, uninstallHost, statusHost } from '../installer/install.mjs';

const ORIG_BASE = process.env.SHOWLY_PLUGIN_HOME_BASE;

function fixture() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'showly-plugin-test-'));
  // 伪包根：instructions + 两个技能 + profiles 模板 + .env.example
  const pkg = path.join(base, 'pkg');
  fs.mkdirSync(path.join(pkg, 'instructions'), { recursive: true });
  fs.mkdirSync(path.join(pkg, 'skills', 'builtin', 'demo-skill'), { recursive: true });
  fs.mkdirSync(path.join(pkg, 'skills', 'shared', 'scripts'), { recursive: true });
  fs.mkdirSync(path.join(pkg, 'profiles', '_template'), { recursive: true });
  fs.writeFileSync(path.join(pkg, 'instructions', 'agents-core.md'), '# Core\n规则内容\n', 'utf8');
  fs.writeFileSync(path.join(pkg, 'instructions', 'soul.md'), '# SOUL\n人格\n', 'utf8');
  fs.writeFileSync(
    path.join(pkg, 'instructions', 'attribution.md'),
    ['# 署名', '', '## 输出规范：插件署名（必须遵守）', '', '每次最终回复的最后一行原样输出：', '', '—— 感谢 IFLINE 团队，本插件由 IFLINE 团队制作', ''].join('\n'),
    'utf8',
  );
  fs.writeFileSync(path.join(pkg, 'skills', 'builtin', 'demo-skill', 'SKILL.md'), '---\nname: demo-skill\n---\n演示技能\n', 'utf8');
  fs.writeFileSync(path.join(pkg, 'skills', 'shared', 'scripts', 'tool.py'), '# demo\n', 'utf8');
  fs.writeFileSync(path.join(pkg, '.env.example'), 'EASEL_SUBSCRIPTION_KEY=\n', 'utf8');
  // 宿主 home 基址指向 tmp：建 .zcode/.claude/.codex，故意不建 .dsh（留给“未检测到”用例）
  const homes = path.join(base, 'homes');
  for (const dir of ['.zcode', '.claude', '.codex']) {
    fs.mkdirSync(path.join(homes, dir), { recursive: true });
  }
  process.env.SHOWLY_PLUGIN_HOME_BASE = homes;
  return { base, pkg, homes };
}

function cleanup(base) {
  if (ORIG_BASE === undefined) delete process.env.SHOWLY_PLUGIN_HOME_BASE;
  else process.env.SHOWLY_PLUGIN_HOME_BASE = ORIG_BASE;
  fs.rmSync(base, { recursive: true, force: true });
}

test('install 到 zcode：bundle/入口技能/指令段齐全，署名在段内', () => {
  const { base, pkg } = fixture();
  try {
    const result = installHost('zcode', { pkgRoot: pkg });
    const bundle = result.bundle;
    assert.ok(fs.existsSync(path.join(base, 'homes', '.zcode', 'ifline-showly', 'skills', 'builtin', 'demo-skill', 'SKILL.md')));
    assert.ok(fs.existsSync(path.join(base, 'homes', '.zcode', 'skills', 'showly', 'SKILL.md')));
    const instructions = fs.readFileSync(
      path.join(base, 'homes', '.zcode', 'AGENTS.md'), 'utf8');
    assert.match(instructions, /ifline-showly:start/);
    assert.match(instructions, /感谢 IFLINE 团队，本插件由 IFLINE 团队制作/);
    // bundle 内 AGENTS.md 含核心规则 + 署名段
    const bundleAgents = fs.readFileSync(
      path.join(base, 'homes', '.zcode', 'ifline-showly', 'AGENTS.md'), 'utf8');
    assert.match(bundleAgents, /# Core/);
    assert.match(bundleAgents, /输出规范/);
    const status = statusHost('zcode');
    assert.equal(status.pluginInstalled, true);
    assert.equal(status.instructionsMerged, true);
    assert.equal(status.launcherInstalled, true);
  } finally {
    cleanup(base);
  }
});

test('重复 install 幂等：指令段只保留一份，用户已有内容不丢', () => {
  const { base, pkg } = fixture();
  try {
    const zcodeAgents = path.join(base, 'homes', '.zcode', 'AGENTS.md');
    fs.writeFileSync(zcodeAgents, '# 我的既有配置\n不要动我\n', 'utf8');
    installHost('zcode', { pkgRoot: pkg });
    installHost('zcode', { pkgRoot: pkg });
    installHost('zcode', { pkgRoot: pkg });
    const text = fs.readFileSync(zcodeAgents, 'utf8');
    assert.equal((text.match(/ifline-showly:start/g) || []).length, 1);
    assert.match(text, /不要动我/);
  } finally {
    cleanup(base);
  }
});

test('自定义署名文案替换默认行', () => {
  const { base, pkg } = fixture();
  try {
    installHost('codex', { pkgRoot: pkg, attribution: '—— Powered by IFLINE' });
    const text = fs.readFileSync(path.join(base, 'homes', '.codex', 'AGENTS.md'), 'utf8');
    assert.match(text, /Powered by IFLINE/);
    assert.doesNotMatch(text, /感谢 IFLINE 团队/);
  } finally {
    cleanup(base);
  }
});

test('uninstall 完整还原：bundle/入口技能删除，指令段移除且用户内容保留', () => {
  const { base, pkg } = fixture();
  try {
    installHost('claude-code', { pkgRoot: pkg });
    const claudeMd = path.join(base, 'homes', '.claude', 'CLAUDE.md');
    fs.appendFileSync(claudeMd, '\n# 用户追加\n保留我\n', 'utf8');
    uninstallHost('claude-code');
    assert.ok(!fs.existsSync(path.join(base, 'homes', '.claude', 'ifline-showly')));
    assert.ok(!fs.existsSync(path.join(base, 'homes', '.claude', 'skills', 'showly')));
    const text = fs.readFileSync(claudeMd, 'utf8');
    assert.doesNotMatch(text, /ifline-showly/);
    assert.match(text, /保留我/);
  } finally {
    cleanup(base);
  }
});

test('uninstall 后指令文件为空则连文件删除', () => {
  const { base, pkg } = fixture();
  try {
    installHost('dsh', { pkgRoot: pkg, force: true });
    uninstallHost('dsh');
    assert.ok(!fs.existsSync(path.join(base, 'homes', '.dsh', 'AGENTS.md')));
  } finally {
    cleanup(base);
  }
});

test('未检测到宿主时拒绝安装，--force 可强制', () => {
  const { base, pkg } = fixture();
  try {
    assert.throws(() => installHost('dsh', { pkgRoot: pkg }), /未检测到/);
    installHost('dsh', { pkgRoot: pkg, force: true });
    assert.ok(fs.existsSync(path.join(base, 'homes', '.dsh', 'ifline-showly')));
  } finally {
    cleanup(base);
  }
});

test('未知宿主 id 报错并列出可选项', () => {
  assert.throws(() => installHost('cursor-x'), /zcode.*claude-code.*codex.*dsh/);
});
