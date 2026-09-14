FROM localhost/arena-offline-base/python:bundle
WORKDIR /app
COPY project/apps/api/requirements.txt .
RUN --mount=type=bind,source=python/api,target=/wheels \
    pip install --no-index --find-links=/wheels --no-cache-dir -r requirements.txt \
    && pip check && useradd --create-home --uid 10001 arena
COPY project/apps/api/app ./app
RUN mkdir -p /data && chown arena:root /data && chmod g=u /data
USER arena
ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
