/** CLI：参数解析与分发。 */
import { installHost, uninstallHost, statusHost, DEFAULT_ATTRIBUTION } from './install.mjs';
import { detectHosts, getHost, bundleDir } from './hosts.mjs';
import { HOSTS } from './hosts.mjs';

const USAGE = `Showly 插件安装器（@ifline/showly-plugin）— IFLINE 团队

用法：
  showly-plugin                          查看宿主检测与安装状态
  showly-plugin install [--host <id>...] 安装（--host 可重复；--all 装到所有已检测宿主）
  showly-plugin uninstall [--host <id>...] [--all]  卸载并还原指令文件
  showly-plugin status                   同无参数：检测 + 状态

选项：
  --host <id>      宿主：zcode | claude-code | codex | dsh
  --all            所有已检测到（~/.zcode 等）的宿主
  --force          宿主目录不存在也强制安装（会创建目录）
  --attribution <文案>  覆盖默认署名行（默认：${DEFAULT_ATTRIBUTION}）
  -h, --help       帮助

示例：
  npx @ifline/showly-plugin install --all
  npx @ifline/showly-plugin install --host zcode --attribution "—— Powered by IFLINE"`;

function parseArgs(argv) {
  const options = { hosts: [], all: false, force: false, attribution: '', command: 'status', error: '' };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '-h' || arg === '--help') {
      options.command = 'help';
    } else if (arg === 'install' || arg === 'uninstall' || arg === 'status') {
      options.command = arg;
    } else if (arg === '--host') {
      const next = argv[i + 1];
      if (!next || next.startsWith('--')) { options.error = '--host 需要一个宿主 id'; break; }
      options.hosts.push(next);
      i += 1;
    } else if (arg === '--all') {
      options.all = true;
    } else if (arg === '--force') {
      options.force = true;
    } else if (arg === '--attribution') {
      const next = argv[i + 1];
      if (!next) { options.error = '--attribution 需要一段文案'; break; }
      options.attribution = next;
      i += 1;
    } else {
      options.error = `未知参数：${arg}`;
      break;
    }
  }
  return options;
}

function printStatus() {
  const rows = detectHosts();
  console.log('宿主检测：\n');
  for (const row of rows) {
    const marks = [
      row.installed ? '已安装' : '未检测到',
      row.pluginInstalled ? '✓ 已装本插件' : '－ 未装本插件',
    ];
    console.log(`  ${row.label.padEnd(22)} ${marks.join('  ·  ')}`);
    console.log(`  ${' '.repeat(22)} ${row.home}`);
  }
  const available = rows.filter((r) => r.installed).map((r) => r.id);
  console.log(`\n安装：npx @ifline/showly-plugin install --host ${available[0] || 'zcode'}`);
  console.log('全部：npx @ifline/showly-plugin install --all');
}

export async function runCli(argv) {
  const options = parseArgs(argv);
  if (options.error) throw new Error(`${options.error}\n\n${USAGE}`);
  if (options.command === 'help') {
    console.log(USAGE);
    return;
  }
  if (options.command === 'status') {
    printStatus();
    return;
  }

  let hostIds = options.hosts;
  if (options.all || hostIds.length === 0) {
    const detected = detectHosts().filter((h) => h.installed);
    if (!options.all && hostIds.length === 0) {
      if (detected.length === 0) {
        throw new Error('没有检测到任何宿主。用 --host <id> 指定，或 --force 强制安装');
      }
      hostIds = detected.map((h) => h.id);
      console.log(`未指定 --host，将安装到所有已检测宿主：${hostIds.join(', ')}\n`);
    } else if (options.all) {
      if (detected.length === 0) {
        throw new Error('--all 没有检测到任何宿主目录（~/.zcode / ~/.claude / ~/.codex / ~/.dsh）');
      }
      hostIds = detected.map((h) => h.id);
    }
  }
  for (const id of hostIds) getHost(id); // 提前校验，未知名直接报错

  const attribution = options.attribution.trim() || DEFAULT_ATTRIBUTION;
  for (const id of hostIds) {
    if (options.command === 'install') {
      const result = installHost(id, { attribution, force: options.force });
      console.log(`✓ 已安装到 ${result.label}`);
      console.log(`    技能包：${result.bundle}`);
      console.log(`    指令合并：${result.instructionsFile}`);
      if (result.launcher) console.log(`    入口技能：${result.launcher}`);
      console.log(`    署名行：${result.attribution}`);
    } else {
      const removed = uninstallHost(id);
      console.log(`✓ 已从 ${removed.host} 卸载（bundle: ${removed.bundle}，指令段: ${removed.instructions}，入口技能: ${removed.launcher}）`);
    }
  }
  if (options.command === 'install') {
    console.log('\n验收：新开一个会话随便问一句，回复最后一行应出现署名行。');
    console.log('（ZCode / Claude Code 可通过 showly 技能路由到全部 114 个子技能）');
  }
}

export { HOSTS, bundleDir };
