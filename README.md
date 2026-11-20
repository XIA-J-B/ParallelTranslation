# 页间 Parallel

页间是 Windows 10/11 x64 上的论文对照阅读工具。打开论文后，可以并排阅读原文和译文，选中一句话向 AI 提问，或在页旁写下批注，导出给同事回复。

[![最新 Windows 版本](https://img.shields.io/github/v/release/XIA-J-B/ParallelTranslation?label=Windows)](https://github.com/XIA-J-B/ParallelTranslation/releases/latest)

**[下载 Windows 安装包](https://xia-j-b.github.io/ParallelTranslation/#download)** · [最新版本与更新说明](https://github.com/XIA-J-B/ParallelTranslation/releases/latest) · [官网试读](https://xia-j-b.github.io/ParallelTranslation/)

<!-- release-notes:start -->

## 最新版本 · [v0.1.31](https://github.com/XIA-J-B/ParallelTranslation/releases/tag/v0.1.31)

更新后，如果已有可用的译文 PDF，打开论文就能在原来的位置继续读。新版排好后会自动切换。文档库从最近导入的论文开始后台重排，复用已有译文。打开仍在排队的论文会优先处理。

译文 PDF 修复了图注公式重复出现的问题。变量、上下标和等式会排在对应的译文位置，确实无法对应的公式仍会保留原式供核对。更新后可直接用已保存的译文重新排版。

部分旧译稿中以竖线分隔的表格可以按原行列排入，包括首列表头留空的表格。排版会核对相邻单元格和脚注链接。原文和译文中能够准确对应的重复术语与括号编号，也能保留原来的粗体或斜体。

阅读器工具栏分别显示整块保留原文、局部公式待核和仅样式待核的数量。点开后可以查看原因并定位到对应位置。尚未翻译的段落继续单独显示。

Windows 登录支持系统信任的代理证书。临时连接失败时会自动重试一次，仍有问题时会给出更具体的检查提示。

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
