#include "process.h"
#include "pmm.h"
#include "string.h"
#include "screen.h"

/* ============================================================
 * 全局状态
 * ============================================================ */

static process_t *proc_list  = NULL;  /* 所有进程链表 */
static process_t *current    = NULL;  /* 当前运行的进程 */
static uint32_t next_pid     = 1;

/* ============================================================
 * Idle任务
 * ============================================================ */

static void idle_task(void) {
    while (1) {
        __asm__ volatile("hlt");
    }
}

/* ============================================================
 * 公共接口
 * ============================================================ */

void process_init(void) {
    /* 创建idle进程（代表当前执行流） */
    process_t *idle = (process_t *)kmalloc(sizeof(process_t));
    memset(idle, 0, sizeof(process_t));

    idle->pid = 0;
    memcpy(idle->name, "idle", 5);
    idle->state = PROCESS_RUNNING;
    idle->page_dir = vmm_get_directory();
    idle->priority = 0;
    idle->time_slice = 1;
    idle->next = NULL;

    proc_list = idle;
    current = idle;

    screen_puts("[PROC] Process subsystem initialized\n");
    screen_printf("[PROC] Idle process (PID 0) created\n");
}

process_t *process_create(const char *name, void (*entry)(void)) {
    process_t *proc = (process_t *)kmalloc(sizeof(process_t));
    memset(proc, 0, sizeof(process_t));

    proc->pid = next_pid++;

    /* 复制名称 */
    uint32_t len = strlen(name);
    if (len >= PROCESS_NAME_MAX) len = PROCESS_NAME_MAX - 1;
    memcpy(proc->name, name, len);
    proc->name[len] = '\0';

    proc->state = PROCESS_READY;

    /* 分配内核栈 */
    uint32_t stack_bottom = (uint32_t)kmalloc_aligned(KERNEL_STACK_SIZE);
    proc->kernel_stack = stack_bottom + KERNEL_STACK_SIZE;

    /* 在栈上构造初始上下文 */
    /*
     * 栈布局（从高到低）：
     *   entry_point (EIP - 由ret弹出)
     *   0 (EBP)
     *   0 (EBX)
     *   0 (ESI)
     *   0 (EDI) ← ESP指向这里
     */
    uint32_t *sp = (uint32_t *)proc->kernel_stack;
    *(--sp) = (uint32_t)entry;  /* 返回地址 = 入口函数 */
    *(--sp) = 0;                 /* EBP */
    *(--sp) = 0;                 /* EBX */
    *(--sp) = 0;                 /* ESI */
    *(--sp) = 0;                 /* EDI */
    proc->esp = (uint32_t)sp;

    proc->eip = (uint32_t)entry;
    proc->eflags = 0x202;  /* IF=1 */
    proc->priority = 1;
    proc->time_slice = 10;

    /* 共享内核页目录 */
    proc->page_dir = vmm_get_directory();

    /* 加入进程链表 */
    proc->next = proc_list;
    proc_list = proc;

    screen_printf("[PROC] Created process '%s' (PID %d)\n", proc->name, proc->pid);

    return proc;
}

void process_terminate(process_t *proc) {
    if (!proc || proc->pid == 0) return;  /* 不能杀死idle */

    proc->state = PROCESS_TERMINATED;
    screen_printf("[PROC] Process '%s' (PID %d) terminated\n", proc->name, proc->pid);

    /* 注意：不立即释放内存，等调度器来清理 */
}

process_t *process_current(void) {
    return current;
}

process_t *process_find(uint32_t pid) {
    process_t *p = proc_list;
    while (p) {
        if (p->pid == pid) return p;
        p = p->next;
    }
    return NULL;
}

void process_list_all(void) {
    static const char *state_names[] = {"READY", "RUNNING", "BLOCKED", "TERMINATED"};

    screen_puts("\n--- Process List ---\n");
    screen_printf("%-5s %-16s %-12s %-8s\n", "PID", "Name", "State", "Prio");

    process_t *p = proc_list;
    while (p) {
        screen_printf("%-5d %-16s %-12s %-8d\n",
            p->pid, p->name, state_names[p->state], p->priority);
        p = p->next;
    }
}
