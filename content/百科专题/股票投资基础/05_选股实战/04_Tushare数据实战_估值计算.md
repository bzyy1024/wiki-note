# Tushare数据实战：估值计算全流程

> 师徒对话录 · 第四篇
> 适用场景：从数据取数到最终估值结论的完整实操

---

## 开篇：用数据说话

前三篇课上完，小林的笔记本已经密密麻麻写满了公式和框架。

这天下午，老陈没有像往常一样拿出白板笔，而是把一台笔记本电脑推到小林面前。

「理论学完了，现在用数据说话。」

小林看了看屏幕，是一个打开的Python编辑器，光标在闪烁。

「老陈，我Python会一点，但不知道从哪里获取股票数据……」

「Tushare。」老陈拉了把椅子坐到小林旁边，「这是国内做得最完整的金融数据平台之一，三张财务报表、行情数据、分红数据，都能取到。今天我带你用茅台做一个完整分析。」

「为什么选茅台？」

「因为茅台是A股教科书级别的好公司，数据完整，没有造假疑虑，正好用来验证我们前三篇学的所有指标。」老陈打开Tushare文档，「但在开始写代码之前，我先问你——你觉得分析一家公司，数据获取的顺序应该是什么？」

小林想了想：「先取财务报表……三张表都要？」

「对，利润表、资产负债表、现金流量表，缺一不可。然后呢？」

「……估值数据？PE、PB？」

「还有？」

「分红数据……」

「好。你已经想到了四类数据，这就是我们今天要操作的全部。」

---

## 第一节：Tushare API全接口速查

### 环境配置

```python
import tushare as ts
import pandas as pd

# 初始化API（需提前在tushare.pro官网注册并获取token）
pro = ts.pro_api('你的TOKEN')   # 替换为实际token
```

> **注意**：Tushare积分说明
> - 基础财务数据（三表）：需要积分≥120
> - 日度行情指标（PE/PB）：需要积分≥120
> - 全部接口均需注册并实名认证

---

### 接口一：利润表

```python
df_income = pro.income(
    ts_code='600519.SH',
    start_date='20190101',
    end_date='20231231',
    fields='end_date,revenue,operate_profit,n_income_attr_p,'
           'ebit,grossprofit_margin'
)
```

| 字段名 | 中文含义 | 单位 |
|-------|---------|------|
| `end_date` | 报告期（如20231231=2023年年报） | — |
| `revenue` | 营业总收入 | 万元 |
| `operate_profit` | 营业利润 | 万元 |
| `n_income_attr_p` | 归母净利润 | 万元 |
| `ebit` | 息税前利润（EBIT） | 万元 |
| `grossprofit_margin` | 毛利率 | % |

---

### 接口二：资产负债表

```python
df_balance = pro.balancesheet(
    ts_code='600519.SH',
    start_date='20190101',
    end_date='20231231',
    fields='end_date,total_assets,total_liab,'
           'total_hldr_eqy_exc_min_int,accounts_receiv,'
           'inventories,goodwill,money_cap'
)
```

| 字段名 | 中文含义 | 单位 |
|-------|---------|------|
| `total_assets` | 总资产 | 万元 |
| `total_liab` | 总负债 | 万元 |
| `total_hldr_eqy_exc_min_int` | 股东权益（净资产，不含少数股东） | 万元 |
| `accounts_receiv` | 应收账款 | 万元 |
| `inventories` | 存货 | 万元 |
| `goodwill` | 商誉 | 万元 |
| `money_cap` | 货币资金 | 万元 |

---

### 接口三：现金流量表

```python
df_cash = pro.cashflow(
    ts_code='600519.SH',
    start_date='20190101',
    end_date='20231231',
    fields='end_date,n_cashflow_act,free_cashflow,'
           'c_pay_acq_const_fiolta'
)
```

| 字段名 | 中文含义 | 单位 |
|-------|---------|------|
| `n_cashflow_act` | 经营活动现金流净额 | 万元 |
| `free_cashflow` | 自由现金流（FCF） | 万元 |
| `c_pay_acq_const_fiolta` | 购建固定资产等支付现金（资本支出） | 万元 |

---

### 接口四：日度行情指标（PE/PB/股息率）

```python
df_basic = pro.daily_basic(
    ts_code='600519.SH',
    start_date='20190101',
    end_date='20231231',
    fields='trade_date,pe_ttm,pb,dv_ratio,total_mv'
)
```

| 字段名 | 中文含义 | 说明 |
|-------|---------|------|
| `trade_date` | 交易日期 | — |
| `pe_ttm` | 滚动市盈率（PE-TTM） | 过去12个月利润计算 |
| `pb` | 市净率（PB） | — |
| `dv_ratio` | 股息率（%） | — |
| `total_mv` | 总市值 | 万元 |

---

### 接口五：历史分红数据

```python
df_div = pro.dividend(
    ts_code='600519.SH',
    fields='end_date,div_grosspershare,record_date'
)
```

| 字段名 | 中文含义 |
|-------|---------|
| `end_date` | 分红对应年度 |
| `div_grosspershare` | 每股分红（税前，元/股） |
| `record_date` | 股权登记日 |

---

## 第二节：核心指标计算脚本（完整注释版）

老陈说：「接口用法学会了，现在把前三篇所有指标的计算代码写出来，一次性跑完。」

```python
import tushare as ts
import pandas as pd
import numpy as np

pro = ts.pro_api('你的TOKEN')

# ============================================================
# 一、数据获取
# ============================================================
ts_code     = '600519.SH'
start_date  = '20190101'
end_date    = '20231231'

df_income  = pro.income(ts_code=ts_code, start_date=start_date, end_date=end_date,
                        fields='end_date,revenue,n_income_attr_p,ebit,grossprofit_margin')
df_balance = pro.balancesheet(ts_code=ts_code, start_date=start_date, end_date=end_date,
                              fields='end_date,total_assets,total_liab,'
                                     'total_hldr_eqy_exc_min_int,accounts_receiv,'
                                     'inventories,goodwill,money_cap,lt_borr,st_borr')
df_cash    = pro.cashflow(ts_code=ts_code, start_date=start_date, end_date=end_date,
                          fields='end_date,n_cashflow_act,free_cashflow')
df_basic   = pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date,
                             fields='trade_date,pe_ttm,pb,dv_ratio,total_mv')

# 只保留年报（end_date结尾为1231）
for df in [df_income, df_balance, df_cash]:
    df.drop(df[~df['end_date'].str.endswith('1231')].index, inplace=True)

# 合并三表（以end_date为key）
df = df_income.merge(df_balance, on='end_date').merge(df_cash, on='end_date')
df = df.sort_values('end_date').reset_index(drop=True)

# ============================================================
# 二、指标计算
# ============================================================

# 【第一关：盈利质量】

# 1.1 现金含量（经营现金流/净利润，理想>0.8）
df['cash_quality'] = df['n_cashflow_act'] / df['n_income_attr_p']

# 1.2 应收账款/收入比值（趋势不能持续上升）
df['ar_ratio'] = df['accounts_receiv'] / df['revenue']

# 【第二关：资本效率】

# 2.1 ROE（净利润/股东权益）
df['roe'] = df['n_income_attr_p'] / df['total_hldr_eqy_exc_min_int']

# 2.2 杜邦三因子拆解
df['net_margin']      = df['n_income_attr_p'] / df['revenue']        # 净利率
df['asset_turnover']  = df['revenue'] / df['total_assets']           # 资产周转率
df['leverage']        = df['total_assets'] / df['total_hldr_eqy_exc_min_int']  # 权益乘数
# 验证：roe ≈ net_margin × asset_turnover × leverage
df['roe_check'] = df['net_margin'] * df['asset_turnover'] * df['leverage']

# 2.3 自由现金流质量（FCF/净利润，理想>0.7）
df['fcf_ratio'] = df['free_cashflow'] / df['n_income_attr_p']

# 【第三关：财务健康】

# 3.1 资产负债率（<60%为健康）
df['debt_ratio'] = df['total_liab'] / df['total_assets']

# 3.2 商誉/净资产（<30%为安全）
df['goodwill_ratio'] = df['goodwill'] / df['total_hldr_eqy_exc_min_int']

# 【第四关：成长质量】

# 4.1 收入5年CAGR
rev_start = df['revenue'].iloc[0]
rev_end   = df['revenue'].iloc[-1]
n_years   = len(df) - 1
cagr_rev  = (rev_end / rev_start) ** (1 / n_years) - 1

# 4.2 净利润5年CAGR
np_start  = df['n_income_attr_p'].iloc[0]
np_end    = df['n_income_attr_p'].iloc[-1]
cagr_np   = (np_end / np_start) ** (1 / n_years) - 1

# ============================================================
# 三、估值分析（基于daily_basic数据）
# ============================================================

df_basic = df_basic.dropna(subset=['pe_ttm']).sort_values('trade_date')

# PE历史分位（当前在过去5年历史中的位置）
current_pe    = df_basic['pe_ttm'].iloc[-1]
pe_percentile = (df_basic['pe_ttm'] < current_pe).mean()

# PB历史分位
current_pb    = df_basic['pb'].iloc[-1]
pb_percentile = (df_basic['pb'] < current_pb).mean()

# ============================================================
# 四、输出综合报告
# ============================================================
print("=" * 50)
print(f"综合分析报告：{ts_code}")
print("=" * 50)
print(f"\n【第一关：盈利质量】")
print(f"  5年现金含量：{df['cash_quality'].tolist()}")
print(f"  5年毛利率趋势：{df['grossprofit_margin'].tolist()}")
print(f"\n【第二关：资本效率】")
print(f"  5年ROE：{(df['roe']*100).round(1).tolist()} %")
print(f"  净利率/资产周转率/权益乘数（最新年）：")
print(f"  {df['net_margin'].iloc[-1]:.2%} / {df['asset_turnover'].iloc[-1]:.2f} / {df['leverage'].iloc[-1]:.2f}")
print(f"  5年FCF质量：{df['fcf_ratio'].tolist()}")
print(f"\n【第三关：财务健康】")
print(f"  最新资产负债率：{df['debt_ratio'].iloc[-1]:.1%}")
print(f"  最新商誉/净资产：{df['goodwill_ratio'].iloc[-1]:.1%}")
print(f"\n【第四关：成长质量】")
print(f"  收入5年CAGR：{cagr_rev:.1%}")
print(f"  净利润5年CAGR：{cagr_np:.1%}")
print(f"\n【估值评估】")
print(f"  当前PE-TTM：{current_pe:.1f} 倍，历史分位：{pe_percentile:.1%}")
print(f"  当前PB：{current_pb:.1f} 倍，历史分位：{pb_percentile:.1%}")
```

---

## 第三节：完整分析案例——以茅台为例

老陈运行了代码，一段数据打印出来。他没有直接说结论，而是转头问小林：

「好，数据出来了。你来读一读，第一关，现金含量怎么样？」

小林看了看屏幕（以下为示意性数字，反映茅台典型特征）：

**【盈利质量验证】**（示意性数字）

| 年份 | 净利润（亿） | 经营现金流（亿） | 现金含量 | 毛利率 |
|------|------------|----------------|---------|--------|
| 2019 | 412        | 498            | 1.21    | 91.2%  |
| 2020 | 467        | 521            | 1.12    | 91.5%  |
| 2021 | 525        | 604            | 1.15    | 91.8%  |
| 2022 | 627        | 712            | 1.14    | 92.0%  |
| 2023 | 748        | 820            | 1.10    | 92.1%  |

小林说：「现金含量全部大于1……这说明经营现金流比净利润还多？」

「对。」老陈点点头，「这叫'预收款效应'。经销商提前打款预订茅台，现金先到账，然后才确认收入，所以现金流往往领先于利润。这是极其健康的商业模式，第一关满分。」

「毛利率90%以上……」小林咋舌，「这是卖酒还是印钞票啊。」

「某种程度上，是的。」

**【资本效率验证】**（示意性数字）

| 年份 | ROE  | 净利率 | 资产周转率 | 权益乘数 |
|------|------|-------|-----------|---------|
| 2019 | 29.4% | 46.2% | 0.64      | 1.00    |
| 2020 | 30.8% | 47.1% | 0.65      | 1.01    |
| 2021 | 32.1% | 48.0% | 0.67      | 1.00    |
| 2022 | 34.0% | 49.3% | 0.69      | 1.00    |
| 2023 | 35.6% | 50.1% | 0.71      | 1.00    |

老陈问：「你看这个权益乘数，茅台杠杆倍数大概是多少？」

「……1.0倍，基本没有杠杆。」

「对。净资产就等于总资产，几乎是零负债。那它的ROE全靠什么驱动？」

小林仔细看了看：「净利率……50%左右，全靠利润率驱动。」

「这才叫真实的ROE。不靠杠杆，纯粹靠产品本身的定价权。这就是护城河最坚实的体现。」

**【成长质量验证】**（示意性数字）

```
收入5年CAGR：约17.8%
净利润5年CAGR：约16.1%
→ 收入CAGR > 净利润CAGR，利润率还在缓慢提升
→ 成长质量评级：优秀
```

**【估值评估】**（示意性数字）

```
当前PE-TTM：28倍
5年历史PE分位：42%（处于合理偏低区间）
历史均值：约35倍
当前PB：8.5倍
5年历史PB分位：38%

→ 绝对低估：PE低于历史均值（35倍→28倍）✓
→ 历史分位：PE处于42%，在合理区间偏低侧 ✓
→ 相对低估：白酒行业均值PE约25倍，茅台溢价不算过分 ✓
```

老陈说：「好，四关数据都看完了。综合来看，这家公司如何？」

小林整理了一下思路：「四关全过，盈利质量极高，资本效率强，财务健康，成长可持续。估值处于合理偏低位置……」

「结论？」

「可以纳入候选买入名单，等待估值进一步回落至低分位时分批买入。」

老陈点点头：「你学会了。」

---

## 第四节：Tushare字段中文对照速查表

### 利润表（pro.income）关键字段

| Tushare字段 | 中文含义 | 常用计算 |
|------------|---------|---------|
| `revenue` | 营业总收入 | 收入CAGR、毛利率分母 |
| `total_revenue` | 营业收入（合并口径） | — |
| `oper_cost` | 营业总成本 | — |
| `sell_exp` | 销售费用 | 费用率分析 |
| `admin_exp` | 管理费用 | 费用率分析 |
| `rd_exp` | 研发费用 | 研发强度计算 |
| `fin_exp` | 财务费用（利息净支出） | EBIT计算 |
| `ebit` | 息税前利润 | ROIC计算 |
| `n_income_attr_p` | 归母净利润 | 核心利润指标 |
| `grossprofit_margin` | 毛利率（%） | 直接使用 |
| `netprofit_margin` | 净利率（%） | 杜邦分析 |

### 资产负债表（pro.balancesheet）关键字段

| Tushare字段 | 中文含义 | 常用计算 |
|------------|---------|---------|
| `total_assets` | 总资产 | 资产负债率、ROA |
| `total_liab` | 总负债 | 资产负债率 |
| `total_hldr_eqy_exc_min_int` | 归母股东权益（净资产） | ROE计算 |
| `money_cap` | 货币资金 | 存贷双高检测 |
| `accounts_receiv` | 应收账款 | 应收比率 |
| `inventories` | 存货 | 存货增速 |
| `goodwill` | 商誉 | 商誉/净资产 |
| `st_borr` | 短期借款 | 流动性分析 |
| `lt_borr` | 长期借款 | 有息负债计算 |
| `bonds_payable` | 应付债券 | 有息负债计算 |

### 现金流量表（pro.cashflow）关键字段

| Tushare字段 | 中文含义 | 常用计算 |
|------------|---------|---------|
| `n_cashflow_act` | 经营活动现金流净额 | 现金含量（最重要） |
| `n_cashflow_inv_act` | 投资活动现金流净额 | 资本支出分析 |
| `n_cashflow_fnc_act` | 筹资活动现金流净额 | 融资行为分析 |
| `free_cashflow` | 自由现金流（FCF） | FCF质量计算 |
| `c_pay_acq_const_fiolta` | 购建固定资产支付现金 | 资本支出（CapEx） |
| `c_cash_equ_end_term` | 期末现金及等价物余额 | 与资产负债表核对 |

---

## 第五节：常见问题与注意事项

小林边看代码边问：「老陈，我发现有些数据取出来是空值，怎么处理？」

「Tushare的数据有几个常见陷阱，你要记住。」

**陷阱一：报告期问题**

Tushare财务数据默认包含四个季报（end_date以0331/0630/0930/1231结尾）。通常分析只用年报（1231），需手动筛选：

```python
# 只保留年报
df = df[df['end_date'].str.endswith('1231')]
```

**陷阱二：单位是万元**

Tushare财务数据单位均为**万元**，计算时注意换算，不能直接与以"亿元"为单位的数据混用：

```python
# 转换为亿元
df['revenue_yi'] = df['revenue'] / 10000
```

**陷阱三：字段为空（None/NaN）**

部分公司或特定年份可能缺少某字段（如商誉为0时可能返回NaN），需要用`fillna(0)`处理：

```python
df['goodwill'] = df['goodwill'].fillna(0)
```

**陷阱四：daily_basic数据量较大**

5年日度数据约1200行，取数时间较长。可以只取每年最后一个交易日：

```python
# 只取每年年末最后一个交易日
df_basic['year'] = df_basic['trade_date'].str[:4]
df_annual = df_basic.groupby('year').last().reset_index()
```

**陷阱五：ROIC中的有息负债需手动合并**

Tushare没有直接提供"有息负债"字段，需手动合并：

```python
# 有息负债 = 短期借款 + 长期借款 + 应付债券
df['interest_debt'] = (df['st_borr'].fillna(0)
                       + df['lt_borr'].fillna(0)
                       + df.get('bonds_payable', pd.Series(0, index=df.index)).fillna(0))
```

---

## 第六节：从数据到决策的完整流程图

老陈最后在纸上画了一张完整的分析流程：

```
第一步：数据获取（Tushare）
  ├── 利润表（revenue, n_income_attr_p, grossprofit_margin）
  ├── 资产负债表（total_assets, total_liab, equity, ar, goodwill, money_cap）
  ├── 现金流量表（n_cashflow_act, free_cashflow）
  └── 行情指标（pe_ttm, pb, dv_ratio）

第二步：四关筛选（量化指标）
  ├── 第一关：现金含量>0.8，毛利率稳定，应收比率不超标
  ├── 第二关：ROE>15%（净利率驱动），FCF质量>0.7
  ├── 第三关：负债率<60%，商誉<30%净资产，存贷不双高
  └── 第四关：收入CAGR>10%，利润增速匹配收入

第三步：估值评估（三维度框架）
  ├── 绝对低估：PE < 历史均值-1σ，或PB<1+ROE>10%
  ├── 相对低估：个股PE/行业PE < 0.8
  └── 历史分位：PE历史分位 < 30%

第四步：价值陷阱排查（七大陷阱对照）
  └── 周期/困境/杠杆/商誉/政策/竞争/流动性

第五步：安全边际计算（DCF简化版）
  └── 内在价值折价 > 30% 才买入

第六步：仓位决策
  ├── 四关全过 + 三维低估 + 安全边际充足 → 可重仓（组合20-30%）
  ├── 四关全过 + 估值合理 → 标配（组合10-15%）
  └── 不过四关 → 排除，不管价格多便宜
```

「把这个流程图打印出来，贴在你电脑旁边。」老陈说，「每次选股，从第一步走到第六步，一步不跳。」

「老陈，走完这六步，我就能选到好股票了？」

老陈摇了摇头：「能选到候选好股票。最后的决策，还需要你对行业的深度理解，对商业模式的判断，对管理层的评估……」

「那不还是要靠感觉？」小林有些沮丧。

「不是感觉。是**在足够多的基本功积累上，形成的判断直觉**。」老陈拍了拍他的肩膀，「这六步是底线，不过底线的直接淘汰；过了底线的，才值得你去深入研究，培养真正的判断力。」

「那……我还要学多久？」

「学投资没有终点。」老陈端起已经凉透了的茶，「但你已经入门了。」

---

## 追问思考题

### 题目一
用Tushare取到茅台2019-2023年数据后，你发现`free_cashflow`字段部分年份为空（NaN）。请问：你会怎么处理？另外，如何用现有字段手动推算自由现金流？

> **答案方向**：
> ①缺失值处理：首先检查数据质量，若是Tushare数据库本身缺失，可尝试将end_date时间范围扩大，或改用`report_type`参数指定年报类型；
> ②手动推算FCF：`FCF = 经营活动现金流净额 - 资本支出`，其中资本支出用字段`c_pay_acq_const_fiolta`（购建固定资产支付现金），计算为：`df['fcf_manual'] = df['n_cashflow_act'] - df['c_pay_acq_const_fiolta']`；
> ③注意：Tushare的`free_cashflow`字段定义可能与手动计算存在轻微差异（如是否扣除维持性资本支出与成长性资本支出），以自己的计算逻辑为准。

---

### 题目二
假设你用上述代码分析了A公司，得到以下结果：ROE连续5年=20%，现金含量连续5年=0.95，负债率=35%，收入CAGR=12%。当前PE历史分位=22%，PB历史分位=18%。但你注意到最近一年研发费用/收入从8%降至4%（该公司是医疗器械公司）。请做出综合评估：这家公司值得买入吗？最大的隐患是什么？

> **答案方向**：
> 综合来看，四关指标优秀，估值处于低分位，是典型的"好公司+低估值"组合，初步符合买入条件。
> 但**最大隐患是研发投入腰斩**：医疗器械属于科技密集型行业，研发费用/收入从8%降至4%，意味着未来的创新管线可能断档。可能原因：①公司主动削减研发以美化短期利润（管理层行为值得警惕）；②研发进入收获期，当期费用自然降低（需核查在研项目进度）；③业务模式从研发驱动转为销售驱动（战略转型）。结论：不能直接买入，需首先搞清楚研发降低的原因。若是管理层短视行为，应压低仓位或暂缓；若是正常研发周期节奏，则可继续。

---

*上一篇：[03\_财务造假识别\_十大预警信号](./03_财务造假识别_十大预警信号.md) ←*

---

## 附录：本系列文档索引

| 篇目 | 文件名 | 核心内容 |
|------|-------|---------|
| 第一篇 | `01_好公司的标准_量化筛选体系.md` | 四关筛选框架、ROE vs ROIC、CAGR计算 |
| 第二篇 | `02_低估值识别与价值陷阱.md` | 三维低估框架、七大价值陷阱、安全边际 |
| 第三篇 | `03_财务造假识别_十大预警信号.md` | 十大预警信号、三表交叉验证、康美案例 |
| 第四篇 | `04_Tushare数据实战_估值计算.md` | API速查、指标计算代码、茅台完整案例 |
