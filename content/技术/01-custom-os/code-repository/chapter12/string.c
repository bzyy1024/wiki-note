#include "string.h"

void *memset(void *ptr, int value, size_t size) {
    uint8_t *p = (uint8_t*)ptr;
    for (size_t i = 0; i < size; i++) {
        p[i] = (uint8_t)value;
    }
    return ptr;
}

void *memcpy(void *dest, const void *src, size_t size) {
    uint8_t *d = (uint8_t*)dest;
    const uint8_t *s = (const uint8_t*)src;
    for (size_t i = 0; i < size; i++) {
        d[i] = s[i];
    }
    return dest;
}

size_t strlen(const char *str) {
    size_t len = 0;
    while (str[len] != '\0') {
        len++;
    }
    return len;
}

int strcmp(const char *s1, const char *s2) {
    while (*s1 && (*s1 == *s2)) {
        s1++;
        s2++;
    }
    return *(const unsigned char*)s1 - *(const unsigned char*)s2;
}
