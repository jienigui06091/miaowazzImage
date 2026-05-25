# miaowazzImage

`miaowazzImage` 是一个面向内部运营的多用户图片生成系统，基于原 ChatGPT 图片代理能力二次开发。系统提供统一登录、用户额度、API Key、号池管理、操作日志、图片管理、PostgreSQL 数据存储、Redis 支持以及 Cloudflare R2 图片存储。

## 功能

- 用户名密码登录，按角色区分管理员和普通用户。
- 普通用户可注册，默认启用，初始图片生成额度为 0。
- 管理员可管理用户、分配生成额度、维护号池。
- 用户每生成一张图片扣减 1 次额度，失败时自动返还。
- 用户可在后台生成自己的 API Key。
- 图片存储支持 Cloudflare R2，访问通过后端签名代理控制权限。
- 管理员可查看全部图片和日志，普通用户只能访问自己的图片。
- 日志、图片索引、图片标签等运营数据入库，删除采用软删除。

## 本地运行

```bash
docker compose -f docker-compose.local.yml up -d --build
```

默认访问地址：

```text
http://127.0.0.1:8000
```

环境变量可参考 `.env.example`。生产环境必须替换 `MIAOWAZZIMAGE_AUTH_KEY`、`APP_JWT_SECRET`、数据库、Redis 和 R2 配置。

## 常用配置

- `MIAOWAZZIMAGE_AUTH_KEY`：兼容旧密钥登录配置，也是首次创建默认管理员时的备用密码来源。
- `APP_ADMIN_USERNAME`：默认管理员用户名，默认 `admin`。
- `APP_ADMIN_PASSWORD`：默认管理员初始密码，不设置时使用 `MIAOWAZZIMAGE_AUTH_KEY`。
- `APP_JWT_SECRET`：登录 JWT 签名密钥，生产环境必须使用长随机值。
- `DATABASE_URL`：PostgreSQL 或 SQLite 连接串。
- `REDIS_URL`：Redis 连接串。
- `R2_ENDPOINT_URL`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`：Cloudflare R2 配置。

## API

图片生成接口兼容 OpenAI 风格：

```text
POST /v1/images/generations
POST /v1/images/edits
GET  /v1/models
```

前端运营接口位于 `/api/*`，包括用户管理、API Key、图片任务、图片管理和日志管理。

## 部署说明

正式部署建议：

- 使用 PostgreSQL 作为主数据库。
- 使用 Redis 做缓存和后续队列扩展。
- R2 bucket 保持私有，由后端代理图片访问。
- 使用 HTTPS 域名并设置 `MIAOWAZZIMAGE_BASE_URL`。
- 不要提交 `.env`、真实数据库密码、Redis 密码、R2 密钥。
