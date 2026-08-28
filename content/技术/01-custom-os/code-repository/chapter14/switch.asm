; switch.asm - 上下文切换
; void switch_context(process_t *prev, process_t *next)
;
; process_t结构中esp的偏移量 = 48字节
; (pid=4 + name=32 + state=4 + esp=4 → offset 44? 实际需要查看结构体)
; 简化：使用固定偏移 (pid:4 + name:32 + state:4 = 40, esp在偏移40处)

%define PROC_ESP_OFFSET 40

global switch_context
switch_context:
    ; 参数: [esp+4] = prev, [esp+8] = next

    ; 保存被调用者保存的寄存器
    push ebp
    push ebx
    push esi
    push edi

    ; 保存当前栈指针到prev->esp
    mov eax, [esp + 20]        ; prev (4 pushes * 4 + ret addr = 20)
    mov [eax + PROC_ESP_OFFSET], esp

    ; 加载next的栈指针
    mov eax, [esp + 24]        ; next
    mov esp, [eax + PROC_ESP_OFFSET]

    ; 恢复寄存器
    pop edi
    pop esi
    pop ebx
    pop ebp

    ret     ; 返回到next进程 (从栈上弹出next的返回地址)
