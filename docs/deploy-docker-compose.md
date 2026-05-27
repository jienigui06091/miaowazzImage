# Docker Compose Server Deployment

This guide deploys `miaowazzImage` on a Linux server with Docker Compose. It assumes production data is stored in PostgreSQL, Redis, and Cloudflare R2.

Do not commit your real `.env` file. It contains database passwords, Redis passwords, and R2 keys.

## 1. Install Required Tools

Check whether Docker, Docker Compose, and Git are installed:

```bash
docker --version
docker compose version
git --version
```

Install Docker if needed:

```bash
curl -fsSL https://get.docker.com | bash
sudo systemctl enable docker
sudo systemctl start docker
```

## 2. Clone The Repository

```bash
sudo mkdir -p /opt/miaowazzImage
sudo chown -R "$USER":"$USER" /opt/miaowazzImage
git clone https://github.com/jienigui06091/miaowazzImage.git /opt/miaowazzImage
cd /opt/miaowazzImage
```

## 3. Create `.env`

Create `/opt/miaowazzImage/.env`:

```env
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://postgres:your_postgres_password@your_postgres_host:15432/chatgpt2api

REDIS_URL=redis://:your_redis_password@your_redis_host:16379/0

MIAOWAZZIMAGE_AUTH_KEY=change_me_to_a_long_random_secret
APP_JWT_SECRET=change_me_to_another_long_random_secret
APP_ADMIN_USERNAME=admin
APP_ADMIN_PASSWORD=change_me_before_deploy
APP_ACCESS_TOKEN_TTL_SECONDS=604800

MIAOWAZZIMAGE_BASE_URL=https://your-domain.com

R2_ENDPOINT_URL=https://your_account_id.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your_r2_access_key_id
R2_SECRET_ACCESS_KEY=your_r2_secret_access_key
R2_REGION=auto
R2_BUCKET=your_bucket
R2_PUBLIC_BASE_URL=
```

Notes:

- Use `STORAGE_BACKEND=postgres` in production.
- `DATABASE_URL` must point to the production PostgreSQL database.
- If you do not have a domain yet, temporarily set `MIAOWAZZIMAGE_BASE_URL=http://server_ip:8000`.
- Keep the R2 bucket private. The backend controls image access.

## 4. Create `docker-compose.prod.yml`

Create `/opt/miaowazzImage/docker-compose.prod.yml`:

```yaml
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    image: miaowazzimage:prod
    container_name: miaowazzimage
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "8000:80"
    volumes:
      - ./data:/app/data
      - ./config.json:/app/config.json
```

If Nginx will proxy traffic, bind the app to localhost only:

```yaml
ports:
  - "127.0.0.1:8000:80"
```

## 5. Start The Service

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Check status and logs:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail 100
```

Open:

```text
http://server_ip:8000
```

If a domain and HTTPS are configured:

```text
https://your-domain.com
```

## 6. Optional Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Enable HTTPS with Certbot:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## 7. Data Locations

Primary data is stored in PostgreSQL:

- users, quota records, API keys, and user account bindings
- account pool records
- runtime settings, registration settings, CPA/Sub2API settings, and backup state
- image records, operation logs, and image conversation history

Cloudflare R2 stores image files. PostgreSQL stores image metadata and access control records.

The local `data/` volume is still kept for runtime cache and compatibility fallback. Keep it mounted.

## 8. Common Operations

Update:

```bash
cd /opt/miaowazzImage
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Restart:

```bash
docker compose -f docker-compose.prod.yml restart
```

View logs:

```bash
docker compose -f docker-compose.prod.yml logs -f --tail 100
```

Stop:

```bash
docker compose -f docker-compose.prod.yml down
```

Check resource usage:

```bash
docker stats miaowazzimage --no-stream
```
