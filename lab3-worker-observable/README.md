## Steps

### Start infra (DB, messagebus, cache) from docker-compose

```sh
docker compose up database messagebus cache jaeger
```

### Start mizinga app from package.json
```Sh
run dev from package.json file in mizinga apps
```

### Start mailhog
```sh
docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog
```

### Install python deps
```sh
pip install -r ~\lab3-worker-observable\requirements.txt
```

### Start worker
```sh
python ~\lab3-worker-observable\worker.py
```