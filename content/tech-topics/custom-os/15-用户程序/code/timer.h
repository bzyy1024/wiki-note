#ifndef TIMER_H
#define TIMER_H

#include "types.h"

/* PIT端口 */
#define PIT_CHANNEL0  0x40
#define PIT_COMMAND   0x43

/* PIT基础频率 */
#define PIT_BASE_FREQ 1193182

/* 默认频率：100Hz（每10ms一次中断） */
#define TIMER_FREQ    100

/* 初始化PIT定时器 */
void timer_init(uint32_t frequency);

/* 获取系统tick数 */
uint32_t timer_get_ticks(void);

/* 获取运行秒数 */
uint32_t timer_get_seconds(void);

#endif
