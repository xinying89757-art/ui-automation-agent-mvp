# TC-0033: FAQ有5条时全部按列表顺序输出

Start: editor

Environment: public_frontend
Data: {"llms.enabled": true, "llms.source": "system", "faq.count": 5}

## Steps

- S1: click txt.save
- S2: open ?public.llms.faq

## Excel expectations

- A1 after S1: 1. 页面显示保存成功提示。
- A2 after S2: 2. FAQ模块显示5条问答且顺序与FAQ列表一致，每条均使用问题和答案两行格式。

## Business questions

