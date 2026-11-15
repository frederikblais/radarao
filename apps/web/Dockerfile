# Contexte de build : apps/web
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -D -u 10001 radarao
COPY --from=build --chown=radarao /app/.next/standalone ./
COPY --from=build --chown=radarao /app/.next/static ./.next/static
COPY --from=build --chown=radarao /app/public ./public
USER 10001
EXPOSE 3000
# API_INTERNAL_URL (ex. http://api:8000) est lu au démarrage pour le proxy /api.
CMD ["node", "server.js"]
