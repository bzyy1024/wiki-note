#ifndef USERMODE_H
#define USERMODE_H

#include "types.h"

/* 用户态段选择子 */
#define USER_CODE_SELECTOR  0x1B  /* GDT index 3, RPL=3 */
#define USER_DATA_SELECTOR  0x23  /* GDT index 4, RPL=3 */

/* 用户栈大小 */
#define USER_STACK_SIZE     4096
#define USER_STACK_TOP      0x800000  /* 用户栈位置 */

/* 切换到用户模式 */
void enter_usermode(uint32_t entry, uint32_t user_stack);

#endif
