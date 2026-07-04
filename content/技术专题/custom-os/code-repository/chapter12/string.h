#ifndef STRING_H
#define STRING_H

#include "types.h"

void *memset(void *ptr, int value, size_t size);
void *memcpy(void *dest, const void *src, size_t size);
size_t strlen(const char *str);
int strcmp(const char *s1, const char *s2);

#endif
