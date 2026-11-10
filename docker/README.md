# Docker setup

The container currently provides a minimal Python 3.12 environment. From the repository root, with Docker Engine and Compose installed:

```bash
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml run --rm python
```

The `data/` and `outputs/` directories are mounted from the host. No credentials or datasets are copied into the image. The TIGGE download and processing workflow has not yet been implemented in this container.
