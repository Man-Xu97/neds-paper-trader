# Neds Paper Trader — 免费 iPhone 观察版

本仓库仅进行赛马、赛狗赛事**只读观察**，不进行真实投注，也**尚未**实现自动虚拟下注或赛后结算。

## 使用方法
1. 在仓库 Settings → Secrets and variables → Actions → New repository secret，添加 `PUNTERSEDGE_API_KEY`。不要提交到仓库文件。
2. 在 Actions 中启用工作流，并手动运行 **Neds paper research scan** 一次。
3. 在 Settings → Pages → Build and deployment 中选择 **Deploy from a branch**，分支 `main`，目录 `/docs`。
4. 页面地址预计为 https://man-xu97.github.io/neds-paper-trader/ ，须待 GitHub Pages 部署成功后才可访问。

GitHub Actions 计划每六小时执行一次，GitHub 可能延迟或跳过运行。免费额度、数据源字段和覆盖范围需通过首次运行验证。

**安全提示：** 这是公开仓库，docs/status.json 是公开数据；绝不放入 API Key、Neds 密码或个人资料。