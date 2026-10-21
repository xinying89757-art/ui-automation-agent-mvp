# TC-0048: 自定义内容为空或仅空格时被拦截

Start: editor

Environment: 
Data: {"llms.enabled": true, "llms.source": "custom"}

## Steps

- S1: fill txt.content = ''
- S2: click txt.save
- S3: fill txt.content = '  \n  '
- S4: click txt.save
- S5: fill txt.content = 'x'

## Excel expectations

- A1 after S2: 1. 文本域下方显示“请填写自定义 llms.txt 内容”，弹窗保持打开。
- A2 after S4: 2. 文本域下方仍显示相同错误，弹窗保持打开。
- A3 after S5: 3. 必填错误消失，保存按钮可用。

## Business questions

