#include "usermode.h"
#include "screen.h"

void enter_usermode(uint32_t entry, uint32_t user_stack) {
    screen_printf("[USERMODE] Switching to Ring 3 (EIP=0x%x, ESP=0x%x)\n",
                  entry, user_stack);

    __asm__ volatile(
        "cli\n"

        /* 设置用户态数据段 */
        "mov $0x23, %%ax\n"   /* 用户数据段 (GDT[4] | RPL=3) */
        "mov %%ax, %%ds\n"
        "mov %%ax, %%es\n"
        "mov %%ax, %%fs\n"
        "mov %%ax, %%gs\n"

        /* 构造IRET栈帧 */
        "push $0x23\n"         /* SS = 用户数据段 */
        "push %1\n"            /* ESP = 用户栈 */
        "pushf\n"              /* EFLAGS */
        "pop %%eax\n"
        "or $0x200, %%eax\n"   /* 确保开启中断 (IF=1) */
        "push %%eax\n"
        "push $0x1B\n"         /* CS = 用户代码段 (GDT[3] | RPL=3) */
        "push %0\n"            /* EIP = 用户程序入口 */
        "iret\n"               /* 切换到Ring 3! */
        :
        : "r"(entry), "r"(user_stack)
        : "eax"
    );
}
