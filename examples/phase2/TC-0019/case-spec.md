# TC-0019: 往返切换内容来源保留两侧已填内容且不覆盖自定义文本

Start: editor

Environment: 
Data: {"llms.enabled": true, "llms.overview": "phase2-original-overview", "llms.custom": "phase2-original-custom", "llms.extras": [{"name": "phase2-field", "value": "phase2-value"}], "llms.source": "system"}

## Steps

- S1: click txt.custom
- S2: fill txt.content = 'phase2-edited-custom'
- S3: click txt.system
- S4: click txt.custom

## Excel expectations

- A1 after S1: 1. 文本域显示已有自定义内容，不被自动生成内容覆盖。
- A2 after S3: 2. 系统生成区域仍显示原网站概述和扩展字段。
- A3 after S4: 3. 文本域显示刚修改的自定义内容。

## Business questions

