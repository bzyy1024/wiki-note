FROM ubuntu:22.04

RUN apt update && apt install -y \
    build-essential \
    gcc-multilib \
    nasm \
    qemu-system-x86 \
    gdb \
    mtools \
    vim \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
CMD ["/bin/bash"]
