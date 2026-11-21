# Multi-stage: build the Vite SPA, serve static via nginx (which also proxies the API).
FROM node:26-slim@sha256:abe7e5a82b61a8ef67b315b85497c9e65173387ccf2f4a029248184b8e020be5 AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# Reproducible install from the lockfile (fails loudly if they drift).
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.31-alpine@sha256:b50897d5c7b1aa08067c3d90c5e8b3e47ec4e3c91c91446f67820228f7b41e34
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

# Base images are pinned by digest as well as tag: a tag can be re-pushed, so a rebuild
# that silently picks up a different image is indistinguishable from a clean one. Dependabot
# bumps these (plan M2.4) and the digest in the diff is the review.
