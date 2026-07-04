/*
 * user_program.c - 示例用户程序
 *
 * 这个程序运行在Ring 3（用户态），通过系统调用与内核交互。
 * 不能直接调用内核函数或访问端口！
 */

#include "syscall.h"

/* 用户态字符串输出 */
static void print(const char *str) {
    int len = 0;
    while (str[len]) len++;
    syscall(SYS_WRITE, (uint32_t)str, (uint32_t)len, 0);
}

/* 用户态数字输出（简易版） */
static void print_num(int n) {
    char buf[12];
    int i = 0;
    if (n == 0) {
        buf[i++] = '0';
    } else {
        int temp = n;
        while (temp > 0) {
            buf[i++] = '0' + (temp % 10);
            temp /= 10;
        }
    }
    /* 反转 */
    for (int j = 0; j < i / 2; j++) {
        char t = buf[j];
        buf[j] = buf[i - 1 - j];
        buf[i - 1 - j] = t;
    }
    buf[i] = '\0';
    print(buf);
}

/* 用户程序入口 */
void user_main(void) {
    print("Hello from user space! (Ring 3)\n");

    int pid = syscall(SYS_GETPID, 0, 0, 0);
    print("My PID is: ");
    print_num(pid);
    print("\n");

    print("Counting: ");
    for (int i = 1; i <= 5; i++) {
        print_num(i);
        print(" ");
        syscall(SYS_YIELD, 0, 0, 0);  /* 让出CPU */
    }
    print("\n");

    print("User program finished. Calling exit().\n");
    syscall(SYS_EXIT, 0, 0, 0);

    /* 如果exit失败，无限循环 */
    while (1);
}
