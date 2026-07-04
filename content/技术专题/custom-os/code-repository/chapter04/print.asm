; print.asm - 字符串打印函数
;
; 提供:
;   print_string  - 打印以0结尾的字符串
;   print_nl      - 打印换行

; ============================================================
; 打印字符串
; 输入: SI = 字符串地址（以0结尾）
; ============================================================
print_string:
    pusha
    mov ah, 0x0E            ; BIOS teletype功能
.loop:
    lodsb                   ; AL = [SI], SI++
    cmp al, 0
    je .done
    int 0x10
    jmp .loop
.done:
    popa
    ret

; ============================================================
; 打印换行
; ============================================================
print_nl:
    pusha
    mov ah, 0x0E
    mov al, 0x0D            ; 回车
    int 0x10
    mov al, 0x0A            ; 换行
    int 0x10
    popa
    ret
