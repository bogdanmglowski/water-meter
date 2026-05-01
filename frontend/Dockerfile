FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 docker-entrypoint.d/40-print-urls.sh /docker-entrypoint.d/40-print-urls.sh
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
