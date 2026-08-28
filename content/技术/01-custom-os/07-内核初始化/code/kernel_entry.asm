[BITS 32]
[EXTERN kernel_main]
global kernel_entry

kernel_entry:
    call kernel_main
    jmp $
