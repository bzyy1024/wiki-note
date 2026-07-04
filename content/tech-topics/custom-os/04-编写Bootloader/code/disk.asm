; disk.asm - 磁盘读取函数
;
; 提供:
;   disk_read - 从磁盘读取扇区

; ============================================================
; 从磁盘读取扇区
; 输入:
;   DH = 扇区数量
;   DL = 驱动器号
;   BX = 目标内存地址 (ES:BX)
; ============================================================
disk_read:
    pusha
    push dx                 ; 保存DH（期望读取的扇区数）

    mov ah, 0x02            ; BIOS读磁盘功能
    mov al, dh              ; 扇区数量
    mov ch, 0x00            ; 柱面号 = 0
    mov cl, 0x02            ; 扇区号 = 2（扇区1是引导扇区，从2开始读）
    mov dh, 0x00            ; 磁头号 = 0
    ; DL = 驱动器号（已经设置好了）

    int 0x13                ; 调用BIOS磁盘服务
    jc .disk_error          ; 如果进位标志CF=1，说明读取失败

    pop dx                  ; 恢复DH
    cmp al, dh              ; 检查实际读取的扇区数是否等于期望值
    jne .sectors_error

    popa
    ret

.disk_error:
    mov si, .msg_disk_err
    call print_string
    jmp $                   ; 死循环

.sectors_error:
    mov si, .msg_sector_err
    call print_string
    jmp $

.msg_disk_err    db 'Disk read error!', 0x0D, 0x0A, 0
.msg_sector_err  db 'Incorrect number of sectors read!', 0x0D, 0x0A, 0
