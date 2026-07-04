#include "timer.h"
#include "port.h"
#include "screen.h"
#include "idt.h"
#include "scheduler.h"

static volatile uint32_t ticks = 0;
static uint32_t timer_frequency = 0;

static void timer_handler(registers_t *regs) {
    (void)regs;
    ticks++;

    /* 每个tick调用调度器 */
    scheduler_tick();
}

void timer_init(uint32_t frequency) {
    timer_frequency = frequency;
    uint16_t divisor = PIT_BASE_FREQ / frequency;

    /* 命令字节: 通道0, lobyte/hibyte, 方波 */
    outb(PIT_COMMAND, 0x36);

    /* 写分频值 */
    outb(PIT_CHANNEL0, divisor & 0xFF);
    outb(PIT_CHANNEL0, (divisor >> 8) & 0xFF);

    /* 注册中断处理器 (IRQ0 → 向量32) */
    register_interrupt_handler(32, timer_handler);

    screen_printf("[TIMER] PIT initialized at %d Hz\n", frequency);
}

uint32_t timer_get_ticks(void) {
    return ticks;
}

uint32_t timer_get_seconds(void) {
    return timer_frequency ? ticks / timer_frequency : 0;
}
