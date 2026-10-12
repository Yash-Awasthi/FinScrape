# Multi-stage: build the Vite SPA, serve static via nginx (which also proxies the API).
FROM node:26-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# Reproducible install from the lockfile (fails loudly if they drift).
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.31-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
