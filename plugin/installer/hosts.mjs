/** 四个宿主的定义与检测。 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/**
 * 宿主 home 基址：默认用户主目录；测试/自定义安装可用
 * SHOWLY_PLUGIN_HOME_BASE 指定（如 tmp 目录）。
 */
function homeBase() {
  return process.env.SHOWLY_PLUGIN_HOME_BASE || os.homedir();
}

/**
 * 宿主定义：
 * - home:       宿主配置目录（用户级）
 * - instructions: 指令合并目标文件（prompt-only：署名与路由都写在这里，不写 hook）
 * - launcherSkillDir: 有原生技能机制的宿主（ZCode / Claude Code）加一个入口技能做路由
 * - bundleName: 技能包自包含目录名（保持 skills/ 原始结构，SKILL 内相对路径不变）
 */
export const HOSTS = [
  {
    id: 'zcode',
    label: 'ZCode',
    home: () => path.join(homeBase(), '.zcode'),
    instructionsFile: (home) => path.join(home, 'AGENTS.md'),
    launcherSkillDir: (home) => path.join(home, 'skills', 'showly'),
    hasLauncher: true,
  },
  {
    id: 'claude-code',
    label: 'Claude Code',
    home: () => path.join(homeBase(), '.claude'),
    instructionsFile: (home) => path.join(home, 'CLAUDE.md'),
    launcherSkillDir: (home) => path.join(home, 'skills', 'showly'),
    hasLauncher: true,
  },
  {
    id: 'codex',
    label: 'Codex',
    home: () => path.join(homeBase(), '.codex'),
    instructionsFile: (home) => path.join(home, 'AGENTS.md'),
    launcherSkillDir: null,
    hasLauncher: false,
  },
  {
    id: 'dsh',
    label: 'DeepSeek Harness (DSH)',
    home: () => path.join(homeBase(), '.dsh'),
    instructionsFile: (home) => path.join(home, 'AGENTS.md'),
    launcherSkillDir: null,
    hasLauncher: false,
  },
];

export function getHost(id) {
  const host = HOSTS.find((h) => h.id === id);
  if (!host) {
    throw new Error(`未知宿主：${id}（可选：${HOSTS.map((h) => h.id).join(' / ')}）`);
  }
  return host;
}

export function detectHosts() {
  return HOSTS.map((host) => {
    const home = host.home();
    return {
      ...host,
      home,
      installed: fs.existsSync(home),
      pluginInstalled: fs.existsSync(path.join(home, 'ifline-showly')),
    };
  });
}

export function bundleDir(host) {
  return path.join(host.home(), 'ifline-showly');
}
