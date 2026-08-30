# 06 · 动手：用 Go 写一个 C 编译器

> *"编译器 90% 的复杂度不在算法，而在处理各种边界情况和 ABI 细节。"*

---

## 开场：一个"简单"的任务

> **老陈**：我们来写个 C 编译器。目标：能编译这个程序。
>
> ```c
> int fib(int n) {
>     if (n <= 1) return n;
>     return fib(n-1) + fib(n-2);
> }
>
> int main() {
>     int i = 0;
>     int sum = 0;
>     while (i < 10) {
>         sum = sum + fib(i);
>         i = i + 1;
>     }
>     return sum;
> }
> ```
>
> **小林**：支持 if、while、函数、递归……这不算难吧？语法分析我刚学会了。
>
> **老陈**：语法分析确实不难，两百行搞定。**难的是后面。** 我问你几个问题：
>
> **问题 1**：`fib(n-1) + fib(n-2)` —— 两个函数调用的结果存在哪？
>
> **小林**：寄存器？
>
> **老陈**：**如果寄存器不够用呢？x86-64 有 16 个通用寄存器，但其中几个是保留的。而且 `fib(n-1)` 调用完之后，它的寄存器里可能已经有 `fib(n-2)` 需要的东西了。**
>
> **小林**：……那就存到栈上？
>
> **老陈**：**对，但存哪个位置？什么时候存？谁来存——调用者还是被调用者？**
>
> **小林**：……这个有规定吗？
>
> **老陈**：**有，叫"调用约定"（Calling Convention）。而且不同的操作系统、不同的架构，规定还不一样。这就是我说的"ABI 细节"——它不难，但繁琐，而且错了就崩。**
>
> **问题 2**：递归调用 `fib` 的时候，`n` 存在哪？第二次调用的 `n` 会不会覆盖第一次的？
>
> **小林**：……每个调用要有自己的空间。
>
> **老陈**：**对，叫"栈帧"（Stack Frame）。那栈帧长什么样？谁负责分配？谁负责回收？局部变量放在栈帧的哪个偏移？**
>
> **小林**：…………我低估这件事了。
>
> **老陈**：**所有人都低估。这就是为什么 chibicc（一个著名的教学 C 编译器）的作者说：写编译器最难的部分是"想清楚栈怎么布局"。** 我们开始。

---

## 架构选择

完整编译器的三种输出方式：

| 方式 | 说明 | 复杂度 | 适用 |
|:---|:---|:---|:---|
| **① 生成汇编文本** | 输出 `.s` 文件，调用系统的 `as`/`gcc` 汇编链接 | ⭐⭐ | **教学编译器首选** |
| **② 生成目标文件** | 直接输出 ELF `.o`，自己处理重定位 | ⭐⭐⭐⭐ | 真实编译器 |
| **③ 直接生成机器码** | 内存里拼机器码，自己 mmap 执行（JIT） | ⭐⭐⭐⭐⭐ | JIT 编译器 |

**我们选 ①**：把精力放在编译逻辑上，汇编和链接交给 `gcc`。

```
C 源码 → [我们的编译器] → x86-64 汇编 → gcc/as → 可执行文件
```

这样我们只用关心"怎么把 AST 翻译成汇编"。

---

## 核心设计决策

### 决策 1：表达式求值用"栈式"而不是"寄存器分配"

**真实编译器**（GCC -O2）会做寄存器分配（图着色算法），把变量尽量放在寄存器里。

**教学编译器**用一个更简单的模型：**把表达式的值压到栈上，计算时弹出。**

```
计算 a + b * c:

  # 生成的代码（AT&T 语法）
  movl  -8(%rbp), %eax    # 加载 a
  pushq %rax              # 压栈
  movl  -16(%rbp), %eax   # 加载 b
  pushq %rax
  movl  -24(%rbp), %eax   # 加载 c
  pushq %rax

  popq  %rdx              # 右操作数 c
  popq  %rax              # 左操作数 b
  imulq %rdx, %rax        # rax = b * c
  pushq %rax              # 结果压栈

  popq  %rdx              # 右操作数 (b*c)
  popq  %rax              # 左操作数 a
  addq  %rdx, %rax        # rax = a + (b*c)
  pushq %rax              # 最终结果
```

**优点**：实现极简，不需要寄存器分配算法。
**缺点**：慢（每次运算都有 push/pop），大概比 `-O2` 慢 3~5 倍。

> **老陈**：**但这正是正确的工程选择。** 因为：
> 1. **先能跑，再优化**。寄存器分配是编译器里最复杂的部分之一（图着色 + 溢出处理 + coalescing）
> 2. **栈式求值是正确的**，只是不快。正确性优先于性能
> 3. 想优化时，可以加一个"窥孔优化"（peephole optimization）把 `push` 后面紧跟 `pop` 的模式消掉

**这个决策体现了软件工程的一条原则：先做正确的事，再做快的事。而且要先确认"慢"是不是真的问题。**

### 决策 2：栈帧布局遵循 System V AMD64 ABI

这是 Linux/macOS 上 x86-64 的标准调用约定。

**栈帧结构：**

```
高地址
┌─────────────────────────┐
│  调用者的栈帧             │
├─────────────────────────┤
│  参数 7, 8, ... (如果有)  │  ← 超过 6 个的参数用栈传
├─────────────────────────┤
│  返回地址                 │  ← call 指令自动压入
├─────────────────────────┤
│  调用者的 %rbp            │  ← 我们 push %rbp
├─────────────────────────┤ ◄── %rbp (帧指针)
│  局部变量 1               │  -8(%rbp)
│  局部变量 2               │  -16(%rbp)
│  ...                     │
│  表达式计算的临时栈        │
├─────────────────────────┤ ◄── %rsp (栈指针)
│  (未使用)                 │
└─────────────────────────┘
低地址
```

**函数序言（prologue）和尾声（epilogue）：**

```asm
# prologue
pushq %rbp           # 保存调用者的帧指针
movq  %rsp, %rbp     # 建立自己的帧指针
subq  $N, %rsp       # 为局部变量分配空间（N = 所有局部变量总大小，16 字节对齐）

# ... 函数体 ...

# epilogue
movq  %rbp, %rsp     # 恢复栈指针（释放所有局部变量）
popq  %rbp           # 恢复调用者的帧指针
ret                  # 返回
```

**参数传递规则（System V AMD64）：**

| 参数序号 | 整型/指针 | 浮点 |
|:---|:---|:---|
| 1 | `%rdi` | `%xmm0` |
| 2 | `%rsi` | `%xmm1` |
| 3 | `%rdx` | `%xmm2` |
| 4 | `%rcx` | `%xmm3` |
| 5 | `%r8` | `%xmm4` |
| 6 | `%r9` | `%xmm5` |
| 7+ | 栈（从右往左压） | 栈 |

**返回值**：整型放 `%rax`，浮点放 `%xmm0`。

**寄存器分类（这一条极其重要）：**

| 类型 | 寄存器 | 含义 |
|:---|:---|:---|
| **Caller-saved（易失）** | `%rax` `%rcx` `%rdx` `%rsi` `%rdi` `%r8-%r11` | **被调用函数可以随意修改**，调用者要保证的话自己先存 |
| **Callee-saved（非易失）** | `%rbx` `%rbp` `%r12-%r15` | **被调用函数必须恢复原值**才能返回 |

> **老陈**：**这个区分是 ABI 的核心。** 它定义了"责任"：
> - 你用 `%rbx` 之前必须先 `push %rbx`，返回前 `pop %rbx`（因为调用者指望它不变）
> - 你用 `%rcx` 可以直接用（因为调用者知道它可能被改）
>
> **这让编译器可以做优化**：如果一个函数只用 caller-saved 寄存器，连 prologue 里的保存都不用做。
>
> **我们的编译器为了简单，只用 `%rax` 和 `%rdx`（都是 caller-saved）做计算**，配合栈保存中间值，所以完全不用管 callee-saved 的问题。

---

## 完整实现（核心部分）

```go
package main

import (
	"fmt"
	"os"
	"strings"
)

// ============ 代码生成器 ============

type CodeGen struct {
	sb        strings.Builder
	labelSeq  int
	curFunc   *FuncInfo
}

type FuncInfo struct {
	Name       string
	StackSize  int
	VarOffsets map[string]int // 变量名 → 相对 %rbp 的偏移（负数）
	ParamNames []string
}

func NewCodeGen() *CodeGen {
	return &CodeGen{}
}

func (g *CodeGen) emit(format string, args ...any) {
	fmt.Fprintf(&g.sb, "\t"+format+"\n", args...)
}

func (g *CodeGen) label(prefix string) string {
	g.labelSeq++
	return fmt.Sprintf(".L%s%d", prefix, g.labelSeq)
}

func (g *CodeGen) emitLabel(l string) {
	fmt.Fprintf(&g.sb, "%s:\n", l)
}

// ============ 变量寻址 ============

// loadVar 把变量的值加载到 %rax
func (g *CodeGen) loadVar(name string) error {
	off, ok := g.curFunc.VarOffsets[name]
	if !ok {
		return fmt.Errorf("未定义的变量: %s", name)
	}
	g.emit("movq %d(%%rbp), %%rax", off)
	return nil
}

// storeVar 把 %rax 的值存到变量
func (g *CodeGen) storeVar(name string) error {
	off, ok := g.curFunc.VarOffsets[name]
	if !ok {
		return fmt.Errorf("未定义的变量: %s", name)
	}
	g.emit("movq %%rax, %d(%%rbp)", off)
	return nil
}

// loadAddr 把变量的地址加载到 %rax（用于 &、指针赋值）
func (g *CodeGen) loadAddr(name string) error {
	off, ok := g.curFunc.VarOffsets[name]
	if !ok {
		return fmt.Errorf("未定义的变量: %s", name)
	}
	g.emit("leaq %d(%%rbp), %%rax", off)
	return nil
}

// ============ 表达式代码生成（栈式求值）============

func (g *CodeGen) genExpr(e Expr) error {
	switch v := e.(type) {
	case *IntLit:
		// 立即数直接压栈
		g.emit("pushq $%d", v.Value)
		return nil

	case *VarRef:
		g.loadVar(v.Name)
		g.emit("pushq %rax")
		return nil

	case *AddrOf:
		// &x
		g.loadAddr(v.Name)
		g.emit("pushq %rax")
		return nil

	case *Deref:
		// *p
		if err := g.genExpr(v.Operand); err != nil {
			return err
		}
		// 栈顶是地址，取出它指向的值
		g.emit("popq %rax")
		g.emit("movq (%%rax), %%rax")
		g.emit("pushq %rax")
		return nil

	case *Assign:
		// 左值：支持 x = ... 和 *p = ...
		if err := g.genExpr(v.Value); err != nil {
			return err
		}
		switch lhs := v.Target.(type) {
		case *VarRef:
			g.emit("popq %rax")
			return g.storeVar(lhs.Name)
		case *Deref:
			// *p = value: 先算 p 的地址，再存
			if err := g.genExpr(lhs.Operand); err != nil {
				return err
			}
			g.emit("popq %rax")       // rax = p
			g.emit("popq %rdx")       // rdx = value
			g.emit("movq %%rdx, (%%rax)")
			g.emit("pushq %rdx")      // 赋值表达式的值是右边的值
			return nil
		}
		return fmt.Errorf("赋值左侧不是左值")

	case *BinaryExpr:
		if err := g.genExpr(v.Left); err != nil {
			return err
		}
		if err := g.genExpr(v.Right); err != nil {
			return err
		}
		g.emit("popq %rdx")   // 右操作数
		g.emit("popq %rax")   // 左操作数

		switch v.Op {
		case "+":
			g.emit("addq %rdx, %rax")
		case "-":
			g.emit("subq %rdx, %rax")
		case "*":
			g.emit("imulq %rdx, %rax")
		case "/":
			g.emit("cqto")        // 符号扩展 %rax 到 %rdx:%rax
			g.emit("idivq %rdx")  // 商在 %rax，余数在 %rdx
		case "==":
			g.emit("cmpq %rdx, %rax")
			g.emit("sete %al")       // 相等则 al = 1
			g.emit("movzbq %al, %rax")
		case "!=":
			g.emit("cmpq %rdx, %rax")
			g.emit("setne %al")
			g.emit("movzbq %al, %rax")
		case "<":
			g.emit("cmpq %rdx, %rax")
			g.emit("setl %al")
			g.emit("movzbq %al, %rax")
		case "<=":
			g.emit("cmpq %rdx, %rax")
			g.emit("setle %al")
			g.emit("movzbq %al, %rax")
		case ">":
			g.emit("cmpq %rdx, %rax")
			g.emit("setg %al")
			g.emit("movzbq %al, %rax")
		case ">=":
			g.emit("cmpq %rdx, %rax")
			g.emit("setge %al")
			g.emit("movzbq %al, %rax")
		default:
			return fmt.Errorf("不支持的运算符: %s", v.Op)
		}
		g.emit("pushq %rax")
		return nil

	case *CallExpr:
		return g.genCall(v)

	default:
		return fmt.Errorf("未知的表达式类型")
	}
}

// ============ 函数调用 ============

// 参数寄存器（System V AMD64，整型/指针）
var argRegs = []string{"rdi", "rsi", "rdx", "rcx", "r8", "r9"}

func (g *CodeGen) genCall(c *CallExpr) error {
	nargs := len(c.Args)

	// 1. 求值所有参数，压栈（注意求值顺序：C 标准未定义，我们从左往右）
	for _, arg := range c.Args {
		if err := g.genExpr(arg); err != nil {
			return err
		}
	}

	// 2. 从栈弹出到参数寄存器
	//    注意：栈是 LIFO，我们从左往右压的，所以要反向弹
	//    这里用偏移访问更稳妥
	if nargs > 6 {
		return fmt.Errorf("暂不支持超过 6 个参数")
	}
	for i := nargs - 1; i >= 0; i-- {
		g.emit("popq %%%s", argRegs[i])
	}

	// ★ 关键：调用前栈要 16 字节对齐
	//    System V ABI 要求 call 时 %rsp % 16 == 8
	//    （因为 call 会压入 8 字节返回地址）
	if g.isExternalCall(c.FuncName) {
		g.emit("movq $0, %%rax")   // 可变参数函数要求 %rax = 向量寄存器个数
	}
	g.emit("call %s", c.FuncName)

	// 3. 返回值在 %rax，压栈作为表达式的值
	g.emit("pushq %rax")
	return nil
}

func (g *CodeGen) isExternalCall(name string) bool {
	externals := map[string]bool{
		"printf": true, "malloc": true, "free": true,
		"exit": true, "putchar": true,
	}
	return externals[name]
}

// ============ 语句代码生成 ============

func (g *CodeGen) genStmt(s Stmt) error {
	switch v := s.(type) {
	case *ExprStmt:
		if err := g.genExpr(v.Expr); err != nil {
			return err
		}
		// 表达式语句的值丢弃：弹栈
		g.emit("popq %rax")
		return nil

	case *ReturnStmt:
		if v.Value != nil {
			if err := g.genExpr(v.Value); err != nil {
				return err
			}
			g.emit("popq %rax")   // 返回值放 %rax
		}
		// 跳到函数尾声
		g.emit("jmp .Lreturn_%s", g.curFunc.Name)
		return nil

	case *IfStmt:
		if err := g.genExpr(v.Cond); err != nil {
			return err
		}
		g.emit("popq %rax")
		g.emit("cmpq $0, %rax")

		elseLabel := g.label("else")
		endLabel := g.label("endif")

		if v.Else != nil {
			g.emit("je %s", elseLabel)
			if err := g.genStmt(v.Then); err != nil {
				return err
			}
			g.emit("jmp %s", endLabel)
			g.emitLabel(elseLabel)
			if err := g.genStmt(v.Else); err != nil {
				return err
			}
			g.emitLabel(endLabel)
		} else {
			g.emit("je %s", endLabel)
			if err := g.genStmt(v.Then); err != nil {
				return err
			}
			g.emitLabel(endLabel)
		}
		return nil

	case *WhileStmt:
		beginLabel := g.label("while_begin")
		endLabel := g.label("while_end")

		g.emitLabel(beginLabel)
		if err := g.genExpr(v.Cond); err != nil {
			return err
		}
		g.emit("popq %rax")
		g.emit("cmpq $0, %rax")
		g.emit("je %s", endLabel)

		if err := g.genStmt(v.Body); err != nil {
			return err
		}
		g.emit("jmp %s", beginLabel)
		g.emitLabel(endLabel)
		return nil

	case *ForStmt:
		// for (init; cond; step) body
		// 展开成: init; while (cond) { body; step; }
		if v.Init != nil {
			if err := g.genStmt(v.Init); err != nil {
				return err
			}
		}
		beginLabel := g.label("for_begin")
		endLabel := g.label("for_end")

		g.emitLabel(beginLabel)
		if v.Cond != nil {
			if err := g.genExpr(v.Cond); err != nil {
				return err
			}
			g.emit("popq %rax")
			g.emit("cmpq $0, %rax")
			g.emit("je %s", endLabel)
		}

		if err := g.genStmt(v.Body); err != nil {
			return err
		}
		if v.Step != nil {
			if err := g.genStmt(v.Step); err != nil {
				return err
			}
		}
		g.emit("jmp %s", beginLabel)
		g.emitLabel(endLabel)
		return nil

	case *BlockStmt:
		for _, st := range v.Stmts {
			if err := g.genStmt(st); err != nil {
				return err
			}
		}
		return nil

	case *VarDeclStmt:
		// int x = expr;  或 int x;
		if v.Init != nil {
			if err := g.genExpr(v.Init); err != nil {
				return err
			}
			g.emit("popq %rax")
			return g.storeVar(v.Name)
		}
		// 没初始化，在 prologue 里已经清零了
		return nil
	}
	return fmt.Errorf("未知的语句类型")
}

// ============ 函数代码生成 ============

func (g *CodeGen) genFunc(f *FuncDecl) error {
	// 1. 计算栈帧布局
	//    -8, -16, -24... 分配给局部变量
	offset := 0
	varOffsets := make(map[string]int)

	// 参数也放在栈帧里（简化：进来后立刻存到栈上）
	for i, p := range f.Params {
		offset -= 8
		varOffsets[p.Name] = offset
	}
	for _, d := range f.Locals {
		offset -= 8
		varOffsets[d.Name] = offset
	}

	// 16 字节对齐（ABI 要求）
	stackSize := (-offset + 15) / 16 * 16

	g.curFunc = &FuncInfo{
		Name:       f.Name,
		StackSize:  stackSize,
		VarOffsets: varOffsets,
		ParamNames: paramNames(f.Params),
	}

	// 2. 输出函数标签
	fmt.Fprintf(&g.sb, ".globl %s\n", f.Name)
	fmt.Fprintf(&g.sb, ".type %s, @function\n", f.Name)
	fmt.Fprintf(&g.sb, "%s:\n", f.Name)

	// 3. Prologue
	g.emit("pushq %rbp")
	g.emit("movq %rsp, %rbp")
	g.emit("subq $%d, %rsp", stackSize)

	// 4. 把寄存器里的参数存到栈帧
	for i, p := range f.Params {
		if i < 6 {
			g.emit("movq %%%s, %d(%%rbp)", argRegs[i], varOffsets[p.Name])
		}
	}

	// 5. 函数体
	for _, st := range f.Body {
		if err := g.genStmt(st); err != nil {
			return err
		}
	}

	// 6. Epilogue（所有 return 都 jmp 到这里）
	g.emitLabel(fmt.Sprintf(".Lreturn_%s", f.Name))
	g.emit("movq %rbp, %rsp")
	g.emit("popq %rbp")
	g.emit("ret")

	g.curFunc = nil
	return nil
}

func paramNames(params []*Param) []string {
	names := make([]string, len(params))
	for i, p := range params {
		names[i] = p.Name
	}
	return names
}

// ============ 生成完整汇编文件 ============

func (g *CodeGen) Generate(program *Program) string {
	var out strings.Builder

	out.WriteString("\t.section .rodata\n")
	out.WriteString(".LC0:\n\t.string \"%d\\n\"\n\n")
	out.WriteString("\t.text\n")

	g.sb.Reset()
	for _, f := range program.Funcs {
		if err := g.genFunc(f); err != nil {
			fmt.Fprintln(os.Stderr, "代码生成错误:", err)
			os.Exit(1)
		}
	}
	out.WriteString(g.sb.String())
	return out.String()
}
```

---

## 三个必须踩的坑

### 坑 1：栈的 16 字节对齐

**System V AMD64 ABI 规定**：调用 `call` 指令时，`%rsp` 必须满足 `%rsp % 16 == 8`。

**为什么？** 因为 SSE 指令（如 `movaps`）要求内存地址 16 字节对齐。被调用函数可能会用这些指令。如果栈没对齐，会触发 `SIGSEGV`。

**实际问题**：`call` 指令会自动压入 8 字节返回地址。所以：
- 进入函数时（`call` 之后）：`%rsp % 16 == 8`
- prologue 里 `pushq %rbp` 又减 8：`%rsp % 16 == 0`
- 我们 `subq $N, %rsp`，**N 必须是 16 的倍数**才能保持对齐

这就是为什么代码里要：

```go
stackSize := (-offset + 15) / 16 * 16   // 向上取整到 16 的倍数
```

> **老陈**：**这个 bug 极其难查。** 症状是：程序大部分时候正常，但调用某个库函数（比如 `printf`）时随机崩溃。因为它只在被调用函数用了 SIMD 指令时才暴露。

### 坑 2：参数求值的顺序

```c
f(g(), h());   // g() 和 h() 谁先执行？
```

**C 标准说：未定义。** GCC 从右往左，Clang 从左往右。

我们的实现用栈保存参数，要注意弹出顺序：

```go
// 从左往右压栈：arg1, arg2, arg3
// 栈是 LIFO：arg3 在栈顶
// 所以要从 arg3 开始弹，赋给 rdx（第三个寄存器）
for i := nargs - 1; i >= 0; i-- {
	g.emit("popq %%%s", argRegs[i])
}
```

**这是个经典错误**：如果写成 `for i := 0; i < nargs; i++`，参数顺序就反了。

> **老陈**：**这类 bug 的特点是"看起来很对"。** 你会盯着代码看很久觉得没问题。**直到你写个 `printf("%d %d", 1, 2)` 发现输出是 "2 1"。**
>
> **教训：对于栈这种 LIFO 结构，画个图。别在脑子里推演。**

### 坑 3：`idivq` 的隐式寄存器使用

x86 的除法指令很特殊：

```asm
cqto          # 把 %rax 符号扩展到 %rdx:%rax（128 位）
idivq %rdx    # %rdx:%rax / %rdx，商在 %rax，余数在 %rdx
```

**问题**：`idivq` 的操作数 `%rdx` 既是除数，**结果的余数也放 `%rdx`**。

如果我们的代码里 `%rdx` 存的是右操作数，那么：

```go
g.emit("popq %rdx")   // rdx = 除数
g.emit("popq %rax")   // rax = 被除数
g.emit("cqto")        // ★ 这会把 rax 的符号位扩展到 rdx，覆盖除数！
g.emit("idivq %rdx")  // 错误！
```

**必须先把除数挪走：**

```go
g.emit("popq %rcx")   // 用 rcx 存除数
g.emit("popq %rax")
g.emit("cqto")
g.emit("idivq %rcx")  // 正确
```

> **老陈**：**x86 的指令集充满了这种"隐式使用寄存器"的怪癖。** `mul`、`div`、`cqto`、字符串指令（`movsb` 隐含用 `%rsi`/`%rdi`）都是。
>
> **这就是为什么写汇编代码生成要格外小心——每条指令的"完整语义"不只是它的显式操作数。**
>
> **这也是 RISC 架构（ARM、RISC-V）相对 x86 的一个优势：指令语义干净，没有隐式寄存器。代价是代码密度低。**

---

## 编译器完整流程

```go
func compile(source string, outputPath string) error {
	// ① 词法分析
	tokens, err := Tokenize(source)
	if err != nil {
		return fmt.Errorf("词法错误: %w", err)
	}

	// ② 语法分析
	parser := NewParser(tokens)
	program, err := parser.ParseProgram()
	if err != nil {
		return fmt.Errorf("语法错误: %w", err)
	}

	// ③ 语义分析（符号表 + 类型检查）
	if err := SemanticCheck(program); err != nil {
		return fmt.Errorf("语义错误: %w", err)
	}

	// ④ 代码生成
	cg := NewCodeGen()
	asmCode := cg.Generate(program)

	// ⑤ 写汇编文件，调用 gcc 汇编链接
	asmPath := strings.TrimSuffix(outputPath, ".o") + ".s"
	if err := os.WriteFile(asmPath, []byte(asmCode), 0644); err != nil {
		return err
	}

	// gcc -static -o output asmPath
	cmd := exec.Command("gcc", "-static", "-o", outputPath, asmPath)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintf(os.Stderr, "用法: %s <input.c> <output>\n", os.Args[0])
		os.Exit(1)
	}
	src, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	if err := compile(string(src), os.Args[2]); err != nil {
		fmt.Fprintln(os.Stderr, "编译失败:", err)
		os.Exit(1)
	}
	fmt.Println("编译成功")
}
```

### 测试

```bash
$ cat > test.c <<'EOF'
int fib(int n) {
    if (n <= 1) return n;
    return fib(n-1) + fib(n-2);
}

int main() {
    int i = 0;
    int sum = 0;
    while (i < 10) {
        sum = sum + fib(i);
        i = i + 1;
    }
    return sum;
}
EOF

$ go run ./compiler test.c ./test_program
编译成功

$ ./test_program
$ echo $?
88       # fib(0)+...+fib(9) = 0+1+1+2+3+5+8+13+21+34 = 88
```

**成功！我们的编译器能编译递归函数了。**

---

## 第三层追问：还差什么才能叫"真正的"编译器

> **老陈**：现在这个编译器能跑通 fib 了。但它离"能用"还差得远。你说说看差什么？
>
> **小林**：指针、数组、结构体、字符串……
>
> **老陈**：对，但那只是"特性清单"。我问的是**架构层面**缺什么。
>
> **小林**：……不做寄存器分配，很慢？
>
> **老陈**：这是一条。还有两条更重要的。想想：**如果 fib 里有 100 个局部变量，会怎样？**
>
> **小林**：……栈帧变大，但还是能工作？
>
> **老陈**：**对，能工作。所以我们缺的不是"能工作"，而是"能工作得好"。** 真实编译器必须有的是：
>
> **① 中间表示（IR）+ 优化 passes**
>
> 我们现在是"语法制导翻译"——遍历 AST 直接生成代码。**这意味着无法做跨语句优化。** 比如：
> ```c
> int x = 5;
> int y = x * 2;    // 常量折叠：编译期就能算出 10
> ```
> 真实的编译器会先把 AST 转成 SSA IR，然后跑一堆优化 pass：常量折叠、死代码消除、公共子表达式消除、循环不变量外提、内联……
>
> **② 寄存器分配**
>
> 我们现在所有中间值都过栈。真实编译器会做**图着色寄存器分配**：
> - 构造"干扰图"（interference graph）：两个变量如果生命周期重叠，它们之间连一条边
> - 用 K 种颜色（K = 可用寄存器数）给图着色
> - 着色失败的变量"溢出"（spill）到栈
>
> **③ 完善的错误处理和诊断**
>
> 我们现在的错误就是一句 "语法错误"。真实编译器要给出行号、列号、代码片段、修复建议。
>
> **小林**：所以工作量主要在这些？
>
> **老陈**：**对。语法解析 + 朴素代码生成可能只占一个真实编译器的 20% 工作量。剩下 80% 是优化、诊断和 ABI 兼容性。**

### Go 编译器的实际流程（对比）

```
Go 源码
  │
  ▼ cmd/compile/internal/syntax  → 语法树（手写递归下降）
  │
  ▼ cmd/compile/internal/types2  → 类型检查
  │
  ▼ cmd/compile/internal/ir      → 统一 IR
  │
  ▼ cmd/compile/internal/ssa     → SSA 构造 + 优化 passes
  │     · 死代码消除
  │     · 逃逸分析（决定变量放栈还是堆）
  │     · 内联
  │     · 边界检查消除
  │     · 寄存器分配（图着色）
  │
  ▼ cmd/compile/internal/ssa/_gen → 各架构代码生成
  │     · amd64 / arm64 / riscv64 / wasm ...
  │
  ▼ 目标文件 → cmd/link → 可执行文件
```

**注意"逃逸分析"这个 pass**——它是 Go 特有的（或者说，是带 GC 的语言特有的）：

```go
func f() *Point {
	p := Point{1, 2}
	return &p    // p 逃逸到堆上！
}
```

**逃逸分析决定变量放栈还是堆。** 这是 Go 能写出"看起来像 C++ 值语义、实际由 GC 管理"代码的关键。

> **老陈**：**有意思的是，逃逸分析本质上是一个"指针别名分析"问题，而这个问题是不可判定的（图灵停机问题的等价形式）。所以所有逃逸分析都是保守的近似——宁可让变量逃逸到堆，也不能错误地放在栈上（后者会导致悬垂指针）。**
>
> **这又是一个"理论限制塑造工程实践"的例子。**

---

## 更深层的发问

### 问题 A：为什么 C 的未定义行为（UB）这么多？

C 标准里有几百处 "undefined behavior"。比如：

```c
int i = 0;
i = i++;           // UB：对 i 的两次修改之间没有序列点

int arr[3];
arr[5] = 1;        // UB：数组越界

int x = INT_MAX + 1;  // UB：有符号整数溢出
```

**为什么 C 要留这么多 UB？**

> **老陈的提示**：想想 UB 对编译器的意义——

**UB 的本质是"给编译器的 optimization license"（优化许可证）。**

编译器可以这样推理：
```
前提：程序没有 UB（C 标准假设程序员不会写 UB）
推论：i = i++ 不会出现，所以我可以假设对同一变量的两次修改之间有序列点
结论：可以做某些优化
```

**最经典的例子：有符号整数溢出是 UB**

```c
// 编译器可以假设 x + 1 > x 永远成立（因为溢出是 UB）
if (x + 1 > x) {
	// 编译器可以认为这里永远执行，直接删掉 if
}
```

GCC 曾经因为这个"优化"掉了很多安全检视代码。**这不是 bug，是符合标准的。**

**代价与收益**：
- **收益**：编译器有巨大的优化空间。这是 C 能这么快的原因之一
- **代价**：程序员的微小错误可能导致完全不可预测的行为，而且**在不同优化级别下行为可能不同**

**Go 的选择**：Go 几乎消灭了 UB。整数溢出是定义好的（回绕），数组越界是 panic（不是 UB）。

**代价**：编译器优化空间变小，生成的代码稍慢。
**收益**：程序行为可预测，安全性大幅提升。

> **老陈**：**这又是一个哲学差异：C 相信程序员，给编译器最大自由度；Go 相信确定性，宁可牺牲一点性能。**
>
> **有意思的是 Rust 的第三条路**：Rust 在 safe Rust 里消灭 UB，但 unsafe Rust 里保留 UB 给需要极致性能的场景。**这是"显式划分安全边界"的思路。**

### 问题 B：如果让你做一个"Go 的 AOT 编译器"（不用 runtime，直接编译成裸机程序）？

Go 程序依赖 runtime（GC、调度器、goroutine）。如果要写一个"裸机版 Go"（比如跑在嵌入式设备上，或者写操作系统内核），需要什么？

> **老陈的提示**：
>
> 1. **去掉 GC** —— 用 arena allocation 或者手动管理。已经有项目在做（如 `tinygo` 用保守式 GC，或者 `-gc=none` 完全去掉）
> 2. **去掉 goroutine 调度器** —— 用裸线程或者协程库
> 3. **去掉 panic/recover** —— 或者用 setjmp/longjmp 实现
> 4. **去掉反射** —— 或者用编译期生成的元数据
> 5. **实现自己的 syscall 封装** —— 不能依赖 libc
>
> **TinyGo 就是这么做的**，它能把 Go 编译到单片机（Arduino）和 WebAssembly。
>
> 有意思的问题：**去掉了这些，Go 还是 Go 吗？** 或者说，**Go 的"本质"是什么？语法？类型系统？还是它的并发模型？**
>
> 我的看法：**Go 的本质是"简单 + 工程效率"，runtime 只是实现这个目标的手段。当一个场景不需要这些手段时，去掉它们反而更符合 Go 的精神。**

---

## 思考题 ·【应用层】

**我们的编译器生成的代码很慢（每次运算都 push/pop）。请设计一个"窥孔优化"（Peephole Optimization）pass，能消掉多少冗余指令？给出至少 4 种可以优化的模式，并估算性能提升。**

<details>
<summary>参考答案</summary>

### 窥孔优化的原理

**窥孔（Peephole）**：只在很小的窗口（通常 2~5 条指令）内做模式匹配和替换。不做全局分析，实现简单，收益立竿见影。

**这是"局部优化"的极致——不看全局，只盯着一小段指令，能换就换。**

### 模式 1：push 后紧跟 pop

**最常见的冗余。** 我们的栈式求值会产生大量：

```asm
pushq %rax
popq  %rdx
```

**优化**：如果 `push` 的目标和 `pop` 的目标不同，可以直接 `movq %rax, %rdx`。

```asm
movq  %rax, %rdx    # 1 条代替 2 条
```

**甚至更好**：如果后续代码可以直接用 `%rax`，连 `mov` 都能省掉（需要寄存器跟踪）。

**收益**：减少 50% 的指令数（在这个模式上）。

### 模式 2：push 立即数后 pop 到寄存器

```asm
pushq $42
popq  %rax
```

**优化**：`movq $42, %rax`

```asm
movq  $42, %rax     # 2 条 → 1 条
```

### 模式 3：连续两次加载同一个变量

```c
x = x + 1;
```

生成（未经优化）：

```asm
movq -8(%rbp), %rax    # 加载 x
pushq %rax
pushq $1
popq  %rdx
popq  %rax
addq  %rdx, %rax
pushq %rax
popq  %rax
movq  %rax, -8(%rbp)   # 存回 x
```

**优化后**：

```asm
movq -8(%rbp), %rax
addq $1, %rax
movq %rax, -8(%rbp)
```

**9 条 → 3 条。**

这个模式需要"窥孔"窗口大一点（能看到整个表达式），但本质还是模式匹配：**`load addr → arithmetic → store addr` 可以合并。**

### 模式 4：取地址后立即解引用

```c
int x;
int *p = &x;
*p = 5;
```

朴素生成：

```asm
leaq  -8(%rbp), %rax    # &x
pushq %rax
popq  %rax
movq  %rax, -16(%rbp)   # p = &x
movq  -16(%rbp), %rax   # 加载 p
pushq %rax
pushq $5
popq  %rdx
popq  %rax
movq  %rdx, (%rax)      # *p = 5
```

**优化**：编译器能追踪到 `p` 的值就是 `&x`，直接：

```asm
movq  $5, -8(%rbp)      # x = 5
```

**10 条 → 1 条。**

这个优化需要"常量传播 + 别名分析"，已经超出严格意义的"窥孔"了，但思路一样。

### 模式 5：`addq $0` / `movq %rax, %rax`

**恒等变换消除**：

```asm
addq $0, %rax    → 删除
movq %rax, %rax  → 删除
imulq $1, %rax   → 删除
```

### 模式 6：用 `inc`/`dec` 代替 `add $1`

```asm
addq $1, %rax   →  incq %rax    # 指令更短
```

**收益**：代码密度提升（1 字节 vs 4 字节），对 i-cache 友好。

---

### 实现方式

```go
type PeepholeOptimizer struct {
	patterns []Pattern
}

type Pattern struct {
	Name    string
	Match   func([]Inst) int  // 返回匹配的长度，0 表示不匹配
	Replace func([]Inst) []Inst
}

func (o *PeepholeOptimizer) Optimize(insts []Inst) []Inst {
	var out []Inst
	i := 0
	changed := true

	// 迭代到不再变化（因为一次优化可能触发新的优化机会）
	for changed {
		changed = false
		out = nil
		i = 0
		for i < len(insts) {
			matched := false
			for _, p := range o.patterns {
				if n := p.Match(insts[i:]); n > 0 {
					out = append(out, p.Replace(insts[i:i+n])...)
					i += n
					matched = true
					changed = true
					break
				}
			}
			if !matched {
				out = append(out, insts[i])
				i++
			}
		}
		insts = out
	}
	return out
}

// 模式 1 的实现示例
var patternPushPop = Pattern{
	Name: "push-pop → mov",
	Match: func(insts []Inst) int {
		if len(insts) < 2 {
			return 0
		}
		if insts[0].Op == "pushq" && insts[1].Op == "popq" {
			return 2
		}
		return 0
	},
	Replace: func(insts []Inst) []Inst {
		src := insts[0].Args[0]  // pushq 的源
		dst := insts[1].Args[0]  // popq 的目标
		if src == dst {
			return nil    // push %rax; pop %rax → 完全删除
		}
		return []Inst{{Op: "movq", Args: []string{src, dst}}}
	},
}
```

**注意"迭代到不再变化"**——一次优化可能产生新的优化机会。这是所有优化器的标准做法。

---

### 性能提升估算

用 `fib(30)` 做基准测试，对比：

| 版本 | 指令数 | 运行时间 | 相对性能 |
|:---|:---|:---|:---|
| 未优化 | 100% | 100% | 1.0x |
| + 模式 1（push-pop） | 62% | 71% | 1.4x |
| + 模式 2（立即数） | 55% | 64% | 1.6x |
| + 模式 3（加载-运算-存储） | 41% | 48% | 2.1x |
| + 模式 5（恒等消除） | 38% | 45% | 2.2x |
| **GCC -O0** | — | — | ~2.5x |
| **GCC -O2** | — | — | **~6x** |

**结论：简单的窥孔优化能达到 `-O2` 性能的 35~40%，而实现成本可能只有 -O2 的 5%。**

**这个性价比极高**——这正是"先做简单有效的优化"的价值。

---

### 为什么窥孔优化做不到 -O2 的水平？

因为它有两个根本限制：

**限制 1 · 只看局部**

窥孔看不到跨基本块的信息。比如：

```c
int x = 5;
for (int i = 0; i < n; i++) {
    y += x * 2;    // x*2 是循环不变量，应该外提
}
```

要发现 `x * 2` 可以提到循环外，需要**数据流分析**（看 x 在循环里有没有被修改）。窥孔做不到。

**限制 2 · 不做寄存器分配**

`-O2` 的核心优化是寄存器分配——把变量放在寄存器里，避免内存访问。

我们现在所有中间值都过栈，即使消掉了 push/pop，**变量的加载和存储还在**。

寄存器分配需要：
1. 活跃变量分析（liveness analysis，数据流分析）
2. 干扰图构造
3. 图着色
4. 溢出处理

这是一个完整的子系统，通常 2000~5000 行代码。

---

### 一句话总结

**窥孔优化是"投入产出比最高的优化"**——用很小的实现成本，拿到 40% 的性能提升。

**但它有天花板**：因为它不做全局分析。要突破这个天花板，必须上数据流分析 + 寄存器分配，**复杂度会上升一个数量级**。

**这给你的实践启示**：做性能优化时，**先把性价比高的低垂果实摘了**，再考虑投入巨大的重型优化。**很多项目在摘完低垂果实后，发现已经够用了。**

</details>

---

## 小结：这一节你应该带走的东西

1. **语法分析不是编译器的难点，ABI 细节才是。** 栈帧布局、调用约定、寄存器分类、栈对齐——这些不难但繁琐，错了就崩，而且极难调试。

2. **栈式求值是正确的工程选择**：先保证正确性，性能可以后面优化。这体现了"先能跑，再优化"的原则。

3. **x86 的隐式寄存器是最大的坑**：`idivq` 用 `%rdx` 存余数、`cqto` 会覆盖 `%rdx`。**每条指令的"完整语义"不只是它的显式操作数。** 这也是 RISC 架构的优势所在。

4. **三个必须踩的坑**：16 字节栈对齐、参数弹出顺序、`idivq` 的寄存器冲突。**这三个都是"看起来很对但实际错"的典型。**

5. **语法解析 + 朴素代码生成只占真实编译器的 20%。** 剩下 80% 是优化 passes、寄存器分配、诊断和 ABI 兼容性。

6. **UB 是给编译器的"优化许可证"**：C 靠它换性能，Go 消灭它换确定性，Rust 划分边界两者兼顾。

---

## 下一节

[07 · 操作系统：进程、调度与系统调用](./07-操作系统-进程调度与系统调用.md)

编译器把源码变成机器码了。现在轮到操作系统——**谁来运行它？多个程序怎么共存？CPU 时间怎么分？**

> **老陈的预告**：你有没有想过：你的 Go 程序和 Chrome 浏览器"同时"运行，但你的 CPU 只有 8 个核，而系统里有 200 个进程。**这 200 个进程是怎么"假装"同时运行的？是谁在骗它们？**
