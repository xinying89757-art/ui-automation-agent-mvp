# TC-0036: 保存配置后无需发布即可立即更新公开文件

Start: editor

Environment:
Data: {"llms.enabled": true, "llms.source": "system"}

## Steps

- S1: fill txt.overview = 'phase2-immediate-public-overview'
- S2: click txt.save
- S3: defer_public public.llms.immediate

## Excel expectations

- A1 after S2: 1. 页面显示“llms.txt 配置已保存”并关闭弹窗。
- A2 after S3: 2. 公开文件立即显示新的网站概述。

## Business questions

