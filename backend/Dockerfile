FROM rust:1.88-bookworm AS build

WORKDIR /app

COPY Cargo.toml Cargo.lock ./
COPY migrations ./migrations
COPY src ./src

RUN cargo build --release --locked

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home appuser

WORKDIR /app

COPY --from=build /app/target/release/water-meter-backend /usr/local/bin/water-meter-backend

USER appuser

EXPOSE 8080

CMD ["water-meter-backend"]
