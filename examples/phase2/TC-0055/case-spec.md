# TC-0055: 保存处理中禁用重复提交、取消和关闭

Start: editor

Environment: delayed_save
Data: {"llms.enabled": true, "llms.source": "system"}

## Steps

- S1: fill txt.overview = 'phase2-save-in-progress'
- S2: click txt.save
- S3: click ?save.repeat_attempt
- S4: click ?cancel.while_saving
- S5: click ?close.while_saving
- S6: wait txt.saved

## Excel expectations

- A1 after S2: 1. 保存按钮立即变为不可用并显示“保存中…”。
- A2 after S5: 2. 重复保存、取消和关闭均不能执行，弹窗保持显示。
- A3 after S6: 3. 保存成功后显示提示并关闭弹窗，全程只产生一次可见保存结果。

## Business questions

