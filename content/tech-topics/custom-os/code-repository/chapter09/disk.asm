[BITS 16]
disk_read:
    pusha
    push dx
    mov ah, 0x02
    mov al, dh
    mov ch, 0x00
    mov cl, 0x02
    mov dh, 0x00
    int 0x13
    jc .disk_error
    pop dx
    cmp al, dh
    jne .sectors_error
    popa
    ret
.disk_error:
    mov si, .msg_err
    call print_string
    jmp $
.sectors_error:
    mov si, .msg_sect_err
    call print_string
    jmp $
.msg_err      db 'Disk read error!', 0x0D, 0x0A, 0
.msg_sect_err db 'Sector count mismatch!', 0x0D, 0x0A, 0
