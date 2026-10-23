# TC-0055: 保存处理中禁用重复提交、取消和关闭

Start: editor

Environment:
Data: {"llms.enabled": true, "llms.source": "system"}

## Steps

- S1: fill txt.overview = 'phase2-save-in-progress'
- S2: observe txt.saved
- S3: network_delay network.llms.save = '12000'
- S4: double_click txt.save
- S5: attempt_click txt.cancel
- S6: attempt_click txt.close
- S7: network_release network.llms.save
- S8: wait txt.saved

## Excel expectations

- A1 after S4: 1. 保存按钮立即变为不可用并显示“保存中…”。
- A2 after S6: 2. 重复保存、取消和关闭均不能执行，弹窗保持显示。
- A3 after S8: 3. 保存成功后显示提示并关闭弹窗，全程只产生一次可见保存结果。

## Business questions

