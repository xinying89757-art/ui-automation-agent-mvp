# TC-0016: 悬停问号显示自动生成规则说明

Start: editor

Environment: 
Data: {"llms.enabled": true, "llms.source": "system"}

## Steps

- S1: hover txt.rule.help
- S2: assert txt.rules

## Excel expectations

- A1 after S1: 1. 页面浮出说明面板。
- A2 after S2: 2. 面板显示“自动生成规则”“文件按以下模块顺序生成，各模块取值规则如下：”，并列出网站标题、网站概述、扩展内容字段、Contact Us、Social Media、Website Language Versions、Website Navigation、Product Category和FAQ九项说明。

## Business questions

