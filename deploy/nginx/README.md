## Nginx reverse proxy (EC2) quick setup

### Goal
- Expose dashboard on **port 80** (and later 443)
- Keep the app container bound to **localhost:8000** only
- Proxy WebSocket endpoint `/ws`

### 1) Run the app container (bind to localhost only)
```bash
docker rm -f quant-trading-dashboard || true
docker run -d --name quant-trading-dashboard \
  --env-file /home/ubuntu/kis-api/config/.env \
  -v /home/ubuntu/kis-api/config:/root/kis-api/config:ro \
  -v /home/ubuntu/kis-api/token:/root/kis-api/token:rw \
  -p 127.0.0.1:8000:8000 \
  <YOUR_DOCKER_IMAGE>:latest
```

### 2) Install nginx on Ubuntu
```bash
sudo apt-get update
sudo apt-get install -y nginx
```

### 3) Enable this site config
Copy `quant-dashboard.conf` to your server and place it as:
```bash
sudo cp quant-dashboard.conf /etc/nginx/sites-available/quant-dashboard
sudo ln -sf /etc/nginx/sites-available/quant-dashboard /etc/nginx/sites-enabled/quant-dashboard
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### 4) Security Group inbound rules
- Open **TCP 80** (and later 443), close 8000 if you want.

### Test
```bash
curl -I http://127.0.0.1/
curl -I http://<EC2_PUBLIC_IP>/
```

