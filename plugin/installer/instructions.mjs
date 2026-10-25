/** 指令文件的标记段合并/移除（幂等；卸载可精确还原）。 */
import fs from 'node:fs';
import path from 'node:path';

export const START = '<!-- ifline-showly:start -->';
export const END = '<!-- ifline-showly:end -->';

/** 把 content 包进标记段；若文件已有旧段则整体替换，否则追加到末尾。 */
export function mergeSection(filePath, content) {
  let text = '';
  if (fs.existsSync(filePath)) {
    text = fs.readFileSync(filePath, 'utf8');
  }
  const block = `${START}\n${content.trim()}\n${END}`;
  const startIdx = text.indexOf(START);
  const endIdx = text.indexOf(END);
  if (startIdx >= 0 && endIdx > startIdx) {
    // 就地替换旧段，其余内容（含用户自己的配置）原样保留
    text = text.slice(0, startIdx) + block + text.slice(endIdx + END.length);
  } else {
    const separator = text.trim() === '' ? '' : '\n\n';
    text = text.replace(/\n*$/, '') + separator + block + '\n';
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, text, 'utf8');
}

/** 移除标记段；段不存在返回 false。移除后若文件为空则连文件一起删掉。 */
export function removeSection(filePath) {
  if (!fs.existsSync(filePath)) return false;
  const text = fs.readFileSync(filePath, 'utf8');
  const startIdx = text.indexOf(START);
  const endIdx = text.indexOf(END);
  if (startIdx < 0 || endIdx < startIdx) return false;
  const next = (text.slice(0, startIdx) + text.slice(endIdx + END.length))
    .replace(/\n{3,}$/, '\n')
    .replace(/^\n+/, '');
  if (next.trim() === '') {
    fs.rmSync(filePath);
  } else {
    fs.writeFileSync(filePath, next, 'utf8');
  }
  return true;
}

export function hasSection(filePath) {
  if (!fs.existsSync(filePath)) return false;
  const text = fs.readFileSync(filePath, 'utf8');
  return text.includes(START) && text.includes(END);
}
