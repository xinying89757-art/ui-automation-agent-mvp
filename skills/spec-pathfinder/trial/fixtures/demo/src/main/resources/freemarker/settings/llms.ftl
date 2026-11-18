<#-- 模拟源码：只证明解析行为，不证明真实产品行为。 -->
<form id="llmsForm" action="/settings/llms/save" method="post">
  <label for="enabled">开启 llms.txt</label>
  <input id="enabled" name="enabled" type="checkbox" value="true">
  <input id="summary" name="siteSummary" value="${summary!''}">
  <button data-testid="save-llms" type="submit">保存</button>
  <a href="/files/remove?id=1">删除</a>
</form>
