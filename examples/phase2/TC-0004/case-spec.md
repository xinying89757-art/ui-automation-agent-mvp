# TC-0004: 从设置面板打开管理txt文件并显示默认页签

Start: editor

Environment: 
Data: {}

## Steps

- S1: open settings
- S2: click txt.entry
- S3: assert txt.dialog

## Excel expectations

- A1 after S1: 1. 网站设置面板显示“管理txt文件”。
- A2 after S2: 2. 页面打开标题为“管理txt文件”的弹窗。
- A3 after S3: 3. 默认选中“llms.txt”页签，左侧显示“取消”，右侧显示“保存”。

## Business questions

