# 第 02 章　第 02 章　Java 17 新特性与 Java 8 差异（现代 Java 长什么样）（已拆分为多篇）

> 原章约 84769 字符，较长。已按主题拆分为以下小节，单篇约 15 分钟可读。

## 本节导航

- [var与record](./01-var与record.md)
- [sealed模式匹配与文本块](./02-sealed模式匹配与文本块.md)
- [Optional与迁移实战](./03-Optional与迁移实战.md)
- [Java8遗产与坑](./04-Java8遗产与坑.md)
- [核心结论与思考题](./05-核心结论与思考题.md)

---

## 原章开头引子

> 你信心满满 `git clone` 了一个号称"现代 Java"的项目，打开第一个文件就看到这个：
>
> ```java
> sealed interface Result permits Ok, Err {}
> record Ok(User user) implements Result {}
> record Err(String reason) implements Result {}
>
> var text = """
>     hello %s
>     """.formatted(user.name());
> ```
>
> 每个单词你都认识，拼出来的意思你看不懂。然后你切到公司内网，看到另一个仓库里全是 `for (int i = 0; i < list.size(); i++)` 和 `SimpleDateFormat`，`pom.xml` 里写着 `<java.version>1.8</java.version>`。
>
> 这两者之间隔的不是语法糖，是一整套编程范式。这一章就是把这道裂缝给你补上 —— 补完之后，你既能读懂新代码，也能说出老代码为什么那么写。

---
