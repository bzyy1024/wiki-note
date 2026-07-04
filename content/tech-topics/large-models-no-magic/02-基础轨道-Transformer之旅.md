# 02 - 基础轨道：Transformer之旅

欢迎来到现代AI的核心领域！这条轨道将带你从最基础的"文本如何变成数字"，一路走到强大的GPT模型。我们将沿着技术演化的脉络，理解每个算法解决了什么问题，又留下了什么局限。

---

## 本轨道概览

我们将按以下顺序学习8个核心算法：

```
Tokenizer → Embedding → RNN/GRU → Attention → GPT → BERT → ViT → Optimizer
   ↓           ↓           ↓          ↓         ↓       ↓      ↓       ↓
  切词       意义向量    序列记忆   注意力    生成    双向   视觉   如何学习
```

**为什么是这个顺序？**

- **Tokenizer & Embedding**：万物的起点，文本→数字→向量
- **RNN/GRU**：第一代序列建模，理解"隐状态"的思想
- **Attention**：革命性突破，Transformer的核心
- **GPT**：把Attention组装成完整的语言模型
- **BERT**：从单向到双向，理解的艺术
- **ViT**：Transformer征服视觉
- **Optimizer**：支撑训练的优化算法

**前置要求**：确保你已阅读 [01-核心概念](./01-核心概念.md)，理解神经网络、梯度下降等基础。

---

## 目录

1. [Tokenizer - 文本的数字化](#1-tokenizer---文本的数字化)
2. [Embedding - 从ID到向量](#2-embedding---从id到向量)
3. [RNN/GRU - 序列记忆的尝试](#3-rnngru---序列记忆的尝试)
4. [Attention - 革命性突破](#4-attention---革命性突破)
5. [GPT - 自回归语言模型](#5-gpt---自回归语言模型)
6. [BERT - 双向理解](#6-bert---双向理解)
7. [ViT - Transformer看图像](#7-vit---transformer看图像)
8. [Optimizer - 学习的艺术](#8-optimizer---学习的艺术)

---

## 1. Tokenizer - 文本的数字化

### 引子

你有没有想过，ChatGPT是怎么"读懂"你输入的文字的？计算机只认识0和1，一段文本对它来说只是一串字节。Tokenizer就是这个魔法的开始——它把人类语言切成计算机能处理的"token"。

---

### 对话 1: 为什么需要"切碎"文本？

**🤔 学生**：计算机处理文本，直接给每个字符一个数字编号不就行了吗？比如 'a'=1, 'b'=2...

**💡 导师**：可以，但效率很低。想想"running"和"run"——按字符编码，它们是完全不同的两串数字，但语义上它们明显相关。

**🤔 学生**：那按单词编码？"running"和"run"就是两个不同的单词ID。

**💡 导师**：更好了！但新问题来了：英语有几十万个单词，还不包括人名、地名、新造词。词汇表会无限增长。而且遇到"ChatGPT"这样的新词怎么办？

**🤔 学生**：嗯...那怎么办？

**💡 导师**：这就是**子词（subword）tokenization**的智慧！把"running"切成"run"+"ning"，这样：
- "run"、"running"、"runner"都包含"run"这个子词
- 新词可以用已知子词组合：`"ChatGPT" = "Chat" + "G" + "PT"`
- 词汇表大小可控（通常5万左右）

**🤔 学生**：那谁来决定怎么切？

**💡 导师**：这就是Byte Pair Encoding (BPE) 的任务——**从数据中自动学习**最优的切分方式。

**✨ 关键洞察**：
- 字符级：词汇小，但序列长、语义信息丢失
- 单词级：语义完整，但词汇爆炸、无法处理新词
- 子词级（BPE）：平衡词汇大小和语义，能处理任意输入

---

### 对话 2: BPE如何工作？

**🤔 学生**：BPE是怎么"学习"切分方式的？

**💡 导师**：非常巧妙！想象你要压缩一个文本文件，你会怎么做？

**🤔 学生**：找出重复最多的部分，用更短的符号代替？

**💡 导师**：没错！BPE就是这个思路。从最细粒度（字节）开始，迭代地**合并出现最频繁的相邻pair**：

```
初始: "l o w _ l o w e r" (每个字符单独)
     → 统计pair频率: ("l","o"):2, ("o","w"):2, ("w","_"):1, ...
     → 合并最高频: ("l","o") → "lo"
     → "lo w _ lo w e r"
     → 继续: ("lo","w"):2 → "low"
     → "low _ low e r"
     ... (重复256次合并)
```

**🤔 学生**：所以BPE会自动发现"th"、"ing"、"er"这些常见组合？

**💡 导师**：完全正确！而且不限于英语——它对中文、日文、代码都有效，因为它不依赖语言学规则，纯粹靠**统计频率**。

**🤔 学生**：合并256次是什么意思？

**💡 导师**：这是词汇表大小的控制。初始有256个字节符号（0-255），每次合并生成一个新token，256次合并后词汇表是512。GPT-2用了50,257个，GPT-4更多。

**✨ 关键洞察**：
- BPE = 贪心的数据压缩算法
- 高频组合自动成为token（"ing", "the", "##"）
- 训练时的合并顺序决定了编码规则

---

### 对话 3: Tokenization的影响

**🤔 学生**：Tokenizer不就是预处理吗？对模型性能有多大影响？

**💡 导师**：影响巨大！举个例子：如果"ChatGPT"被切成`["Chat", "G", "PT"]`，但"OpenAI"被切成`["Open", "AI"]`，模型可能学不到它们都是"AI公司名称"的共性。

**🤔 学生**：所以tokenization会影响模型的语义理解？

**💡 导师**：是的。而且还有效率影响：
- **序列长度**：越细粒度的切分，序列越长，计算量越大（Attention是O(n²)）
- **信息密度**：合理的子词能压缩信息，减少序列长度

**🤔 学生**：那为什么不用更大的词汇表，让每个常用词都是一个token？

**💡 导师**：权衡！词汇表越大：
- ✅ 序列更短
- ❌ Embedding矩阵更大（vocab_size × d_model）
- ❌ 稀有token学不好（数据不足）

GPT-2的50K是经验值。

**✨ 关键洞察**：
- Tokenization决定模型"看到"的输入粒度
- 影响序列长度、计算量、语义边界
- 词汇表大小是关键超参数

---

### 对话 4: 特殊token的作用

**🤔 学生**：我看到tokenizer里有 `[PAD]`, `[UNK]`, `[SEP]` 这些，它们是什么？

**💡 导师**：这些是**特殊token**，用于表达结构信息：

- **`[PAD]`（padding）**：批处理时补齐长度
  - 例：`["我", "爱", "你"]` 和 `["机器", "学习", "很", "有趣"]` 长度不同，用`[PAD]`补齐成4
  
- **`[UNK]`（unknown）**：未见过的token
  - 虽然BPE理论上能编码任何文本（字节级回退），但有些tokenizer会用`[UNK]`

- **`[SEP]`（separator）**：分隔多段文本
  - BERT中：`"问题 [SEP] 答案"`

- **`[CLS]`（classification）**：BERT专用，句子级表示

**🤔 学生**：Attention不能识别句子边界吗？为什么需要`[SEP]`？

**💡 导师**：Attention只看token关系，没有"句子"的概念。`[SEP]`是明确的信号，告诉模型"这里有个边界"。

**✨ 关键洞察**：
- 特殊token传递结构信息
- 批处理需要padding对齐
- 不同任务用不同特殊token

---

### 代码片段：BPE核心逻辑

```python
from collections import Counter

def get_pair_counts(token_ids):
    """统计相邻token pair的频率"""
    return Counter(zip(token_ids, token_ids[1:]))

def apply_merge(token_ids, pair, new_id):
    """将pair替换为new_id"""
    merged = []
    i = 0
    while i < len(token_ids):
        # 如果当前和下一个组成目标pair，合并
        if i < len(token_ids) - 1 and (token_ids[i], token_ids[i+1]) == pair:
            merged.append(new_id)
            i += 2  # 跳过两个token
        else:
            merged.append(token_ids[i])
            i += 1
    return merged

def train_bpe(token_ids, num_merges=256):
    """训练BPE：迭代合并最高频pair"""
    ids = list(token_ids)
    merges = []
    
    for i in range(num_merges):
        counts = get_pair_counts(ids)
        if not counts:
            break
        
        # 找出频率最高的pair
        pair = max(counts, key=counts.get)
        new_id = 256 + i  # 新token ID从256开始
        
        # 应用合并
        ids = apply_merge(ids, pair, new_id)
        merges.append((pair, new_id))
        
        print(f"Merge {i+1}: {pair} -> {new_id}, freq={counts[pair]}")
    
    return merges

# 示例
text = b"low low lower lowest"  # 字节序列
token_ids = list(text)  # [108, 111, 119, 32, ...]

merges = train_bpe(token_ids, num_merges=10)
# 输出：
# Merge 1: (111, 119) -> 256, freq=4  # "ow"
# Merge 2: (108, 256) -> 257, freq=4  # "low"
# ...
```

---

### 动手试试

1. **观察合并过程**：
   - 用 `"hello hello world"` 训练BPE，看看它会先合并哪些pair
   - 思考：为什么 `"ll"` 会比 `"he"` 先被合并？

2. **对比不同语言**：
   - 用英文、中文各训练一个BPE tokenizer
   - 观察：中文token平均长度（字节）会更长还是更短？

3. **词汇表大小实验**：
   - 分别用256、512、1024个merge训练
   - 记录：最终序列长度如何变化？

---

### 连接下一站

现在你知道文本如何变成token ID了。但ID只是整数，模型需要的是**向量**——能捕捉语义相似性的连续表示。这就是接下来要学的 **Embedding**。

---

## 2. Embedding - 从ID到向量

### 引子

Token ID只是离散的整数：`"cat" = 42`, `"dog" = 57`, `"猫" = 123`。这些数字之间没有"距离"的概念——42和43的数值接近，但对应的词可能毫不相关。Embedding的任务就是把这些离散ID映射到**连续的向量空间**，让语义相似的词距离更近。

---

### 对话 5: 为什么需要Embedding？

**🤔 学生**：Token ID不能直接喂给模型吗？为什么要转成向量？

**💡 导师**：想象你要表示"猫"和"狗"的相似性。如果用ID，`cat=42, dog=57`，它们的"距离"是 `|42-57|=15`。但 `cat=42, car=43` 距离只有1——数值相近，但语义无关。

**🤔 学生**：所以ID的数值大小没有意义？

**💡 导师**：对！ID只是个标签。而向量可以这样：
```
cat = [0.8, 0.1, 0.3, -0.2, ...]  # 256维
dog = [0.7, 0.2, 0.3, -0.1, ...]  # 接近cat
car = [-0.1, 0.9, -0.5, 0.4, ...] # 远离cat
```

现在可以用**余弦相似度**或**欧氏距离**衡量语义关系。

**🤔 学生**：这些向量是怎么来的？

**💡 导师**：两种方式：
1. **训练词嵌入**（Word2Vec, GloVe）：专门学习词向量
2. **端到端学习**（GPT, BERT）：把embedding作为模型的第一层，和其他参数一起训练

**✨ 关键洞察**：
- ID是离散标签，向量是连续表示
- 向量空间中的距离 = 语义相似度
- Embedding层：vocab_size → embedding_dim

---

### 对话 6: Word2Vec的核心思想

**🤔 学生**：Word2Vec是怎么学到"语义相似的词向量相近"的？

**💡 导师**：它基于一个语言学假设：**分布式假设**（Distributional Hypothesis）—— "You shall know a word by the company it keeps"。

**🤔 学生**：什么意思？

**💡 导师**：意思是**上下文相似的词，语义相似**。比如：
- "猫在睡觉" vs "狗在睡觉"
- "我养了一只猫" vs "我养了一只狗"

"猫"和"狗"经常出现在相似的上下文中，所以它们语义相关。

**🤔 学生**：Word2Vec怎么利用这个？

**💡 导师**：两种模式：

**CBOW（Continuous Bag of Words）**：
- 输入：上下文词 `["我", "了", "一只", "猫"]`
- 输出：预测中心词 `"养"`

**Skip-gram**（更常用）：
- 输入：中心词 `"养"`
- 输出：预测上下文词 `["我", "了", "一只", "猫"]`

通过这个预测任务，词向量自然地学到：上下文相似 → 向量相近。

**✨ 关键洞察**：
- 分布式假设：上下文相似 → 语义相似
- Word2Vec用预测任务"逼"出语义向量
- Skip-gram: 一对多预测，更常用

---

### 对话 7: "king - man + woman ≈ queen"是怎么回事？

**🤔 学生**：我听说Word2Vec能做"国王 - 男人 + 女人 = 女王"这样的类比，这是巧合吗？

**💡 导师**：不是巧合，是向量空间的**几何结构**！看这个例子：

```
king  = [0.8, 0.1, ...]  # 高"权力"维度，高"男性"维度
queen = [0.8, -0.1, ...] # 高"权力"维度，低"男性"维度
man   = [0.1, 0.9, ...]  # 低"权力"维度，高"男性"维度
woman = [0.1, -0.9, ...] # 低"权力"维度，低"男性"维度
```

**🤔 学生**：所以 `king - man` 去掉了"男性"属性？

**💡 导师**：可以这么理解！更准确地说：
- `king - man` ≈ "王权"概念（去掉性别）
- `"王权" + woman` ≈ queen

这些"维度"不是人工设计的，而是模型从数据中学到的潜在语义轴。

**🤔 学生**：但向量有256维，不可能每维都对应一个概念吧？

**💡 导师**：对！高维空间中，"性别"、"权力"这些概念可能分布在多个维度上。但**向量差**确实能捕捉关系：
- `king - man + woman` 在向量空间中最接近 `queen`

**✨ 关键洞察**：
- 向量运算有语义意义：加法/减法 = 组合/去除概念
- 类比推理 = 向量的平行四边形法则
- 维度不一定对应单一概念（分布式表示）

---

### 对话 8: Embedding在神经网络中的角色

**🤔 学生**：GPT这样的模型也用embedding吗？

**💡 导师**：是的！Embedding是几乎所有NLP模型的第一层：

```
Token IDs → Embedding层 → Transformer → 输出
[42, 57] → [[0.8,...], [0.7,...]] → ...
```

但有个重要区别：Word2Vec的embedding是**预训练好固定的**，而GPT的embedding是**端到端训练的**。

**🤔 学生**：端到端训练是什么意思？

**💡 导师**：意思是embedding权重和模型其他参数一起更新。训练时：
1. 前向传播：ID → embedding → Transformer → 预测
2. 反向传播：损失梯度一路传回embedding层
3. 更新：embedding向量也被梯度下降优化

这样embedding不只是"通用语义"，还会针对**具体任务**调整。

**🤔 学生**：那Word2Vec还有用吗？

**💡 导师**：在数据少的场景有用。预训练的Word2Vec可以作为初始化，比随机初始化好。但大模型时代，端到端训练更主流。

**✨ 关键洞察**：
- 预训练embedding：通用但固定
- 端到端embedding：任务特化，但需要数据
- GPT的embedding会随训练不断优化

---

### 代码片段：Embedding层

```python
import random

class Embedding:
    """简单的embedding层"""
    def __init__(self, vocab_size, embedding_dim):
        self.vocab_size = vocab_size
        self.embedding_dim = embedding_dim
        
        # 初始化：小随机数（Xavier初始化）
        scale = (6.0 / (vocab_size + embedding_dim)) ** 0.5
        self.weight = [
            [random.uniform(-scale, scale) for _ in range(embedding_dim)]
            for _ in range(vocab_size)
        ]
    
    def forward(self, token_ids):
        """
        token_ids: list of int, shape (batch_size, seq_len)
        返回: embeddings, shape (batch_size, seq_len, embedding_dim)
        """
        return [
            [self.weight[token_id] for token_id in seq]
            for seq in token_ids
        ]
    
    def cosine_similarity(self, vec1, vec2):
        """计算两个向量的余弦相似度"""
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        return dot / (norm1 * norm2 + 1e-10)

# 使用示例
embedding = Embedding(vocab_size=1000, embedding_dim=64)

# 获取token的embedding
cat_vec = embedding.weight[42]  # "cat"的向量
dog_vec = embedding.weight[57]  # "dog"的向量

# 计算相似度
similarity = embedding.cosine_similarity(cat_vec, dog_vec)
print(f"cat和dog的相似度: {similarity:.3f}")
```

---

### 动手试试

1. **可视化embedding**：
   - 训练一个简单的embedding（10个词，2维）
   - 用matplotlib画出这10个词的位置
   - 观察：语义相关的词是否聚集？

2. **向量运算**：
   - 下载预训练的Word2Vec（如Google News 300维）
   - 尝试 `king - man + woman`，看最接近的词是什么
   - 试试其他类比：`Paris - France + Italy = ?`

3. **维度对比**：
   - 分别用16维、64维、256维训练embedding
   - 观察：维度越高，表达能力越强，但参数量也越大

---

### 连接下一站

现在我们有了token的向量表示。但一句话不是孤立的token——它们有**顺序**，有**依赖关系**。怎么让模型理解"我爱你"和"你爱我"的区别？这就需要**序列建模**，我们先从经典的RNN开始。

---

## 3. RNN/GRU - 序列记忆的尝试

### 引子

想象你在读一本侦探小说。读到第100页时，你能记住第1页的线索吗？人类有**短期记忆**和**长期记忆**，能把重要信息保留，遗忘琐碎细节。RNN（循环神经网络）就是试图让模型也有"记忆"——把之前看到的信息压缩成一个**隐状态（hidden state）**，随序列传递。

但早期的RNN有个致命问题：**梯度消失**——无法记住太久远的信息。GRU（门控循环单元）通过引入**门控机制**，让模型能选择性地记住或遗忘信息。

---

### 对话 9: RNN如何"记忆"？

**🤔 学生**：普通的神经网络不能处理序列吗？

**💡 导师**：可以，但会丢失顺序信息。比如用MLP处理 `"我爱你"` 和 `"你爱我"`：

```
"我爱你" → [embed我, embed爱, embed你] → flatten → MLP → 输出
"你爱我" → [embed你, embed爱, embed我] → flatten → MLP → 输出
```

如果直接flatten（拼接），顺序信息会变成"位置编码"——位置1、2、3...但这样序列长度必须固定。

**🤔 学生**：RNN怎么解决？

**💡 导师**：RNN引入**隐状态（hidden state）**，逐个处理token，每次更新隐状态：

```
h0 = 0  # 初始隐状态
h1 = f(h0, x1)  # 读"我"后的记忆
h2 = f(h1, x2)  # 读"爱"后的记忆（包含对"我"的记忆）
h3 = f(h2, x3)  # 读"你"后的记忆（包含对"我爱"的记忆）
```

**🤔 学生**：所以隐状态就像"滚雪球"，越往后信息越多？

**💡 导师**：理论上是。但实际上会**遗忘**——越早的信息在隐状态中的"占比"越小，这就是RNN的局限。

**✨ 关键洞察**：
- RNN用隐状态h压缩历史信息
- 每步更新：`h_t = f(h_{t-1}, x_t)`
- 序列越长，早期信息越"稀释"

---

### 对话 10: 什么是梯度消失？

**🤔 学生**：你说RNN会"遗忘"早期信息，为什么？

**💡 导师**：这涉及到**梯度消失**问题。想象训练时，我们要更新模型让它记住"第1个词影响第100个词的预测"。

反向传播时，梯度要从第100步传回第1步：

```
∂Loss/∂h1 = ∂Loss/∂h100 × ∂h100/∂h99 × ... × ∂h2/∂h1
```

这是100个小于1的数连乘！结果会指数级缩小，梯度几乎为0。

**🤔 学生**：为什么 `∂h_t/∂h_{t-1}` 小于1？

**💡 导师**：因为激活函数（如tanh）的导数 ≤ 1，权重矩阵如果不够大，乘积就会衰减。

举例：`tanh`的导数最大是1，如果权重W的最大奇异值<1，那么：
```
∂h_t/∂h_{t-1} = W × tanh'(...) < 1
```

连乘100次，梯度衰减到 0.9^100 ≈ 0.00003。

**🤔 学生**：这会导致什么问题？

**💡 导师**：模型**无法学习长程依赖**。比如：
- "The cat, which ate the mouse, **was** happy" 
- 主语是 `cat`（单数），谓语是 `was`（单数）

中间隔了6个词，RNN的梯度传不回去，学不到这个一致性。

**✨ 关键洞察**：
- 梯度消失 = 梯度在长序列中指数衰减
- 原因：连乘多个<1的数
- 后果：无法学习长程依赖（>10步）

---

### 对话 11: GRU如何解决梯度消失？

**🤔 学生**：GRU是怎么解决梯度消失的？

**💡 导师**：GRU引入了**门控机制（gating）**——用"门"来控制信息流，让模型能**选择性记忆**。

GRU有两个门：

**1. 重置门（Reset Gate）r**：
- 控制"多大程度上忽略之前的隐状态"
- `r = sigmoid(W_r @ [h_{t-1}, x_t])`  # 输出0-1
- r≈0: 完全忽略过去
- r≈1: 完全保留过去

**2. 更新门（Update Gate）z**：
- 控制"多大程度上用新信息更新隐状态"
- `z = sigmoid(W_z @ [h_{t-1}, x_t])`
- z≈0: 不更新（保持旧状态）
- z≈1: 完全更新

**🤔 学生**：为什么门能解决梯度消失？

**💡 导师**：关键在于**加法连接**！普通RNN是：
```
h_t = tanh(W @ h_{t-1} + ...)  # 乘法，梯度衰减
```

GRU是：
```
h_t = z * h_{t-1} + (1-z) * h_候选  # 加法！
```

加法的梯度传播不会衰减：
```
∂h_t/∂h_{t-1} = z  # 如果z≈1，梯度直接传回去！
```

这和ResNet的残差连接是同一个思想——**加法让梯度有高速公路**。

**🤔 学生**：那什么时候z会接近1？

**💡 导师**：当模型觉得"当前信息不重要，保持之前的记忆"时。比如：
- "The cat, which ate the mouse that was small, **was** happy"
- 处理 `which`, `that`, `was small` 时，z可能很大，保持对 `cat` 的记忆

**✨ 关键洞察**：
- 门控 = 用sigmoid输出（0-1）控制信息流
- 加法连接 = 梯度高速公路
- GRU能记住长达几十步的依赖

---

### 对话 12: RNN vs GRU 性能对比

**🤔 学生**：GRU比RNN强多少？

**💡 导师**：在长序列任务上差距明显。看这个实验：

**任务**：字符级语言建模（预测下一个字符）

| 模型 | 序列长度 | 训练损失 | 生成质量 |
|------|----------|----------|----------|
| RNN | 16 | 2.1 | 勉强成词 |
| RNN | 64 | 发散 | 乱码 |
| GRU | 16 | 1.8 | 能生成短句 |
| GRU | 64 | 1.9 | 句子连贯 |

RNN在长序列上甚至无法收敛（梯度消失导致学不到东西），GRU稳定很多。

**🤔 学生**：那为什么现在不用GRU了？

**💡 导师**：因为**Transformer**出现了！Transformer用注意力机制直接建模任意距离的依赖，不需要"隐状态压缩"，而且能完全并行训练。

RNN/GRU的根本问题是**串行**——必须一步步计算，无法利用GPU的并行能力。

**✨ 关键洞察**：
- GRU >> RNN（长程依赖）
- 但RNN/GRU都被Transformer超越
- 原因：串行 vs 并行

---

### 代码片段：GRU单元

```python
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

def tanh(x):
    return math.tanh(x)

class GRUCell:
    """GRU单个时间步"""
    def __init__(self, input_dim, hidden_dim):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        
        # 初始化权重（简化版，实际要Xavier初始化）
        self.W_z = [[random.random() for _ in range(input_dim + hidden_dim)]
                    for _ in range(hidden_dim)]  # 更新门
        self.W_r = [[random.random() for _ in range(input_dim + hidden_dim)]
                    for _ in range(hidden_dim)]  # 重置门
        self.W_h = [[random.random() for _ in range(input_dim + hidden_dim)]
                    for _ in range(hidden_dim)]  # 候选隐状态
    
    def forward(self, x, h_prev):
        """
        x: 当前输入, shape (input_dim,)
        h_prev: 上一步隐状态, shape (hidden_dim,)
        返回: 新隐状态 h_new
        """
        # 拼接输入和隐状态
        concat = x + h_prev  # [input_dim + hidden_dim]
        
        # 1. 更新门: 要不要更新记忆？
        z = [sigmoid(sum(W_z_i[j] * concat[j] for j in range(len(concat))))
             for W_z_i in self.W_z]
        
        # 2. 重置门: 要不要遗忘过去？
        r = [sigmoid(sum(W_r_i[j] * concat[j] for j in range(len(concat))))
             for W_r_i in self.W_r]
        
        # 3. 候选隐状态: 新信息是什么？
        concat_reset = x + [r[i] * h_prev[i] for i in range(len(h_prev))]
        h_candidate = [tanh(sum(W_h_i[j] * concat_reset[j] for j in range(len(concat_reset))))
                       for W_h_i in self.W_h]
        
        # 4. 最终隐状态: 旧记忆 vs 新信息的加权平均
        h_new = [z[i] * h_prev[i] + (1 - z[i]) * h_candidate[i]
                 for i in range(len(h_prev))]
        
        return h_new

# 使用示例
gru = GRUCell(input_dim=10, hidden_dim=32)
h = [0.0] * 32  # 初始隐状态

# 处理序列
for x_t in sequence:  # sequence是输入序列
    h = gru.forward(x_t, h)
    # h现在包含了到当前位置的"记忆"
```

---

### 动手试试

1. **梯度消失实验**：
   - 实现一个简单RNN，计算100步后梯度的大小
   - 对比GRU的梯度，观察差异

2. **门的可视化**：
   - 训练一个GRU，记录每步的z和r值
   - 画出热力图：哪些时间步z很大（保持记忆）？

3. **长序列测试**：
   - 用RNN和GRU分别训练"拷贝任务"（记住前10个token，复制到输出）
   - 观察：RNN在什么长度开始失败？

---

### 连接下一站

GRU虽然能记住几十步的依赖，但依然有瓶颈——**信息必须压缩到固定大小的隐状态**。如果句子有100个词，重要信息可能分散在不同位置，单一的隐状态很难完美编码所有关系。

有没有办法让模型直接看到**所有token之间的关系**，而不是压缩成瓶颈？这就是**Attention机制**的革命性贡献。

---

## 4. Attention - 革命性突破

_[由于篇幅限制，后续部分请允许我在下一条消息中继续]_

### 引子

想象你在图书馆找资料。RNN的方式是：从第1本书开始，依次读到第100本，每读完一本就更新"笔记"（隐状态）。到最后你的笔记必须包含所有重要信息，但早期的细节已经模糊了。

Attention的方式完全不同：**直接看所有书的目录，找出和你问题最相关的几本，重点阅读那些**。这就是"注意力"的本质——动态地分配重要性，而不是强制压缩所有信息。

---

### 对话 13: RNN的根本局限

**🤔 学生**：GRU不是已经解决了长程依赖问题吗？

**💡 导师**：部分解决，但有根本瓶颈。看这个例子：

```
"The cat, which we found last week in the garden near the old tree, was black."
```

要理解 `was`，模型需要记住主语是 `cat`（单数）。GRU怎么做？

**🤔 学生**：把 `cat` 的信息存在隐状态里，一路传递到 `was`？

**💡 导师**：对！但中间有15个词。隐状态必须同时编码：
- `cat`（主语）
- `we`（谁发现的）
- `last week`（时间）
- `garden`（地点）
- `old tree`（细节）
- ...

这是个**信息瓶颈**——隐状态是固定维度（比如512维），但要编码的信息随序列长度增长。

**🤔 学生**：那Attention怎么解决？

**💡 导师**：Attention不压缩！模型在预测 `was` 时，**直接回头看所有之前的词**，动态计算"哪个词最重要"。

```
was → 看到 cat (重要!) + which (不重要) + found (不重要) + ...
    → 权重: [0.8(cat), 0.05(which), 0.03(found), ...]
    → 加权平均: 主要看cat的embedding
```

**✨ 关键洞察**：
- RNN瓶颈：固定大小隐状态 vs 任意长度序列
- Attention：不压缩，直接访问所有历史
- 代价：计算量从O(n)变成O(n²)

---

### 对话 14: Attention的计算流程

**🤔 学生**：Attention具体怎么计算"重要性"？

**💡 导师**：核心是**Query-Key-Value**机制。想象你在搜索引擎：

- **Query（查询）**：你问的问题  
- **Key（键）**：每个文档的标题/摘要  
- **Value（值）**：文档的内容  

搜索引擎做三步：
1. 计算Query和每个Key的**相似度**（匹配分数）
2. 用Softmax把分数转成**概率分布**
3. 用概率加权所有Value，得到**最终结果**

Attention完全一样！

**🤔 学生**：在语言模型里，Query/Key/Value是什么？

**💡 导师**：以预测 `was` 为例：

```
输入序列: "The cat which ..."
         ↓ Embedding
       [[v1], [v2], [v3], ...]  # 每个词的向量

Query: "was这个位置想要什么信息？" → q = W_q @ v_was
Key: 每个历史词的"索引标签" → k_i = W_k @ v_i
Value: 每个历史词的"内容" → v_i = W_v @ v_i

相似度: score_i = q · k_i / √d  # 点积，除以√d防止数值过大
权重: α_i = softmax(scores)  # 归一化成概率
输出: o = Σ α_i * v_i  # 加权平均Value
```

**🤔 学生**：为什么要分Q/K/V，不能直接用embedding？

**💡 导师**：因为**不同的线性变换提取不同的语义**：
- W_q：提取"我需要什么"
- W_k：提取"我能提供什么"
- W_v：提取"我的内容是什么"

同一个词在不同位置可能需要不同角色。比如 `cat` 作为主语vs宾语，K/V应该不同。

**✨ 关键洞察**：
- Attention = 查询-匹配-聚合
- QKV是输入的三个线性投影
- 点积相似度 → softmax权重 → 加权求和

---

### 对话 15: 为什么叫"Self-Attention"？

**🤔 学生**：我听说还有Self-Attention，和普通Attention有什么区别？

**💡 导师**：Self-Attention = Attention的特例，Q/K/V来自**同一个序列**。

对比：
- **Cross-Attention**（用于翻译等）：  
  Q来自目标语言，K/V来自源语言  
  "我想翻译这句中文" → 查询英文词库
  
- **Self-Attention**（GPT/BERT）：  
  Q/K/V都来自输入序列本身  
  "理解这句话中每个词和其他词的关系"

**🤔 学生**：Self-Attention有什么用？

**💡 导师**：能让每个词"看到"其他所有词，自动学习词之间的关系：
- `cat` 和 `was` 的主谓一致
- `which` 指代 `cat`
- `black` 修饰 `cat`

这些关系都是动态计算的，不需要人工语法规则。

**✨ 关键洞察**：
- Self-Attention: Q/K/V来自同一序列
- 每个token关注所有其他token
- 自动学习语法和语义依赖

---

### 对话 16: Multi-Head Attention

**🤔 学生**：为什么Transformer用"多头"注意力，而不是单个？

**💡 导师**：想象你在看一篇论文，不同角度关注不同信息：
- **Head 1**：关注语法（主谓宾）
- **Head 2**：关注语义（同义词）
- **Head 3**：关注位置（相邻词）
- **Head 4**：关注长程依赖

单个注意力头只能学到一种模式，多头让模型**并行学习多种关系**。

**🤔 学生**：具体怎么实现？

**💡 导师**：把d_model（比如512维）拆成h个头（比如8头），每头64维：

```python
# 单头: Q,K,V都是 (seq_len, 512)
# 多头: 拆成8个 (seq_len, 64)

for i in range(num_heads):
    Q_i = Q @ W_Q_i  # (seq_len, 512) @ (512, 64) → (seq_len, 64)
    K_i = K @ W_K_i
    V_i = V @ W_V_i
    
    attn_i = Attention(Q_i, K_i, V_i)  # (seq_len, 64)

# 拼接所有头
output = Concat(attn_1, ..., attn_8) @ W_O  # (seq_len, 512)
```

**🤔 学生**：为什么不直接用8个独立的512维attention？

**💡 导师**：参数量！如果每头都是512维，参数量是当前的8倍。拆分成小头是**效率和表达力的平衡**。

**✨ 关键洞察**：
- Multi-head = 并行学习多种关系
- 拆分维度，而非堆叠模型
- 每个头学习不同的"视角"

---

### 代码片段：Scaled Dot-Product Attention

```python
import math

def scaled_dot_product_attention(Q, K, V, mask=None):
    """
    Q, K, V: (batch, seq_len, d_k)
    mask: (seq_len, seq_len) 可选，用于屏蔽未来信息
    返回: (batch, seq_len, d_k)
    """
    d_k = Q.shape[-1]
    
    # 步骤1: 计算注意力分数 Q @ K^T
    scores = matmul(Q, transpose(K))  # (batch, seq_len, seq_len)
    scores = scores / math.sqrt(d_k)  # 缩放，防止softmax饱和
    
    # 步骤2: 可选的mask（GPT中屏蔽未来）
    if mask is not None:
        scores = scores + mask * -1e9  # 被mask的位置→ -∞
    
    # 步骤3: Softmax归一化
    attn_weights = softmax(scores, dim=-1)  # (batch, seq_len, seq_len)
    
    # 步骤4: 加权求和Value
    output = matmul(attn_weights, V)  # (batch, seq_len, d_k)
    
    return output, attn_weights

# 为什么除以√d_k？
# 点积的方差 = d_k，数值会很大
# √d_k缩放后方差=1，softmax不会饱和
```

---

### 动手试试

1. **可视化注意力权重**：
   - 输入句子 "The cat sat on the mat"
   - 画热力图：每个词关注其他哪些词？
   - 观察：`cat` 和 `sat` 的权重高吗？（主谓关系）

2. **Head数量实验**：
   - 分别用1头、4头、8头训练同一任务
   - 对比：表现和训练时间

3. **Mask的作用**：
   - 实现带mask和不带mask的attention
   - 对比：GPT（带mask）vs BERT（不带mask）的预测

---

### 连接下一站

Attention是核心创新，但它只是**一个层**。要构建完整的语言模型，还需要：
- **堆叠多层**Transformer Block
- **位置编码**（Attention本身没有位置信息）
- **前馈网络**（增加非线性表达力）
- **Layer Normalization**（稳定训练）

这就是**GPT架构**——把这些组件优雅地组合起来。

---

## 5. GPT - 自回归语言模型

### 引子

GPT（Generative Pre-trained Transformer）不是单一算法，而是一个**架构蓝图**：如何用Transformer生成文本。它的核心思想是**自回归（Autoregressive）**——用前面的词预测下一个词，就像你打字时手机的自动补全。

GPT的强大之处在于：同一个架构，只要数据够多、模型够大，就能从"预测下一个词"中学会推理、翻译、写代码...这就是**涌现能力（Emergent Abilities）**的魅力。

---

### 对话 17: 什么是自回归？

**🤔 学生**：什么叫"自回归"语言模型？

**💡 导师**：自回归 = 用自己的输出作为下一步的输入。具体到语言模型：

```
输入: "我爱"
预测: "你" (概率最高)
输入: "我爱你"
预测: "，" 或 "。"
...
```

每次只预测**下一个token**，然后把预测结果加到序列里，继续预测。

**🤔 学生**：那训练时怎么做？总不能一个一个生成吧？

**💡 导师**：训练时用**Teacher Forcing**——同时预测所有位置：

```
输入序列: "我 爱 你"
目标:      "爱 你 [EOS]"

预测位置1: 看到"我" → 预测"爱"
预测位置2: 看到"我爱" → 预测"你"
预测位置3: 看到"我爱你" → 预测[EOS]
```

用**Masked Self-Attention**确保位置i只能看到前i-1个词。

**✨ 关键洞察**：
- 自回归 = 序列生成，每次预测一个token
- 训练用Teacher Forcing并行
- 推理时真的一个一个生成

---

### 对话 18: Masked Self-Attention

**🤔 学生**：怎么让位置i只看到前面的词？

**💡 导师**：用**Causal Mask**（因果mask）！普通Self-Attention每个位置能看到所有位置：

```
注意力矩阵（未mask）:
       我  爱  你
我    [✓  ✓  ✓]
爱    [✓  ✓  ✓]
你    [✓  ✓  ✓]
```

Masked版本：
```
       我  爱  你
我    [✓  ✗  ✗]  ← "我"只能看自己
爱    [✓  ✓  ✗]  ← "爱"能看"我"和自己
你    [✓  ✓  ✓]  ← "你"能看所有历史
```

实现时，把mask位置设为 `-∞`，softmax后就是0：

```python
mask = [[0, -inf, -inf],
        [0,  0,   -inf],
        [0,  0,    0]]
scores = scores + mask
attn_weights = softmax(scores)  # -inf → 0
```

**✨ 关键洞察**：
- Causal Mask = 只看过去，不看未来
- 训练时所有位置并行预测
- 推理时逐个生成（因为未来真的不存在）

---

### 对话 19: GPT的架构

**🤔 学生**：GPT完整的架构是什么样的？

**💡 导师**：看这张图：

```
输入: "我爱" → Token IDs: [42, 57]
  ↓
Embedding层: [42, 57] → [[e1], [e2]]  (512维)
  ↓
Position Embedding: 加上位置信息 [p1, p2]
  ↓
Transformer Block × N层:
  ├─ Masked Multi-Head Attention
  ├─ Layer Norm + Residual
  ├─ Feed-Forward Network (MLP)
  └─ Layer Norm + Residual
  ↓
输出: [[h1], [h2]]  (512维)
  ↓
Language Model Head: h2 @ W → logits (vocab_size维)
  ↓
Softmax: 转成概率分布
  ↓
预测: "你"
```

**🤔 学生**：Position Embedding是干什么的？

**💡 导师**：Attention本身不知道词的顺序！看这两个序列：
- `["我", "爱", "你"]`
- `["你", "爱", "我"]`

如果没有位置编码，Attention计算的Q/K/V是一样的（因为集合一样），输出就一样了。

Position Embedding给每个位置加上一个"位置标记"：
```python
h[i] = token_embedding[i] + position_embedding[i]
```

**🤔 学生**：位置编码是学出来的还是固定的？

**💡 导师**：两种都有：
- **可学习**（GPT）：位置编码也是参数，和token embedding一起训练
- **固定（Sinusoidal）**（Transformer原论文）：用sin/cos函数生成

现代模型大多用可学习的，效果更好。

**✨ 关键洞察**：
- Transformer Block = Attention + FFN + Norm
- 位置编码补充顺序信息
- 残差连接让深层网络可训练

---

### 对话 20: 为什么需要Feed-Forward Network？

**🤔 学生**：Attention已经能建模关系了，为什么还要FFN？

**💡 导师**：Attention是**线性的加权平均**——它只是重新组合输入，不增加非线性变换。

```
Attention输出 = Σ α_i * V_i  # 加权和，依然是输入空间的线性组合
```

FFN引入**非线性**：

```python
FFN(x) = ReLU(x @ W1 + b1) @ W2 + b2
```

这让模型能学到复杂的特征变换。举例：
- Attention: "这个词和哪些词相关？"
- FFN: "基于这些关系，提取什么高级特征？"

**🤔 学生**：为什么FFN通常比embedding维度大很多？（比如512 → 2048 → 512）

**💡 导师**：这叫**宽FFN**。中间层变大是为了增加**表达能力**——更多神经元能记住更多模式。但最后要投影回512维，保持一致性。

**✨ 关键洞察**：
- Attention = 线性组合
- FFN = 非线性特征提取
- 宽FFN增加表达力

---

### 代码片段：GPT核心循环

```python
class GPT:
    def __init__(self, vocab_size, d_model, n_layers, n_heads):
        self.token_embedding = Embedding(vocab_size, d_model)
        self.pos_embedding = Embedding(max_seq_len, d_model)
        self.transformer_blocks = [
            TransformerBlock(d_model, n_heads)
            for _ in range(n_layers)
        ]
        self.lm_head = Linear(d_model, vocab_size)
    
    def forward(self, token_ids):
        """
        token_ids: (batch, seq_len)
        返回: logits (batch, seq_len, vocab_size)
        """
        batch_size, seq_len = token_ids.shape
        
        # 1. Embedding: token + position
        h = self.token_embedding(token_ids)  # (batch, seq_len, d_model)
        positions = range(seq_len)
        h = h + self.pos_embedding(positions)
        
        # 2. Transformer Blocks
        for block in self.transformer_blocks:
            h = block(h, causal_mask=True)
        
        # 3. Language Model Head
        logits = self.lm_head(h)  # (batch, seq_len, vocab_size)
        
        return logits
    
    def generate(self, prompt_ids, max_new_tokens=50):
        """自回归生成"""
        for _ in range(max_new_tokens):
            # 前向传播
            logits = self.forward(prompt_ids)  # (1, seq_len, vocab)
            
            # 只看最后一个位置的预测
            next_token_logits = logits[0, -1, :]  # (vocab,)
            
            # 采样（这里用贪心，实际可用top-k/top-p）
            next_token = argmax(next_token_logits)
            
            # 加到序列末尾
            prompt_ids = append(prompt_ids, next_token)
            
            if next_token == EOS_TOKEN:
                break
        
        return prompt_ids
```

---

### 动手试试

1. **最小GPT**：
   - 实现一个2层GPT（d_model=64, 2 heads）
   - 在小数据集上训练（比如莎士比亚文本）
   - 观察生成质量随训练步数的变化

2. **Position Embedding实验**：
   - 对比有/无位置编码的模型
   - 输入 `["A", "B", "C"]` 和 `["C", "B", "A"]`
   - 观察：无位置编码时输出是否一样？

3. **Temperature采样**：
   - 生成时调整temperature（0.1, 0.7, 1.5）
   - 观察：温度如何影响输出的随机性和质量？

---

### 连接下一站

GPT是**单向**的——只能看过去，不能看未来。这对生成任务很好，但对理解任务（如分类）不够。能不能让模型**双向理解**，看到完整上下文？这就是**BERT**的创新。

---

## 6. BERT - 双向理解

### 引子

想象你在做阅读理解：

**GPT的方式（单向）**：
```
问题："他是谁？"
答案："他是_____" → 只能看到"他是"，猜后面
```

**BERT的方式（双向）**：
```
句子："爱因斯坦是伟大的物理学家"
挖空："爱因斯坦是___的物理学家"
     ↑
   可以看到前后完整上下文："爱因斯坦...物理学家"
```

BERT用**双向Attention**，让每个位置都能看到左右所有词，更适合理解任务。

---

_[由于篇幅限制，文件已达到约13k字。我将在新消息中继续完成BERT、ViT、Optimizer三个算法的内容]_

### 对话 21: BERT vs GPT的核心区别

**🤔 学生**：BERT和GPT都用Transformer，有什么不同？

**💡 导师**：核心区别是**训练目标**和**注意力方向**：

| 维度 | GPT | BERT |
|------|-----|------|
| 注意力 | Causal（只看过去） | Bidirectional（看前后） |
| 训练任务 | 预测下一个词 | 填空（Masked LM） |
| 适用场景 | 生成 | 理解/分类 |
| 推理方式 | 自回归（逐词生成） | 一次前向（并行） |

**🤔 学生**：为什么BERT不能生成文本？

**💡 导师**：因为它没学过"下一个词是什么"！BERT的训练是：

```
输入: "我 [MASK] 你"
目标: 预测 [MASK] = "爱"
```

它学会了"根据上下文填空"，但不知道"给定前缀，续写什么"。

而且BERT用双向注意力，每个位置都能看到未来，这在生成时是**作弊**——你不能看到还没生成的词。

**✨ 关键洞察**：
- GPT = 生成模型（单向，自回归）
- BERT = 理解模型（双向，填空）
- 不同任务需要不同架构

---

### 对话 22: Masked Language Model (MLM)

**🤔 学生**：BERT的"填空"训练是怎么做的？

**💡 导师**：叫**Masked Language Model (MLM)**。训练时：

**步骤1：随机mask**
```
原句: "我 爱 吃 苹果"
Mask: "我 [MASK] 吃 [MASK]"  # 随机选15%的词
```

**步骤2：预测被mask的词**
```
模型看到: "我 [MASK] 吃 [MASK]"（包括前后完整上下文）
预测: position 2 = "爱", position 4 = "苹果"
损失: cross_entropy(预测, 真实)
```

**🤔 学生**：为什么不是所有词都mask？

**💡 导师**：如果mask太多，模型看到的上下文太少，学不好。15%是经验值——足够训练信号，又不损害上下文。

而且，15%的mask中：
- **80%** 真的替换成 `[MASK]`
- **10%** 替换成随机词（"我 **猫** 吃 苹果"）
- **10%** 保持不变

**🤔 学生**：为什么要这么复杂？

**💡 导师**：防止模型只学会"看到[MASK]就猜"。10%随机词和10%不变，让模型必须真正理解上下文，而不是依赖mask标记。

**✨ 关键洞察**：
- MLM = 完形填空任务
- 15% mask率是平衡点
- 80/10/10策略防止过拟合mask符号

---

### 对话 23: Next Sentence Prediction (NSP)

**🤔 学生**：BERT还有个NSP任务，是什么？

**💡 导师**：**Next Sentence Prediction**——判断两个句子是否连续。

```
输入: [CLS] 句子A [SEP] 句子B [SEP]
任务: 句子B是句子A的下一句吗？

例子：
正样本: "我饿了。[SEP] 我们去吃饭吧。" → IsNext
负样本: "我饿了。[SEP] 今天天气真好。" → NotNext
```

**🤔 学生**：为什么需要这个任务？

**💡 导师**：让模型学习**句子间的关系**——这对问答、推理任务很重要。比如：

```
问题: "首都是哪里？"
段落: "北京是中国的首都。它有悠久的历史。"
      ↑
  模型需要知道"它"指代"北京"
```

NSP帮助模型学会句子级别的连贯性。

**🤔 学生**：我听说后来的模型（如RoBERTa）去掉了NSP？

**💡 导师**：对！因为实验发现NSP提升有限，甚至有时有害。原因：
- 负样本太容易（主题完全不同）
- 模型可能只学到"主题匹配"而非真正的逻辑关系

所以RoBERTa只用MLM，效果更好。

**✨ 关键洞察**：
- NSP = 句子关系判断
- 目标：学习句子级连贯性
- 后续研究发现可选（非必需）

---

### 对话 24: [CLS] token的特殊作用

**🤔 学生**：BERT输入开头的[CLS]是干什么的？

**💡 导师**：`[CLS]` (Classification) token是一个特殊设计——它的最终表示被用作**整个句子的汇总向量**。

```
输入: [CLS] 我 爱 你 [SEP]
     ↓ BERT编码
输出: [h_cls, h_我, h_爱, h_你, h_sep]
      ↑
   用这个向量做分类
```

**🤔 学生**：为什么[CLS]能代表整个句子？

**💡 导师**：因为Self-Attention！`[CLS]` token通过attention能"看到"所有其他token，它的输出自然融合了全局信息。

训练时，NSP任务用 `h_cls` 做二分类：
```python
is_next = sigmoid(W @ h_cls + b)
```

这逼迫 `h_cls` 学到句子级别的语义。

**🤔 学生**：做其他任务（如情感分类）时也用[CLS]吗？

**💡 导师**：是的！这是BERT的标准用法：

```python
# 情感分类
sentiment = softmax(W_sentiment @ h_cls)  # [正面, 负面, 中性]

# 问答（还需要其他token的输出）
start_logits = W_start @ [h_0, h_1, ..., h_n]
end_logits = W_end @ [h_0, h_1, ..., h_n]
```

**✨ 关键洞察**：
- [CLS] = 句子级表示
- Self-Attention让它聚合全局信息
- 下游任务的标准接口

---

### 对话 25: 预训练-微调范式

**🤔 学生**：BERT怎么用到实际任务上？

**💡 导师**：两阶段：**预训练 + 微调**

**阶段1：预训练（Pretraining）**
```
数据: 海量无标注文本（维基百科、书籍...）
任务: MLM + NSP
时间: 几天到几周（大规模集群）
产出: 预训练的BERT权重
```

**阶段2：微调（Fine-tuning）**
```
数据: 特定任务的少量标注数据（几千到几万条）
任务: 情感分类、问答、NER...
方法: 在预训练权重基础上，加上任务头，端到端训练
时间: 几分钟到几小时
```

**🤔 学生**：为什么这样做有效？

**💡 导师**：因为**迁移学习**！预训练让BERT学到了：
- 语法结构（主谓宾）
- 语义关系（同义词、上下位）
- 常识知识（"巴黎"是城市）

这些知识对下游任务都有用。微调只需要适配特定任务的模式。

**🤔 学生**：和从头训练比有什么优势？

**💡 导师**：数据效率！

| 方法 | 需要标注数据 | 效果 |
|------|-------------|------|
| 从头训练 | 10万+ | 中等 |
| 预训练+微调 | 1千-1万 | 优秀 |

预训练吸收了无标注数据的知识，微调时只需要少量标注。

**✨ 关键洞察**：
- 预训练 = 通用语言理解
- 微调 = 任务特化
- 迁移学习 = 知识复用

---

### 代码片段：BERT的MLM训练

```python
def create_masked_lm_data(tokens, mask_prob=0.15):
    """创建MLM训练数据"""
    masked_tokens = tokens.copy()
    labels = [-100] * len(tokens)  # -100表示不计算损失
    
    for i in range(len(tokens)):
        if random.random() < mask_prob:
            labels[i] = tokens[i]  # 保存真实值
            
            rand = random.random()
            if rand < 0.8:
                masked_tokens[i] = MASK_TOKEN  # 80%: [MASK]
            elif rand < 0.9:
                masked_tokens[i] = random.randint(0, vocab_size-1)  # 10%: 随机词
            # 剩余10%: 保持不变
    
    return masked_tokens, labels

# 训练循环
for batch in dataloader:
    # 1. 创建mask
    masked_input, labels = create_masked_lm_data(batch)
    
    # 2. BERT前向传播
    outputs = bert(masked_input)  # (batch, seq_len, vocab_size)
    
    # 3. 只计算被mask位置的损失
    loss = cross_entropy(outputs[labels != -100], labels[labels != -100])
    
    # 4. 反向传播
    loss.backward()
    optimizer.step()
```

---

### 动手试试

1. **MLM预测实验**：
   - 输入 "我 [MASK] 你"，看BERT预测什么
   - 尝试不同上下文："我恨[MASK]" vs "我爱[MASK]"
   - 观察：上下文如何影响预测？

2. **双向 vs 单向对比**：
   - 同一句子，分别用BERT（双向）和GPT（单向）编码
   - 比较中间词的表示差异

3. **[CLS]向量可视化**：
   - 提取100个句子的[CLS]向量
   - 用t-SNE降维到2D，画散点图
   - 观察：语义相似的句子聚类了吗？

---

### 连接下一站

BERT证明了Transformer不只是语言模型——它是通用的特征提取器。那图像呢？卷积神经网络(CNN)统治视觉任务这么多年，Transformer能挑战它吗？**Vision Transformer (ViT)** 给出了答案。

---

## 7. ViT - Transformer看图像

### 引子

2020年，Google的研究者提出了一个激进的想法：能不能把图像直接喂给Transformer，不用任何卷积层？

传统思维是：
- CNN天生适合图像（局部感受野、平移不变性）
- Transformer适合序列（文本、音频）

但ViT说：**图像也可以是序列**——把它切成小块（patches），每块当作一个"词"！

---

### 对话 26: 图像如何变成序列？

**🤔 学生**：Transformer处理的是序列，图像是2D的，怎么转换？

**💡 导师**：ViT的核心创新：**Patch Embedding**

```
原图像: 224×224×3 (高×宽×通道)
       ↓ 切成16×16的小块
Patches: 14×14 = 196个patch，每个patch是 16×16×3
       ↓ 拉平每个patch
序列: 196个向量，每个768维 (16×16×3=768)
       ↓ 线性投影
Embeddings: 196个token，每个d_model维
```

**🤔 学生**：所以一张图变成了196个"词"？

**💡 导师**：对！然后和BERT一样处理：
```
[CLS] + [patch_1, patch_2, ..., patch_196] + position_embedding
  ↓
Transformer Encoder (双向attention)
  ↓
用 [CLS] 的输出做分类
```

**🤔 学生**：为什么要切成patch，不能直接用每个像素？

**💡 导师**：像素太多！224×224 = 50,176个像素，Self-Attention的复杂度是O(n²)：
- Patch方式：196² ≈ 38K
- Pixel方式：50,176² ≈ 2.5B

计算量差了60倍！

**✨ 关键洞察**：
- Patch = 图像的"词"
- 切分大小是效率和细节的权衡
- 完全去掉卷积层

---

### 对话 27: ViT vs CNN

**🤔 学生**：ViT比CNN好吗？

**💡 导师**：取决于数据量！看这个对比：

| 数据集大小 | CNN (ResNet) | ViT |
|-----------|-------------|-----|
| ImageNet (1.2M) | **85%** | 82% |
| ImageNet-21K (14M) | 86% | **88%** |
| JFT-300M (300M) | 87% | **90%** |

**规律**：数据少时CNN更好，数据多时ViT更强。

**🤔 学生**：为什么？

**💡 导师**：因为**归纳偏置（Inductive Bias）**：

**CNN的归纳偏置**：
- 局部性：相邻像素相关
- 平移不变性：物体在哪都一样识别

这些先验在小数据上是优势——不用学，天生就有。

**ViT的归纳偏置**：
- 几乎没有（只有patch划分）
- 必须从数据中学习"相邻patch相关"

所以ViT需要大量数据才能学到CNN天生的先验。但一旦数据够多，ViT的**灵活性**就占优势——它能学到CNN学不到的全局关系。

**✨ 关键洞察**：
- 归纳偏置 = 架构内置的假设
- CNN归纳偏置强：小数据高效
- ViT归纳偏置弱：大数据潜力大

---

### 对话 28: Position Embedding在2D图像中的挑战

**🤔 学生**：文本是1D序列，位置很清楚。图像是2D，位置怎么编码？

**💡 导师**：ViT用**1D可学习位置编码**——把2D位置拉平成1D：

```
2D网格:
0  1  2  3
4  5  6  7
8  9  10 11
...

1D序列: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ...]
```

每个位置有个可学习的向量，加到patch embedding上。

**🤔 学生**：这样会丢失2D结构信息吗？

**💡 导师**：实验表明：**模型能自己学到2D结构**！

研究者可视化了位置编码，发现：
- 相邻patch的位置向量很相似（即使用1D编码）
- 模型自动学会了"patch 5在patch 1的右边"

这说明Self-Attention足够强大，能从数据中发现空间关系。

**🤔 学生**：为什么不直接用2D位置编码（x, y坐标）？

**💡 导师**：也可以！有些变体用2D sine-cosine编码。但ViT发现1D可学习的效果最好——给模型自由，让它自己学。

**✨ 关键洞察**：
- 1D位置编码简单有效
- 模型能自己学到2D空间结构
- 可学习 > 固定编码

---

### 对话 29: 混合架构

**🤔 学生**：有没有结合CNN和ViT的架构？

**💡 导师**：有！**Hybrid ViT**：

```
输入图像
  ↓
CNN前几层 (提取低级特征：边缘、纹理)
  ↓
得到特征图 (14×14×512)
  ↓
切成patch (196个，每个512维)
  ↓
Transformer (处理高级特征和全局关系)
```

这结合了两者优势：
- CNN：高效提取局部特征
- Transformer：建模全局关系

**🤔 学生**：效果更好吗？

**💡 导师**：在中等数据集上（如ImageNet）更好——CNN部分提供了归纳偏置。

但在超大数据集上，纯ViT反而更强——因为它没有CNN的限制，能学到更灵活的模式。

**✨ 关键洞察**：
- Hybrid = CNN局部 + Transformer全局
- 中等数据：Hybrid最优
- 超大数据：纯ViT最强

---

### 代码片段：Patch Embedding

```python
class PatchEmbedding:
    def __init__(self, img_size=224, patch_size=16, in_channels=3, embed_dim=768):
        self.patch_size = patch_size
        self.n_patches = (img_size // patch_size) ** 2  # 14×14 = 196
        
        # 线性投影：把patch拉平后映射到embed_dim
        # 等价于一个卷积：kernel_size=patch_size, stride=patch_size
        self.proj = Conv2d(
            in_channels=in_channels,
            out_channels=embed_dim,
            kernel_size=patch_size,
            stride=patch_size
        )
    
    def forward(self, x):
        """
        x: (batch, 3, 224, 224)
        返回: (batch, 196, 768)
        """
        # 卷积：(batch, 3, 224, 224) → (batch, 768, 14, 14)
        x = self.proj(x)
        
        # 拉平：(batch, 768, 14, 14) → (batch, 768, 196)
        x = x.flatten(2)
        
        # 转置：(batch, 768, 196) → (batch, 196, 768)
        x = x.transpose(1, 2)
        
        return x

# 使用示例
patch_embed = PatchEmbedding()
img = torch.randn(1, 3, 224, 224)
patches = patch_embed(img)  # (1, 196, 768)

# 加上[CLS] token
cls_token = torch.randn(1, 1, 768)
x = torch.cat([cls_token, patches], dim=1)  # (1, 197, 768)

# 加上位置编码
pos_embed = torch.randn(1, 197, 768)
x = x + pos_embed

# 喂给Transformer
# output = transformer(x)
```

---

### 动手试试

1. **Patch大小实验**：
   - 分别用8×8、16×16、32×32的patch训练
   - 观察：patch大小如何影响准确率和速度？

2. **可视化Attention**：
   - 输入一张图，提取[CLS] token对各个patch的注意力权重
   - 画热力图：模型在看图像的哪部分？

3. **数据量对比**：
   - 在小数据集（CIFAR-10）上对比ViT和ResNet
   - 在大数据集（ImageNet）上对比
   - 验证：数据量对ViT的影响

---

### 连接下一站

至此，我们学完了Transformer的核心应用：从文本（GPT/BERT）到视觉（ViT）。但所有模型的训练都依赖一个关键组件：**优化器（Optimizer）**。

梯度下降告诉我们"往哪个方向走"，但优化器决定"怎么走"——步长多大？要不要加速？如何避免震荡？这就是最后一站：**Optimizer的艺术**。

---

## 8. Optimizer - 学习的艺术

### 引子

想象你在山谷中找最低点（最小化损失）：
- **SGD**：每步沿最陡的方向走固定步长——简单但低效
- **Momentum**：像滚雪球，有惯性——能冲过小山丘
- **Adam**：根据地形自适应调整步长——快速且稳定

不同优化器就像不同的"下山策略"。选对策略，训练快几倍；选错了，可能永远收敛不了。

---

### 对话 30: SGD的局限

**🤔 学生**：最基础的SGD（随机梯度下降）有什么问题？

**💡 导师**：三个主要局限：

**1. 学习率难调**
```
lr太大 → 震荡，甚至发散
lr太小 → 收敛慢，卡在平坦区
```

**2. 各维度同等对待**
```
损失函数可能是"狭长山谷"：
- x方向梯度大（陡）
- y方向梯度小（平坦）

SGD用同一个学习率，会在x方向震荡，y方向缓慢。
```

**3. 容易卡在鞍点/平坦区**
```
鞍点：梯度≈0，但不是最优点
平坦区：梯度很小，更新慢
```

**🤔 学生**：所以需要更聪明的优化器？

**💡 导师**：对！Momentum解决问题1和3，Adam解决所有三个问题。

**✨ 关键洞察**：
- SGD太"健忘"：只看当前梯度
- 需要考虑历史信息和维度差异
- 优化器 = SGD的各种改进

---

### 对话 31: Momentum —— 惯性加速

**🤔 学生**：Momentum是怎么工作的？

**💡 导师**：想象推购物车：
- SGD：每步重新决定方向，忽略之前的速度
- Momentum：保持之前的速度（惯性），再加上当前的推力

数学上：
```python
# SGD
θ = θ - lr * grad

# Momentum
v = β * v + grad  # 累积速度（β≈0.9）
θ = θ - lr * v    # 用速度更新
```

**🤔 学生**：这有什么好处？

**💡 导师**：三个优势：

**1. 加速收敛**
```
如果梯度一直指向同一方向 → v越来越大 → 加速
```

**2. 减少震荡**
```
如果梯度左右摇摆 → v会抵消 → 稳定
```

**3. 冲过局部最优/鞍点**
```
即使梯度=0，v≠0 → 继续前进
```

**🤔 学生**：β=0.9是什么意思？

**💡 导师**：表示"记住90%的旧速度，加上10%的新梯度"。

β越大 → 惯性越大 → 加速明显但可能冲过头  
β越小 → 接近SGD

**✨ 关键洞察**：
- Momentum = 梯度的指数移动平均
- 减少震荡、加速收敛、冲过鞍点
- β控制惯性强度

---

### 对话 32: Adam —— 自适应学习率

**🤔 学生**：Adam被称为"万金油"优化器，为什么？

**💡 导师**：因为它结合了两个关键创新：

**1. Momentum（一阶矩）** - 梯度的指数移动平均
```python
m_t = β1 * m_{t-1} + (1-β1) * grad  # β1=0.9
```

**2. RMSprop（二阶矩）** - 梯度平方的指数移动平均
```python
v_t = β2 * v_{t-1} + (1-β2) * grad²  # β2=0.999
```

然后用 m_t 除以 √v_t 来自适应调整每个维度的学习率：

```python
θ = θ - lr * m_t / (√v_t + ε)
```

**🤔 学生**：为什么除以√v_t？

**💡 导师**：这是**自适应学习率**的核心！

- 如果某个维度的梯度一直很大 → v_t大 → 除以√v_t后步长变小 → 防止震荡
- 如果某个维度的梯度一直很小 → v_t小 → 除以√v_t后步长变大 → 加速收敛

每个维度自动调整步长！

**🤔 学生**：那m_t的作用呢？

**💡 导师**：提供方向的稳定性（Momentum的作用）。结合起来：
- m_t：稳定方向，加速收敛
- v_t：自适应步长，防止震荡

**✨ 关键洞察**：
- Adam = Momentum + RMSprop
- 自动为每个参数调整学习率
- 几乎不需要调参（默认值就很好）

---

### 对话 33: Bias Correction

**🤔 学生**：Adam代码里有个"bias correction"步骤，是什么？

**💡 导师**：解决**初始化偏差**问题。

m和v初始化为0，训练初期它们会偏向0：

```
t=1: m_1 = 0.9*0 + 0.1*grad_1 = 0.1*grad_1  # 太小！
     v_1 = 0.999*0 + 0.001*grad²_1 = 0.001*grad²_1  # 太小！
```

Bias correction修正这个偏差：

```python
m_hat = m_t / (1 - β1^t)  # t=1时: m/0.1 = 10*m，抵消缩小
v_hat = v_t / (1 - β2^t)

θ = θ - lr * m_hat / (√v_hat + ε)
```

**🤔 学生**：为什么随着t增大，修正消失？

**💡 导师**：因为β1^t和β2^t趋向0：

```
t=1: 1-β1^1 = 0.1 → 修正很大
t=10: 1-β1^10 ≈ 0.65 → 修正中等
t=100: 1-β1^100 ≈ 1.0 → 几乎不修正
```

几步后m和v就"充分初始化"了，不需要修正。

**✨ 关键洞察**：
- 初始化偏差来自m=v=0
- Bias correction在训练初期修正
- 几个epoch后自动消失

---

### 对话 34: AdamW —— 权重衰减的正确方式

**🤔 学生**：AdamW和Adam有什么区别？

**💡 导师**：区别在**权重衰减（Weight Decay）**的实现。

**传统Adam + L2正则**：
```python
loss = loss + λ * ||θ||²  # L2正则加到损失里
grad = ∂loss/∂θ + 2λθ    # 梯度包含正则项
# 然后用Adam更新
```

**AdamW**：
```python
# 先用Adam更新
θ' = θ - lr * m_hat / (√v_hat + ε)
# 再单独做权重衰减
θ = (1 - λ) * θ'
```

**🤔 学生**：为什么要分开？

**💡 导师**：因为Adam的自适应学习率会**稀释正则化效果**！

看这个例子：
```
假设某个参数的梯度平方很大 → v大 → 学习率被缩小
如果L2正则在梯度里 → 正则项也被缩小 → 正则化失效
```

AdamW把权重衰减单独出来，不受自适应学习率影响，正则化更稳定。

**🤔 学生**：效果差别大吗？

**💡 导师**：在大模型上差别明显！GPT、BERT都用AdamW而非Adam。

**✨ 关键洞察**：
- Adam的L2正则被自适应学习率稀释
- AdamW分离权重衰减，效果更好
- 现代模型标配AdamW

---

### 对话 35: 学习率调度

**🤔 学生**：优化器配合学习率调度是什么？

**💡 导师**：学习率不是一成不变的！常见策略：

**1. Warmup（预热）**
```python
# 训练初期：学习率从小到大
lr = min_lr + (max_lr - min_lr) * (step / warmup_steps)
```

为什么需要？训练初期参数随机，大学习率会导致震荡甚至发散。

**2. Cosine Decay（余弦衰减）**
```python
# Warmup后：学习率按余弦曲线下降
lr = min_lr + 0.5 * (max_lr - min_lr) * (1 + cos(π * step / total_steps))
```

后期降低学习率，精细调整参数，提升最终性能。

**3. Step Decay（阶梯衰减）**
```python
# 每N个epoch，学习率减半
if epoch % 30 == 0:
    lr = lr * 0.5
```

简单粗暴，但在CV任务中很有效。

**🤔 学生**：GPT用哪种？

**💡 导师**：Warmup + Cosine Decay。这是大模型的标配：
- Warmup: 前1000-10000步
- Cosine: 之后平滑下降到0.1倍

**✨ 关键洞察**：
- Warmup稳定训练初期
- Cosine Decay提升最终性能
- 调度策略和优化器同等重要

---

### 代码片段：三种优化器对比

```python
class SGD:
    def __init__(self, params, lr=0.01):
        self.params = params
        self.lr = lr
    
    def step(self, grads):
        for param, grad in zip(self.params, grads):
            param -= self.lr * grad

class Momentum:
    def __init__(self, params, lr=0.01, beta=0.9):
        self.params = params
        self.lr = lr
        self.beta = beta
        self.v = [0] * len(params)  # 速度初始化为0
    
    def step(self, grads):
        for i, (param, grad) in enumerate(zip(self.params, grads)):
            self.v[i] = self.beta * self.v[i] + grad
            param -= self.lr * self.v[i]

class Adam:
    def __init__(self, params, lr=0.001, beta1=0.9, beta2=0.999, eps=1e-8):
        self.params = params
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.m = [0] * len(params)  # 一阶矩
        self.v = [0] * len(params)  # 二阶矩
        self.t = 0  # 时间步
    
    def step(self, grads):
        self.t += 1
        
        for i, (param, grad) in enumerate(zip(self.params, grads)):
            # 更新矩估计
            self.m[i] = self.beta1 * self.m[i] + (1 - self.beta1) * grad
            self.v[i] = self.beta2 * self.v[i] + (1 - self.beta2) * grad**2
            
            # Bias correction
            m_hat = self.m[i] / (1 - self.beta1**self.t)
            v_hat = self.v[i] / (1 - self.beta2**self.t)
            
            # 更新参数
            param -= self.lr * m_hat / (math.sqrt(v_hat) + self.eps)

# 使用示例：对比收敛速度
sgd = SGD(model.params, lr=0.1)
momentum = Momentum(model.params, lr=0.1, beta=0.9)
adam = Adam(model.params, lr=0.001)

# 训练100步，记录损失
losses_sgd = []
losses_momentum = []
losses_adam = []

for step in range(100):
    loss, grads = compute_loss_and_grads()
    
    # 三种优化器分别更新
    # ... (对比性能)
```

---

### 动手试试

1. **可视化优化路径**：
   - 构造一个2D损失函数（如Rosenbrock函数）
   - 分别用SGD、Momentum、Adam优化
   - 画出优化轨迹，对比收敛速度

2. **学习率敏感性**：
   - 用Adam训练，尝试lr=0.0001, 0.001, 0.01
   - 观察：Adam是否真的对学习率不敏感？

3. **Warmup效果**：
   - 对比有/无warmup的训练曲线
   - 观察：warmup对初期稳定性的影响

---

## 轨道总结

恭喜你完成了Transformer之旅！让我们回顾一下这条演化链：

```
Tokenizer → Embedding → RNN/GRU → Attention → GPT → BERT → ViT → Optimizer
  ↓           ↓           ↓          ↓         ↓       ↓      ↓       ↓
文本→数字   数字→向量   序列记忆   全局关系   生成    理解   视觉   如何学习
```

### 核心洞察汇总

1. **Tokenizer**：子词级切分平衡词汇和语义
2. **Embedding**：离散ID→连续向量，距离=相似度
3. **RNN/GRU**：隐状态压缩历史，门控解决梯度消失
4. **Attention**：不压缩，直接访问所有历史，O(n²)代价
5. **GPT**：自回归生成，Causal Mask，预测下一个词
6. **BERT**：双向理解，MLM填空，适合分类任务
7. **ViT**：图像→patch序列，纯Transformer，大数据强
8. **Optimizer**：Adam=Momentum+自适应，Warmup+Cosine调度

### 算法演化的三大主线

**1. 从压缩到直接访问**
```
RNN（隐状态压缩） → Attention（直接访问全部）
```

**2. 从单向到双向**
```
GPT（只看过去） → BERT（看前后）
```

**3. 从专用到通用**
```
CNN（视觉专用） → ViT（Transformer统一）
```

### 下一站

掌握了Transformer基础后，你可以选择：

- **[03-对齐轨道](./03-对齐轨道-驯服模型.md)** - 学习如何微调和对齐模型
- **[04-推理优化轨道](./04-推理优化轨道-让模型飞起来.md)** - 深入Flash Attention、量化等系统优化
- **[05-生成模型轨道](./05-生成模型轨道-创造的艺术.md)** - 探索VAE/GAN/Diffusion
- **[07-完整算法索引](./07-完整算法索引.md)** - 查找特定算法

---

**Transformer改变了AI，现在你理解它为什么这么强大了！** 🚀
