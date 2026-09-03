import re, os
from collections import Counter

base = '.'
# 编号 n(1-based) -> 中文: cn[1]='一'(但首节不显示), cn[2]='二', cn[3]='三' ...
cn = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
      '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九']
cn2int = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7,
          '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12, '十三': 13,
          '十四': 14, '十五': 15, '十六': 16, '十七': 17, '十八': 18, '十九': 19}


def strip_prefix(txt, key):
    m = re.match(r'^' + re.escape(key) + r'([一二三四五六七八九十]+)?[：:\s]*(.*)$', txt)
    return m.group(2).strip() if m else txt


def num_of(txt, key):
    m = re.match(r'^' + re.escape(key) + r'([一二三四五六七八九十]+)', txt)
    return cn2int.get(m.group(1)) if m else None  # None => 视为 1


def fix(f):
    raw = open(f, encoding='utf-8').read()
    lines = raw.split('\n')
    h2 = []
    inf = False
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith('```'):
            inf = not inf
            continue
        if inf:
            continue
        if re.match(r'^##\s', l):
            h2.append((i, l[2:].strip()))
    yjx = [i for i, l in enumerate(lines)
           if l.strip().startswith('下一章预告') or l.strip().startswith('## 下一章预告')]
    def next_boundary(k):
        c = len(lines)
        if k + 1 < len(h2):
            c = min(c, h2[k + 1][0])
        for y in yjx:
            if y > h2[k][0]:
                c = min(c, y)
                break
        return c
    seen = {}
    dup = []
    for k, (i, txt) in enumerate(h2):
        if txt in seen:
            dup.append((i, next_boundary(k)))
        else:
            seen[txt] = i
    del_lines = set()
    for i, txt in h2:
        if txt == '' or re.match(r'^[\d一二三四五六七八九十]+[、.．]?$', txt):
            nx = [lines[i + 1].strip() if i + 1 < len(lines) else '',
                  lines[i + 2].strip() if i + 2 < len(lines) else '']
            if i + 1 >= len(lines) or any(x == '' or x.startswith('##') or x == '---' for x in nx):
                del_lines.add(i)
    removed = set(del_lines)
    for a, b in dup:
        for x in range(a, b):
            removed.add(x)
    buyi = [(i, t) for i, t in h2 if i not in removed and t.startswith('实战补遗')]
    fanwai = [(i, t) for i, t in h2 if i not in removed and t.startswith('番外')]
    newtext = {}

    def renumber(series, key):
        if not series:
            return
        nums = [num_of(t, key) or 1 for _, t in series]
        need = (nums[0] > 1) or (len(nums) != len(set(nums)))
        if not need:
            return
        for idx, (i, t) in enumerate(series, 1):
            newtext[i] = '## ' + key + (cn[idx] if idx > 1 else '') + '：' + strip_prefix(t, key)

    renumber(buyi, '实战补遗')
    renumber(fanwai, '番外')
    out = []
    for i, l in enumerate(lines):
        if i in removed:
            continue
        out.append(newtext[i] if i in newtext else l)
    open(f, 'w', encoding='utf-8').write('\n'.join(out))
    seq = [re.sub(r'^##\s*', '', l) for l in out
           if l.startswith('## 实战补遗') or l.startswith('## 番外')]
    print(f'{f}: dup{len(dup)} empty{len(del_lines)} 实战补遗×{len(buyi)} 番外×{len(fanwai)}')
    print('   ', ' / '.join(seq))


def verify():
    problems = 0
    for f in sorted(x for x in os.listdir(base) if re.match(r'^\d{2}-.*\.md$', x)):
        t = open(f, encoding='utf-8').read()
        h2 = re.findall(r'^##\s+(.+)$', t, re.M)
        for key in ('实战补遗', '番外'):
            seq = []
            for h in h2:
                if h.startswith(key):
                    m = re.match(r'^' + key + r'([一二三四五六七八九十]+)?', h)
                    seq.append(cn2int.get(m.group(1)) if m and m.group(1) else 1)
            if not seq:
                continue
            if len(seq) != len(set(seq)):
                print(f'  [问题] {f} {key} 重复编号: {seq}'); problems += 1
            elif seq != list(range(1, len(seq) + 1)):
                print(f'  [问题] {f} {key} 不连续(从{seq[0]}开始/缺号): {seq}'); problems += 1
    print('=== 校验完成, 问题数:', problems)


for f in sorted(x for x in os.listdir(base) if re.match(r'^\d{2}-.*\.md$', x)):
    fix(f)
print('--- 校验 ---')
verify()
print('DONE')
