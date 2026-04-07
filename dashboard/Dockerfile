# ── Build stage ──
FROM node:20-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ── Production stage: serve static files with nginx ──
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# Templated nginx config — BACKEND_URL is substituted at container start.
# Defaults to docker-compose service name; override on Railway/other hosts.
ENV BACKEND_URL=http://backend:8000
ENV PORT=80

RUN printf '%s\n' \
  'server {' \
  '  listen ${PORT};' \
  '  root /usr/share/nginx/html;' \
  '  index index.html;' \
  '  location / {' \
  '    try_files $uri $uri/ /index.html;' \
  '  }' \
  '  location /api {' \
  '    proxy_pass ${BACKEND_URL};' \
  '    proxy_set_header Host $host;' \
  '    proxy_set_header X-Real-IP $remote_addr;' \
  '    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
  '    proxy_set_header X-Forwarded-Proto $scheme;' \
  '  }' \
  '}' > /etc/nginx/templates/default.conf.template

# nginx:alpine includes envsubst and auto-templates files in /etc/nginx/templates/
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
