FROM localhost/arena-offline-base/node:bundle AS build
WORKDIR /app
COPY project/apps/web/package*.json ./
RUN --mount=type=bind,source=node/cache,target=/offline-cache \
    cp -a /offline-cache /tmp/npm-cache \
    && npm ci --offline --cache /tmp/npm-cache --no-audit --no-fund
COPY project/apps/web/ ./
RUN npm run build

FROM localhost/arena-offline-base/nginx:bundle
COPY --from=build /app/dist /usr/share/nginx/html
COPY project/apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 project/apps/web/20-arena-resolver.sh /docker-entrypoint.d/20-arena-resolver.sh
RUN sed -i 's/listen 80;/listen 8080;/' /etc/nginx/conf.d/default.conf \
    && sed -i '/^user /d; s@/var/run/nginx.pid@/tmp/nginx.pid@; s@/run/nginx.pid@/tmp/nginx.pid@' /etc/nginx/nginx.conf \
    && chgrp -R 0 /etc/nginx /var/cache/nginx /var/log/nginx \
    && chmod -R g=u /etc/nginx /var/cache/nginx /var/log/nginx
USER 10001
EXPOSE 8080
