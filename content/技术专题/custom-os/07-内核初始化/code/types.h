#ifndef TYPES_H
#define TYPES_H

/* 固定宽度无符号整数 */
typedef unsigned char      uint8_t;
typedef unsigned short     uint16_t;
typedef unsigned int       uint32_t;
typedef unsigned long long uint64_t;

/* 固定宽度有符号整数 */
typedef signed char        int8_t;
typedef signed short       int16_t;
typedef signed int         int32_t;
typedef signed long long   int64_t;

/* 大小类型 */
typedef uint32_t size_t;

/* 布尔类型 */
#define true  1
#define false 0
typedef int bool;

/* 空指针 */
#define NULL ((void*)0)

#endif
