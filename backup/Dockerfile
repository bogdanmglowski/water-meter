FROM postgres:17

WORKDIR /app

COPY docker-run.sh /app/docker-run.sh
RUN chmod +x /app/docker-run.sh

CMD ["/app/docker-run.sh"]
