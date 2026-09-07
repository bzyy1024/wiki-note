$ErrorActionPreference = 'Stop'
$desktop = 'C:\Users\admin\Desktop'
$content = 'c:\www\Mine\wiki-note\content'

$src1 = Join-Path $desktop '写实的写作·把内容写充实'
$dst1 = Join-Path $content '个人成长\10-写实的写作·把内容写充实'

$src2 = Join-Path $desktop '设计的内功·视觉心法修炼手册'
$dst2 = Join-Path $content '人文社科\11-设计的内功·视觉心法修炼手册'

$src3 = Join-Path $desktop '一事十面·英语思维切片'
$dst3 = Join-Path $content '语言学习\05-一事十面·英语思维切片'

# 1) 先把 _SPEC.md（内部写作规格，不对外）移出到桌面单独留档
Move-Item -LiteralPath (Join-Path $src3 '_SPEC.md') -Destination (Join-Path $desktop '_SPEC-一事十面英语思维切片-内部写作规格（不对外）.md') -Force

# 2) 移动三门课到 wiki 对应分类
Move-Item -LiteralPath $src1 -Destination $dst1
Move-Item -LiteralPath $src2 -Destination $dst2
Move-Item -LiteralPath $src3 -Destination $dst3

Write-Output 'MOVE-OK'
