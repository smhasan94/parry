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

# nginx:alpine ships an entrypoint script that runs envsubst on every file in
# /etc/nginx/templates/ at container start, writing the result to
# /etc/nginx/conf.d/. NGINX_ENVSUBST_FILTER limits substitution to just our
# two variables so nginx's own $host/$uri/etc are left alone.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Run as non-root — nginx:alpine includes an 'nginx' user (uid 101).
# The entrypoint needs to write envsubst output to /etc/nginx/conf.d/,
# the worker cache to /var/cache/nginx, and the pid file to /run
# (alpine's /var/run is a symlink to /run, and chown -R on the symlink
# does not propagate to the target — chown /run directly).
RUN chown -R nginx:nginx /etc/nginx/conf.d /var/cache/nginx /run && \
    chmod -R 755 /etc/nginx/conf.d
USER nginx

ENV BACKEND_URL=http://backend:8000
ENV PORT=80
ENV NGINX_ENVSUBST_FILTER="^(PORT|BACKEND_URL)$"

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
