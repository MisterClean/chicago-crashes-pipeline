FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . ./
ARG BACKEND_URL=http://backend:8000
ARG NEXT_PUBLIC_BASEMAP_URL=https://basemaps.cartocdn.com/gl/positron-gl-style/style.json
ENV BACKEND_URL=$BACKEND_URL NEXT_PUBLIC_BASEMAP_URL=$NEXT_PUBLIC_BASEMAP_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build
FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3001
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3001
CMD ["node","server.js"]
