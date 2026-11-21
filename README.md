# 页间 Parallel

页间是 Windows 10/11 x64 上的论文对照阅读工具。打开论文后，可以并排阅读原文和译文，选中一句话向 AI 提问，或在页旁写下批注，导出给同事回复。

[![最新 Windows 版本](https://img.shields.io/github/v/release/XIA-J-B/ParallelTranslation?label=Windows)](https://github.com/XIA-J-B/ParallelTranslation/releases/latest)

**[下载 Windows 安装包](https://xia-j-b.github.io/ParallelTranslation/#download)** · [最新版本与更新说明](https://github.com/XIA-J-B/ParallelTranslation/releases/latest) · [官网试读](https://xia-j-b.github.io/ParallelTranslation/)

<!-- release-notes:start -->

## 最新版本 · [v0.1.41](https://github.com/XIA-J-B/ParallelTranslation/releases/tag/v0.1.41)

阅读译文时，公式开头的符号、分数和矩阵上下标能保持原来的位置。双栏论文中的公式会和同栏引导句一起排版。遇到无法安全拆分的公式，页间会保留完整原式，供你对照。

表格行名沿用原列的左对齐、居中或右对齐，角度符号和表题中的变量下标也会跟随对应文字。图内标签会先核对完整词边界，避免翻译后留下半个英文词。靠近曲线、边界难以确认的标签会保留原图并标记待核对。

在 Windows 高分屏上，文档库和阅读器现在按窗口所在屏幕的清晰度绘制。你可以继续使用系统的 200% 缩放。把窗口移到缩放比例不同的屏幕时，原文和译文会自动换用相应分辨率，阅读位置保持不变。

升级后直接打开文库里的论文即可。页间会用已保存的译文更新排版，保留手动修改和批注位置，无需重新翻译。

[全部版本记录](https://github.com/XIA-J-B/ParallelTranslation/releases)

<!-- release-notes:end -->

## 安装与更新

首次安装时，从官网下载 x64 安装包并运行。已安装的用户可在「版本与更新」中点击「检查更新」。软件运行时也会每小时检查新版并在后台下载，下载完成后点击「安装并重启」即可升级。本机论文、译文、笔记、设置和阅读记录都会保留。

## 和同事交换论文批注

1. 在原文或译文中选中要讨论的句子，点击「批注」写下问题并保存。之后可以点击页边编号回到这条讨论。
2. 在阅读器右上角点击「导出」，选择原文、译文或双语对照。发 Word 文档时，同事可以在 Word 中回复批注。发 PDF 时，同事可以在 WPS 中回复，也可以在 Zotero 中添加便笺后选择「导出 PDF」。
3. 把同事发回的 PDF 或 DOCX 拖入页间首页。识别到原论文后，选择「合并批注到原论文」，便可在原处查看反馈。遇到无法定位的选区，页间会保留意见和引文，并提示你核对位置。

## 试用与订阅

新账号完成邮箱验证后可免费试用全部会员功能 7 天。同一账号最多授权 4 台设备。翻译和 AI 助读使用你自行配置的模型接口，调用费用由模型服务商另行收取。

| 方案 | 价格 | 开通方式 |
| --- | --- | --- |
| Pro | 10 元 / 30 天 | [购买 Pro 兑换码](https://wzyp.cn/item/l4xdi2)，在软件内开通或续期 |
| MAX 终身版 | 20 元，一次买断 | [购买 MAX 兑换码](https://wzyp.cn/item/yno07i)，在软件内兑换永久权益 |

本仓库提供 Windows 安装包、更新清单和版本记录。开发源码在独立私有仓库维护，软件及第三方组件的许可证和版权声明随安装包提供。
