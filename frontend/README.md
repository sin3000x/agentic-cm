# Agentic CM Frontend

供应链异常 Case 的 React + TypeScript 演示工作台。

```bash
npm ci
npm run dev
```

默认连接 `http://localhost:8000`。如需修改，复制 `.env.example` 为 `.env.local` 并设置 `NEXT_PUBLIC_API_BASE_URL`。

本地监听地址和端口也通过 `.env.local` 配置：

```dotenv
AGENTIC_CM_WEB_HOST=127.0.0.1
AGENTIC_CM_WEB_PORT=3000
```

如需允许局域网访问，可将监听地址改为 `0.0.0.0`。端口必须是 `1–65535` 的整数；端口被占用时服务会直接报错，不会静默切换到其他端口。
