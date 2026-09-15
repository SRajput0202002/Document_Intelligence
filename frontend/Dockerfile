# =============================================================================
# Stage 1: Build
# =============================================================================
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and config needed for build
COPY . .

# Optional: set API URL at build time (NEXT_PUBLIC_* are inlined at build)
ARG NEXT_PUBLIC_API_URL=https://idp-new-be.whitewave-bde6c83a.eastus.azurecontainerapps.io
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# =============================================================================
# Stage 2: Production (runner)
# =============================================================================
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001

# Production dependencies only
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Copy built app from builder
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.js ./

EXPOSE 3001

CMD ["npm", "start"]
