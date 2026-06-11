# Deployment Guide

This guide provides high-level steps for deploying the PRIIS V1.5
prototype. The instructions assume you are familiar with container
technologies, environment variables, and cloud hosting platforms.

## 1. Prepare Secrets and Configuration

1. **Database credentials** – Ensure that the target PostgreSQL/PostGIS
   instance is running and accessible from your deployment environment.
2. **Environment variables** – Create a `.env` file or use your
   hosting provider's secret manager to store sensitive values such as
   `DATABASE_URL`, API keys for map tiles, and LLM providers.
3. **Map tiles** – Obtain a MapLibre style URL or host your own
   vector tiles. Update the `style` property in
   `frontend/src/components/MapPane.tsx` if necessary.
4. **Vector/LLM services** – If using a vector store or external LLM,
   set up those services and store their connection details as
   environment variables.

## 2. Build the Images

### Backend

Build the backend container image:

```bash
docker build -t priis-backend ./backend
```

### Frontend

Build the frontend for production:

```bash
cd frontend
npm install
npm run build
```

The built assets will be in `frontend/dist`. Serve these files using
your web server of choice (e.g., Nginx, Caddy, or a static hosting
service). Alternatively, embed a simple static file server in your
backend or use a containerized Nginx image.

## 3. Configure Infrastructure

1. **Database** – Provision a PostgreSQL instance with the PostGIS
   extension. Run `database/schema.sql` to create tables and
   `database/seed_data.sql` to insert sample data. Grant
   appropriate permissions to the service account.
2. **App hosting** – Use a platform such as AWS (ECS/EKS/Fargate),
   Render, Railway, Fly.io, Heroku, or your on‑premise environment
   to run the containers. Expose ports 8000 (backend) and 80/443
   (frontend) as needed.
3. **Networking** – Configure network rules and firewalls to allow
   traffic only from trusted sources. Use HTTPS for all external
   endpoints.
4. **Secrets** – Use your hosting provider’s secret management system
   to inject environment variables. Do not bake secrets into the
   container images.

## 4. Deploy Containers

Deploy the backend container with the necessary environment:

```bash
docker run -d \
  --name priis-backend \
  -e DATABASE_URL=postgresql://user:password@db-host:5432/priis \
  -p 8000:8000 \
  priis-backend
```

Serve the frontend build directory behind an HTTP server. For example,
using Nginx:

```nginx
server {
    listen 80;
    server_name your.domain.com;

    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000/;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

Replace `your.domain.com` and adjust the `proxy_pass` URL to match
your backend service.

## 5. Monitor and Iterate

Once deployed, monitor logs, performance, and resource usage. Use
continuous integration and deployment pipelines (e.g., GitHub
Actions) to automate builds and tests. Collect feedback from users
and analysts to refine the system.