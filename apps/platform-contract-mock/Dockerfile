FROM node:22.22.0-alpine AS dependencies

RUN corepack enable && corepack prepare pnpm@11.9.0 --activate
WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/platform-contract-mock/package.json apps/platform-contract-mock/package.json
RUN pnpm install --frozen-lockfile --prod --filter @wotao/platform-contract-mock

FROM node:22.22.0-alpine AS runtime

ENV HOST=0.0.0.0 \
    PORT=4011 \
    NODE_ENV=production
WORKDIR /workspace

COPY --from=dependencies /workspace/node_modules ./node_modules
COPY --from=dependencies /workspace/apps/platform-contract-mock/node_modules ./apps/platform-contract-mock/node_modules
COPY apps/platform-contract-mock ./apps/platform-contract-mock
COPY packages/contracts/platform ./packages/contracts/platform

USER node
EXPOSE 4011
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:4011/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "apps/platform-contract-mock/src/server.mjs"]
