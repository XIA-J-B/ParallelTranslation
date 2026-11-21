# 页间 Parallel

页间是 Windows 10/11 x64 上的论文对照阅读工具。打开论文后，可以并排阅读原文和译文，选中一句话向 AI 提问，或在页旁写下批注，导出给同事回复。

[![最新 Windows 版本](https://img.shields.io/github/v/release/XIA-J-B/ParallelTranslation?label=Windows)](https://github.com/XIA-J-B/ParallelTranslation/releases/latest)

**[下载 Windows 安装包](https://xia-j-b.github.io/ParallelTranslation/#download)** · [最新版本与更新说明](https://github.com/XIA-J-B/ParallelTranslation/releases/latest) · [官网试读](https://xia-j-b.github.io/ParallelTranslation/)

<!-- release-notes:start -->

## 最新版本 · [v0.1.40](https://github.com/XIA-J-B/ParallelTranslation/releases/tag/v0.1.40)

修复了部分论文翻译停在 99%、点击「继续翻译」仍反复失败的问题。页间现在用内置符号库辨认图中的变量和单位。遇到模糊字形时，会保留原图并标为「待核对」，其余内容仍可翻译、阅读和导出。已保存的译文会保留。

要核对图中某一处，可以直接定位原图，也可以自己圈选，再到「图内文字设置」确认它是符号或公式。判断可以撤销。以后遇到相似字形时，页间会提示你参考之前的判断，由你决定是否采用。

文档库现在为每篇正在处理的论文显示进度条，长篇名会自动换行。补译时能看到本批已译多少段，排版时能看到已处理多少页。最后一页处理完后，还会显示正在合并或保存 PDF。

打开正在处理的论文，阅读区也会显示进度。等待期间可以先读上一版 PDF 或已保存的段落译文。新版就绪后会在原来的阅读位置切换。如果论文内容也有变化，点击「重新打开本篇」即可查看。

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
