# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS build
WORKDIR /workspace

ARG VITE_GATEWAY_URL
ENV VITE_GATEWAY_URL=${VITE_GATEWAY_URL}

ENV COREPACK_ENABLE_STRICT=0
RUN corepack enable

COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps ./apps
COPY packages ./packages

RUN pnpm install --frozen-lockfile
RUN pnpm -C apps/ui build

FROM nginx:1.27-alpine
COPY --from=build /workspace/apps/ui/dist /usr/share/nginx/html
COPY apps/ui/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
