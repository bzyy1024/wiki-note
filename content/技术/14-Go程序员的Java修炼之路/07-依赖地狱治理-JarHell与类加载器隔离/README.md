# 第 07 章　第 07 章　依赖地狱治理：Jar Hell、ClassLoader 与 Shade（NoSuchMethodError 的三种死法）（已拆分为多篇）

> 原章约 63118 字符，较长。已按主题拆分为以下小节，单篇约 15 分钟可读。

## 本节导航

- [心智模型与诊断工具箱](./01-心智模型与诊断工具箱.md)
- [类加载隔离与FatJar](./02-类加载隔离与FatJar.md)
- [Shade类重定位](./03-Shade类重定位.md)
- [依赖治理与实战](./04-依赖治理与实战.md)
- [核心结论与思考题](./05-核心结论与思考题.md)

---

## 原章开头引子

> 这三行报错，你迟早都会遇到，而且它们长得像一家人：
>
> ```
> java.lang.NoSuchMethodError: com.google.common.base.Preconditions.checkArgument
> java.lang.NoClassDefFoundError: Could not initialize class org.apache.http.conn.ssl.SSLConnectionSocketFactory
> java.lang.ClassNotFoundException: org.slf4j.spi.LocationAwareLogger
> ```
>
> 第一行是"类在，方法没了"；第二行是"类在，但它初始化失败过一次，现在不让你用了"；第三行是"按名字去加载，压根找不到"。**现象相似，根因完全不同，修复动作也完全不同。**
>
> 在 Go 世界里，这三个错误几乎不可能出现 —— 编译期就把符号解析完了，链接器把调用地址直接写进二进制。Java 把这件事推迟到运行时，于是有了这一整章。

---
