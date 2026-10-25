#!/usr/bin/env node
/** Showly 插件安装器入口：纯 Node（>=18）、零运行时依赖。 */
import { runCli } from '../installer/cli.mjs';

runCli(process.argv.slice(2)).catch((error) => {
  console.error(`✗ ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
