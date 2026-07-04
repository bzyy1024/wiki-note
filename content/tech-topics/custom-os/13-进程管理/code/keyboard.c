#include "keyboard.h"
#include "port.h"
#include "screen.h"
#include "idt.h"

/* ============================================================
 * 扫描码到ASCII映射表（Scan Code Set 1）
 * ============================================================ */

/* 普通（无Shift） */
static const char scancode_ascii[] = {
    0,    27,  '1', '2', '3', '4', '5', '6',   /* 0x00 - 0x07 */
    '7', '8', '9', '0', '-', '=', '\b', '\t',  /* 0x08 - 0x0F */
    'q', 'w', 'e', 'r', 't', 'y', 'u', 'i',   /* 0x10 - 0x17 */
    'o', 'p', '[', ']', '\n', 0,   'a', 's',   /* 0x18 - 0x1F */
    'd', 'f', 'g', 'h', 'j', 'k', 'l', ';',   /* 0x20 - 0x27 */
    '\'','`',  0,  '\\','z', 'x', 'c', 'v',   /* 0x28 - 0x2F */
    'b', 'n', 'm', ',', '.', '/', 0,   '*',    /* 0x30 - 0x37 */
    0,   ' ',  0,   0,   0,   0,   0,   0,     /* 0x38 - 0x3F */
    0,    0,   0,   0,   0,   0,   0,   '7',   /* 0x40 - 0x47 */
    '8', '9', '-', '4', '5', '6', '+', '1',    /* 0x48 - 0x4F */
    '2', '3', '0', '.',  0,   0,   0,   0,     /* 0x50 - 0x57 */
};

/* Shift按下时 */
static const char scancode_ascii_shift[] = {
    0,    27,  '!', '@', '#', '$', '%', '^',    /* 0x00 - 0x07 */
    '&', '*', '(', ')', '_', '+', '\b', '\t',  /* 0x08 - 0x0F */
    'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I',   /* 0x10 - 0x17 */
    'O', 'P', '{', '}', '\n', 0,   'A', 'S',   /* 0x18 - 0x1F */
    'D', 'F', 'G', 'H', 'J', 'K', 'L', ':',   /* 0x20 - 0x27 */
    '"', '~',  0,  '|', 'Z', 'X', 'C', 'V',   /* 0x28 - 0x2F */
    'B', 'N', 'M', '<', '>', '?', 0,   '*',    /* 0x30 - 0x37 */
    0,   ' ',  0,   0,   0,   0,   0,   0,     /* 0x38 - 0x3F */
};

/* ============================================================
 * 环形缓冲区
 * ============================================================ */

static char kb_buffer[KB_BUFFER_SIZE];
static volatile uint32_t kb_head = 0;
static volatile uint32_t kb_tail = 0;

static bool buffer_put(char c) {
    uint32_t next = (kb_head + 1) % KB_BUFFER_SIZE;
    if (next == kb_tail) {
        return false; /* 缓冲区满 */
    }
    kb_buffer[kb_head] = c;
    kb_head = next;
    return true;
}

/* ============================================================
 * 修饰键状态
 * ============================================================ */

static bool shift_pressed = false;
static bool ctrl_pressed  = false;
static bool caps_on       = false;

/* ============================================================
 * 键盘中断处理程序
 * ============================================================ */

static void keyboard_handler(registers_t *regs) {
    (void)regs;

    uint8_t scancode = inb(KEYBOARD_DATA_PORT);

    /* === 处理释放事件 (Break Code) === */
    if (scancode & 0x80) {
        uint8_t released = scancode & 0x7F;
        switch (released) {
            case SC_LSHIFT:
            case SC_RSHIFT:
                shift_pressed = false;
                break;
            case SC_LCTRL:
                ctrl_pressed = false;
                break;
        }
        return;
    }

    /* === 处理按下事件 (Make Code) === */

    /* 修饰键 */
    switch (scancode) {
        case SC_LSHIFT:
        case SC_RSHIFT:
            shift_pressed = true;
            return;
        case SC_LCTRL:
            ctrl_pressed = true;
            return;
        case SC_CAPSLOCK:
            caps_on = !caps_on;
            return;
    }

    /* 普通字符转换 */
    char c = 0;
    if (scancode < sizeof(scancode_ascii)) {
        if (shift_pressed) {
            c = scancode_ascii_shift[scancode];
        } else {
            c = scancode_ascii[scancode];
        }
    }

    /* Caps Lock影响字母 */
    if (caps_on && !shift_pressed) {
        if (c >= 'a' && c <= 'z') c -= 32;
    } else if (caps_on && shift_pressed) {
        if (c >= 'A' && c <= 'Z') c += 32;
    }

    /* Ctrl组合键 */
    if (ctrl_pressed && c >= 'a' && c <= 'z') {
        c = c - 'a' + 1;  /* Ctrl+A = 1, Ctrl+C = 3, etc. */
    }

    if (c) {
        buffer_put(c);
        /* 回显到屏幕 */
        if (c == '\n') {
            screen_putchar('\n');
        } else if (c == '\b') {
            /* 退格：回退一格并清除 */
            screen_puts("\b \b");
        } else if (c >= 32) {  /* 可打印字符 */
            screen_putchar(c);
        }
    }
}

/* ============================================================
 * 公共接口
 * ============================================================ */

void keyboard_init(void) {
    /* 注册键盘中断处理程序（IRQ1 → 向量33） */
    register_interrupt_handler(33, keyboard_handler);
    screen_puts("[KB] Keyboard driver initialized\n");
}

char keyboard_getchar(void) {
    if (kb_head == kb_tail) {
        return 0;
    }
    char c = kb_buffer[kb_tail];
    kb_tail = (kb_tail + 1) % KB_BUFFER_SIZE;
    return c;
}

bool keyboard_has_input(void) {
    return kb_head != kb_tail;
}
