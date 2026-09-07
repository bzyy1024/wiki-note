const fs = require('fs');
const path = require('path');

const desktop = 'C:\\Users\\admin\\Desktop';
const content = 'c:\\www\\Mine\\wiki-note\\content';

// 1) 先把 _SPEC.md（内部写作规格，不对外）移出到桌面单独留档
const specFrom = path.join(desktop, '一事十面·英语思维切片', '_SPEC.md');
const specTo = path.join(desktop, '_SPEC-一事十面英语思维切片-内部写作规格（不对外）.md');
fs.renameSync(specFrom, specTo);

// 2) 移动三门课到 wiki 对应分类
const moves = [
  ['写实的写作·把内容写充实', path.join(content, '个人成长', '10-写实的写作·把内容写充实')],
  ['设计的内功·视觉心法修炼手册', path.join(content, '人文社科', '11-设计的内功·视觉心法修炼手册')],
  ['一事十面·英语思维切片', path.join(content, '语言学习', '05-一事十面·英语思维切片')],
];

for (const [name, dst] of moves) {
  fs.renameSync(path.join(desktop, name), dst);
  console.log('moved: ' + name);
}
console.log('MOVE-OK');
