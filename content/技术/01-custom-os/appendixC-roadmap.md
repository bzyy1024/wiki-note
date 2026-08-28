# 附录C：扩展路线图

完成本教程的15章后，你已经有了一个能运行用户程序的微型操作系统。以下是继续扩展的路线图。

---

## 短期项目（1-2周）

### 1. 简易文件系统

实现一个简单的内存文件系统（ramfs）：

```
目标：
├── 文件创建、读取、写入、删除
├── 目录支持
├── 文件描述符表
└── open/read/write/close 系统调用

关键数据结构：
- superblock（文件系统元信息）
- inode（文件元数据：大小、权限、数据块指针）
- directory entry（文件名 → inode映射）
- 数据块（实际文件内容）

推荐步骤：
1. 在内存中分配固定大小的"磁盘"区域
2. 实现inode分配/释放
3. 实现目录操作（create/lookup/list）
4. 实现文件读写
5. 添加系统调用接口
```

### 2. Shell

```
目标：
├── 命令行解析
├── 内建命令（cd, ls, cat, echo, help, clear）
├── 简单的命令历史
└── 与文件系统集成

推荐实现：
1. 读取键盘输入到行缓冲区
2. 按空格分割命令和参数
3. 查找并执行匹配的命令处理函数
4. 输出结果到屏幕
```

### 3. 堆内存管理

```
替换简单的bump allocator：
├── 实现 malloc/free
├── 空闲链表管理
├── 合并相邻空闲块
├── 分裂大块
└── 对齐支持

推荐算法：
- First Fit（首次适配）：简单易实现
- Best Fit（最佳适配）：减少碎片
- 伙伴系统（Buddy System）：快速合并
```

---

## 中期项目（1-2月）

### 4. 磁盘文件系统

```
实现真正的磁盘文件系统：
├── ATA/IDE磁盘驱动（PIO模式）
├── FAT16或ext2文件系统
├── 磁盘分区表解析
└── 文件系统挂载

ATA PIO步骤：
1. 选择驱动器：outb(0x1F6, 0xE0 | drive | head)
2. 设置参数：扇区数、LBA地址
3. 发送命令：outb(0x1F7, 0x20)（读）
4. 等待就绪：轮询状态寄存器
5. 读取数据：insw(0x1F0, buffer, 256)
```

### 5. 进程间通信（IPC）

```
├── 管道（Pipe）
│   ├── 环形缓冲区
│   ├── 读写端文件描述符
│   └── 阻塞/唤醒机制
├── 共享内存
│   ├── 映射相同物理页到不同进程
│   └── 需要同步机制
├── 信号（Signal）
│   ├── 注册信号处理函数
│   └── SIGTERM, SIGKILL等
└── 消息队列
```

### 6. 网络栈

```
├── 网卡驱动（virtio-net或RTL8139）
├── 以太网帧收发
├── ARP协议
├── IP协议
├── ICMP（ping）
├── UDP
├── TCP（简化版）
└── Socket API

推荐顺序：
1. 网卡驱动 → 能收发原始帧
2. 以太网 + ARP → 能解析MAC地址
3. IP + ICMP → 能ping通
4. UDP → 能发送/接收UDP包
5. TCP → 建立连接、可靠传输
```

---

## 长期项目（3-6月）

### 7. 图形界面

```
├── VGA图形模式（或VESA/VBE）
├── 帧缓冲区管理
├── 基本图形操作（画点/线/矩形/圆）
├── 字体渲染（位图字体）
├── 窗口管理器
│   ├── 窗口创建/销毁/移动/调整大小
│   ├── Z-order管理
│   └── 事件分发
├── 鼠标驱动
└── GUI工具包（按钮/文本框/菜单）

VBE模式设置：
1. 在实模式下调用BIOS INT 0x10
2. AX=0x4F02, BX=模式号（如0x118=1024x768x24bpp）
3. 保存帧缓冲区物理地址
4. 进入保护模式后映射帧缓冲区
```

### 8. 多核支持（SMP）

```
├── ACPI表解析（找到其他CPU核心）
├── AP(Application Processor)启动
│   ├── 发送INIT IPI
│   ├── 发送STARTUP IPI
│   └── AP从实模式启动，进入保护模式
├── APIC（替代PIC）
│   ├── Local APIC配置
│   └── I/O APIC配置
├── 自旋锁（Spinlock）
├── 每CPU数据结构
└── 负载均衡调度器
```

### 9. 64位长模式

```
├── 修改bootloader进入长模式
│   ├── 启用PAE
│   ├── 设置4级页表（PML4→PDPT→PD→PT）
│   ├── 启用IA-32e模式
│   └── 跳转到64位代码
├── 更新所有汇编代码为64位
├── 更新GDT/IDT
├── 更新系统调用（syscall/sysret替代int 0x80）
└── 更新内存管理（48位/57位虚拟地址）
```

### 10. ELF加载器

```
├── 解析ELF头
│   ├── 验证魔数 0x7f 'E' 'L' 'F'
│   ├── 读取程序头表（Program Header Table）
│   └── 识别PT_LOAD段
├── 加载段到内存
│   ├── 分配虚拟内存页
│   ├── 复制段内容
│   └── 设置权限（读/写/执行）
├── 设置用户栈
└── 跳转到入口点（e_entry）
```

---

## 参考资源

### 书籍

| 书籍 | 说明 |
|------|------|
| 《Operating Systems: Three Easy Pieces》 | OS概念经典，免费在线阅读 |
| 《Operating System Concepts》(恐龙书) | 标准教材 |
| 《Modern Operating Systems》(Tanenbaum) | 理论深入 |
| 《Linux内核设计与实现》 | Linux内核入门 |
| 《深入理解Linux内核》 | Linux内核进阶 |
| 《Intel® 64 and IA-32 Architectures SDM》 | x86权威参考 |

### 在线教程

| 资源 | 网址 |
|------|------|
| OSDev Wiki | wiki.osdev.org |
| James Molloy's Tutorial | jamesmolloy.co.uk/tutorial_html |
| Writing a Simple OS from Scratch | nick-blundell.com |
| The Little OS Book | littleosbook.github.io |
| Bran's Kernel Development | osdever.net/bkerndev |
| xv6 (MIT教学OS) | github.com/mit-pdos/xv6-public |
| ToaruOS | github.com/klange/toaruos |

### 开源OS项目（学习参考）

| 项目 | 特点 |
|------|------|
| xv6 | MIT教学OS，简洁清晰 |
| Minix 3 | Tanenbaum设计的微内核 |
| SerenityOS | 现代C++ OS，带完整GUI |
| Redox | Rust编写的微内核OS |
| ToaruOS | 功能丰富的爱好者OS |
