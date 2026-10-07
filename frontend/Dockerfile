FROM node:22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Final image is Caddy with the built static files baked in at /srv.
FROM caddy:2
COPY --from=build /app/dist /srv
